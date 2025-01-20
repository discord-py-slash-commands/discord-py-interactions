import audioop
import shutil
import subprocess
import threading
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Union, Optional, TYPE_CHECKING

__all__ = ("Audio", "AudioBuffer", "AudioVolume", "BaseAudio", "RawInputAudio")

from interactions.client.const import get_logger
from interactions.api.voice.opus import Encoder
from interactions.client.utils import FastJson

if TYPE_CHECKING:
    from interactions.api.voice.recorder import Recorder


class RawInputAudio:
    decoded: bytes
    """The decoded audio"""
    pcm: bytes
    """The raw PCM audio"""
    sequence: int
    """The audio sequence"""
    audio_timestamp: int
    """The current timestamp for this audio"""
    timestamp_ns: float
    """The time this audio was received, in nanoseconds"""
    timestamp: float
    """The time this audio was received, in seconds"""
    ssrc: int
    """The source of this audio"""
    _recoder: "Recorder"
    """A reference to the audio recorder managing this object"""

    def __init__(self, recorder: "Recorder", data: bytes) -> None:
        self.decoded: bytes = b""
        self._recorder = recorder
        self.timestamp_ns = time.monotonic_ns()
        self.timestamp = self.timestamp_ns / 1e9
        self.pcm = b""

        self.ingest(data)

    def ingest(self, data: bytes) -> bytes | None:
        data = bytearray(data)
        header = data[:12]

        decrypted: bytes = self._recorder.decrypt(header, data[12:])
        self.ssrc = int.from_bytes(header[8:12], byteorder="big")
        self.sequence = int.from_bytes(header[2:4], byteorder="big")
        self.audio_timestamp = int.from_bytes(header[4:8], byteorder="big")

        if not self._recorder.recording_whitelist or self.user_id in self._recorder.recording_whitelist:
            # noinspection PyProtectedMember
            if decrypted[0] == 0xBE and decrypted[1] == 0xDE:
                # rtp header extension, remove it
                header_ext_length = int.from_bytes(decrypted[2:4], byteorder="big")
                decrypted = decrypted[4 + 4 * header_ext_length :]
            self.decoded = self._recorder.get_decoder(self.ssrc).decode(decrypted)
            return self.decoded

    @property
    def user_id(self) -> Optional[int]:
        """The ID of the user who made this audio."""
        while not self._recorder.state.ws.user_ssrc_map.get(self.ssrc):
            time.sleep(0.05)
        return self._recorder.state.ws.user_ssrc_map.get(self.ssrc)["user_id"]


class AudioBuffer:
    def __init__(self) -> None:
        self._buffer = bytearray()
        self._lock = threading.Lock()
        self.initialised = threading.Event()

    def __len__(self) -> int:
        return len(self._buffer)

    def extend(self, data: bytes) -> None:
        """
        Extend the buffer with additional data.

        Args:
            data: The data to add

        """
        with self._lock:
            self._buffer.extend(data)

    def read(self, total_bytes: int, *, pad: bool = True) -> bytearray:
        """
        Read `total_bytes` bytes of audio from the buffer.

        Args:
            total_bytes: Amount of bytes to read.
            pad: Whether to pad incomplete frames with 0's.

        Returns:
            Desired amount of bytes

        Raises:
            ValueError: If `pad` is False and the buffer does not contain enough data.

        """
        with self._lock:
            view = memoryview(self._buffer)
            self._buffer = bytearray(view[total_bytes:])
            data = bytearray(view[:total_bytes])
            if 0 < len(data) < total_bytes:
                if pad:
                    # pad incomplete frames with 0's
                    data.extend(b"\0" * (total_bytes - len(data)))
                else:
                    raise ValueError(
                        f"Buffer does not contain enough data to fulfill request {len(data)} < {total_bytes}"
                    )
            return data

    def read_max(self, total_bytes: int) -> bytearray:
        """
        Read up to `total_bytes` bytes of audio from the buffer.

        Args:
            total_bytes: Maximum amount of bytes to read.

        Returns:
            Desired amount of bytes

        Raises:
            EOFError: If the buffer is empty.

        """
        with self._lock:
            if len(self._buffer) == 0:
                raise EOFError("Buffer is empty")
            view = memoryview(self._buffer)
            self._buffer = bytearray(view[total_bytes:])
            return bytearray(view[:total_bytes])


class BaseAudio(ABC):
    """Base structure of the audio."""

    locked_stream: bool
    """Prevents the audio task from closing automatically when no data is received."""
    needs_encode: bool
    """Does this audio data need encoding with opus?"""
    bitrate: Optional[int]
    """Optionally specify a specific bitrate to encode this audio data with"""
    encoder: Optional[Encoder]
    """The encoder to use for this audio data"""

    def __del__(self) -> None:
        self.cleanup()

    @abstractmethod
    def cleanup(self) -> None:
        """A method to optionally cleanup after this object is no longer required."""
        ...

    @property
    def audio_complete(self) -> bool:
        """A property to tell the player if more audio is expected."""
        return False

    @abstractmethod
    def read(self, frame_size: int) -> bytes:
        """
        Reads frame_size ms of audio from source.

        Returns:
            bytes of audio

        """
        ...


class Audio(BaseAudio):
    """Audio for playing from file or URL."""

    source: str
    """The source ffmpeg should use to play the audio"""
    process: subprocess.Popen
    """The ffmpeg process to use"""
    buffer: AudioBuffer
    """The audio objects buffer to prevent stuttering"""
    buffer_seconds: int
    """How many seconds of audio should be buffered"""
    read_ahead_task: threading.Thread
    """A thread that reads ahead to create the buffer"""
    probe: bool
    """Should ffprobe be used to detect audio data?"""
    ffmpeg_args: str | list[str]
    """Args to pass to ffmpeg"""
    ffmpeg_before_args: str | list[str]
    """Args to pass to ffmpeg before the source"""

    def __init__(self, src: Union[str, Path]) -> None:
        self.source = src
        self.needs_encode = True
        self.locked_stream = False
        self.process: Optional[subprocess.Popen] = None

        self.buffer = AudioBuffer()

        self.buffer_seconds = 3
        self.read_ahead_task = threading.Thread(target=self._read_ahead, daemon=True)

        self.ffmpeg_before_args = ""
        self.ffmpeg_args = ""
        self.probe: bool = False

    def __repr__(self) -> str:
        return f"<{type(self).__name__}: {self.source}>"

    @property
    def _max_buffer_size(self) -> int:
        # 1ms of audio * (buffer seconds * 1000)
        return 192 * (self.buffer_seconds * 1000)

    @property
    def audio_complete(self) -> bool:
        """Uses the state of the subprocess to determine if more audio is coming"""
        return not self.process or self.process.poll() is not None

    def _create_process(self, *, block: bool = True) -> None:
        before = (
            self.ffmpeg_before_args if isinstance(self.ffmpeg_before_args, list) else self.ffmpeg_before_args.split()
        )

        config = {
            "sample_rate": 48000,
            "bitrate": None,
        }

        if shutil.which("ffprobe") is not None and self.probe:
            ffprobe_cmd = [
                "ffprobe",
                "-loglevel",
                "quiet",
                "-print_format",
                "json",
                "-show_streams",
                "-select_streams",
                "a:0",
                self.source,
            ]
            raw_output = subprocess.check_output(ffprobe_cmd, stderr=subprocess.DEVNULL)
            output = FastJson.loads(raw_output)

            config["sample_rate"] = int(output["streams"][0]["sample_rate"])
            config["bitrate"] = int(output["streams"][0]["bit_rate"])

            get_logger().debug(f"Detected audio data for {self.source} - {config}")

            if getattr(self, "bitrate", None) is None and self.encoder:
                self.bitrate = int(config["bitrate"] / 1024)
                self.encoder.set_bitrate(self.bitrate)

        after = self.ffmpeg_args if isinstance(self.ffmpeg_args, list) else self.ffmpeg_args.split()
        cmd = [
            "ffmpeg",
            "-i",
            self.source,
            "-f",
            "s16le",
            "-ar",
            str(config["sample_rate"]),
            "-ac",
            "2",
            "-loglevel",
            "warning",
            "pipe:1",
            "-vn",
        ]
        cmd[1:1] = before
        cmd.extend(after)

        self.process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL)
        self.read_ahead_task.start()

        if block:
            # block until some data is in the buffer
            self.buffer.initialised.wait()

    def _read_ahead(self) -> None:
        while self.process:
            if self.process.poll() is not None:
                # ffmpeg has exited, stop reading ahead
                if not self.buffer.initialised.is_set():
                    # assume this is a small file and initialise the buffer
                    self.buffer.initialised.set()

                return
            if len(self.buffer) < self._max_buffer_size:
                self.buffer.extend(self.process.stdout.read(3840))
            else:
                if not self.buffer.initialised.is_set():
                    self.buffer.initialised.set()
                time.sleep(0.1)

    def pre_buffer(self, duration: None | float = None) -> None:
        """
        Start pre-buffering the audio.

        Args:
            duration: The duration of audio to pre-buffer.

        """
        if duration:
            self.buffer_seconds = duration

        if self.process and self.process.poll() is None:
            raise RuntimeError("Cannot pre-buffer an already running process")
        # sanity value enforcement to prevent audio weirdness
        self.buffer = AudioBuffer()
        self.buffer.initialised.clear()

        self._create_process(block=False)

    def read(self, frame_size: int) -> bytes:
        """
        Reads frame_size bytes of audio from the buffer.

        Returns:
            bytes of audio

        """
        if not self.process:
            self._create_process()
        if not self.buffer.initialised.is_set():
            # we cannot start playing until the buffer is initialised
            self.buffer.initialised.wait()

        data = self.buffer.read(frame_size)

        if len(data) != frame_size:
            data = b""

        return bytes(data)

    def cleanup(self) -> None:
        """Cleans up after this audio object."""
        if self.process and self.process.poll() is None:
            self.process.kill()
            self.process.wait()


class AudioVolume(Audio):
    """An audio object with volume control"""

    _volume: float
    """The internal volume level of the audio"""

    def __init__(self, src: Union[str, Path]) -> None:
        super().__init__(src)
        self._volume = 0.5

    @property
    def volume(self) -> float:
        """The volume of the audio"""
        return self._volume

    @volume.setter
    def volume(self, value: float) -> None:
        """Sets the volume of the audio. Volume cannot be negative."""
        self._volume = max(value, 0.0)

    def read(self, frame_size: int) -> bytes:
        """
        Reads frame_size ms of audio from source.

        Returns:
            bytes of audio

        """
        data = super().read(frame_size)
        return audioop.mul(data, 2, self._volume)

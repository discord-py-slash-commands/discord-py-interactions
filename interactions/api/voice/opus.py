import array
import ctypes
import ctypes.util
import struct
import sys
from ctypes import CDLL
from enum import IntEnum
from pathlib import Path
from typing import Any

import attr

__all__ = ["Decoder", "Encoder"]

from interactions.client.const import MISSING, get_logger

c_int_ptr = ctypes.POINTER(ctypes.c_int)
c_int16_ptr = ctypes.POINTER(ctypes.c_int16)
c_float_ptr = ctypes.POINTER(ctypes.c_float)

lib_opus = MISSING


class EncoderStructure(ctypes.Structure): ...


class DecoderStructure(ctypes.Structure): ...


EncoderStructurePointer = ctypes.POINTER(EncoderStructure)
DecoderStructurePointer = ctypes.POINTER(DecoderStructure)


class OpusError(Exception):
    def __init__(self, code: int) -> None:
        msg = lib_opus.opus_strerror(code).decode("utf-8")
        super().__init__(msg)


def error_lt(result, func, args) -> int:
    if result < 0:
        raise OpusError(result)
    return result


def error_ne(result, func, args) -> int:
    # noinspection PyProtectedMember
    ret = args[-1]._obj
    if ret.value != 0:
        raise OpusError(ret.value)
    return result


@attr.s(auto_attribs=True)
class FuncData:
    arg_types: Any = attr.ib()
    res_type: Any = attr.ib()
    err_check: Any = attr.ib(default=None)


# opus consts
# from https://github.com/xiph/opus/blob/master/include/opus_defines.h


class OpusStates(IntEnum):
    OK = 0
    """No Error!"""
    BAD_ARG = -1
    """One or more invalid/out of range arguments"""
    BUFFER_TOO_SMALL = -2
    """Not enough bytes allocated in the buffer"""
    INTERNAL_ERROR = -3
    """An internal error was detected"""
    INVALID_PACKET = -4
    """The compressed data passed is corrupted"""
    UNIMPLEMENTED = -5
    """Invalid/unsupported request number"""
    INVALID_STATE = -6
    """An encoder or decoder structure is invalid or already freed"""
    ALLOC_FAIL = -7
    """Memory allocation has failed"""


class EncoderCTL(IntEnum):
    OK = 0
    APPLICATION_AUDIO = 2049
    APPLICATION_VOIP = 2048
    APPLICATION_LOWDELAY = 2051
    CTL_SET_BITRATE = 4002
    CTL_SET_BANDWIDTH = 4008
    CTL_SET_FEC = 4012
    CTL_SET_PLP = 4014
    CTL_SET_SIGNAL = 4024


class DecoderCTL(IntEnum):
    CTL_SET_GAIN = 4034
    CTL_LAST_PACKET_DURATION = 4039


class BandCTL(IntEnum):
    NARROW = 1101
    MEDIUM = 1102
    WIDE = 1103
    SUPERWIDE = 1104
    FULL = 1105


class SignalCTL(IntEnum):
    AUTO = -1000
    VOICE = 3001
    MUSIC = 3002


exported_functions: dict[str, FuncData] = {
    "opus_strerror": FuncData([ctypes.c_int], ctypes.c_char_p),
    "opus_encoder_get_size": FuncData([ctypes.c_int], ctypes.c_int),
    "opus_encoder_create": FuncData(
        [ctypes.c_int, ctypes.c_int, ctypes.c_int, c_int_ptr],
        EncoderStructurePointer,
        error_ne,
    ),
    "opus_encode": FuncData(
        [
            EncoderStructurePointer,
            c_int16_ptr,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int32,
        ],
        ctypes.c_int32,
        error_lt,
    ),
    "opus_encoder_ctl": FuncData(None, ctypes.c_int32, error_lt),
    "opus_encoder_destroy": FuncData([EncoderStructurePointer], None, None),
    "opus_decoder_get_size": FuncData([ctypes.c_int], ctypes.c_int, None),
    "opus_decoder_create": FuncData([ctypes.c_int, ctypes.c_int, c_int_ptr], DecoderStructurePointer, error_ne),
    "opus_decode": FuncData(
        [
            DecoderStructurePointer,
            ctypes.c_char_p,
            ctypes.c_int32,
            c_int16_ptr,
            ctypes.c_int,
            ctypes.c_int,
        ],
        ctypes.c_int,
        error_lt,
    ),
    "opus_decode_float": FuncData(
        [
            DecoderStructurePointer,
            ctypes.c_char_p,
            ctypes.c_int32,
            c_float_ptr,
            ctypes.c_int,
            ctypes.c_int,
        ],
        ctypes.c_int,
        error_lt,
    ),
    "opus_decoder_ctl": FuncData(None, ctypes.c_int32, error_lt),
    "opus_decoder_destroy": FuncData([DecoderStructurePointer], None, None),
    "opus_packet_get_bandwidth": FuncData([ctypes.c_char_p], ctypes.c_int, error_lt),
    "opus_packet_get_nb_channels": FuncData([ctypes.c_char_p], ctypes.c_int, error_lt),
    "opus_decoder_get_nb_samples": FuncData(
        [DecoderStructurePointer, ctypes.c_char_p, ctypes.c_int32], ctypes.c_int, error_lt
    ),
    "opus_packet_get_nb_frames": FuncData(
        [ctypes.c_char_p, ctypes.c_int],
        ctypes.c_int,
        error_lt,
    ),
    "opus_packet_get_samples_per_frame": FuncData([ctypes.c_char_p, ctypes.c_int], ctypes.c_int, error_lt),
}


def load_opus() -> CDLL:
    global lib_opus

    if not lib_opus:
        if sys.platform == "win32":
            architecture = "x64" if sys.maxsize > 32**2 else "x86"
            directory = Path(__file__).parent.parent.parent
            name = directory / f"bin/opus-{architecture}.dll"
            if not name.exists():
                raise RuntimeError("Could not find opus library.")
            name = str(name)
        else:
            name = ctypes.util.find_library("opus")

        if name is None:
            raise RuntimeError("Could not find opus library.")

        _lib_opus = ctypes.cdll.LoadLibrary(name)

        for func_name, opt in exported_functions.items():
            func = getattr(_lib_opus, func_name)

            func.restype = opt.res_type

            if opt.arg_types:
                func.argtypes = opt.arg_types

            if opt.err_check:
                func.errcheck = opt.err_check

        lib_opus = _lib_opus
    return lib_opus


class OpusConfig:
    """Shared default config for decoder and encoder."""

    def __init__(self) -> None:
        self.lib_opus = load_opus()

        self.sample_rate: int = 48000  # bps
        self.channels: int = 2
        self.frame_length: int = 20  # ms
        self.expected_packet_loss: float = 0
        self.bitrate: int = 64

    @property
    def samples_per_frame(self) -> int:
        return int(self.sample_rate / 1000 * self.frame_length)

    @property
    def delay(self) -> float:
        return self.frame_length / 1000

    @property
    def sample_size(self) -> int:
        return struct.calcsize("h") * self.channels

    @property
    def frame_size(self) -> int:
        return self.samples_per_frame * self.sample_size


class Encoder(OpusConfig):
    def __init__(self) -> None:
        super().__init__()

        self.encoder = self.create_state()
        self.set_bitrate(self.bitrate)
        self.set_fec(True)
        self.set_expected_pack_loss(self.expected_packet_loss)
        self.set_bandwidth("FULL")
        self.set_signal_type("AUTO")

    def __del__(self) -> None:
        if hasattr(self, "encoder"):
            self.lib_opus.opus_encoder_destroy(self.encoder)
            self.encoder = None

    def create_state(self) -> EncoderStructurePointer:
        """Create an opus encoder state."""
        ret = ctypes.c_int()
        return self.lib_opus.opus_encoder_create(self.sample_rate, 2, EncoderCTL.APPLICATION_AUDIO, ctypes.byref(ret))

    def set_bitrate(self, kbps: int) -> None:
        """Set the birate of the opus encoder"""
        self.bitrate = min(512, max(16, kbps))
        self.lib_opus.opus_encoder_ctl(self.encoder, EncoderCTL.CTL_SET_BITRATE, self.bitrate * 1024)

    def set_signal_type(self, sig_type: str) -> None:
        """Set the signal type to encode"""
        try:
            sig_type = SignalCTL[sig_type.upper()]
        except KeyError as e:
            raise ValueError(f"`{sig_type}` is not a valid signal type. Please consult documentation") from e

        self.lib_opus.opus_encoder_ctl(self.encoder, EncoderCTL.CTL_SET_SIGNAL, sig_type)

    def set_bandwidth(self, bandwidth_type: str) -> None:
        """Set the bandwidth for the encoder"""
        try:
            bandwidth_type = BandCTL[bandwidth_type.upper()]
        except KeyError as e:
            raise ValueError(f"`{bandwidth_type}` is not a valid bandwidth type. Please consult documentation") from e
        self.lib_opus.opus_encoder_ctl(self.encoder, EncoderCTL.CTL_SET_BANDWIDTH, bandwidth_type)

    def set_fec(self, enabled: bool) -> None:
        """Enable or disable the forward error correction"""
        self.lib_opus.opus_encoder_ctl(self.encoder, EncoderCTL.CTL_SET_FEC, int(enabled))

    def set_expected_pack_loss(self, expected_packet_loss: float) -> None:
        """Set the expected packet loss amount"""
        self.expected_packet_loss = expected_packet_loss
        self.lib_opus.opus_encoder_ctl(self.encoder, EncoderCTL.CTL_SET_PLP, self.expected_packet_loss)

    def encode(self, pcm: bytes) -> bytes:
        """Encode a frame of audio"""
        max_data_bytes = len(pcm)
        pcm = ctypes.cast(pcm, c_int16_ptr)
        data = (ctypes.c_char * max_data_bytes)()
        resp = self.lib_opus.opus_encode(self.encoder, pcm, self.samples_per_frame, data, max_data_bytes)
        return array.array("b", data[:resp]).tobytes()


class Decoder(OpusConfig):
    def __init__(self) -> None:
        super().__init__()

        self.decoder = self.create_state()

    def __del__(self) -> None:
        if hasattr(self, "decoder"):
            self.lib_opus.opus_decoder_destroy(self.decoder)
            self.decoder = None

    def create_state(self) -> DecoderStructurePointer:
        """Create an opus decoder state."""
        ret = ctypes.c_int()
        return self.lib_opus.opus_decoder_create(self.sample_rate, self.channels, ctypes.byref(ret))

    def get_packet_frame_count(self, data: bytes) -> int:
        """Get the number of frames in an encoded packet."""
        return self.lib_opus.opus_packet_get_nb_frames(data, len(data))

    def get_packet_channel_count(self, data: bytes) -> int:
        """Get the number of channels in an encoded packet."""
        return self.lib_opus.opus_packet_get_nb_channels(data)

    def get_packet_sample_rate(self, data: bytes) -> int:
        """Get the sample rate of an encoded packet."""
        return self.lib_opus.opus_packet_get_samples_per_frame(data, self.sample_rate)

    def get_last_packet_duration(self) -> int:
        """Get the duration of the last decoded packet."""
        return self.lib_opus.opus_decoder_ctl(
            self.decoder, DecoderCTL.CTL_GET_LAST_PACKET_DURATION, ctypes.byref(ctypes.c_int32())
        )

    def decode(self, data: bytes, fec: bool = False) -> bytes:
        """
        Decode an opus payload from discord.

        Args:
            data: The data to decode
            fec: Enable forward error correction

        Returns:
            The decoded bytes

        """
        try:
            if data:
                frames = self.get_packet_frame_count(data)
                channels = self.channels
                self.get_packet_sample_rate(data)
                f_size = frames * self.sample_rate
            else:
                f_size = self.get_last_packet_duration() or self.sample_rate
                channels = self.channels

            pcm = (ctypes.c_int16 * (f_size * channels * 2))()
            pcm_pointer = ctypes.cast(pcm, c_int16_ptr)

            result = self.lib_opus.opus_decode(self.decoder, data, len(data) if data else 0, pcm_pointer, f_size, fec)
            return array.array("h", pcm[: result * channels]).tobytes()
        except OpusError as e:
            get_logger().exception("Error decoding opus data frame", exc_info=e)
            return b""

from io import IOBase
from pathlib import Path
from typing import BinaryIO, Optional, Union

import attrs

__all__ = ("UPLOADABLE_TYPE", "File", "open_file")


@attrs.define(eq=False, order=False, hash=False, kw_only=False)
class File:
    """
    Representation of a file.

    Used for sending files to discord.

    """

    file: Union["IOBase", BinaryIO, "Path", str] = attrs.field(repr=True)
    """Location of file to send or the bytes."""
    file_name: Optional[str] = attrs.field(repr=True, default=None)
    """Set a filename that will be displayed when uploaded to discord. If you leave this empty, the file will be called `file` by default"""
    description: Optional[str] = attrs.field(repr=True, default=None)
    """Optional description (ALT text) for the file."""
    content_type: Optional[str] = attrs.field(repr=True, default=None)
    """Override the content type of the file. If you leave this empty, the content type will be guessed from the file's data"""

    def __attrs_post_init__(self) -> None:
        if self.file_name is None:
            if isinstance(self.file, (IOBase, BinaryIO)):
                self.file_name = "file"
            else:
                self.file_name = Path(self.file).name

    def open_file(self) -> BinaryIO | IOBase:
        """
        Opens the file.

        Returns:
            A file-like BinaryIO object.

        """
        if isinstance(self.file, (IOBase, BinaryIO, bytes)):
            return self.file
        return open(str(self.file), "rb")

    def __enter__(self) -> "File":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if isinstance(self.file, (IOBase, BinaryIO)):
            self.file.close()


UPLOADABLE_TYPE = Union[File, IOBase, BinaryIO, Path, str]


def open_file(file: UPLOADABLE_TYPE) -> BinaryIO | IOBase:
    """
    Opens the file.

    Args:
        file: The target file or path to file.

    Returns:
        A file-like BinaryIO object.

    """
    match file:
        case File():
            return file.open_file()
        case IOBase() | BinaryIO():
            return file
        case Path() | str():
            return open(str(file), "rb")
        case _:
            raise ValueError(f"{file} is not a valid file")

import datetime
from typing import Union, List, SupportsInt, Optional

import attrs

import interactions.models as models
from interactions.client.const import MISSING, Absent, DISCORD_EPOCH

__all__ = (
    "Snowflake",
    "SnowflakeObject",
    "Snowflake_Type",
    "to_optional_snowflake",
    "to_snowflake",
    "to_snowflake_list",
)


# Snowflake_Type should be used in FUNCTION args of user-facing APIs (combined with to_snowflake to sanitize input)
# For MODEL id fields, just use int as type-hinting instead;
# For attr convertors: Use int() when API-facing conversion is expected,
# use to_snowflake when user should create this object
Snowflake_Type = Union[int, str, "SnowflakeObject", SupportsInt, "Snowflake"]


def to_snowflake(snowflake: Snowflake_Type) -> "Snowflake":
    """
    Helper function to convert something into correct Discord snowflake int, gives more helpful errors Use internally to sanitize user input or in user- facing APIs (a must).

    For Discord-API - facing code, just int() is sufficient

    """
    try:
        snowflake = Snowflake(snowflake)
    except TypeError as e:
        raise TypeError(
            f"ID (snowflake) should be instance of int, str, SnowflakeObject, or support __int__. "
            f"Got '{snowflake}' ({type(snowflake)}) instead."
        ) from e
    except ValueError as e:
        raise ValueError(f"ID (snowflake) should represent int. Got '{snowflake}' ({type(snowflake)}) instead.") from e

    if 22 > snowflake.bit_length() > 64:
        raise ValueError(
            f"ID (snowflake) is not in correct Discord format! Bit length of int should be from 22 to 64 "
            f"Got '{snowflake}' (bit length {snowflake.bit_length()})"
        )

    return snowflake


def to_optional_snowflake(
    snowflake: Absent[Optional[Snowflake_Type]] = MISSING,
) -> "Optional[Snowflake]":
    if snowflake is MISSING:
        return MISSING
    return None if snowflake is None else to_snowflake(snowflake)


def to_snowflake_list(snowflakes: List[Snowflake_Type]) -> "list[Snowflake]":
    return [to_snowflake(c) for c in snowflakes]


class Snowflake(int):
    def __new__(cls, id: int) -> "Snowflake":
        return int.__new__(cls, id)

    def __iadd__(self, other) -> "Snowflake":
        return Snowflake(int(self) + other)

    def __isub__(self, other) -> "Snowflake":
        return Snowflake(int(self) - other)

    def __add__(self, other) -> "Snowflake":
        return Snowflake(int(self) + other)

    def __sub__(self, other) -> "Snowflake":
        return Snowflake(int(self) - other)

    @classmethod
    def from_datetime(cls, dt: datetime.datetime, *, high: bool = False) -> "Snowflake":
        """
        Creates a snowflake from a datetime object.

        Args:
            dt: The datetime object to create the snowflake from.
            high: Set to True if you're creating a snowflake in the discord future.

        """
        timestamp = dt.timestamp()
        ms = int(timestamp * 1000 - DISCORD_EPOCH)

        return cls((ms << 22) + (2**22 - 1 if high else 0))

    @property
    def created_at(self) -> "models.Timestamp":
        """
        Returns a timestamp representing the date-time this discord object was created.

        :Returns:
        """
        from interactions.models import (
            Timestamp,
        )  # dirty i know; but it's an unavoidable circular import

        return Timestamp.from_snowflake(self)

    @property
    def worker_id(self) -> int:
        """The internal worker ID of the snowflake."""
        return (int(self) & 0x3E0000) >> 17

    @property
    def process_id(self) -> int:
        """The internal process ID of the snowflake."""
        return (int(self) & 0x1F000) >> 12

    @property
    def increment(self) -> int:
        """
        The internal incrementation number of the snowflake.

        This value will only increment when a process has been
        generated on this snowflake, e.g. a resource.
        """
        return int(self) & 0xFFF

    def difference(self, other: Union["Snowflake", int, str]) -> datetime.timedelta:
        """
        Returns the difference between two snowflakes.

        Args:
            other: The other snowflake to compare to.

        """
        if not isinstance(other, Snowflake):
            other = Snowflake(other)
        return abs(self.created_at - other.created_at)


@attrs.define(eq=False, order=False, hash=False, slots=False)
class SnowflakeObject:
    id: Snowflake = attrs.field(repr=True, converter=Snowflake, metadata={"docs": "Discord unique snowflake ID"})

    def __eq__(self, other: "SnowflakeObject") -> bool:
        if hasattr(other, "id"):
            other = other.id
        return self.id == other

    def __ne__(self, other: "SnowflakeObject") -> bool:
        return not self.__eq__(other)

    def __hash__(self) -> int:
        return self.id << 32

    def __int__(self) -> int:
        return self.id

    @property
    def created_at(self) -> "models.Timestamp":
        """
        Returns a timestamp representing the date-time this discord object was created.

        :Returns:

        """
        return self.id.created_at

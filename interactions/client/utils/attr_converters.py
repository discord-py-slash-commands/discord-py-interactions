import inspect
import typing
import interactions
from datetime import datetime
from typing import Callable, Union, Any

from interactions.client.const import MISSING
from interactions.models.discord.timestamp import Timestamp

__all__ = ("list_converter", "optional", "timestamp_converter")


def timestamp_converter(value: Union[datetime, int, float, str]) -> Timestamp:
    """
    Converts a datetime, int, float, or str to a Timestamp object

    Args:
        value: The time value to convert

    Returns:
        A Timestamp object

    """
    try:
        if isinstance(value, str):
            return Timestamp.fromisoformat(value)
        if isinstance(value, (float, int)):
            return Timestamp.fromtimestamp(float(value))
        if isinstance(value, datetime):
            return Timestamp.fromdatetime(value)
        raise TypeError("Timestamp must be one of: datetime, int, float, ISO8601 str")
    except ValueError as e:
        interactions.const.get_logger().warning("Failed to convert timestamp", exc_info=e)
        # Should only happen if the timestamp is something stupid like 269533-01-01T00:00 - in which case we just return MISSING
        return MISSING


def list_converter(converter) -> Callable[[list], list]:
    """Converts a list of values to a list of converted values"""

    def convert_action(value: Union[list, Any]) -> list:
        if not isinstance(value, list):
            """If only one single item was passed (without a list), then we only convert that one item instead of throwing an exception."""
            return [converter(value)]

        return [converter(element) for element in value]

    return convert_action


def optional(converter: typing.Callable) -> typing.Any:
    """
    A modified version of attrs optional converter that supports both `None` and `MISSING`

    Type annotations will be inferred from the wrapped converter's, if it
    has any.

    Args:
        converter: The convertor that is used for the non-None or MISSING

    """

    def optional_converter(val) -> typing.Any:
        return val if val is None or val is MISSING else converter(val)

    sig = None
    try:
        sig = inspect.signature(converter)
    except (ValueError, TypeError):  # inspect failed
        pass
    if sig:
        params = list(sig.parameters.values())
        if params and params[0].annotation is not inspect.Parameter.empty:
            optional_converter.__annotations__["val"] = typing.Optional[params[0].annotation]
        if sig.return_annotation is not inspect.Signature.empty:
            optional_converter.__annotations__["return"] = typing.Optional[sig.return_annotation]

    return optional_converter

import inspect
import re
import typing
from enum import IntFlag
from interactions.models.discord.snowflake import Snowflake
from typing import Any, Dict, Union, Optional

import aiohttp  # type: ignore

from interactions.client.const import get_logger
import importlib.util

__all__ = ("FastJson", "get_args", "get_first_word", "response_decode", "unpack_helper")

json_mode = "builtin"

if importlib.util.find_spec("orjson"):
    import orjson as json

    json_mode = "orjson"
elif importlib.util.find_spec("ujson"):
    import ujson as json

    json_mode = "ujson"
elif importlib.util.find_spec("msgspec"):
    import msgspec.json as json

    def enc_hook(obj: Any) -> int:
        # msgspec doesnt support IntFlags or interactions.Snowflakes
        if isinstance(obj, (IntFlag, Snowflake)):
            return int(obj)
        raise TypeError(f"Object of type {type(obj)} is not JSON serializable")

    json.dumps = json.Encoder(enc_hook=enc_hook).encode
    json.loads = json.Decoder().decode

    json_mode = "msgspec"
else:
    import json  # type: ignore

get_logger().debug(f"Using {json_mode} for JSON encoding and decoding.")


_quotes = {
    '"': '"',
    "‘": "’",  # noqa RUF001
    "‚": "‛",  # noqa RUF001
    "“": "”",
    "„": "‟",
    "⹂": "⹂",
    "「": "」",
    "『": "』",
    "〝": "〞",
    "﹁": "﹂",
    "﹃": "﹄",
    "＂": "＂",  # noqa RUF001
    "｢": "｣",
    "«": "»",
    "‹": "›",  # noqa RUF001
    "《": "》",
    "〈": "〉",
}
_pending_regex = r"(1.*2|[^\t\f\v ]+)"
_pending_regex = _pending_regex.replace("1", f"[{''.join(list(_quotes.keys()))}]")
_pending_regex = _pending_regex.replace("2", f"[{''.join(list(_quotes.values()))}]")

arg_parse = re.compile(_pending_regex)
white_space = re.compile(r"\s+")


class FastJson:
    """Provides a fast way to encode and decode JSON data, using the fastest available library on the system."""

    @staticmethod
    def dumps(*args, **kwargs) -> str:
        data = json.dumps(*args, **kwargs)
        if json_mode in ("orjson", "msgspec"):
            data = data.decode("utf-8")
        return data

    @staticmethod
    def loads(*args, **kwargs) -> dict:
        return json.loads(*args, **kwargs)


async def response_decode(response: aiohttp.ClientResponse) -> Union[Dict[str, Any], str]:
    """
    Return the response text in its correct format, be it dict, or string.

    Args:
        response: the aiohttp response
    Returns:
        the response text field in its correct type

    """
    text = await response.text(encoding="utf-8")

    if response.headers.get("content-type") == "application/json":
        return FastJson.loads(text)
    return text


def get_args(text: str) -> list:
    """
    Get arguments from an input text.

    Args:
        text: The text to process
    Returns:
        A list of words

    """
    return arg_parse.findall(text)


def get_first_word(text: str) -> Optional[str]:
    """
    Get a the first word in a string, regardless of whitespace type.

    Args:
        text: The text to process
    Returns:
         The requested word

    """
    return split[0] if (split := text.split(maxsplit=1)) else None


def unpack_helper(iterable: typing.Iterable) -> list[Any]:
    """
    Unpacks all types of iterable into a list. Primarily to flatten generators.

    Args:
        iterable: The iterable to unpack
    Returns:
        A flattened list

    """
    unpack = []
    for c in iterable:
        if inspect.isgenerator(c):
            unpack += list(c)
        else:
            unpack.append(c)
    return unpack

import functools
import inspect
import re
from typing import Callable, Iterable, List, Optional, Any, Union, TYPE_CHECKING

import interactions.api.events as events
from interactions.client.const import T
from interactions.models.discord.enums import ComponentType

if TYPE_CHECKING:
    from interactions.models.discord.components import BaseComponent

__all__ = (
    "escape_mentions",
    "find",
    "find_all",
    "get",
    "get_all",
    "get_event_name",
    "get_object_name",
    "get_parameters",
    "maybe_coroutine",
    "nulled_boolean_get",
    "wrap_partial",
)

mention_reg = re.compile(r"@(everyone|here|[!&]?[0-9]{17,20})")
camel_to_snake = re.compile(r"([A-Z]+)")


def escape_mentions(content: str) -> str:
    """
    Escape mentions that could ping someone in a string.

    !!! note
        This does not escape channel mentions as they do not ping anybody

    Args:
        content: The string to escape

    Returns:
        Processed string

    """
    return mention_reg.sub("@\u200b\\1", content)


def find(predicate: Callable[[T], bool], sequence: Iterable[T]) -> Optional[T]:
    """
    Find the first element in a sequence that matches the predicate.

    ??? Hint "Example Usage:"
        ```python
        member = find(lambda m: m.name == "UserName", guild.members)
        ```
    Args:
        predicate: A callable that returns a boolean value
        sequence: A sequence to be searched

    Returns:
        A match if found, otherwise None

    """
    return next((el for el in sequence if predicate(el)), None)


def find_all(predicate: Callable[[T], bool], sequence: Iterable[T]) -> List[T]:
    """
    Find all elements in a sequence that match the predicate.

    ??? Hint "Example Usage:"
        ```python
        members = find_all(lambda m: m.name == "UserName", guild.members)
        ```
    Args:
        predicate: A callable that returns a boolean value
        sequence: A sequence to be searched

    Returns:
        A list of matches

    """
    return [el for el in sequence if predicate(el)]


def get(sequence: Iterable[T], **kwargs: Any) -> Optional[T]:
    """
    Find the first element in a sequence that matches all attrs.

    ??? Hint "Example Usage:"
        ```python
        channel = get(guild.channels, nsfw=False, category="General")
        ```

    Args:
        sequence: A sequence to be searched
        **kwargs: Keyword arguments to search the sequence for

    Returns:
        A match if found, otherwise None

    """
    if not kwargs:
        return sequence[0]

    for el in sequence:
        if any(not hasattr(el, attr) for attr in kwargs):
            continue
        if all(getattr(el, attr) == value for attr, value in kwargs.items()):
            return el
    return None


def get_all(sequence: Iterable[T], **kwargs: Any) -> List[T]:
    """
    Find all elements in a sequence that match all attrs.

    ??? Hint "Example Usage:"
        ```python
        channels = get_all(guild.channels, nsfw=False, category="General")
        ```

    Args:
        sequence: A sequence to be searched
        **kwargs: Keyword arguments to search the sequence for

    Returns:
        A list of matches

    """
    if not kwargs:
        return sequence

    matches = []
    for el in sequence:
        if any(not hasattr(el, attr) for attr in kwargs):
            continue
        if all(getattr(el, attr) == value for attr, value in kwargs.items()):
            matches.append(el)
    return matches


def wrap_partial(obj: Any, cls: Any) -> Callable:
    """
    🎁 Wraps a commands callback objects into partials.

    !!! note
        This is used internally, you shouldn't need to use this function

    Args:
        obj: The command object to process
        cls: The class to use in partials

    Returns:
        The original command object with its callback methods wrapped

    """
    if obj.callback is None or isinstance(obj.callback, functools.partial):
        return obj
    if "_no_wrap" not in getattr(obj.callback, "__name__", ""):
        obj.callback = functools.partial(obj.callback, cls)

    if getattr(obj, "error_callback", None):
        obj.error_callback = functools.partial(obj.error_callback, cls)
    if getattr(obj, "pre_run_callback", None):
        obj.pre_run_callback = functools.partial(obj.pre_run_callback, cls)
    if getattr(obj, "post_run_callback", None):
        obj.post_run_callback = functools.partial(obj.post_run_callback, cls)
    if getattr(obj, "autocomplete_callbacks", None):
        obj.autocomplete_callbacks = {k: functools.partial(v, cls) for k, v in obj.autocomplete_callbacks.items()}
    if getattr(obj, "subcommands", None):
        obj.subcommands = {k: wrap_partial(v, cls) for k, v in obj.subcommands.items()}

    return obj


def get_parameters(callback: Callable) -> dict[str, inspect.Parameter]:
    """
    Gets all the parameters of a callback.

    Args:
        callback: The callback to get the parameters of

    Returns:
        A dictionary of parameters

    """
    return {p.name: p for p in inspect.signature(callback).parameters.values()}


@functools.lru_cache(maxsize=50)
def get_event_name(event: Union[str, "events.BaseEvent"]) -> str:
    """
    Get the event name smartly from an event class or string name.

    Args:
        event: The event to parse the name of

    Returns:
        The event name

    """
    name = event

    if inspect.isclass(name) and issubclass(name, events.BaseEvent):
        name = name.__name__

    # convert CamelCase to snake_case
    name = camel_to_snake.sub(r"_\1", name).lower()
    # remove any leading underscores
    name = name.lstrip("_")
    # remove any `on_` prefixes
    name = name.removeprefix("on_")

    return name


def get_object_name(x: Any) -> str:
    """
    Gets the name of virtually any object.

    Args:
        x (Any): The object to get the name of.

    Returns:
        str: The name of the object.

    """
    try:
        return x.__name__
    except AttributeError:
        return repr(x) if hasattr(x, "__origin__") else x.__class__.__name__


async def maybe_coroutine(func: Callable, *args, **kwargs) -> Any:
    """Allows running either a coroutine or a function."""
    if inspect.iscoroutinefunction(func):
        return await func(*args, **kwargs)
    return func(*args, **kwargs)


def disable_components(*components: "BaseComponent") -> list["BaseComponent"]:
    """Disables all components in a list of components."""
    for component in components:
        if component.type == ComponentType.ACTION_ROW:
            disable_components(*component.components)
        else:
            component.disabled = True
    return list(components)


def nulled_boolean_get(data: dict[str, Any], key: str) -> bool:
    """
    Gets a boolean value from a dictionary, but treats None as True.

    Args:
        data: The dictionary to get the value from
        key: The key to get the value from

    Returns:
        The boolean value of the key

    """
    # discord tags are weird, when they are None they are True, when they are True they are True and when they are False they are False
    if key in data:
        return True if data[key] is None else bool(data[key])
    return False

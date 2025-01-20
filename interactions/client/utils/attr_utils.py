from functools import partial
from typing import Any, Dict, Callable

import attrs
from attr import Attribute

from interactions.client.const import MISSING, get_logger

__all__ = ("define", "docs", "field", "str_validator")


class_defaults = {
    "eq": False,
    "order": False,
    "hash": False,
    "slots": True,
    "kw_only": True,
}
field_defaults = {"repr": False}


define = partial(attrs.define, **class_defaults)  # type: ignore
field = partial(attrs.field, **field_defaults)  # type: ignore


def docs(doc_string: str) -> Dict[str, str]:
    """
    Makes it easier to quickly type attr documentation.

    Args:
        doc_string: The documentation string.

    Returns:
        The processed metadata dict

    """
    return {"docs": doc_string}


def str_validator(cls: Any, attribute: attrs.Attribute, value: Any) -> None:
    """
    Validates that the value is a string. Helps convert and ives a warning if it isn't.

    Args:
        cls: The instance of the class.
        attribute: The attr attribute being validated.
        value: The value being validated.

    """
    if not isinstance(value, str):
        if value is MISSING:
            return
        setattr(cls, attribute.name, str(value))
        get_logger().warning(
            f"Value of {attribute.name} has been automatically converted to a string. Please use strings in future.\n"
            "Note: Discord will always return value as a string"
        )


def attrs_validator(
    validator: Callable, skip_fields: list[str] | None = None
) -> Callable[[Any, list[Attribute]], list[Attribute]]:
    """
    Sets a validator to all fields of an attrs-dataclass.

    Args:
        validator: The validator to set
        skip_fields: A list of fields to skip adding the validator to

    Returns:
        The new fields for the attrs class

    """

    def operation(_, attributes: list[Attribute]) -> list[Attribute]:
        new_attrs = []
        for attr in attributes:
            if skip_fields and attr.name in skip_fields:
                new_attrs.append(attr)
            else:
                new_attrs.append(attr.evolve(validator=validator))
        return new_attrs

    return operation

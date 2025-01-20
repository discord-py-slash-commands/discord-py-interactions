import functools
import inspect
import typing
from collections import deque
from types import NoneType, UnionType
from typing import (
    Optional,
    Any,
    Callable,
    Annotated,
    Literal,
    Union,
    TYPE_CHECKING,
    Type,
    TypeGuard,
)

import attrs
from typing_extensions import Self

from interactions.client.const import MISSING, T
from interactions.client.errors import BadArgument
from interactions.client.utils.input_utils import _quotes
from interactions.client.utils.misc_utils import get_object_name, maybe_coroutine
from interactions.models.internal.command import BaseCommand
from interactions.models.internal.converters import (
    _LiteralConverter,
    NoArgumentConverter,
    Greedy,
    CONSUME_REST_MARKER,
    MODEL_TO_CONVERTER,
)
from interactions.models.internal.protocols import Converter
from ...client.utils.attr_utils import docs

if TYPE_CHECKING:
    from .context import PrefixedContext

__all__ = (
    "PrefixedCommand",
    "PrefixedCommandParameter",
    "prefixed_command",
)


_STARTING_QUOTES = frozenset(_quotes.keys())


class PrefixedCommandParameter:
    """
    An object representing parameters in a prefixed command.

    This class should not be instantiated directly.
    """

    __slots__ = (
        "consume_rest",
        "consume_rest_class",
        "converters",
        "default",
        "greedy",
        "kind",
        "name",
        "no_argument",
        "type",
        "union",
        "variable",
    )

    name: str
    "The name of the parameter."
    default: Any
    "The default value of the parameter."
    type: Type
    "The type of the parameter."
    kind: inspect._ParameterKind
    """The kind of parameter this is as related to the function."""
    converters: list[Callable[["PrefixedContext", str], Any]]
    "A list of the converter functions for the parameter that convert to its type."
    greedy: bool
    "Is the parameter greedy?"
    union: bool
    "Is the parameter a union?"
    variable: bool
    "Was the parameter marked as a variable argument?"
    consume_rest: bool
    "Was the parameter marked to consume the rest of the input?"
    no_argument: bool
    "Does this parameter have a converter that subclasses `NoArgumentConverter`?"

    def __init__(
        self,
        name: str,
        default: Any = MISSING,
        type: Type | None = None,
        kind: inspect._ParameterKind = inspect._ParameterKind.POSITIONAL_OR_KEYWORD,
        converters: Optional[list[Callable[["PrefixedContext", str], Any]]] = None,
        greedy: bool = False,
        union: bool = False,
        variable: bool = False,
        consume_rest: bool = False,
        no_argument: bool = False,
    ) -> None:
        self.name = name
        self.default = default
        self.type = type
        self.kind = kind
        self.converters = converters or []
        self.greedy = greedy
        self.union = union
        self.variable = variable
        self.consume_rest = consume_rest
        self.no_argument = no_argument

    @classmethod
    def from_param(cls, param: inspect.Parameter) -> Self:
        return cls(
            param.name,
            param.default if param.default is not param.empty else MISSING,
            param.annotation,
            param.kind,
        )

    def __repr__(self) -> str:
        return f"<PrefixedCommandParameter name={self.name!r}>"

    @property
    def optional(self) -> bool:
        """Is this parameter optional?"""
        return self.default != MISSING


class _PrefixedArgsIterator:
    """
    An iterator over the arguments of a prefixed command.

    Has functions to control the iteration.
    """

    __slots__ = ("args", "index", "length")

    def __init__(self, args: tuple[str, ...]) -> None:
        self.args = args
        self.index = 0
        self.length = len(self.args)

    def __iter__(self) -> Self:
        return self

    def __next__(self) -> str:
        if self.index >= self.length:
            raise StopIteration

        result = self.args[self.index]
        self.index += 1
        return self._remove_quotes(result)

    def _remove_quotes(self, arg: str) -> str:
        # this removes quotes from the arguments themselves
        return arg[1:-1] if arg[0] in _STARTING_QUOTES else arg

    def _finish_args(self) -> tuple[str]:
        result = self.args[self.index - 1 :]
        self.index = self.length
        return result

    def get_rest_of_args(self) -> tuple[str]:
        return tuple(self._remove_quotes(r) for r in self._finish_args())

    def consume_rest(self) -> str:
        return " ".join(self._finish_args())

    def back(self, count: int = 1) -> None:
        self.index -= count

    def reset(self) -> None:
        self.index = 0

    @property
    def finished(self) -> bool:
        return self.index >= self.length


def _check_for_no_arg(anno: Any) -> TypeGuard[NoArgumentConverter]:
    return isinstance(anno, NoArgumentConverter) or (inspect.isclass(anno) and issubclass(anno, NoArgumentConverter))


def _convert_to_bool(argument: str) -> bool:
    lowered = argument.lower()
    if lowered in {"yes", "y", "true", "t", "1", "enable", "on"}:
        return True
    if lowered in {"no", "n", "false", "f", "0", "disable", "off"}:
        return False
    raise BadArgument(f"{argument} is not a recognised boolean option.")


def _get_from_anno_type(anno: Annotated) -> Any:
    """
    Handles dealing with Annotated annotations, getting their (first) type annotation.

    This allows correct type hinting with, say, Converters, for example.
    """
    # this is treated how it usually is during runtime
    # the first argument is ignored and the rest is treated as is

    return typing.get_args(anno)[1]


def _get_converter(anno: type, name: str) -> Callable[["PrefixedContext", str], Any]:  # type: ignore
    if typing.get_origin(anno) == Annotated:
        anno = _get_from_anno_type(anno)

    if isinstance(anno, Converter):
        return BaseCommand._get_converter_function(anno, name)
    if converter := MODEL_TO_CONVERTER.get(anno, None):
        return BaseCommand._get_converter_function(converter, name)
    if typing.get_origin(anno) is Literal:
        literals = typing.get_args(anno)
        return _LiteralConverter(literals).convert
    if inspect.isroutine(anno):
        num_params = len(inspect.signature(anno).parameters.values())
        match num_params:
            case 2:
                return anno
            case 1:

                async def _one_function_cmd(ctx, arg) -> Any:
                    return await maybe_coroutine(anno, arg)

                return _one_function_cmd
            case 0:
                ValueError(f"{get_object_name(anno)} for {name} has 0 arguments, which is unsupported.")
            case _:
                ValueError(f"{get_object_name(anno)} for {name} has more than 2 arguments, which is unsupported.")
    elif anno == bool:
        return lambda ctx, arg: _convert_to_bool(arg)
    elif anno == inspect._empty:
        return lambda ctx, arg: str(arg)
    else:
        return lambda ctx, arg: anno(arg)


def _greedy_parse(greedy: Greedy, param: inspect.Parameter) -> Any:
    default = param.default

    if param.kind in {param.KEYWORD_ONLY, param.VAR_POSITIONAL}:
        raise ValueError("Greedy[...] cannot be a variable or keyword-only argument.")

    arg = typing.get_args(greedy)[0]

    if typing.get_origin(arg) == Annotated:
        arg = _get_from_anno_type(arg)

    if typing.get_origin(arg) in {Union, UnionType}:
        args = typing.get_args(arg)

        if len(args) > 2 or NoneType not in args:
            raise ValueError(f"Greedy[{arg!r}] is invalid.")

        arg = args[0]
        default = None

    if arg in {NoneType, str, Greedy, Union, UnionType}:
        raise ValueError(f"Greedy[{get_object_name(arg)}] is invalid.")

    return arg, default


async def _convert(param: PrefixedCommandParameter, ctx: "PrefixedContext", arg: str) -> tuple[Any, bool]:
    converted = MISSING
    for converter in param.converters:
        try:
            converted = await maybe_coroutine(converter, ctx, arg)
            break
        except Exception as e:
            if not param.union and not param.optional:
                if isinstance(e, BadArgument):
                    raise
                raise BadArgument(str(e)) from e

    used_default = False
    if converted == MISSING:
        if param.optional:
            converted = param.default
            used_default = True
        else:
            union_types = typing.get_args(param.type)
            union_names = tuple(get_object_name(t) for t in union_types)
            union_types_str = ", ".join(union_names[:-1]) + f", or {union_names[-1]}"
            raise BadArgument(f'Could not convert "{arg}" into {union_types_str}.')

    if param.no_argument:
        # tells converter not to eat the current argument
        used_default = True

    return converted, used_default


async def _greedy_convert(
    param: PrefixedCommandParameter, ctx: "PrefixedContext", args: _PrefixedArgsIterator
) -> tuple[list[Any] | Any, bool]:
    args.back()
    broke_off = False
    greedy_args = []

    for arg in args:
        try:
            greedy_arg, used_default = await _convert(param, ctx, arg)

            if used_default:
                raise BadArgument

            greedy_args.append(greedy_arg)
        except BadArgument:
            broke_off = True
            break

    if not greedy_args:
        if param.default:
            greedy_args = param.default  # im sorry, typehinters
        else:
            raise BadArgument(f"Failed to find any arguments for {param.type!r}.")

    return greedy_args, broke_off


@attrs.define(eq=False, order=False, hash=False, kw_only=True)
class PrefixedCommand(BaseCommand):
    """Represents a command based off a message, usually denoted with a prefix."""

    name: str = attrs.field(repr=False, metadata=docs("The name of the command."))
    parameters: list[PrefixedCommandParameter] = attrs.field(
        repr=False, metadata=docs("The parameters of the command."), factory=list
    )
    aliases: list[str] = attrs.field(
        metadata=docs("The list of aliases the command can be invoked under."),
        factory=list,
    )
    hidden: bool = attrs.field(
        metadata=docs("If `True`, help commands should not show this in the help output (unless toggled to do so)."),
        default=False,
    )
    ignore_extra: bool = attrs.field(
        metadata=docs(
            "If `True`, ignores extraneous strings passed to a command if all its requirements are met (e.g. ?foo a b c"
            " when only expecting a and b). Otherwise, an error is raised. Defaults to True."
        ),
        default=True,
    )
    help: Optional[str] = attrs.field(repr=False, metadata=docs("The long help text for the command."), default=None)
    brief: Optional[str] = attrs.field(repr=False, metadata=docs("The short help text for the command."), default=None)
    parent: Optional["PrefixedCommand"] = attrs.field(
        repr=False, metadata=docs("The parent command, if applicable."), default=None
    )
    subcommands: dict[str, "PrefixedCommand"] = attrs.field(
        repr=False, metadata=docs("A dict of all subcommands for the command."), factory=dict
    )
    _usage: Optional[str] = attrs.field(repr=False, default=None)
    _inspect_signature: Optional[inspect.Signature] = attrs.field(repr=False, default=None)

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()  # we want checks to work

        # we have to do this afterwards as these rely on the callback
        # and its own value, which is impossible to get with attrs
        # methods, i think

        if self.help:
            self.help = inspect.cleandoc(self.help)
        else:
            self.help = inspect.getdoc(self.callback)
            if isinstance(self.help, bytes):
                self.help = self.help.decode("utf-8")

        if self.brief is None:
            self.brief = self.help.splitlines()[0] if self.help is not None else None

    @property
    def usage(self) -> str:
        """
        A string displaying how the command can be used.

        If no string is set, it will default to the command's signature.
        Useful for help commands.
        """
        return self._usage or self.signature

    @usage.setter
    def usage(self, usage: str) -> None:
        self._usage = usage

    @property
    def qualified_name(self) -> str:
        """Returns the full qualified name of this command."""
        name_deq = deque()
        command = self

        while command.parent is not None:
            name_deq.appendleft(command.name)
            command = command.parent

        name_deq.appendleft(command.name)
        return " ".join(name_deq)

    @property
    def all_subcommands(self) -> frozenset[Self]:
        """Returns all unique subcommands underneath this command."""
        return frozenset(self.subcommands.values())

    @property
    def signature(self) -> str:
        """Returns a POSIX-like signature useful for help command output."""
        if not self.parameters:
            return ""

        results = []

        for param in self.parameters:
            anno = param.type
            name = param.name

            if typing.get_origin(anno) == Annotated:
                anno = typing.get_args(anno)[1]

            if not param.greedy and param.union:
                union_args = typing.get_args(anno)
                if len(union_args) == 2 and param.optional:
                    anno = union_args[0]

            if typing.get_origin(anno) is Literal:
                # it's better to list the values it can be than display the variable name itself
                name = "|".join(f'"{v}"' if isinstance(v, str) else str(v) for v in typing.get_args(anno))

            # we need to do a lot of manipulations with the signature
            # string, so using a deque as a string builder makes sense for performance
            result_builder: deque[str] = deque()

            if param.optional and param.default is not None:
                # it would be weird making it look like name=None
                result_builder.append(f"{name}={param.default}")
            else:
                result_builder.append(name)

            if param.variable:
                # this is inside the brackets
                result_builder.append("...")

            # surround the result with brackets
            if param.optional:
                result_builder.appendleft("[")
                result_builder.append("]")
            else:
                result_builder.appendleft("<")
                result_builder.append(">")

            if param.greedy:
                # this is outside the brackets, making it differentiable from
                # a variable argument
                result_builder.append("...")

            results.append("".join(result_builder))

        return " ".join(results)

    @property
    def is_subcommand(self) -> bool:
        """Return whether this command is a subcommand or not."""
        return bool(self.parent)

    def _parse_parameters(self) -> None:  # noqa: C901
        """
        Parses the parameters that this command has into a form i.py can use.

        This is purposely separated like this to allow "lazy parsing" - parsing
        as the command is added to a bot rather than being parsed immediately.
        This allows variables like "self" to be filtered out, and is useful for
        potential future additions.
        """
        # clear out old parameters just in case
        self.parameters = []

        if not self._inspect_signature:
            # we don't care about the ctx or self variables
            if self.has_binding:
                callback = functools.partial(self.callback, None, None)
            else:
                callback = functools.partial(self.callback, None)

            self._inspect_signature = inspect.signature(callback)

        params = self._inspect_signature.parameters

        # this is used by keyword-only and variable args to make sure there isn't more than one of either
        # mind you, we also don't want one keyword-only and one variable arg either
        finished_params = False

        for name, param in params.items():
            if finished_params:
                raise ValueError("Cannot have multiple keyword-only or variable arguments.")

            cmd_param = PrefixedCommandParameter.from_param(param)
            anno = param.annotation

            # this is ugly, ik
            if typing.get_origin(anno) == Annotated and typing.get_args(anno)[1] is CONSUME_REST_MARKER:
                cmd_param.consume_rest = True
                finished_params = True
                anno = typing.get_args(anno)[0]

                if anno == T:
                    # someone forgot to typehint
                    anno = inspect._empty

            if typing.get_origin(anno) == Annotated:
                anno = _get_from_anno_type(anno)

            if typing.get_origin(anno) == Greedy:
                if finished_params:
                    raise ValueError("Consume rest arguments cannot be Greedy.")

                anno, default = _greedy_parse(anno, param)

                if default is not param.empty:
                    cmd_param.default = default
                cmd_param.greedy = True

            if typing.get_origin(anno) == tuple:
                if cmd_param.optional:
                    # there's a lot of parser ambiguities here, so i'd rather not
                    raise ValueError("Variable arguments cannot have default values or be Optional.")
                cmd_param.variable = True
                finished_params = True

                # use empty if the typehint is just "tuple"
                anno = typing.get_args(anno)[0] if typing.get_args(anno) else inspect._empty

            if typing.get_origin(anno) in {Union, UnionType}:
                cmd_param.union = True
                for arg in typing.get_args(anno):
                    if _check_for_no_arg(anno):
                        cmd_param.no_argument = True

                    if arg != NoneType:
                        converter = _get_converter(arg, name)
                        cmd_param.converters.append(converter)
                    elif not cmd_param.optional:  # d.py-like behavior
                        cmd_param.default = None
            else:
                if _check_for_no_arg(anno):
                    cmd_param.no_argument = True

                converter = _get_converter(anno, name)
                cmd_param.converters.append(converter)

            if not finished_params:
                match param.kind:
                    case param.KEYWORD_ONLY:
                        if cmd_param.greedy:
                            raise ValueError("Consume rest arguments cannot be Greedy.")

                        cmd_param.consume_rest = True
                        finished_params = True
                    case param.VAR_POSITIONAL:
                        if cmd_param.optional:
                            # there's a lot of parser ambiguities here, so i'd rather not
                            raise ValueError("Variable arguments cannot have default values or be Optional.")
                        if cmd_param.greedy:
                            raise ValueError("Variable arguments cannot be Greedy.")

                        cmd_param.variable = True
                        finished_params = True

            self.parameters.append(cmd_param)

        # we need to deal with subcommands too
        for command in self.all_subcommands:
            command._parse_parameters()

    def add_command(self, cmd: Self) -> None:
        """
        Adds a command as a subcommand to this command.

        Args:
            cmd: The command to add

        """
        cmd.parent = self  # just so we know this is a subcommand

        if self.subcommands.get(cmd.name):
            raise ValueError(
                f"Duplicate command! Multiple commands share the name/alias: {self.qualified_name} {cmd.name}."
            )
        self.subcommands[cmd.name] = cmd

        for alias in cmd.aliases:
            if self.subcommands.get(alias):
                raise ValueError(
                    f"Duplicate command! Multiple commands share the name/alias: {self.qualified_name} {cmd.name}."
                )
            self.subcommands[alias] = cmd

    def remove_command(self, name: str) -> None:
        """
        Removes a command as a subcommand from this command.

        If an alias is specified, only the alias will be removed.

        Args:
            name: The command to remove.

        """
        command = self.subcommands.pop(name, None)

        if command is None:
            return

        if name in command.aliases:
            command.aliases.remove(name)
            return

        for alias in command.aliases:
            self.subcommands.pop(alias, None)

    def get_command(self, name: str) -> Optional[Self]:
        """
        Gets a subcommand from this command. Can get subcommands of subcommands if needed.

        Args:
            name: The command to search for.

        Returns:
            PrefixedCommand: The command object, if found.

        """
        if " " not in name:
            return self.subcommands.get(name)

        names = name.split()
        if not names:
            return None

        cmd = self.subcommands.get(names[0])
        if not cmd or not cmd.subcommands:
            return cmd

        for name in names[1:]:
            try:
                cmd = cmd.subcommands[name]
            except (AttributeError, KeyError):
                return None

        return cmd

    def subcommand(
        self,
        name: Optional[str] = None,
        *,
        aliases: Optional[list[str]] = None,
        help: Optional[str] = None,
        brief: Optional[str] = None,
        usage: Optional[str] = None,
        enabled: bool = True,
        hidden: bool = False,
        ignore_extra: bool = True,
        inherit_checks: bool = True,
    ) -> Callable[..., Self]:
        """
        A decorator to declare a subcommand for a prefixed command.

        Args:
            name: The name of the command. Defaults to the name of the coroutine.
            aliases: The list of aliases the command can be invoked under.
            help: The long help text for the command. Defaults to the docstring of the coroutine, if there is one.
            brief: The short help text for the command. Defaults to the first line of the help text, if there is one.
            usage: A string displaying how the command can be used. If no string is set, it will \
                default to the command's signature. Useful for help commands.
            enabled: Whether this command can be run at all.
            hidden: If `True`, the default help command (when it is added) does not show this in the help output.
            ignore_extra: If `True`, ignores extraneous strings passed to a command if all its requirements are met \
                (e.g. ?foo a b c when only expecting a and b). Otherwise, an error is raised.
            inherit_checks: If `True`, the subcommand will inherit its checks from the parent command.

        """

        def wrapper(func: Callable) -> Self:
            cmd = PrefixedCommand(
                callback=func,
                name=name or func.__name__,
                aliases=aliases or [],
                help=help,
                brief=brief,
                parent=self,
                usage=usage,
                enabled=enabled,
                hidden=hidden,
                ignore_extra=ignore_extra,
                checks=self.checks if inherit_checks else [],
            )
            self.add_command(cmd)
            return cmd

        return wrapper

    async def call_callback(self, callback: Callable, ctx: "PrefixedContext") -> None:  # noqa: C901
        """
        Runs the callback of this command.

        Args:
            callback (Callable: The callback to run. This is provided for compatibility with internal.
            ctx (internal.MessageContext): The context to use for this command.

        """
        # sourcery skip: remove-empty-nested-block, remove-redundant-if, remove-unnecessary-else
        if len(self.parameters) == 0:
            if ctx.args and not self.ignore_extra:
                raise BadArgument(f"Too many arguments passed to {self.name}.")
            return await self.call_with_binding(callback, ctx)
        # this is slightly costly, but probably worth it
        new_args: list[Any] = []
        kwargs: dict[str, Any] = {}
        args = _PrefixedArgsIterator(tuple(ctx.args))
        param_index = 0

        for arg in args:
            while param_index < len(self.parameters):
                param = self.parameters[param_index]

                if param.consume_rest:
                    arg = args.consume_rest()

                if param.variable:
                    args_to_convert = args.get_rest_of_args()
                    new_arg = [await _convert(param, ctx, arg) for arg in args_to_convert]
                    new_arg = tuple(arg[0] for arg in new_arg)

                    if param.kind == inspect.Parameter.VAR_POSITIONAL:
                        new_args.extend(new_arg)
                    elif param.kind == inspect.Parameter.POSITIONAL_ONLY:
                        new_args.append(new_arg)
                    else:
                        kwargs[param.name] = new_arg

                    param_index += 1
                    break

                if param.greedy:
                    greedy_args, broke_off = await _greedy_convert(param, ctx, args)

                    new_args.append(greedy_args)
                    param_index += 1
                    if broke_off:
                        args.back()

                    if param.default:
                        continue
                    break

                converted, used_default = await _convert(param, ctx, arg)
                if param.kind in {
                    inspect.Parameter.POSITIONAL_ONLY,
                    inspect.Parameter.VAR_POSITIONAL,
                }:
                    new_args.append(converted)
                else:
                    kwargs[param.name] = converted
                param_index += 1

                if not used_default:
                    break

        if param_index < len(self.parameters):
            for param in self.parameters[param_index:]:
                if param.no_argument:
                    converted, _ = await _convert(param, ctx, None)  # type: ignore
                    if not param.consume_rest:
                        new_args.append(converted)
                    else:
                        kwargs[param.name] = converted
                        break
                    continue

                if not param.optional:
                    raise BadArgument(f"{param.name} is a required argument that is missing.")
                if param.kind in {
                    inspect.Parameter.POSITIONAL_ONLY,
                    inspect.Parameter.VAR_POSITIONAL,
                }:
                    new_args.append(param.default)
                else:
                    kwargs[param.name] = param.default
                    break
        elif not self.ignore_extra and not args.finished:
            raise BadArgument(f"Too many arguments passed to {self.name}.")

        return await self.call_with_binding(callback, ctx, *new_args, **kwargs)


def prefixed_command(
    name: Optional[str] = None,
    *,
    aliases: Optional[list[str]] = None,
    help: Optional[str] = None,
    brief: Optional[str] = None,
    usage: Optional[str] = None,
    enabled: bool = True,
    hidden: bool = False,
    ignore_extra: bool = True,
) -> Callable[..., PrefixedCommand]:
    """
    A decorator to declare a coroutine as a prefixed command.

    Args:
        name: The name of the command. Defaults to the name of the coroutine.
        aliases: The list of aliases the command can be invoked under.
        help: The long help text for the command. Defaults to the docstring of the coroutine, if there is one.
        brief: The short help text for the command. Defaults to the first line of the help text, if there is one.
        usage: A string displaying how the command can be used. If no string is set, it will default to the \
            command's signature. Useful for help commands.
        enabled: Whether this command can be run at all.
        hidden: If `True`, the default help command (when it is added) does not show this in the help output.
        ignore_extra: If `True`, ignores extraneous strings passed to a command if all its requirements are \
            met (e.g. ?foo a b c when only expecting a and b). Otherwise, an error is raised.

    """

    def wrapper(func: Callable) -> PrefixedCommand:
        return PrefixedCommand(
            callback=func,
            name=name or func.__name__,
            aliases=aliases or [],
            help=help,
            brief=brief,
            usage=usage,
            enabled=enabled,
            hidden=hidden,
            ignore_extra=ignore_extra,
        )

    return wrapper

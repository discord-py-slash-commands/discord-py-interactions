import asyncio
from collections import defaultdict
import inspect
import re
import typing
import types
import functools
from enum import IntEnum
from typing import (
    TYPE_CHECKING,
    Annotated,
    Callable,
    Coroutine,
    Dict,
    List,
    Union,
    Optional,
    Any,
    TypeVar,
)

import attrs
from attr import Attribute

import interactions.models.discord.channel as channel
from interactions.client.const import (
    GLOBAL_SCOPE,
    SLASH_CMD_NAME_LENGTH,
    SLASH_CMD_MAX_OPTIONS,
    SLASH_CMD_MAX_DESC_LENGTH,
    MISSING,
    Absent,
    AsyncCallable,
)
from interactions.client.mixins.serialization import DictSerializationMixin
from interactions.client.utils import optional
from interactions.client.utils.attr_utils import attrs_validator, docs
from interactions.client.utils.misc_utils import get_parameters, maybe_coroutine
from interactions.client.utils.serializer import no_export_meta
from interactions.models.discord.enums import ChannelType, CommandType, ContextType, IntegrationType, Permissions
from interactions.models.discord.role import Role
from interactions.models.discord.snowflake import to_snowflake_list, to_snowflake
from interactions.models.discord.user import BaseUser
from interactions.models.internal.auto_defer import AutoDefer
from interactions.models.internal.callback import CallbackObject
from interactions.models.internal.command import BaseCommand
from interactions.models.internal.localisation import LocalisedField
from interactions.models.internal.protocols import Converter

if TYPE_CHECKING:
    from interactions.models.discord.snowflake import Snowflake_Type
    from interactions.models.internal.context import BaseContext, InteractionContext
    from interactions import Client

__all__ = (
    "CallbackType",
    "ComponentCommand",
    "ContextMenu",
    "GlobalAutoComplete",
    "InteractionCommand",
    "LocalisedDesc",
    "LocalisedName",
    "LocalizedDesc",
    "LocalizedName",
    "ModalCommand",
    "OptionType",
    "SlashCommand",
    "SlashCommandChoice",
    "SlashCommandOption",
    "SlashCommandParameter",
    "application_commands_to_dict",
    "auto_defer",
    "component_callback",
    "context_menu",
    "contexts",
    "global_autocomplete",
    "integration_types",
    "message_context_menu",
    "modal_callback",
    "slash_command",
    "slash_default_member_permission",
    "slash_option",
    "subcommand",
    "sync_needed",
    "user_context_menu",
)


def name_validator(_: Any, attr: Attribute, value: str) -> None:
    if value:
        if not re.match(f"^[\\w-]{{1,{SLASH_CMD_NAME_LENGTH}}}$", value) or value != value.lower():
            raise ValueError(
                f"Slash Command names must be lower case and match this regex: ^[\\w-]{1, {SLASH_CMD_NAME_LENGTH} }$"
            )


def desc_validator(_: Any, attr: Attribute, value: str) -> None:
    if value and not 1 <= len(value) <= SLASH_CMD_MAX_DESC_LENGTH:
        raise ValueError(f"Description must be between 1 and {SLASH_CMD_MAX_DESC_LENGTH} characters long")


def custom_ids_validator(*custom_id: str | re.Pattern) -> None:
    if not (all(isinstance(i, re.Pattern) for i in custom_id) or all(isinstance(i, str) for i in custom_id)):
        raise ValueError("All custom IDs be either a string or a regex pattern, not a mix of both.")


@attrs.define(
    eq=False,
    order=False,
    hash=False,
    field_transformer=attrs_validator(name_validator, skip_fields=["default_locale"]),
)
class LocalisedName(LocalisedField):
    """A localisation object for names."""

    def __repr__(self) -> str:
        return super().__repr__()


@attrs.define(
    eq=False,
    order=False,
    hash=False,
    field_transformer=attrs_validator(desc_validator, skip_fields=["default_locale"]),
)
class LocalisedDesc(LocalisedField):
    """A localisation object for descriptions."""

    def __repr__(self) -> str:
        return super().__repr__()


LocalizedName = LocalisedName
LocalizedDesc = LocalisedDesc


class OptionType(IntEnum):
    """Option types supported by slash commands."""

    SUB_COMMAND = 1
    SUB_COMMAND_GROUP = 2
    STRING = 3
    INTEGER = 4
    BOOLEAN = 5
    USER = 6
    CHANNEL = 7
    ROLE = 8
    MENTIONABLE = 9
    NUMBER = 10
    ATTACHMENT = 11

    @classmethod
    def resolvable_types(cls) -> tuple["OptionType", ...]:
        """A tuple of all resolvable types."""
        return cls.USER, cls.CHANNEL, cls.ROLE, cls.MENTIONABLE, cls.ATTACHMENT

    @classmethod
    def static_types(cls) -> tuple["OptionType", ...]:
        """A tuple of all static types."""
        return cls.STRING, cls.INTEGER, cls.BOOLEAN, cls.NUMBER

    @classmethod
    def command_types(cls) -> tuple["OptionType", ...]:
        """A tuple of all command types."""
        return cls.SUB_COMMAND, cls.SUB_COMMAND_GROUP

    @classmethod
    def from_type(cls, t: type) -> "OptionType | None":
        """
        Convert data types to their corresponding OptionType.

        Args:
            t: The datatype to convert

        Returns:
            OptionType or None

        """
        if issubclass(t, str):
            return cls.STRING
        if issubclass(t, int):
            return cls.INTEGER
        if issubclass(t, bool):
            return cls.BOOLEAN
        if issubclass(t, BaseUser):
            return cls.USER
        if issubclass(t, channel.BaseChannel):
            return cls.CHANNEL
        if issubclass(t, Role):
            return cls.ROLE
        if issubclass(t, float):
            return cls.NUMBER


class CallbackType(IntEnum):
    """Types of callback supported by interaction response."""

    PONG = 1
    CHANNEL_MESSAGE_WITH_SOURCE = 4
    DEFERRED_CHANNEL_MESSAGE_WITH_SOURCE = 5
    DEFERRED_UPDATE_MESSAGE = 6
    UPDATE_MESSAGE = 7
    AUTOCOMPLETE_RESULT = 8
    MODAL = 9


@attrs.define(eq=False, order=False, hash=False, kw_only=True)
class InteractionCommand(BaseCommand):
    """
    Represents a discord abstract interaction command.

    Attributes:
        scope: Denotes whether its global or for specific guild.
        default_member_permissions: What permissions members need to have by default to use this command.
        dm_permission: Should this command be available in DMs.
        cmd_id: The id of this command given by discord.
        callback: The coroutine to callback when this interaction is received.

    """

    name: LocalisedName | str = attrs.field(
        repr=False,
        metadata=docs("1-32 character name") | no_export_meta,
        converter=LocalisedName.converter,
    )
    scopes: List["Snowflake_Type"] = attrs.field(
        factory=lambda: [GLOBAL_SCOPE],
        converter=to_snowflake_list,
        metadata=docs("The scopes of this interaction. Global or guild ids") | no_export_meta,
    )
    default_member_permissions: Optional["Permissions"] = attrs.field(
        repr=False,
        default=None,
        metadata=docs("What permissions members need to have by default to use this command"),
    )
    dm_permission: bool = attrs.field(
        repr=False, default=True, metadata=docs("Whether this command is enabled in DMs (deprecated)") | no_export_meta
    )
    cmd_id: Dict[str, "Snowflake_Type"] = attrs.field(
        repr=False, factory=dict, metadata=docs("The unique IDs of this commands") | no_export_meta
    )  # scope: cmd_id
    callback: Callable[..., Coroutine] = attrs.field(
        repr=False,
        default=None,
        metadata=docs("The coroutine to call when this interaction is received") | no_export_meta,
    )
    auto_defer: "AutoDefer" = attrs.field(
        default=MISSING,
        metadata=docs("A system to automatically defer this command after a set duration") | no_export_meta,
    )
    nsfw: bool = attrs.field(repr=False, default=False, metadata=docs("This command should only work in NSFW channels"))
    integration_types: list[Union[IntegrationType, int]] = attrs.field(
        factory=lambda: [IntegrationType.GUILD_INSTALL],
        repr=False,
        metadata=docs("Installation context(s) where the command is available, only for globally-scoped commands."),
    )
    contexts: list[Union[ContextType, int]] = attrs.field(
        factory=lambda: [ContextType.GUILD, ContextType.BOT_DM, ContextType.PRIVATE_CHANNEL],
        repr=False,
        metadata=docs("Interaction context(s) where the command can be used, only for globally-scoped commands."),
    )
    _application_id: "Snowflake_Type" = attrs.field(repr=False, default=None, converter=optional(to_snowflake))

    def __attrs_post_init__(self) -> None:
        if self.callback is not None:
            if hasattr(self.callback, "auto_defer"):
                self.auto_defer = self.callback.auto_defer
            if hasattr(self.callback, "integration_types"):
                self.integration_types = self.callback.integration_types
            if hasattr(self.callback, "contexts"):
                self.contexts = self.callback.contexts

        super().__attrs_post_init__()

    @dm_permission.validator
    def _dm_permission_validator(self, attribute: str, value: bool) -> None:
        # since dm_permission is deprecated, ipy transforms it into something that isn't
        if not value:
            try:
                self.contexts.remove(ContextType.PRIVATE_CHANNEL)
            except ValueError:
                pass

            try:
                self.contexts.remove(ContextType.BOT_DM)
            except ValueError:
                pass

    def to_dict(self) -> dict:
        data = super().to_dict()

        data["name_localizations"] = self.name.to_locale_dict()

        if self.default_member_permissions is not None:
            data["default_member_permissions"] = str(int(self.default_member_permissions))
        else:
            data["default_member_permissions"] = None

        return data

    def mention(self, scope: Optional["Snowflake_Type"] = None) -> str:
        """
        Returns a string that would mention the interaction.

        Args:
            scope: If the command is available in multiple scope, specify which scope to get the mention for. Defaults to the first available one if not specified.

        Returns:
            The markdown mention.

        """
        if scope:
            cmd_id = self.get_cmd_id(scope=scope)
        else:
            cmd_id = next(iter(self.cmd_id.values()))

        return f"</{self.resolved_name}:{cmd_id}>"

    @property
    def resolved_name(self) -> str:
        """A representation of this interaction's name."""
        return str(self.name)

    def get_localised_name(self, locale: str) -> str:
        return self.name.get_locale(locale)

    def get_cmd_id(self, scope: "Snowflake_Type") -> "Snowflake_Type":
        return self.cmd_id.get(scope, self.cmd_id.get(GLOBAL_SCOPE, None))

    @property
    def is_subcommand(self) -> bool:
        return False

    async def _permission_enforcer(self, ctx: "BaseContext") -> bool:
        """A check that enforces Discord permissions."""
        # I wish this wasn't needed, but unfortunately Discord permissions cant be trusted to actually prevent usage
        return ctx.guild is not None if self.dm_permission is False else True

    def is_enabled(self, ctx: "BaseContext") -> bool:
        """
        Check if this command is enabled in the given context.

        Args:
            ctx: The context to check.

        Returns:
            Whether this command is enabled in the given context.

        """
        if not self.dm_permission and ctx.guild is None:
            return False
        if self.dm_permission and ctx.guild is None:
            # remaining checks are impossible if this is a DM and DMs are enabled
            return True

        if self.nsfw and not ctx.channel.is_nsfw():
            return False
        if cmd_perms := ctx.guild.command_permissions.get(self.get_cmd_id(ctx.guild.id)):
            if not cmd_perms.is_enabled_in_context(ctx):
                return False
        if self.default_member_permissions is not None:
            channel_perms = ctx.author.channel_permissions(ctx.channel)
            if any(perm not in channel_perms for perm in self.default_member_permissions):
                return False
        return True


@attrs.define(eq=False, order=False, hash=False, kw_only=True)
class ContextMenu(InteractionCommand):
    """
    Represents a discord context menu.

    Attributes:
        name: The name of this entry.
        type: The type of entry (user or message).

    """

    name: LocalisedField = attrs.field(
        repr=False, metadata=docs("1-32 character name"), converter=LocalisedField.converter
    )
    type: CommandType = attrs.field(repr=False, metadata=docs("The type of command, defaults to 1 if not specified"))

    @type.validator
    def _type_validator(self, attribute: str, value: int) -> None:
        if not isinstance(value, CommandType):
            if value not in CommandType.__members__.values():
                raise ValueError("Context Menu type not recognised, please consult the docs.")
        elif value == CommandType.CHAT_INPUT:
            raise ValueError(
                "The CHAT_INPUT type is basically slash commands. Please use the @slash_command() " "decorator instead."
            )

    def to_dict(self) -> dict:
        data = super().to_dict()

        data["name"] = str(self.name)
        return data


@attrs.define(eq=False, order=False, hash=False, kw_only=False)
class SlashCommandChoice(DictSerializationMixin):
    """
    Represents a discord slash command choice.

    Attributes:
        name: The name the user will see
        value: The data sent to your code when this choice is used

    """

    name: LocalisedField | str = attrs.field(repr=False, converter=LocalisedField.converter)
    value: Union[str, int, float] = attrs.field(
        repr=False,
    )

    def as_dict(self) -> dict:
        return {
            "name": str(self.name),
            "value": self.value,
            "name_localizations": self.name.to_locale_dict(),
        }


@attrs.define(eq=False, order=False, hash=False, kw_only=False)
class SlashCommandOption(DictSerializationMixin):
    """
    Represents a discord slash command option.

    Attributes:
        name: The name of this option
        type: The type of option
        description: The description of this option
        required: "This option must be filled to use the command"
        choices: A list of choices the user has to pick between
        channel_types: The channel types permitted. The option needs to be a channel
        min_value: The minimum value permitted. The option needs to be an integer or float
        max_value: The maximum value permitted. The option needs to be an integer or float
        min_length: The minimum length of text a user can input. The option needs to be a string
        max_length: The maximum length of text a user can input. The option needs to be a string
        argument_name: The name of the argument to be used in the function. If not given, assumed to be the same as the name of the option

    """

    name: LocalisedName | str = attrs.field(repr=False, converter=LocalisedName.converter)
    type: Union[OptionType, int] = attrs.field(
        repr=False,
    )
    description: LocalisedDesc | str | str = attrs.field(
        repr=False, default="No Description Set", converter=LocalisedDesc.converter
    )
    required: bool = attrs.field(repr=False, default=True)
    autocomplete: bool = attrs.field(repr=False, default=False)
    choices: List[Union[SlashCommandChoice, Dict]] = attrs.field(repr=False, factory=list)
    channel_types: Optional[list[Union[ChannelType, int]]] = attrs.field(repr=False, default=None)
    min_value: Optional[float] = attrs.field(repr=False, default=None)
    max_value: Optional[float] = attrs.field(repr=False, default=None)
    min_length: Optional[int] = attrs.field(repr=False, default=None)
    max_length: Optional[int] = attrs.field(repr=False, default=None)
    argument_name: Optional[str] = attrs.field(repr=False, default=None)

    @type.validator
    def _type_validator(self, attribute: str, value: int) -> None:
        if value in (OptionType.SUB_COMMAND, OptionType.SUB_COMMAND_GROUP):
            raise ValueError(
                "Options cannot be SUB_COMMAND or SUB_COMMAND_GROUP. If you want to use subcommands, "
                "see the @sub_command() decorator."
            )

    @channel_types.validator
    def _channel_types_validator(self, attribute: str, value: Optional[list[OptionType]]) -> None:
        if value is not None:
            if self.type != OptionType.CHANNEL:
                raise ValueError("The option needs to be CHANNEL to use this")

            allowed_int = [channel_type.value for channel_type in ChannelType]
            for item in value:
                if (item not in allowed_int) and (item not in ChannelType):
                    raise ValueError(f"{value} is not allowed here")

    @min_value.validator
    def _min_value_validator(self, attribute: str, value: Optional[float]) -> None:
        if value is not None:
            if self.type not in [OptionType.INTEGER, OptionType.NUMBER]:
                raise ValueError("`min_value` can only be supplied with int or float options")

            if self.type == OptionType.INTEGER and isinstance(value, float):
                raise ValueError("`min_value` needs to be an int in an int option")

            if self.max_value is not None and self.min_value is not None and self.max_value < self.min_value:
                raise ValueError("`min_value` needs to be <= than `max_value`")

    @max_value.validator
    def _max_value_validator(self, attribute: str, value: Optional[float]) -> None:
        if value is not None:
            if self.type not in (OptionType.INTEGER, OptionType.NUMBER):
                raise ValueError("`max_value` can only be supplied with int or float options")

            if self.type == OptionType.INTEGER and isinstance(value, float):
                raise ValueError("`max_value` needs to be an int in an int option")

            if self.max_value and self.min_value and self.max_value < self.min_value:
                raise ValueError("`min_value` needs to be <= than `max_value`")

    @min_length.validator
    def _min_length_validator(self, attribute: str, value: Optional[int]) -> None:
        if value is not None:
            if self.type != OptionType.STRING:
                raise ValueError("`min_length` can only be supplied with string options")

            if self.max_length is not None and self.min_length is not None and self.max_length < self.min_length:
                raise ValueError("`min_length` needs to be <= than `max_length`")

            if self.min_length < 0:
                raise ValueError("`min_length` needs to be >= 0")

    @max_length.validator
    def _max_length_validator(self, attribute: str, value: Optional[int]) -> None:
        if value is not None:
            if self.type != OptionType.STRING:
                raise ValueError("`max_length` can only be supplied with string options")

            if self.min_length is not None and self.max_length is not None and self.max_length < self.min_length:
                raise ValueError("`min_length` needs to be <= than `max_length`")

            if self.max_length < 1:
                raise ValueError("`max_length` needs to be >= 1")

    def as_dict(self) -> dict:
        data = attrs.asdict(self)
        data.pop("argument_name", None)
        data["name"] = str(self.name)
        data["description"] = str(self.description)
        data["choices"] = [
            choice.as_dict() if isinstance(choice, SlashCommandChoice) else choice for choice in self.choices
        ]
        data["name_localizations"] = self.name.to_locale_dict()
        data["description_localizations"] = self.description.to_locale_dict()

        return data


@attrs.define()
class SlashCommandParameter:
    name: str = attrs.field()
    type: typing.Any = attrs.field()
    kind: inspect._ParameterKind = attrs.field()
    default: typing.Any = attrs.field(default=MISSING)
    converter: typing.Optional[typing.Callable] = attrs.field(default=None)
    _option_name: typing.Optional[str] = attrs.field(default=None)

    @property
    def option_name(self) -> str:
        return self._option_name or self.name


def _get_option_from_annotated(annotated: Annotated) -> SlashCommandOption | None:
    args = typing.get_args(annotated)
    return next((a for a in args if isinstance(a, SlashCommandOption)), None)


def _get_converter_from_annotated(annotated: Annotated) -> Converter | None:
    args = typing.get_args(annotated)
    return next((a for a in args if isinstance(a, Converter)), None)


def _is_union(anno: typing.Any) -> bool:
    return typing.get_origin(anno) in {Union, types.UnionType}


def _is_optional(anno: typing.Any) -> bool:
    return _is_union(anno) and types.NoneType in typing.get_args(anno)


def _remove_optional(t: OptionType | type) -> Any:
    non_optional_args: tuple[type] = tuple(a for a in typing.get_args(t) if a is not types.NoneType)
    if len(non_optional_args) == 1:
        return non_optional_args[0]
    return typing.Union[non_optional_args]  # type: ignore


@attrs.define(eq=False, order=False, hash=False, kw_only=True)
class SlashCommand(InteractionCommand):
    name: LocalisedName | str = attrs.field(repr=False, converter=LocalisedName.converter)
    description: LocalisedDesc | str = attrs.field(
        repr=False, default="No Description Set", converter=LocalisedDesc.converter
    )

    group_name: LocalisedName | str = attrs.field(
        repr=False, default=None, metadata=no_export_meta, converter=LocalisedName.converter
    )
    group_description: LocalisedDesc | str = attrs.field(
        repr=False,
        default="No Description Set",
        metadata=no_export_meta,
        converter=LocalisedDesc.converter,
    )

    sub_cmd_name: LocalisedName | str = attrs.field(
        repr=False, default=None, metadata=no_export_meta, converter=LocalisedName.converter
    )
    sub_cmd_description: LocalisedDesc | str = attrs.field(
        repr=False,
        default="No Description Set",
        metadata=no_export_meta,
        converter=LocalisedDesc.converter,
    )

    options: List[Union[SlashCommandOption, Dict]] = attrs.field(repr=False, factory=list)
    autocomplete_callbacks: dict = attrs.field(repr=False, factory=dict, metadata=no_export_meta)

    parameters: dict[str, SlashCommandParameter] = attrs.field(
        repr=False,
        factory=dict,
        metadata=no_export_meta,
    )
    _uses_arg: bool = attrs.field(repr=False, default=False, metadata=no_export_meta)

    @property
    def resolved_name(self) -> str:
        return (
            f"{self.name}"
            f"{f' {self.group_name}' if bool(self.group_name) else ''}"
            f"{f' {self.sub_cmd_name}' if bool(self.sub_cmd_name) else ''}"
        )

    def get_localised_name(self, locale: str) -> str:
        return (
            f"{self.name.get_locale(locale)}"
            f"{f' {self.group_name.get_locale(locale)}' if bool(self.group_name) else ''}"
            f"{f' {self.sub_cmd_name.get_locale(locale)}' if bool(self.sub_cmd_name) else ''}"
        )

    @property
    def is_subcommand(self) -> bool:
        return bool(self.sub_cmd_name)

    def __attrs_post_init__(self) -> None:
        if self.callback is not None and hasattr(self.callback, "options"):
            if not self.options:
                self.options = []
            self.options += self.callback.options

        super().__attrs_post_init__()

    def _add_option_from_anno_method(self, name: str, option: SlashCommandOption) -> None:
        if not self.options:
            self.options = []

        if option.name.default is None:
            option.name = LocalisedName.converter(name)
        else:
            option.argument_name = name

        self.options.append(option)

    def _parse_parameters(self) -> None:  # noqa: C901
        """
        Parses the parameters that this command has into a form i.py can use.

        This is purposely separated like this to allow "lazy parsing" - parsing
        as the command is added to a bot rather than being parsed immediately.
        This allows variables like "self" to be filtered out, and is useful for
        potential future additions.

        For slash commands, it is also much faster than inspecting the parameters
        each time the command is called.
        It also allows for us to deal with the "annotation method", where users
        put their options in the annotations itself.
        """
        if self.callback is None or self.parameters:
            return

        if self.has_binding:
            callback = functools.partial(self.callback, None, None)
        else:
            callback = functools.partial(self.callback, None)

        for param in get_parameters(callback).values():
            if param.kind == inspect._ParameterKind.VAR_POSITIONAL:
                self._uses_arg = True
                continue

            if param.kind == inspect._ParameterKind.VAR_KEYWORD:
                # in case it was set before
                # we prioritize **kwargs over *args
                self._uses_arg = False
                continue

            our_param = SlashCommandParameter(param.name, param.annotation, param.kind)
            our_param.default = param.default if param.default is not inspect._empty else MISSING

            if param.annotation is not inspect._empty:
                anno = param.annotation
                converter = None

                if _is_optional(anno):
                    anno = _remove_optional(anno)

                if isinstance(anno, SlashCommandOption):
                    # annotation method, get option and add it in
                    self._add_option_from_anno_method(param.name, anno)

                if isinstance(anno, Converter):
                    converter = anno
                elif typing.get_origin(anno) == Annotated:
                    if option := _get_option_from_annotated(anno):
                        # also annotation method
                        self._add_option_from_anno_method(param.name, option)

                    converter = _get_converter_from_annotated(anno)

                if converter:
                    our_param.converter = self._get_converter_function(converter, our_param.name)

            self.parameters[param.name] = our_param

        if self.options:
            for option in self.options:
                maybe_argument_name = (
                    option.argument_name if isinstance(option, SlashCommandOption) else option.get("argument_name")
                )
                if maybe_argument_name:
                    name = option.name if isinstance(option, SlashCommandOption) else option["name"]
                    try:
                        self.parameters[maybe_argument_name]._option_name = str(name)
                    except KeyError:
                        raise ValueError(
                            f'Argument name "{maybe_argument_name}" for "{name}" does not match any parameter in {self.resolved_name}\'s function.'
                        ) from None

    def to_dict(self) -> dict:
        data = super().to_dict()

        if self.is_subcommand:
            data["name"] = str(self.sub_cmd_name)
            data["description"] = str(self.sub_cmd_description)
            data["name_localizations"] = self.sub_cmd_name.to_locale_dict()
            data["description_localizations"] = self.sub_cmd_description.to_locale_dict()
            data.pop("default_member_permissions", None)
            data.pop("dm_permission", None)
            data.pop("nsfw", None)
        else:
            data["name_localizations"] = self.name.to_locale_dict()
            data["description_localizations"] = self.description.to_locale_dict()
        return data

    @options.validator
    def options_validator(self, attribute: str, value: List) -> None:
        if value:
            if not isinstance(value, list):
                raise TypeError("Options attribute must be either None or a list of options")
            if len(value) > SLASH_CMD_MAX_OPTIONS:
                raise ValueError(f"Slash commands can only hold {SLASH_CMD_MAX_OPTIONS} options")
            if value != sorted(
                value,
                key=lambda x: x.required if isinstance(x, SlashCommandOption) else x["required"],
                reverse=True,
            ):
                raise ValueError("Required options must go before optional options")

    def autocomplete(self, option_name: str) -> Callable[..., Coroutine]:
        """A decorator to declare a coroutine as an option autocomplete."""

        def wrapper(call: Callable[..., Coroutine]) -> Callable[..., Coroutine]:
            if not asyncio.iscoroutinefunction(call):
                raise TypeError("autocomplete must be coroutine")
            self.autocomplete_callbacks[option_name] = call

            if self.options:
                # automatically set the option's autocomplete attribute to True
                for opt in self.options:
                    if isinstance(opt, dict) and str(opt["name"]) == option_name:
                        opt["autocomplete"] = True
                    elif isinstance(opt, SlashCommandOption) and str(opt.name) == option_name:
                        opt.autocomplete = True

            return call

        option_name = option_name.lower()
        return wrapper

    def group(
        self, name: str | None = None, description: str = "No Description Set", inherit_checks: bool = True
    ) -> "SlashCommand":
        return SlashCommand(
            name=self.name,
            description=self.description,
            group_name=name,
            group_description=description,
            scopes=self.scopes,
            default_member_permissions=self.default_member_permissions,
            integration_types=self.integration_types,
            contexts=self.contexts,
            dm_permission=self.dm_permission,
            checks=self.checks.copy() if inherit_checks else [],
        )

    def subcommand(
        self,
        sub_cmd_name: Absent[LocalisedName | str] = MISSING,
        group_name: LocalisedName | str = None,
        sub_cmd_description: Absent[LocalisedDesc | str] = MISSING,
        group_description: Absent[LocalisedDesc | str] = MISSING,
        options: List[Union[SlashCommandOption, Dict]] | None = None,
        nsfw: bool = False,
        inherit_checks: bool = True,
    ) -> Callable[..., "SlashCommand"]:
        def wrapper(call: Callable[..., Coroutine]) -> "SlashCommand":
            nonlocal sub_cmd_name, sub_cmd_description

            if not asyncio.iscoroutinefunction(call):
                raise TypeError("Subcommand must be coroutine")

            if sub_cmd_description is MISSING:
                sub_cmd_description = call.__doc__ or "No Description Set"
            if sub_cmd_name is MISSING:
                sub_cmd_name = call.__name__

            return SlashCommand(
                name=self.name,
                description=self.description,
                group_name=group_name or self.group_name,
                group_description=group_description or self.group_description,
                sub_cmd_name=sub_cmd_name,
                sub_cmd_description=sub_cmd_description,
                default_member_permissions=self.default_member_permissions,
                integration_types=self.integration_types,
                contexts=self.contexts,
                dm_permission=self.dm_permission,
                options=options,
                callback=call,
                scopes=self.scopes,
                nsfw=nsfw,
                checks=self.checks.copy() if inherit_checks else [],
            )

        return wrapper

    async def call_callback(self, callback: typing.Callable, ctx: "InteractionContext") -> None:
        if not self.parameters:
            if self._uses_arg:
                return await self.call_with_binding(callback, ctx, *ctx.args)
            return await self.call_with_binding(callback, ctx)

        kwargs_copy = ctx.kwargs.copy()

        new_args = []
        new_kwargs = {}

        for param in self.parameters.values():
            value = kwargs_copy.pop(param.option_name, MISSING)
            if value is MISSING:
                continue

            if converter := param.converter:
                value = await maybe_coroutine(converter, ctx, value)

            if param.kind == inspect.Parameter.POSITIONAL_ONLY:
                new_args.append(value)
            else:
                new_kwargs[param.name] = value

        # i do want to address one thing: what happens if you have both *args and **kwargs
        # in your argument?
        # i would say passing in values for both makes sense... but they're very likely
        # going to overlap and cause issues and confusion
        # for the sake of simplicty, i.py assumes kwargs takes priority over args
        if kwargs_copy:
            if self._uses_arg:
                new_args.extend(kwargs_copy.values())
            else:
                new_kwargs |= kwargs_copy

        return await self.call_with_binding(callback, ctx, *new_args, **new_kwargs)


@attrs.define(eq=False, order=False, hash=False, kw_only=True)
class ComponentCommand(InteractionCommand):
    # right now this adds no extra functionality, but for future dev ive implemented it
    name: str = attrs.field(
        repr=False,
    )
    listeners: list[str | re.Pattern] = attrs.field(repr=False, factory=list)


@attrs.define(eq=False, order=False, hash=False, kw_only=True)
class ModalCommand(ComponentCommand):
    _just_ctx: bool = attrs.field(repr=False, default=False)

    async def call_callback(self, callback: Callable, context: "BaseContext") -> None:
        if self._just_ctx:
            return await self.call_with_binding(callback, context)
        return await super().call_callback(callback, context)


def _unpack_helper(iterable: typing.Iterable[str]) -> list[str]:
    """
    Unpacks all types of iterable into a list of strings. Primarily to flatten generators.

    Args:
        iterable: The iterable of strings to unpack

    Returns:
        A list of strings

    """
    unpack = []
    for c in iterable:
        if inspect.isgenerator(c):
            unpack += list(c)
        else:
            unpack.append(c)
    return unpack


class GlobalAutoComplete(CallbackObject):
    def __init__(self, option_name: str, callback: Callable) -> None:
        self.callback = callback
        self.option_name = option_name


##############
# Decorators #
##############


def global_autocomplete(option_name: str) -> Callable[[AsyncCallable], GlobalAutoComplete]:
    """
    Decorator for global autocomplete functions

    Args:
        option_name: The name of the option to register the autocomplete function for

    Returns:
        The decorator

    """

    def decorator(func: Callable) -> GlobalAutoComplete:
        if not asyncio.iscoroutinefunction(func):
            raise TypeError("Autocomplete functions must be coroutines")
        return GlobalAutoComplete(option_name, func)

    return decorator


def slash_command(
    name: Absent[str | LocalisedName] = MISSING,
    *,
    description: Absent[str | LocalisedDesc] = MISSING,
    scopes: Absent[List["Snowflake_Type"]] = MISSING,
    options: Optional[List[Union[SlashCommandOption, Dict]]] = None,
    default_member_permissions: Optional["Permissions"] = None,
    integration_types: Optional[List[Union[IntegrationType, int]]] = None,
    contexts: Optional[List[Union[ContextType, int]]] = None,
    dm_permission: bool = True,
    sub_cmd_name: str | LocalisedName = None,
    group_name: str | LocalisedName = None,
    sub_cmd_description: str | LocalisedDesc = "No Description Set",
    group_description: str | LocalisedDesc = "No Description Set",
    nsfw: bool = False,
) -> Callable[[AsyncCallable], SlashCommand]:
    """
    A decorator to declare a coroutine as a slash command.

    !!! note
        While the base and group descriptions arent visible in the discord client, currently.
        We strongly advise defining them anyway, if you're using subcommands, as Discord has said they will be visible in
        one of the future ui updates.

    Args:
        name: 1-32 character name of the command, defaults to the name of the coroutine.
        description: 1-100 character description of the command
        scopes: The scope this command exists within
        options: The parameters for the command, max 25
        default_member_permissions: What permissions members need to have by default to use this command.
        integration_types: Installation context(s) where the command is available, only for globally-scoped commands.
        contexts: Interaction context(s) where the command can be used, only for globally-scoped commands.
        dm_permission: Should this command be available in DMs (deprecated).
        sub_cmd_name: 1-32 character name of the subcommand
        sub_cmd_description: 1-100 character description of the subcommand
        group_name: 1-32 character name of the group
        group_description: 1-100 character description of the group
        nsfw: This command should only work in NSFW channels

    Returns:
        SlashCommand Object

    """

    def wrapper(func: AsyncCallable) -> SlashCommand:
        if not asyncio.iscoroutinefunction(func):
            raise ValueError("Commands must be coroutines")

        perm = default_member_permissions
        if hasattr(func, "default_member_permissions"):
            if perm:
                perm = perm | func.default_member_permissions
            else:
                perm = func.default_member_permissions

        _name = name
        if _name is MISSING:
            _name = func.__name__

        _description = description
        if _description is MISSING:
            _description = func.__doc__ or "No Description Set"

        cmd = SlashCommand(
            name=_name,
            group_name=group_name,
            group_description=group_description,
            sub_cmd_name=sub_cmd_name,
            sub_cmd_description=sub_cmd_description,
            description=_description,
            scopes=scopes or [GLOBAL_SCOPE],
            default_member_permissions=perm,
            integration_types=integration_types or [IntegrationType.GUILD_INSTALL],
            contexts=contexts or [ContextType.GUILD, ContextType.BOT_DM, ContextType.PRIVATE_CHANNEL],
            dm_permission=dm_permission,
            callback=func,
            options=options,
            nsfw=nsfw,
        )

        return cmd

    return wrapper


def subcommand(
    base: str | LocalisedName,
    *,
    subcommand_group: Optional[str | LocalisedName] = None,
    name: Absent[str | LocalisedName] = MISSING,
    description: Absent[str | LocalisedDesc] = MISSING,
    base_description: Optional[str | LocalisedDesc] = None,
    base_desc: Optional[str | LocalisedDesc] = None,
    base_default_member_permissions: Optional["Permissions"] = None,
    base_integration_types: Optional[List[Union[IntegrationType, int]]] = None,
    base_contexts: Optional[List[Union[ContextType, int]]] = None,
    base_dm_permission: bool = True,
    subcommand_group_description: Optional[str | LocalisedDesc] = None,
    sub_group_desc: Optional[str | LocalisedDesc] = None,
    scopes: List["Snowflake_Type"] | None = None,
    options: List[dict] | None = None,
    nsfw: bool = False,
) -> Callable[[AsyncCallable], SlashCommand]:
    """
    A decorator specifically tailored for creating subcommands.

    Args:
        base: The name of the base command
        subcommand_group: The name of the subcommand group, if any.
        name: The name of the subcommand, defaults to the name of the coroutine.
        description: The description of the subcommand
        base_description: The description of the base command
        base_desc: An alias of `base_description`
        base_default_member_permissions: What permissions members need to have by default to use this command.
        base_integration_types: Installation context(s) where the command is available, only for globally-scoped commands.
        base_contexts: Interaction context(s) where the command can be used, only for globally-scoped commands.
        base_dm_permission: Should this command be available in DMs (deprecated).
        subcommand_group_description: Description of the subcommand group
        sub_group_desc: An alias for `subcommand_group_description`
        scopes: The scopes of which this command is available, defaults to GLOBAL_SCOPE
        options: The options for this command
        nsfw: This command should only work in NSFW channels

    Returns:
        A SlashCommand object

    """

    def wrapper(func: AsyncCallable) -> SlashCommand:
        if not asyncio.iscoroutinefunction(func):
            raise ValueError("Commands must be coroutines")

        _name = name
        if _name is MISSING:
            _name = func.__name__

        _description = description
        if _description is MISSING:
            _description = func.__doc__ or "No Description Set"

        cmd = SlashCommand(
            name=base,
            description=(base_description or base_desc) or "No Description Set",
            group_name=subcommand_group,
            group_description=(subcommand_group_description or sub_group_desc) or "No Description Set",
            sub_cmd_name=_name,
            sub_cmd_description=_description,
            default_member_permissions=base_default_member_permissions,
            integration_types=base_integration_types or [IntegrationType.GUILD_INSTALL],
            contexts=base_contexts or [ContextType.GUILD, ContextType.BOT_DM, ContextType.PRIVATE_CHANNEL],
            dm_permission=base_dm_permission,
            scopes=scopes or [GLOBAL_SCOPE],
            callback=func,
            options=options,
            nsfw=nsfw,
        )
        return cmd

    return wrapper


def context_menu(
    name: Absent[str | LocalisedName] = MISSING,
    *,
    context_type: "CommandType",
    scopes: Absent[List["Snowflake_Type"]] = MISSING,
    default_member_permissions: Optional["Permissions"] = None,
    integration_types: Optional[List[Union[IntegrationType, int]]] = None,
    contexts: Optional[List[Union[ContextType, int]]] = None,
    dm_permission: bool = True,
) -> Callable[[AsyncCallable], ContextMenu]:
    """
    A decorator to declare a coroutine as a Context Menu.

    Args:
        name: 1-32 character name of the context menu, defaults to the name of the coroutine.
        context_type: The type of context menu
        scopes: The scope this command exists within
        default_member_permissions: What permissions members need to have by default to use this command.
        integration_types: Installation context(s) where the command is available, only for globally-scoped commands.
        contexts: Interaction context(s) where the command can be used, only for globally-scoped commands.
        dm_permission: Should this command be available in DMs (deprecated).

    Returns:
        ContextMenu object

    """

    def wrapper(func: AsyncCallable) -> ContextMenu:
        if not asyncio.iscoroutinefunction(func):
            raise ValueError("Commands must be coroutines")

        perm = default_member_permissions
        if hasattr(func, "default_member_permissions"):
            if perm:
                perm = perm | func.default_member_permissions
            else:
                perm = func.default_member_permissions

        _name = name
        if _name is MISSING:
            _name = func.__name__

        cmd = ContextMenu(
            name=_name,
            type=context_type,
            scopes=scopes or [GLOBAL_SCOPE],
            default_member_permissions=perm,
            integration_types=integration_types or [IntegrationType.GUILD_INSTALL],
            contexts=contexts or [ContextType.GUILD, ContextType.BOT_DM, ContextType.PRIVATE_CHANNEL],
            dm_permission=dm_permission,
            callback=func,
        )
        return cmd

    return wrapper


def user_context_menu(
    name: Absent[str | LocalisedName] = MISSING,
    *,
    scopes: Absent[List["Snowflake_Type"]] = MISSING,
    default_member_permissions: Optional["Permissions"] = None,
    integration_types: Optional[List[Union[IntegrationType, int]]] = None,
    contexts: Optional[List[Union[ContextType, int]]] = None,
    dm_permission: bool = True,
) -> Callable[[AsyncCallable], ContextMenu]:
    """
    A decorator to declare a coroutine as a User Context Menu.

    Args:
        name: 1-32 character name of the context menu, defaults to the name of the coroutine.
        scopes: The scope this command exists within
        default_member_permissions: What permissions members need to have by default to use this command.
        integration_types: Installation context(s) where the command is available, only for globally-scoped commands.
        contexts: Interaction context(s) where the command can be used, only for globally-scoped commands.
        dm_permission: Should this command be available in DMs (deprecated).

    Returns:
        ContextMenu object

    """
    return context_menu(
        name,
        context_type=CommandType.USER,
        scopes=scopes,
        default_member_permissions=default_member_permissions,
        integration_types=integration_types or [IntegrationType.GUILD_INSTALL],
        contexts=contexts or [ContextType.GUILD, ContextType.BOT_DM, ContextType.PRIVATE_CHANNEL],
        dm_permission=dm_permission,
    )


def message_context_menu(
    name: Absent[str | LocalisedName] = MISSING,
    *,
    scopes: Absent[List["Snowflake_Type"]] = MISSING,
    default_member_permissions: Optional["Permissions"] = None,
    integration_types: Optional[List[Union[IntegrationType, int]]] = None,
    contexts: Optional[List[Union[ContextType, int]]] = None,
    dm_permission: bool = True,
) -> Callable[[AsyncCallable], ContextMenu]:
    """
    A decorator to declare a coroutine as a Message Context Menu.

    Args:
        name: 1-32 character name of the context menu, defaults to the name of the coroutine.
        scopes: The scope this command exists within
        default_member_permissions: What permissions members need to have by default to use this command.
        integration_types: Installation context(s) where the command is available, only for globally-scoped commands.
        contexts: Interaction context(s) where the command can be used, only for globally-scoped commands.
        dm_permission: Should this command be available in DMs (deprecated).

    Returns:
        ContextMenu object

    """
    return context_menu(
        name,
        context_type=CommandType.MESSAGE,
        scopes=scopes,
        default_member_permissions=default_member_permissions,
        integration_types=integration_types or [IntegrationType.GUILD_INSTALL],
        contexts=contexts or [ContextType.GUILD, ContextType.BOT_DM, ContextType.PRIVATE_CHANNEL],
        dm_permission=dm_permission,
    )


def component_callback(*custom_id: str | re.Pattern) -> Callable[[AsyncCallable], ComponentCommand]:
    """
    Register a coroutine as a component callback.

    Component callbacks work the same way as commands, just using components as a way of invoking, instead of messages.
    Your callback will be given a single argument, `ComponentContext`

    Note:
        This can optionally take a regex pattern, which will be used to match against the custom ID of the component.

        If you do not supply a `custom_id`, the name of the coroutine will be used instead.

    Args:
        *custom_id: The custom ID of the component to wait for

    """

    def wrapper(func: AsyncCallable) -> ComponentCommand:
        resolved_custom_id = custom_id or [func.__name__]

        if not asyncio.iscoroutinefunction(func):
            raise ValueError("Commands must be coroutines")

        return ComponentCommand(
            name=f"ComponentCallback::{resolved_custom_id}", callback=func, listeners=resolved_custom_id
        )

    custom_id = _unpack_helper(custom_id)
    custom_ids_validator(*custom_id)
    return wrapper


def modal_callback(*custom_id: str | re.Pattern) -> Callable[[AsyncCallable], ModalCommand]:
    """
    Register a coroutine as a modal callback.

    Modal callbacks work the same way as commands, just using modals as a way of invoking, instead of messages.
    Your callback will be given a single argument, `ModalContext`

    Note:
        This can optionally take a regex pattern, which will be used to match against the custom ID of the modal.

        If you do not supply a `custom_id`, the name of the coroutine will be used instead.


    Args:
        *custom_id: The custom ID of the modal to wait for

    """

    def wrapper(func: AsyncCallable) -> ModalCommand:
        resolved_custom_id = custom_id or [func.__name__]

        if not asyncio.iscoroutinefunction(func):
            raise ValueError("Commands must be coroutines")

        return ModalCommand(name=f"ModalCallback::{resolved_custom_id}", callback=func, listeners=resolved_custom_id)

    custom_id = _unpack_helper(custom_id)
    custom_ids_validator(*custom_id)
    return wrapper


InterCommandT = TypeVar("InterCommandT", InteractionCommand, AsyncCallable)
SlashCommandT = TypeVar("SlashCommandT", SlashCommand, AsyncCallable)


def slash_option(
    name: str,
    description: str,
    opt_type: Union[OptionType, int],
    required: bool = False,
    autocomplete: bool = False,
    choices: List[Union[SlashCommandChoice, dict]] | None = None,
    channel_types: Optional[list[Union[ChannelType, int]]] = None,
    min_value: Optional[float] = None,
    max_value: Optional[float] = None,
    min_length: Optional[int] = None,
    max_length: Optional[int] = None,
    argument_name: Optional[str] = None,
) -> Callable[[SlashCommandT], SlashCommandT]:
    r"""
    A decorator to add an option to a slash command.

    Args:
        name: 1-32 lowercase character name matching ^[\w-]{1,32}$
        opt_type: The type of option
        description: 1-100 character description of option
        required: If the parameter is required or optional--default false
        autocomplete: If autocomplete interactions are enabled for this STRING, INTEGER, or NUMBER type option
        choices: A list of choices the user has to pick between (max 25)
        channel_types: The channel types permitted. The option needs to be a channel
        min_value: The minimum value permitted. The option needs to be an integer or float
        max_value: The maximum value permitted. The option needs to be an integer or float
        min_length: The minimum length of text a user can input. The option needs to be a string
        max_length: The maximum length of text a user can input. The option needs to be a string
        argument_name: The name of the argument to be used in the function. If not given, assumed to be the same as the name of the option

    """

    def wrapper(func: SlashCommandT) -> SlashCommandT:
        if hasattr(func, "cmd_id"):
            raise ValueError("slash_option decorators must be positioned under a slash_command decorator")

        option = SlashCommandOption(
            name=name,
            type=opt_type,
            description=description,
            required=required,
            autocomplete=autocomplete,
            choices=choices or [],
            channel_types=channel_types,
            min_value=min_value,
            max_value=max_value,
            min_length=min_length,
            max_length=max_length,
            argument_name=argument_name,
        )
        if not hasattr(func, "options"):
            func.options = []
        func.options.insert(0, option)
        return func

    return wrapper


def slash_default_member_permission(
    permission: "Permissions",
) -> Callable[[SlashCommandT], SlashCommandT]:
    """
    A decorator to permissions members need to have by default to use a command.

    Args:
        permission: The permissions to require for to this command

    """

    def wrapper(func: SlashCommandT) -> SlashCommandT:
        if hasattr(func, "cmd_id"):
            raise ValueError(
                "slash_default_member_permission decorators must be positioned under a slash_command decorator"
            )

        if not hasattr(func, "default_member_permissions") or func.default_member_permissions is None:
            func.default_member_permissions = permission
        else:
            func.default_member_permissions = func.default_member_permissions | permission
        return func

    return wrapper


def auto_defer(
    enabled: bool = True, ephemeral: bool = False, time_until_defer: float = 0.0
) -> Callable[[InterCommandT], InterCommandT]:
    """
    A decorator to add an auto defer to a application command.

    Args:
        enabled: Should the command be deferred automatically
        ephemeral: Should the command be deferred as ephemeral
        time_until_defer: How long to wait before deferring automatically

    """

    def wrapper(func: InterCommandT) -> InterCommandT:
        if hasattr(func, "cmd_id"):
            raise ValueError("auto_defer decorators must be positioned under a slash_command decorator")
        func.auto_defer = AutoDefer(enabled=enabled, ephemeral=ephemeral, time_until_defer=time_until_defer)
        return func

    return wrapper


def integration_types(guild: bool = True, user: bool = False) -> Callable[[InterCommandT], InterCommandT]:
    """
    A decorator to set integration types for an application command.

    Args:
        guild: Should the command be available for guilds
        user: Should the command be available for individual users

    """
    kwargs = locals()

    def wrapper(func: InterCommandT) -> InterCommandT:
        if hasattr(func, "cmd_id"):
            raise ValueError("integration_types decorators must be positioned under a command decorator")

        func.integration_types = []
        for key in kwargs:
            if kwargs[key]:
                func.integration_types.append(IntegrationType[key.upper() + "_INSTALL"])

        return func

    return wrapper


def contexts(
    guild: bool = True, bot_dm: bool = True, private_channel: bool = True
) -> Callable[[InterCommandT], InterCommandT]:
    """
    A decorator to set contexts where the command can be used for a application command.

    Args:
        guild: Should the command be available in guilds
        bot_dm: Should the command be available in bot DMs
        private_channel: Should the command be available in private channels

    """
    kwargs = locals()

    def wrapper(func: InterCommandT) -> InterCommandT:
        if hasattr(func, "cmd_id"):
            raise ValueError("contexts decorators must be positioned under a command decorator")

        func.contexts = []
        for key in kwargs:
            if kwargs[key]:
                func.contexts.append(ContextType[key.upper()])

        return func

    return wrapper


def application_commands_to_dict(  # noqa: C901
    commands: Dict["Snowflake_Type", Dict[str, InteractionCommand]], client: "Client"
) -> dict:
    """
    Convert the command list into a format that would be accepted by discord.

    `Client.interactions` should be the variable passed to this

    """
    cmd_bases: defaultdict[str, list[InteractionCommand]] = defaultdict(list)  # {cmd_base: [commands]}
    """A store of commands organised by their base command"""
    output: defaultdict["Snowflake_Type", list[dict]] = defaultdict(list)
    """The output dictionary"""

    def squash_subcommand(subcommands: List) -> Dict:
        output_data = {}
        groups = {}
        sub_cmds = []
        for subcommand in subcommands:
            if not output_data:
                output_data = {
                    "name": str(subcommand.name),
                    "description": str(subcommand.description),
                    "options": [],
                    "default_member_permissions": (
                        str(int(subcommand.default_member_permissions))
                        if subcommand.default_member_permissions
                        else None
                    ),
                    "integration_types": subcommand.integration_types,
                    "contexts": subcommand.contexts,
                    "name_localizations": subcommand.name.to_locale_dict(),
                    "description_localizations": subcommand.description.to_locale_dict(),
                    "nsfw": subcommand.nsfw,
                }
            if bool(subcommand.group_name):
                if str(subcommand.group_name) not in groups:
                    groups[str(subcommand.group_name)] = {
                        "name": str(subcommand.group_name),
                        "description": str(subcommand.group_description),
                        "type": int(OptionType.SUB_COMMAND_GROUP),
                        "options": [],
                        "name_localizations": subcommand.group_name.to_locale_dict(),
                        "description_localizations": subcommand.group_description.to_locale_dict(),
                    }
                groups[str(subcommand.group_name)]["options"].append(
                    subcommand.to_dict() | {"type": int(OptionType.SUB_COMMAND)}
                )
            elif subcommand.is_subcommand:
                sub_cmds.append(subcommand.to_dict() | {"type": int(OptionType.SUB_COMMAND)})
        options = list(groups.values()) + sub_cmds
        output_data["options"] = options
        return output_data

    for _scope, cmds in commands.items():
        for cmd in cmds.values():
            cmd_name = str(cmd.name)
            if cmd not in cmd_bases[cmd_name]:
                cmd_bases[cmd_name].append(cmd)

    for cmd_list in cmd_bases.values():
        if any(c.is_subcommand for c in cmd_list):
            # validate all commands share required attributes
            scopes: list[Snowflake_Type] = list({s for c in cmd_list for s in c.scopes})
            base_description = next(
                (
                    c.description
                    for c in cmd_list
                    if str(c.description) is not None and str(c.description) != "No Description Set"
                ),
                "No Description Set",
            )
            nsfw = cmd_list[0].nsfw

            if any(str(c.description) not in (str(base_description), "No Description Set") for c in cmd_list):
                client.logger.warning(
                    f"Conflicting descriptions found in `{cmd_list[0].name}` subcommands; `{base_description!s}` will be used"
                )
            if any(c.default_member_permissions != cmd_list[0].default_member_permissions for c in cmd_list):
                raise ValueError(f"Conflicting `default_member_permissions` values found in `{cmd_list[0].name}`")
            if any(c.contexts != cmd_list[0].contexts for c in cmd_list):
                raise ValueError(f"Conflicting `contexts` values found in `{cmd_list[0].name}`")
            if any(c.integration_types != cmd_list[0].integration_types for c in cmd_list):
                raise ValueError(f"Conflicting `integration_types` values found in `{cmd_list[0].name}`")
            if any(c.dm_permission != cmd_list[0].dm_permission for c in cmd_list):
                raise ValueError(f"Conflicting `dm_permission` values found in `{cmd_list[0].name}`")
            if any(c.nsfw != nsfw for c in cmd_list):
                client.logger.warning(f"Conflicting `nsfw` values found in {cmd_list[0].name} - `True` will be used")
                nsfw = True

            for cmd in cmd_list:
                cmd.scopes = list(scopes)
                cmd.description = base_description
                cmd.nsfw = nsfw
            # end validation of attributes
            cmd_data = squash_subcommand(cmd_list)

            for s in scopes:
                output[s].append(cmd_data)
        else:
            for cmd in cmd_list:
                for s in cmd.scopes:
                    output[s].append(cmd.to_dict())
    return dict(output)


def _compare_commands(local_cmd: dict, remote_cmd: dict) -> bool:
    """
    Compares remote and local commands

    Args:
        local_cmd: The local command
        remote_cmd: The remote command from discord

    Returns:
        True if the commands are the same

    """
    lookup: dict[str, tuple[str, any]] = {
        "name": ("name", ""),
        "description": ("description", ""),
        "default_member_permissions": ("default_member_permissions", None),
        "name_localized": ("name_localizations", None),
        "description_localized": ("description_localizations", None),
        "integration_types": ("integration_types", [IntegrationType.GUILD_INSTALL]),
        "contexts": ("contexts", [ContextType.GUILD, ContextType.BOT_DM, ContextType.PRIVATE_CHANNEL]),
    }
    if remote_cmd.get("guild_id"):
        # non-global command
        del lookup["contexts"]

    for local_name, comparison_data in lookup.items():
        remote_name, default_value = comparison_data
        if local_cmd.get(local_name, default_value) != remote_cmd.get(remote_name, default_value):
            return False
    return True


def _compare_options(local_opt_list: dict, remote_opt_list: dict) -> bool:
    if local_opt_list != remote_opt_list:
        post_process: Dict[str, Callable] = {
            "choices": lambda l10n: [d | {"name_localizations": {}} if len(d) == 2 else d for d in l10n],
        }

        if len(local_opt_list) != len(remote_opt_list):
            return False
        options_lookup: dict[str, tuple[str, any]] = {
            "name": ("name", ""),
            "description": ("description", ""),
            "required": ("required", False),
            "autocomplete": ("autocomplete", False),
            "name_localized": ("name_localizations", None),
            "description_localized": ("description_localizations", None),
            "channel_types": ("channel_types", None),
            "choices": ("choices", []),
            "max_value": ("max_value", None),
            "min_value": ("min_value", None),
            "max_length": ("max_length", None),
            "min_length": ("min_length", None),
        }
        for i in range(len(local_opt_list)):
            local_option = local_opt_list[i]
            remote_option = remote_opt_list[i]

            if local_option["type"] != remote_option["type"]:
                return False
            if local_option["type"] in (OptionType.SUB_COMMAND_GROUP, OptionType.SUB_COMMAND):
                if not _compare_commands(local_option, remote_option) or not _compare_options(
                    local_option.get("options", []), remote_option.get("options", [])
                ):
                    return False
            else:
                for local_name, comparison_data in options_lookup.items():
                    remote_name, default_value = comparison_data
                    if local_option.get(local_name, default_value) != post_process.get(remote_name, lambda name: name)(
                        remote_option.get(remote_name, default_value)
                    ):
                        return False

    return True


def sync_needed(local_cmd: dict, remote_cmd: Optional[dict] = None) -> bool:
    """
    Compares a local application command to its remote counterpart to determine if a sync is required.

    Args:
        local_cmd: The local json representation of the command
        remote_cmd: The json representation of the command from Discord

    Returns:
        Boolean indicating if a sync is needed

    """
    if not remote_cmd:
        # No remote version, command must be new
        return True

    if not _compare_commands(local_cmd, remote_cmd):
        # basic comparison of attributes
        return True

    if remote_cmd["type"] == CommandType.CHAT_INPUT:
        try:
            if not _compare_options(local_cmd["options"], remote_cmd["options"]):
                # options are not the same, sync needed
                return True
        except KeyError:
            if "options" in local_cmd or "options" in remote_cmd:
                return True

    return False

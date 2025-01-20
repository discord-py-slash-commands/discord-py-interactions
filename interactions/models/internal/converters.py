import re
import typing
from typing import Any, Optional, List, Annotated

from interactions.client.const import T, T_co, Sentinel
from interactions.client.errors import BadArgument
from interactions.client.errors import Forbidden, HTTPException
from interactions.models.discord.channel import (
    BaseChannel,
    DMChannel,
    DM,
    DMGroup,
    GuildChannel,
    GuildCategory,
    GuildNews,
    GuildText,
    ThreadChannel,
    GuildNewsThread,
    GuildPublicThread,
    GuildPrivateThread,
    VoiceChannel,
    GuildVoice,
    GuildStageVoice,
    TYPE_ALL_CHANNEL,
    TYPE_DM_CHANNEL,
    TYPE_GUILD_CHANNEL,
    TYPE_THREAD_CHANNEL,
    TYPE_VOICE_CHANNEL,
    TYPE_MESSAGEABLE_CHANNEL,
)
from interactions.models.discord.emoji import PartialEmoji, CustomEmoji
from interactions.models.discord.guild import Guild
from interactions.models.discord.message import Message
from interactions.models.discord.role import Role
from interactions.models.discord.snowflake import SnowflakeObject
from interactions.models.discord.user import User, Member
from interactions.models.internal.context import BaseContext
from interactions.models.internal.protocols import Converter

__all__ = (
    "MODEL_TO_CONVERTER",
    "BaseChannelConverter",
    "ChannelConverter",
    "ConsumeRest",
    "CustomEmojiConverter",
    "DMChannelConverter",
    "DMConverter",
    "DMGroupConverter",
    "Greedy",
    "GuildCategoryConverter",
    "GuildChannelConverter",
    "GuildConverter",
    "GuildNewsConverter",
    "GuildNewsThreadConverter",
    "GuildPrivateThreadConverter",
    "GuildPublicThreadConverter",
    "GuildStageVoiceConverter",
    "GuildTextConverter",
    "GuildVoiceConverter",
    "IDConverter",
    "MemberConverter",
    "MessageConverter",
    "MessageableChannelConverter",
    "NoArgumentConverter",
    "PartialEmojiConverter",
    "RoleConverter",
    "SnowflakeConverter",
    "ThreadChannelConverter",
    "UserConverter",
    "VoiceChannelConverter",
)


class NoArgumentConverter(Converter[T_co]):
    """
    An indicator class for special type of converters that only uses the Context.

    This is mainly needed for prefixed commands, as arguments will be "eaten up" by converters otherwise.
    """


class _LiteralConverter(Converter):
    values: dict

    def __init__(self, args: Any) -> None:
        self.values = {arg: type(arg) for arg in args}

    async def convert(self, ctx: BaseContext, argument: str) -> Any:
        for arg, converter in self.values.items():
            try:
                if (converted := converter(argument)) == arg:
                    return converted
            except Exception:
                continue

        literals_list = [str(a) for a in self.values.keys()]
        literals_str = ", ".join(literals_list[:-1]) + f", or {literals_list[-1]}"
        raise BadArgument(f'Could not convert "{argument}" into one of {literals_str}.')


_ID_REGEX = re.compile(r"([0-9]{15,})$")


class IDConverter(Converter[T_co]):
    """The base converter for objects that have snowflake IDs."""

    @staticmethod
    def _get_id_match(argument: str) -> Optional[re.Match[str]]:
        return _ID_REGEX.match(argument)


class SnowflakeConverter(IDConverter[SnowflakeObject]):
    """Converts a string argument to a SnowflakeObject."""

    async def convert(self, ctx: BaseContext, argument: str) -> SnowflakeObject:
        """
        Converts a given string to a SnowflakeObject.

        The lookup strategy is as follows:

        1. By raw snowflake ID.

        2. By role or channel mention.

        Args:
            ctx: The context to use for the conversion.
            argument: The argument to be converted.

        Returns:
            SnowflakeObject: The converted object.

        """
        match = self._get_id_match(argument) or re.match(r"<(?:@(?:!|&)?|#)([0-9]{15,})>$", argument)

        if match is None:
            raise BadArgument(argument)

        return SnowflakeObject(int(match.group(1)))  # type: ignore


class ChannelConverter(IDConverter[T_co]):
    """The base converter for channel objects."""

    def _check(self, result: BaseChannel) -> bool:
        return True

    async def convert(self, ctx: BaseContext, argument: str) -> T_co:
        """
        Converts a given string to a Channel object.

        The lookup strategy is as follows:

        1. By raw snowflake ID.

        2. By channel mention.

        3. By name - the bot will search in a guild if the context has it, otherwise it will search globally.

        Args:
            ctx: The context to use for the conversion.
            argument: The argument to be converted.

        Returns:
            BaseChannel: The converted object.
            The channel type will be of the type the converter represents.

        """
        match = self._get_id_match(argument) or re.match(r"<#([0-9]{15,})>$", argument)
        result = None

        if match:
            result = await ctx.bot.fetch_channel(int(match.group(1)))
        elif ctx.guild:
            result = next((c for c in ctx.guild.channels if c.name == argument), None)
        else:
            result = next((c for c in ctx.bot.cache.channel_cache.values() if c.name == argument), None)

        if not result:
            raise BadArgument(f'Channel "{argument}" not found.')

        if self._check(result):
            return result  # type: ignore

        raise BadArgument(f'Channel "{argument}" not found.')


class BaseChannelConverter(ChannelConverter[BaseChannel]):
    pass


class DMChannelConverter(ChannelConverter[DMChannel]):
    def _check(self, result: BaseChannel) -> bool:
        return isinstance(result, DMChannel)


class DMConverter(ChannelConverter[DM]):
    def _check(self, result: BaseChannel) -> bool:
        return isinstance(result, DM)


class DMGroupConverter(ChannelConverter[DMGroup]):
    def _check(self, result: BaseChannel) -> bool:
        return isinstance(result, DMGroup)


class GuildChannelConverter(ChannelConverter[GuildChannel]):
    def _check(self, result: BaseChannel) -> bool:
        return isinstance(result, GuildChannel)


class GuildNewsConverter(ChannelConverter[GuildNews]):
    def _check(self, result: BaseChannel) -> bool:
        return isinstance(result, GuildNews)


class GuildCategoryConverter(ChannelConverter[GuildCategory]):
    def _check(self, result: BaseChannel) -> bool:
        return isinstance(result, GuildCategory)


class GuildTextConverter(ChannelConverter[GuildText]):
    def _check(self, result: BaseChannel) -> bool:
        return isinstance(result, GuildText)


class ThreadChannelConverter(ChannelConverter[ThreadChannel]):
    def _check(self, result: BaseChannel) -> bool:
        return isinstance(result, ThreadChannel)


class GuildNewsThreadConverter(ChannelConverter[GuildNewsThread]):
    def _check(self, result: BaseChannel) -> bool:
        return isinstance(result, GuildNewsThread)


class GuildPublicThreadConverter(ChannelConverter[GuildPublicThread]):
    def _check(self, result: BaseChannel) -> bool:
        return isinstance(result, GuildPublicThread)


class GuildPrivateThreadConverter(ChannelConverter[GuildPrivateThread]):
    def _check(self, result: BaseChannel) -> bool:
        return isinstance(result, GuildPrivateThread)


class VoiceChannelConverter(ChannelConverter[VoiceChannel]):
    def _check(self, result: BaseChannel) -> bool:
        return isinstance(result, VoiceChannel)


class GuildVoiceConverter(ChannelConverter[GuildVoice]):
    def _check(self, result: BaseChannel) -> bool:
        return isinstance(result, GuildVoice)


class GuildStageVoiceConverter(ChannelConverter[GuildStageVoice]):
    def _check(self, result: BaseChannel) -> bool:
        return isinstance(result, GuildStageVoice)


_MESSAGEABLE_CHANNEL_TYPES = typing.get_args(TYPE_MESSAGEABLE_CHANNEL)


class MessageableChannelConverter(ChannelConverter[TYPE_MESSAGEABLE_CHANNEL]):
    def _check(self, result: BaseChannel) -> bool:
        return isinstance(result, _MESSAGEABLE_CHANNEL_TYPES)


class UserConverter(IDConverter[User]):
    """Converts a string argument to a User object."""

    async def convert(self, ctx: BaseContext, argument: str) -> User:
        """
        Converts a given string to a User object.

        The lookup strategy is as follows:

        1. By raw snowflake ID.

        2. By mention.

        3. By username + tag (ex User#1234).

        4. By username.

        Args:
            ctx: The context to use for the conversion.
            argument: The argument to be converted.

        Returns:
            User: The converted object.

        """
        match = self._get_id_match(argument) or re.match(r"<@!?([0-9]{15,})>$", argument)
        result = None

        if match:
            result = await ctx.bot.fetch_user(int(match.group(1)))
        else:
            if len(argument) > 5 and argument[-5] == "#":
                result = next((u for u in ctx.bot.cache.user_cache.values() if u.tag == argument), None)

            if not result:
                result = next((u for u in ctx.bot.cache.user_cache.values() if u.username == argument), None)

        if not result:
            raise BadArgument(f'User "{argument}" not found.')

        return result


class MemberConverter(IDConverter[Member]):
    """Converts a string argument to a Member object."""

    def _get_member_from_list(self, members: list[Member], argument: str) -> Optional[Member]:
        # sourcery skip: assign-if-exp
        result = None
        if len(argument) > 5 and argument[-5] == "#":
            result = next((m for m in members if m.user.tag == argument), None)

        if not result:
            result = next(
                (m for m in members if m.display_name == argument or m.user.username == argument),
                None,
            )

        return result

    async def convert(self, ctx: BaseContext, argument: str) -> Member:
        """
        Converts a given string to a Member object. This will only work in guilds.

        The lookup strategy is as follows:

        1. By raw snowflake ID.

        2. By mention.

        3. By username + tag (ex User#1234).

        4. By nickname.

        5. By username.

        Args:
            ctx: The context to use for the conversion.
            argument: The argument to be converted.

        Returns:
            Member: The converted object.

        """
        if not ctx.guild:
            raise BadArgument("This command cannot be used in private messages.")

        match = self._get_id_match(argument) or re.match(r"<@!?([0-9]{15,})>$", argument)
        result = None

        if match:
            result = await ctx.guild.fetch_member(int(match.group(1)))
        elif ctx.guild.chunked:
            result = self._get_member_from_list(ctx.guild.members, argument)
        else:
            query = argument
            if len(argument) > 5 and argument[-5] == "#":
                query, _, _ = argument.rpartition("#")

            members = await ctx.guild.search_members(query, limit=100)
            result = self._get_member_from_list(members, argument)

        if not result:
            raise BadArgument(f'Member "{argument}" not found.')

        return result


class MessageConverter(Converter[Message]):
    """Converts a string argument to a Message object."""

    # either just the id or <chan_id>-<mes_id>, a format you can get by shift clicking "copy id"
    _ID_REGEX = re.compile(r"(?:(?P<channel_id>[0-9]{15,})-)?(?P<message_id>[0-9]{15,})")
    # of course, having a way to get it from a link is nice
    _MESSAGE_LINK_REGEX = re.compile(
        r"https?://[\S]*?discord(?:app)?\.com/channels/(?P<guild_id>[0-9]{15,}|@me)/(?P<channel_id>[0-9]{15,})/(?P<message_id>[0-9]{15,})\/?$"
    )

    async def convert(self, ctx: BaseContext, argument: str) -> Message:
        """
        Converts a given string to a Message object.

        The lookup strategy is as follows:

        1. By raw snowflake ID. The message must be in the same channel as the context.

        2. By message + channel ID in the format of "{Channel ID}-{Message ID}". This can be obtained by shift clicking "Copy ID" when Developer Mode is enabled.

        3. By message link.

        Args:
            ctx: The context to use for the conversion.
            argument: The argument to be converted.

        Returns:
            Message: The converted object.

        """
        match = self._ID_REGEX.match(argument) or self._MESSAGE_LINK_REGEX.match(argument)
        if not match:
            raise BadArgument(f'Message "{argument}" not found.')

        data = match.groupdict()

        message_id = data["message_id"]
        channel_id = int(data["channel_id"]) if data.get("channel_id") else ctx.channel.id

        # this guild checking is technically unnecessary, but we do it just in case
        # it means a user cant just provide an invalid guild id and still get a message
        guild_id = data["guild_id"] if data.get("guild_id") else ctx.guild_id
        guild_id = int(guild_id) if guild_id != "@me" else None

        try:
            # this takes less possible requests than getting the guild and/or channel
            mes = await ctx.bot.cache.fetch_message(channel_id, message_id)
            if mes._guild_id != guild_id:
                raise BadArgument(f'Message "{argument}" not found.')
            return mes
        except Forbidden as e:
            raise BadArgument(f"Cannot read messages for <#{channel_id}>.") from e
        except HTTPException as e:
            raise BadArgument(f'Message "{argument}" not found.') from e


class GuildConverter(IDConverter[Guild]):
    """Converts a string argument to a Guild object."""

    async def convert(self, ctx: BaseContext, argument: str) -> Guild:
        """
        Converts a given string to a Guild object.

        The lookup strategy is as follows:

        1. By raw snowflake ID.

        2. By name.

        Args:
            ctx: The context to use for the conversion.
            argument: The argument to be converted.

        Returns:
            Guild: The converted object.

        """
        match = self._get_id_match(argument)
        result = None

        if match:
            result = await ctx.bot.fetch_guild(int(match.group(1)))
        else:
            result = next((g for g in ctx.bot.guilds if g.name == argument), None)

        if not result:
            raise BadArgument(f'Guild "{argument}" not found.')

        return result


class RoleConverter(IDConverter[Role]):
    """Converts a string argument to a Role object."""

    async def convert(self, ctx: BaseContext, argument: str) -> Role:
        """
        Converts a given string to a Role object.

        The lookup strategy is as follows:

        1. By raw snowflake ID.

        2. By mention.

        3. By name.

        Args:
            ctx: The context to use for the conversion.
            argument: The argument to be converted.

        Returns:
            Role: The converted object.

        """
        if not ctx.guild:
            raise BadArgument("This command cannot be used in private messages.")

        match = self._get_id_match(argument) or re.match(r"<@&([0-9]{15,})>$", argument)
        result = None

        if match:
            result = await ctx.guild.fetch_role(int(match.group(1)))
        else:
            result = next((r for r in ctx.guild.roles if r.name == argument), None)

        if not result:
            raise BadArgument(f'Role "{argument}" not found.')

        return result


class PartialEmojiConverter(IDConverter[PartialEmoji]):
    """Converts a string argument to a PartialEmoji object."""

    async def convert(self, ctx: BaseContext, argument: str) -> PartialEmoji:
        """
        Converts a given string to a PartialEmoji object.

        This converter only accepts emoji strings.

        Args:
            ctx: The context to use for the conversion.
            argument: The argument to be converted.

        Returns:
            PartialEmoji: The converted object.

        """
        if match := re.match(r"<a?:[a-zA-Z0-9\_]{1,32}:([0-9]{15,})>$", argument):
            emoji_animated = bool(match[1])
            emoji_name = match[2]
            emoji_id = int(match[3])

            return PartialEmoji(id=emoji_id, name=emoji_name, animated=emoji_animated)  # type: ignore

        raise BadArgument(f'Couldn\'t convert "{argument}" to {PartialEmoji.__name__}.')


class CustomEmojiConverter(IDConverter[CustomEmoji]):
    """Converts a string argument to a CustomEmoji object."""

    async def convert(self, ctx: BaseContext, argument: str) -> CustomEmoji:
        """
        Converts a given string to a CustomEmoji object.

        The lookup strategy is as follows:

        1. By raw snowflake ID.

        2. By the emoji string format.

        3. By name.

        Args:
            ctx: The context to use for the conversion.
            argument: The argument to be converted.

        Returns:
            CustomEmoji: The converted object.

        """
        if not ctx.guild:
            raise BadArgument("This command cannot be used in private messages.")

        match = self._get_id_match(argument) or re.match(r"<a?:[a-zA-Z0-9\_]{1,32}:([0-9]{15,})>$", argument)
        result = None

        if match:
            result = await ctx.guild.fetch_custom_emoji(int(match.group(1)))
        else:
            if ctx.bot.cache.enable_emoji_cache:
                emojis = ctx.bot.cache.emoji_cache.values()  # type: ignore
                result = next((e for e in emojis if e.name == argument))

            if not result:
                emojis = await ctx.guild.fetch_all_custom_emojis()
                result = next((e for e in emojis if e.name == argument))

        if not result:
            raise BadArgument(f'Emoji "{argument}" not found.')

        return result


class Greedy(List[T]):
    """A special marker class to mark an argument in a prefixed command to repeatedly convert until it fails to convert an argument."""


class ConsumeRestMarker(Sentinel):
    pass


CONSUME_REST_MARKER = ConsumeRestMarker()

ConsumeRest = Annotated[T, CONSUME_REST_MARKER]
"""A special marker type alias to mark an argument in a prefixed command to consume the rest of the arguments."""

MODEL_TO_CONVERTER: dict[type, type[Converter]] = {
    SnowflakeObject: SnowflakeConverter,
    BaseChannel: BaseChannelConverter,
    DMChannel: DMChannelConverter,
    DM: DMConverter,
    DMGroup: DMGroupConverter,
    GuildChannel: GuildChannelConverter,
    GuildNews: GuildNewsConverter,
    GuildCategory: GuildCategoryConverter,
    GuildText: GuildTextConverter,
    ThreadChannel: ThreadChannelConverter,
    GuildNewsThread: GuildNewsThreadConverter,
    GuildPublicThread: GuildPublicThreadConverter,
    GuildPrivateThread: GuildPrivateThreadConverter,
    VoiceChannel: VoiceChannelConverter,
    GuildVoice: GuildVoiceConverter,
    GuildStageVoice: GuildStageVoiceConverter,
    TYPE_ALL_CHANNEL: BaseChannelConverter,
    TYPE_DM_CHANNEL: DMChannelConverter,
    TYPE_GUILD_CHANNEL: GuildChannelConverter,
    TYPE_THREAD_CHANNEL: ThreadChannelConverter,
    TYPE_VOICE_CHANNEL: VoiceChannelConverter,
    TYPE_MESSAGEABLE_CHANNEL: MessageableChannelConverter,
    User: UserConverter,
    Member: MemberConverter,
    Message: MessageConverter,
    Guild: GuildConverter,
    Role: RoleConverter,
    PartialEmoji: PartialEmojiConverter,
    CustomEmoji: CustomEmojiConverter,
}
"""A dictionary mapping of interactions objects to their corresponding converters."""

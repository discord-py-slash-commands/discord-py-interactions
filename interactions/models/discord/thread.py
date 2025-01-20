from typing import TYPE_CHECKING, List, Dict, Any, Union, Optional

import attrs

import interactions.models as models
from interactions.client.const import MISSING
from interactions.client.mixins.serialization import DictSerializationMixin
from interactions.client.mixins.send import SendMixin
from interactions.client.utils.attr_converters import optional
from interactions.client.utils.attr_converters import timestamp_converter
from interactions.models.discord.emoji import PartialEmoji, process_emoji
from interactions.models.discord.snowflake import to_snowflake
from interactions.models.discord.timestamp import Timestamp
from .base import DiscordObject, ClientObject

if TYPE_CHECKING:
    from aiohttp import FormData

    from interactions.client import Client
    from interactions.models.discord.user import User
    from interactions.models.discord.channel import TYPE_THREAD_CHANNEL
    from interactions.models.discord.snowflake import Snowflake_Type
    from interactions import UPLOADABLE_TYPE, GuildForum

__all__ = (
    "DefaultReaction",
    "ThreadList",
    "ThreadMember",
    "ThreadTag",
    "process_default_reaction",
    "process_thread_tag",
)


@attrs.define(eq=False, order=False, hash=False, kw_only=True)
class ThreadMember(DiscordObject, SendMixin):
    """A thread member is used to indicate whether a user has joined a thread or not."""

    join_timestamp: Timestamp = attrs.field(repr=False, converter=timestamp_converter)
    """The time the current user last joined the thread."""
    flags: int = attrs.field(
        repr=False,
    )
    """Any user-thread settings, currently only used for notifications."""

    _user_id: "Snowflake_Type" = attrs.field(repr=False, converter=optional(to_snowflake))

    async def fetch_thread(self, *, force: bool = False) -> "TYPE_THREAD_CHANNEL":
        """
        Fetches the thread associated with with this member.

        Args:
            force: Whether to force a fetch from the API

        Returns:
            The thread in question

        """
        return await self._client.cache.fetch_channel(self.id, force=force)

    def get_thread(self) -> "TYPE_THREAD_CHANNEL":
        """
        Gets the thread associated with with this member.

        Returns:
            The thread in question

        """
        return self._client.cache.get_channel(self.id)

    async def fetch_user(self, *, force: bool = False) -> "User":
        """
        Fetch the user associated with this thread member.

        Args:
            force: Whether to force a fetch from the API

        Returns:
            The user object

        """
        return await self._client.cache.fetch_user(self._user_id, force=force)

    def get_user(self) -> "User":
        """
        Get the user associated with this thread member.

        Returns:
            The user object

        """
        return self._client.cache.get_user(self._user_id)

    async def _send_http_request(
        self, message_payload: Union[dict, "FormData"], files: list["UPLOADABLE_TYPE"] | None = None
    ) -> dict:
        dm_id = await self._client.cache.fetch_dm_channel_id(self._user_id)
        return await self._client.http.create_message(message_payload, dm_id, files=files)


@attrs.define(eq=False, order=False, hash=False, kw_only=True)
class ThreadList(ClientObject):
    """Represents a list of one or more threads."""

    threads: List["TYPE_THREAD_CHANNEL"] = attrs.field(
        repr=False, factory=list
    )  # TODO Reference the cache or store actual object?
    """The active threads."""
    members: List[ThreadMember] = attrs.field(repr=False, factory=list)
    """A thread member object for each returned thread the current user has joined."""
    has_more: bool = attrs.field(repr=False, default=False)
    """Whether there are potentially additional threads that could be returned on a subsequent call."""

    @classmethod
    def _process_dict(cls, data: Dict[str, Any], client: "Client") -> Dict[str, Any]:
        threads = [client.cache.place_channel_data(thread_data) for thread_data in data["threads"]]
        data["threads"] = threads

        data["members"] = ThreadMember.from_list(data["members"], client)

        return data


@attrs.define(eq=False, order=False, hash=False, kw_only=True)
class ThreadTag(DiscordObject):
    name: str = attrs.field(
        repr=False,
    )
    moderated: bool = attrs.field(repr=False)
    emoji_id: "Snowflake_Type | None" = attrs.field(repr=False, default=None)
    emoji_name: str | None = attrs.field(repr=False, default=None)

    _parent_channel_id: "Snowflake_Type" = attrs.field(repr=False, default=MISSING)

    @classmethod
    def create(
        cls,
        name: str,
        *,
        moderated: bool = False,
        emoji: Union["models.PartialEmoji", dict, str, None] = None,
    ) -> "ThreadTag":
        """
        Create a new thread tag - this is useful if you're making a new forum

        !!! warning
            This does not create the tag on Discord, it only creates a local object
            Do not expect the tag to contain valid values or for its methods to work

        Args:
            name: The name for this tag
            moderated: Whether this tag is moderated
            emoji: The emoji for this tag

        Returns:
            This object

        """
        if emoji := models.process_emoji(emoji):
            return cls(
                client=None,
                moderated=moderated,
                id=0,
                name=name,
                emoji_id=emoji.get("id"),
                emoji_name=emoji.get("name"),
            )
        return cls(client=None, moderated=moderated, id=0, name=name)

    @property
    def parent_channel(self) -> "GuildForum":
        """The parent forum for this tag."""
        return self._client.get_channel(self._parent_channel_id)

    async def edit(
        self, *, name: Optional[str] = None, emoji: Union["models.PartialEmoji", dict, str, None] = None
    ) -> "ThreadTag":
        """
        Edit this tag

        Args:
            name: The name for this tag
            emoji: The emoji for this tag

        Returns:
            This object

        """
        if isinstance(emoji, str):
            emoji = PartialEmoji.from_str(emoji)
        elif isinstance(emoji, dict):
            emoji = PartialEmoji.from_dict(emoji)

        if emoji.id:
            data = await self._client.http.edit_tag(self._parent_channel_id, self.id, name, emoji_id=emoji.id)
        else:
            data = await self._client.http.edit_tag(self._parent_channel_id, self.id, name, emoji_name=emoji.name)

        self._client.cache.place_channel_data(data)

        for tag in data["available_tags"]:
            if tag.id == self.id:
                self.name = tag.name
                self.emoji_id = tag.emoji_id
                self.emoji_name = tag.emoji_name
                break

        return self

    async def delete(self) -> None:
        """Delete this tag."""
        data = await self._client.http.delete_tag(self._parent_channel_id, self.id)
        self._client.cache.place_channel_data(data)


@attrs.define(eq=False, order=False, hash=False, kw_only=True)
class DefaultReaction(DictSerializationMixin):
    """Represents a default reaction for a forum."""

    emoji_id: "Snowflake_Type | None" = attrs.field(default=None)
    emoji_name: str | None = attrs.field(default=None)

    @classmethod
    def from_emoji(cls, emoji: PartialEmoji) -> "DefaultReaction":
        """Create a default reaction from an emoji."""
        if emoji.id:
            return cls(emoji_id=emoji.id)
        return cls(emoji_name=emoji.name)


def process_thread_tag(tag: Optional[dict | ThreadTag]) -> Optional[dict]:
    """
    Processes the tag parameter into the dictionary format required by the API.

    Args:
        tag: The tag to process

    Returns:
        formatted dictionary for discrd

    """
    if not tag:
        return tag

    if isinstance(tag, ThreadTag):
        return tag.to_dict()

    if isinstance(tag, dict):
        return tag

    raise ValueError(f"Invalid tag: {tag}")


def process_default_reaction(reaction: Optional[dict | DefaultReaction | PartialEmoji | str]) -> Optional[dict]:
    """
    Processes the reaction parameter into the dictionary format required by the API.

    Args:
        reaction: The reaction to process.

    Returns:
        formatted dictionary for discrd

    """
    if not reaction:
        return reaction

    if isinstance(reaction, dict):
        return reaction

    if not isinstance(reaction, DefaultReaction):
        emoji = process_emoji(reaction)
        if emoji_id := emoji.get("id"):
            reaction = DefaultReaction(emoji_id=emoji_id)
        else:
            reaction = DefaultReaction(emoji_name=emoji["name"])

    return reaction.to_dict()

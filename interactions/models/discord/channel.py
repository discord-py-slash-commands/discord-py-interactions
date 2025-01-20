import time
from asyncio import QueueEmpty
from collections import namedtuple
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Union, Callable

import attrs

import interactions.models as models
from interactions.client.const import Absent, DISCORD_EPOCH, MISSING
from interactions.client.errors import NotFound, VoiceNotConnected, TooManyChanges
from interactions.client.mixins.send import SendMixin
from interactions.client.mixins.serialization import DictSerializationMixin
from interactions.client.utils.attr_converters import optional as optional_c
from interactions.client.utils.attr_converters import timestamp_converter
from interactions.client.utils.misc_utils import get
from interactions.client.utils.serializer import to_dict, to_image_data
from interactions.models.discord.base import DiscordObject
from interactions.models.discord.emoji import PartialEmoji
from interactions.models.discord.file import UPLOADABLE_TYPE
from interactions.models.discord.snowflake import (
    Snowflake_Type,
    to_snowflake,
    to_optional_snowflake,
    SnowflakeObject,
)
from interactions.models.discord.thread import DefaultReaction, ThreadTag
from interactions.models.misc.context_manager import Typing
from interactions.models.misc.iterator import AsyncIterator
from .enums import (
    ChannelFlags,
    ChannelType,
    OverwriteType,
    Permissions,
    VideoQualityMode,
    AutoArchiveDuration,
    StagePrivacyLevel,
    MessageFlags,
    InviteTargetType,
    ForumSortOrder,
    ForumLayoutType,
)

if TYPE_CHECKING:
    from aiohttp import FormData
    from interactions import Client, Embed, BaseComponent, AllowedMentions, Sticker, Message
    from interactions.models.internal.active_voice_state import ActiveVoiceState

__all__ = (
    "DM",
    "TYPE_ALL_CHANNEL",
    "TYPE_CHANNEL_MAPPING",
    "TYPE_DM_CHANNEL",
    "TYPE_GUILD_CHANNEL",
    "TYPE_MESSAGEABLE_CHANNEL",
    "TYPE_THREAD_CHANNEL",
    "TYPE_VOICE_CHANNEL",
    "BaseChannel",
    "ChannelHistory",
    "DMChannel",
    "DMGroup",
    "GuildCategory",
    "GuildChannel",
    "GuildForum",
    "GuildForumPost",
    "GuildNews",
    "GuildNewsThread",
    "GuildPrivateThread",
    "GuildPublicThread",
    "GuildStageVoice",
    "GuildText",
    "GuildVoice",
    "InvitableMixin",
    "MessageableMixin",
    "PermissionOverwrite",
    "ThreadChannel",
    "ThreadableMixin",
    "WebhookMixin",
    "process_permission_overwrites",
)


class ChannelHistory(AsyncIterator):
    """
    An async iterator for searching through a channel's history.

    Attributes:
        channel: The channel to search through
        limit: The maximum number of messages to return (set to 0 for no limit)
        before: get messages before this message ID
        after: get messages after this message ID
        around: get messages "around" this message ID

    """

    def __init__(self, channel: "BaseChannel", limit=50, before=None, after=None, around=None) -> None:
        self.channel: "BaseChannel" = channel
        self.before: Snowflake_Type = before
        self.after: Snowflake_Type = after
        self.around: Snowflake_Type = around
        super().__init__(limit)

    async def fetch(self) -> List["models.Message"]:
        """
        Fetch additional objects.

        Your implementation of this method *must* return a list of objects.
        If no more objects are available, raise QueueEmpty

        Returns:
            List of objects

        Raises:
              QueueEmpty: when no more objects are available.

        """
        if self.after:
            if not self.last:
                self.last = namedtuple("temp", "id")
                self.last.id = self.after
            messages = await self.channel.fetch_messages(limit=self.get_limit, after=self.last.id)
            messages.sort(key=lambda x: x.id)

        elif self.around:
            messages = await self.channel.fetch_messages(limit=self.get_limit, around=self.around)
            # todo: decide how getting *more* messages from `around` would work
            self._limit = 1  # stops history from getting more messages

        else:
            if self.before and not self.last:
                self.last = namedtuple("temp", "id")
                self.last.id = self.before

            messages = await self.channel.fetch_messages(limit=self.get_limit, before=self.last.id)
            messages.sort(key=lambda x: x.id, reverse=True)
        return messages


class ArchivedForumPosts(AsyncIterator):
    def __init__(self, channel: "BaseChannel", limit: int = 50, before: Snowflake_Type = None) -> None:
        self.channel: "BaseChannel" = channel
        self.before: Snowflake_Type = before
        self._more: bool = True
        super().__init__(limit)

        if self.before:
            self.last = self.before

    async def fetch(self) -> list["GuildForumPost"]:
        if self._more:
            expected = self.get_limit

            rcv = await self.channel._client.http.list_public_archived_threads(
                self.channel.id,
                limit=expected,
                before=to_snowflake(self.last) if self.last else None,
            )
            threads = [self.channel._client.cache.place_channel_data(data) for data in rcv["threads"]]

            if not rcv:
                raise QueueEmpty

            self._more = rcv.get("has_more", False)
            return threads
        raise QueueEmpty


@attrs.define(eq=False, order=False, hash=False, kw_only=True)
class PermissionOverwrite(SnowflakeObject, DictSerializationMixin):
    """
    Channel Permissions Overwrite object.

    !!! note
        `id` here is not an attribute of the overwrite, it is the ID of the overwritten instance

    """

    type: "OverwriteType" = attrs.field(repr=True, converter=OverwriteType)
    """Permission overwrite type (role or member)"""
    allow: Optional["Permissions"] = attrs.field(
        repr=True, converter=optional_c(Permissions), kw_only=True, default=None
    )
    """Permissions to allow"""
    deny: Optional["Permissions"] = attrs.field(
        repr=True, converter=optional_c(Permissions), kw_only=True, default=None
    )
    """Permissions to deny"""

    @classmethod
    def for_target(cls, target_type: Union["models.Role", "models.Member", "models.User"]) -> "PermissionOverwrite":
        """
        Create a PermissionOverwrite for a role or member.

        Args:
            target_type: The type of the target (role or member)

        Returns:
            PermissionOverwrite

        """
        if isinstance(target_type, models.Role):
            return cls(type=OverwriteType.ROLE, id=target_type.id)
        if isinstance(target_type, (models.Member, models.User)):
            return cls(type=OverwriteType.MEMBER, id=target_type.id)
        raise TypeError("target_type must be a Role, Member or User")

    def add_allows(self, *perms: "Permissions") -> None:
        """
        Add permissions to allow.

        Args:
            *perms: Permissions to add

        """
        if not self.allow:
            self.allow = Permissions.NONE
        for perm in perms:
            self.allow |= perm

    def add_denies(self, *perms: "Permissions") -> None:
        """
        Add permissions to deny.

        Args:
            *perms: Permissions to add

        """
        if not self.deny:
            self.deny = Permissions.NONE
        for perm in perms:
            self.deny |= perm


@attrs.define(eq=False, order=False, hash=False, slots=False, kw_only=True)
class MessageableMixin(SendMixin):
    last_message_id: Optional[Snowflake_Type] = attrs.field(
        repr=False, default=None
    )  # TODO May need to think of dynamically updating this.
    """The id of the last message sent in this channel (may not point to an existing or valid message)"""
    default_auto_archive_duration: int = attrs.field(repr=False, default=AutoArchiveDuration.ONE_DAY)
    """Default duration that the clients (not the API) will use for newly created threads, in minutes, to automatically archive the thread after recent activity"""
    last_pin_timestamp: Optional["models.Timestamp"] = attrs.field(
        repr=False, default=None, converter=optional_c(timestamp_converter)
    )
    """When the last pinned message was pinned. This may be None when a message is not pinned."""
    rate_limit_per_user: int = attrs.field(repr=False, default=0)
    """Amount of seconds a user has to wait before sending another message (0-21600)"""

    async def _send_http_request(
        self, message_payload: Union[dict, "FormData"], files: list["UPLOADABLE_TYPE"] | None = None
    ) -> dict:
        return await self._client.http.create_message(message_payload, self.id, files=files)

    async def fetch_message(self, message_id: Snowflake_Type, *, force: bool = False) -> Optional["models.Message"]:
        """
        Fetch a message from the channel.

        Args:
            message_id: ID of message to retrieve.
            force: Whether to force a fetch from the API.

        Returns:
            The message object fetched. If the message is not found, returns None.

        """
        try:
            return await self._client.cache.fetch_message(self.id, message_id, force=force)
        except NotFound:
            return None

    def get_message(self, message_id: Snowflake_Type) -> "models.Message":
        """
        Get a message from the channel.

        Args:
            message_id: ID of message to retrieve.

        Returns:
            The message object fetched.

        """
        message_id = to_snowflake(message_id)
        message: "models.Message" = self._client.cache.get_message(self.id, message_id)
        return message

    def history(
        self,
        limit: int = 100,
        before: Snowflake_Type = None,
        after: Snowflake_Type = None,
        around: Snowflake_Type = None,
    ) -> ChannelHistory:
        """
        Get an async iterator for the history of this channel.

        Args:
            limit: The maximum number of messages to return (set to 0 for no limit)
            before: get messages before this message ID
            after: get messages after this message ID
            around: get messages "around" this message ID

        ??? Hint "Example Usage:"
            ```python
            async for message in channel.history(limit=0):
                if message.author.id == 174918559539920897:
                    print("Found author's message")
                    # ...
                    break
            ```
            or
            ```python
            history = channel.history(limit=250)
            # Flatten the async iterator into a list
            messages = await history.flatten()
            ```

        Returns:
            ChannelHistory (AsyncIterator)

        """
        return ChannelHistory(self, limit, before, after, around)

    async def fetch_messages(
        self,
        limit: int = 50,
        around: Snowflake_Type = MISSING,
        before: Snowflake_Type = MISSING,
        after: Snowflake_Type = MISSING,
    ) -> List["models.Message"]:
        """
        Fetch multiple messages from the channel.

        Args:
            limit: Max number of messages to return, default `50`, max `100`
            around: Message to get messages around
            before: Message to get messages before
            after: Message to get messages after

        Returns:
            A list of messages fetched.

        """
        if limit > 100:
            raise ValueError("You cannot fetch more than 100 messages at once.")

        if around:
            around = to_snowflake(around)
        elif before:
            before = to_snowflake(before)
        elif after:
            after = to_snowflake(after)

        messages_data = await self._client.http.get_channel_messages(
            self.id, limit, around=around, before=before, after=after
        )
        if isinstance(self, GuildChannel):
            for m in messages_data:
                m["guild_id"] = self._guild_id

        return [self._client.cache.place_message_data(m) for m in messages_data]

    async def fetch_pinned_messages(self) -> List["models.Message"]:
        """
        Fetch pinned messages from the channel.

        Returns:
            A list of messages fetched.

        """
        messages_data = await self._client.http.get_pinned_messages(self.id)
        return [self._client.cache.place_message_data(message_data) for message_data in messages_data]

    async def delete_messages(
        self,
        messages: List[Union[Snowflake_Type, "models.Message"]],
        reason: Absent[Optional[str]] = MISSING,
    ) -> None:
        """
        Bulk delete messages from channel.

        Args:
            messages: List of messages or message IDs to delete.
            reason: The reason for this action. Used for audit logs.

        """
        message_ids = [to_snowflake(message) for message in messages]
        # TODO Add check for min/max and duplicates.

        if len(message_ids) == 1:
            # bulk delete messages will throw a http error if only 1 message is passed
            await self.delete_message(message_ids[0], reason)
        else:
            await self._client.http.bulk_delete_messages(self.id, message_ids, reason)

    async def delete_message(self, message: Union[Snowflake_Type, "models.Message"], reason: str | None = None) -> None:
        """
        Delete a single message from a channel.

        Args:
            message: The message to delete
            reason: The reason for this action

        """
        message = to_snowflake(message)
        await self._client.http.delete_message(self.id, message, reason=reason)

    async def purge(
        self,
        deletion_limit: int = 50,
        search_limit: int = 100,
        predicate: Callable[["models.Message"], bool] = MISSING,
        avoid_loading_msg: bool = True,
        return_messages: bool = False,
        before: Optional[Snowflake_Type] = MISSING,
        after: Optional[Snowflake_Type] = MISSING,
        around: Optional[Snowflake_Type] = MISSING,
        reason: Absent[Optional[str]] = MISSING,
    ) -> int | List["models.Message"]:
        """
        Bulk delete messages within a channel. If a `predicate` is provided, it will be used to determine which messages to delete, otherwise all messages will be deleted within the `deletion_limit`.

        ??? Hint "Example Usage:"
            ```python
            # this will delete the last 20 messages sent by a user with the given ID
            deleted = await channel.purge(deletion_limit=20, predicate=lambda m: m.author.id == 174918559539920897)
            await channel.send(f"{deleted} messages deleted")
            ```

        Args:
            deletion_limit: The target amount of messages to delete
            search_limit: How many messages to search through
            predicate: A function that returns True or False, and takes a message as an argument
            avoid_loading_msg: Should the bot attempt to avoid deleting its own loading messages (recommended enabled)
            return_messages: Should the bot return the messages that were deleted
            before: Search messages before this ID
            after: Search messages after this ID
            around: Search messages around this ID
            reason: The reason for this deletion

        Returns:
            The total amount of messages deleted

        """
        if not predicate:

            def predicate(m) -> bool:
                return True

        to_delete = []

        # 1209600 14 days ago in seconds, 1420070400000 is used to convert to snowflake
        fourteen_days_ago = int((time.time() - 1209600) * 1000.0 - DISCORD_EPOCH) << 22
        async for message in self.history(limit=search_limit, before=before, after=after, around=around):
            if deletion_limit != 0 and len(to_delete) == deletion_limit:
                break

            if not predicate(message):
                # fails predicate
                continue

            if (
                avoid_loading_msg
                and message._author_id == self._client.user.id
                and MessageFlags.LOADING in message.flags
            ):
                continue

            if message.id < fourteen_days_ago:
                # message is too old to be purged
                continue

            to_delete.append(message)

        out = to_delete.copy()
        while len(to_delete):
            iteration = [to_delete.pop().id for i in range(min(100, len(to_delete)))]
            await self.delete_messages(iteration, reason=reason)
        return out if return_messages else len(out)

    async def trigger_typing(self) -> None:
        """Trigger a typing animation in this channel."""
        await self._client.http.trigger_typing_indicator(self.id)

    @property
    def typing(self) -> Typing:
        """A context manager to send a typing state to a given channel as long as long as the wrapped operation takes."""
        return Typing(self)


@attrs.define(eq=False, order=False, hash=False, slots=False, kw_only=True)
class InvitableMixin:
    async def create_invite(
        self,
        max_age: int = 86400,
        max_uses: int = 0,
        temporary: bool = False,
        unique: bool = False,
        target_type: Optional[InviteTargetType] = None,
        target_user: Optional[Union[Snowflake_Type, "models.User"]] = None,
        target_application: Optional[Union[Snowflake_Type, "models.Application"]] = None,
        reason: Optional[str] = None,
    ) -> "models.Invite":
        """
        Creates a new channel invite.

        Args:
            max_age: Max age of invite in seconds, default 86400 (24 hours).
            max_uses: Max uses of invite, default 0.
            temporary: Grants temporary membership, default False.
            unique: Invite is unique, default false.
            target_type: Target type for streams and embedded applications.
            target_user: Target User ID for Stream target type.
            target_application: Target Application ID for Embedded App target type.
            reason: The reason for creating this invite.

        Returns:
            Newly created Invite object.

        """
        if target_type:
            if target_type == InviteTargetType.STREAM and not target_user:
                raise ValueError("Stream target must include target user id.")
            if target_type == InviteTargetType.EMBEDDED_APPLICATION and not target_application:
                raise ValueError("Embedded Application target must include target application id.")

        if target_user and target_application:
            raise ValueError("Invite target must be either User or Embedded Application, not both.")
        if target_user:
            target_user = to_snowflake(target_user)
            target_type = InviteTargetType.STREAM
        if target_application:
            target_application = to_snowflake(target_application)
            target_type = InviteTargetType.EMBEDDED_APPLICATION

        invite_data = await self._client.http.create_channel_invite(
            self.id,
            max_age,
            max_uses,
            temporary,
            unique,
            target_user_id=target_user,
            target_application_id=target_application,
            reason=reason,
        )
        return models.Invite.from_dict(invite_data, self._client)

    async def fetch_invites(self) -> List["models.Invite"]:
        """
        Fetches all invites (with invite metadata) for the channel.

        Returns:
            List of Invite objects.

        """
        invites_data = await self._client.http.get_channel_invites(self.id)
        return models.Invite.from_list(invites_data, self._client)


@attrs.define(eq=False, order=False, hash=False, slots=False, kw_only=True)
class ThreadableMixin:
    async def create_thread(
        self,
        name: str,
        message: Absent[Snowflake_Type] = MISSING,
        thread_type: Absent[ChannelType] = MISSING,
        invitable: Absent[bool] = MISSING,
        rate_limit_per_user: Absent[int] = MISSING,
        auto_archive_duration: AutoArchiveDuration = AutoArchiveDuration.ONE_DAY,
        reason: Absent[str] | None = None,
    ) -> "TYPE_THREAD_CHANNEL":
        """
        Creates a new thread in this channel. If a message is provided, it will be used as the initial message.

        Args:
            name: 1-100 character thread name
            message: The message to connect this thread to. Required for news channel.
            thread_type: Is the thread private or public. Not applicable to news channel, it will always be GUILD_NEWS_THREAD.
            invitable: whether non-moderators can add other non-moderators to a thread. Only applicable when creating a private thread.
            rate_limit_per_user: The time users must wait between sending messages (0-21600).
            auto_archive_duration: Time before the thread will be automatically archived. Note 3 day and 7 day archive durations require the server to be boosted.
            reason: The reason for creating this thread.

        Returns:
            The created thread, if successful

        """
        if self.type == ChannelType.GUILD_NEWS and not message:
            raise ValueError("News channel must include message to create thread from.")

        if message and (thread_type or invitable):
            raise ValueError("Message cannot be used with thread_type or invitable.")

        if thread_type != ChannelType.GUILD_PRIVATE_THREAD and invitable:
            raise ValueError("Invitable only applies to private threads.")

        thread_data = await self._client.http.create_thread(
            channel_id=self.id,
            name=name,
            thread_type=thread_type,
            invitable=invitable,
            rate_limit_per_user=rate_limit_per_user,
            auto_archive_duration=auto_archive_duration,
            message_id=to_optional_snowflake(message),
            reason=reason,
        )
        return self._client.cache.place_channel_data(thread_data)

    async def fetch_public_archived_threads(
        self, limit: int | None = None, before: Optional["models.Timestamp"] = None
    ) -> "models.ThreadList":
        """
        Get a `ThreadList` of archived **public** threads available in this channel.

        Args:
            limit: optional maximum number of threads to return
            before: Returns threads before this timestamp

        Returns:
            A `ThreadList` of archived threads.

        """
        threads_data = await self._client.http.list_public_archived_threads(
            channel_id=self.id, limit=limit, before=before
        )
        threads_data["id"] = self.id
        return models.ThreadList.from_dict(threads_data, self._client)

    async def fetch_private_archived_threads(
        self, limit: int | None = None, before: Optional["models.Timestamp"] = None
    ) -> "models.ThreadList":
        """
        Get a `ThreadList` of archived **private** threads available in this channel.

        Args:
            limit: optional maximum number of threads to return
            before: Returns threads before this timestamp

        Returns:
            A `ThreadList` of archived threads.

        """
        threads_data = await self._client.http.list_private_archived_threads(
            channel_id=self.id, limit=limit, before=before
        )
        threads_data["id"] = self.id
        return models.ThreadList.from_dict(threads_data, self._client)

    async def fetch_archived_threads(
        self, limit: int | None = None, before: Optional["models.Timestamp"] = None
    ) -> "models.ThreadList":
        """
        Get a `ThreadList` of archived threads available in this channel.

        Args:
            limit: optional maximum number of threads to return
            before: Returns threads before this timestamp

        Returns:
            A `ThreadList` of archived threads.

        """
        threads_data = await self._client.http.list_private_archived_threads(
            channel_id=self.id, limit=limit, before=before
        )
        threads_data.update(
            await self._client.http.list_public_archived_threads(channel_id=self.id, limit=limit, before=before)
        )
        threads_data["id"] = self.id
        return models.ThreadList.from_dict(threads_data, self._client)

    async def fetch_joined_private_archived_threads(
        self, limit: int | None = None, before: Optional["models.Timestamp"] = None
    ) -> "models.ThreadList":
        """
        Get a `ThreadList` of threads the bot is a participant of in this channel.

        Args:
            limit: optional maximum number of threads to return
            before: Returns threads before this timestamp

        Returns:
            A `ThreadList` of threads the bot is a participant of.

        """
        threads_data = await self._client.http.list_joined_private_archived_threads(
            channel_id=self.id, limit=limit, before=before
        )
        threads_data["id"] = self.id
        return models.ThreadList.from_dict(threads_data, self._client)

    async def fetch_active_threads(self) -> "models.ThreadList":
        """
        Gets all active threads in the channel, including public and private threads.

        Returns:
            A `ThreadList` of active threads.

        """
        threads_data = await self._client.http.list_active_threads(guild_id=self._guild_id)

        # delete the items where the channel_id does not match
        removed_thread_ids = []
        cleaned_threads_data_threads = []
        for thread in threads_data["threads"]:
            if thread["parent_id"] == str(self.id):
                cleaned_threads_data_threads.append(thread)
            else:
                removed_thread_ids.append(thread["id"])
        threads_data["threads"] = cleaned_threads_data_threads

        cleaned_member_data_threads = [
            thread_member for thread_member in threads_data["members"] if thread_member["id"] not in removed_thread_ids
        ]
        threads_data["members"] = cleaned_member_data_threads

        return models.ThreadList.from_dict(threads_data, self._client)

    async def fetch_all_threads(self) -> "models.ThreadList":
        """
        Gets all threads in the channel. Active and archived, including public and private threads.

        Returns:
            A `ThreadList` of all threads.

        """
        threads = await self.fetch_active_threads()

        # update that data with the archived threads
        archived_threads = await self.fetch_archived_threads()
        threads.threads.extend(archived_threads.threads)
        threads.members.extend(archived_threads.members)

        return threads


@attrs.define(eq=False, order=False, hash=False, slots=False, kw_only=True)
class WebhookMixin:
    async def create_webhook(self, name: str, avatar: Absent[UPLOADABLE_TYPE] = MISSING) -> "models.Webhook":
        """
        Create a webhook in this channel.

        Args:
            name: The name of the webhook
            avatar: An optional default avatar image to use

        Returns:
            The created webhook object

        Raises:
            ValueError: If you try to name the webhook "Clyde"

        """
        return await models.Webhook.create(self._client, self, name, avatar)  # type: ignore

    async def delete_webhook(self, webhook: "models.Webhook") -> None:
        """
        Delete a given webhook in this channel.

        Args:
            webhook: The webhook to delete

        """
        return await webhook.delete()

    async def fetch_webhooks(self) -> List["models.Webhook"]:
        """
        Fetches all the webhooks for this channel.

        Returns:
            List of webhook objects

        """
        resp = await self._client.http.get_channel_webhooks(self.id)
        return [models.Webhook.from_dict(d, self._client) for d in resp]


@attrs.define(eq=False, order=False, hash=False, slots=False, kw_only=True)
class BaseChannel(DiscordObject):
    name: Optional[str] = attrs.field(repr=True, default=None)
    """The name of the channel (1-100 characters)"""
    type: Union[ChannelType, int] = attrs.field(repr=True, converter=ChannelType)
    """The channel topic (0-1024 characters)"""
    permissions: Optional[Permissions] = attrs.field(repr=False, default=None, converter=optional_c(Permissions))
    """Calculated permissions for the bot in this channel, only given when using channels as an option with slash commands"""

    @classmethod
    def from_dict_factory(cls, data: dict, client: "Client") -> "TYPE_ALL_CHANNEL":
        """
        Creates a channel object of the appropriate type.

        Args:
            data: The channel data.
            client: The bot.

        Returns:
            The new channel object.

        """
        channel_type = data.get("type")
        channel_class = TYPE_CHANNEL_MAPPING.get(channel_type, None)
        if not channel_class:
            client.logger.error(f"Unsupported channel type for {data} ({channel_type}).")
            channel_class = BaseChannel

        if channel_class == GuildPublicThread:
            # attempt to determine if this thread is a forum post (thanks discord)
            parent_channel = client.cache.get_channel(data["parent_id"])
            if parent_channel and parent_channel.type == ChannelType.GUILD_FORUM:
                channel_class = GuildForumPost

        return channel_class.from_dict(data, client)

    @property
    def mention(self) -> str:
        """Returns a string that would mention the channel."""
        return f"<#{self.id}>"

    async def edit(
        self,
        *,
        name: Absent[str] = MISSING,
        icon: Absent[UPLOADABLE_TYPE] = MISSING,
        type: Absent[ChannelType] = MISSING,
        position: Absent[int] = MISSING,
        topic: Absent[str] = MISSING,
        nsfw: Absent[bool] = MISSING,
        rate_limit_per_user: Absent[int] = MISSING,
        bitrate: Absent[int] = MISSING,
        user_limit: Absent[int] = MISSING,
        permission_overwrites: Absent[
            Union[dict, PermissionOverwrite, List[Union[dict, PermissionOverwrite]]]
        ] = MISSING,
        parent_id: Absent[Snowflake_Type] = MISSING,
        rtc_region: Absent[Union["models.VoiceRegion", str]] = MISSING,
        video_quality_mode: Absent[VideoQualityMode] = MISSING,
        default_auto_archive_duration: Absent[AutoArchiveDuration] = MISSING,
        flags: Absent[Union[int, ChannelFlags]] = MISSING,
        archived: Absent[bool] = MISSING,
        auto_archive_duration: Absent[AutoArchiveDuration] = MISSING,
        locked: Absent[bool] = MISSING,
        invitable: Absent[bool] = MISSING,
        reason: Absent[str] = MISSING,
        **kwargs,
    ) -> "TYPE_ALL_CHANNEL":
        """
        Edits the channel.

        Args:
            name: 1-100 character channel name
            icon: DM Group icon
            type: The type of channel; only conversion between text and news is supported and only in guilds with the "NEWS" feature
            position: The position of the channel in the left-hand listing
            topic: 0-1024 character channel topic
            nsfw: Whether the channel is nsfw
            rate_limit_per_user: Amount of seconds a user has to wait before sending another message (0-21600)
            bitrate: The bitrate (in bits) of the voice channel; 8000 to 96000 (128000 for VIP servers)
            user_limit: The user limit of the voice channel; 0 refers to no limit, 1 to 99 refers to a user limit
            permission_overwrites: Channel or category-specific permissions
            parent_id: The id of the new parent category for a channel
            rtc_region: Channel voice region id, automatic when set to None.
            video_quality_mode: The camera video quality mode of the voice channel
            default_auto_archive_duration: The default duration that the clients use (not the API) for newly created threads in the channel, in minutes, to automatically archive the thread after recent activity
            flags: Channel flags combined as a bitfield. Only REQUIRE_TAG is supported for now.
            archived: Whether the thread is archived
            auto_archive_duration: Duration in minutes to automatically archive the thread after recent activity, can be set to: 60, 1440, 4320, 10080
            locked: Whether the thread is locked; when a thread is locked, only users with MANAGE_THREADS can unarchive it
            invitable: Whether non-moderators can add other non-moderators to a thread; only available on private threads
            reason: The reason for editing the channel

        Returns:
            The edited channel. May be a new object if the channel type changes.

        """
        payload = {
            "name": name,
            "icon": to_image_data(icon),
            "type": type,
            "position": position,
            "topic": topic,
            "nsfw": nsfw,
            "rate_limit_per_user": rate_limit_per_user,
            "bitrate": bitrate,
            "user_limit": user_limit,
            "permission_overwrites": process_permission_overwrites(permission_overwrites),
            "parent_id": to_optional_snowflake(parent_id),
            "rtc_region": rtc_region.id if isinstance(rtc_region, models.VoiceRegion) else rtc_region,
            "video_quality_mode": video_quality_mode,
            "default_auto_archive_duration": default_auto_archive_duration,
            "flags": flags,
            "archived": archived,
            "auto_archive_duration": auto_archive_duration,
            "locked": locked,
            "invitable": invitable,
            **kwargs,
        }
        channel_data = await self._client.http.modify_channel(self.id, payload, reason)
        if not channel_data:
            raise TooManyChanges(
                "You have changed this channel too frequently, you need to wait a while before trying again."
            ) from None

        return self._client.cache.place_channel_data(channel_data)

    async def delete(self, reason: Absent[Optional[str]] = MISSING) -> None:
        """
        Delete this channel.

        Args:
            reason: The reason for deleting this channel

        """
        await self._client.http.delete_channel(self.id, reason)


################################################################
# DMs


@attrs.define(eq=False, order=False, hash=False, slots=False, kw_only=True)
class DMChannel(BaseChannel, MessageableMixin):
    recipients: List["models.User"] = attrs.field(repr=False, factory=list)
    """The users of the DM that will receive messages sent"""

    @classmethod
    def _process_dict(cls, data: Dict[str, Any], client: "Client") -> Dict[str, Any]:
        data = super()._process_dict(data, client)
        if recipients := data.get("recipients", None):
            data["recipients"] = [
                client.cache.place_user_data(recipient) if isinstance(recipient, dict) else recipient
                for recipient in recipients
            ]
        return data

    @property
    def members(self) -> List["models.User"]:
        """Returns a list of users that are in this DM channel."""
        return self.recipients


@attrs.define(eq=False, order=False, hash=False, kw_only=True)
class DM(DMChannel):
    @property
    def recipient(self) -> "models.User":
        """Returns the user that is in this DM channel."""
        return self.recipients[0]


@attrs.define(eq=False, order=False, hash=False, kw_only=True)
class DMGroup(DMChannel):
    owner_id: Snowflake_Type = attrs.field(repr=True)
    """id of the creator of the group DM"""
    application_id: Optional[Snowflake_Type] = attrs.field(repr=False, default=None)
    """Application id of the group DM creator if it is bot-created"""

    async def edit(
        self,
        *,
        name: Absent[str] = MISSING,
        icon: Absent[UPLOADABLE_TYPE] = MISSING,
        reason: Absent[str] = MISSING,
        **kwargs,
    ) -> "DMGroup":
        """
        Edit this DM Channel.

        Args:
            name: 1-100 character channel name
            icon: An icon to use
            reason: The reason for this change

        """
        return await super().edit(name=name, icon=icon, reason=reason, **kwargs)

    async def fetch_owner(self, *, force: bool = False) -> "models.User":
        """
        Fetch the owner of this DM group

        Args:
            force: Whether to force a fetch from the API

        """
        return await self._client.cache.fetch_user(self.owner_id, force=force)

    def get_owner(self) -> "models.User":
        """Get the owner of this DM group"""
        return self._client.cache.get_user(self.owner_id)

    async def add_recipient(
        self,
        user: Union["models.User", Snowflake_Type],
        access_token: str,
        nickname: Absent[Optional[str]] = MISSING,
    ) -> None:
        """
        Add a recipient to this DM Group.

        Args:
            user: The user to add
            access_token: access token of a user that has granted your app the gdm.join scope
            nickname: nickname to apply to the user being added

        """
        user = await self._client.cache.fetch_user(user)
        await self._client.http.group_dm_add_recipient(self.id, user.id, access_token, nickname)
        self.recipients.append(user)

    async def remove_recipient(self, user: Union["models.User", Snowflake_Type]) -> None:
        """
        Remove a recipient from this DM Group.

        Args:
            user: The user to remove

        """
        user = await self._client.cache.fetch_user(user)
        await self._client.http.group_dm_remove_recipient(self.id, user.id)
        self.recipients.remove(user)


################################################################
# Guild


@attrs.define(eq=False, order=False, hash=False, slots=False, kw_only=True)
class GuildChannel(BaseChannel):
    position: Optional[int] = attrs.field(repr=False, default=0)
    """Sorting position of the channel"""
    nsfw: bool = attrs.field(repr=False, default=False)
    """Whether the channel is nsfw"""
    parent_id: Optional[Snowflake_Type] = attrs.field(repr=False, default=None, converter=optional_c(to_snowflake))
    """id of the parent category for a channel (each parent category can contain up to 50 channels)"""
    permission_overwrites: list[PermissionOverwrite] = attrs.field(repr=False, factory=list)
    """A list of the overwritten permissions for the members and roles"""

    _guild_id: Optional[Snowflake_Type] = attrs.field(repr=False, default=None, converter=optional_c(to_snowflake))

    @property
    def guild(self) -> "models.Guild":
        """The guild this channel belongs to."""
        return self._client.cache.get_guild(self._guild_id)

    @property
    def category(self) -> Optional["GuildCategory"]:
        """The parent category of this channel."""
        return self._client.cache.get_channel(self.parent_id)

    @property
    def gui_position(self) -> int:
        """The position of this channel in the Discord interface."""
        return self.guild.get_channel_gui_position(self.id)

    @classmethod
    def _process_dict(cls, data: Dict[str, Any], client: "Client") -> Dict[str, Any]:
        data = super()._process_dict(data, client)
        if overwrites := data.get("permission_overwrites"):
            data["permission_overwrites"] = PermissionOverwrite.from_list(overwrites)
        return data

    def permissions_for(self, instance: Snowflake_Type) -> Permissions:
        """
        Calculates permissions for an instance

        Args:
            instance: Member or Role instance (or its ID)

        Returns:
            Permissions data

        Raises:
            ValueError: If could not find any member or role by given ID
            RuntimeError: If given instance is from another guild

        """
        if (is_member := isinstance(instance, models.Member)) or isinstance(instance, models.Role):
            if instance._guild_id != self._guild_id:
                raise RuntimeError("Unable to calculate permissions for the instance from different guild")

            if is_member:
                return instance.channel_permissions(self)

            permissions = instance.permissions

            for overwrite in self.permission_overwrites:
                if overwrite.id == instance.id:
                    permissions &= ~overwrite.deny
                    permissions |= overwrite.allow
                    break

            return permissions

        instance = to_snowflake(instance)
        guild = self.guild
        if instance := guild.get_member(instance) or guild.get_role(instance):
            return self.permissions_for(instance)
        raise ValueError("Unable to find any member or role by given instance ID")

    async def add_permission(
        self,
        target: Union["PermissionOverwrite", "models.Role", "models.User", "models.Member", "Snowflake_Type"],
        type: Optional["OverwriteType"] = None,
        allow: Optional[List["Permissions"] | int] = None,
        deny: Optional[List["Permissions"] | int] = None,
        reason: Optional[str] = None,
    ) -> None:
        """
        Add a permission to this channel.

        Args:
            target: The updated PermissionOverwrite object, or the Role or User object/id to update
            type: The type of permission overwrite. Only applicable if target is an id
            allow: List of permissions to allow. Only applicable if target is not an PermissionOverwrite object
            deny: List of permissions to deny. Only applicable if target is not an PermissionOverwrite object
            reason: The reason for this change

        Raises:
            ValueError: Invalid target for permission

        """
        allow = allow or []
        deny = deny or []
        if not isinstance(target, PermissionOverwrite):
            if isinstance(target, (models.User, models.Member)):
                target = target.id
                type = OverwriteType.MEMBER
            elif isinstance(target, models.Role):
                target = target.id
                type = OverwriteType.ROLE
            elif type and isinstance(target, Snowflake_Type):
                target = to_snowflake(target)
            else:
                raise ValueError("Invalid target and/or type for permission")
            overwrite = PermissionOverwrite(id=target, type=type, allow=Permissions.NONE, deny=Permissions.NONE)
            if isinstance(allow, int):
                overwrite.allow |= allow
            else:
                for perm in allow:
                    overwrite.allow |= perm
            if isinstance(deny, int):
                overwrite.deny |= deny
            else:
                for perm in deny:
                    overwrite.deny |= perm
        else:
            overwrite = target

        if exists := get(self.permission_overwrites, id=overwrite.id, type=overwrite.type):
            exists.deny = (exists.deny | overwrite.deny) & ~overwrite.allow
            exists.allow = (exists.allow | overwrite.allow) & ~overwrite.deny
            await self.edit_permission(exists, reason)
        else:
            permission_overwrites = self.permission_overwrites
            permission_overwrites.append(overwrite)
            await self.edit(permission_overwrites=permission_overwrites)

    async def edit_permission(self, overwrite: PermissionOverwrite, reason: Optional[str] = None) -> None:
        """
        Edit the permissions for this channel.

        Args:
            overwrite: The permission overwrite to apply
            reason: The reason for this change

        """
        await self._client.http.edit_channel_permission(
            self.id,
            overwrite_id=overwrite.id,
            allow=overwrite.allow,
            deny=overwrite.deny,
            perm_type=overwrite.type,
            reason=reason,
        )

    async def delete_permission(
        self,
        target: Union["PermissionOverwrite", "models.Role", "models.User"],
        reason: Absent[Optional[str]] = MISSING,
    ) -> None:
        """
        Delete a permission overwrite for this channel.

        Args:
            target: The permission overwrite to delete
            reason: The reason for this change

        """
        target = to_snowflake(target)
        await self._client.http.delete_channel_permission(self.id, target, reason)

    async def set_permission(
        self,
        target: Union["models.Role", "models.Member", "models.User"],
        *,
        add_reactions: bool | None = None,
        administrator: bool | None = None,
        attach_files: bool | None = None,
        ban_members: bool | None = None,
        change_nickname: bool | None = None,
        connect: bool | None = None,
        create_instant_invite: bool | None = None,
        deafen_members: bool | None = None,
        embed_links: bool | None = None,
        kick_members: bool | None = None,
        manage_channels: bool | None = None,
        manage_emojis_and_stickers: bool | None = None,
        manage_events: bool | None = None,
        manage_guild: bool | None = None,
        manage_messages: bool | None = None,
        manage_nicknames: bool | None = None,
        manage_roles: bool | None = None,
        manage_threads: bool | None = None,
        manage_webhooks: bool | None = None,
        mention_everyone: bool | None = None,
        moderate_members: bool | None = None,
        move_members: bool | None = None,
        mute_members: bool | None = None,
        priority_speaker: bool | None = None,
        read_message_history: bool | None = None,
        request_to_speak: bool | None = None,
        send_messages: bool | None = None,
        send_messages_in_threads: bool | None = None,
        send_tts_messages: bool | None = None,
        speak: bool | None = None,
        start_embedded_activities: bool | None = None,
        stream: bool | None = None,
        use_application_commands: bool | None = None,
        use_external_emojis: bool | None = None,
        use_external_stickers: bool | None = None,
        use_private_threads: bool | None = None,
        use_public_threads: bool | None = None,
        use_vad: bool | None = None,
        view_audit_log: bool | None = None,
        view_channel: bool | None = None,
        view_guild_insights: bool | None = None,
        reason: str | None = None,
    ) -> None:
        """
        Set the Permission Overwrites for a given target.

        Args:
            target: The target to set permission overwrites for
            add_reactions: Allows for the addition of reactions to messages
            administrator: Allows all permissions and bypasses channel permission overwrites
            attach_files: Allows for uploading images and files
            ban_members: Allows banning members
            change_nickname: Allows for modification of own nickname
            connect: Allows for joining of a voice channel
            create_instant_invite: Allows creation of instant invites
            deafen_members: Allows for deafening of members in a voice channel
            embed_links: Links sent by users with this permission will be auto-embedded
            kick_members: Allows kicking members
            manage_channels: Allows management and editing of channels
            manage_emojis_and_stickers: Allows management and editing of emojis and stickers
            manage_events: Allows for creating, editing, and deleting scheduled events
            manage_guild: Allows management and editing of the guild
            manage_messages: Allows for deletion of other users messages
            manage_nicknames: Allows for modification of other users nicknames
            manage_roles: Allows management and editing of roles
            manage_threads: Allows for deleting and archiving threads, and viewing all private threads
            manage_webhooks: Allows management and editing of webhooks
            mention_everyone: Allows for using the `@everyone` tag to notify all users in a channel, and the `@here` tag to notify all online users in a channel
            moderate_members: Allows for timing out users to prevent them from sending or reacting to messages in chat and threads, and from speaking in voice and stage channels
            move_members: Allows for moving of members between voice channels
            mute_members: Allows for muting members in a voice channel
            priority_speaker: Allows for using priority speaker in a voice channel
            read_message_history: Allows for reading of message history
            request_to_speak: Allows for requesting to speak in stage channels. (This permission is under active development and may be changed or removed.)
            send_messages:  Allows for sending messages in a channel (does not allow sending messages in threads)
            send_messages_in_threads: Allows for sending messages in threads
            send_tts_messages:  Allows for sending of `/tts` messages
            speak: Allows for speaking in a voice channel
            start_embedded_activities: Allows for using Activities (applications with the `EMBEDDED` flag) in a voice channel
            stream: Allows the user to go live
            use_application_commands: Allows members to use application commands, including slash commands and context menu commands
            use_external_emojis: Allows the usage of custom emojis from other servers
            use_external_stickers: Allows the usage of custom stickers from other servers
            use_private_threads: Allows for creating private threads
            use_public_threads:  Allows for creating public and announcement threads
            use_vad: Allows for using voice-activity-detection in a voice channel
            view_audit_log: Allows for viewing of audit logs
            view_channel: Allows guild members to view a channel, which includes reading messages in text channels and joining voice channels
            view_guild_insights: Allows for viewing guild insights
            reason: The reason for creating this overwrite

        """
        overwrite = PermissionOverwrite.for_target(target)

        allow: Permissions = Permissions.NONE
        deny: Permissions = Permissions.NONE

        for name, val in locals().items():
            if isinstance(val, bool):
                if val:
                    allow |= getattr(Permissions, name.upper())
                else:
                    deny |= getattr(Permissions, name.upper())

        overwrite.add_allows(allow)
        overwrite.add_denies(deny)

        await self.edit_permission(overwrite, reason)

    @property
    def members(self) -> List["models.Member"]:
        """Returns a list of members that can see this channel."""
        return [m for m in self.guild.members if Permissions.VIEW_CHANNEL in m.channel_permissions(self)]  # type: ignore

    @property
    def bots(self) -> List["models.Member"]:
        """Returns a list of bots that can see this channel."""
        return [m for m in self.guild.members if m.bot and Permissions.VIEW_CHANNEL in m.channel_permissions(self)]  # type: ignore

    @property
    def humans(self) -> List["models.Member"]:
        """Returns a list of humans that can see this channel."""
        return [m for m in self.guild.members if not m.bot and Permissions.VIEW_CHANNEL in m.channel_permissions(self)]  # type: ignore

    async def clone(self, name: Optional[str] = None, reason: Absent[Optional[str]] = MISSING) -> "TYPE_GUILD_CHANNEL":
        """
        Clone this channel and create a new one.

        Args:
            name: The name of the new channel. Defaults to the current name
            reason: The reason for creating this channel

        Returns:
            The newly created channel.

        """
        return await self.guild.create_channel(
            channel_type=self.type,
            name=name or self.name,
            topic=getattr(self, "topic", MISSING),
            position=self.position,
            permission_overwrites=self.permission_overwrites,
            category=self.category,
            nsfw=self.nsfw,
            bitrate=getattr(self, "bitrate", 64000),
            user_limit=getattr(self, "user_limit", 0),
            rate_limit_per_user=getattr(self, "rate_limit_per_user", 0),
            reason=reason,
        )


@attrs.define(eq=False, order=False, hash=False, kw_only=True)
class GuildCategory(GuildChannel):
    @property
    def channels(self) -> List["TYPE_GUILD_CHANNEL"]:
        """Get all channels within the category"""
        return [channel for channel in self.guild.channels if channel.parent_id == self.id]

    @property
    def voice_channels(self) -> List["GuildVoice"]:
        """Get all voice channels within the category"""
        return [
            channel
            for channel in self.channels
            if isinstance(channel, GuildVoice) and not isinstance(channel, GuildStageVoice)
        ]

    @property
    def stage_channels(self) -> List["GuildStageVoice"]:
        """Get all stage channels within the category"""
        return [channel for channel in self.channels if isinstance(channel, GuildStageVoice)]

    @property
    def text_channels(self) -> List["GuildText"]:
        """Get all text channels within the category"""
        return [channel for channel in self.channels if isinstance(channel, GuildText)]

    @property
    def news_channels(self) -> List["GuildNews"]:
        """Get all news channels within the category"""
        return [channel for channel in self.channels if isinstance(channel, GuildNews)]

    async def edit(
        self,
        *,
        name: Absent[str] = MISSING,
        position: Absent[int] = MISSING,
        permission_overwrites: Absent[
            Union[dict, PermissionOverwrite, List[Union[dict, PermissionOverwrite]]]
        ] = MISSING,
        reason: Absent[str] = MISSING,
        **kwargs,
    ) -> "GuildCategory":
        """
        Edit this channel.

        Args:
            name: 1-100 character channel name
            position: the position of the channel in the left-hand listing
            permission_overwrites: channel or category-specific permissions
            reason: the reason for this change

        Returns:
            The updated channel object.

        """
        return await super().edit(
            name=name,
            position=position,
            permission_overwrites=permission_overwrites,
            reason=reason,
            **kwargs,
        )

    async def create_channel(
        self,
        channel_type: Union[ChannelType, int],
        name: str,
        topic: Absent[Optional[str]] = MISSING,
        position: Absent[Optional[int]] = MISSING,
        permission_overwrites: Absent[
            Union[dict, PermissionOverwrite, List[Union[dict, PermissionOverwrite]]]
        ] = MISSING,
        nsfw: bool = False,
        bitrate: int = 64000,
        user_limit: int = 0,
        rate_limit_per_user: int = 0,
        reason: Absent[Optional[str]] = MISSING,
    ) -> "TYPE_GUILD_CHANNEL":
        """
        Create a guild channel within this category, allows for explicit channel type setting.

        Args:
            channel_type: The type of channel to create
            name: The name of the channel
            topic: The topic of the channel
            position: The position of the channel in the channel list
            permission_overwrites: Permission overwrites to apply to the channel
            nsfw: Should this channel be marked nsfw
            bitrate: The bitrate of this channel, only for voice
            user_limit: The max users that can be in this channel, only for voice
            rate_limit_per_user: The time users must wait between sending messages
            reason: The reason for creating this channel

        Returns:
            The newly created channel.

        """
        return await self.guild.create_channel(
            channel_type=channel_type,
            name=name,
            topic=topic,
            position=position,
            permission_overwrites=permission_overwrites,
            category=self.id,
            nsfw=nsfw,
            bitrate=bitrate,
            user_limit=user_limit,
            rate_limit_per_user=rate_limit_per_user,
            reason=reason,
        )

    async def create_text_channel(
        self,
        name: str,
        topic: Absent[Optional[str]] = MISSING,
        position: Absent[Optional[int]] = MISSING,
        permission_overwrites: Absent[
            Union[dict, PermissionOverwrite, List[Union[dict, PermissionOverwrite]]]
        ] = MISSING,
        nsfw: bool = False,
        rate_limit_per_user: int = 0,
        reason: Absent[Optional[str]] = MISSING,
    ) -> "GuildText":
        """
        Create a text channel in this guild within this category.

        Args:
            name: The name of the channel
            topic: The topic of the channel
            position: The position of the channel in the channel list
            permission_overwrites: Permission overwrites to apply to the channel
            nsfw: Should this channel be marked nsfw
            rate_limit_per_user: The time users must wait between sending messages
            reason: The reason for creating this channel

        Returns:
           The newly created text channel.

        """
        return await self.create_channel(
            channel_type=ChannelType.GUILD_TEXT,
            name=name,
            topic=topic,
            position=position,
            permission_overwrites=permission_overwrites,
            nsfw=nsfw,
            rate_limit_per_user=rate_limit_per_user,
            reason=reason,
        )

    async def create_news_channel(
        self,
        name: str,
        topic: Absent[Optional[str]] = MISSING,
        position: Absent[Optional[int]] = MISSING,
        permission_overwrites: Absent[
            Union[dict, PermissionOverwrite, List[Union[dict, PermissionOverwrite]]]
        ] = MISSING,
        nsfw: bool = False,
        reason: Absent[Optional[str]] = MISSING,
    ) -> "GuildNews":
        """
        Create a news channel in this guild within this category.

        Args:
            name: The name of the channel
            topic: The topic of the channel
            position: The position of the channel in the channel list
            permission_overwrites: Permission overwrites to apply to the channel
            nsfw: Should this channel be marked nsfw
            reason: The reason for creating this channel

        Returns:
           The newly created news channel.

        """
        return await self.create_channel(
            channel_type=ChannelType.GUILD_NEWS,
            name=name,
            topic=topic,
            position=position,
            permission_overwrites=permission_overwrites,
            nsfw=nsfw,
            reason=reason,
        )

    async def create_voice_channel(
        self,
        name: str,
        topic: Absent[Optional[str]] = MISSING,
        position: Absent[Optional[int]] = MISSING,
        permission_overwrites: Absent[
            Union[dict, PermissionOverwrite, List[Union[dict, PermissionOverwrite]]]
        ] = MISSING,
        nsfw: bool = False,
        bitrate: int = 64000,
        user_limit: int = 0,
        reason: Absent[Optional[str]] = MISSING,
    ) -> "GuildVoice":
        """
        Create a guild voice channel within this category.

        Args:
            name: The name of the channel
            topic: The topic of the channel
            position: The position of the channel in the channel list
            permission_overwrites: Permission overwrites to apply to the channel
            nsfw: Should this channel be marked nsfw
            bitrate: The bitrate of this channel, only for voice
            user_limit: The max users that can be in this channel, only for voice
            reason: The reason for creating this channel

        Returns:
           The newly created voice channel.

        """
        return await self.create_channel(
            channel_type=ChannelType.GUILD_VOICE,
            name=name,
            topic=topic,
            position=position,
            permission_overwrites=permission_overwrites,
            nsfw=nsfw,
            bitrate=bitrate,
            user_limit=user_limit,
            reason=reason,
        )

    async def create_stage_channel(
        self,
        name: str,
        topic: Absent[Optional[str]] = MISSING,
        position: Absent[Optional[int]] = MISSING,
        permission_overwrites: Absent[
            Union[dict, PermissionOverwrite, List[Union[dict, PermissionOverwrite]]]
        ] = MISSING,
        bitrate: int = 64000,
        user_limit: int = 0,
        reason: Absent[Optional[str]] = MISSING,
    ) -> "GuildStageVoice":
        """
        Create a guild stage channel within this category.

        Args:
            name: The name of the channel
            topic: The topic of the channel
            position: The position of the channel in the channel list
            permission_overwrites: Permission overwrites to apply to the channel
            bitrate: The bitrate of this channel, only for voice
            user_limit: The max users that can be in this channel, only for voice
            reason: The reason for creating this channel

        Returns:
            The newly created stage channel.

        """
        return await self.create_channel(
            channel_type=ChannelType.GUILD_STAGE_VOICE,
            name=name,
            topic=topic,
            position=position,
            permission_overwrites=permission_overwrites,
            bitrate=bitrate,
            user_limit=user_limit,
            reason=reason,
        )


@attrs.define(eq=False, order=False, hash=False, kw_only=True)
class GuildNews(GuildChannel, MessageableMixin, InvitableMixin, ThreadableMixin, WebhookMixin):
    topic: Optional[str] = attrs.field(repr=False, default=None)
    """The channel topic (0-1024 characters)"""

    async def edit(
        self,
        *,
        name: Absent[str] = MISSING,
        position: Absent[int] = MISSING,
        permission_overwrites: Absent[
            Union[dict, PermissionOverwrite, List[Union[dict, PermissionOverwrite]]]
        ] = MISSING,
        parent_id: Absent[Snowflake_Type] = MISSING,
        nsfw: Absent[bool] = MISSING,
        topic: Absent[str] = MISSING,
        channel_type: Absent["ChannelType"] = MISSING,
        default_auto_archive_duration: Absent["AutoArchiveDuration"] = MISSING,
        reason: Absent[str] = MISSING,
        **kwargs,
    ) -> Union["GuildNews", "GuildText"]:
        """
        Edit the guild text channel.

        Args:
            name: 1-100 character channel name
            position: the position of the channel in the left-hand listing
            permission_overwrites: a list of PermissionOverwrite
            parent_id:  the parent category `Snowflake_Type` for the channel
            nsfw: whether the channel is nsfw
            topic: 0-1024 character channel topic
            channel_type: the type of channel; only conversion between text and news is supported and only in guilds with the "NEWS" feature
            default_auto_archive_duration: optional AutoArchiveDuration
            reason: An optional reason for the audit log

        Returns:
            The edited channel.

        """
        return await super().edit(
            name=name,
            position=position,
            permission_overwrites=permission_overwrites,
            parent_id=parent_id,
            nsfw=nsfw,
            topic=topic,
            type=channel_type,
            default_auto_archive_duration=default_auto_archive_duration,
            reason=reason,
            **kwargs,
        )

    async def follow(self, webhook_channel_id: Snowflake_Type) -> None:
        """
        Follow this channel.

        Args:
            webhook_channel_id: The ID of the channel to post messages from this channel to

        """
        await self._client.http.follow_news_channel(self.id, webhook_channel_id)

    async def create_thread_from_message(
        self,
        name: str,
        message: Snowflake_Type,
        auto_archive_duration: AutoArchiveDuration = AutoArchiveDuration.ONE_DAY,
        reason: Absent[str] | None = None,
    ) -> "GuildNewsThread":
        """
        Creates a new news thread in this channel.

        Args:
            name: 1-100 character thread name.
            message: The message to connect this thread to.
            auto_archive_duration: Time before the thread will be automatically archived. Note 3 day and 7 day archive durations require the server to be boosted.
            reason: The reason for creating this thread.

        Returns:
            The created public thread, if successful

        """
        return await self.create_thread(
            name=name,
            message=message,
            auto_archive_duration=auto_archive_duration,
            reason=reason,
        )


@attrs.define(eq=False, order=False, hash=False, kw_only=True)
class GuildText(GuildChannel, MessageableMixin, InvitableMixin, ThreadableMixin, WebhookMixin):
    topic: Optional[str] = attrs.field(repr=False, default=None)
    """The channel topic (0-1024 characters)"""

    async def edit(
        self,
        *,
        name: Absent[str] = MISSING,
        position: Absent[int] = MISSING,
        permission_overwrites: Absent[
            Union[dict, PermissionOverwrite, List[Union[dict, PermissionOverwrite]]]
        ] = MISSING,
        parent_id: Absent[Snowflake_Type] = MISSING,
        nsfw: Absent[bool] = MISSING,
        topic: Absent[str] = MISSING,
        channel_type: Absent["ChannelType"] = MISSING,
        default_auto_archive_duration: Absent["AutoArchiveDuration"] = MISSING,
        rate_limit_per_user: Absent[int] = MISSING,
        reason: Absent[str] = MISSING,
        **kwargs,
    ) -> Union["GuildText", "GuildNews"]:
        """
        Edit the guild text channel.

        Args:
            name: 1-100 character channel name
            position: the position of the channel in the left-hand listing
            permission_overwrites: a list of PermissionOverwrite
            parent_id:  the parent category `Snowflake_Type` for the channel
            nsfw: whether the channel is nsfw
            topic: 0-1024 character channel topic
            channel_type: the type of channel; only conversion between text and news is supported and only in guilds with the "NEWS" feature
            default_auto_archive_duration: optional AutoArchiveDuration
            rate_limit_per_user: amount of seconds a user has to wait before sending another message (0-21600)
            reason: An optional reason for the audit log

        Returns:
            The edited channel.

        """
        return await super().edit(
            name=name,
            position=position,
            permission_overwrites=permission_overwrites,
            parent_id=parent_id,
            nsfw=nsfw,
            topic=topic,
            type=channel_type,
            default_auto_archive_duration=default_auto_archive_duration,
            rate_limit_per_user=rate_limit_per_user,
            reason=reason,
            **kwargs,
        )

    async def create_public_thread(
        self,
        name: str,
        auto_archive_duration: AutoArchiveDuration = AutoArchiveDuration.ONE_DAY,
        rate_limit_per_user: Absent[int] = MISSING,
        reason: Absent[str] | None = None,
    ) -> "GuildPublicThread":
        """
        Creates a new public thread in this channel.

        Args:
            name: 1-100 character thread name.
            auto_archive_duration: Time before the thread will be automatically archived. Note 3 day and 7 day archive durations require the server to be boosted.
            rate_limit_per_user: The time users must wait between sending messages (0-21600).
            reason: The reason for creating this thread.

        Returns:
            The created public thread, if successful

        """
        return await self.create_thread(
            name=name,
            thread_type=ChannelType.GUILD_PUBLIC_THREAD,
            auto_archive_duration=auto_archive_duration,
            rate_limit_per_user=rate_limit_per_user,
            reason=reason,
        )

    async def create_private_thread(
        self,
        name: str,
        invitable: Absent[bool] = MISSING,
        auto_archive_duration: AutoArchiveDuration = AutoArchiveDuration.ONE_DAY,
        rate_limit_per_user: Absent[int] = MISSING,
        reason: Absent[str] | None = None,
    ) -> "GuildPrivateThread":
        """
        Creates a new private thread in this channel.

        Args:
            name: 1-100 character thread name.
            invitable: Whether non-moderators can add other non-moderators to a thread.
            rate_limit_per_user: The time users must wait between sending messages (0-21600).
            auto_archive_duration: Time before the thread will be automatically archived. Note 3 day and 7 day archive durations require the server to be boosted.
            reason: The reason for creating this thread.

        Returns:
            The created thread, if successful

        """
        return await self.create_thread(
            name=name,
            thread_type=ChannelType.GUILD_PRIVATE_THREAD,
            invitable=invitable,
            rate_limit_per_user=rate_limit_per_user,
            auto_archive_duration=auto_archive_duration,
            reason=reason,
        )

    async def create_thread_from_message(
        self,
        name: str,
        message: Snowflake_Type,
        auto_archive_duration: AutoArchiveDuration = AutoArchiveDuration.ONE_DAY,
        reason: Absent[str] | None = None,
    ) -> "GuildPublicThread":
        """
        Creates a new public thread in this channel.

        Args:
            name: 1-100 character thread name.
            message: The message to connect this thread to.
            auto_archive_duration: Time before the thread will be automatically archived. Note 3 day and 7 day archive durations require the server to be boosted.
            reason: The reason for creating this thread.

        Returns:
            The created public thread, if successful

        """
        return await self.create_thread(
            name=name,
            message=message,
            auto_archive_duration=auto_archive_duration,
            reason=reason,
        )


################################################################
# Guild Threads


@attrs.define(eq=False, order=False, hash=False, slots=False, kw_only=True)
class ThreadChannel(BaseChannel, MessageableMixin, WebhookMixin):
    parent_id: Snowflake_Type = attrs.field(repr=False, default=None, converter=optional_c(to_snowflake))
    """id of the text channel this thread was created"""
    owner_id: Snowflake_Type = attrs.field(repr=False, default=None, converter=optional_c(to_snowflake))
    """id of the creator of the thread"""
    topic: Optional[str] = attrs.field(repr=False, default=None)
    """The thread topic (0-1024 characters)"""
    message_count: int = attrs.field(repr=False, default=0)
    """An approximate count of messages in a thread, stops counting at 50"""
    member_count: int = attrs.field(repr=False, default=0)
    """An approximate count of users in a thread, stops counting at 50"""
    archived: bool = attrs.field(repr=False, default=False)
    """Whether the thread is archived"""
    auto_archive_duration: int = attrs.field(
        repr=False,
        default=attrs.Factory(lambda self: self.default_auto_archive_duration, takes_self=True),
    )
    """Duration in minutes to automatically archive the thread after recent activity, can be set to: 60, 1440, 4320, 10080"""
    locked: bool = attrs.field(repr=False, default=False)
    """Whether the thread is locked"""
    archive_timestamp: Optional["models.Timestamp"] = attrs.field(
        repr=False, default=None, converter=optional_c(timestamp_converter)
    )
    """Timestamp when the thread's archive status was last changed, used for calculating recent activity"""
    create_timestamp: Optional["models.Timestamp"] = attrs.field(
        repr=False, default=None, converter=optional_c(timestamp_converter)
    )
    """Timestamp when the thread was created"""
    flags: ChannelFlags = attrs.field(repr=False, default=ChannelFlags.NONE, converter=ChannelFlags)
    """Flags for the thread"""

    _guild_id: Snowflake_Type = attrs.field(repr=False, default=None, converter=optional_c(to_snowflake))

    @classmethod
    def _process_dict(cls, data: Dict[str, Any], client: "Client") -> Dict[str, Any]:
        data = super()._process_dict(data, client)
        thread_metadata: dict = data.get("thread_metadata", {})
        data.update(thread_metadata)
        return data

    @property
    def is_private(self) -> bool:
        """Is this a private thread?"""
        return self.type == ChannelType.GUILD_PRIVATE_THREAD

    @property
    def guild(self) -> "models.Guild":
        """The guild this channel belongs to."""
        return self._client.cache.get_guild(self._guild_id)

    @property
    def parent_channel(self) -> Union[GuildText, "GuildForum"]:
        """The channel this thread is a child of."""
        return self._client.cache.get_channel(self.parent_id)

    @property
    def parent_message(self) -> Optional["Message"]:
        """The message this thread is a child of."""
        return self._client.cache.get_message(self.parent_id, self.id)

    @property
    def mention(self) -> str:
        """Returns a string that would mention this thread."""
        return f"<#{self.id}>"

    @property
    def permission_overwrites(self) -> List["PermissionOverwrite"]:
        """The permission overwrites for this channel."""
        return []

    @property
    def clyde_created(self) -> bool:
        """Whether this thread was created by Clyde."""
        return ChannelFlags.CLYDE_THREAD in self.flags

    def permissions_for(self, instance: Snowflake_Type) -> Permissions:
        """
        Calculates permissions for an instance

        Args:
            instance: Member or Role instance (or its ID)

        Returns:
            Permissions data

        Raises:
            ValueError: If could not find any member or role by given ID
            RuntimeError: If given instance is from another guild

        """
        if self.parent_channel:
            return self.parent_channel.permissions_for(instance)
        return Permissions.NONE

    async def fetch_members(self) -> List["models.ThreadMember"]:
        """Get the members that have access to this thread."""
        members_data = await self._client.http.list_thread_members(self.id)
        return models.ThreadMember.from_list(members_data, self._client)

    async def add_member(self, member: Union["models.Member", Snowflake_Type]) -> None:
        """
        Add a member to this thread.

        Args:
            member: The member to add

        """
        await self._client.http.add_thread_member(self.id, to_snowflake(member))

    async def remove_member(self, member: Union["models.Member", Snowflake_Type]) -> None:
        """
        Remove a member from this thread.

        Args:
            member: The member to remove

        """
        await self._client.http.remove_thread_member(self.id, to_snowflake(member))

    async def join(self) -> None:
        """Join this thread."""
        await self._client.http.join_thread(self.id)

    async def leave(self) -> None:
        """Leave this thread."""
        await self._client.http.leave_thread(self.id)

    async def archive(self, locked: bool = False, reason: Absent[str] = MISSING) -> "TYPE_THREAD_CHANNEL":
        """
        Helper method to archive this thread.

        Args:
            locked: whether the thread is locked; when a thread is locked, only users with MANAGE_THREADS can unarchive it
            reason: The reason for this archive

        Returns:
            The archived thread channel object.

        """
        return await super().edit(locked=locked, archived=True, reason=reason)


@attrs.define(eq=False, order=False, hash=False, kw_only=True)
class GuildNewsThread(ThreadChannel):
    async def edit(
        self,
        *,
        name: Absent[str] = MISSING,
        archived: Absent[bool] = MISSING,
        auto_archive_duration: Absent[AutoArchiveDuration] = MISSING,
        locked: Absent[bool] = MISSING,
        rate_limit_per_user: Absent[int] = MISSING,
        reason: Absent[str] = MISSING,
        **kwargs,
    ) -> "GuildNewsThread":
        """
        Edit this thread.

        Args:
            name: 1-100 character channel name
            archived: whether the thread is archived
            auto_archive_duration: duration in minutes to automatically archive the thread after recent activity, can be set to: 60, 1440, 4320, 10080
            locked: whether the thread is locked; when a thread is locked, only users with MANAGE_THREADS can unarchive it
            rate_limit_per_user: amount of seconds a user has to wait before sending another message (0-21600)
            reason: The reason for this change

        Returns:
            The edited thread channel object.

        """
        return await super().edit(
            name=name,
            archived=archived,
            auto_archive_duration=auto_archive_duration,
            locked=locked,
            rate_limit_per_user=rate_limit_per_user,
            reason=reason,
            **kwargs,
        )


@attrs.define(eq=False, order=False, hash=False, kw_only=True)
class GuildPublicThread(ThreadChannel):
    async def edit(
        self,
        *,
        name: Absent[str] = MISSING,
        archived: Absent[bool] = MISSING,
        auto_archive_duration: Absent[AutoArchiveDuration] = MISSING,
        locked: Absent[bool] = MISSING,
        rate_limit_per_user: Absent[int] = MISSING,
        flags: Absent[Union[int, ChannelFlags]] = MISSING,
        reason: Absent[str] = MISSING,
        **kwargs,
    ) -> "GuildPublicThread":
        """
        Edit this thread.

        Args:
            name: 1-100 character channel name
            archived: whether the thread is archived
            auto_archive_duration: duration in minutes to automatically archive the thread after recent activity, can be set to: 60, 1440, 4320, 10080
            locked: whether the thread is locked; when a thread is locked, only users with MANAGE_THREADS can unarchive it
            rate_limit_per_user: amount of seconds a user has to wait before sending another message (0-21600)
            flags: channel flags for forum threads
            reason: The reason for this change

        Returns:
            The edited thread channel object.

        """
        return await super().edit(
            name=name,
            archived=archived,
            auto_archive_duration=auto_archive_duration,
            locked=locked,
            rate_limit_per_user=rate_limit_per_user,
            reason=reason,
            flags=flags,
            **kwargs,
        )


@attrs.define(eq=False, order=False, hash=False, kw_only=True)
class GuildForumPost(GuildPublicThread):
    """
    A forum post

    !!! note
        This model is an abstraction of the api - In reality all posts are GuildPublicThread
    """

    _applied_tags: list[Snowflake_Type] = attrs.field(repr=False, factory=list)

    @classmethod
    def _process_dict(cls, data: Dict[str, Any], client: "Client") -> Dict[str, Any]:
        data = super()._process_dict(data, client)
        data["_applied_tags"] = data.pop("applied_tags") if "applied_tags" in data else []
        return data

    async def edit(
        self,
        *,
        name: Absent[str] = MISSING,
        archived: Absent[bool] = MISSING,
        auto_archive_duration: Absent[AutoArchiveDuration] = MISSING,
        applied_tags: Absent[List[Union[Snowflake_Type, ThreadTag]]] = MISSING,
        locked: Absent[bool] = MISSING,
        rate_limit_per_user: Absent[int] = MISSING,
        flags: Absent[Union[int, ChannelFlags]] = MISSING,
        reason: Absent[str] = MISSING,
        **kwargs,
    ) -> "GuildForumPost":
        """
        Edit this thread.

        Args:
            name: 1-100 character channel name
            archived: whether the thread is archived
            applied_tags: list of tags to apply
            auto_archive_duration: duration in minutes to automatically archive the thread after recent activity, can be set to: 60, 1440, 4320, 10080
            locked: whether the thread is locked; when a thread is locked, only users with MANAGE_THREADS can unarchive it
            rate_limit_per_user: amount of seconds a user has to wait before sending another message (0-21600)
            flags: channel flags to apply
            reason: The reason for this change

        Returns:
            The edited thread channel object.

        """
        if applied_tags != MISSING:
            applied_tags = [str(tag.id) if isinstance(tag, ThreadTag) else str(tag) for tag in applied_tags]

        return await super().edit(
            name=name,
            archived=archived,
            auto_archive_duration=auto_archive_duration,
            applied_tags=applied_tags,
            locked=locked,
            rate_limit_per_user=rate_limit_per_user,
            reason=reason,
            flags=flags,
            **kwargs,
        )

    @property
    def applied_tags(self) -> list[ThreadTag]:
        """The tags applied to this thread."""
        if not isinstance(self.parent_channel, GuildForum):
            raise AttributeError("This is only available on forum threads.")
        return [tag for tag in self.parent_channel.available_tags if str(tag.id) in self._applied_tags]

    @property
    def initial_post(self) -> Optional["Message"]:
        """The initial message posted by the OP."""
        if not isinstance(self.parent_channel, GuildForum):
            raise AttributeError("This is only available on forum threads.")
        return self.get_message(self.id)

    @property
    def pinned(self) -> bool:
        """Whether this thread is pinned."""
        return ChannelFlags.PINNED in self.flags

    async def pin(self, reason: Absent[str] = MISSING) -> None:
        """
        Pin this thread.

        Args:
            reason: The reason for this pin

        """
        flags = self.flags | ChannelFlags.PINNED
        await self.edit(flags=flags, reason=reason)

    async def unpin(self, reason: Absent[str] = MISSING) -> None:
        """
        Unpin this thread.

        Args:
            reason: The reason for this unpin

        """
        flags = self.flags & ~ChannelFlags.PINNED
        await self.edit(flags=flags, reason=reason)


@attrs.define(eq=False, order=False, hash=False, kw_only=True)
class GuildPrivateThread(ThreadChannel):
    invitable: bool = attrs.field(repr=False, default=False)
    """Whether non-moderators can add other non-moderators to a thread"""

    async def edit(
        self,
        *,
        name: Absent[str] = MISSING,
        archived: Absent[bool] = MISSING,
        auto_archive_duration: Absent[AutoArchiveDuration] = MISSING,
        locked: Absent[bool] = MISSING,
        rate_limit_per_user: Absent[int] = MISSING,
        invitable: Absent[bool] = MISSING,
        reason: Absent[str] = MISSING,
        **kwargs,
    ) -> "GuildPrivateThread":
        """
        Edit this thread.

        Args:
            name: 1-100 character channel name
            archived: whether the thread is archived
            auto_archive_duration: duration in minutes to automatically archive the thread after recent activity, can be set to: 60, 1440, 4320, 10080
            locked: whether the thread is locked; when a thread is locked, only users with MANAGE_THREADS can unarchive it
            rate_limit_per_user: amount of seconds a user has to wait before sending another message (0-21600)
            invitable: whether non-moderators can add other non-moderators to a thread; only available on private threads
            reason: The reason for this change

        Returns:
            The edited thread channel object.

        """
        return await super().edit(
            name=name,
            archived=archived,
            auto_archive_duration=auto_archive_duration,
            locked=locked,
            rate_limit_per_user=rate_limit_per_user,
            invitable=invitable,
            reason=reason,
            **kwargs,
        )


################################################################
# Guild Voices


@attrs.define(eq=False, order=False, hash=False, slots=False, kw_only=True)
class VoiceChannel(GuildChannel):  # May not be needed, can be directly just GuildVoice.
    bitrate: int = attrs.field(
        repr=False,
    )
    """The bitrate (in bits) of the voice channel"""
    user_limit: int = attrs.field(
        repr=False,
    )
    """The user limit of the voice channel"""
    rtc_region: str = attrs.field(repr=False, default="auto")
    """Voice region id for the voice channel, automatic when set to None"""
    video_quality_mode: Union[VideoQualityMode, int] = attrs.field(repr=False, default=VideoQualityMode.AUTO)
    """The camera video quality mode of the voice channel, 1 when not present"""
    _voice_member_ids: list[Snowflake_Type] = attrs.field(repr=False, factory=list)

    async def edit(
        self,
        *,
        name: Absent[str] = MISSING,
        position: Absent[int] = MISSING,
        permission_overwrites: Absent[
            Union[dict, PermissionOverwrite, List[Union[dict, PermissionOverwrite]]]
        ] = MISSING,
        parent_id: Absent[Snowflake_Type] = MISSING,
        bitrate: Absent[int] = MISSING,
        user_limit: Absent[int] = MISSING,
        rtc_region: Absent[str] = MISSING,
        video_quality_mode: Absent[VideoQualityMode] = MISSING,
        reason: Absent[str] = MISSING,
        **kwargs,
    ) -> Union["GuildVoice", "GuildStageVoice"]:
        """
        Edit guild voice channel.

        Args:
            name: 1-100 character channel name
            position: the position of the channel in the left-hand listing
            permission_overwrites: a list of `PermissionOverwrite` to apply to the channel
            parent_id: the parent category `Snowflake_Type` for the channel
            bitrate: the bitrate (in bits) of the voice channel; 8000 to 96000 (128000 for VIP servers)
            user_limit: the user limit of the voice channel; 0 refers to no limit, 1 to 99 refers to a user limit
            rtc_region: channel voice region id, automatic when not set
            video_quality_mode: the camera video quality mode of the voice channel
            reason: optional reason for audit logs

        Returns:
            The edited voice channel object.

        """
        return await super().edit(
            name=name,
            position=position,
            permission_overwrites=permission_overwrites,
            parent_id=parent_id,
            bitrate=bitrate,
            user_limit=user_limit,
            rtc_region=rtc_region,
            video_quality_mode=video_quality_mode,
            reason=reason,
            **kwargs,
        )

    @property
    def members(self) -> List["models.Member"]:
        """Returns a list of members that have access to this voice channel"""
        return [m for m in self.guild.members if Permissions.CONNECT in m.channel_permissions(self)]  # type: ignore

    @property
    def voice_members(self) -> List["models.Member"]:
        """
        Returns a list of members that are currently in the channel.

        !!! note
            This will not be accurate if the bot was offline while users joined the channel
        """
        return [self._client.cache.get_member(self._guild_id, member_id) for member_id in self._voice_member_ids]

    @property
    def voice_state(self) -> Optional["ActiveVoiceState"]:
        """Returns the voice state of the bot in this channel if it is connected"""
        return self._client.get_bot_voice_state(self._guild_id)

    async def connect(self, muted: bool = False, deafened: bool = False) -> "ActiveVoiceState":
        """
        Connect the bot to this voice channel, or move the bot to this voice channel if it is already connected in another voice channel.

        Args:
            muted: Whether the bot should be muted when connected.
            deafened: Whether the bot should be deafened when connected.

        Returns:
            The new active voice state on successfully connection.

        """
        if not self.voice_state:
            return await self._client.connect_to_vc(self._guild_id, self.id, muted, deafened)
        await self.voice_state.move(self.id)
        return self.voice_state

    async def disconnect(self) -> None:
        """
        Disconnect from the currently connected voice state.

        Raises:
            VoiceNotConnected: if the bot is not connected to a voice channel

        """
        if self.voice_state:
            return await self.voice_state.disconnect()
        raise VoiceNotConnected


@attrs.define(eq=False, order=False, hash=False, kw_only=True)
class GuildVoice(VoiceChannel, InvitableMixin, MessageableMixin):
    pass


@attrs.define(eq=False, order=False, hash=False, kw_only=True)
class GuildStageVoice(GuildVoice):
    stage_instance: "models.StageInstance" = attrs.field(repr=False, default=MISSING)
    """The stage instance that this voice channel belongs to"""

    # todo: Listeners and speakers properties (needs voice state caching)

    async def fetch_stage_instance(self) -> "models.StageInstance":
        """
        Fetches the stage instance associated with this channel.

        Returns:
            The stage instance associated with this channel. If no stage is live, will return None.

        """
        self.stage_instance = models.StageInstance.from_dict(
            await self._client.http.get_stage_instance(self.id), self._client
        )
        return self.stage_instance

    async def create_stage_instance(
        self,
        topic: str,
        privacy_level: StagePrivacyLevel = StagePrivacyLevel.GUILD_ONLY,
        reason: Absent[Optional[str]] = MISSING,
    ) -> "models.StageInstance":
        """
        Create a stage instance in this channel.

        Args:
            topic: The topic of the stage (1-120 characters)
            privacy_level: The privacy level of the stage
            reason: The reason for creating this instance

        Returns:
            The created stage instance object.

        """
        self.stage_instance = models.StageInstance.from_dict(
            await self._client.http.create_stage_instance(self.id, topic, privacy_level, reason),
            self._client,
        )
        return self.stage_instance

    async def close_stage(self, reason: Absent[Optional[str]] = MISSING) -> None:
        """
        Closes the live stage instance.

        Args:
            reason: The reason for closing the stage

        """
        if not self.stage_instance and not await self.get_stage_instance():
            # we dont know of an active stage instance, so lets check for one
            raise ValueError("No stage instance found")

        await self.stage_instance.delete(reason=reason)


@attrs.define(eq=False, order=False, hash=False, kw_only=True)
class GuildForum(GuildChannel, InvitableMixin, WebhookMixin):
    available_tags: List[ThreadTag] = attrs.field(repr=False, factory=list)
    """A list of tags available to assign to threads"""
    default_reaction_emoji: Optional[DefaultReaction] = attrs.field(repr=False, default=None)
    """The default emoji to react with for posts"""
    last_message_id: Optional[Snowflake_Type] = attrs.field(repr=False, default=None)
    # TODO: Implement "template" once the API supports them
    rate_limit_per_user: int = attrs.field(repr=False, default=0)
    """Amount of seconds a user has to wait before sending another message (0-21600)"""
    default_sort_order: Optional[ForumSortOrder] = attrs.field(
        repr=False, default=None, converter=ForumSortOrder.converter
    )
    """the default sort order type used to order posts in GUILD_FORUM channels. Defaults to null, which indicates a preferred sort order hasn't been set by a channel admin"""
    default_forum_layout: ForumLayoutType = attrs.field(
        repr=False, default=ForumLayoutType.NOT_SET, converter=ForumLayoutType
    )
    """The default forum layout view used to display posts in GUILD_FORUM channels. Defaults to 0, which indicates a layout view has not been set by a channel admin"""

    @classmethod
    def _process_dict(cls, data: Dict[str, Any], client: "Client") -> Dict[str, Any]:
        data = super()._process_dict(data, client)
        data["available_tags"] = [
            ThreadTag.from_dict(tag_data | {"parent_channel_id": data["id"]}, client)
            for tag_data in data.get("available_tags", [])
        ]
        return data

    async def create_post(
        self,
        name: str,
        content: str | None,
        applied_tags: Absent[List[Union["Snowflake_Type", "ThreadTag", str]]] = MISSING,
        *,
        auto_archive_duration: AutoArchiveDuration = AutoArchiveDuration.ONE_DAY,
        rate_limit_per_user: Absent[int] = MISSING,
        embeds: Optional[Union[List[Union["Embed", dict]], Union["Embed", dict]]] = None,
        embed: Optional[Union["Embed", dict]] = None,
        components: Optional[
            Union[
                List[List[Union["BaseComponent", dict]]],
                List[Union["BaseComponent", dict]],
                "BaseComponent",
                dict,
            ]
        ] = None,
        stickers: Optional[Union[List[Union["Sticker", "Snowflake_Type"]], "Sticker", "Snowflake_Type"]] = None,
        allowed_mentions: Optional[Union["AllowedMentions", dict]] = None,
        files: Optional[Union["UPLOADABLE_TYPE", List["UPLOADABLE_TYPE"]]] = None,
        file: Optional["UPLOADABLE_TYPE"] = None,
        tts: bool = False,
        reason: Absent[str] = MISSING,
    ) -> "GuildForumPost":
        """
        Create a post within this channel.

        Args:
            name: The name of the post
            content: The text content of this post
            applied_tags: A list of tag ids or tag objects to apply to this post
            auto_archive_duration: Time before the thread will be automatically archived. Note 3 day and 7 day archive durations require the server to be boosted.
            rate_limit_per_user: The time users must wait between sending messages
            embeds: Embedded rich content (up to 6000 characters).
            embed: Embedded rich content (up to 6000 characters).
            components: The components to include with the message.
            stickers: IDs of up to 3 stickers in the server to send in the message.
            allowed_mentions: Allowed mentions for the message.
            files: Files to send, the path, bytes or File() instance, defaults to None. You may have up to 10 files.
            file: Files to send, the path, bytes or File() instance, defaults to None. You may have up to 10 files.
            tts: Should this message use Text To Speech.
            reason: The reason for creating this post

        Returns:
            A GuildForumPost object representing the created post.

        """
        if applied_tags is not MISSING:
            processed = []
            for tag in applied_tags:
                if isinstance(tag, ThreadTag):
                    tag = tag.id
                elif isinstance(tag, (str, int)):
                    tag = self.get_tag(tag, case_insensitive=True)
                    if not tag:
                        continue
                    tag = tag.id
                elif isinstance(tag, dict):
                    tag = tag["id"]
                processed.append(tag)

            applied_tags = processed

        message_payload = models.discord.message.process_message_payload(
            content=content,
            embeds=embeds or embed,
            components=components,
            stickers=stickers,
            allowed_mentions=allowed_mentions,
            tts=tts,
        )

        data = await self._client.http.create_forum_thread(
            self.id,
            name,
            auto_archive_duration,
            message_payload,
            applied_tags,
            rate_limit_per_user,
            files=files or file,
            reason=reason,
        )
        return self._client.cache.place_channel_data(data)

    async def fetch_posts(self) -> List["GuildForumPost"]:
        """
        Requests all active posts within this channel.

        Returns:
            A list of GuildForumPost objects representing the posts.

        """
        # I can guarantee this endpoint will need to be converted to an async iterator eventually
        data = await self._client.http.list_active_threads(self._guild_id)
        threads = [self._client.cache.place_channel_data(post_data) for post_data in data["threads"]]

        return [thread for thread in threads if thread.parent_id == self.id]

    def get_posts(self, *, exclude_archived: bool = True) -> List["GuildForumPost"]:
        """
        List all, cached, active posts within this channel.

        Args:
            exclude_archived: Whether to exclude archived posts from the response

        Returns:
            A list of GuildForumPost objects representing the posts.

        """
        out = [thread for thread in self.guild.threads if thread.parent_id == self.id]
        if exclude_archived:
            return [thread for thread in out if not thread.archived]
        return out

    def archived_posts(self, limit: int = 0, before: Snowflake_Type | None = None) -> ArchivedForumPosts:
        """An async iterator for all archived posts in this channel."""
        return ArchivedForumPosts(self, limit, before)

    async def fetch_post(self, id: "Snowflake_Type", *, force: bool = False) -> "GuildForumPost":
        """
        Fetch a post within this channel.

        Args:
            id: The id of the post to fetch
            force: Whether to force a fetch from the API

        Returns:
            A GuildForumPost object representing the post.

        """
        return await self._client.fetch_channel(id, force=force)

    def get_post(self, id: "Snowflake_Type") -> "GuildForumPost":
        """
        Get a post within this channel.

        Args:
            id: The id of the post to get

        Returns:
            A GuildForumPost object representing the post.

        """
        return self._client.cache.get_channel(id)

    def get_tag(self, value: str | Snowflake_Type, *, case_insensitive: bool = False) -> Optional["ThreadTag"]:
        """
        Get a tag within this channel.

        Args:
            value: The name or ID of the tag to get
            case_insensitive: Whether to ignore case when searching for the tag

        Returns:
            A ThreadTag object representing the tag.

        """
        value = str(value)

        def maybe_insensitive(string: str) -> str:
            return string.lower() if case_insensitive else string

        def predicate(tag: ThreadTag) -> Optional["ThreadTag"]:
            if str(tag.id) == value:
                return tag
            if maybe_insensitive(tag.name) == maybe_insensitive(value):
                return tag

        return next((tag for tag in self.available_tags if predicate(tag)), None)

    async def create_tag(
        self, name: str, emoji: Union["models.PartialEmoji", dict, str, None] = None, moderated: bool = False
    ) -> "ThreadTag":
        """
        Create a tag for this forum.

        Args:
            name: The name of the tag
            emoji: The emoji to use for the tag
            moderated: whether this tag can only be added to or removed from threads by a member with the MANAGE_THREADS permission

        !!! note
            If the emoji is a custom emoji, it must be from the same guild as the channel.

        Returns:
            The created tag object.

        """
        payload = {"channel_id": self.id, "name": name, "moderated": moderated}

        if emoji:
            if isinstance(emoji, str):
                emoji = PartialEmoji.from_str(emoji)
            elif isinstance(emoji, dict):
                emoji = PartialEmoji.from_dict(emoji)

            if emoji.id:
                payload["emoji_id"] = emoji.id
            else:
                payload["emoji_name"] = emoji.name

        data = await self._client.http.create_tag(**payload)

        channel_data = self._client.cache.place_channel_data(data)
        return next(tag for tag in channel_data.available_tags if tag.name == name)

    async def edit_tag(
        self,
        tag_id: "Snowflake_Type",
        *,
        name: str | None = None,
        emoji: Union["models.PartialEmoji", dict, str, None] = None,
    ) -> "ThreadTag":
        """
        Edit a tag for this forum.

        Args:
            tag_id: The id of the tag to edit
            name: The name for this tag
            emoji: The emoji for this tag

        """
        if isinstance(emoji, str):
            emoji = PartialEmoji.from_str(emoji)
        elif isinstance(emoji, dict):
            emoji = PartialEmoji.from_dict(emoji)

        if emoji.id:
            data = await self._client.http.edit_tag(self.id, tag_id, name, emoji_id=emoji.id)
        else:
            data = await self._client.http.edit_tag(self.id, tag_id, name, emoji_name=emoji.name)

        channel_data = self._client.cache.place_channel_data(data)
        return next(tag for tag in channel_data.available_tags if tag.name == name)

    async def delete_tag(self, tag_id: "Snowflake_Type") -> None:
        """
        Delete a tag for this forum.

        Args:
            tag_id: The ID of the tag to delete

        """
        data = await self._client.http.delete_tag(self.id, tag_id)
        self._client.cache.place_channel_data(data)


@attrs.define(eq=False, order=False, hash=False, kw_only=True)
class GuildMedia(GuildForum): ...


def process_permission_overwrites(
    overwrites: Union[dict, PermissionOverwrite, List[Union[dict, PermissionOverwrite]]]
) -> List[dict]:
    """
    Processes a permission overwrite lists into format for sending to discord.

    Args:
        overwrites: The permission overwrites to process

    Returns:
        The processed permission overwrites

    """
    if not overwrites:
        return overwrites

    if isinstance(overwrites, dict):
        return [overwrites]

    if isinstance(overwrites, list):
        return list(map(to_dict, overwrites))

    if isinstance(overwrites, PermissionOverwrite):
        return [overwrites.to_dict()]

    raise ValueError(f"Invalid overwrites: {overwrites}")


TYPE_ALL_CHANNEL = Union[
    GuildText,
    GuildForum,
    GuildNews,
    GuildVoice,
    GuildStageVoice,
    GuildCategory,
    GuildPublicThread,
    GuildForumPost,
    GuildPrivateThread,
    GuildNewsThread,
    DM,
    DMGroup,
]


TYPE_DM_CHANNEL = Union[DM, DMGroup]


TYPE_GUILD_CHANNEL = Union[
    GuildCategory,
    GuildNews,
    GuildText,
    GuildVoice,
    GuildStageVoice,
    GuildForum,
    GuildMedia,
    GuildPublicThread,
    GuildForumPost,
    GuildPrivateThread,
]


TYPE_THREAD_CHANNEL = Union[GuildNewsThread, GuildPublicThread, GuildForumPost, GuildPrivateThread]


TYPE_VOICE_CHANNEL = Union[GuildVoice, GuildStageVoice]


TYPE_MESSAGEABLE_CHANNEL = Union[
    DM,
    DMGroup,
    GuildNews,
    GuildText,
    GuildPublicThread,
    GuildForumPost,
    GuildPrivateThread,
    GuildNewsThread,
    GuildVoice,
]


TYPE_CHANNEL_MAPPING = {
    ChannelType.GUILD_TEXT: GuildText,
    ChannelType.GUILD_NEWS: GuildNews,
    ChannelType.GUILD_VOICE: GuildVoice,
    ChannelType.GUILD_STAGE_VOICE: GuildStageVoice,
    ChannelType.GUILD_CATEGORY: GuildCategory,
    ChannelType.GUILD_PUBLIC_THREAD: GuildPublicThread,
    ChannelType.GUILD_PRIVATE_THREAD: GuildPrivateThread,
    ChannelType.GUILD_NEWS_THREAD: GuildNewsThread,
    ChannelType.DM: DM,
    ChannelType.GROUP_DM: DMGroup,
    ChannelType.GUILD_FORUM: GuildForum,
    ChannelType.GUILD_MEDIA: GuildMedia,
}

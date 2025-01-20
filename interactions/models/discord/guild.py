import asyncio
import time
from asyncio import QueueEmpty
from collections import namedtuple
from functools import cmp_to_key
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Set, Union
from warnings import warn

import attrs

import interactions.models as models
from interactions.client.const import MISSING, PREMIUM_GUILD_LIMITS, Absent
from interactions.client.errors import EventLocationNotProvided, NotFound
from interactions.client.mixins.serialization import DictSerializationMixin
from interactions.client.utils.attr_converters import (
    list_converter,
    optional,
    timestamp_converter,
)
from interactions.client.utils.attr_utils import docs
from interactions.client.utils.deserialise_app_cmds import deserialize_app_cmds
from interactions.client.utils.serializer import no_export_meta, to_image_data
from interactions.models.discord.app_perms import (
    ApplicationCommandPermission,
    CommandPermissions,
)
from interactions.models.discord.auto_mod import AutoModRule, BaseAction, BaseTrigger
from interactions.models.discord.file import UPLOADABLE_TYPE
from interactions.models.discord.onboarding import Onboarding
from interactions.models.misc.iterator import AsyncIterator

from .base import ClientObject, DiscordObject
from .enums import (
    AuditLogEventType,
    AutoModEvent,
    AutoModTriggerType,
    ChannelType,
    DefaultNotificationLevel,
    ExplicitContentFilterLevel,
    ForumLayoutType,
    ForumSortOrder,
    IntegrationExpireBehaviour,
    MFALevel,
    NSFWLevel,
    Permissions,
    ScheduledEventPrivacyLevel,
    ScheduledEventType,
    SystemChannelFlags,
    VerificationLevel,
)
from .snowflake import (
    Snowflake_Type,
    to_optional_snowflake,
    to_snowflake,
    to_snowflake_list,
)

if TYPE_CHECKING:
    from interactions import InteractionCommand
    from interactions.client.client import Client

__all__ = (
    "AuditLog",
    "AuditLogChange",
    "AuditLogEntry",
    "AuditLogHistory",
    "BaseGuild",
    "BulkBanResponse",
    "Guild",
    "GuildBan",
    "GuildIntegration",
    "GuildPreview",
    "GuildTemplate",
    "GuildWelcome",
    "GuildWelcomeChannel",
    "GuildWidget",
    "GuildWidgetSettings",
)


@attrs.define(eq=False, order=False, hash=False, kw_only=True)
class GuildBan:
    reason: Optional[str]
    """The reason for the ban"""
    user: "models.User"
    """The banned user"""


@attrs.define(eq=False, order=False, hash=False, kw_only=True)
class BulkBanResponse(ClientObject):
    _banned_users: list[Snowflake_Type] = attrs.field(repr=False, converter=to_snowflake_list)
    """List of user IDs that were successfully banned."""
    _failed_users: list[Snowflake_Type] = attrs.field(repr=False, converter=to_snowflake_list)
    """List of user IDs that were not banned."""

    @property
    def banned_users(self) -> List["models.User | None"]:
        """List of users that were successfully banned."""
        return [self.client.cache.get_user(u_id) for u_id in self._banned_users]

    @property
    def failed_users(self) -> List["models.User | None"]:
        """List of users that were not banned."""
        return [self.client.cache.get_user(u_id) for u_id in self._failed_users]

    @property
    def failed_user_ids(self) -> List[Snowflake_Type]:
        """List of user IDs that were not banned."""
        return self._failed_users

    @property
    def banned_user_ids(self) -> List[Snowflake_Type]:
        """List of user IDs that were successfully banned."""
        return self._banned_users


@attrs.define(eq=False, order=False, hash=False, kw_only=True)
class BaseGuild(DiscordObject):
    name: str = attrs.field(repr=True)
    """Name of guild. (2-100 characters, excluding trailing and leading whitespace)"""
    description: Optional[str] = attrs.field(repr=True, default=None)
    """The description for the guild, if the guild is discoverable"""

    icon: Optional["models.Asset"] = attrs.field(repr=False, default=None)
    """Icon image asset"""
    splash: Optional["models.Asset"] = attrs.field(repr=False, default=None)
    """Splash image asset"""
    discovery_splash: Optional["models.Asset"] = attrs.field(repr=False, default=None)
    """Discovery splash image. Only present for guilds with the "DISCOVERABLE" feature."""
    features: List[str] = attrs.field(repr=False, factory=list)
    """The features of this guild"""

    @classmethod
    def _process_dict(cls, data: Dict[str, Any], client: "Client") -> Dict[str, Any]:
        if icon_hash := data.pop("icon", None):
            data["icon"] = models.Asset.from_path_hash(client, f"icons/{data['id']}/{{}}", icon_hash)
        if splash_hash := data.pop("splash", None):
            data["splash"] = models.Asset.from_path_hash(client, f"splashes/{data['id']}/{{}}", splash_hash)
        if disco_splash := data.pop("discovery_splash", None):
            data["discovery_splash"] = models.Asset.from_path_hash(
                client, f"discovery-splashes/{data['id']}/{{}}", disco_splash
            )
        return data


@attrs.define(eq=False, order=False, hash=False, kw_only=True)
class GuildWelcome(ClientObject):
    description: Optional[str] = attrs.field(
        repr=False, default=None, metadata=docs("Welcome Screen server description")
    )
    welcome_channels: List["models.GuildWelcomeChannel"] = attrs.field(
        repr=False, metadata=docs("List of Welcome Channel objects, up to 5")
    )


@attrs.define(eq=False, order=False, hash=False, kw_only=True)
class GuildPreview(BaseGuild):
    """A partial guild object."""

    emoji: list["models.PartialEmoji"] = attrs.field(repr=False, factory=list)
    """A list of custom emoji from this guild"""
    approximate_member_count: int = attrs.field(repr=False, default=0)
    """Approximate number of members in this guild"""
    approximate_presence_count: int = attrs.field(repr=False, default=0)
    """Approximate number of online members in this guild"""

    @classmethod
    def _process_dict(cls, data: Dict[str, Any], client: "Client") -> Dict[str, Any]:
        return super()._process_dict(data, client)


class MemberIterator(AsyncIterator):
    def __init__(self, guild: "Guild", limit: int = 0) -> None:
        super().__init__(limit)
        self.guild = guild
        self._more = True

    async def fetch(self) -> list:
        if self._more:
            expected = self.get_limit

            rcv = await self.guild._client.http.list_members(
                self.guild.id, limit=expected, after=self.last["id"] if self.last else MISSING
            )
            if not rcv:
                raise QueueEmpty
            self._more = len(rcv) == expected
            return rcv
        raise QueueEmpty


@attrs.define(eq=False, order=False, hash=False, kw_only=True)
class Guild(BaseGuild):
    """Guilds in Discord represent an isolated collection of users and channels, and are often referred to as "servers" in the UI."""

    unavailable: bool = attrs.field(repr=False, default=False)
    """True if this guild is unavailable due to an outage."""
    # owner: bool = attrs.field(repr=False, default=False)  # we get this from api but it's kinda useless to store
    afk_channel_id: Optional[Snowflake_Type] = attrs.field(repr=False, default=None)
    """The channel id for afk."""
    afk_timeout: Optional[int] = attrs.field(repr=False, default=None)
    """afk timeout in seconds."""
    widget_enabled: bool = attrs.field(repr=False, default=False)
    """True if the server widget is enabled."""
    widget_channel_id: Optional[Snowflake_Type] = attrs.field(repr=False, default=None)
    """The channel id that the widget will generate an invite to, or None if set to no invite."""
    verification_level: Union[VerificationLevel, int] = attrs.field(repr=False, default=VerificationLevel.NONE)
    """The verification level required for the guild."""
    default_message_notifications: Union[DefaultNotificationLevel, int] = attrs.field(
        repr=False, default=DefaultNotificationLevel.ALL_MESSAGES
    )
    """The default message notifications level."""
    explicit_content_filter: Union[ExplicitContentFilterLevel, int] = attrs.field(
        repr=False, default=ExplicitContentFilterLevel.DISABLED
    )
    """The explicit content filter level."""
    mfa_level: Union[MFALevel, int] = attrs.field(repr=False, default=MFALevel.NONE)
    """The required MFA (Multi Factor Authentication) level for the guild."""
    system_channel_id: Optional[Snowflake_Type] = attrs.field(repr=False, default=None)
    """The id of the channel where guild notices such as welcome messages and boost events are posted."""
    system_channel_flags: SystemChannelFlags = attrs.field(
        repr=False, default=SystemChannelFlags.NONE, converter=SystemChannelFlags
    )
    """The system channel flags."""
    rules_channel_id: Optional[Snowflake_Type] = attrs.field(repr=False, default=None)
    """The id of the channel where Community guilds can display rules and/or guidelines."""
    joined_at: str = attrs.field(repr=False, default=None, converter=optional(timestamp_converter))
    """When this guild was joined at."""
    large: bool = attrs.field(repr=False, default=False)
    """True if this is considered a large guild."""
    member_count: int = attrs.field(repr=False, default=0)
    """The total number of members in this guild."""
    presences: List[dict] = attrs.field(repr=False, factory=list)
    """The presences of the members in the guild, will only include non-offline members if the size is greater than large threshold."""
    max_presences: Optional[int] = attrs.field(repr=False, default=None)
    """The maximum number of presences for the guild. (None is always returned, apart from the largest of guilds)"""
    max_members: Optional[int] = attrs.field(repr=False, default=None)
    """The maximum number of members for the guild."""
    vanity_url_code: Optional[str] = attrs.field(repr=False, default=None)
    """The vanity url code for the guild."""
    banner: Optional[str] = attrs.field(repr=False, default=None)
    """Hash for banner image."""
    premium_tier: Optional[str] = attrs.field(repr=False, default=None)
    """The premium tier level. (Server Boost level)"""
    premium_subscription_count: int = attrs.field(repr=False, default=0)
    """The number of boosts this guild currently has."""
    preferred_locale: str = attrs.field(
        repr=False,
    )
    """The preferred locale of a Community guild. Used in server discovery and notices from Discord. Defaults to \"en-US\""""
    public_updates_channel_id: Optional[Snowflake_Type] = attrs.field(repr=False, default=None)
    """The id of the channel where admins and moderators of Community guilds receive notices from Discord."""
    max_video_channel_users: int = attrs.field(repr=False, default=0)
    """The maximum amount of users in a video channel."""
    welcome_screen: Optional["GuildWelcome"] = attrs.field(repr=False, default=None)
    """The welcome screen of a Community guild, shown to new members, returned in an Invite's guild object."""
    nsfw_level: Union[NSFWLevel, int] = attrs.field(repr=False, default=NSFWLevel.DEFAULT)
    """The guild NSFW level."""
    stage_instances: List[dict] = attrs.field(repr=False, factory=list)  # TODO stage instance objects
    """Stage instances in the guild."""
    chunked = attrs.field(repr=False, factory=asyncio.Event, metadata=no_export_meta)
    """An event that is fired when this guild has been chunked"""
    command_permissions: dict[Snowflake_Type, CommandPermissions] = attrs.field(
        repr=False, factory=dict, metadata=no_export_meta
    )
    """A cache of all command permissions for this guild"""
    premium_progress_bar_enabled: bool = attrs.field(repr=False, default=False)
    """True if the guild has the boost progress bar enabled"""
    safety_alerts_channel_id: Optional[Snowflake_Type] = attrs.field(repr=False, default=None)
    """The id of the channel where admins and moderators of Community guilds receive safety alerts from Discord."""

    _owner_id: Snowflake_Type = attrs.field(repr=False, converter=to_snowflake)
    _channel_ids: Set[Snowflake_Type] = attrs.field(repr=False, factory=set)
    _thread_ids: Set[Snowflake_Type] = attrs.field(repr=False, factory=set)
    _member_ids: Set[Snowflake_Type] = attrs.field(repr=False, factory=set)
    _role_ids: Set[Snowflake_Type] = attrs.field(repr=False, factory=set)
    _chunk_cache: list = attrs.field(repr=False, factory=list)
    _channel_gui_positions: Dict[Snowflake_Type, int] = attrs.field(repr=False, factory=dict)

    @classmethod
    def _process_dict(cls, data: Dict[str, Any], client: "Client") -> Dict[str, Any]:
        data = super()._process_dict(data, client)
        guild_id = data["id"]

        channels_data = data.pop("channels", [])
        for c in channels_data:
            c["guild_id"] = guild_id
        data["channel_ids"] = {client.cache.place_channel_data(channel_data).id for channel_data in channels_data}

        threads_data = data.pop("threads", [])
        data["thread_ids"] = {client.cache.place_channel_data(thread_data).id for thread_data in threads_data}

        members_data = data.pop("members", [])
        data["member_ids"] = {client.cache.place_member_data(guild_id, member_data).id for member_data in members_data}

        roles_data = data.pop("roles", [])
        data["role_ids"] = set(client.cache.place_role_data(guild_id, roles_data).keys())

        if welcome_screen := data.get("welcome_screen"):
            data["welcome_screen"] = GuildWelcome.from_dict(welcome_screen, client)

        if voice_states := data.get("voice_states"):
            [
                asyncio.create_task(client.cache.place_voice_state_data(state | {"guild_id": guild_id}))
                for state in voice_states
            ]
        return data

    @classmethod
    async def create(
        cls,
        name: str,
        client: "Client",
        *,
        icon: Absent[Optional[UPLOADABLE_TYPE]] = MISSING,
        verification_level: Absent["VerificationLevel"] = MISSING,
        default_message_notifications: Absent["DefaultNotificationLevel"] = MISSING,
        explicit_content_filter: Absent["ExplicitContentFilterLevel"] = MISSING,
        roles: Absent[list[dict]] = MISSING,
        channels: Absent[list[dict]] = MISSING,
        afk_channel_id: Absent["Snowflake_Type"] = MISSING,
        afk_timeout: Absent[int] = MISSING,
        system_channel_id: Absent["Snowflake_Type"] = MISSING,
        system_channel_flags: Absent["SystemChannelFlags"] = MISSING,
    ) -> "Guild":
        """
        Create a guild.

        !!! note
            This method will only work for bots in less than 10 guilds.

        ??? note "Param notes"
            Roles:
                - When using the `roles` parameter, the first member of the array is used to change properties of the guild's `@everyone` role. If you are trying to bootstrap a guild with additional roles, keep this in mind.
                - When using the `roles` parameter, the required id field within each role object is an integer placeholder, and will be replaced by the API upon consumption. Its purpose is to allow you to overwrite a role's permissions in a channel when also passing in channels with the channels array.

            Channels:
                - When using the `channels` parameter, the position field is ignored, and none of the default channels are created.
                - When using the `channels` parameter, the id field within each channel object may be set to an integer placeholder, and will be replaced by the API upon consumption. Its purpose is to allow you to create `GUILD_CATEGORY` channels by setting the `parent_id` field on any children to the category's id field. Category channels must be listed before any children.

        Args:
            name: name of the guild (2-100 characters)
            client: The client
            icon: An icon for the guild
            verification_level: The guild's verification level
            default_message_notifications: The default message notification level
            explicit_content_filter: The guild's explicit content filter level
            roles: An array of partial role dictionaries
            channels: An array of partial channel dictionaries
            afk_channel_id: id for afk channel
            afk_timeout: afk timeout in seconds
            system_channel_id: the id of the channel where guild notices should go
            system_channel_flags: flags for the system channel

        Returns:
            The created guild object

        """
        data = await client.http.create_guild(
            name=name,
            icon=to_image_data(icon) if icon else MISSING,
            verification_level=verification_level,
            default_message_notifications=default_message_notifications,
            explicit_content_filter=explicit_content_filter,
            roles=roles,
            channels=channels,
            afk_channel_id=afk_channel_id,
            afk_timeout=afk_timeout,
            system_channel_id=system_channel_id,
            system_channel_flags=int(system_channel_flags) if system_channel_flags else MISSING,
        )
        return client.cache.place_guild_data(data)

    @property
    def channels(self) -> List["models.TYPE_GUILD_CHANNEL"]:
        """Returns a list of channels associated with this guild."""
        channels = [self._client.cache.get_channel(c_id) for c_id in self._channel_ids]
        return [c for c in channels if c]

    @property
    def threads(self) -> List["models.TYPE_THREAD_CHANNEL"]:
        """Returns a list of threads associated with this guild."""
        return [self._client.cache.get_channel(t_id) for t_id in self._thread_ids]

    @property
    def members(self) -> List["models.Member"]:
        """Returns a list of all members within this guild."""
        members = (self._client.cache.get_member(self.id, m_id) for m_id in self._member_ids)
        return [m for m in members if m]

    @property
    def premium_subscribers(self) -> List["models.Member"]:
        """Returns a list of all premium subscribers"""
        return [member for member in self.members if member.premium]

    @property
    def bots(self) -> List["models.Member"]:
        """Returns a list of all bots within this guild"""
        return [member for member in self.members if member.bot]

    @property
    def humans(self) -> List["models.Member"]:
        """Returns a list of all humans within this guild"""
        return [member for member in self.members if not member.bot]

    @property
    def roles(self) -> List["models.Role"]:
        """Returns a list of roles associated with this guild."""
        return sorted((r for r_id in self._role_ids if (r := self._client.cache.get_role(r_id))), reverse=True)

    @property
    def me(self) -> "models.Member":
        """Returns this bots member object within this guild."""
        return self._client.cache.get_member(self.id, self._client.user.id)

    @property
    def system_channel(self) -> Optional["models.GuildText"]:
        """Returns the channel this guild uses for system messages."""
        return self._client.cache.get_channel(self.system_channel_id)

    @property
    def rules_channel(self) -> Optional["models.GuildText"]:
        """Returns the channel declared as a rules channel."""
        return self._client.cache.get_channel(self.rules_channel_id)

    @property
    def public_updates_channel(self) -> Optional["models.GuildText"]:
        """Returns the channel where server staff receive notices from Discord."""
        return self._client.cache.get_channel(self.public_updates_channel_id)

    @property
    def safety_alerts_channel(self) -> Optional["models.GuildText"]:
        """Returns the channel where server staff receive safety alerts from Discord."""
        return self._client.cache.get_channel(self.safety_alerts_channel_id)

    @property
    def emoji_limit(self) -> int:
        """The maximum number of emoji this guild can have."""
        base = 200 if "MORE_EMOJI" in self.features else 50
        return max(base, PREMIUM_GUILD_LIMITS[self.premium_tier]["emoji"])

    @property
    def sticker_limit(self) -> int:
        """The maximum number of stickers this guild can have."""
        base = 60 if "MORE_STICKERS" in self.features else 0
        return max(base, PREMIUM_GUILD_LIMITS[self.premium_tier]["stickers"])

    @property
    def bitrate_limit(self) -> int:
        """The maximum bitrate for this guild."""
        base = 128000 if "VIP_REGIONS" in self.features else 96000
        return max(base, PREMIUM_GUILD_LIMITS[self.premium_tier]["bitrate"])

    @property
    def filesize_limit(self) -> int:
        """The maximum filesize that may be uploaded within this guild."""
        return PREMIUM_GUILD_LIMITS[self.premium_tier]["filesize"]

    @property
    def default_role(self) -> "models.Role":
        """The `@everyone` role in this guild."""
        return self._client.cache.get_role(self.id)  # type: ignore

    @property
    def premium_subscriber_role(self) -> Optional["models.Role"]:
        """The role given to boosters of this server, if set."""
        return next((role for role in self.roles if role.premium_subscriber), None)

    @property
    def my_role(self) -> Optional["models.Role"]:
        """The role associated with this client, if set."""
        m_r_id = self._client.user.id
        return next((role for role in self.roles if role._bot_id == m_r_id), None)

    @property
    def permissions(self) -> Permissions:
        """Alias for me.guild_permissions"""
        return self.me.guild_permissions

    @property
    def voice_state(self) -> Optional["models.VoiceState"]:
        """Get the bot's voice state for the guild."""
        return self._client.cache.get_bot_voice_state(self.id)

    @property
    def voice_states(self) -> List["models.VoiceState"]:
        """Get a list of the active voice states in this guild."""
        # this is *very* ick, but we cache by user_id, so we have to do it this way,
        # alternative would be maintaining a lookup table in this guild object, which is inherently unreliable
        # noinspection PyProtectedMember
        return [v_state for v_state in self._client.cache.voice_state_cache.values() if v_state._guild_id == self.id]

    @property
    def mention_onboarding_customize(self) -> str:
        """Return a mention string for the customise section of Onboarding"""
        return "<id:customize>"

    @property
    def mention_onboarding_browse(self) -> str:
        """Return a mention string for the browse section of Onboarding"""
        return "<id:browse>"

    @property
    def mention_onboarding_guide(self) -> str:
        """Return a mention string for the guide section of Onboarding"""
        return "<id:guide>"

    async def fetch_member(self, member_id: Snowflake_Type, *, force: bool = False) -> Optional["models.Member"]:
        """
        Return the Member with the given discord ID, fetching from the API if necessary.

        Args:
            member_id: The ID of the member.
            force: Whether to force a fetch from the API.

        Returns:
            The member object fetched. If the member is not in this guild, returns None.

        """
        try:
            return await self._client.cache.fetch_member(self.id, member_id, force=force)
        except NotFound:
            return None

    def get_member(self, member_id: Snowflake_Type) -> Optional["models.Member"]:
        """
        Return the Member with the given discord ID.

        Args:
            member_id: The ID of the member

        Returns:
            Member object or None

        """
        return self._client.cache.get_member(self.id, member_id)

    async def fetch_owner(self, *, force: bool = False) -> "models.Member":
        """
        Return the Guild owner, fetching from the API if necessary.

        Args:
            force: Whether to force a fetch from the API.

        Returns:
            Member object or None

        """
        return await self._client.cache.fetch_member(self.id, self._owner_id, force=force)

    def get_owner(self) -> "models.Member":
        """
        Return the Guild owner

        Returns:
            Member object or None

        """
        return self._client.cache.get_member(self.id, self._owner_id)

    async def fetch_channels(self) -> List["models.TYPE_GUILD_CHANNEL"]:
        """
        Fetch this guild's channels.

        Returns:
            A list of channels in this guild

        """
        data = await self._client.http.get_guild_channels(self.id)
        return [self._client.cache.place_channel_data(channel_data) for channel_data in data]

    async def fetch_app_cmd_perms(self) -> dict[Snowflake_Type, "CommandPermissions"]:
        """
        Fetch the application command permissions for this guild.

        Returns:
            The application command permissions for this guild.

        """
        data = await self._client.http.batch_get_application_command_permissions(self._client.app.id, self.id)

        for command in data:
            command_permissions = CommandPermissions(client=self._client, command_id=command["id"], guild=self)
            perms = [ApplicationCommandPermission.from_dict(perm, self._client) for perm in command["permissions"]]

            command_permissions.update_permissions(*perms)

            self.command_permissions[int(command["id"])] = command_permissions

        return self.command_permissions

    def is_owner(self, user: Snowflake_Type) -> bool:
        """
        Whether the user is owner of the guild.

        Args:
            user: The user to check

        Returns:
            True if the user is the owner of the guild, False otherwise.

        !!! note
            the `user` argument can be any type that meets `Snowflake_Type`

        """
        return self._owner_id == to_snowflake(user)

    async def edit_nickname(self, new_nickname: Absent[str] = MISSING, reason: Absent[str] = MISSING) -> None:
        """
        Alias for me.edit_nickname

        Args:
            new_nickname: The new nickname to apply
            reason: The reason for this change

        !!! note
            Leave `new_nickname` empty to clean user's nickname

        """
        await self.me.edit_nickname(new_nickname, reason=reason)

    async def http_chunk(self) -> None:
        """Populates all members of this guild using the REST API."""
        start_time = time.perf_counter()

        iterator = MemberIterator(self)
        async for member in iterator:
            self._client.cache.place_member_data(self.id, member)

        self.chunked.set()
        self.logger.info(
            f"Cached {iterator.total_retrieved} members for {self.id} in {time.perf_counter() - start_time:.2f} seconds"
        )

    async def gateway_chunk(self, wait: bool = True, presences: bool = True) -> None:
        """
        Trigger a gateway `get_members` event, populating this object with members.

        Args:
            wait: Wait for chunking to be completed before continuing
            presences: Do you need presence data for members?

        """
        ws = self._client.get_guild_websocket(self.id)
        await ws.request_member_chunks(self.id, limit=0, presences=presences)
        if wait:
            await self.chunked.wait()

    async def chunk(self) -> None:
        """Populates all members of this guild using the REST API."""
        await self.http_chunk()

    async def chunk_guild(self, wait: bool = True, presences: bool = True) -> None:
        """
        Trigger a gateway `get_members` event, populating this object with members.

        !!! warning "Depreciation Warning"
            Gateway chunking is deprecated and replaced by http chunking. Use `guild.gateway_chunk` if you need gateway chunking.

        Args:
            wait: Wait for chunking to be completed before continuing
            presences: Do you need presence data for members?

        """
        warn(
            "Gateway chunking is deprecated and replaced by http chunking. Use `guild.gateway_chunk` if you need gateway chunking.",
            DeprecationWarning,
            stacklevel=2,
        )
        await self.gateway_chunk(wait=wait, presences=presences)

    async def process_member_chunk(self, chunk: dict) -> None:
        """
        Receive and either cache or process the chunks of members from gateway.

        Args:
            chunk: A member chunk from discord

        """
        if self.chunked.is_set():
            self.chunked.clear()

        if presences := chunk.get("presences"):
            # combine the presence dict into the members dict
            for presence in presences:
                u_id = presence["user"]["id"]
                # find the user this presence is for
                member_index = next(
                    (index for (index, d) in enumerate(chunk.get("members")) if d["user"]["id"] == u_id),
                    None,
                )
                del presence["user"]
                chunk["members"][member_index]["user"] = chunk["members"][member_index]["user"] | presence

        self._chunk_cache = self._chunk_cache + chunk.get("members") if self._chunk_cache else chunk.get("members")
        if chunk.get("chunk_index") != chunk.get("chunk_count") - 1:
            return self.logger.debug(f"Cached chunk of {len(chunk.get('members'))} members for {self.id}")
        members = self._chunk_cache
        self.logger.info(f"Processing {len(members)} members for {self.id}")

        s = time.monotonic()
        start_time = time.perf_counter()

        for member in members:
            self._client.cache.place_member_data(self.id, member)
            if (time.monotonic() - s) > 0.05:
                # look, i get this *could* be a thread, but because it needs to modify data in the main thread,
                # it is still blocking. So by periodically yielding to the event loop, we can avoid blocking, and still
                # process this data properly
                await asyncio.sleep(0)
                s = time.monotonic()

        total_time = time.perf_counter() - start_time
        self.chunk_cache = []
        self.logger.info(f"Cached members for {self.id} in {total_time:.2f} seconds")
        self.chunked.set()

    async def fetch_audit_log(
        self,
        user_id: Optional["Snowflake_Type"] = MISSING,
        action_type: Optional["AuditLogEventType"] = MISSING,
        before: Optional["Snowflake_Type"] = MISSING,
        after: Optional["Snowflake_Type"] = MISSING,
        limit: int = 100,
    ) -> "AuditLog":
        """
        Fetch section of the audit log for this guild.

        Args:
            user_id: The ID of the user to filter by
            action_type: The type of action to filter by
            before: The ID of the entry to start at
            after: The ID of the entry to end at
            limit: The number of entries to return

        Returns:
            An AuditLog object

        """
        data = await self._client.http.get_audit_log(self.id, user_id, action_type, before, after, limit)
        return AuditLog.from_dict(data, self._client)

    def audit_log_history(
        self,
        user_id: Optional["Snowflake_Type"] = MISSING,
        action_type: Optional["AuditLogEventType"] = MISSING,
        before: Optional["Snowflake_Type"] = MISSING,
        after: Optional["Snowflake_Type"] = MISSING,
        limit: int = 100,
    ) -> "AuditLogHistory":
        """
        Get an async iterator for the history of the audit log.

        Args:
            user_id (:class:`Snowflake_Type`): The user ID to search for.
            action_type (:class:`AuditLogEventType`): The action type to search for.
            before: get entries before this message ID
            after: get entries after this message ID
            limit: The maximum number of entries to return (set to 0 for no limit)

        ??? Hint "Example Usage:"
            ```python
            async for entry in guild.audit_log_history(limit=0):
                entry: "AuditLogEntry"
                if entry.changes:
                    # ...
            ```
            or
            ```python
            history = guild.audit_log_history(limit=250)
            # Flatten the async iterator into a list
            entries = await history.flatten()
            ```

        Returns:
            AuditLogHistory (AsyncIterator)

        """
        return AuditLogHistory(self, user_id, action_type, before, after, limit)

    async def edit(
        self,
        *,
        name: Absent[Optional[str]] = MISSING,
        description: Absent[Optional[str]] = MISSING,
        verification_level: Absent[Optional["VerificationLevel"]] = MISSING,
        default_message_notifications: Absent[Optional["DefaultNotificationLevel"]] = MISSING,
        explicit_content_filter: Absent[Optional["ExplicitContentFilterLevel"]] = MISSING,
        afk_channel: Absent[Optional[Union["models.GuildVoice", Snowflake_Type]]] = MISSING,
        afk_timeout: Absent[Optional[int]] = MISSING,
        system_channel: Absent[Optional[Union["models.GuildText", Snowflake_Type]]] = MISSING,
        system_channel_flags: Absent[Union[SystemChannelFlags, int]] = MISSING,
        owner: Absent[Optional[Union["models.Member", Snowflake_Type]]] = MISSING,
        icon: Absent[Optional[UPLOADABLE_TYPE]] = MISSING,
        splash: Absent[Optional[UPLOADABLE_TYPE]] = MISSING,
        discovery_splash: Absent[Optional[UPLOADABLE_TYPE]] = MISSING,
        banner: Absent[Optional[UPLOADABLE_TYPE]] = MISSING,
        rules_channel: Absent[Optional[Union["models.GuildText", Snowflake_Type]]] = MISSING,
        public_updates_channel: Absent[Optional[Union["models.GuildText", Snowflake_Type]]] = MISSING,
        safety_alerts_channel: Absent[Optional[Union["models.GuildText", Snowflake_Type]]] = MISSING,
        preferred_locale: Absent[Optional[str]] = MISSING,
        premium_progress_bar_enabled: Absent[Optional[bool]] = False,
        # ToDo: Fill in guild features. No idea how this works - https://discord.com/developers/docs/resources/guild#guild-object-guild-features
        features: Absent[Optional[list[str]]] = MISSING,
        reason: Absent[Optional[str]] = MISSING,
    ) -> None:
        """
        Edit the guild.

        Args:
            name: The new name of the guild.
            description: The new description of the guild.
            verification_level: The new verification level for the guild.
            default_message_notifications: The new notification level for the guild.
            explicit_content_filter: The new explicit content filter level for the guild.
            afk_channel: The voice channel that should be the new AFK channel.
            afk_timeout: How many seconds does a member need to be afk before they get moved to the AFK channel. Must be either `60`, `300`, `900`, `1800` or `3600`, otherwise HTTPException will be raised.
            icon: The new icon. Requires a bytes like object or a path to an image.
            owner: The new owner of the guild. You, the bot, need to be owner for this to work.
            splash: The new invite splash image. Requires a bytes like object or a path to an image.
            discovery_splash: The new discovery image. Requires a bytes like object or a path to an image.
            banner: The new banner image. Requires a bytes like object or a path to an image.
            system_channel: The text channel where new system messages should appear. This includes boosts and welcome messages.
            system_channel_flags: The new settings for the system channel.
            rules_channel: The text channel where your rules and community guidelines are displayed.
            public_updates_channel: The text channel where updates from discord should appear.
            safety_alerts_channel: The text channel where safety alerts from discord should appear.
            preferred_locale: The new preferred locale of the guild. Must be an ISO 639 code.
            premium_progress_bar_enabled: The status of the Nitro boost bar.
            features: The enabled guild features
            reason: An optional reason for the audit log.

        """
        await self._client.http.modify_guild(
            guild_id=self.id,
            name=name,
            description=description,
            verification_level=int(verification_level) if verification_level else MISSING,
            default_message_notifications=(
                int(default_message_notifications) if default_message_notifications else MISSING
            ),
            explicit_content_filter=int(explicit_content_filter) if explicit_content_filter else MISSING,
            afk_channel_id=to_snowflake(afk_channel) if afk_channel else MISSING,
            afk_timeout=afk_timeout,
            icon=to_image_data(icon) if icon else MISSING,
            owner_id=to_snowflake(owner) if owner else MISSING,
            splash=to_image_data(splash) if splash else MISSING,
            discovery_splash=to_image_data(discovery_splash) if discovery_splash else MISSING,
            banner=to_image_data(banner) if banner else MISSING,
            system_channel_id=to_snowflake(system_channel) if system_channel else MISSING,
            system_channel_flags=int(system_channel_flags) if system_channel_flags else MISSING,
            rules_channel_id=to_snowflake(rules_channel) if rules_channel else MISSING,
            public_updates_channel_id=to_snowflake(public_updates_channel) if public_updates_channel else MISSING,
            safety_alerts_channel_id=to_snowflake(safety_alerts_channel) if safety_alerts_channel else MISSING,
            preferred_locale=preferred_locale,
            premium_progress_bar_enabled=premium_progress_bar_enabled if premium_progress_bar_enabled else False,
            features=features,
            reason=reason,
        )

    async def create_custom_emoji(
        self,
        name: str,
        imagefile: UPLOADABLE_TYPE,
        roles: Absent[List[Union[Snowflake_Type, "models.Role"]]] = MISSING,
        reason: Absent[Optional[str]] = MISSING,
    ) -> "models.CustomEmoji":
        """
        Create a new custom emoji for the guild.

        Args:
            name: Name of the emoji
            imagefile: The emoji image. (Supports PNG, JPEG, WebP, GIF)
            roles: Roles allowed to use this emoji.
            reason: An optional reason for the audit log.

        Returns:
            The new custom emoji created.

        """
        data_payload = {
            "name": name,
            "image": to_image_data(imagefile),
            "roles": to_snowflake_list(roles) if roles else MISSING,
        }

        emoji_data = await self._client.http.create_guild_emoji(data_payload, self.id, reason=reason)
        return self._client.cache.place_emoji_data(self.id, emoji_data)

    async def create_guild_template(self, name: str, description: Absent[str] = MISSING) -> "models.GuildTemplate":
        """
        Create a new guild template based on this guild.

        Args:
            name: The name of the template (1-100 characters)
            description: The description for the template (0-120 characters)

        Returns:
            The new guild template created.

        """
        template = await self._client.http.create_guild_template(self.id, name, description)
        return GuildTemplate.from_dict(template, self._client)

    async def fetch_guild_templates(self) -> List["models.GuildTemplate"]:
        """
        Fetch all guild templates for this guild.

        Returns:
            A list of guild template objects.

        """
        templates = await self._client.http.get_guild_templates(self.id)
        return GuildTemplate.from_list(templates, self._client)

    async def fetch_all_custom_emojis(self) -> List["models.CustomEmoji"]:
        """
        Gets all the custom emoji present for this guild.

        Returns:
            A list of custom emoji objects.

        """
        emojis_data = await self._client.http.get_all_guild_emoji(self.id)
        return [self._client.cache.place_emoji_data(self.id, emoji_data) for emoji_data in emojis_data]

    async def fetch_custom_emoji(
        self, emoji_id: Snowflake_Type, *, force: bool = False
    ) -> Optional["models.CustomEmoji"]:
        """
        Fetches the custom emoji present for this guild, based on the emoji id.

        Args:
            emoji_id: The target emoji to get data of.
            force: Whether to force fetch the emoji from the API.

        Returns:
            The custom emoji object. If the emoji is not found, returns None.

        """
        try:
            return await self._client.cache.fetch_emoji(self.id, emoji_id, force=force)
        except NotFound:
            return None

    def get_custom_emoji(self, emoji_id: Snowflake_Type) -> Optional["models.CustomEmoji"]:
        """
        Gets the custom emoji present for this guild, based on the emoji id.

        Args:
            emoji_id: The target emoji to get data of.

        Returns:
            The custom emoji object.

        """
        emoji_id = to_snowflake(emoji_id)
        emoji = self._client.cache.get_emoji(emoji_id)
        return emoji if emoji and emoji._guild_id == self.id else None

    async def create_channel(
        self,
        channel_type: Union[ChannelType, int],
        name: str,
        topic: Absent[Optional[str]] = MISSING,
        position: Absent[Optional[int]] = MISSING,
        permission_overwrites: Absent[
            Union[dict, "models.PermissionOverwrite", List[Union[dict, "models.PermissionOverwrite"]]]
        ] = MISSING,
        category: Union[Snowflake_Type, "models.GuildCategory"] = None,
        nsfw: bool = False,
        bitrate: int = 64000,
        user_limit: int = 0,
        rate_limit_per_user: int = 0,
        reason: Absent[Optional[str]] = MISSING,
        **kwargs: dict,
    ) -> "models.TYPE_GUILD_CHANNEL":
        """
        Create a guild channel, allows for explicit channel type setting.

        Args:
            channel_type: The type of channel to create
            name: The name of the channel
            topic: The topic of the channel
            position: The position of the channel in the channel list
            permission_overwrites: Permission overwrites to apply to the channel
            category: The category this channel should be within
            nsfw: Should this channel be marked nsfw
            bitrate: The bitrate of this channel, only for voice
            user_limit: The max users that can be in this channel, only for voice
            rate_limit_per_user: The time users must wait between sending messages
            reason: The reason for creating this channel
            kwargs: Additional keyword arguments to pass to the channel creation

        Returns:
            The newly created channel.

        """
        channel_data = await self._client.http.create_guild_channel(
            self.id,
            name,
            channel_type,
            topic,
            position,
            models.process_permission_overwrites(permission_overwrites),
            to_optional_snowflake(category),
            nsfw,
            bitrate,
            user_limit,
            rate_limit_per_user,
            reason,
            **kwargs,
        )
        return self._client.cache.place_channel_data(channel_data)

    async def create_text_channel(
        self,
        name: str,
        topic: Absent[Optional[str]] = MISSING,
        position: Absent[Optional[int]] = MISSING,
        permission_overwrites: Absent[
            Union[dict, "models.PermissionOverwrite", List[Union[dict, "models.PermissionOverwrite"]]]
        ] = MISSING,
        category: Union[Snowflake_Type, "models.GuildCategory"] = None,
        nsfw: bool = False,
        rate_limit_per_user: int = 0,
        reason: Absent[Optional[str]] = MISSING,
    ) -> "models.GuildText":
        """
        Create a text channel in this guild.

        Args:
            name: The name of the channel
            topic: The topic of the channel
            position: The position of the channel in the channel list
            permission_overwrites: Permission overwrites to apply to the channel
            category: The category this channel should be within
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
            category=category,
            nsfw=nsfw,
            rate_limit_per_user=rate_limit_per_user,
            reason=reason,
        )

    async def create_forum_channel(
        self,
        name: str,
        topic: Absent[Optional[str]] = MISSING,
        position: Absent[Optional[int]] = MISSING,
        permission_overwrites: Absent[
            Union[dict, "models.PermissionOverwrite", List[Union[dict, "models.PermissionOverwrite"]]]
        ] = MISSING,
        category: Union[Snowflake_Type, "models.GuildCategory"] = None,
        nsfw: bool = False,
        rate_limit_per_user: int = 0,
        default_reaction_emoji: Absent[Union[dict, "models.PartialEmoji", "models.DefaultReaction", str]] = MISSING,
        available_tags: Absent["list[dict | models.ThreadTag] | dict | models.ThreadTag"] = MISSING,
        layout: ForumLayoutType = ForumLayoutType.NOT_SET,
        sort_order: Absent[ForumSortOrder] = MISSING,
        reason: Absent[Optional[str]] = MISSING,
    ) -> "models.GuildForum":
        """
        Create a forum channel in this guild.

        Args:
            name: The name of the forum channel
            topic: The topic of the forum channel
            position: The position of the forum channel in the channel list
            permission_overwrites: Permission overwrites to apply to the forum channel
            category: The category this forum channel should be within
            nsfw: Should this forum be marked nsfw
            rate_limit_per_user: The time users must wait between sending messages
            default_reaction_emoji: The default emoji to react with when creating a thread
            available_tags: The available tags for this forum channel
            layout: The layout of the forum channel
            sort_order: The sort order of the forum channel
            reason: The reason for creating this channel

        Returns:
           The newly created forum channel.

        """
        return await self.create_channel(
            channel_type=ChannelType.GUILD_FORUM,
            name=name,
            topic=topic,
            position=position,
            permission_overwrites=permission_overwrites,
            category=category,
            nsfw=nsfw,
            rate_limit_per_user=rate_limit_per_user,
            default_reaction_emoji=models.process_default_reaction(default_reaction_emoji),
            available_tags=list_converter(models.process_thread_tag)(available_tags) if available_tags else MISSING,
            default_forum_layout=layout,
            default_sort_order=sort_order,
            reason=reason,
        )

    async def create_news_channel(
        self,
        name: str,
        topic: Absent[Optional[str]] = MISSING,
        position: Absent[Optional[int]] = MISSING,
        permission_overwrites: Absent[
            Union[dict, "models.PermissionOverwrite", List[Union[dict, "models.PermissionOverwrite"]]]
        ] = MISSING,
        category: Union[Snowflake_Type, "models.GuildCategory"] = None,
        nsfw: bool = False,
        reason: Absent[Optional[str]] = MISSING,
    ) -> "models.GuildNews":
        """
        Create a news channel in this guild.

        Args:
            name: The name of the channel
            topic: The topic of the channel
            position: The position of the channel in the channel list
            permission_overwrites: Permission overwrites to apply to the channel
            category: The category this channel should be within
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
            category=category,
            nsfw=nsfw,
            reason=reason,
        )

    async def create_voice_channel(
        self,
        name: str,
        topic: Absent[Optional[str]] = MISSING,
        position: Absent[Optional[int]] = MISSING,
        permission_overwrites: Absent[
            Union[dict, "models.PermissionOverwrite", List[Union[dict, "models.PermissionOverwrite"]]]
        ] = MISSING,
        category: Union[Snowflake_Type, "models.GuildCategory"] = None,
        nsfw: bool = False,
        bitrate: int = 64000,
        user_limit: int = 0,
        reason: Absent[Optional[str]] = MISSING,
    ) -> "models.GuildVoice":
        """
        Create a guild voice channel.

        Args:
            name: The name of the channel
            topic: The topic of the channel
            position: The position of the channel in the channel list
            permission_overwrites: Permission overwrites to apply to the channel
            category: The category this channel should be within
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
            category=category,
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
            Union[dict, "models.PermissionOverwrite", List[Union[dict, "models.PermissionOverwrite"]]]
        ] = MISSING,
        category: Absent[Union[Snowflake_Type, "models.GuildCategory"]] = MISSING,
        bitrate: int = 64000,
        user_limit: int = 0,
        reason: Absent[Optional[str]] = MISSING,
    ) -> "models.GuildStageVoice":
        """
        Create a guild stage channel.

        Args:
            name: The name of the channel
            topic: The topic of the channel
            position: The position of the channel in the channel list
            permission_overwrites: Permission overwrites to apply to the channel
            category: The category this channel should be within
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
            category=category,
            bitrate=bitrate,
            user_limit=user_limit,
            reason=reason,
        )

    async def create_category(
        self,
        name: str,
        position: Absent[Optional[int]] = MISSING,
        permission_overwrites: Absent[
            Union[dict, "models.PermissionOverwrite", List[Union[dict, "models.PermissionOverwrite"]]]
        ] = MISSING,
        reason: Absent[Optional[str]] = MISSING,
    ) -> "models.GuildCategory":
        """
        Create a category within this guild.

        Args:
            name: The name of the channel
            position: The position of the channel in the channel list
            permission_overwrites: Permission overwrites to apply to the channel
            reason: The reason for creating this channel

        Returns:
            The newly created category.

        """
        return await self.create_channel(
            channel_type=ChannelType.GUILD_CATEGORY,
            name=name,
            position=position,
            permission_overwrites=permission_overwrites,
            reason=reason,
        )

    async def delete_channel(
        self, channel: Union["models.TYPE_GUILD_CHANNEL", Snowflake_Type], reason: str | None = None
    ) -> None:
        """
        Delete the given channel, can handle either a snowflake or channel object.

        This is effectively just an alias for `channel.delete()`

        Args:
            channel: The channel to be deleted
            reason: The reason for this deletion

        """
        if isinstance(channel, (str, int)):
            channel = await self._client.fetch_channel(channel)

        if not channel:
            raise ValueError("Unable to find requested channel")

        if channel.id not in self._channel_ids:
            raise ValueError("This guild does not hold the requested channel")

        await channel.delete(reason)

    async def list_scheduled_events(self, with_user_count: bool = False) -> List["models.ScheduledEvent"]:
        """
        List all scheduled events in this guild.

        Returns:
            A list of scheduled events.

        """
        scheduled_events_data = await self._client.http.list_schedules_events(self.id, with_user_count)
        return [self._client.cache.place_scheduled_event_data(data) for data in scheduled_events_data]

    def get_scheduled_event(self, scheduled_event_id: Snowflake_Type) -> Optional["models.ScheduledEvent"]:
        """
        Gets a scheduled event from the cache by id.

        Args:
            scheduled_event_id: The id of the scheduled event.

        Returns:
            The scheduled event. If the event does not exist, returns None.

        """
        event = self._client.cache.get_scheduled_event(scheduled_event_id)
        return None if event and int(event._guild_id) != self.id else event

    async def fetch_scheduled_event(
        self,
        scheduled_event_id: Snowflake_Type,
        with_user_count: bool = False,
        *,
        force: bool = False,
    ) -> Optional["models.ScheduledEvent"]:
        """
        Fetches a scheduled event by id.

        Args:
            scheduled_event_id: The id of the scheduled event.
            with_user_count: Whether to include the user count in the response.
            force: If the cache should be ignored, and the event should be fetched from the API

        Returns:
            The scheduled event. If the event does not exist, returns None.

        """
        try:
            return await self._client.cache.fetch_scheduled_event(
                self.id, scheduled_event_id, with_user_count=with_user_count, force=force
            )
        except NotFound:
            return None

    async def create_scheduled_event(
        self,
        name: str,
        event_type: ScheduledEventType,
        start_time: "models.Timestamp",
        end_time: Absent[Optional["models.Timestamp"]] = MISSING,
        description: Absent[Optional[str]] = MISSING,
        channel_id: Absent[Optional[Snowflake_Type]] = MISSING,
        external_location: Absent[Optional[str]] = MISSING,
        entity_metadata: Optional[dict] = None,
        privacy_level: ScheduledEventPrivacyLevel = ScheduledEventPrivacyLevel.GUILD_ONLY,
        cover_image: Absent[UPLOADABLE_TYPE] = MISSING,
        reason: Absent[Optional[str]] = MISSING,
    ) -> "models.ScheduledEvent":
        """
        Create a scheduled guild event.

        Args:
            name: event name
            event_type: event type
            start_time: `Timestamp` object
            end_time: `Timestamp` object
            description: event description
            channel_id: channel id
            external_location: event external location (For external events)
            entity_metadata: event metadata (additional data for the event)
            privacy_level: event privacy level
            cover_image: the cover image of the scheduled event
            reason: reason for creating this scheduled event

        Returns:
            The newly created ScheduledEvent object

        !!! note
            For external events, external_location is required
            For voice/stage events, channel_id is required

        ??? note
            entity_metadata is the backend dictionary for fluff fields. Where possible, we plan to expose these fields directly.
            The full list of supported fields is https://discord.com/developers/docs/resources/guild-scheduled-event#guild-scheduled-event-object-guild-scheduled-event-entity-metadata
            Example: `entity_metadata=dict(location="cool place")`

        """
        if external_location is not MISSING:
            entity_metadata = {"location": external_location}

        if event_type == ScheduledEventType.EXTERNAL and external_location == MISSING:
            raise EventLocationNotProvided("Location is required for external events")

        payload = {
            "name": name,
            "entity_type": event_type,
            "scheduled_start_time": start_time.isoformat(),
            "scheduled_end_time": end_time.isoformat() if end_time is not MISSING else end_time,
            "description": description,
            "channel_id": channel_id,
            "entity_metadata": entity_metadata,
            "privacy_level": privacy_level,
            "image": to_image_data(cover_image) if cover_image else MISSING,
        }

        scheduled_event_data = await self._client.http.create_scheduled_event(self.id, payload, reason)
        return self._client.cache.place_scheduled_event_data(scheduled_event_data)

    async def create_custom_sticker(
        self,
        name: str,
        file: UPLOADABLE_TYPE,
        tags: list[str],
        description: Absent[Optional[str]] = MISSING,
        reason: Absent[Optional[str]] = MISSING,
    ) -> "models.Sticker":
        """
        Creates a custom sticker for a guild.

        Args:
            name: The name of the sticker (2-30 characters)
            file: The sticker file to upload, must be a PNG, APNG, or Lottie JSON file (max 500 KB)
            tags: Autocomplete/suggestion tags for the sticker (max 200 characters)
            description: The description of the sticker (empty or 2-100 characters)
            reason: Reason for creating the sticker

        Returns:
            New Sticker instance

        """
        payload = {"name": name, "tags": " ".join(tags)}

        if description:
            payload["description"] = description

        sticker_data = await self._client.http.create_guild_sticker(payload, self.id, file=file, reason=reason)
        return models.Sticker.from_dict(sticker_data, self._client)

    async def fetch_all_custom_stickers(self) -> List["models.Sticker"]:
        """
        Fetches all custom stickers for a guild.

        Returns:
            List of Sticker objects

        """
        stickers_data = await self._client.http.list_guild_stickers(self.id)
        return models.Sticker.from_list(stickers_data, self._client)

    async def fetch_custom_sticker(self, sticker_id: Snowflake_Type) -> Optional["models.Sticker"]:
        """
        Fetches a specific custom sticker for a guild.

        Args:
            sticker_id: ID of sticker to get

        Returns:
            The custom sticker object. If the sticker does not exist, returns None.

        """
        try:
            sticker_data = await self._client.http.get_guild_sticker(self.id, to_snowflake(sticker_id))
        except NotFound:
            return None
        return models.Sticker.from_dict(sticker_data, self._client)

    async def fetch_all_webhooks(self) -> List["models.Webhook"]:
        """
        Fetches all the webhooks for this guild.

        Returns:
            A list of webhook objects.

        """
        webhooks_data = await self._client.http.get_guild_webhooks(self.id)
        return models.Webhook.from_list(webhooks_data, self._client)

    async def fetch_active_threads(self) -> "models.ThreadList":
        """
        Fetches all active threads in the guild, including public and private threads. Threads are ordered by their id, in descending order.

        Returns:
            List of active threads and thread member object for each returned thread the bot user has joined.

        """
        threads_data = await self._client.http.list_active_threads(self.id)
        return models.ThreadList.from_dict(threads_data, self._client)

    async def fetch_role(self, role_id: Snowflake_Type, *, force: bool = False) -> Optional["models.Role"]:
        """
        Fetch the specified role by ID.

        Args:
            role_id: The ID of the role to get
            force: Whether to force a fetch from the API

        Returns:
            The role object. If the role does not exist, returns None.

        """
        try:
            return await self._client.cache.fetch_role(self.id, role_id, force=force)
        except NotFound:
            return None

    def get_role(self, role_id: Snowflake_Type) -> Optional["models.Role"]:
        """
        Get the specified role by ID.

        Args:
            role_id: The ID of the role to get

        Returns:
            A role object or None if the role is not found.

        """
        role_id = to_snowflake(role_id)
        if role_id in self._role_ids:
            return self._client.cache.get_role(role_id)
        return None

    async def create_role(
        self,
        name: Absent[Optional[str]] = MISSING,
        permissions: Absent[Optional[Permissions]] = MISSING,
        colour: Absent[Optional[Union["models.Color", int]]] = MISSING,
        color: Absent[Optional[Union["models.Color", int]]] = MISSING,
        hoist: Optional[bool] = False,
        mentionable: Optional[bool] = False,
        icon: Absent[Optional[UPLOADABLE_TYPE]] = MISSING,
        reason: Absent[Optional[str]] = MISSING,
    ) -> "models.Role":
        """
        Create a new role for the guild. You must have the `manage roles` permission.

        Args:
            name: The name the role should have. `Default: new role`
            permissions: The permissions the role should have. `Default: @everyone permissions`
            colour: The colour of the role. Can be either `Color` or an RGB integer. `Default: BrandColors.BLACK`
            color: Alias for `colour`
            icon: Can be either a bytes like object or a path to an image, or a unicode emoji which is supported by discord.
            hoist: Whether the role is shown separately in the members list. `Default: False`
            mentionable: Whether the role can be mentioned. `Default: False`
            reason: An optional reason for the audit log.

        Returns:
            A role object or None if the role is not found.

        """
        payload = {}

        if name:
            payload["name"] = name

        if permissions is not MISSING and permissions is not None:
            payload["permissions"] = str(int(permissions))

        if colour := colour or color:
            payload["color"] = colour if isinstance(colour, int) else colour.value

        if hoist:
            payload["hoist"] = True

        if mentionable:
            payload["mentionable"] = True

        if icon:
            # test if the icon is probably a unicode emoji (str and len() == 1) or a path / bytes obj
            if isinstance(icon, str) and len(icon) == 1:
                payload["unicode_emoji"] = icon

            else:
                payload["icon"] = to_image_data(icon)

        result = await self._client.http.create_guild_role(guild_id=self.id, payload=payload, reason=reason)
        return self._client.cache.place_role_data(guild_id=self.id, data=[result])[to_snowflake(result["id"])]

    def get_channel(self, channel_id: Snowflake_Type) -> Optional["models.TYPE_GUILD_CHANNEL"]:
        """
        Returns a channel with the given `channel_id`.

        Args:
            channel_id: The ID of the channel to get

        Returns:
            Channel object if found, otherwise None

        """
        channel_id = to_snowflake(channel_id)
        if channel_id in self._channel_ids:
            # theoretically, this could get any channel the client can see,
            # but to make it less confusing to new programmers,
            # i intentionally check that the guild contains the channel first
            return self._client.cache.get_channel(channel_id)
        return None

    async def fetch_channel(
        self, channel_id: Snowflake_Type, *, force: bool = False
    ) -> Optional["models.TYPE_GUILD_CHANNEL"]:
        """
        Returns a channel with the given `channel_id` from the API.

        Args:
            channel_id: The ID of the channel to get
            force: Whether to force a fetch from the API

        Returns:
            The channel object. If the channel does not exist, returns None.

        """
        channel_id = to_snowflake(channel_id)
        if channel_id in self._channel_ids or not self._client.gateway_started:
            # The latter check here is to see if the bot is running with the gateway.
            # If not, then we need to check the API since only the gateway
            # populates the channel IDs

            # theoretically, this could get any channel the client can see,
            # but to make it less confusing to new programmers,
            # i intentionally check that the guild contains the channel first
            try:
                channel = await self._client.fetch_channel(channel_id, force=force)
                if channel._guild_id == self.id:
                    return channel
            except (NotFound, AttributeError):
                return None

        return None

    def get_thread(self, thread_id: Snowflake_Type) -> Optional["models.TYPE_THREAD_CHANNEL"]:
        """
        Returns a Thread with the given `thread_id`.

        Args:
            thread_id: The ID of the thread to get

        Returns:
            Thread object if found, otherwise None

        """
        thread_id = to_snowflake(thread_id)
        if thread_id in self._thread_ids:
            return self._client.cache.get_channel(thread_id)
        return None

    async def fetch_thread(
        self, thread_id: Snowflake_Type, *, force: bool = False
    ) -> Optional["models.TYPE_THREAD_CHANNEL"]:
        """
        Returns a Thread with the given `thread_id` from the API.

        Args:
            thread_id: The ID of the thread to get
            force: Whether to force a fetch from the API

        Returns:
            Thread object if found, otherwise None

        """
        thread_id = to_snowflake(thread_id)
        if thread_id in self._thread_ids:
            try:
                return await self._client.fetch_channel(thread_id, force=force)
            except NotFound:
                return None
        return None

    async def prune_members(
        self,
        days: int = 7,
        roles: Optional[List[Snowflake_Type]] = None,
        compute_prune_count: bool = True,
        reason: Absent[str] = MISSING,
    ) -> Optional[int]:
        """
        Begin a guild prune. Removes members from the guild who who have not interacted for the last `days` days. By default, members with roles are excluded from pruning, to include them, pass their role (or role id) in `roles` Requires `kick members` permission.

        Args:
            days: number of days to prune (1-30)
            roles: list of roles to include in the prune
            compute_prune_count: Whether the number of members pruned should be calculated (disable this for large guilds)
            reason: The reason for this prune

        Returns:
            The total number of members pruned, if `compute_prune_count` is set to True, otherwise None

        """
        if roles:
            roles = [str(to_snowflake(r)) for r in roles]

        resp = await self._client.http.begin_guild_prune(
            self.id,
            days,
            include_roles=roles,
            compute_prune_count=compute_prune_count,
            reason=reason,
        )
        return resp["pruned"]

    async def estimate_prune_members(
        self, days: int = 7, roles: List[Union[Snowflake_Type, "models.Role"]] = MISSING
    ) -> int:
        """
        Calculate how many members would be pruned, should `guild.prune_members` be used. By default, members with roles are excluded from pruning, to include them, pass their role (or role id) in `roles`.

        Args:
            days: number of days to prune (1-30)
            roles: list of roles to include in the prune

        Returns:
            Total number of members that would be pruned

        """
        if roles is not MISSING:
            roles = [r.id if isinstance(r, models.Role) else r for r in roles]
        else:
            roles = []

        resp = await self._client.http.get_guild_prune_count(self.id, days=days, include_roles=roles)
        return resp["pruned"]

    async def leave(self) -> None:
        """Leave this guild."""
        await self._client.http.leave_guild(self.id)

    async def delete(self) -> None:
        """
        Delete the guild.

        !!! note
            You must own this guild to do this.

        """
        await self._client.http.delete_guild(self.id)

    async def kick(
        self,
        user: Union["models.User", "models.Member", Snowflake_Type],
        reason: Absent[str] = MISSING,
    ) -> None:
        """
        Kick a user from the guild.

        !!! note
            You must have the `kick members` permission

        Args:
            user: The user to kick
            reason: The reason for the kick

        """
        await self._client.http.remove_guild_member(self.id, to_snowflake(user), reason=reason)

    async def ban(
        self,
        user: Union["models.User", "models.Member", Snowflake_Type],
        delete_message_days: Absent[int] = MISSING,
        delete_message_seconds: int = 0,
        reason: Absent[str] = MISSING,
    ) -> None:
        """
        Ban a user from the guild.

        !!! note
            You must have the `ban members` permission

        Args:
            user: The user to ban
            delete_message_days: (deprecated) How many days worth of messages to remove
            delete_message_seconds: How many seconds worth of messages to remove
            reason: The reason for the ban

        """
        if delete_message_days is not MISSING:
            warn(
                "delete_message_days is deprecated and will be removed in a future update",
                DeprecationWarning,
                stacklevel=2,
            )
            delete_message_seconds = delete_message_days * 3600
        await self._client.http.create_guild_ban(self.id, to_snowflake(user), delete_message_seconds, reason=reason)

    async def bulk_ban(
        self,
        users: List[Union["models.User", "models.Member", Snowflake_Type]],
        delete_message_seconds: int = 0,
        reason: Optional[str] = None,
    ) -> BulkBanResponse:
        """
        Bans a list of users from the guild.

        !!! note
            You must have the `ban members` permission

        Args:
            user: The users to ban
            delete_message_seconds: How many seconds worth of messages to remove
            reason: The reason for the ban

        """
        result = await self.client.http.bulk_guild_ban(
            self.id, [to_snowflake(user) for user in users], delete_message_seconds, reason=reason
        )
        return BulkBanResponse.from_dict(result, self.client)

    async def fetch_ban(self, user: Union["models.User", "models.Member", Snowflake_Type]) -> Optional[GuildBan]:
        """
        Fetches the ban information for the specified user in the guild. You must have the `ban members` permission.

        Args:
            user: The user to look up.

        Returns:
            The ban information. If the user is not banned, returns None.

        """
        try:
            ban_info = await self._client.http.get_guild_ban(self.id, to_snowflake(user))
        except NotFound:
            return None
        return GuildBan(reason=ban_info["reason"], user=self._client.cache.place_user_data(ban_info["user"]))

    async def fetch_bans(
        self,
        before: Optional["Snowflake_Type"] = MISSING,
        after: Optional["Snowflake_Type"] = MISSING,
        limit: int = 1000,
    ) -> list[GuildBan]:
        """
        Fetches bans for the guild. You must have the `ban members` permission.

        Args:
            before: consider only users before given user id
            after: consider only users after given user id
            limit: number of users to return (up to maximum 1000)

        Returns:
            A list containing bans and information about them.

        """
        ban_infos = await self._client.http.get_guild_bans(self.id, before=before, after=after, limit=limit)
        return [
            GuildBan(reason=ban_info["reason"], user=self._client.cache.place_user_data(ban_info["user"]))
            for ban_info in ban_infos
        ]

    async def create_auto_moderation_rule(
        self,
        name: str,
        *,
        trigger: BaseTrigger,
        actions: list[BaseAction],
        exempt_roles: list["Snowflake_Type"] = MISSING,
        exempt_channels: list["Snowflake_Type"] = MISSING,
        enabled: bool = True,
        event_type: AutoModEvent = AutoModEvent.MESSAGE_SEND,
    ) -> AutoModRule:
        """
        Create an auto-moderation rule in this guild.

        Args:
            name: The name of the rule
            trigger: The trigger for this rule
            actions: A list of actions to take upon triggering
            exempt_roles: Roles that ignore this rule
            exempt_channels: Channels that ignore this role
            enabled: Is this rule enabled?
            event_type: The type of event that triggers this rule

        Returns:
            The created rule

        """
        rule = AutoModRule(
            name=name,
            enabled=enabled,
            actions=actions,
            event_type=event_type,
            trigger=trigger,
            exempt_channels=exempt_channels if exempt_roles is not MISSING else [],
            exempt_roles=exempt_roles if exempt_roles is not MISSING else [],
            client=self._client,
        )
        data = await self._client.http.create_auto_moderation_rule(self.id, rule.to_dict())
        return AutoModRule.from_dict(data, self._client)

    async def fetch_auto_moderation_rules(self) -> List[AutoModRule]:
        """
        Get this guild's auto moderation rules.

        Returns:
            A list of auto moderation rules

        """
        data = await self._client.http.get_auto_moderation_rules(self.id)
        return [AutoModRule.from_dict(d, self._client) for d in data]

    async def delete_auto_moderation_rule(self, rule: "Snowflake_Type", reason: Absent[str] = MISSING) -> None:
        """
        Delete a given auto moderation rule.

        Args:
            rule: The rule to delete
            reason: The reason for deleting this rule

        """
        await self._client.http.delete_auto_moderation_rule(self.id, to_snowflake(rule), reason=reason)

    async def modify_auto_moderation_rule(
        self,
        rule: "Snowflake_Type",
        *,
        name: Absent[str] = MISSING,
        trigger: Absent[BaseTrigger] = MISSING,
        trigger_type: Absent[AutoModTriggerType] = MISSING,
        trigger_metadata: Absent[dict] = MISSING,
        actions: Absent[list[BaseAction]] = MISSING,
        exempt_channels: Absent[list["Snowflake_Type"]] = MISSING,
        exempt_roles: Absent[list["Snowflake_Type"]] = MISSING,
        event_type: Absent[AutoModEvent] = MISSING,
        enabled: Absent[bool] = MISSING,
        reason: Absent[str] = MISSING,
    ) -> AutoModRule:
        """
        Modify an existing automod rule.

        Args:
            rule: The rule to modify
            name: The name of the rule
            trigger: A trigger for this rule
            trigger_type: The type trigger for this rule (ignored if trigger specified)
            trigger_metadata: Metadata for the trigger (ignored if trigger specified)
            actions: A list of actions to take upon triggering
            exempt_roles: Roles that ignore this rule
            exempt_channels: Channels that ignore this role
            enabled: Is this rule enabled?
            event_type: The type of event that triggers this rule
            reason: The reason for this change

        Returns:
            The updated rule

        """
        if trigger:
            _data = trigger.to_dict()
            trigger_type = _data["trigger_type"]
            trigger_metadata = _data.get("trigger_metadata", {})

        out = await self._client.http.modify_auto_moderation_rule(
            self.id,
            to_snowflake(rule),
            name=name,
            trigger_type=trigger_type,
            trigger_metadata=trigger_metadata,
            actions=actions,
            exempt_roles=to_snowflake_list(exempt_roles) if exempt_roles is not MISSING else MISSING,
            exempt_channels=to_snowflake_list(exempt_channels) if exempt_channels is not MISSING else MISSING,
            event_type=event_type,
            enabled=enabled,
            reason=reason,
        )
        return AutoModRule.from_dict(out, self._client)

    async def unban(
        self,
        user: Union["models.User", "models.Member", Snowflake_Type],
        reason: Absent[str] = MISSING,
    ) -> None:
        """
        Unban a user from the guild.

        !!! note
            You must have the `ban members` permission

        Args:
            user: The user to unban
            reason: The reason for the ban

        """
        await self._client.http.remove_guild_ban(self.id, to_snowflake(user), reason=reason)

    async def fetch_widget_image(self, style: str | None = None) -> str:
        """
        Fetch a guilds widget image.

        For a list of styles, look here: https://discord.com/developers/docs/resources/guild#get-guild-widget-image-widget-style-options

        Args:
            style: The style to use for the widget image

        Returns:
            The URL of the widget image.

        """
        return await self._client.http.get_guild_widget_image(self.id, style)

    async def fetch_widget_settings(self) -> "GuildWidgetSettings":
        """
        Fetches the guilds widget settings.

        Returns:
            The guilds widget settings object.

        """
        return await GuildWidgetSettings.from_dict(await self._client.http.get_guild_widget_settings(self.id))

    async def fetch_widget(self) -> "GuildWidget":
        """
        Fetches the guilds widget.

        Returns:
            The guilds widget object.

        """
        return GuildWidget.from_dict(await self._client.http.get_guild_widget(self.id), self._client)

    async def modify_widget(
        self,
        enabled: Absent[bool] = MISSING,
        channel: Absent[Union["models.TYPE_GUILD_CHANNEL", Snowflake_Type]] = MISSING,
        settings: Absent["GuildWidgetSettings"] = MISSING,
    ) -> "GuildWidget":
        """
        Modify the guild's widget.

        Args:
            enabled: Should the widget be enabled?
            channel: The channel to use in the widget
            settings: The settings to use for the widget

        Returns:
            The updated guilds widget object.

        """
        if isinstance(settings, GuildWidgetSettings):
            enabled = settings.enabled
            channel = settings.channel_id

        channel = to_optional_snowflake(channel)
        return GuildWidget.from_dict(
            await self._client.http.modify_guild_widget(self.id, enabled, channel), self._client
        )

    async def fetch_invites(self) -> List["models.Invite"]:
        """
        Fetches all invites for the guild.

        Returns:
            A list of invites for the guild.

        """
        invites_data = await self._client.http.get_guild_invites(self.id)
        return models.Invite.from_list(invites_data, self._client)

    async def fetch_guild_integrations(self) -> List["models.GuildIntegration"]:
        """
        Fetches all integrations for the guild.

        Returns:
            A list of integrations for the guild.

        """
        data = await self._client.http.get_guild_integrations(self.id)
        return [GuildIntegration.from_dict(d | {"guild_id": self.id}, self._client) for d in data]

    async def search_members(self, query: str, limit: int = 1) -> List["models.Member"]:
        """
        Search for members in the guild whose username or nickname starts with a provided string.

        Args:
            query: Query string to match username(s) and nickname(s) against.
            limit: Max number of members to return (1-1000)

        Returns:
            A list of members matching the query.

        """
        data = await self._client.http.search_guild_members(guild_id=self.id, query=query, limit=limit)
        return [self._client.cache.place_member_data(self.id, _d) for _d in data]

    async def fetch_voice_regions(self) -> List["models.VoiceRegion"]:
        """
        Fetches the voice regions for the guild.

        Unlike the `Client.fetch_voice_regions` method, this will returns VIP servers when the guild is VIP-enabled.

        Returns:
            A list of voice regions.

        """
        regions_data = await self._client.http.get_guild_voice_regions(self.id)
        return models.VoiceRegion.from_list(regions_data)

    async def fetch_onboarding(self) -> Onboarding:
        """
        Fetches the guild's onboarding settings.

        Returns:
            The guild's onboarding settings.

        """
        return Onboarding.from_dict(await self._client.http.get_guild_onboarding(self.id), self._client)

    @property
    def gui_sorted_channels(self) -> list["models.TYPE_GUILD_CHANNEL"]:
        """Return this guilds channels sorted by their gui positions"""
        # create a sorted list of objects by their gui position
        if not self._channel_gui_positions:
            self._calculate_gui_channel_positions()
        return [
            self._client.get_channel(k)
            for k, v in sorted(self._channel_gui_positions.items(), key=lambda item: item[1])
        ]

    def get_channel_gui_position(self, channel_id: "Snowflake_Type") -> int:
        """
        Get a given channels gui position.

        Args:
            channel_id: The ID of the channel to get the gui position for.

        Returns:
            The gui position of the channel.

        """
        if not self._channel_gui_positions:
            self._calculate_gui_channel_positions()
        return self._channel_gui_positions.get(to_snowflake(channel_id), 0)

    def _calculate_gui_channel_positions(self) -> list["models.TYPE_GUILD_CHANNEL"]:
        """
        Calculates the GUI position for all known channels within this guild.

        Note this is an expensive operation and should only be run when actually required.

        Returns:
            The list of channels in this guild, sorted by their GUI position.

        """
        # sorting is based on this https://github.com/discord/discord-api-docs/issues/4613#issuecomment-1059997612
        sort_map = {
            ChannelType.GUILD_NEWS_THREAD: 1,
            ChannelType.GUILD_PUBLIC_THREAD: 1,
            ChannelType.GUILD_PRIVATE_THREAD: 1,
            ChannelType.GUILD_TEXT: 2,
            ChannelType.GUILD_CATEGORY: 2,
            ChannelType.GUILD_NEWS: 2,
            ChannelType.GUILD_FORUM: 2,  # assumed value
            ChannelType.GUILD_VOICE: 3,
            ChannelType.GUILD_STAGE_VOICE: 3,
        }

        def channel_sort_func(a, b) -> int:
            a_sorting = sort_map.get(a.type, 0)
            b_sorting = sort_map.get(b.type, 0)

            if a_sorting != b_sorting:
                return a_sorting - b_sorting
            return a.position - b.position or a.id - b.id

        sorted_channels = sorted(self.channels, key=cmp_to_key(channel_sort_func))

        for channel in sorted_channels[::-1]:
            if channel.parent_id:
                # sort channels under their respective categories
                sorted_channels.remove(channel)
                parent_index = sorted_channels.index(channel.category)
                sorted_channels.insert(parent_index + 1, channel)
            elif channel.type != ChannelType.GUILD_CATEGORY:
                # move non-category channels to the top
                sorted_channels.remove(channel)
                sorted_channels.insert(0, channel)

        self._channel_gui_positions = {channel.id: i for i, channel in enumerate(sorted_channels)}

        return sorted_channels


@attrs.define(eq=False, order=False, hash=False, kw_only=True)
class GuildTemplate(ClientObject):
    code: str = attrs.field(repr=True, metadata=docs("the template code (unique ID)"))
    name: str = attrs.field(repr=True, metadata=docs("the name"))
    description: Optional[str] = attrs.field(repr=False, default=None, metadata=docs("the description"))

    usage_count: int = attrs.field(repr=False, default=0, metadata=docs("number of times this template has been used"))

    creator_id: Snowflake_Type = attrs.field(repr=False, metadata=docs("The ID of the user who created this template"))
    creator: Optional["models.User"] = attrs.field(
        repr=False, default=None, metadata=docs("the user who created this template")
    )

    created_at: "models.Timestamp" = attrs.field(repr=False, metadata=docs("When this template was created"))
    updated_at: "models.Timestamp" = attrs.field(
        repr=False, metadata=docs("When this template was last synced to the source guild")
    )

    source_guild_id: Snowflake_Type = attrs.field(
        repr=False, metadata=docs("The ID of the guild this template is based on")
    )
    guild_snapshot: "models.Guild" = attrs.field(
        repr=False, metadata=docs("A snapshot of the guild this template contains")
    )

    is_dirty: bool = attrs.field(
        repr=False, default=False, metadata=docs("Whether this template has un-synced changes")
    )

    @classmethod
    def _process_dict(cls, data: Dict[str, Any], client: "Client") -> Dict[str, Any]:
        data["creator"] = client.cache.place_user_data(data["creator"])

        # todo: partial guild obj that **isn't** cached
        data["guild_snapshot"] = data.pop("serialized_source_guild")
        return data

    async def synchronise(self) -> "models.GuildTemplate":
        """Synchronise the template to the source guild's current state."""
        data = await self._client.http.sync_guild_template(self.source_guild_id, self.code)
        self.update_from_dict(data)
        return self

    async def modify(self, name: Absent[str] = MISSING, description: Absent[str] = MISSING) -> "models.GuildTemplate":
        """
        Modify the template's metadata.

        Args:
            name: The name for the template
            description: The description for the template

        Returns:
            The modified template object.

        """
        data = await self._client.http.modify_guild_template(
            self.source_guild_id, self.code, name=name, description=description
        )
        self.update_from_dict(data)
        return self

    async def delete(self) -> None:
        """Delete the guild template."""
        await self._client.http.delete_guild_template(self.source_guild_id, self.code)


@attrs.define(eq=False, order=False, hash=False, kw_only=True)
class GuildWelcomeChannel(ClientObject):
    channel_id: Snowflake_Type = attrs.field(repr=True, metadata=docs("Welcome Channel ID"))
    description: str = attrs.field(repr=False, metadata=docs("Welcome Channel description"))
    emoji_id: Optional[Snowflake_Type] = attrs.field(
        repr=False, default=None, metadata=docs("Welcome Channel emoji ID if the emoji is custom")
    )
    emoji_name: Optional[str] = attrs.field(
        repr=False,
        default=None,
        metadata=docs("Emoji name if custom, unicode character if standard"),
    )


class GuildIntegration(DiscordObject):
    name: str = attrs.field(repr=True)
    """The name of the integration"""
    type: str = attrs.field(repr=True)
    """integration type (twitch, youtube, or discord)"""
    enabled: bool = attrs.field(repr=True)
    """is this integration enabled"""
    account: dict = attrs.field(
        repr=False,
    )
    """integration account information"""
    application: Optional["models.Application"] = attrs.field(repr=False, default=None)
    """The bot/OAuth2 application for discord integrations"""
    _guild_id: Snowflake_Type = attrs.field(
        repr=False,
    )

    syncing: Optional[bool] = attrs.field(repr=False, default=MISSING)
    """is this integration syncing"""
    role_id: Optional[Snowflake_Type] = attrs.field(repr=False, default=MISSING)
    """id that this integration uses for "subscribers\""""
    enable_emoticons: bool = attrs.field(repr=False, default=MISSING)
    """whether emoticons should be synced for this integration (twitch only currently)"""
    expire_behavior: IntegrationExpireBehaviour = attrs.field(
        repr=False, default=MISSING, converter=optional(IntegrationExpireBehaviour)
    )
    """the behavior of expiring subscribers"""
    expire_grace_period: int = attrs.field(repr=False, default=MISSING)
    """the grace period (in days) before expiring subscribers"""
    user: "models.BaseUser" = attrs.field(repr=False, default=MISSING)
    """user for this integration"""
    synced_at: "models.Timestamp" = attrs.field(repr=False, default=MISSING, converter=optional(timestamp_converter))
    """when this integration was last synced"""
    subscriber_count: int = attrs.field(repr=False, default=MISSING)
    """how many subscribers this integration has"""
    revoked: bool = attrs.field(repr=False, default=MISSING)
    """has this integration been revoked"""

    @classmethod
    def _process_dict(cls, data: Dict[str, Any], client: "Client") -> Dict[str, Any]:
        if app := data.get("application", None):
            data["application"] = models.Application.from_dict(app, client)
        if user := data.get("user", None):
            data["user"] = client.cache.place_user_data(user)

        return data

    async def delete(self, reason: Absent[str] = MISSING) -> None:
        """Delete this guild integration."""
        await self._client.http.delete_guild_integration(self._guild_id, self.id, reason)


class GuildWidgetSettings(DictSerializationMixin):
    enabled: bool = attrs.field(repr=True, default=False)
    """Whether the widget is enabled."""
    channel_id: Optional["Snowflake_Type"] = attrs.field(repr=True, default=None, converter=to_optional_snowflake)
    """The widget channel id. None if widget is not enabled."""


class GuildWidget(DiscordObject):
    name: str = attrs.field(repr=True)
    """Guild name (2-100 characters)"""
    instant_invite: str = attrs.field(repr=True, default=None)
    """Instant invite for the guilds specified widget invite channel"""
    presence_count: int = attrs.field(repr=True, default=0)
    """Number of online members in this guild"""

    _channel_ids: List["Snowflake_Type"] = attrs.field(repr=False, default=[])
    """Voice and stage channels which are accessible by @everyone"""
    _member_ids: List["Snowflake_Type"] = attrs.field(repr=False, default=[])
    """Special widget user objects that includes users presence (Limit 100)"""

    @classmethod
    def _process_dict(cls, data: Dict[str, Any], client: "Client") -> Dict[str, Any]:
        if channels := data.get("channels"):
            data["channel_ids"] = [channel["id"] for channel in channels]
        if members := data.get("members"):
            data["member_ids"] = [member["id"] for member in members]
        return data

    def get_channels(self) -> List["models.TYPE_VOICE_CHANNEL"]:
        """
        Gets voice and stage channels which are accessible by @everyone

        Returns:
            List of channels

        """
        return [self._client.get_channel(channel_id) for channel_id in self._channel_ids]

    async def fetch_channels(self, *, force: bool = False) -> List["models.TYPE_VOICE_CHANNEL"]:
        """
        Gets voice and stage channels which are accessible by @everyone. Fetches the channels from API if they are not cached.

        Args:
            force: Whether to force fetch the channels from API

        Returns:
            List of channels

        """
        return [await self._client.fetch_channel(channel_id, force=force) for channel_id in self._channel_ids]

    def get_members(self) -> List["models.User"]:
        """
        Gets special widget user objects that includes users presence (Limit 100)

        Returns:
            List of users

        """
        return [self._client.get_user(member_id) for member_id in self._member_ids]

    async def fetch_members(self, *, force: bool = False) -> List["models.User"]:
        """
        Gets special widget user objects that includes users presence (Limit 100). Fetches the users from API if they are not cached.

        Args:
            force: Whether to force fetch the users from API

        Returns:
            List of users

        """
        return [await self._client.fetch_user(member_id, force=force) for member_id in self._member_ids]


@attrs.define(eq=False, order=False, hash=False, kw_only=True)
class AuditLogChange(ClientObject):
    key: str = attrs.field(repr=True)
    """name of audit log change key"""
    new_value: Optional[Union[list, str, int, bool, "Snowflake_Type"]] = attrs.field(repr=False, default=MISSING)
    """new value of the key"""
    old_value: Optional[Union[list, str, int, bool, "Snowflake_Type"]] = attrs.field(repr=False, default=MISSING)
    """old value of the key"""


@attrs.define(eq=False, order=False, hash=False, kw_only=True)
class AuditLogEntry(DiscordObject):
    target_id: Optional["Snowflake_Type"] = attrs.field(repr=False, converter=optional(to_snowflake))
    """id of the affected entity (webhook, user, role, etc.)"""
    user_id: "Snowflake_Type" = attrs.field(repr=False, converter=optional(to_snowflake))
    """the user who made the changes"""
    action_type: "AuditLogEventType" = attrs.field(repr=False, converter=AuditLogEventType)
    """type of action that occurred"""
    changes: Optional[List[AuditLogChange]] = attrs.field(repr=False, default=MISSING)
    """changes made to the target_id"""
    options: Optional[Union["Snowflake_Type", str]] = attrs.field(repr=False, default=MISSING)
    """additional info for certain action types"""
    reason: Optional[str] = attrs.field(repr=False, default=MISSING)
    """the reason for the change (0-512 characters)"""

    @classmethod
    def _process_dict(cls, data: Dict[str, Any], client: "Client") -> Dict[str, Any]:
        if changes := data.get("changes", None):
            data["changes"] = AuditLogChange.from_list(changes, client)

        return data


@attrs.define(eq=False, order=False, hash=False, kw_only=True)
class AuditLog(ClientObject):
    """Contains entries and other data given from selected"""

    application_commands: list["InteractionCommand"] = attrs.field(
        repr=False, factory=list, converter=optional(deserialize_app_cmds)
    )
    """list of application commands that have had their permissions updated"""
    entries: Optional[List["AuditLogEntry"]] = attrs.field(repr=False, default=MISSING)
    """list of audit log entries"""
    scheduled_events: Optional[List["models.ScheduledEvent"]] = attrs.field(repr=False, default=MISSING)
    """list of guild scheduled events found in the audit log"""
    integrations: Optional[List["GuildIntegration"]] = attrs.field(repr=False, default=MISSING)
    """list of partial integration objects"""
    threads: Optional[List["models.ThreadChannel"]] = attrs.field(repr=False, default=MISSING)
    """list of threads found in the audit log"""
    users: Optional[List["models.User"]] = attrs.field(repr=False, default=MISSING)
    """list of users found in the audit log"""
    webhooks: Optional[List["models.Webhook"]] = attrs.field(repr=False, default=MISSING)
    """list of webhooks found in the audit log"""

    @classmethod
    def _process_dict(cls, data: Dict[str, Any], client: "Client") -> Dict[str, Any]:
        if entries := data.get("audit_log_entries", None):
            data["entries"] = AuditLogEntry.from_list(entries, client)
        if scheduled_events := data.get("guild_scheduled_events", None):
            data["scheduled_events"] = models.ScheduledEvent.from_list(scheduled_events, client)
        if integrations := data.get("integrations", None):
            data["integrations"] = GuildIntegration.from_list(integrations, client)
        if threads := data.get("threads", None):
            data["threads"] = models.ThreadChannel.from_list(threads, client)
        if users := data.get("users", None):
            data["users"] = models.User.from_list(users, client)
        if webhooks := data.get("webhooks", None):
            data["webhooks"] = models.Webhook.from_list(webhooks, client)

        return data


class AuditLogHistory(AsyncIterator):
    """
    An async iterator for searching through a audit log's entry history.

    Attributes:
        guild (:class:`Guild`): The guild to search through.
        user_id (:class:`Snowflake_Type`): The user ID to search for.
        action_type (:class:`AuditLogEventType`): The action type to search for.
        before: get messages before this message ID
        after: get messages after this message ID
        limit: The maximum number of entries to return (set to 0 for no limit)

    """

    def __init__(
        self,
        guild: "Guild",
        user_id: Snowflake_Type = None,
        action_type: "AuditLogEventType" = None,
        before: Snowflake_Type = None,
        after: Snowflake_Type = None,
        limit: int = 50,
    ) -> None:
        self.guild: "Guild" = guild
        self.user_id: Snowflake_Type = user_id
        self.action_type: "AuditLogEventType" = action_type
        self.before: Snowflake_Type = before
        self.after: Snowflake_Type = after
        super().__init__(limit)

    async def fetch(self) -> List["AuditLog"]:
        """
        Retrieves the audit log entries from discord API.

        Returns:
            The list of audit log entries.

        """
        if self.after:
            if not self.last:
                self.last = namedtuple("temp", "id")
                self.last.id = self.after
            log = await self.guild.fetch_audit_log(limit=self.get_limit, after=self.last.id)
        else:
            if self.before and not self.last:
                self.last = namedtuple("temp", "id")
                self.last.id = self.before

            log = await self.guild.fetch_audit_log(limit=self.get_limit, before=self.last.id)
        entries = log.entries or []

        return entries

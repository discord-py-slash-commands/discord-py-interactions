from datetime import datetime
from typing import TYPE_CHECKING, Any, Iterable, Set, Dict, List, Optional, Union
from warnings import warn

import attrs

from interactions.client.const import Absent, MISSING
from interactions.client.errors import HTTPException, TooManyChanges
from interactions.client.mixins.send import SendMixin
from interactions.client.utils.attr_converters import list_converter, optional
from interactions.client.utils.attr_converters import optional as optional_c
from interactions.client.utils.attr_converters import timestamp_converter
from interactions.client.utils.attr_utils import docs
from interactions.client.utils.serializer import to_image_data
from interactions.models.discord.activity import Activity
from interactions.models.discord.asset import Asset
from interactions.models.discord.color import Color
from interactions.models.discord.enums import Permissions, PremiumType, UserFlags, Status, MemberFlags
from interactions.models.discord.file import UPLOADABLE_TYPE
from interactions.models.discord.role import Role
from interactions.models.discord.snowflake import Snowflake_Type
from interactions.models.discord.snowflake import to_snowflake
from .base import DiscordObject

if TYPE_CHECKING:
    from aiohttp import FormData
    from interactions.models.discord.guild import Guild
    from interactions.client import Client
    from interactions.models.discord.timestamp import Timestamp
    from interactions.models.discord.channel import DM, TYPE_GUILD_CHANNEL
    from interactions.models.discord.voice_state import VoiceState

__all__ = ("BaseUser", "ClientUser", "Member", "User")


class _SendDMMixin(SendMixin):
    id: "Snowflake_Type"

    async def _send_http_request(
        self, message_payload: Union[dict, "FormData"], files: list["UPLOADABLE_TYPE"] | None = None
    ) -> dict:
        dm_id = await self._client.cache.fetch_dm_channel_id(self.id)
        return await self._client.http.create_message(message_payload, dm_id, files=files)


@attrs.define(eq=False, order=False, hash=False, kw_only=True)
class BaseUser(DiscordObject, _SendDMMixin):
    """Base class for User, essentially partial user discord model."""

    username: str = attrs.field(repr=True, metadata=docs("The user's username, not unique across the platform"))
    global_name: str | None = attrs.field(
        repr=True, metadata=docs("The user's chosen display name, platform-wide"), default=None
    )
    discriminator: str = attrs.field(
        repr=True, metadata=docs("The user's 4-digit discord-tag"), default="0"
    )  # will likely be removed in future api version
    avatar: "Asset" = attrs.field(repr=False, metadata=docs("The user's default avatar"))

    def __str__(self) -> str:
        return self.tag

    @classmethod
    def _process_dict(cls, data: Dict[str, Any], client: "Client") -> Dict[str, Any]:
        if not isinstance(data["avatar"], Asset):
            if data["avatar"]:
                data["avatar"] = Asset.from_path_hash(client, f"avatars/{data['id']}/{{}}", data["avatar"])
            elif data["discriminator"] == "0":
                data["avatar"] = Asset(client, f"{Asset.BASE}/embed/avatars/{(int(data['id']) >> 22) % 6}")
            else:
                data["avatar"] = Asset(client, f"{Asset.BASE}/embed/avatars/{int(data['discriminator']) % 5}")
        return data

    @property
    def tag(self) -> str:
        """Returns the user's Discord tag."""
        if self.discriminator == "0":
            return f"@{self.username}"
        return f"{self.username}#{self.discriminator}"

    @property
    def mention(self) -> str:
        """Returns a string that would mention the user."""
        return f"<@{self.id}>"

    @property
    def display_name(self) -> str:
        """The users display name, will return nickname if one is set, otherwise will return username."""
        return self.global_name or self.username

    @property
    def display_avatar(self) -> "Asset":
        """The users displayed avatar, will return `guild_avatar` if one is set, otherwise will return user avatar."""
        return self.avatar

    @property
    def avatar_url(self) -> str:
        """The users avatar url."""
        return self.display_avatar.url

    async def fetch_dm(self, *, force: bool = False) -> "DM":
        """
        Fetch the DM channel associated with this user.

        Args:
            force: Whether to force a fetch from the API

        """
        return await self._client.cache.fetch_dm_channel(self.id, force=force)

    def get_dm(self) -> Optional["DM"]:
        """Get the DM channel associated with this user."""
        return self._client.cache.get_dm_channel(self.id)

    @property
    def mutual_guilds(self) -> List["Guild"]:
        """
        Get a list of mutual guilds shared between this user and the client.

        !!! note
            This will only be accurate if the guild members are cached internally
        """
        return [
            guild for guild in self._client.guilds if self._client.cache.get_member(guild_id=guild.id, user_id=self.id)
        ]


@attrs.define(eq=False, order=False, hash=False, kw_only=True)
class User(BaseUser):
    bot: bool = attrs.field(repr=True, default=False, metadata=docs("Is this user a bot?"))
    system: bool = attrs.field(
        default=False,
        metadata=docs("whether the user is an Official Discord System user (part of the urgent message system)"),
    )
    public_flags: "UserFlags" = attrs.field(
        repr=True,
        default=0,
        converter=UserFlags,
        metadata=docs("The flags associated with this user"),
    )
    premium_type: "PremiumType" = attrs.field(
        repr=False,
        default=0,
        converter=PremiumType,
        metadata=docs("The type of nitro subscription on a user's account"),
    )

    banner: Optional["Asset"] = attrs.field(repr=False, default=None, metadata=docs("The user's banner"))
    avatar_decoration: Optional["Asset"] = attrs.field(
        repr=False, default=None, metadata=docs("The user's avatar decoration")
    )
    accent_color: Optional["Color"] = attrs.field(
        default=None,
        converter=optional_c(Color),
        metadata=docs("The user's banner color"),
    )
    activities: list[Activity] = attrs.field(
        factory=list,
        converter=list_converter(optional(Activity.from_dict)),
        metadata=docs("A list of activities the user is in"),
    )
    status: Absent[Status] = attrs.field(
        repr=False, default=MISSING, metadata=docs("The user's status"), converter=optional(Status)
    )

    _fetched: bool = attrs.field(repr=False, default=False, metadata=docs("Has the user been fetched?"))
    """Flag to indicate if a `fetch` api call has been made to get the full user object."""

    @classmethod
    def _process_dict(cls, data: Dict[str, Any], client: "Client") -> Dict[str, Any]:
        data = super()._process_dict(data, client)
        if any(field in data for field in ("banner", "accent_color", "avatar_decoration")):
            data["_fetched"] = True

        if "banner" in data:
            data["banner"] = Asset.from_path_hash(client, f"banners/{data['id']}/{{}}", data["banner"])

        if data.get("premium_type", None) is None:
            data["premium_type"] = 0

        if data.get("avatar_decoration", None):
            data["avatar_decoration"] = Asset.from_path_hash(
                client, "avatar-decoration-presets/{}", data["avatar_decoration"]
            )

        return data

    @property
    def member_instances(self) -> List["Member"]:
        """
        Returns the member object for all guilds both the bot and the user are in.

        !!! note
            This will only be accurate if the guild members are cached internally
        """
        member_objs = [
            self._client.cache.get_member(guild_id=guild.id, user_id=self.id) for guild in self._client.guilds
        ]
        return [member for member in member_objs if member]


@attrs.define(eq=False, order=False, hash=False, kw_only=True)
class ClientUser(User):
    verified: bool = attrs.field(repr=True, metadata={"docs": "Whether the email on this account has been verified"})
    mfa_enabled: bool = attrs.field(
        repr=False,
        default=False,
        metadata={"docs": "Whether the user has two factor enabled on their account"},
    )
    email: Optional[str] = attrs.field(
        repr=False, default=None, metadata={"docs": "the user's email"}
    )  # needs special permissions?
    locale: Optional[str] = attrs.field(
        repr=False, default=None, metadata={"docs": "the user's chosen language option"}
    )
    bio: Optional[str] = attrs.field(repr=False, default=None, metadata={"docs": ""})
    flags: "UserFlags" = attrs.field(
        repr=False,
        default=0,
        converter=UserFlags,
        metadata={"docs": "the flags on a user's account"},
    )

    _guild_ids: Set["Snowflake_Type"] = attrs.field(
        repr=False, factory=set, metadata={"docs": "All the guilds the user is in"}
    )

    def _add_guilds(self, guild_ids: Set["Snowflake_Type"]) -> None:
        """
        Add the guilds that the user is in to the internal reference.

        Args:
            guild_ids: The guild ids to add

        """
        self._guild_ids |= guild_ids

    @property
    def guilds(self) -> List["Guild"]:
        """The guilds the user is in."""
        return list(filter(None, (self._client.cache.get_guild(guild_id) for guild_id in self._guild_ids)))

    @property
    def guild_count(self) -> int:
        """
        Returns the number of guilds the bot is in.

        This function is faster than using `len(client_user.guilds)` as it does not require using the cache.
        As such, this is preferred when you only need the count of guilds.
        """
        return len(self._guild_ids or ())

    async def edit(
        self,
        *,
        username: Absent[str] = MISSING,
        avatar: Absent[UPLOADABLE_TYPE] = MISSING,
        banner: Absent[UPLOADABLE_TYPE] = MISSING,
    ) -> None:
        """
        Edit the client's user.

        You can change the username, avatar, and banner, or any combination of the three.
        `avatar` and `banner` may be set to `None` to remove your bot's avatar/banner

        ??? Hint "Example Usage:"
            ```python
            await self.user.edit(avatar="path_to_file")
            ```
            or
            ```python
            await self.user.edit(username="hello world")
            ```

        Args:
            username: The username you want to use
            avatar: The avatar to use. Can be a image file, path, or `bytes` (see example)
            banner: The banner to use. Can be a image file, path, or `bytes`

        Raises:
            TooManyChanges: If you change the profile too many times

        """
        payload = {}
        if username:
            payload["username"] = username
        if avatar:
            payload["avatar"] = to_image_data(avatar)
        elif avatar is None:
            payload["avatar"] = None
        if banner:
            payload["banner"] = to_image_data(banner)
        elif banner is None:
            payload["banner"] = None

        try:
            resp = await self._client.http.modify_client_user(payload)
        except HTTPException:
            raise TooManyChanges(
                "You have changed your profile too frequently, you need to wait a while before trying again."
            ) from None
        if resp:
            self._client.cache.place_user_data(resp)


@attrs.define(eq=False, order=False, hash=False, kw_only=True)
class Member(DiscordObject, _SendDMMixin):
    bot: bool = attrs.field(repr=True, default=False, metadata=docs("Is this user a bot?"))
    nick: Optional[str] = attrs.field(repr=True, default=None, metadata=docs("The user's nickname in this guild'"))
    deaf: bool = attrs.field(repr=False, default=False, metadata=docs("Has this user been deafened in voice channels?"))
    mute: bool = attrs.field(repr=False, default=False, metadata=docs("Has this user been muted in voice channels?"))
    flags: MemberFlags = attrs.field(
        repr=False, default=0, converter=MemberFlags, metadata=docs("The flags associated with this guild member")
    )
    joined_at: "Timestamp" = attrs.field(
        repr=False,
        default=MISSING,
        converter=optional(timestamp_converter),
        metadata=docs("When the user joined this guild"),
    )
    premium_since: Optional["Timestamp"] = attrs.field(
        default=None,
        converter=optional_c(timestamp_converter),
        metadata=docs("When the user started boosting the guild"),
    )
    pending: Optional[bool] = attrs.field(
        repr=False,
        default=None,
        metadata=docs("Whether the user has **not** passed guild's membership screening requirements"),
    )
    guild_avatar: "Asset" = attrs.field(repr=False, default=None, metadata=docs("The user's guild avatar"))
    communication_disabled_until: Optional["Timestamp"] = attrs.field(
        default=None,
        converter=optional_c(timestamp_converter),
        metadata=docs("When a member's timeout will expire, `None` or a time in the past if the user is not timed out"),
    )

    _guild_id: "Snowflake_Type" = attrs.field(repr=True, metadata=docs("The ID of the guild"))
    _role_ids: List["Snowflake_Type"] = attrs.field(
        repr=False,
        factory=list,
        converter=list_converter(to_snowflake),
        metadata=docs("The roles IDs this user has"),
    )

    _user_ref: frozenset = MISSING
    """A lookup reference to the user object"""

    @classmethod
    def _process_dict(cls, data: Dict[str, Any], client: "Client") -> Dict[str, Any]:
        if "user" in data:
            user_data = data.pop("user")
            client.cache.place_user_data(user_data)
            data["id"] = user_data["id"]
            data["bot"] = user_data.get("bot", False)
        elif "member" in data:
            member_data = data.pop("member")
            client.cache.place_user_data(data)
            member_data["id"] = data["id"]
            member_data["bot"] = data.get("bot", False)
            if "guild_id" not in member_data:
                member_data["guild_id"] = data.get("guild_id")
            data = member_data
        if data.get("avatar"):
            try:
                data["guild_avatar"] = Asset.from_path_hash(
                    client,
                    f"guilds/{data['guild_id']}/users/{data['id']}/avatars/{{}}",
                    data.pop("avatar", None),
                )
            except Exception as e:
                client.logger.warning(
                    f"[DEBUG NEEDED - REPORT THIS] Incomplete dictionary has been passed to member object: {e}"
                )
                raise

        data["role_ids"] = data.pop("roles", [])

        return data

    def update_from_dict(self, data) -> None:
        if "guild_id" not in data:
            data["guild_id"] = self._guild_id
        data["_role_ids"] = data.pop("roles", [])
        return super().update_from_dict(data)

    @property
    def user(self) -> "User":
        """Returns this member's user object."""
        return self._client.cache.get_user(self.id)

    def __str__(self) -> str:
        return self.user.tag

    def __getattr__(self, name: str) -> Any:
        # this allows for transparent access to user attributes
        if not hasattr(self.__class__._user_ref, "__iter__"):
            self.__class__._user_ref = frozenset(dir(User))

        if name in self.__class__._user_ref:
            return getattr(self.user, name)
        raise AttributeError(f"Neither `User` or `Member` have attribute {name}")

    @property
    def nickname(self) -> str:
        """Alias for nick."""
        return self.nick

    @nickname.setter
    def nickname(self, nickname: str) -> None:
        """Sets the member's nickname."""
        self.nick = nickname

    @property
    def guild(self) -> "Guild":
        """The guild object this member is from."""
        return self._client.cache.get_guild(self._guild_id)

    @property
    def roles(self) -> List["Role"]:
        """The roles this member has."""
        return [r for r in self.guild.roles if r.id in self._role_ids]

    @property
    def top_role(self) -> "Role":
        """The member's top most role."""
        return max(self.roles, key=lambda x: x.position) if self.roles else self.guild.default_role

    @property
    def display_name(self) -> str:
        """The users display name, will return nickname if one is set, otherwise will return username."""
        return self.nickname or self.user.global_name or self.user.username

    @property
    def display_avatar(self) -> "Asset":
        """The users displayed avatar, will return `guild_avatar` if one is set, otherwise will return user avatar."""
        return self.guild_avatar or self.user.avatar

    @property
    def avatar_url(self) -> str:
        """The users avatar url."""
        return self.display_avatar.url

    @property
    def premium(self) -> bool:
        """Is this member a server booster?"""
        return self.premium_since is not None

    @property
    def guild_permissions(self) -> Permissions:
        """
        Returns the permissions this member has in the guild.

        Returns:
            Permission data

        """
        guild = self.guild
        if guild.is_owner(self):
            return Permissions.ALL

        permissions = guild.default_role.permissions  # get @everyone role

        for role in self.roles:
            permissions |= role.permissions

        if Permissions.ADMINISTRATOR in permissions:
            return Permissions.ALL

        return permissions

    @property
    def voice(self) -> Optional["VoiceState"]:
        """Returns the voice state of this user if any."""
        return self._client.cache.get_voice_state(self.id)

    def has_permission(self, *permissions: Permissions) -> bool:
        """
        Checks if the member has all the given permission(s).

        ??? Hint "Example Usage:"
            Two different styles can be used to call this method.

            ```python
            member.has_permission(Permissions.KICK_MEMBERS, Permissions.BAN_MEMBERS)
            ```
            or
            ```python
            member.has_permission(Permissions.KICK_MEMBERS | Permissions.BAN_MEMBERS)
            ```

            If `member` has both permissions, `True` gets returned.

        Args:
            *permissions: The permission(s) to check whether the user has it.

        """
        # Get the user's permissions
        guild_permissions = self.guild_permissions

        return all(permission in guild_permissions for permission in permissions)

    def channel_permissions(self, channel: "TYPE_GUILD_CHANNEL") -> Permissions:
        """
        Returns the permissions this member has in a channel.

        Args:
            channel: The channel in question

        Returns:
            Permissions data

        ??? note
            This method is used in `Channel.permissions_for`

        """
        permissions = self.guild_permissions

        if Permissions.ADMINISTRATOR in permissions:
            return Permissions.ALL

        overwrites = tuple(
            filter(
                lambda overwrite: overwrite.id in (self._guild_id, self.id, *self._role_ids),
                channel.permission_overwrites,
            )
        )

        for everyone_overwrite in filter(lambda overwrite: overwrite.id == self._guild_id, overwrites):
            permissions &= ~everyone_overwrite.deny
            permissions |= everyone_overwrite.allow

        for role_overwrite in filter(lambda overwrite: overwrite.id not in (self._guild_id, self.id), overwrites):
            permissions &= ~role_overwrite.deny
            permissions |= role_overwrite.allow

        for member_overwrite in filter(lambda overwrite: overwrite.id == self.id, overwrites):
            permissions &= ~member_overwrite.deny
            permissions |= member_overwrite.allow

        return permissions

    async def edit_nickname(self, new_nickname: Absent[str] = MISSING, reason: Absent[str] = MISSING) -> None:
        """
        Change the user's nickname.

        Args:
            new_nickname: The new nickname to apply
            reason: The reason for this change

        !!! note
            Leave `new_nickname` empty to clean user's nickname

        """
        if self.id == self._client.user.id:
            await self._client.http.modify_current_member(self._guild_id, nickname=new_nickname, reason=reason)
        else:
            await self._client.http.modify_guild_member(self._guild_id, self.id, nickname=new_nickname, reason=reason)

    async def add_role(self, role: Union[Snowflake_Type, Role], reason: Absent[str] = MISSING) -> None:
        """
        Add a role to this member.

        Args:
            role: The role to add
            reason: The reason for adding this role

        """
        role = to_snowflake(role)
        await self._client.http.add_guild_member_role(self._guild_id, self.id, role, reason=reason)
        self._role_ids.append(role)

    async def add_roles(self, roles: Iterable[Union[Snowflake_Type, Role]], reason: Absent[str] = MISSING) -> None:
        """
        Atomically add multiple roles to this member.

        Args:
            roles: The roles to add
            reason: The reason for adding the roles

        """
        new_roles = set(self._role_ids) | {to_snowflake(r) for r in roles}
        await self.edit(roles=new_roles, reason=reason)

    async def remove_role(self, role: Union[Snowflake_Type, Role], reason: Absent[str] = MISSING) -> None:
        """
        Remove a role from this user.

        Args:
            role: The role to remove
            reason: The reason for this removal

        """
        role = to_snowflake(role)
        await self._client.http.remove_guild_member_role(self._guild_id, self.id, role, reason=reason)
        try:
            self._role_ids.remove(role)
        except ValueError:
            pass

    async def remove_roles(self, roles: Iterable[Union[Snowflake_Type, Role]], reason: Absent[str] = MISSING) -> None:
        """
        Atomically remove multiple roles from this member.

        Args:
            roles: The roles to remove
            reason: The reason for removing the roles

        """
        new_roles = set(self._role_ids) - {to_snowflake(r) for r in roles}
        await self.edit(roles=new_roles, reason=reason)

    def has_role(self, *roles: Union[Snowflake_Type, Role]) -> bool:
        """
        Checks if the user has the given role(s).

        Args:
            *roles: The role(s) to check whether the user has it.

        """
        return all(to_snowflake(role) in self._role_ids for role in roles)

    def has_any_role(self, roles: List[Union[Snowflake_Type, Role]]) -> bool:
        """
        Checks if the user has any of the given roles.

        Args:
            *roles: The Role(s) or role id(s) to check for

        """
        return any((self.has_role(to_snowflake(role)) for role in roles))

    async def timeout(
        self,
        communication_disabled_until: Union["Timestamp", datetime, int, float, str, None],
        reason: Absent[str] = MISSING,
    ) -> dict:
        """
        Disable a members communication for a given time.

        Args:
            communication_disabled_until: The time until the user can communicate again
            reason: The reason for this timeout

        """
        if isinstance(communication_disabled_until, (datetime, int, float, str)):
            communication_disabled_until = timestamp_converter(communication_disabled_until)

        self.communication_disabled_until = communication_disabled_until

        return await self._client.http.modify_guild_member(
            self._guild_id,
            self.id,
            communication_disabled_until=communication_disabled_until,
            reason=reason,
        )

    async def move(self, channel_id: "Snowflake_Type") -> None:
        """
        Moves the member to a different voice channel.

        Args:
            channel_id: The voice channel to move the member to

        """
        await self._client.http.modify_guild_member(self._guild_id, self.id, channel_id=channel_id)

    async def disconnect(self) -> None:
        """Disconnects the member from the voice channel."""
        await self._client.http.modify_guild_member(self._guild_id, self.id, channel_id=None)

    async def edit(
        self,
        *,
        nickname: Absent[str] = MISSING,
        roles: Absent[Iterable["Snowflake_Type"]] = MISSING,
        mute: Absent[bool] = MISSING,
        deaf: Absent[bool] = MISSING,
        channel_id: Absent["Snowflake_Type"] = MISSING,
        communication_disabled_until: Absent[Union["Timestamp", None]] = MISSING,
        flags: Absent[int] = MISSING,
        reason: Absent[str] = MISSING,
    ) -> None:
        """
        Modify attrbutes of this guild member.

        Args:
            nickname: Value to set users nickname to
            roles: Array of role ids the member is assigned
            mute: Whether the user is muted in voice channels. Will throw a 400 if the user is not in a voice channel
            deaf: Whether the user is deafened in voice channels
            channel_id: id of channel to move user to (if they are connected to voice)
            communication_disabled_until: 	when the user's timeout will expire and the user will be able to communicate in the guild again
            flags: Represents the guild member flags
            reason: An optional reason for the audit log

        """
        await self._client.http.modify_guild_member(
            self._guild_id,
            self.id,
            nickname=nickname,
            roles=roles,
            mute=mute,
            deaf=deaf,
            channel_id=channel_id,
            communication_disabled_until=communication_disabled_until,
            flags=flags,
            reason=reason,
        )

    async def kick(self, reason: Absent[str] = MISSING) -> None:
        """
        Remove a member from the guild.

        Args:
            reason: The reason for this removal

        """
        await self._client.http.remove_guild_member(self._guild_id, self.id, reason=reason)

    async def ban(
        self,
        delete_message_days: Absent[int] = MISSING,
        delete_message_seconds: int = 0,
        reason: Absent[str] = MISSING,
    ) -> None:
        """
        Ban a member from the guild.

        Args:
            delete_message_days: (deprecated) The number of days of messages to delete
            delete_message_seconds: The number of seconds of messages to delete
            reason: The reason for this ban

        """
        if delete_message_days is not MISSING:
            warn(
                "delete_message_days  is deprecated and will be removed in a future update",
                DeprecationWarning,
                stacklevel=2,
            )
            delete_message_seconds = delete_message_days * 3600
        await self._client.http.create_guild_ban(self._guild_id, self.id, delete_message_seconds, reason=reason)

import copy
from typing import TYPE_CHECKING, Optional, Dict, Any

import attrs

from interactions.client.const import MISSING
from interactions.client.mixins.serialization import DictSerializationMixin
from interactions.client.utils.attr_converters import optional as optional_c
from interactions.client.utils.attr_converters import timestamp_converter
from interactions.models.discord.snowflake import to_snowflake
from interactions.models.discord.timestamp import Timestamp
from .base import ClientObject

if TYPE_CHECKING:
    from interactions.client import Client
    from interactions.models import Guild, TYPE_VOICE_CHANNEL
    from interactions.models.discord.user import Member
    from interactions.models.discord.snowflake import Snowflake_Type

__all__ = ("VoiceRegion", "VoiceState")


@attrs.define(eq=False, order=False, hash=False, kw_only=True)
class VoiceState(ClientObject):
    user_id: "Snowflake_Type" = attrs.field(repr=False, default=MISSING, converter=to_snowflake)
    """the user id this voice state is for"""
    session_id: str = attrs.field(repr=False, default=MISSING)
    """the session id for this voice state"""
    deaf: bool = attrs.field(repr=False, default=False)
    """whether this user is deafened by the server"""
    mute: bool = attrs.field(repr=False, default=False)
    """whether this user is muted by the server"""
    self_deaf: bool = attrs.field(repr=False, default=False)
    """whether this user is locally deafened"""
    self_mute: bool = attrs.field(repr=False, default=False)
    """whether this user is locally muted"""
    self_stream: Optional[bool] = attrs.field(repr=False, default=False)
    """whether this user is streaming using "Go Live\""""
    self_video: bool = attrs.field(repr=False, default=False)
    """whether this user's camera is enabled"""
    suppress: bool = attrs.field(repr=False, default=False)
    """whether this user is muted by the current user"""
    request_to_speak_timestamp: Optional[Timestamp] = attrs.field(
        repr=False, default=None, converter=optional_c(timestamp_converter)
    )
    """the time at which the user requested to speak"""

    # internal for props
    _guild_id: Optional["Snowflake_Type"] = attrs.field(repr=False, default=None, converter=to_snowflake)
    _channel_id: "Snowflake_Type" = attrs.field(repr=False, converter=to_snowflake)
    _member_id: Optional["Snowflake_Type"] = attrs.field(repr=False, default=None, converter=to_snowflake)

    @property
    def guild(self) -> "Guild":
        """The guild this voice state is for."""
        return self._client.cache.get_guild(self._guild_id) if self._guild_id else None

    @property
    def channel(self) -> "TYPE_VOICE_CHANNEL":
        """The channel the user is connected to."""
        channel: "TYPE_VOICE_CHANNEL" = self._client.cache.get_channel(self._channel_id)

        if channel and self._member_id not in channel._voice_member_ids:
            # the list of voice members need to be deepcopied, otherwise the cached obj will be updated
            # noinspection PyProtectedMember
            voice_member_ids = copy.deepcopy(channel._voice_member_ids)

            # create a copy of the obj
            channel = copy.copy(channel)
            channel._voice_member_ids = voice_member_ids

            # add the member to that list
            # noinspection PyProtectedMember
            channel._voice_member_ids.append(self._member_id)

        return channel

    @property
    def member(self) -> "Member":
        """The member this voice state is for."""
        return self._client.cache.get_member(self._guild_id, self._member_id) if self._guild_id else None

    @classmethod
    def _process_dict(cls, data: Dict[str, Any], client: "Client") -> Dict[str, Any]:
        if member := data.pop("member", None):
            member = client.cache.place_member_data(data["guild_id"], member)
            data["member_id"] = member.id
        else:
            data["member_id"] = data["user_id"]
        return data


@attrs.define(eq=False, order=False, hash=False, kw_only=True)
class VoiceRegion(DictSerializationMixin):
    """A voice region."""

    id: str = attrs.field(repr=True)
    """unique ID for the region"""
    name: str = attrs.field(repr=True)
    """name of the region"""
    vip: bool = attrs.field(default=False, repr=True)
    """whether this is a VIP-only voice region"""
    optimal: bool = attrs.field(repr=False, default=False)
    """true for a single server that is closest to the current user's client"""
    deprecated: bool = attrs.field(repr=False, default=False)
    """whether this is a deprecated voice region (avoid switching to these)"""
    custom: bool = attrs.field(repr=False, default=False)
    """whether this is a custom voice region (used for events/etc)"""

    def __str__(self) -> str:
        return self.name

from typing import Optional, List

import attrs

from interactions.client.mixins.serialization import DictSerializationMixin
from interactions.client.utils.attr_converters import timestamp_converter, optional
from interactions.client.utils.serializer import dict_filter_none
from interactions.models.discord.emoji import PartialEmoji
from interactions.models.discord.enums import ActivityType, ActivityFlag
from interactions.models.discord.snowflake import Snowflake_Type
from interactions.models.discord.timestamp import Timestamp

__all__ = (
    "Activity",
    "ActivityAssets",
    "ActivityParty",
    "ActivitySecrets",
    "ActivityTimestamps",
)


@attrs.define(eq=False, order=False, hash=False, kw_only=True)
class ActivityTimestamps(DictSerializationMixin):
    start: Optional[Timestamp] = attrs.field(repr=False, default=None, converter=optional(timestamp_converter))
    """The start time of the activity. Shows "elapsed" timer on discord client."""
    end: Optional[Timestamp] = attrs.field(repr=False, default=None, converter=optional(timestamp_converter))
    """The end time of the activity. Shows "remaining" timer on discord client."""


@attrs.define(eq=False, order=False, hash=False, kw_only=True)
class ActivityParty(DictSerializationMixin):
    id: Optional[str] = attrs.field(repr=False, default=None)
    """A unique identifier for this party"""
    size: Optional[List[int]] = attrs.field(repr=False, default=None)
    """Info about the size of the party"""


@attrs.define(eq=False, order=False, hash=False, kw_only=True)
class ActivityAssets(DictSerializationMixin):
    large_image: Optional[str] = attrs.field(repr=False, default=None)
    """The large image for this activity. Uses discord's asset image url format."""
    large_text: Optional[str] = attrs.field(repr=False, default=None)
    """Hover text for the large image"""
    small_image: Optional[str] = attrs.field(repr=False, default=None)
    """The large image for this activity. Uses discord's asset image url format."""
    small_text: Optional[str] = attrs.field(repr=False, default=None)
    """Hover text for the small image"""


@attrs.define(eq=False, order=False, hash=False, kw_only=True)
class ActivitySecrets(DictSerializationMixin):
    join: Optional[str] = attrs.field(repr=False, default=None)
    """The secret for joining a party"""
    spectate: Optional[str] = attrs.field(repr=False, default=None)
    """The secret for spectating a party"""
    match: Optional[str] = attrs.field(repr=False, default=None)
    """The secret for a specific instanced match"""


@attrs.define(eq=False, order=False, hash=False, kw_only=False)
class Activity(DictSerializationMixin):
    """Represents a discord activity object use for rich presence in discord."""

    name: str = attrs.field(repr=True)
    """The activity's name"""
    type: ActivityType = attrs.field(repr=True, default=ActivityType.GAME)
    """The type of activity"""
    url: Optional[str] = attrs.field(repr=True, default=None)
    """Stream url, is validated when type is 1"""
    created_at: Optional[Timestamp] = attrs.field(repr=True, default=None, converter=optional(timestamp_converter))
    """When the activity was added to the user's session"""
    timestamps: Optional[ActivityTimestamps] = attrs.field(
        repr=False, default=None, converter=optional(ActivityTimestamps.from_dict)
    )
    """Start and/or end of the game"""
    application_id: "Snowflake_Type" = attrs.field(repr=False, default=None)
    """Application id for the game"""
    details: Optional[str] = attrs.field(repr=False, default=None)
    """What the player is currently doing"""
    state: Optional[str] = attrs.field(repr=False, default=None)
    """The user's current party status, or text used for a custom status if type is set as CUSTOM"""
    emoji: Optional[PartialEmoji] = attrs.field(repr=False, default=None, converter=optional(PartialEmoji.from_dict))
    """The emoji used for a custom status"""
    party: Optional[ActivityParty] = attrs.field(repr=False, default=None, converter=optional(ActivityParty.from_dict))
    """Information for the current party of the player"""
    assets: Optional[ActivityAssets] = attrs.field(
        repr=False, default=None, converter=optional(ActivityAssets.from_dict)
    )
    """Assets to display on the player's profile"""
    secrets: Optional[ActivitySecrets] = attrs.field(
        repr=False, default=None, converter=optional(ActivitySecrets.from_dict)
    )
    """Secrets for Rich Presence joining and spectating"""
    instance: Optional[bool] = attrs.field(repr=False, default=False)
    """Whether or not the activity is an instanced game session"""
    flags: Optional[ActivityFlag] = attrs.field(repr=False, default=None, converter=optional(ActivityFlag))
    """Activity flags bitwise OR together, describes what the payload includes"""
    buttons: List[str] = attrs.field(repr=False, factory=list)
    """The custom buttons shown in the Rich Presence (max 2)"""

    @classmethod
    def create(
        cls, name: str, type: ActivityType = ActivityType.GAME, url: Optional[str] = None, state: Optional[str] = None
    ) -> "Activity":
        """
        Creates an activity object for the bot.

        Args:
            name: The new activity's name
            type: Type of activity to create
            url: Stream link for the activity
            state: Current party status, or text used for a custom status if type is set as CUSTOM

        Returns:
            The new activity object

        """
        return cls(name=name, type=type, url=url, state=state)

    def to_dict(self) -> dict:
        return dict_filter_none({"name": self.name, "type": self.type, "state": self.state, "url": self.url})

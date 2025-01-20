from typing import Any, Dict, List, Optional, Union

import attrs

from interactions.client.const import MISSING, Absent
from interactions.client.mixins.serialization import DictSerializationMixin
from interactions.client.utils.attr_converters import optional
from interactions.models.discord.base import ClientObject
from interactions.models.discord.emoji import PartialEmoji, process_emoji
from interactions.models.discord.enums import OnboardingMode, OnboardingPromptType
from interactions.models.discord.snowflake import (
    Snowflake,
    Snowflake_Type,
    SnowflakeObject,
    to_snowflake,
    to_snowflake_list,
)

__all__ = ("Onboarding", "OnboardingPrompt", "OnboardingPromptOption")


@attrs.define(eq=False, order=False, hash=False, kw_only=True)
class OnboardingPromptOption(SnowflakeObject, DictSerializationMixin):
    channel_ids: List["Snowflake"] = attrs.field(repr=False, converter=to_snowflake_list)
    """IDs for channels a member is added to when the option is selected"""
    role_ids: List["Snowflake"] = attrs.field(repr=False, converter=to_snowflake_list)
    """IDs for roles assigned to a member when the option is selected"""
    title: str = attrs.field(repr=False)
    """Title of the option"""
    description: Optional[str] = attrs.field(repr=False, default=None)
    """Description of the option"""
    emoji: Optional[PartialEmoji] = attrs.field(repr=False, default=None, converter=optional(PartialEmoji.from_dict))
    """Emoji of the option"""

    # this method is here because Discord needs the id field to be present in the payload
    @classmethod
    def create(
        cls,
        title: str,
        *,
        channel_ids: Optional[List[Snowflake_Type]] = None,
        role_ids: Optional[List[Snowflake_Type]] = None,
        description: Optional[str] = None,
        emoji: Optional[Union[PartialEmoji, dict, str]] = None,
    ) -> "OnboardingPromptOption":
        """
        Creates a new Onboarding prompt option object.

        Args:
            title: Title of the option
            channel_ids: Channel IDs that this option represents
            role_ids: Role IDs that this option represents
            description: Description of the option
            emoji: Emoji of the option

        Returns:
            The newly created OnboardingPromptOption object

        """
        return cls(
            id=0,
            channel_ids=channel_ids or [],
            role_ids=role_ids or [],
            title=title,
            description=description,
            emoji=process_emoji(emoji),
        )

    def as_dict(self) -> Dict[str, Any]:
        data = {
            "id": self.id,
            "channel_ids": self.channel_ids,
            "role_ids": self.role_ids,
            "title": self.title,
            "description": self.description,
        }
        # use the separate fields when sending to Discord
        if self.emoji is not None:
            data["emoji_id"] = self.emoji.id
            data["emoji_name"] = self.emoji.name
            data["emoji_animated"] = self.emoji.animated
        return data


@attrs.define(eq=False, order=False, hash=False, kw_only=False)
class OnboardingPrompt(SnowflakeObject, DictSerializationMixin):
    type: OnboardingPromptType = attrs.field(repr=False, converter=OnboardingPromptType)
    """Type of the prompt"""
    options: List[OnboardingPromptOption] = attrs.field(repr=False, converter=OnboardingPromptOption.from_list)
    """Options available in the prompt"""
    title: str = attrs.field(repr=False)
    """Title of the prompt"""
    single_select: bool = attrs.field(repr=False)
    """Whether users are limited to selecting one option for the prompt"""
    required: bool = attrs.field(repr=False)
    """Whether users are required to complete this prompt"""
    in_onboarding: bool = attrs.field(repr=False)
    """Whether the prompt is present in the onboarding flow; otherwise it is only in the Channels & Roles tab"""

    @classmethod
    def create(
        cls,
        *,
        type: Union[OnboardingPromptType, int] = OnboardingPromptType.MULTIPLE_CHOICE,
        options: List[OnboardingPromptOption],
        title: str,
        single_select: bool = False,
        required: bool = False,
        in_onboarding: bool = True,
    ) -> "OnboardingPrompt":
        """
        Creates a new Onboarding prompt object.

        Args:
            type: Type of the prompt
            options: Options available in the prompt
            title: Title of the prompt
            single_select: Whether users are limited to selecting one option for the prompt
            required: Whether users are required to complete this prompt
            in_onboarding: Whether the prompt is present in the onboarding flow; otherwise it is only in the Channels & Roles tab

        Returns:
            The newly created OnboardingPrompt object

        """
        return cls(
            id=0,
            type=type,
            options=options,
            title=title,
            single_select=single_select,
            required=required,
            in_onboarding=in_onboarding,
        )


@attrs.define(eq=False, order=False, hash=False, kw_only=False)
class Onboarding(ClientObject):
    """Represents the onboarding flow for a guild."""

    guild_id: Snowflake = attrs.field(repr=False, converter=to_snowflake)
    """ID of the guild this onboarding is part of"""
    prompts: list[OnboardingPrompt] = attrs.field(repr=False, converter=OnboardingPrompt.from_list)
    """Prompts shown during onboarding and in customize community"""
    default_channel_ids: list[Snowflake] = attrs.field(repr=False, converter=to_snowflake_list)
    """Channel IDs that members get opted into automatically"""
    enabled: bool = attrs.field(repr=False)
    """Whether onboarding is enabled in the guild"""
    mode: OnboardingMode = attrs.field(repr=False, converter=OnboardingMode)
    """Current mode of onboarding"""

    async def edit(
        self,
        *,
        prompts: Absent[List[OnboardingPrompt]] = MISSING,
        default_channel_ids: Absent[list[Snowflake_Type]] = MISSING,
        enabled: Absent[bool] = MISSING,
        mode: Absent[Union[OnboardingMode, int]] = MISSING,
        reason: Absent[str] = MISSING,
    ) -> None:
        """
        Edits this Onboarding flow.

        Args:
            prompts: Prompts shown during onboarding and in customize community
            default_channel_ids: Channel IDs that members get opted into automatically
            enabled: Whether onboarding is enabled in the guild
            mode: Current mode of onboarding
            reason: The reason for this change

        """
        payload = {
            "prompts": prompts,
            "default_channel_ids": default_channel_ids,
            "enabled": enabled,
            "mode": mode,
        }
        data = await self._client.http.modify_guild_onboarding(self.guild_id, payload, reason)
        self.update_from_dict(data)

from typing import TYPE_CHECKING, List, Optional, Union

import attrs

from interactions.client.const import MISSING, Absent
from interactions.client.utils.attr_converters import optional
from interactions.client.utils.serializer import dict_filter_none
from interactions.models.discord.snowflake import to_snowflake
from .base import DiscordObject
from interactions.models.discord.enums import StickerTypes, StickerFormatType

if TYPE_CHECKING:
    from interactions.models.discord.guild import Guild
    from interactions.models.discord.user import User
    from interactions.models.discord.snowflake import Snowflake_Type

__all__ = ("Sticker", "StickerItem", "StickerPack")


@attrs.define(eq=False, order=False, hash=False, kw_only=False)
class StickerItem(DiscordObject):
    name: str = attrs.field(repr=True)
    """Name of the sticker."""
    format_type: StickerFormatType = attrs.field(repr=True, converter=StickerFormatType)
    """Type of sticker image format."""


@attrs.define(eq=False, order=False, hash=False, kw_only=True)
class Sticker(StickerItem):
    """Represents a sticker that can be sent in messages."""

    pack_id: Optional["Snowflake_Type"] = attrs.field(repr=False, default=None, converter=optional(to_snowflake))
    """For standard stickers, id of the pack the sticker is from."""
    description: Optional[str] = attrs.field(repr=False, default=None)
    """Description of the sticker."""
    tags: str = attrs.field(repr=False)
    """autocomplete/suggestion tags for the sticker (max 200 characters)"""
    type: Union[StickerTypes, int] = attrs.field(repr=False, converter=StickerTypes)
    """Type of sticker."""
    available: Optional[bool] = attrs.field(repr=False, default=True)
    """Whether this guild sticker can be used, may be false due to loss of Server Boosts."""
    sort_value: Optional[int] = attrs.field(repr=False, default=None)
    """The standard sticker's sort order within its pack."""

    _user_id: Optional["Snowflake_Type"] = attrs.field(repr=False, default=None, converter=optional(to_snowflake))
    _guild_id: Optional["Snowflake_Type"] = attrs.field(repr=False, default=None, converter=optional(to_snowflake))

    async def fetch_creator(self, *, force: bool = False) -> "User":
        """
        Fetch the user who created this emoji.

        Args:
            force: Whether to force a fetch from the API

        Returns:
            User object

        """
        return await self._client.cache.fetch_user(self._user_id, force=force)

    def get_creator(self) -> "User":
        """
        Get the user who created this emoji.

        Returns:
            User object

        """
        return self._client.cache.get_user(self._user_id)

    async def fetch_guild(self, *, force: bool = False) -> "Guild":
        """
        Fetch the guild associated with this emoji.

        Args:
            force: Whether to force a fetch from the API

        Returns:
            Guild object

        """
        return await self._client.cache.fetch_guild(self._guild_id, force=force)

    def get_guild(self) -> "Guild":
        """
        Get the guild associated with this emoji.

        Returns:
            Guild object

        """
        return self._client.cache.get_guild(self._guild_id)

    async def edit(
        self,
        *,
        name: Absent[Optional[str]] = MISSING,
        description: Absent[Optional[str]] = MISSING,
        tags: Absent[Optional[str]] = MISSING,
        reason: Absent[Optional[str]] = MISSING,
    ) -> "Sticker":
        """
        Edit a sticker.

        Args:
            name: New name of the sticker
            description: New description of the sticker
            tags: New tags of the sticker
            reason: Reason for the edit

        Returns:
            The updated sticker instance

        """
        if not self._guild_id:
            raise ValueError("You can only edit guild stickers.")

        payload = dict_filter_none({"name": name, "description": description, "tags": tags})
        sticker_data = await self._client.http.modify_guild_sticker(payload, self._guild_id, self.id, reason)
        return self.update_from_dict(sticker_data)

    async def delete(self, reason: Optional[str] = MISSING) -> None:
        """
        Delete a sticker.

        Args:
            reason: Reason for the deletion

        Raises:
            ValueError: If you attempt to delete a non-guild sticker

        """
        if not self._guild_id:
            raise ValueError("You can only delete guild stickers.")

        await self._client.http.delete_guild_sticker(self._guild_id, self.id, reason)

    @property
    def url(self) -> str:
        """CDN url for the sticker."""
        return f"https://media.discordapp.net/stickers/{self.id}.webp"


@attrs.define(eq=False, order=False, hash=False, kw_only=True)
class StickerPack(DiscordObject):
    """Represents a pack of standard stickers."""

    stickers: List["Sticker"] = attrs.field(repr=False, factory=list)
    """The stickers in the pack."""
    name: str = attrs.field(repr=True)
    """Name of the sticker pack."""
    sku_id: "Snowflake_Type" = attrs.field(repr=True)
    """id of the pack's SKU."""
    cover_sticker_id: Optional["Snowflake_Type"] = attrs.field(repr=False, default=None)
    """id of a sticker in the pack which is shown as the pack's icon."""
    description: str = attrs.field(repr=False)
    """Description of the sticker pack."""
    banner_asset_id: "Snowflake_Type" = attrs.field(repr=False)  # TODO CDN Asset
    """id of the sticker pack's banner image."""

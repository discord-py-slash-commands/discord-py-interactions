from typing import TYPE_CHECKING, Any, Iterable, Optional, Union

import interactions.models as models
import interactions.models.discord
from interactions.models.discord.enums import MessageFlags

if TYPE_CHECKING:
    from interactions.client import Client
    from interactions.models.discord.file import UPLOADABLE_TYPE
    from interactions.models.discord.components import BaseComponent
    from interactions.models.discord.embed import Embed
    from interactions.models.discord.message import AllowedMentions, Message, MessageReference
    from interactions.models.discord.poll import Poll
    from interactions.models.discord.sticker import Sticker
    from interactions.models.discord.snowflake import Snowflake_Type


__all__ = ("SendMixin",)


class SendMixin:
    client: "Client"

    async def _send_http_request(self, message_payload: dict, files: Iterable["UPLOADABLE_TYPE"] | None = None) -> dict:
        raise NotImplementedError

    async def send(
        self,
        content: Optional[str] = None,
        *,
        embeds: Optional[Union[Iterable[Union["Embed", dict]], Union["Embed", dict]]] = None,
        embed: Optional[Union["Embed", dict]] = None,
        components: Optional[
            Union[
                Iterable[Iterable[Union["BaseComponent", dict]]],
                Iterable[Union["BaseComponent", dict]],
                "BaseComponent",
                dict,
            ]
        ] = None,
        stickers: Optional[Union[Iterable[Union["Sticker", "Snowflake_Type"]], "Sticker", "Snowflake_Type"]] = None,
        allowed_mentions: Optional[Union["AllowedMentions", dict]] = None,
        reply_to: Optional[Union["MessageReference", "Message", dict, "Snowflake_Type"]] = None,
        files: Optional[Union["UPLOADABLE_TYPE", Iterable["UPLOADABLE_TYPE"]]] = None,
        file: Optional["UPLOADABLE_TYPE"] = None,
        tts: bool = False,
        suppress_embeds: bool = False,
        silent: bool = False,
        flags: Optional[Union[int, "MessageFlags"]] = None,
        delete_after: Optional[float] = None,
        nonce: Optional[str | int] = None,
        enforce_nonce: bool = False,
        poll: "Optional[Poll | dict]" = None,
        **kwargs: Any,
    ) -> "Message":
        """
        Send a message.

        Args:
            content: Message text content.
            embeds: Embedded rich content (up to 6000 characters).
            embed: Embedded rich content (up to 6000 characters).
            components: The components to include with the message.
            stickers: IDs of up to 3 stickers in the server to send in the message.
            allowed_mentions: Allowed mentions for the message.
            reply_to: Message to reference, must be from the same channel.
            files: Files to send, the path, bytes or File() instance, defaults to None. You may have up to 10 files.
            file: Files to send, the path, bytes or File() instance, defaults to None. You may have up to 10 files.
            tts: Should this message use Text To Speech.
            suppress_embeds: Should embeds be suppressed on this send
            silent: Should this message be sent without triggering a notification.
            flags: Message flags to apply.
            delete_after: Delete message after this many seconds.
            nonce: Used to verify a message was sent. Can be up to 25 characters.
            enforce_nonce: If enabled and nonce is present, it will be checked for uniqueness in the past few minutes. \
                If another message was created by the same author with the same nonce, that message will be returned \
                and no new message will be created.
            poll: A poll.

        Returns:
            New message object that was sent.

        """
        if not flags:
            flags = MessageFlags(0)
        if suppress_embeds:
            if isinstance(flags, int):
                flags = MessageFlags(flags)
            flags = flags | MessageFlags.SUPPRESS_EMBEDS
        if silent:
            if isinstance(flags, int):
                flags = MessageFlags(flags)
            flags = flags | MessageFlags.SILENT

        if (
            files
            and (
                isinstance(files, Iterable)
                and any(isinstance(file, interactions.models.discord.message.Attachment) for file in files)
            )
        ) or isinstance(files, interactions.models.discord.message.Attachment):
            raise ValueError(
                "Attachments are not files. Attachments only contain metadata about the file, not the file itself - to send an attachment, you need to download it first. Check Attachment.url"
            )

        if enforce_nonce and not nonce:
            raise ValueError("You must provide a nonce to use enforce_nonce.")

        message_payload = models.discord.message.process_message_payload(
            content=content,
            embeds=embeds or embed,
            components=components,
            stickers=stickers,
            allowed_mentions=allowed_mentions,
            reply_to=reply_to,
            tts=tts,
            flags=flags,
            nonce=nonce,
            enforce_nonce=enforce_nonce,
            poll=poll,
            **kwargs,
        )

        message_data = await self._send_http_request(message_payload, files=files or file)
        if message_data:
            message = self.client.cache.place_message_data(message_data)
            if delete_after:
                if kwargs.get("pass_self_into_delete"):  # hack to pass in interaction/hybrid context
                    await message.delete(delay=delete_after, context=self)
                else:
                    await message.delete(delay=delete_after)
            return message

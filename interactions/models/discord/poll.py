from typing import Optional, Union, Dict, Any
from typing_extensions import Self

import attrs

from interactions.client.const import MISSING, POLL_MAX_DURATION_HOURS, POLL_MAX_ANSWERS
from interactions.client.utils.attr_converters import (
    optional,
    timestamp_converter,
)
from interactions.client.mixins.serialization import DictSerializationMixin
from interactions.models.discord.emoji import PartialEmoji, process_emoji
from interactions.models.discord.enums import PollLayoutType
from interactions.models.discord.timestamp import Timestamp

__all__ = (
    "Poll",
    "PollAnswer",
    "PollAnswerCount",
    "PollMedia",
    "PollResults",
)


@attrs.define(eq=False, order=False, hash=False, kw_only=True)
class PollMedia(DictSerializationMixin):
    text: Optional[str] = attrs.field(repr=False, default=None)
    """
    The text of the field.

    !!! warning
        While `text` is *marked* as optional, it is *currently required* by Discord's API to make polls.
        According to Discord, this may change to be actually optional in the future.
    """
    emoji: Optional[PartialEmoji] = attrs.field(repr=False, default=None, converter=optional(PartialEmoji.from_dict))
    """The emoji of the field."""

    @classmethod
    def create(cls, *, text: Optional[str] = None, emoji: Optional[Union[PartialEmoji, dict, str]] = None) -> Self:
        """
        Create a PollMedia object, used for questions and answers for polls.

        !!! warning
            While `text` is *marked* as optional, it is *currently required* by Discord's API to make polls.
            According to Discord, this may change to be actually optional in the future.

        Args:
            text: The text of the field.
            emoji: The emoji of the field.

        Returns:
            A PollMedia object.

        """
        if not text and not emoji:
            raise ValueError("Either text or emoji must be provided.")

        return cls(text=text, emoji=process_emoji(emoji))


@attrs.define(eq=False, order=False, hash=False, kw_only=True)
class PollAnswer(DictSerializationMixin):
    poll_media: PollMedia = attrs.field(repr=False, converter=PollMedia.from_dict)
    """The data of the answer."""
    answer_id: Optional[int] = attrs.field(repr=False, default=None)
    """The ID of the answer. This is only returned for polls that have been given by Discord's API."""


@attrs.define(eq=False, order=False, hash=False, kw_only=True)
class PollAnswerCount(DictSerializationMixin):
    id: int = attrs.field(repr=False)
    """The answer ID of the answer."""
    count: int = attrs.field(repr=False, default=0)
    """The number of votes for this answer."""
    me_voted: bool = attrs.field(repr=False, default=False)
    """Whether the current user voted for this answer."""


@attrs.define(eq=False, order=False, hash=False, kw_only=True)
class PollResults(DictSerializationMixin):
    is_finalized: bool = attrs.field(repr=False, default=False)
    """Whether the votes have been precisely counted."""
    answer_counts: list[PollAnswerCount] = attrs.field(repr=False, factory=list, converter=PollAnswerCount.from_list)
    """The counts for each answer."""


@attrs.define(eq=False, order=False, hash=False, kw_only=True)
class Poll(DictSerializationMixin):
    question: PollMedia = attrs.field(repr=False, converter=PollMedia.from_dict)
    """The question of the poll. Only text media is supported."""
    answers: list[PollAnswer] = attrs.field(repr=False, factory=list, converter=PollAnswer.from_list)
    """Each of the answers available in the poll, up to 10."""
    expiry: Timestamp = attrs.field(repr=False, default=MISSING, converter=optional(timestamp_converter))
    """Number of hours the poll is open for, up to 32 days."""
    allow_multiselect: bool = attrs.field(repr=False, default=False)
    """Whether a user can select multiple answers."""
    layout_type: PollLayoutType = attrs.field(repr=False, default=PollLayoutType.DEFAULT, converter=PollLayoutType)
    """The layout type of the poll."""
    results: Optional[PollResults] = attrs.field(repr=False, default=None, converter=optional(PollResults.from_dict))
    """The results of the poll, if the polls is finished."""

    _duration: int = attrs.field(repr=False, default=0)
    """How long, in hours, the poll will be open for (up to 32 days). This is only used when creating polls."""

    @classmethod
    def create(
        cls,
        question: str,
        *,
        duration: int,
        allow_multiselect: bool = False,
        answers: Optional[list[PollMedia | str]] = None,
    ) -> Self:
        """
        Create a Poll object for sending.

        Args:
            question: The question of the poll.
            duration: How long, in hours, the poll will be open for (up to 7 days).
            allow_multiselect: Whether a user can select multiple answers.
            answers: Each of the answers available in the poll, up to 10.

        Returns:
            A Poll object.

        """
        if answers:
            media_to_answers = [
                (
                    PollAnswer(poll_media=answer)
                    if isinstance(answer, PollMedia)
                    else PollAnswer(poll_media=PollMedia.create(text=answer))
                )
                for answer in answers
            ]
        else:
            media_to_answers = []

        return cls(
            question=PollMedia(text=question),
            duration=duration,
            allow_multiselect=allow_multiselect,
            answers=media_to_answers,
        )

    @answers.validator
    def _answers_validation(self, attribute: str, value: Any) -> None:
        if len(value) > POLL_MAX_ANSWERS:
            raise ValueError(f"A poll can have at most {POLL_MAX_ANSWERS} answers.")

    @_duration.validator
    def _duration_validation(self, attribute: str, value: int) -> None:
        if value < 0 or value > POLL_MAX_DURATION_HOURS:
            raise ValueError(
                f"The duration must be between 0 and {POLL_MAX_DURATION_HOURS} hours ({POLL_MAX_DURATION_HOURS // 24} days)."
            )

    def add_answer(self, text: Optional[str] = None, emoji: Optional[Union[PartialEmoji, dict, str]] = None) -> Self:
        """
        Adds an answer to the poll.

        !!! warning
            While `text` is *marked* as optional, it is *currently required* by Discord's API to make polls.
            According to Discord, this may change to be actually optional in the future.

        Args:
            text: The text of the answer.
            emoji: The emoji for the answer.

        """
        if not text and not emoji:
            raise ValueError("Either text or emoji must be provided")

        self.answers.append(PollAnswer(poll_media=PollMedia.create(text=text, emoji=emoji)))
        self._answers_validation("answers", self.answers)
        return self

    def to_dict(self) -> Dict[str, Any]:
        data = super().to_dict()

        data["duration"] = self._duration
        data.pop("_duration", None)
        return data

import typing
from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone

if typing.TYPE_CHECKING:
    from datetime import _TzInfo

from croniter import croniter

__all__ = ("BaseTrigger", "CronTrigger", "DateTrigger", "IntervalTrigger", "OrTrigger", "TimeTrigger")


class BaseTrigger(ABC):
    last_call_time: datetime

    def __new__(cls, *args, **kwargs) -> "BaseTrigger":
        new_cls = super().__new__(cls)
        new_cls.last_call_time = datetime.now()
        return new_cls

    def __or__(self, other: "BaseTrigger") -> "OrTrigger":
        return OrTrigger(self, other)

    def reschedule(self) -> None:
        """Update the last call time to now"""
        self.last_call_time = datetime.now()

    def set_last_call_time(self, call_time: datetime) -> None:
        self.last_call_time = call_time

    @abstractmethod
    def next_fire(self) -> datetime | None:
        """
        Return the next datetime to fire on.

        Returns:
            Datetime if one can be determined. If no datetime can be determined, return None

        """
        ...


class IntervalTrigger(BaseTrigger):
    """
    Trigger the task every set interval.

    Attributes:
        seconds Union[int, float]: How many seconds between intervals
        minutes Union[int, float]: How many minutes between intervals
        hours Union[int, float]: How many hours between intervals
        days Union[int, float]: How many days between intervals
        weeks Union[int, float]: How many weeks between intervals

    """

    _t = int | float

    def __init__(self, seconds: _t = 0, minutes: _t = 0, hours: _t = 0, days: _t = 0, weeks: _t = 0) -> None:
        self.delta = timedelta(days=days, seconds=seconds, minutes=minutes, hours=hours, weeks=weeks)

        # lazy check for negatives
        if (datetime.now() + self.delta) < datetime.now():
            raise ValueError("Interval values must result in a time in the future!")

    def next_fire(self) -> datetime | None:
        return self.last_call_time + self.delta


class DateTrigger(BaseTrigger):
    """
    Trigger the task once, when the specified datetime is reached.

    Attributes:
        target_datetime datetime: A datetime representing the date/time to run this task

    """

    def __init__(self, target_datetime: datetime) -> None:
        self.target = target_datetime

    def next_fire(self) -> datetime | None:
        return self.target if datetime.now() < self.target else None


class TimeTrigger(BaseTrigger):
    """
    Trigger the task every day, at a specified (24 hour clock) time.

    Attributes:
        hour int: The hour of the day (24 hour clock)
        minute int: The minute of the hour
        seconds int: The seconds of the minute
        utc bool: If this time is in UTC

    """

    def __init__(self, hour: int = 0, minute: int = 0, seconds: int = 0, utc: bool = True) -> None:
        self.target_time = (hour, minute, seconds)
        self.tz = timezone.utc if utc else None

    def next_fire(self) -> datetime | None:
        now = datetime.now()
        target = datetime(
            now.year,
            now.month,
            now.day,
            self.target_time[0],
            self.target_time[1],
            self.target_time[2],
            tzinfo=self.tz,
        )
        if target.tzinfo == timezone.utc:
            target = target.astimezone(now.tzinfo)
            # target can fall behind or go forward a day, but all we need is the time itself
            # to be converted
            # to ensure it's on the same day as "now" and not break the next if statement,
            # we can just replace the date with now's date
            target = target.replace(year=now.year, month=now.month, day=now.day, tzinfo=None)

        if target <= self.last_call_time:
            target += timedelta(days=1)
        return target


class OrTrigger(BaseTrigger):
    """Trigger a task when any sub-trigger is fulfilled."""

    def __init__(self, *trigger: BaseTrigger) -> None:
        self.triggers: list[BaseTrigger] = list(trigger)
        self.current_trigger: BaseTrigger = None

    def set_last_call_time(self, call_time: datetime) -> None:
        self.current_trigger.last_call_time = call_time

    def _get_delta(self, d: BaseTrigger) -> timedelta:
        next_fire = d.next_fire()
        return abs(next_fire - self.last_call_time) if next_fire else timedelta.max

    def __or__(self, other: "BaseTrigger") -> "OrTrigger":
        self.triggers.append(other)
        return self

    def _set_current_trigger(self) -> BaseTrigger | None:
        self.current_trigger = self.triggers[0] if len(self.triggers) == 1 else min(self.triggers, key=self._get_delta)
        return self.current_trigger

    def next_fire(self) -> datetime | None:
        return self.current_trigger.next_fire() if self._set_current_trigger() else None


class CronTrigger(BaseTrigger):
    """
    Trigger the task based on a cron schedule.

    Attributes:
        cron str: The cron schedule, use https://crontab.guru for help
        tz datetime: Whether or not to use UTC for the time (uses timezone information)

    """

    def __init__(self, cron: str, tz: "_TzInfo" = timezone.utc) -> None:
        self.cron = cron
        self.tz = tz

    def next_fire(self) -> datetime | None:
        return croniter(self.cron, self.last_call_time.astimezone(self.tz)).next(datetime)

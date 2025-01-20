import asyncio
import time
import typing
from enum import IntEnum
from typing import TYPE_CHECKING, Any, Dict, Type

if TYPE_CHECKING:
    from interactions.models.internal.context import BaseContext

__all__ = (
    "Buckets",
    "Cooldown",
    "CooldownSystem",
    "ExponentialBackoffSystem",
    "LeakyBucketSystem",
    "MaxConcurrency",
    "SlidingWindowSystem",
    "TokenBucketSystem",
)


class Buckets(IntEnum):
    """
    Outlines the cooldown buckets that may be used. Should a bucket for guilds exist, and the command is invoked in a DM, a sane default will be used.

    ??? note
         To add your own, override this

    """

    DEFAULT = 0
    """Default is the same as user"""
    USER = 1
    """Per user cooldowns"""
    GUILD = 2
    """Per guild cooldowns"""
    CHANNEL = 3
    """Per channel cooldowns"""
    MEMBER = 4
    """Per guild member cooldowns"""
    CATEGORY = 5
    """Per category cooldowns"""
    ROLE = 6
    """Per role cooldowns"""

    async def get_key(self, context: "BaseContext") -> Any:
        if self is Buckets.USER:
            return context.author.id
        if self is Buckets.GUILD:
            return context.guild_id or context.author.id
        if self is Buckets.CHANNEL:
            return context.channel.id
        if self is Buckets.MEMBER:
            return (context.guild_id, context.author.id) if context.guild_id else context.author.id
        if self is Buckets.CATEGORY:
            return await context.channel.parent_id if context.channel.parent else context.channel.id
        if self is Buckets.ROLE:
            return context.author.top_role.id if context.guild_id else context.channel.id
        return context.author.id

    def __call__(self, context: "BaseContext") -> Any:
        return self.get_key(context)


class CooldownSystem:
    """
    A basic cooldown strategy that allows a specific number of commands to be executed within a given interval. Once the rate is reached, no more tokens can be acquired until the interval has passed.

    Attributes:
        rate: The number of commands allowed per interval.
        interval: The time window (in seconds) within which the allowed number of commands can be executed.

    ??? tip "Example Use-case"
        This strategy is useful for scenarios where you want to limit the number of times a command can be executed within a fixed time frame, such as preventing command spamming or limiting API calls.

    """

    __slots__ = "_tokens", "interval", "opened", "rate"

    def __init__(self, rate: int, interval: float) -> None:
        self.rate: int = rate
        self.interval: float = interval
        self.opened: float = 0.0

        self._tokens: int = self.rate

        # sanity checks
        if self.rate == 0:
            raise ValueError("Cooldown rate must be greater than 0")
        if self.interval == 0:
            raise ValueError("Cooldown interval must be greater than 0")

    def reset(self) -> None:
        """Resets the tokens for this cooldown."""
        self._tokens = self.rate
        self.opened = 0.0

    def on_cooldown(self) -> bool:
        """
        Returns the cooldown state of the command.

        Returns:
            boolean state if the command is on cooldown or not

        """
        self.determine_cooldown()

        return self._tokens == 0

    def acquire_token(self) -> bool:
        """
        Attempt to acquire a token for a command to run.

        Returns:
            True if a token was acquired, False if not

        """
        self.determine_cooldown()

        if self._tokens == 0:
            return False
        if self._tokens == self.rate:
            self.opened = time.time()
        self._tokens -= 1

        return True

    def get_cooldown_time(self) -> float:
        """
        Returns how long until the cooldown will reset.

        Returns:
            remaining cooldown time, will return 0 if the cooldown has not been reached

        """
        self.determine_cooldown()
        return 0 if self._tokens != 0 else self.interval - (time.time() - self.opened)

    def determine_cooldown(self) -> None:
        """Determines the state of the cooldown system."""
        c_time = time.time()

        if c_time > self.opened + self.interval:
            # cooldown has expired, reset the cooldown
            self.reset()


class SlidingWindowSystem(CooldownSystem):
    """
    A sliding window cooldown strategy that allows a specific number of commands to be executed within a rolling time window.

    The cooldown incrementally resets as commands fall outside of the window.

    Attributes:
        rate: The number of commands allowed per interval.
        interval: The time window (in seconds) within which the allowed number of commands can be executed.

    ??? tip "Example Use-case"
        This strategy is useful for scenarios where you want to limit the rate of commands executed over a continuous time window, such as ensuring consistent usage of resources or controlling chat bot response frequency.

    """

    __slots__ = "interval", "rate", "timestamps"

    def __init__(self, rate: int, interval: float) -> None:
        self.rate: int = rate
        self.interval: float = interval
        self.timestamps: list[float] = []

        # sanity checks
        if self.rate == 0:
            raise ValueError("Cooldown rate must be greater than 0")
        if self.interval == 0:
            raise ValueError("Cooldown interval must be greater than 0")

    def on_cooldown(self) -> bool:
        """
        Returns the cooldown state of the command.

        Returns:
            boolean state if the command is on cooldown or not

        """
        self._trim()

        return len(self.timestamps) >= self.rate

    def acquire_token(self) -> bool:
        """
        Attempt to acquire a token for a command to run.

        Returns:
            True if a token was acquired, False if not

        """
        self._trim()

        if len(self.timestamps) >= self.rate:
            return False

        self.timestamps.append(time.time())

        return True

    def get_cooldown_time(self) -> float:
        """
        Returns how long until the cooldown will reset.

        Returns:
            remaining cooldown time, will return 0 if the cooldown has not been reached

        """
        self._trim()

        if len(self.timestamps) < self.rate:
            return 0

        return self.timestamps[0] + self.interval - time.time()

    def reset(self) -> None:
        """Resets the timestamps for this cooldown."""
        self.timestamps = []

    def _trim(self) -> None:
        """Removes all timestamps that are outside the current interval."""
        cutoff = time.time() - self.interval

        while self.timestamps and self.timestamps[0] < cutoff:
            self.timestamps.pop(0)


class ExponentialBackoffSystem(CooldownSystem):
    """
    An exponential backoff cooldown strategy that doubles the interval between allowed commands after each failed attempt, up to a maximum interval.

    Attributes:
        rate: The number of commands allowed per interval.
        interval: The initial time window (in seconds) within which the allowed number of commands can be executed.
        max_interval: The maximum time window (in seconds) between allowed commands.
        multiplier: The multiplier to apply to the interval after each failed attempt.

    ??? tip "Example Use-case"
        This strategy is useful for scenarios where you want to progressively slow down repeated attempts at a command, such as preventing brute force attacks or limiting retries on failed operations.

    """

    def __init__(self, rate: int, interval: float, max_interval: float, multiplier: float = 2) -> None:
        super().__init__(rate, interval)
        self.max_interval = max_interval
        self.multiplier = multiplier

    def determine_cooldown(self) -> None:
        c_time = time.time()

        if c_time > self.opened + self.interval:
            if self.interval < self.max_interval:
                self.interval *= self.multiplier
            self.reset()


class LeakyBucketSystem(CooldownSystem):
    """
    A leaky bucket cooldown strategy that gradually replenishes tokens over time, allowing commands to be executed as long as there are available tokens in the bucket.

    Attributes:
        rate: The number of tokens generated per interval.
        interval: The time window (in seconds) within which the tokens are generated.

    ??? tip "Example Use-case"
        This strategy is useful for scenarios where you want to allow a steady flow of commands to be executed while preventing sudden bursts, such as rate limiting API calls or managing user interactions in a chatbot.

    """

    def determine_cooldown(self) -> None:
        c_time = time.time()

        tokens_to_recover = (c_time - self.opened) / self.interval
        if tokens_to_recover >= 1:
            self._tokens = min(self.rate, self._tokens + int(tokens_to_recover))
            self.opened = c_time


class TokenBucketSystem(CooldownSystem):
    """
    A token bucket cooldown strategy that generates tokens at a specific rate up to a burst rate, allowing commands to be executed as long as there are available tokens in the bucket.

    Attributes:
        rate: The number of tokens generated per interval.
        interval: The time window (in seconds) within which the tokens are generated.
        burst_rate: The maximum number of tokens that can be held in the bucket at any given time.

    ??? tip "Example Use-case"
        This strategy is useful for scenarios where you want to allow a burst of commands to be executed while limiting the overall rate, such as handling peak traffic in an API or permitting rapid user interactions in a game.

    """

    def __init__(self, rate: int, interval: float, burst_rate: int) -> None:
        super().__init__(rate, interval)
        self.burst_rate = burst_rate

    def determine_cooldown(self) -> None:
        c_time = time.time()

        tokens_to_recover = (c_time - self.opened) / self.interval
        if tokens_to_recover >= 1:
            self._tokens = min(self.burst_rate, self._tokens + int(tokens_to_recover))
            self.opened = c_time


class Cooldown:
    """
    Manages cooldowns and their respective buckets for a command.

    There are two pre-defined cooldown systems, a sliding window and a standard cooldown system (default);
    you can specify which one to use by passing in the cooldown_system parameter.

    Attributes:
        bucket: The bucket to use for this cooldown
        cooldown_repositories: A dictionary of cooldowns for each bucket
        rate: How many commands may be ran per interval
        interval: How many seconds to wait for a cooldown
        cooldown_system: The cooldown system to use for this cooldown

    """

    __slots__ = "bucket", "cooldown_repositories", "cooldown_system", "interval", "rate"

    def __init__(
        self,
        cooldown_bucket: Buckets,
        rate: int,
        interval: float,
        *,
        cooldown_system: Type[CooldownSystem] = CooldownSystem,
    ) -> None:
        self.bucket: Buckets = cooldown_bucket
        self.cooldown_repositories = {}
        self.rate: int = rate
        self.interval: float = interval

        self.cooldown_system: Type[CooldownSystem] = cooldown_system or CooldownSystem

    async def get_cooldown(self, context: "BaseContext") -> "CooldownSystem":
        key = await self.bucket(context)

        if key not in self.cooldown_repositories:
            cooldown = self.cooldown_system(self.rate, self.interval)
            self.cooldown_repositories[key] = cooldown
            return cooldown
        return self.cooldown_repositories.get(await self.bucket(context))

    def get_cooldown_with_key(self, key: Any, *, create: bool = False) -> typing.Optional["CooldownSystem"]:
        """
        Get the cooldown system for the command.

        Note:
            The preferred way to get the cooldown system is to use `get_cooldown` as it will use the context to get the correct key.

        Args:
            key: The key to get the cooldown system for
            create: Whether to create a new cooldown system if one does not exist

        """
        if key not in self.cooldown_repositories and create:
            cooldown = self.cooldown_system(self.rate, self.interval)
            self.cooldown_repositories[key] = cooldown
            return cooldown
        return self.cooldown_repositories.get(key)

    async def acquire_token(self, context: "BaseContext") -> bool:
        """
        Attempt to acquire a token for a command to run. Uses the context of the command to use the correct CooldownStrategy.

        Args:
            context: The context of the command

        Returns:
            True if a token was acquired, False if not

        """
        cooldown = await self.get_cooldown(context)

        return cooldown.acquire_token()

    async def get_cooldown_time(self, context: "BaseContext") -> float:
        """
        Get the remaining cooldown time.

        Args:
            context: The context of the command

        Returns:
            remaining cooldown time, will return 0 if the cooldown has not been reached

        """
        cooldown = await self.get_cooldown(context)
        return cooldown.get_cooldown_time()

    def get_cooldown_time_with_key(self, key: Any, *, create: bool = False) -> float:
        """
        Get the remaining cooldown time with a key instead of the context.

        Note:
            The preferred way to get the cooldown system is to use `get_cooldown` as it will use the context to get the correct key.

        Args:
            key: The key to get the cooldown system for
            create: Whether to create a new cooldown system if one does not exist

        """
        cooldown = self.get_cooldown_with_key(key, create=create)
        if cooldown is not None:
            return cooldown.get_cooldown_time()
        return 0

    async def on_cooldown(self, context: "BaseContext") -> bool:
        """
        Returns the cooldown state of the command.

        Args:
            context: The context of the command

        Returns:
            boolean state if the command is on cooldown or not

        """
        cooldown = await self.get_cooldown(context)
        return cooldown.on_cooldown()

    async def reset_all(self) -> None:
        """
        Resets this cooldown system to its initial state.

        !!! warning     To be clear, this will reset **all** cooldowns
        for this command to their initial states

        """
        # this doesnt need to be async, but for consistency, it is
        self.cooldown_repositories = {}

    async def reset(self, context: "BaseContext") -> None:
        """
        Resets the cooldown for the bucket of which invoked this command.

        Args:
            context: The context of the command

        """
        cooldown = await self.get_cooldown(context)
        cooldown.reset()

    def reset_with_key(self, key: Any) -> bool:
        """
        Resets the cooldown for the bucket associated with the provided key.

        Note:
            The preferred way to reset the cooldown system is to use `reset_cooldown` as it will use the context to reset the correct cooldown.

        Args:
            key: The key to reset the cooldown system for

        Returns:
            True if the key existed and was reset successfully, False if the key didn't exist.

        """
        cooldown = self.get_cooldown_with_key(key)
        if cooldown is not None:
            cooldown.reset()
            return True
        return False


class MaxConcurrency:
    """
    Limits how many instances of a command may be running concurrently.

    Attributes:
        bucket Buckets: The bucket this concurrency applies to
        concurrent int: The maximum number of concurrent instances permitted to
        wait bool: Should we wait until a instance is available

    """

    def __init__(self, concurrent: int, concurrency_bucket: Buckets, wait: bool = False) -> None:
        self.bucket: Buckets = concurrency_bucket
        self.concurrency_repository: Dict = {}
        self.concurrent: int = concurrent
        self.wait = wait

    async def get_semaphore(self, context: "BaseContext") -> asyncio.Semaphore:
        """
        Get the semaphore associated with the given context.

        Args:
            context: The commands context

        Returns:
            A semaphore object

        """
        key = await self.bucket(context)

        if key not in self.concurrency_repository:
            semaphore = asyncio.Semaphore(self.concurrent)
            self.concurrency_repository[key] = semaphore
            return semaphore
        return self.concurrency_repository.get(key)

    async def acquire(self, context: "BaseContext") -> bool:
        """
        Acquire an instance of the semaphore.

        Args:
            context:The context of the command
        Returns:
            If the semaphore was successfully acquired

        """
        semaphore = await self.get_semaphore(context)

        if not self.wait and semaphore.locked():
            return False
        return await semaphore.acquire()

    async def release(self, context: "BaseContext") -> None:
        """
        Release the semaphore.

        Args:
            context: The context of the command

        """
        semaphore = await self.get_semaphore(context)

        semaphore.release()

import time
from collections import OrderedDict
from collections.abc import ItemsView, ValuesView
from typing import Any, Callable, Generic, Iterator, Optional, Tuple, TypeVar

import attrs

__all__ = ("NullCache", "TTLCache", "TTLItem")

KT = TypeVar("KT")
VT = TypeVar("VT")


class NullCache(dict):
    """
    A special cache that will always return None

    Effectively just a lazy way to disable caching.
    """

    def __setitem__(self, key, value) -> None:
        pass


@attrs.define(eq=False, order=False, hash=False, kw_only=False)
class TTLItem(Generic[VT]):
    value: VT = attrs.field(
        repr=False,
    )
    expire: float = attrs.field(
        repr=False,
    )
    """When the item expires in cache."""

    def is_expired(self, timestamp: float) -> bool:
        """
        Check if the item is expired.

        Args:
            timestamp: The current timestamp to compare against.

        Returns:
            True if the item is expired, False otherwise.

        """
        return timestamp >= self.expire


class TTLCache(OrderedDict[KT, TTLItem[VT]]):
    def __init__(
        self,
        ttl: int = 600,
        soft_limit: int = 50,
        hard_limit: int = 250,
        on_expire: Optional[Callable] = None,
    ) -> None:
        super().__init__()

        self.ttl = ttl
        self.hard_limit = hard_limit
        self.soft_limit = min(soft_limit, hard_limit)
        self.on_expire = on_expire

    def __setitem__(self, key: KT, value: VT) -> None:
        expire = time.monotonic() + self.ttl
        item = TTLItem(value, expire)
        super().__setitem__(key, item)
        self.move_to_end(key)

        self.expire()

    def __getitem__(self, key: KT) -> VT:
        # Will not (should not) reset expiration!
        item = super().__getitem__(key)
        # self._reset_expiration(key, item)
        return item.value

    def pop(self, key: KT, default=attrs.NOTHING) -> VT:
        if key in self:
            item = self[key]
            del self[key]
            return item

        if default is attrs.NOTHING:
            raise KeyError(key)

        return default

    def get(self, key: KT, default: Optional[VT] = None, reset_expiration: bool = True) -> VT:
        item = super().get(key, default)
        if item is not default:
            if reset_expiration:
                self._reset_expiration(key, item)
            return item.value

        return default

    def values(self) -> ValuesView[VT]:
        return _CacheValuesView(self)

    def items(self) -> ItemsView:
        return _CacheItemsView(self)

    def _reset_expiration(self, key: KT, item: TTLItem) -> None:
        self.move_to_end(key)
        item.expire = time.monotonic() + self.ttl

    def _first_item(self) -> Tuple[KT, TTLItem[VT]]:
        return next(super().items().__iter__())

    def expire(self) -> None:
        """Removes expired elements from the cache."""
        if self.soft_limit and len(self) <= self.soft_limit:
            return

        if self.hard_limit:
            while len(self) > self.hard_limit:
                self._expire_first()

        timestamp = time.monotonic()
        while True:
            key, item = self._first_item()
            if item.is_expired(timestamp):
                self._expire_first()
            else:
                break

    def _expire_first(self) -> None:
        key, value = self.popitem(last=False)
        if self.on_expire:
            self.on_expire(key, value)


class _CacheValuesView(ValuesView):
    def __contains__(self, value) -> bool:
        for key in self._mapping:
            v = self._mapping.get(key, reset_expiration=False)
            if v is value or v == value:
                return True
        return False

    def __iter__(self) -> Iterator[Any]:
        for key in self._mapping:
            yield self._mapping.get(key, reset_expiration=False)

    def __reversed__(self) -> Iterator[Any]:
        for key in reversed(self._mapping):
            yield self._mapping.get(key, reset_expiration=False)


class _CacheItemsView(ItemsView):
    def __contains__(self, item) -> bool:
        key, value = item
        v = self._mapping.get(key, default=attrs.NOTHING, reset_expiration=False)
        return False if v is attrs.NOTHING else v is value or v == value

    def __iter__(self) -> Iterator[Tuple[Any, Any]]:
        for key in self._mapping:
            yield key, self._mapping.get(key, reset_expiration=False)

    def __reversed__(self) -> Iterator[Tuple[Any, Any]]:
        for key in reversed(self._mapping):
            yield key, self._mapping.get(key, reset_expiration=False)

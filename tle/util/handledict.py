from collections.abc import ItemsView, Iterator
from typing import Any


class HandleDict:
    """A case insensitive dictionary for handling usernames."""

    def __init__(self) -> None:
        self._store: dict[str, tuple[str, Any]] = {}

    @staticmethod
    def _getlower(key: str) -> str:
        return key.lower() if isinstance(key, str) else key

    def __setitem__(self, key: str, value: Any) -> None:
        # Use the lowercased key for lookups, but store the actual
        # key alongside the value.
        self._store[self._getlower(key)] = (key, value)

    def __getitem__(self, key: str) -> Any:
        return self._store[self._getlower(key)][1]

    def __delitem__(self, key: str) -> None:
        del self._store[self._getlower(key)]

    def __iter__(self) -> Iterator[str]:
        return (cased_key for cased_key, mapped_value in self._store.values())

    def items(self) -> ItemsView[str, Any]:
        return dict([value for value in self._store.values()]).items()

    def __repr__(self) -> str:
        return str(self.items())

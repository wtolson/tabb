from __future__ import annotations

from collections.abc import Iterator, Mapping
from typing import TypeVar, overload

U = TypeVar("U")


class Config(Mapping[str, object]):
    def __init__(self, *mappings: Mapping[str, object]) -> None:
        self._mappings: list[Mapping[str, object]] = list(mappings) if mappings else []

    def merge(self, data: Mapping[str, object]) -> None:
        self._mappings.append(data)

    def subconfig(self, key: str) -> Config:
        mappings: list[Mapping[str, object]] = []

        for mapping in self._mappings:
            try:
                value = mapping[key]
            except KeyError:
                continue

            if isinstance(value, Mapping):
                mappings.append(value)

        return self.__class__(*mappings)

    def __missing__(self, key: str) -> object:
        raise KeyError(key)

    def __getitem__(self, key: str) -> object:
        mappings = reversed(self._mappings)

        for mapping in mappings:
            try:
                value = mapping[key]
            except KeyError:
                continue

            if not isinstance(value, Mapping):
                return value

            submapping = self.__class__(value)

            for parent in mappings:
                try:
                    value = parent[key]
                except KeyError:
                    continue

                if not isinstance(value, Mapping):
                    return value

                submapping.merge(value)

            return submapping

        return self.__missing__(key)

    @overload
    def get(self, key: str) -> object | None:
        ...

    @overload
    def get(self, key: str, default: U) -> object | U:
        ...

    def get(self, key: str, default: U | None = None) -> object | U | None:
        return self[key] if key in self else default

    @overload
    def get_path(self, path: str) -> object | None:
        ...

    @overload
    def get_path(self, path: str, default: U) -> object | U:
        ...

    def get_path(self, path: str, default: U | None = None) -> object | U | None:
        keys = path.split(".")
        value: object = self

        for key in keys:
            if not isinstance(value, Mapping):
                return default

            try:
                value = value[key]
            except KeyError:
                return default

        return value

    def __len__(self) -> int:
        return len(set().union(*self._mappings))

    def __iter__(self) -> Iterator[str]:
        result = {}
        for mapping in reversed(self._mappings):
            result.update(dict.fromkeys(mapping))
        return iter(result)

    def __contains__(self, key: object) -> bool:
        if not isinstance(key, str):
            return False
        return any(key in m for m in self._mappings)

    def __bool__(self) -> bool:
        return any(self._mappings)

    def __repr__(self) -> str:
        mappings = ", ".join(map(repr, self._mappings))
        return f"{self.__class__.__name__}({mappings})"

    def copy(self) -> Config:
        return self.__class__(*self._mappings)

    __copy__ = copy

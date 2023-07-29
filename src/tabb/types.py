from __future__ import annotations

import dataclasses
import re
from collections.abc import Callable, Sequence
from typing import Any, Generic, TypeVar

from tabb.missing import _MISSING_TYPE, MISSING
from tabb.parameter.types import ParameterType

ValueType = TypeVar("ValueType")


class Secret(str):
    """
    Holds a string value that should not be revealed in tracebacks etc.
    You should cast the value to `str` at the point it is required.
    """

    def __repr__(self) -> str:
        return f'{type(self).__name__}("**********")'


@dataclasses.dataclass()
class Length:
    min: int | None = None  # noqa: A003
    max: int | None = None  # noqa: A003


@dataclasses.dataclass()
class Range:
    min: int | float | None = None  # noqa: A003
    max: int | float | None = None  # noqa: A003
    max_open: bool = False
    min_open: bool = False
    clamp: bool = False


@dataclasses.dataclass()
class Choices(Generic[ValueType]):
    values: tuple[ValueType, ...]

    def __init__(self, *values: ValueType) -> None:
        self.values = values


@dataclasses.dataclass()
class Matches:
    pattern: re.Pattern[str]

    def __init__(self, pattern: str | re.Pattern[str]) -> None:
        if isinstance(pattern, str):
            pattern = re.compile(pattern)
        self.pattern = pattern


@dataclasses.dataclass()
class Greedy:
    is_greedy: bool = True


@dataclasses.dataclass()
class Validate(Generic[ValueType]):
    validator: Callable[[Any], bool]


class Argument(Generic[ValueType]):
    def __init__(
        self,
        *,
        config: str | Sequence[str] | _MISSING_TYPE = MISSING,
        default_factory: Callable[[], ValueType] | _MISSING_TYPE = MISSING,
        default: ValueType | _MISSING_TYPE = MISSING,
        envvar: str | Sequence[str] | _MISSING_TYPE = MISSING,
        help: str | _MISSING_TYPE = MISSING,
        hidden: bool | _MISSING_TYPE = MISSING,
        metavar: str | _MISSING_TYPE = MISSING,
        type: ParameterType[ValueType] | _MISSING_TYPE = MISSING,
    ) -> None:
        self.config = config
        self.default_factory = default_factory
        self.default: ValueType | _MISSING_TYPE = default
        self.envvar = envvar
        self.help = help
        self.hidden = hidden
        self.metavar = metavar
        self.type = type


class Option(Generic[ValueType]):
    def __init__(
        self,
        *flags: str,
        config: str | Sequence[str] | _MISSING_TYPE = MISSING,
        default_factory: Callable[[], Any] | _MISSING_TYPE = MISSING,
        default: Any | _MISSING_TYPE = MISSING,
        envvar: str | Sequence[str] | _MISSING_TYPE = MISSING,
        help: str | _MISSING_TYPE = MISSING,
        hidden: bool | _MISSING_TYPE = MISSING,
        metavar: str | _MISSING_TYPE = MISSING,
        show_config: bool | _MISSING_TYPE = MISSING,
        show_default: bool | _MISSING_TYPE = MISSING,
        show_envvar: bool | _MISSING_TYPE = MISSING,
        type: ParameterType[Any] | _MISSING_TYPE = MISSING,
    ) -> None:
        self.flags = flags
        self.config = config
        self.default_factory = default_factory
        self.default = default
        self.envvar = envvar
        self.help = help
        self.hidden = hidden
        self.metavar = metavar
        self.show_config = show_config
        self.show_default = show_default
        self.show_envvar = show_envvar
        self.type = type


class Depends(Generic[ValueType]):
    def __init__(
        self, dependency: Callable[..., ValueType], *, use_cache: bool = True
    ) -> None:
        self.dependency = dependency
        self.use_cache = use_cache

from __future__ import annotations

import abc
import dataclasses
import enum
from typing import Any, Generic, TypeVar

from tabb.context import Context
from tabb.missing import _MISSING_TYPE

ValueType = TypeVar("ValueType")


class ParameterKind(enum.Enum):
    POSITIONAL = enum.auto()
    KEYWORD = enum.auto()
    POSITIONAL_OR_KEYWORD = enum.auto()
    VAR_POSITIONAL = enum.auto()
    VAR_KEYWORD = enum.auto()


class ParameterSource(enum.Enum):
    COMMANDLINE = enum.auto()
    ENVIRONMENT = enum.auto()
    CONFIG = enum.auto()
    DEFAULT = enum.auto()
    PROMPT = enum.auto()
    DEPENDS = enum.auto()


@dataclasses.dataclass(frozen=True, slots=True)
class ParameterValue(Generic[ValueType]):
    value: ValueType | _MISSING_TYPE
    source: ParameterSource
    param: Parameter[ValueType]


class Parameter(abc.ABC, Generic[ValueType]):
    POSITIONAL = ParameterKind.POSITIONAL
    KEYWORD = ParameterKind.KEYWORD
    POSITIONAL_OR_KEYWORD = ParameterKind.POSITIONAL_OR_KEYWORD
    VAR_POSITIONAL = ParameterKind.VAR_POSITIONAL
    VAR_KEYWORD = ParameterKind.VAR_KEYWORD

    def __init__(
        self,
        name: str,
        kind: ParameterKind,
    ) -> None:
        self.name = name
        self.kind = kind

    def get_param_type(self) -> str:
        return "parameter"

    def get_usage_pieces(self, ctx: Context[Any] | None = None) -> list[str]:
        return []

    def get_help_record(
        self, ctx: Context[Any] | None = None
    ) -> tuple[str, str] | None:
        return None

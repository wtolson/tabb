from __future__ import annotations

import abc
import dataclasses
from itertools import repeat
from typing import Literal

NArgsLiteral = int | Literal["?", "*", "+", "??", "*?", "+?"]


@dataclasses.dataclass(slots=True, frozen=True)
class NArgs(abc.ABC):
    @staticmethod
    def from_literal(value: NArgsLiteral) -> NArgs:
        if isinstance(value, int):
            return IntNArgs(value)

        if value == "?":
            return VariadicNArgs(IntNArgs(1), min_values=0, max_values=1, greedy=True)

        if value == "*":
            return VariadicNArgs(
                IntNArgs(1), min_values=0, max_values=None, greedy=True
            )

        if value == "+":
            return VariadicNArgs(
                IntNArgs(1), min_values=1, max_values=None, greedy=True
            )

        if value == "??":
            return VariadicNArgs(IntNArgs(1), min_values=0, max_values=1, greedy=False)

        if value == "*?":
            return VariadicNArgs(
                IntNArgs(1), min_values=0, max_values=None, greedy=False
            )

        if value == "+?":
            return VariadicNArgs(
                IntNArgs(1), min_values=1, max_values=None, greedy=False
            )

        msg = f"Invalid nargs literal: {value!r}"
        raise ValueError(msg)

    def as_optional(self) -> NArgs:
        return VariadicNArgs(self, min_values=0, max_values=1, greedy=True)

    @abc.abstractmethod
    def decrement(self) -> NArgs | None:
        ...

    @abc.abstractmethod
    def format_metavar(self, metavar: str) -> str:
        ...

    @abc.abstractmethod
    def __str__(self) -> str:
        ...


@dataclasses.dataclass(slots=True, frozen=True)
class IntNArgs(NArgs):
    value: int

    def __post_init__(self) -> None:
        if self.value < 0:
            raise ValueError("nargs cannot be negative.")

    def decrement(self) -> IntNArgs | None:
        if self.value <= 1:
            return None
        return IntNArgs(self.value - 1)

    def format_metavar(self, metavar: str) -> str:
        if self.value <= 16 // len(metavar):
            return " ".join(repeat(metavar, self.value))
        return f"{metavar}{{{self.value}}}"

    def __str__(self) -> str:
        return f"{{{self.value}}}"


@dataclasses.dataclass(slots=True, frozen=True)
class VariadicNArgs(NArgs):
    value: NArgs
    min_values: int
    max_values: int | None
    greedy: bool = True

    def __post_init__(self) -> None:
        if self.min_values < 0:
            raise ValueError("min_values cannot be negative.")

        if self.max_values is None:
            return

        if self.min_values > self.max_values:
            raise ValueError("min_values cannot be greater than max_values.")

    def as_optional(self) -> NArgs:
        if self.min_values == 0:
            return self
        return super(VariadicNArgs, self).as_optional()  # noqa: UP008

    def decrement(self) -> VariadicNArgs | None:
        if self.max_values == 1:
            return None

        return VariadicNArgs(
            value=self.value,
            min_values=self.min_values and self.min_values - 1,
            max_values=self.max_values and self.max_values - 1,
            greedy=self.greedy,
        )

    def _format_range(self) -> str:
        if self.min_values == self.max_values:
            return f"{{{self.min_values}}}"

        max_value = "" if self.max_values is None else self.max_values
        greedy = "" if self.greedy else "?"

        return f"{{{self.min_values},{max_value}}}{greedy}"

    def _format_modifier(self) -> str:
        greedy = "" if self.greedy else "?"

        if self.min_values == 0 and self.max_values == 1:
            return f"?{greedy}"

        if self.min_values == 0 and self.max_values is None:
            return f"*{greedy}"

        if self.min_values == 1 and self.max_values is None:
            return f"+{greedy}"

        return self._format_range()

    def format_metavar(self, metavar: str) -> str:
        result = self.value.format_metavar(metavar)
        if not result:
            return ""

        if self.min_values == 0 and self.max_values == 0:
            return ""

        if self.min_values == 1 and self.max_values == 1:
            return result

        if result == metavar and self.min_values == self.max_values:
            return IntNArgs(self.min_values).format_metavar(metavar)

        if result != metavar:
            result = f"({result})"

        return f"{result}{self._format_modifier()}"

    def __str__(self) -> str:
        result = str(self.value)
        if result == "{0}":
            return "{0}"

        if self.min_values == 0 and self.max_values == 0:
            return "{0}"

        if self.min_values == 1 and self.max_values == 1:
            return result

        if result == "{1}":
            return self._format_range()

        return f"({result}){self._format_modifier()}"

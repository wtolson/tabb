from __future__ import annotations

import abc
import dataclasses
import operator
import os
import pathlib
import typing
from collections.abc import Callable, Hashable, Mapping, Sequence, Sized
from types import UnionType
from typing import (
    TYPE_CHECKING,
    Any,
    Generic,
    NoReturn,
    TypeAlias,
    TypeGuard,
    TypeVar,
    Union,
    cast,
    overload,
)

from tabb.exceptions import BadParameter, Help
from tabb.missing import _MISSING_TYPE, MISSING
from tabb.nargs import IntNArgs, NArgs, NArgsLiteral, VariadicNArgs
from tabb.utils import split_csv

if TYPE_CHECKING:
    from tabb.context import Context
    from tabb.parameter import ParserParameter

KeyType = TypeVar("KeyType", bound=Hashable)
SizedValueType = TypeVar("SizedValueType", bound=Sized)
ValueType = TypeVar("ValueType")

Number = TypeVar("Number", int, float)
NumberLike = TypeVar("NumberLike", bound=int | float)


@dataclasses.dataclass(slots=True, frozen=True)
class PositionalArg:
    value: str


@dataclasses.dataclass(slots=True, frozen=True)
class OptionArg:
    flag: str
    value: str | None


ParameterArg: TypeAlias = PositionalArg | OptionArg


class ParameterType(abc.ABC, Generic[ValueType]):
    @abc.abstractproperty
    def name(self) -> str:
        pass

    @property
    def nargs(self) -> NArgs:
        return IntNArgs(1)

    def has_default(self) -> bool:
        return_type = typing.get_type_hints(self.process_args).get("return", None)
        if return_type is _MISSING_TYPE:
            return False

        if typing.get_origin(return_type) not in (Union, UnionType):
            return True

        return _MISSING_TYPE not in typing.get_args(return_type)

    def get_metavar(self, ctx: Context[Any] | None) -> str | None:
        """Returns the metavar default for this param if it provides one."""
        return None

    def parse_flags(self, flags: Sequence[str]) -> tuple[list[str], list[str]]:
        return list(flags), []

    def format_value(self, value: ValueType) -> str:
        return repr(value)

    def fail(
        self,
        message: str,
        ctx: Context[Any] | None = None,
        param: ParserParameter[Any] | None = None,
    ) -> NoReturn:
        """Helper method to fail with an invalid value message."""
        raise BadParameter(message, ctx=ctx, param=param)

    def process_config(self, value: object) -> object:
        return value

    @abc.abstractmethod
    def matches(self, arg: ParameterArg) -> bool:
        """Reduces a new argument value into the current value."""
        ...

    @abc.abstractmethod
    def process_args(self, args: list[ParameterArg]) -> ValueType | _MISSING_TYPE:
        """Reduces a new argument value into the current value."""
        ...

    @abc.abstractmethod
    def parse_envvar(self, value: str) -> ValueType:
        """Parses a value from an environment variable."""
        ...

    @abc.abstractmethod
    def validate(self, value: Any) -> TypeGuard[ValueType]:
        """Validate a value after it was parsed."""
        ...


class TypeAdapter(ParameterType[ValueType]):
    def __init__(self, type: ParameterType[ValueType]) -> None:
        self.type = type
        super().__init__()

    @property
    def name(self) -> str:
        return f"<{type(self).__name__} type={self.type.name}>"

    @property
    def nargs(self) -> NArgs:
        return self.type.nargs

    def has_default(self) -> bool:
        return self.type.has_default()

    def get_metavar(self, ctx: Context[Any] | None) -> str | None:
        return self.type.get_metavar(ctx)

    def parse_flags(self, flags: Sequence[str]) -> tuple[list[str], list[str]]:
        return self.type.parse_flags(flags)

    def format_value(self, value: ValueType) -> str:
        return self.type.format_value(value)

    def matches(self, arg: ParameterArg) -> bool:
        return self.type.matches(arg)

    def process_args(self, args: list[ParameterArg]) -> ValueType | _MISSING_TYPE:
        return self.type.process_args(args)

    def process_config(self, value: object) -> object:
        return self.type.process_config(value)

    def parse_envvar(self, value: str) -> ValueType:
        return self.type.parse_envvar(value)

    def validate(self, value: Any) -> TypeGuard[ValueType]:
        return self.type.validate(value)


class AnyType(ParameterType[Any]):
    @property
    def name(self) -> str:
        return "Any"

    @property
    def nargs(self) -> NArgs:
        return IntNArgs(0)

    def has_default(self) -> bool:
        return False

    def matches(self, arg: ParameterArg) -> bool:
        return False

    def process_args(self, args: list[ParameterArg]) -> Any | _MISSING_TYPE:
        return MISSING

    def parse_envvar(self, value: str) -> Any:
        return value

    def validate(self, value: Any) -> TypeGuard[Any]:
        """Validate a value after it was parsed."""
        return True


class Scalar(ParameterType[ValueType]):
    def __init__(
        self, type: Callable[[str], ValueType], allow_overwrite: bool = True
    ) -> None:
        self.type = type
        self.allow_overwrite = allow_overwrite
        super().__init__()

    @property
    def name(self) -> str:
        # Return name if type is builtin
        if self.type.__module__ == "builtins":
            return self.type.__name__.lower()
        return repr(self.type)

    def matches(self, arg: ParameterArg) -> bool:
        if arg.value is None:
            return False

        try:
            self.type(arg.value)
        except (BadParameter, ValueError):
            return False

        return True

    def parse(self, value: str) -> ValueType:
        try:
            return self.type(value)
        except ValueError:
            self.fail(f"{value!r} is not a valid {self.name}.")

    def process_arg(self, arg: ParameterArg) -> ValueType:
        if arg.value is None:
            raise TypeError("Expected string value")
        return self.parse(arg.value)

    def process_args(self, args: list[ParameterArg]) -> ValueType | _MISSING_TYPE:
        if not args:
            return MISSING

        if len(args) != 1 and not self.allow_overwrite:
            self.fail("Parameter already set.")

        return self.process_arg(args[-1])

    def parse_envvar(self, value: str) -> ValueType:
        return self.parse(value)

    def validate(self, value: Any) -> TypeGuard[ValueType]:
        if isinstance(self.type, type) and not isinstance(value, self.type):
            self.fail(f"Expected {self.name} value")
        return True


class String(Scalar[str]):
    def __init__(self, allow_overwrite: bool = True) -> None:
        super().__init__(str, allow_overwrite)


class Int(Scalar[int]):
    def __init__(self, allow_overwrite: bool = True) -> None:
        super().__init__(int, allow_overwrite)


class Float(Scalar[float]):
    def __init__(self, allow_overwrite: bool = True) -> None:
        super().__init__(float, allow_overwrite)


class Bool(Scalar[bool]):
    true_values = ("1", "true", "t", "yes", "y", "on")
    false_values = ("0", "false", "f", "no", "n", "off")

    def __init__(self, allow_overwrite: bool = False) -> None:
        super().__init__(bool, allow_overwrite=allow_overwrite)

    @property
    def name(self) -> str:
        return "bool"

    def format_value(self, value: bool) -> str:
        return "true" if value else "false"

    def matches(self, arg: ParameterArg) -> bool:
        if arg.value is None:
            return False
        value = arg.value.lower()
        return value in self.true_values or value in self.false_values

    def parse(self, value: str) -> bool:
        if value.lower() in self.true_values:
            return True

        if value.lower() in self.false_values:
            return False

        self.fail(f"{value!r} is not a valid bool (try true/false).")


class Flag(Bool):
    def __init__(self, allow_overwrite: bool = False) -> None:
        self.true_flags: list[str] = []
        self.false_flags: list[str] = []
        super().__init__(allow_overwrite=allow_overwrite)

    @property
    def name(self) -> str:
        return "<BooleanFlag>"

    @property
    def nargs(self) -> NArgs:
        return IntNArgs(0)

    def format_value(self, value: bool) -> str:
        return self.true_flags[0] if value else self.false_flags[0]

    def parse_flags(self, flags: Sequence[str]) -> tuple[list[str], list[str]]:
        for flag in flags:
            true_flag, _, false_flag = flag.partition("/")

            if true_flag:
                self.true_flags.append(true_flag)

            if false_flag:
                self.false_flags.append(false_flag)

            elif true_flag.startswith("--"):
                self.false_flags.append(f"--no-{true_flag[2:]}")

        if set(self.true_flags).intersection(self.false_flags):
            raise ValueError("True and false flags overlap")

        return self.true_flags, self.false_flags

    def matches(self, arg: ParameterArg) -> bool:
        if not isinstance(arg, OptionArg):
            return False

        if arg.value is not None:
            return False

        return arg.flag in self.true_flags or arg.flag in self.false_flags

    def process_arg(self, arg: ParameterArg) -> bool:
        if arg.value is not None:
            raise TypeError("Expected None value")

        if arg.flag in self.true_flags:
            return True

        if arg.flag in self.false_flags:
            return False

        msg = f"Unexpected flag: {arg.flag!r}"
        raise RuntimeError(msg)


class Counter(ParameterType[Number]):
    def __init__(self, value_type: type[Number] = int) -> None:
        self.value_type: type[Number] = value_type
        super().__init__()

    @property
    def name(self) -> str:
        return f"<Counter type={self.value_type.__name__}>"

    @property
    def nargs(self) -> NArgs:
        return IntNArgs(0)

    def matches(self, arg: ParameterArg) -> bool:
        return arg.value is None

    def process_args(self, args: list[ParameterArg]) -> Number:
        return self.value_type(len(args))

    def parse_envvar(self, value: str) -> Number:
        try:
            return self.value_type(value)
        except ValueError:
            self.fail(f"{value!r} is not a valid {self.value_type.__name__}.")

    def validate(self, value: Any) -> TypeGuard[Number]:
        if not isinstance(value, self.value_type):
            self.fail(f"Expected {self.value_type.__name__} value")
        return True


class Optional(TypeAdapter[ValueType | None]):
    @property
    def name(self) -> str:
        return f"Optional[{self.type.name}]"

    def process_config(self, value: object) -> object | None:
        if value is None:
            return None
        return super().process_config(value)

    def validate(self, value: Any) -> TypeGuard[ValueType | None]:
        if value is None:
            return True
        return super().validate(value)


class SequenceType(ParameterType[Sequence[ValueType]]):
    def __init__(
        self,
        item_type: ParameterType[ValueType],
        *,
        nargs: NArgs | NArgsLiteral | None = None,
    ) -> None:
        if nargs is not None and not isinstance(nargs, NArgs):
            nargs = NArgs.from_literal(nargs)

        self.item_type = item_type
        self._nargs = nargs
        super().__init__()

    @property
    def name(self) -> str:
        return f"Sequence[{self.item_type.name}]"

    @property
    def nargs(self) -> NArgs:
        if self._nargs is None:
            return self.item_type.nargs
        return self._nargs

    def get_metavar(self, ctx: Context[Any] | None) -> str | None:
        return self.item_type.get_metavar(ctx)

    def parse_flags(self, flags: Sequence[str]) -> tuple[list[str], list[str]]:
        return self.item_type.parse_flags(flags)

    def format_value(self, value: Sequence[ValueType]) -> str:
        return ", ".join(self.item_type.format_value(item) for item in value)

    def matches(self, arg: ParameterArg) -> bool:
        return self.item_type.matches(arg)

    def process_args(self, args: list[ParameterArg]) -> Sequence[ValueType]:
        result: list[ValueType] = []

        for arg in args:
            value = self.item_type.process_args([arg])
            if isinstance(value, _MISSING_TYPE):
                continue
            result.append(value)

        return result

    def process_config(self, value: object) -> object:
        if not isinstance(value, Sequence):
            return value
        return [self.item_type.process_config(item) for item in value]

    def parse_envvar(self, value: str) -> Sequence[ValueType]:
        return [self.item_type.parse_envvar(s) for s in split_csv(value)]

    def validate(self, value: Any) -> TypeGuard[Sequence[ValueType]]:
        if self.validate_type(value):
            return self.validate_items(value)
        return False

    def validate_type(self, value: Any) -> TypeGuard[Sequence[Any]]:
        if not isinstance(value, Sequence):
            self.fail("Expected Sequence")
        return True

    def validate_items(self, value: Sequence[Any]) -> TypeGuard[Sequence[ValueType]]:
        for item in value:
            self.item_type.validate(item)
        return True


class List(SequenceType[ValueType], ParameterType[list[ValueType]]):
    def _cast(self, value: Sequence[ValueType]) -> list[ValueType]:
        if isinstance(value, list):
            return value
        return list(value)

    @property
    def name(self) -> str:
        return f"list[{self.item_type.name}]"

    def format_value(self, value: Sequence[ValueType]) -> str:
        return f"[{super().format_value(value)}]"

    def process_args(self, args: list[ParameterArg]) -> list[ValueType]:
        return self._cast(super().process_args(args))

    def process_config(self, value: object) -> object:
        value = super().process_config(value)
        if isinstance(value, Sequence):
            return self._cast(value)
        return value

    def parse_envvar(self, value: str) -> list[ValueType]:
        return self._cast(super().parse_envvar(value))

    def validate_type(self, value: Any) -> TypeGuard[list[Any]]:
        if not isinstance(value, list):
            self.fail("Expected list")
        return True

    def validate(self, value: Any) -> TypeGuard[list[ValueType]]:
        return super().validate(value)


class Tuple(SequenceType[ValueType], ParameterType[list[ValueType]]):
    def _cast(self, value: Sequence[ValueType]) -> tuple[ValueType, ...]:
        return tuple(value)

    @property
    def name(self) -> str:
        return f"list[{self.item_type.name}]"

    def format_value(self, value: Sequence[ValueType]) -> str:
        return f"[{super().format_value(value)}]"

    def process_args(self, args: list[ParameterArg]) -> tuple[ValueType, ...]:
        return self._cast(super().process_args(args))

    def process_config(self, value: object) -> object:
        value = super().process_config(value)
        if isinstance(value, Sequence):
            return self._cast(value)
        return value

    def parse_envvar(self, value: str) -> tuple[ValueType, ...]:
        return self._cast(super().parse_envvar(value))

    def validate_type(self, value: Any) -> TypeGuard[tuple[Any, ...]]:
        if not isinstance(value, tuple):
            self.fail("Expected tuple")
        return True

    def validate(self, value: Any) -> TypeGuard[tuple[ValueType, ...]]:
        return super().validate(value)


class Dict(ParameterType[dict[KeyType, ValueType]]):
    @overload
    def __init__(
        self: Dict[str, ValueType],
        value_type: ParameterType[ValueType],
        *,
        nargs: NArgs | NArgsLiteral | None = None,
    ) -> None:
        ...

    @overload
    def __init__(
        self: Dict[KeyType, ValueType],
        value_type: ParameterType[ValueType],
        key_type: ParameterType[KeyType],
        *,
        nargs: NArgs | NArgsLiteral | None = None,
    ) -> None:
        ...

    def __init__(
        self,
        value_type: ParameterType[ValueType],
        key_type: ParameterType[KeyType] | None = None,
        *,
        nargs: NArgs | NArgsLiteral | None = None,
    ) -> None:
        if key_type is None:
            key_type = cast(ParameterType[KeyType], Scalar(str))

        if key_type.nargs != IntNArgs(1):
            raise ValueError("DictType does not support nargs other than 1")

        if value_type.nargs != IntNArgs(1):
            raise ValueError("DictType does not support nargs other than 1")

        if nargs is not None and not isinstance(nargs, NArgs):
            nargs = NArgs.from_literal(nargs)

        self.value_type = value_type
        self.key_type = key_type
        self._nargs = nargs
        super().__init__()

    @property
    def name(self) -> str:
        return f"dict[{self.key_type.name}, {self.value_type.name}]"

    @property
    def nargs(self) -> NArgs:
        if self._nargs is None:
            return IntNArgs(1)
        return self._nargs

    def get_metavar(self, ctx: Context[Any] | None) -> str | None:
        key_metavar = self.key_type.get_metavar(ctx) or "KEY"
        value_metavar = self.value_type.get_metavar(ctx) or "VALUE"
        return f"{key_metavar}={value_metavar}"

    def parse_flags(self, flags: Sequence[str]) -> tuple[list[str], list[str]]:
        return self.value_type.parse_flags(flags)

    def format_value(self, value: dict[KeyType, ValueType]) -> str:
        return ", ".join(
            f"{self.key_type.format_value(k)}={self.value_type.format_value(v)}"
            for k, v in value.items()
        )

    def parse_arg(self, arg: ParameterArg) -> tuple[ParameterArg, ParameterArg] | None:
        if not isinstance(arg, OptionArg):
            return None

        if arg.value is None:
            return None

        key, has_sep, value = arg.value.partition("=")
        if not has_sep:
            return None

        if isinstance(arg, PositionalArg):
            return PositionalArg(value=key), PositionalArg(value=value)

        return (
            OptionArg(flag=arg.flag, value=key),
            OptionArg(flag=arg.flag, value=value),
        )

    def matches(self, arg: ParameterArg) -> bool:
        if arg.value is None:
            return False

        item = self.parse_arg(arg)
        if item is None:
            return False

        return self.key_type.matches(item[0]) and self.value_type.matches(item[0])

    def process_args(self, args: list[ParameterArg]) -> dict[KeyType, ValueType]:
        def _process(arg: ParameterArg) -> tuple[KeyType, ValueType] | None:
            item = self.parse_arg(arg)
            if item is None:
                return None

            key_result = self.key_type.process_args([item[0]])
            if isinstance(key_result, _MISSING_TYPE):
                return None

            value_result = self.value_type.process_args([item[1]])
            if isinstance(value_result, _MISSING_TYPE):
                return None

            return (key_result, value_result)

        return dict(item for arg in args if (item := _process(arg)))

    def process_config(self, value: object) -> object:
        if not isinstance(value, Mapping):
            return value

        def _process(key: object, value: object) -> tuple[object, object]:
            return (
                self.key_type.process_config(key),
                self.value_type.process_config(value),
            )

        return dict(_process(k, v) for k, v in value.items())

    def parse_envvar(self, value: str) -> dict[KeyType, ValueType]:
        def _parse(item: str) -> tuple[KeyType, ValueType]:
            k, has_sep, v = item.partition("=")
            if not has_sep:
                self.fail(f"Expected key=value, got {item!r}")

            return (
                self.key_type.parse_envvar(k),
                self.value_type.parse_envvar(v),
            )

        return dict(_parse(item) for item in split_csv(value))

    def validate(self, value: Any) -> TypeGuard[dict[KeyType, ValueType]]:
        if not isinstance(value, dict):
            self.fail("Expected dict")

        for key, item in value.items():
            self.key_type.validate(key)
            self.value_type.validate(item)

        return True


class Path(Scalar[pathlib.Path]):
    @property
    def name(self) -> str:
        return "path"

    def __init__(
        self,
        *,
        allow_dash: bool = False,
        allow_overwrite: bool = True,
        dir_okay: bool = True,
        executable: bool = False,
        exists: bool = False,
        file_okay: bool = True,
        readable: bool = False,
        resolve_path: bool = False,
        writable: bool = False,
    ) -> None:
        super().__init__(pathlib.Path, allow_overwrite)

        self.allow_dash = allow_dash
        self.dir_okay = dir_okay
        self.executable = executable
        self.exists = exists
        self.file_okay = file_okay
        self.readable = readable
        self.resolve_path = resolve_path
        self.writable = writable

    def parse(self, value: str) -> pathlib.Path:
        result = super().parse(value)

        if self.resolve_path and value != "-":
            result = result.resolve()

        return result

    def process_config(self, value: object) -> object:
        if not isinstance(value, str):
            return value
        return self.parse(value)

    def validate(self, value: Any) -> TypeGuard[pathlib.Path]:
        if not isinstance(value, pathlib.Path):
            self.fail("Expected path value.")

        if not self.allow_dash and value == pathlib.Path("-"):
            self.fail("'-' is not allowed.")

        if self.exists and not value.exists():
            self.fail("Path must exist.")

        if not self.file_okay and value.is_file():
            self.fail("Path must not be a file.")

        if not self.dir_okay and value.is_dir():
            self.fail("Path must not be a directory.")

        if self.readable and not os.access(value, os.R_OK):
            self.fail("Path must be readable.")

        if self.writable and not os.access(value, os.W_OK):
            self.fail("Path must be writable.")

        if self.executable and not os.access(value, os.X_OK):
            self.fail("Path must be executable.")

        return True


class Validator(TypeAdapter[ValueType]):
    def __init__(
        self,
        type: ParameterType[ValueType],
        validator: Callable[[ValueType], bool],
    ) -> None:
        self.validator = validator
        super().__init__(type)

    @property
    def name(self) -> str:
        return f"<Validator type={self.type.name} validator={self.validator!r}>"

    def validate(self, value: Any) -> TypeGuard[ValueType]:
        return self.type.validate(value) and self.validator(value)


class ChoicesValidator(TypeAdapter[ValueType]):
    def __init__(
        self, type: ParameterType[ValueType], choices: Sequence[ValueType]
    ) -> None:
        self.choices = list(choices)
        super().__init__(type)

    @property
    def name(self) -> str:
        choices = "|".join(str(choice) for choice in self.choices)
        return f"<ChoicesValidator type={self.type.name} choices={choices!r}>"

    def get_metavar(self, ctx: Context[Any] | None) -> str | None:
        return "|".join(self.type.format_value(choice) for choice in self.choices)

    def validate(self, value: Any) -> TypeGuard[ValueType]:
        self.type.validate(value)

        if value not in self.choices:
            choices = ", ".join(str(choice) for choice in self.choices)
            self.fail(f"{value!r} is not one of {choices}.")

        return True


class RangeValidator(TypeAdapter[NumberLike]):
    def __init__(
        self,
        type: ParameterType[NumberLike],
        cast: Callable[[int | float | str], NumberLike],
        min: int | float | None = None,
        max: int | float | None = None,
        min_open: bool = False,
        max_open: bool = False,
        clamp: bool = False,
    ) -> None:
        self.cast = cast
        self.min = min
        self.max = max
        self.min_open = min_open
        self.max_open = max_open
        self.clamp = clamp
        super().__init__(type)

    @property
    def name(self) -> str:
        return (
            f"<NumberRangeValidator type={self.type.name} "
            "min={self.min} max={self.max} "
            "min_open={self.min_open} max_open={self.max_open} "
            "clamp={self.clamp}>"
        )

    def lt_min(self, value: NumberLike) -> bool:
        if self.min is None:
            return False
        lt = operator.le if self.min_open else operator.lt
        return bool(lt(value, self.min))

    def gt_max(self, value: NumberLike) -> bool:
        if self.max is None:
            return False
        gt = operator.ge if self.max_open else operator.gt
        return bool(gt(value, self.max))

    def maybe_clamp(self, value: NumberLike) -> NumberLike:
        if not self.clamp:
            return value

        if self.min is not None:
            value = self.cast(max(self.min, value))

        if self.max is not None:
            value = self.cast(min(self.max, value))

        return value

    def process_args(self, args: list[ParameterArg]) -> NumberLike | _MISSING_TYPE:
        result = self.type.process_args(args)
        if isinstance(result, _MISSING_TYPE):
            return MISSING
        return self.maybe_clamp(result)

    def parse_envvar(self, value: str) -> NumberLike:
        result = self.type.parse_envvar(value)
        return self.maybe_clamp(result)

    def validate(self, value: Any) -> TypeGuard[NumberLike]:
        if self.type.validate(value):
            if self.lt_min(value):
                self.fail(f"{value!r} is smaller than the minimum value of {self.min}.")

            if self.gt_max(value):
                self.fail(f"{value!r} is greater than the maximum value of {self.max}.")
            return True
        return False


class LengthValidator(TypeAdapter[SizedValueType]):
    def __init__(
        self,
        type: ParameterType[SizedValueType],
        min_length: int | None = None,
        max_length: int | None = None,
    ) -> None:
        self.min_length = min_length
        self.max_length = max_length
        super().__init__(type)

    @property
    def name(self) -> str:
        return (
            f"<LengthValidator type={self.type.name} "
            "min_length={self.min_length} max_length={self.max_length}>"
        )

    @property
    def nargs(self) -> NArgs:
        child_nargs: NArgs = self.type.nargs

        if not isinstance(child_nargs, VariadicNArgs):
            return child_nargs

        min_values = child_nargs.min_values
        if self.min_length is not None:
            min_values = max(min_values, self.min_length)

        max_values = child_nargs.max_values
        if self.max_length is not None:
            if max_values is None:
                max_values = self.max_length
            else:
                max_values = min(max_values, self.max_length)

        return VariadicNArgs(
            value=child_nargs.value,
            min_values=min_values,
            max_values=max_values,
            greedy=child_nargs.greedy,
        )

    def validate(self, value: Any) -> TypeGuard[SizedValueType]:
        if self.type.validate(value):
            if self.min_length is not None and len(value) < self.min_length:
                self.fail(
                    f"{value!r} is shorter than the minimum length of "
                    f"{self.min_length}."
                )

            if self.max_length is not None and len(value) > self.max_length:
                self.fail(
                    f"{value!r} is longer than the maximum length of "
                    f"{self.max_length}."
                )

            return True
        return False


class GreedyAdaptor(TypeAdapter[ValueType,]):
    def __init__(self, type: ParameterType[ValueType,], greedy: bool = True) -> None:
        self.greedy = greedy
        super().__init__(type)

    @property
    def name(self) -> str:
        return f"<GreedyAdaptor type={self.type.name} greedy={self.greedy}>"

    @property
    def nargs(self) -> NArgs:
        child_nargs: NArgs = self.type.nargs

        if not isinstance(child_nargs, VariadicNArgs):
            return child_nargs

        return VariadicNArgs(
            value=child_nargs.value,
            min_values=child_nargs.min_values,
            max_values=child_nargs.max_values,
            greedy=self.greedy,
        )


class HelpFlag(ParameterType[NoReturn]):
    @property
    def name(self) -> str:
        return "<Help>"

    @property
    def nargs(self) -> NArgs:
        return IntNArgs(0)

    def matches(self, arg: ParameterArg) -> bool:
        return arg.value is None

    def process_args(self, args: list[ParameterArg]) -> NoReturn | _MISSING_TYPE:
        if not args:
            return MISSING
        raise Help()

    def parse_envvar(self, value: str) -> NoReturn:
        raise Help()

    def validate(self, value: Any) -> TypeGuard[NoReturn]:
        raise Help()


# TODO: add types:
# - file
# - url
# - uuid
# - enum

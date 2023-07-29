from __future__ import annotations

import abc
import dataclasses
import functools
import itertools
from collections.abc import Iterator, Sequence
from difflib import get_close_matches
from typing import Any, Generic, Literal, NoReturn, TypeVar

from tabb.context import Context
from tabb.exceptions import UnexpetedParameter
from tabb.nargs import IntNArgs, NArgs, VariadicNArgs
from tabb.parameter import (
    ArgumentParameter,
    DependsParameter,
    OptionParameter,
    ParameterValue,
    ParserParameter,
)
from tabb.parameter.types import OptionArg, ParameterArg, PositionalArg
from tabb.utils import to_snake

T = TypeVar("T")

CapturedArg = tuple[ParserParameter[Any], ParameterArg]


class MatchError(Exception):
    pass


class ImmutableStackIterator(Iterator[T]):
    def __init__(self, stack: Stack[T]) -> None:
        self.stack = stack

    def __next__(self) -> T:
        try:
            item, self.stack = self.stack.pop()
        except IndexError:
            raise StopIteration from None
        return item


@dataclasses.dataclass(slots=True, frozen=True)
class Stack(abc.ABC, Generic[T]):
    @staticmethod
    def from_sequence(items: Sequence[T]) -> Stack[T]:
        stack: Stack[T] = EmptyStack()

        for item in reversed(items):
            stack = stack.push(item)

        return stack

    @abc.abstractmethod
    def peek(self) -> T:
        ...

    @abc.abstractmethod
    def pop(self) -> tuple[T, Stack[T]]:
        ...

    def push(self, item: T) -> StackNode[T]:
        return StackNode(item, self)

    @abc.abstractmethod
    def __len__(self) -> int:
        ...

    @abc.abstractmethod
    def __bool__(self) -> bool:
        ...

    def __iter__(self) -> ImmutableStackIterator[T]:
        return ImmutableStackIterator(self)


@dataclasses.dataclass(slots=True, frozen=True)
class EmptyStack(Stack[T]):
    def peek(self) -> NoReturn:
        raise IndexError("Stack is empty")

    def pop(self) -> NoReturn:
        raise IndexError("Stack is empty")

    def __len__(self) -> int:
        return 0

    def __bool__(self) -> Literal[False]:
        return False

    def __repr__(self) -> str:
        return "Stack([])"


@dataclasses.dataclass(slots=True, frozen=True)
class StackNode(Stack[T]):
    head: T
    tail: Stack[T]

    def peek(self) -> T:
        return self.head

    def pop(self) -> tuple[T, Stack[T]]:
        return self.head, self.tail

    @functools.cache  # noqa: B019
    def __len__(self) -> int:
        return len(self.tail) + 1

    def __bool__(self) -> Literal[True]:
        return True

    def __repr__(self) -> str:
        return f"Stack({list(self)!r})"


@dataclasses.dataclass(slots=True)
class StackFrame:
    param: ParserParameter[Any]
    nargs: NArgs
    flag: str | None = None
    value: str | None = None
    has_value: bool = False


@dataclasses.dataclass(slots=True)
class State:
    args: Stack[str]
    positional: Stack[ArgumentParameter[Any]]
    parse_options: bool = True
    unused_args: Stack[str] = dataclasses.field(default_factory=EmptyStack)
    captured_args: Stack[CapturedArg] = dataclasses.field(default_factory=EmptyStack)
    stack: Stack[StackFrame] = dataclasses.field(default_factory=EmptyStack)

    def copy(self) -> State:
        return State(
            args=self.args,
            positional=self.positional,
            parse_options=self.parse_options,
            unused_args=self.unused_args,
            stack=self.stack,
            captured_args=self.captured_args,
        )

    def push_arg(self, arg: str) -> None:
        self.args = self.args.push(arg)

    def pop_arg(self) -> str:
        arg, self.args = self.args.pop()
        return arg

    def pop_positional(self) -> ArgumentParameter[Any]:
        param, self.positional = self.positional.pop()
        return param

    def push_unused_arg(self, arg: str) -> None:
        self.unused_args = self.unused_args.push(arg)

    def reset_unused_args(self) -> None:
        while self.unused_args:
            arg, self.unused_args = self.unused_args.pop()
            self.args = self.args.push(arg)

    def push_frame(self, frame: StackFrame) -> None:
        self.stack = self.stack.push(frame)

    def pop_frame(self) -> StackFrame:
        frame, self.stack = self.stack.pop()
        return frame

    def capture_arg(self, param: ParserParameter[Any], arg: ParameterArg) -> None:
        self.captured_args = self.captured_args.push((param, arg))

    def get_captured_args(self) -> dict[ParserParameter[Any], list[ParameterArg]]:
        args: dict[ParserParameter[Any], list[Any]] = {}

        for param, arg in self.captured_args:
            try:
                args[param].append(arg)
            except KeyError:
                args[param] = [arg]

        # Reverse the order of the values
        return {param: args[param][::-1] for param in args}

    def loss(self) -> tuple[int, int]:
        return len(self.positional), len(self.args)


def is_long_flag(arg: str) -> bool:
    return arg.startswith("--") and to_snake(arg[2:]).isidentifier()


def is_short_flag(arg: str) -> bool:
    return arg.startswith("-") and len(arg) == 2 and arg[1].isalpha()


def is_short_arg(arg: str) -> bool:
    return arg.startswith("-") and len(arg) > 1 and arg[1:].isalpha()


def is_long_arg(arg: str) -> bool:
    return is_long_flag(arg)


def is_positional_arg(arg: str) -> bool:
    return not (is_short_arg(arg) or is_long_arg(arg))


class Parser:
    def __init__(self, params: list[ParserParameter[Any]]) -> None:
        self.short_flags: dict[str, OptionParameter[Any]] = {}
        self.long_flags: dict[str, OptionParameter[Any]] = {}
        self.positional: list[ArgumentParameter[Any]] = []
        self.params: list[ParserParameter[Any]] = []
        self.add_params(params)

    def add_params(self, params: list[ParserParameter[Any]]) -> None:
        for param in params:
            self.add_param(param)

    def add_param(self, param: ParserParameter[Any]) -> None:
        if isinstance(param, ArgumentParameter):
            self.positional.append(param)

        elif isinstance(param, OptionParameter):
            for flag in itertools.chain(param.flags, param.secondary_flags):
                if is_short_flag(flag):
                    if flag in self.short_flags:
                        msg = f"Duplicate short flag: {flag}"
                        raise ValueError(msg)
                    self.short_flags[flag] = param

                elif is_long_flag(flag):
                    if flag in self.long_flags:
                        msg = f"Duplicate long flag: {flag}"
                        raise ValueError(msg)
                    self.long_flags[flag] = param

                else:
                    msg = f"Invalid flag: {flag}"
                    raise ValueError(msg)

        elif isinstance(param, DependsParameter):
            pass

        else:
            msg = f"Unsupported parameter type: {type(param)}"
            raise TypeError(msg)

        self.params.append(param)

    def parse_args(
        self,
        ctx: Context[Any],
        *,
        allow_interspersed_args: bool = True,
        raise_on_unexpected: bool = True,
    ) -> tuple[list[ParameterValue[Any]], list[str]]:
        state = self._parse_args(
            ctx,
            allow_interspersed_args=allow_interspersed_args,
        )

        captured_args = state.get_captured_args()
        values: list[ParameterValue[Any]] = []

        for param in self.params:
            value = param.process_args(ctx, captured_args.get(param, []))
            values.append(value)

        if (state.args or state.unused_args) and raise_on_unexpected:
            if not state.args:
                state.reset_unused_args()
            possibilities = self._get_possible_matches(ctx, state)
            raise UnexpetedParameter(state.args.peek(), possibilities=possibilities)

        state.reset_unused_args()
        return values, list(state.args)

    def _get_possible_matches(self, ctx: Context[Any], state: State) -> list[str]:
        flag, _, _ = state.args.peek().partition("=")
        if is_short_flag(flag):
            return []

        if is_long_flag(flag):
            return get_close_matches(flag, self.long_flags)

        if state.positional:
            return [state.positional.peek().get_metavar(ctx)]

        return []

    def _parse_args(
        self,
        ctx: Context[Any],
        *,
        allow_interspersed_args: bool = True,
    ) -> State:
        best_match: State = State(
            Stack.from_sequence(ctx.args),
            Stack.from_sequence(self.positional),
        )

        threads = [best_match]

        while threads:
            state = threads.pop()

            try:
                self._parse_thread(
                    ctx, threads, state, allow_interspersed_args=allow_interspersed_args
                )

            except MatchError:
                if state.loss() < best_match.loss():
                    best_match = state
                continue

            except UnexpetedParameter as error:
                state.push_arg(error.arg)

            return state

        return best_match

    def _parse_thread(
        self,
        ctx: Context[Any],
        threads: list[State],
        state: State,
        *,
        allow_interspersed_args: bool,
    ) -> None:
        while True:
            while state.stack:
                frame = state.pop_frame()
                self._parse_frame(ctx, threads, state, frame)

            if state.parse_options:
                self._parse_option(
                    ctx=ctx,
                    threads=threads,
                    state=state,
                    allow_interspersed_args=allow_interspersed_args,
                )

            elif state.positional:
                state.reset_unused_args()
                self._parse_positional(ctx=ctx, threads=threads, state=state)

            else:
                break

    def _push_frame(
        self,
        ctx: Context[Any],
        threads: list[State],
        state: State,
        param: ParserParameter[Any],
        nargs: NArgs | None,
        flag: str | None = None,
        value: str | None = None,
        has_value: bool = False,
    ) -> None:
        if nargs is None:
            return

        if isinstance(nargs, VariadicNArgs):
            if nargs.min_values == 0:
                if nargs.greedy:
                    # Try without in next thread
                    threads.append(state.copy())
                else:
                    # Move non-greedy variadics to the next thread
                    state = state.copy()
                    threads.append(state)

        state.push_frame(
            StackFrame(
                param=param,
                nargs=nargs,
                flag=flag,
                value=value,
                has_value=has_value,
            )
        )

    def _parse_frame(
        self,
        ctx: Context[Any],
        threads: list[State],
        state: State,
        frame: StackFrame,
    ) -> None:
        if isinstance(frame.nargs, IntNArgs):
            return self._parse_int_frame(ctx, threads, state, frame, frame.nargs)

        if isinstance(frame.nargs, VariadicNArgs):
            return self._parse_variadic_frame(ctx, threads, state, frame, frame.nargs)

        msg = f"Unsupported nargs: {frame.nargs!r}"
        raise TypeError(msg)

    def _parse_int_frame(
        self,
        ctx: Context[Any],
        threads: list[State],
        state: State,
        frame: StackFrame,
        nargs: IntNArgs,
    ) -> None:
        arg = self._get_int_frame_arg(ctx, state, frame, nargs)

        if not frame.param.matches(ctx, arg):
            raise MatchError()

        state.capture_arg(frame.param, arg)

        self._push_frame(
            ctx=ctx,
            threads=threads,
            state=state,
            param=frame.param,
            nargs=nargs.decrement(),
            flag=frame.flag,
        )

    def _get_int_frame_arg(
        self,
        ctx: Context[Any],
        state: State,
        frame: StackFrame,
        nargs: IntNArgs,
    ) -> ParameterArg:
        if frame.flag is not None:
            if nargs.value == 0 and frame.value is None:
                return OptionArg(flag=frame.flag, value=None)

            if nargs.value == 1 and frame.value is not None:
                return OptionArg(flag=frame.flag, value=frame.value)

        if frame.has_value:
            raise MatchError()

        try:
            value = state.pop_arg()
        except IndexError:
            raise MatchError() from None

        if frame.flag is not None:
            return OptionArg(flag=frame.flag, value=value)

        return PositionalArg(value=value)

    def _parse_variadic_frame(
        self,
        ctx: Context[Any],
        threads: list[State],
        state: State,
        frame: StackFrame,
        nargs: VariadicNArgs,
    ) -> None:
        child_frame = StackFrame(
            param=frame.param,
            nargs=nargs.value,
            flag=frame.flag,
        )

        self._parse_frame(ctx, threads, state, child_frame)

        self._push_frame(
            ctx=ctx,
            threads=threads,
            state=state,
            param=frame.param,
            nargs=nargs.decrement(),
            flag=frame.flag,
        )

    def _parse_option(
        self,
        ctx: Context[Any],
        threads: list[State],
        state: State,
        *,
        allow_interspersed_args: bool,
    ) -> None:
        if not state.args:
            state.parse_options = False
            return

        arg = state.pop_arg()
        if arg == "--":
            state.parse_options = False
            return

        value: str | None
        flag, has_value, value = arg.partition("=")

        if not has_value:
            value = None

        if is_short_arg(flag):
            self._parse_short(ctx, threads, state, arg, flag, value)

        elif is_long_arg(flag):
            self._parse_long(ctx, threads, state, arg, flag, value)

        elif allow_interspersed_args:
            state.push_unused_arg(arg)
        else:
            state.parse_options = False
            state.push_arg(arg)

    def _parse_short(
        self,
        ctx: Context[Any],
        threads: list[State],
        state: State,
        arg: str,
        flag: str,
        value: str | None,
    ) -> None:
        for index, short_name in enumerate(reversed(flag[1:])):
            short_flag = f"-{short_name}"

            try:
                param = self.short_flags[short_flag]
            except KeyError:
                raise UnexpetedParameter(arg) from None

            self._push_frame(
                ctx=ctx,
                threads=threads,
                state=state,
                param=param,
                nargs=param.nargs,
                flag=short_flag,
                value=value if index == 0 else None,
                has_value=index != 0 or value is not None,
            )

    def _parse_long(
        self,
        ctx: Context[Any],
        threads: list[State],
        state: State,
        arg: str,
        flag: str,
        value: str | None,
    ) -> None:
        try:
            param = self.long_flags[flag]
        except KeyError:
            raise UnexpetedParameter(arg) from None

        self._push_frame(
            ctx=ctx,
            threads=threads,
            state=state,
            param=param,
            nargs=param.nargs,
            flag=flag,
            value=value,
            has_value=value is not None,
        )

    def _parse_positional(
        self, ctx: Context[Any], threads: list[State], state: State
    ) -> None:
        param = state.pop_positional()
        self._push_frame(
            ctx=ctx,
            threads=threads,
            state=state,
            param=param,
            nargs=param.nargs,
        )


def parse_args(
    ctx: Context[Any],
    params: list[ParserParameter[Any]],
    *,
    allow_interspersed_args: bool = True,
    raise_on_unexpected: bool = True,
) -> tuple[list[ParameterValue[Any]], list[str]]:
    parser = Parser(params)
    return parser.parse_args(
        ctx,
        allow_interspersed_args=allow_interspersed_args,
        raise_on_unexpected=raise_on_unexpected,
    )

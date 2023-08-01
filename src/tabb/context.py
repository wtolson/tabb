from __future__ import annotations

from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager, ExitStack
from threading import local
from types import TracebackType
from typing import (
    TYPE_CHECKING,
    Any,
    Generic,
    Literal,
    NoReturn,
    ParamSpec,
    TypeVar,
    cast,
    overload,
)

from tabb.config import Config
from tabb.exceptions import Abort, Exit, UsageError
from tabb.formatter import HelpFormatter
from tabb.utils import to_kebab, to_snake

if TYPE_CHECKING:
    from tabb.base import BaseCommand
    from tabb.parameter import Parameter, ParameterValue


T = TypeVar("T")
V = TypeVar("V")
P = ParamSpec("P")


class DependencyCache:
    def __init__(self) -> None:
        self.callbacks: dict[Callable[..., Any], Callable[[Context[Any]], Any]] = {}
        self.values: dict[Callable[[Context[Any]], Any], Any] = {}


_local = local()


@overload
def get_current_context(silent: Literal[False] = False) -> Context[Any]:
    ...


@overload
def get_current_context(silent: bool = ...) -> Context[Any] | None:
    ...


def get_current_context(silent: bool = False) -> Context[Any] | None:
    try:
        return cast(Context[Any], _local.stack[-1])
    except (AttributeError, IndexError) as error:
        if not silent:
            raise RuntimeError("There is no active click context.") from error

    return None


def push_context(ctx: Context[Any]) -> None:
    """Pushes a new context to the current stack."""
    _local.__dict__.setdefault("stack", []).append(ctx)


def pop_context() -> None:
    """Removes the top level from the stack."""
    _local.stack.pop()


class Context(Generic[T]):
    def __init__(
        self,
        name: str,
        args: list[str],
        environ: Mapping[str, str],
        config: Mapping[str, object],
        command: BaseCommand[T],
        parent: Context[Any] | None = None,
        auto_config_prefix: str | None = None,
        auto_envvar_prefix: str | None = None,
    ) -> None:
        self.name = name
        self.args = args
        self.environ = environ
        self.config = Config(config)
        self.command = command
        self.parent = parent
        self.values: dict[Parameter[Any], ParameterValue[Any]] = {}

        if auto_config_prefix is None:
            if parent is not None and parent.auto_config_prefix is not None:
                auto_config_prefix = f"{parent.auto_config_prefix}.{self.name.lower()}"
        else:
            auto_config_prefix = auto_config_prefix.lower()

        if auto_config_prefix is not None:
            auto_config_prefix = to_kebab(auto_config_prefix)

        self.auto_config_prefix: str | None = auto_config_prefix

        if auto_envvar_prefix is None:
            if parent is not None and parent.auto_envvar_prefix is not None:
                auto_envvar_prefix = f"{parent.auto_envvar_prefix}_{self.name.upper()}"
        else:
            auto_envvar_prefix = auto_envvar_prefix.upper()

        if auto_envvar_prefix is not None:
            auto_envvar_prefix = to_snake(auto_envvar_prefix)

        self.auto_envvar_prefix: str | None = auto_envvar_prefix

        if parent is None:
            self.dependencies = DependencyCache()
        else:
            self.dependencies = parent.dependencies

        self._depth = 0
        self._exit_stack = ExitStack()

    @property
    def command_path(self) -> str:
        if self.parent is None:
            return self.name

        path: list[str] = [self.parent.command_path]

        for param in self.parent.command.get_params(self).get_parser_params():
            path.extend(param.get_usage_pieces(self))

        path.append(self.name)
        return " ".join(path)

    def make_formatter(self) -> HelpFormatter:
        return HelpFormatter()

    def get_help(self) -> str:
        return self.command.get_help(self)

    def get_usage(self) -> str:
        return self.command.get_usage(self)

    def abort(self) -> NoReturn:
        raise Abort()

    def exit(self, code: int = 0) -> NoReturn:
        raise Exit(code)

    def fail(self, message: str) -> NoReturn:
        raise UsageError(message, self)

    def with_resource(self, context_manager: AbstractContextManager[V]) -> V:
        return self._exit_stack.enter_context(context_manager)

    def call_on_close(self, fn: Callable[P, V]) -> Callable[P, V]:
        return self._exit_stack.callback(fn)

    def close(self) -> None:
        self._exit_stack.close()
        # In case the context is reused, create a new exit stack.
        self._exit_stack = ExitStack()

    def __enter__(self) -> Context[T]:
        self._depth += 1
        push_context(self)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self._depth = min(self._depth - 1, 0)
        if self._depth == 0:
            self.close()
        pop_context()

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING, Any, Generic, NoReturn, TypeVar

from tabb.config import Config
from tabb.exceptions import Abort, Exit, UsageError
from tabb.formatter import HelpFormatter
from tabb.utils import to_kebab, to_snake

if TYPE_CHECKING:
    from tabb.base import BaseCommand
    from tabb.parameter import Parameter, ParameterValue


T = TypeVar("T")


class DependencyCache:
    def __init__(self) -> None:
        self.callbacks: dict[Callable[..., Any], Callable[[Context[Any]], Any]] = {}
        self.values: dict[Callable[[Context[Any]], Any], Any] = {}


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

    def exit(self, code: int = 0) -> NoReturn:  # noqa: A003
        raise Exit(code)

    def fail(self, message: str) -> NoReturn:
        raise UsageError(message, self)

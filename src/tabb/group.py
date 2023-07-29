from __future__ import annotations

import collections.abc
import inspect
from collections.abc import Callable, Mapping, Sequence
from difflib import get_close_matches
from typing import (
    Any,
    ParamSpec,
    TypeVar,
    overload,
)

from tabb.base import BaseCommand
from tabb.callback import create_callback
from tabb.command import Command
from tabb.context import Context
from tabb.formatter import HelpFormatter
from tabb.parameter import ParameterGroup
from tabb.utils import to_kebab

P = ParamSpec("P")
T = TypeVar("T")


class Group(BaseCommand[T]):
    allow_interspersed_args: bool = False

    def __init__(
        self,
        callback: str | Callable[..., Any] | None = None,
        commands: Mapping[str, BaseCommand[T]] | Sequence[BaseCommand[T]] | None = None,
        *,
        add_help_option: bool = True,
        deprecated: bool = False,
        epilog: str | None = None,
        help: str | None = None,
        hidden: bool = False,
        import_dependencies: str | None = None,
        name: str | None = None,
        no_args_is_help: bool = True,
        options_metavar: str | None = "[OPTIONS]",
        package: str | None = None,
        short_help: str | None = None,
        subcommand_metavar: str = "COMMAND [ARGS]...",
    ) -> None:
        self._callback = create_callback(callback) if callback else None
        self.import_dependencies = import_dependencies
        self.package = package
        self.subcommand_metavar = subcommand_metavar
        self.commands: dict[str, BaseCommand[T]] = {}

        if commands is not None:
            self.add_commands(commands)

        super().__init__(
            add_help_option=add_help_option,
            deprecated=deprecated,
            epilog=epilog,
            help=help,
            hidden=hidden,
            name=name,
            no_args_is_help=no_args_is_help,
            options_metavar=options_metavar,
            short_help=short_help,
        )

    def get_name(self) -> str | None:
        name = super().get_name()
        if name:
            return name

        if self._callback:
            return to_kebab(self._callback.name)

        return None

    def get_help_text(self) -> str:
        help_text = super().get_help_text()
        if help_text:
            return help_text

        if self._callback:
            return inspect.getdoc(self._callback.fn) or ""

        return ""

    def collect_usage_pieces(self, ctx: Context[T]) -> list[str]:
        rv = super().collect_usage_pieces(ctx)
        rv.append(self.subcommand_metavar)
        return rv

    def format_options(self, ctx: Context[T], formatter: HelpFormatter) -> None:
        super().format_options(ctx, formatter)
        self.format_commands(ctx, formatter)

    def format_commands(self, ctx: Context[T], formatter: HelpFormatter) -> None:
        """Extra format methods for multi methods that adds all the commands
        after the options.
        """
        commands = {name: cmd for name, cmd in self.commands.items() if not cmd.hidden}
        if not commands:
            return

        limit = formatter.width - 6 - max(len(name) for name in commands)

        rows: list[tuple[str, str]] = []

        for name, cmd in commands.items():
            rows.append((name, cmd.get_short_help_text(limit)))

        with formatter.section("Commands"):
            formatter.write_dl(rows)

    def add_command(
        self, command: BaseCommand[Any], *, name: str | None = None
    ) -> None:
        if name is None:
            name = command.get_name()

        if name is None:
            raise ValueError("Command must have a name")

        self.commands[name] = command

    def add_commands(
        self, commands: Mapping[str, BaseCommand[Any]] | Sequence[BaseCommand[Any]]
    ) -> None:
        if isinstance(commands, collections.abc.Sequence):
            for command in commands:
                self.add_command(command)

        else:
            for name, command in commands.items():
                self.add_command(command, name=name)

    @overload
    def command(self, callback: Callable[P, T], /) -> Command[P, T]:
        ...

    @overload
    def command(
        self,
        name: str | None = None,
        *,
        add_help_option: bool = True,
        deprecated: bool = False,
        epilog: str | None = None,
        help: str | None = None,
        hidden: bool = False,
        import_dependencies: str | None = None,
        options_metavar: str | None = "[OPTIONS]",
        package: str | None = None,
        short_help: str | None = None,
    ) -> Callable[[Callable[P, T]], Command[P, T]]:
        ...

    def command(
        self,
        name: Callable[P, T] | str | None = None,
        **kwargs: Any,
    ) -> Command[P, T] | Callable[[Callable[P, T]], Command[P, T]]:
        if callable(name):
            command = Command(name)
            self.add_command(command)
            return command

        def decorator(callback: Callable[P, T]) -> Command[P, T]:
            if isinstance(callback, Command):
                raise TypeError("Attempted to convert a callback into a command twice.")

            command = Command(callback, name=name, **kwargs)
            self.add_command(command)
            return command

        return decorator

    @overload
    def group(self, callback: Callable[..., Any], /) -> Group[T]:
        ...

    @overload
    def group(
        self,
        name: str | None = None,
        *,
        add_help_option: bool = True,
        deprecated: bool = False,
        epilog: str | None = None,
        help: str | None = None,
        hidden: bool = False,
        import_dependencies: str | None = None,
        options_metavar: str | None = "[OPTIONS]",
        package: str | None = None,
        short_help: str | None = None,
    ) -> Callable[[Callable[..., Any]], Group[T]]:
        ...

    def group(
        self,
        name: Callable[..., Any] | str | None = None,
        **kwargs: Any,
    ) -> Group[T] | Callable[[Callable[..., Any]], Group[T]]:
        if callable(name):
            group: Group[T] = Group(name)
            self.add_command(group)
            return group

        def decorator(callback: Callable[..., Any]) -> Group[T]:
            if isinstance(callback, Group):
                raise TypeError("Attempted to convert a callback into a group twice.")

            group: Group[T] = Group(callback, name=name, **kwargs)
            self.add_command(group)
            return group

        return decorator

    def get_params(self, ctx: Context[T]) -> ParameterGroup:
        params = super().get_params(ctx)
        if self._callback is not None:
            params.add_params(self._callback.get_params(ctx))
        return params

    def invoke(self, ctx: Context[T]) -> T:
        args = self.parse_args(ctx, raise_on_unexpected=False)

        self.invoke_callbacks(ctx)

        if self._callback is not None:
            self._callback(ctx)

        try:
            command_name, args = args[0], args[1:]
        except IndexError:
            ctx.fail("Missing command.")

        try:
            command = self.commands[command_name]
        except KeyError:
            msg = f"Unknown command {command_name!r}."
            possibilities = get_close_matches(command_name, self.commands)

            if len(possibilities) == 1:
                msg += f" Did you mean {possibilities[0]!r}?"
            elif possibilities:
                options = ", ".join(sorted(possibilities))
                msg += f" (Possible options: {options})"

            ctx.fail(msg)

        sub_ctx = command.make_context(command_name, args, ctx.environ, ctx.config, ctx)
        return command.invoke(sub_ctx)

from __future__ import annotations

import abc
import errno
import inspect
import os
import sys
from collections.abc import Callable, Mapping
from typing import (
    Any,
    Generic,
    NoReturn,
    ParamSpec,
    TypeVar,
)

from tabb.callback import Callback, create_callback
from tabb.context import Context
from tabb.exceptions import (
    Abort,
    TabbError,
    Exit,
    Help,
)
from tabb.formatter import HelpFormatter, make_default_short_help
from tabb.parameter import OptionParameter, ParameterGroup
from tabb.parameter.types import HelpFlag
from tabb.parser import parse_args
from tabb.utils import detect_program_name, pacify_flush

T = TypeVar("T")

CallbackParms = ParamSpec("CallbackParms")
CallbackResult = TypeVar("CallbackResult")


class BaseCommand(abc.ABC, Generic[T]):
    allow_interspersed_args: bool = True

    def __init__(
        self,
        *,
        add_help_option: bool,
        deprecated: bool,
        epilog: str | None,
        help: str | None,
        hidden: bool,
        name: str | None,
        no_args_is_help: bool,
        options_metavar: str | None,
        short_help: str | None,
    ) -> None:
        self.add_help_option = add_help_option
        self.deprecated = deprecated
        self.epilog = epilog
        self.help = help
        self.hidden = hidden
        self.name = name
        self.no_args_is_help = no_args_is_help
        self.options_metavar = options_metavar
        self.short_help = short_help
        self.callbacks: list[Callback[..., Any]] = []

    @abc.abstractmethod
    def invoke(self, ctx: Context[T]) -> T:
        raise NotImplementedError

    def make_context(
        self,
        name: str,
        args: list[str],
        environ: Mapping[str, str],
        config: Mapping[str, object],
        parent: Context[T] | None = None,
        *,
        auto_config_prefix: str | None = None,
        auto_envvar_prefix: str | None = None,
    ) -> Context[T]:
        return Context(
            name=name,
            args=args,
            environ=environ,
            config=config,
            command=self,
            parent=parent,
            auto_config_prefix=auto_config_prefix,
            auto_envvar_prefix=auto_envvar_prefix,
        )

    def get_name(self) -> str | None:
        return self.name

    def get_usage(self, ctx: Context[T]) -> str:
        """Formats the usage line into a string and returns it."""
        formatter = ctx.make_formatter()
        self.format_usage(ctx, formatter)
        return formatter.getvalue().rstrip("\n")

    def get_help(self, ctx: Context[T]) -> str:
        """Formats the help into a string and returns it."""
        formatter = ctx.make_formatter()
        self.format_help(ctx, formatter)
        return formatter.getvalue().rstrip("\n")

    def get_help_text(self) -> str:
        if self.help:
            return inspect.cleandoc(self.help)
        return ""

    def get_short_help_text(self, limit: int = 45) -> str:
        if self.short_help:
            text = self.short_help
        else:
            text = make_default_short_help(self.get_help_text(), limit)

        if self.deprecated:
            text = f"(Deprecated) {text}"

        return text.strip()

    def get_help_option(self, ctx: Context[T]) -> OptionParameter[NoReturn] | None:
        """Returns the help option object."""
        if not self.add_help_option:
            return None

        help_flags = self.get_help_option_names(ctx)
        if not help_flags:
            return None

        return OptionParameter(
            name="help",
            kind=OptionParameter.POSITIONAL,
            flags=help_flags,
            type=HelpFlag(),
            help="Show this message and exit.",
            required=False,
        )

    def get_help_option_names(self, ctx: Context[T]) -> list[str]:
        """Returns the names for the help option."""
        return ["--help", "-h"]

    def format_usage(self, ctx: Context[T], formatter: HelpFormatter) -> None:
        """Writes the usage line into the formatter if it exists."""
        pieces = self.collect_usage_pieces(ctx)
        formatter.write_usage(ctx.command_path, " ".join(pieces))

    def format_help(self, ctx: Context[T], formatter: HelpFormatter) -> None:
        """Writes the help into the formatter if it exists.

        This calls the following methods:

        -   :meth:`format_usage`
        -   :meth:`format_help_text`
        -   :meth:`format_options`
        -   :meth:`format_epilog`
        """
        self.format_usage(ctx, formatter)
        self.format_help_text(ctx, formatter)
        self.format_options(ctx, formatter)
        self.format_epilog(ctx, formatter)

    def format_help_text(self, ctx: Context[T], formatter: HelpFormatter) -> None:
        """Writes the help text to the formatter if it exists."""
        text = self.get_help_text()

        if text:
            # truncate the help text to the first form feed
            text = inspect.cleandoc(text).partition("\f")[0]

        if self.deprecated:
            text = f"(Deprecated) {text}"

        if text:
            formatter.write_paragraph()

            with formatter.indentation():
                formatter.write_text(text)

    def format_options(self, ctx: Context[T], formatter: HelpFormatter) -> None:
        """Writes all the options into the formatter if they exist."""
        opts = []
        for param in self.get_params(ctx).get_parser_params():
            rv = param.get_help_record(ctx)
            if rv is not None:
                opts.append(rv)

        if opts:
            with formatter.section("Options"):
                formatter.write_dl(opts)

    def format_epilog(self, ctx: Context[T], formatter: HelpFormatter) -> None:
        """Writes the epilog into the formatter if it exists."""
        if self.epilog:
            epilog = inspect.cleandoc(self.epilog)
            formatter.write_paragraph()

            with formatter.indentation():
                formatter.write_text(epilog)

    def collect_usage_pieces(self, ctx: Context[T]) -> list[str]:
        """Returns all the pieces that go into the usage line and returns
        it as a list of strings.
        """
        usage_pieces = [self.options_metavar] if self.options_metavar else []

        for param in self.get_params(ctx).get_parser_params():
            usage_pieces.extend(param.get_usage_pieces(ctx))

        return usage_pieces

    def callback(
        self, callback: Callable[CallbackParms, CallbackResult], /
    ) -> Callable[CallbackParms, CallbackResult]:
        self.add_callback(callback)
        return callback

    def add_callback(
        self, fn: Callable[..., Any] | str, *, import_dependencies: str | None = None
    ) -> None:
        self.callbacks.append(
            create_callback(fn, import_dependencies=import_dependencies)
        )

    def get_params(self, ctx: Context[T]) -> ParameterGroup:
        params = ParameterGroup(ctx)

        if (help_option := self.get_help_option(ctx)) is not None:
            params.add_param(help_option)

        for callback in self.callbacks:
            params.add_params(callback.get_params(ctx))

        return params

    def parse_args(
        self, ctx: Context[T], *, raise_on_unexpected: bool = True
    ) -> list[str]:
        if not ctx.args and self.no_args_is_help:
            raise Help(ctx=ctx)

        params = self.get_params(ctx)

        values, remaining_args = parse_args(
            ctx,
            params.get_parser_params(),
            allow_interspersed_args=self.allow_interspersed_args,
            raise_on_unexpected=raise_on_unexpected,
        )

        for value in values:
            ctx.values[value.param] = value

        for param in params.get_depends_params():
            ctx.values[param] = param.resolve(ctx)

        return remaining_args

    def invoke_callbacks(self, ctx: Context[T]) -> None:
        for callback in self.callbacks:
            callback(ctx)

    def run(
        self,
        args: list[str] | None = None,
        *,
        prog_name: str | None = None,
        environ: Mapping[str, str] | None = None,
        config: Mapping[str, object] | None = None,
        auto_config_prefix: str | None = None,
        auto_envvar_prefix: str | None = None,
    ) -> T:
        if args is None:
            args = sys.argv[1:]
        else:
            args = list(args)

        if prog_name is None:
            prog_name = detect_program_name()

        if environ is None:
            environ = os.environ

        if config is None:
            config = {}

        ctx = self.make_context(
            prog_name,
            args,
            environ,
            config,
            auto_config_prefix=auto_config_prefix,
            auto_envvar_prefix=auto_envvar_prefix,
        )
        return self.invoke(ctx)

    def main(
        self,
        args: list[str] | None = None,
        *,
        prog_name: str | None = None,
        environ: Mapping[str, str] | None = None,
        config: Mapping[str, object] | None = None,
        auto_config_prefix: str | None = None,
        auto_envvar_prefix: str | None = None,
    ) -> NoReturn:
        try:
            try:
                self.run(
                    args=args,
                    prog_name=prog_name,
                    environ=environ,
                    config=config,
                    auto_config_prefix=auto_config_prefix,
                    auto_envvar_prefix=auto_envvar_prefix,
                )
                raise Exit()

            except TabbError as error:
                error.show()
                sys.exit(error.exit_code)

            except (EOFError, KeyboardInterrupt):
                print(file=sys.stderr)
                raise Abort() from None

            except OSError as error:
                if error.errno == errno.EPIPE:
                    sys.stdout = pacify_flush(sys.stdout)
                    sys.stderr = pacify_flush(sys.stderr)
                    sys.exit(1)
                else:
                    raise

        except Exit as error:
            sys.exit(error.exit_code)

        except Abort:
            print("Aborted!", file=sys.stderr)
            sys.exit(1)

    def __call__(
        self,
        args: list[str] | None = None,
        *,
        prog_name: str | None = None,
        environ: Mapping[str, str] | None = None,
        config: Mapping[str, object] | None = None,
        auto_config_prefix: str | None = None,
        auto_envvar_prefix: str | None = None,
    ) -> NoReturn:
        self.main(
            args,
            prog_name=prog_name,
            environ=environ,
            config=config,
            auto_config_prefix=auto_config_prefix,
            auto_envvar_prefix=auto_envvar_prefix,
        )

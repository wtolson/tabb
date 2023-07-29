from __future__ import annotations

import abc
from collections.abc import Callable, Sequence
from typing import Any, NoReturn, TypeGuard, TypeVar

from tabb.context import Context
from tabb.exceptions import (
    BadParameter,
    MissingParameter,
    augment_usage_errors,
)
from tabb.missing import _MISSING_TYPE, MISSING
from tabb.nargs import IntNArgs, NArgs
from tabb.parameter.base import (
    Parameter,
    ParameterKind,
    ParameterSource,
    ParameterValue,
)
from tabb.parameter.types import ParameterArg, ParameterType
from tabb.utils import to_kebab, to_snake

ValueType = TypeVar("ValueType")


class ParserParameter(Parameter[ValueType]):
    def __init__(
        self,
        name: str,
        kind: ParameterKind,
        type: ParameterType[ValueType],
        *,
        config: Sequence[str] | None = None,
        default_factory: Callable[[], ValueType] | _MISSING_TYPE = MISSING,
        default: ValueType | _MISSING_TYPE = MISSING,
        envvar: Sequence[str] | None = None,
        help: str | None = None,
        hidden: bool = False,
        metavar: str | None = None,
        required: bool | None = None,
    ) -> None:
        super().__init__(name, kind)
        self.config = None if config is None else list(config)
        self.type = type
        self.default = default
        self.default_factory = default_factory
        self.envvar = None if envvar is None else list(envvar)
        self.help = help
        self.hidden = hidden
        self.metavar = metavar
        self.required = required

    @abc.abstractmethod
    def get_error_hint(self, ctx: Context[Any] | None = None) -> str:
        ...

    @property
    def nargs(self) -> NArgs:
        return self.type.nargs

    def is_required(self, ctx: Context[Any] | None = None) -> bool:
        if self.required is not None:
            return self.required

        return not (self.has_default(ctx) or self.type.has_default())

    def has_default(self, ctx: Context[Any] | None = None) -> bool:
        if self.default is not MISSING:
            return True

        if self.default_factory is not MISSING:
            return True

        return False

    def get_metavar(self, ctx: Context[Any] | None = None) -> str:
        if self.metavar is not None:
            return self.metavar

        metavar = self.type.get_metavar(ctx)
        if metavar is None:
            metavar = self.name.upper()

        return self.nargs.format_metavar(metavar)

    def get_config(self, ctx: Context[Any] | None = None) -> list[str]:
        if self.config is not None:
            return self.config

        if ctx and ctx.auto_config_prefix is not None:
            return [f"{ctx.auto_config_prefix}.{to_kebab(self.name).lower()}"]

        return []

    def get_envvar(self, ctx: Context[Any] | None = None) -> list[str]:
        if self.envvar is not None:
            return self.envvar

        if ctx and ctx.auto_envvar_prefix is not None:
            return [f"{ctx.auto_envvar_prefix}_{to_snake(self.name).upper()}"]

        return []

    def fail(
        self,
        message: str,
        ctx: Context[Any] | None = None,
    ) -> NoReturn:
        """Helper method to fail with an invalid value message."""
        raise BadParameter(message, ctx=ctx, param=self)

    def fail_missing(
        self,
        message: str | None = None,
        ctx: Context[Any] | None = None,
    ) -> NoReturn:
        """Helper method to fail with a missing value message."""
        raise MissingParameter(
            message, ctx=ctx, param=self, param_type=self.get_param_type()
        )

    def matches(
        self,
        ctx: Context[Any],
        arg: ParameterArg,
    ) -> bool:
        return True

    def process_args(
        self,
        ctx: Context[Any],
        args: list[ParameterArg],
    ) -> ParameterValue[ValueType]:
        value, source = self.get_value(ctx, args)

        if self.validate(ctx, value):
            return ParameterValue(value, source, self)

        self.fail(f"Invalid value {value!r}", ctx=ctx)

    def get_value(
        self,
        ctx: Context[Any],
        args: list[ParameterArg],
    ) -> tuple[Any | _MISSING_TYPE, ParameterSource]:
        value: Any

        with augment_usage_errors(ctx, self, parameter_errors=ValueError):
            # Only process args first if any were provided, otherwise we look
            # for a default value elsewhere first.
            if args:
                value = self.type.process_args(args)
                if not isinstance(value, _MISSING_TYPE):
                    return value, ParameterSource.COMMANDLINE

            for envar in self.get_envvar(ctx):
                if envar not in ctx.environ:
                    continue

                value = self.type.parse_envvar(ctx.environ[envar])
                return value, ParameterSource.ENVIRONMENT

            for config_path in self.get_config(ctx):
                value = ctx.config.get_path(config_path, MISSING)
                if isinstance(value, _MISSING_TYPE):
                    continue

                value = self.type.process_config(value)
                return value, ParameterSource.CONFIG

            if not isinstance(self.default, _MISSING_TYPE):
                return self.default, ParameterSource.DEFAULT

            if not isinstance(self.default_factory, _MISSING_TYPE):
                return self.default_factory(), ParameterSource.DEFAULT

            # Process are args again if we didn't find a default value
            # to see if our type will accept an empty value.
            if not args:
                value = self.type.process_args(args)

            return value, ParameterSource.COMMANDLINE

    def validate(
        self,
        ctx: Context[Any],
        value: Any | _MISSING_TYPE,
    ) -> TypeGuard[ValueType | _MISSING_TYPE]:
        if value is MISSING and self.is_required(ctx):
            self.fail_missing(ctx=ctx)

        if value is MISSING:
            return True

        with augment_usage_errors(ctx, self, parameter_errors=(TypeError, ValueError)):
            return self.type.validate(value)

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} {self.name!r}>"


class ArgumentParameter(ParserParameter[ValueType]):
    @property
    def nargs(self) -> NArgs:
        nargs = super().nargs
        if self.is_required():
            return nargs
        return nargs.as_optional()

    def get_error_hint(self, ctx: Context[Any] | None = None) -> str:
        return f"'{self.get_metavar(ctx)}'"

    def get_usage_pieces(self, ctx: Context[Any] | None = None) -> list[str]:
        return [self.get_metavar(ctx)]

    def get_param_type(self) -> str:
        return "argument"

    def matches(self, ctx: Context[Any], arg: ParameterArg) -> bool:
        return super().matches(ctx, arg) and self.type.matches(arg)


class OptionParameter(ParserParameter[ValueType]):
    def __init__(
        self,
        name: str,
        kind: ParameterKind,
        type: ParameterType[ValueType],
        flags: Sequence[str],
        *,
        envvar: str | Sequence[str] | None = None,
        default_factory: Callable[[], ValueType] | _MISSING_TYPE = MISSING,
        default: ValueType | _MISSING_TYPE = MISSING,
        help: str | None = None,
        hidden: bool = False,
        metavar: str | None = None,
        required: bool | None = None,
        show_config: bool = False,
        show_default: bool | str | None = None,
        show_envvar: bool = False,
    ) -> None:
        if isinstance(type.nargs, str):
            raise ValueError("nargs for options may not be veradic.")

        self.flags, self.secondary_flags = type.parse_flags(flags)
        self.show_config = show_config
        self.show_default = show_default
        self.show_envvar = show_envvar

        super().__init__(
            name=name,
            kind=kind,
            type=type,
            envvar=envvar,
            default=default,
            default_factory=default_factory,
            help=help,
            hidden=hidden,
            metavar=metavar,
            required=required,
        )

    @property
    def nargs(self) -> IntNArgs:
        if isinstance(nargs := self.type.nargs, IntNArgs):
            return nargs
        raise ValueError("nargs for options may not be variadic.")

    def get_error_hint(self, ctx: Context[Any] | None = None) -> str:
        return " / ".join(f"'{flag}'" for flag in self.flags)

    def get_default_repr(self, ctx: Context[Any] | None = None) -> str | None:
        if isinstance(self.show_default, str):
            return f"({self.show_default})"

        if not self.show_default:
            return None

        if self.default is not None and not isinstance(self.default, _MISSING_TYPE):
            return self.type.format_value(self.default)

        if not isinstance(self.default_factory, _MISSING_TYPE):
            return "(dynamic)"

        return None

    def get_help_record(
        self, ctx: Context[Any] | None = None
    ) -> tuple[str, str] | None:
        if self.hidden:
            return None

        def _write_opts(flags: Sequence[str]) -> str:
            rv = ", ".join(sorted(flags))

            if metavar := self.get_metavar(ctx):
                rv += f" {metavar}"

            return rv

        rv = [_write_opts(self.flags)]

        if self.secondary_flags:
            rv.append(_write_opts(self.secondary_flags))

        help_text = self.help or ""
        extra = []

        if self.show_config and (config := self.get_config(ctx)):
            paths = ", ".join(config)
            extra.append(f"config path: {paths}")

        if self.show_envvar and (envvar := self.get_envvar(ctx)):
            var_str = ", ".join(envvar)
            extra.append(f"env var: {var_str}")

        if default_repr := self.get_default_repr(ctx):
            extra.append(f"default: {default_repr}")

        if self.is_required(ctx):
            extra.append("required")

        if extra:
            extra_str = "; ".join(extra)
            help_text = f"{help_text}  [{extra_str}]" if help_text else f"[{extra_str}]"

        return (" / ").join(rv), help_text

    def get_param_type(self) -> str:
        return "option"

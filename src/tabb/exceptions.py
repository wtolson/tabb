from __future__ import annotations

import sys
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any, TextIO

if TYPE_CHECKING:
    from tabb.context import Context
    from tabb.parameter import ParserParameter


@contextmanager
def augment_usage_errors(
    ctx: Context[Any],
    param: ParserParameter[Any] | None = None,
    *,
    parameter_errors: type[Exception] | tuple[type[Exception], ...] = (),
    usage_errors: type[Exception] | tuple[type[Exception], ...] = (),
) -> Iterator[None]:
    """Context manager that attaches extra information to exceptions."""
    try:
        yield

    except BadParameter as error:
        if error.ctx is None:
            error.ctx = ctx
        if param is not None and error.param is None:
            error.param = param
        raise

    except (Help, UsageError) as error:
        if error.ctx is None:
            error.ctx = ctx
        raise

    except parameter_errors as error:
        raise BadParameter(str(error), ctx, param) from error

    except usage_errors as error:
        raise UsageError(str(error), ctx) from error


class Abort(RuntimeError):  # noqa: N818
    pass


class Exit(RuntimeError):  # noqa: N818
    """An exception that indicates that the application should exit with some
    status code.

    :param code: the status code to exit with.
    """

    __slots__ = ("exit_code",)

    def __init__(self, code: int = 0) -> None:
        self.exit_code = code


class TabbError(Exception):
    """An exception that TaBB can handle and show to the user."""

    #: The exit code for this exception.
    exit_code = 1

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message

    def format_message(self) -> str:
        return self.message

    def __str__(self) -> str:
        return self.message

    def show(self, file: TextIO = sys.stderr) -> None:
        print(f"Error: {self.format_message()}", file=file)


class Help(TabbError):  # noqa: N818
    """An internal exception that signals TaBB to show the help page."""

    def __init__(
        self, message: str | None = None, ctx: Context[Any] | None = None
    ) -> None:
        super().__init__(message or "Help requested.")
        self.ctx = ctx

    def show(self, file: TextIO = sys.stderr) -> None:
        if self.ctx is None:
            raise RuntimeError("Cannot show help without ctx.")

        print(self.ctx.get_help(), file=file)


class UsageError(TabbError):
    """An internal exception that signals a usage error. This typically
    aborts any further handling."""

    exit_code = 2

    def __init__(self, message: str, ctx: Context[Any] | None = None) -> None:
        super().__init__(message)
        self.ctx = ctx

    def show(self, file: TextIO = sys.stderr) -> None:
        if self.ctx is not None:
            print(self.ctx.get_usage(), file=file)

            help_option = self.ctx.command.get_help_option(self.ctx)
            if help_option is not None:
                print(
                    f"Try '{self.ctx.command_path} {help_option.flags[0]}' for help.",
                    file=file,
                )

        super().show(file=file)


class BadParameter(UsageError):  # noqa: N818
    """An exception that formats out a standardized error message for a
    bad parameter.  This is useful when thrown from a callback or type as
    TaBB will attach contextual information to it (for instance, which
    parameter it is).
    """

    def __init__(
        self,
        message: str,
        ctx: Context[Any] | None = None,
        param: ParserParameter[Any] | None = None,
        param_hint: str | None = None,
    ) -> None:
        super().__init__(message, ctx)
        self.param = param
        self.param_hint = param_hint

    def format_message(self) -> str:
        if self.param_hint is not None:
            param_hint = self.param_hint
        elif self.param is not None:
            param_hint = self.param.get_error_hint(self.ctx)
        else:
            return f"Invalid value: {self.message}"

        return f"Invalid value for {param_hint}: {self.message}"


class MissingParameter(BadParameter):
    """Raised if a required an option or argument is missing."""

    def __init__(
        self,
        message: str | None = None,
        ctx: Context[Any] | None = None,
        param: ParserParameter[Any] | None = None,
        param_hint: str | None = None,
        param_type: str = "parameter",
    ) -> None:
        super().__init__(message or "", ctx, param, param_hint)
        self.param_type = param_type

    def _get_param_hint(self) -> str | None:
        if self.param_hint is not None:
            return self.param_hint

        if self.param is not None:
            return self.param.get_error_hint(self.ctx)

        return None

    def format_message(self) -> str:
        msg = f"Missing {self.param_type}"

        param_hint = self._get_param_hint()
        if param_hint:
            msg = f"{msg} {param_hint}"

        if self.message:
            return f"{msg}: {self.message}"

        return f"{msg}."

    def __str__(self) -> str:
        if self.message:
            return self.message

        if self.param:
            return f"Missing {self.param_type}: {self.param.name}"

        return f"Missing {self.param_type}."


class UnexpetedParameter(UsageError):  # noqa: N818
    def __init__(
        self,
        arg: str,
        message: str | None = None,
        possibilities: Sequence[str] | None = None,
        ctx: Context[Any] | None = None,
    ) -> None:
        if message is None:
            message = f"Unexpeted parameter: {arg}"

        super().__init__(message, ctx)
        self.arg = arg
        self.possibilities = possibilities

    def format_message(self) -> str:
        if not self.possibilities:
            return self.message

        if len(self.possibilities) == 1:
            suggest = f"Did you mean {self.possibilities[0]}?"
        else:
            options = ", ".join(sorted(self.possibilities))
            suggest = f"(Possible options: {options})"

        return f"{self.message} {suggest}"

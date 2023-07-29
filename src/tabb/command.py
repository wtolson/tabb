from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Generic, ParamSpec, TypeVar

from tabb.base import BaseCommand
from tabb.callback import create_callback
from tabb.context import Context
from tabb.parameter import ParameterGroup
from tabb.utils import to_kebab

P = ParamSpec("P")
T = TypeVar("T")


class Command(BaseCommand[T], Generic[P, T]):
    def __init__(
        self,
        callback: str | Callable[P, T],
        *,
        add_help_option: bool = True,
        deprecated: bool = False,
        epilog: str | None = None,
        help: str | None = None,
        hidden: bool = False,
        import_dependencies: str | None = None,
        name: str | None = None,
        no_args_is_help: bool = False,
        options_metavar: str | None = "[OPTIONS]",
        short_help: str | None = None,
    ) -> None:
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
        self._callback = create_callback(
            callback, import_dependencies=import_dependencies
        )

    def get_name(self) -> str:
        name = super().get_name()
        if name:
            return name
        return to_kebab(self._callback.name)

    def get_help_text(self) -> str:
        help_text = super().get_help_text()
        if help_text:
            return help_text

        if self._callback:
            return inspect.getdoc(self._callback.fn) or ""

        return ""

    def get_params(self, ctx: Context[T]) -> ParameterGroup:
        params = super().get_params(ctx)
        params.add_params(self._callback.get_params(ctx))
        return params

    def invoke(self, ctx: Context[T]) -> T:
        self.parse_args(ctx)
        self.invoke_callbacks(ctx)
        return self._callback(ctx)

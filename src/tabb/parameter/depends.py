from __future__ import annotations

import inspect
import typing
from collections.abc import Callable
from typing import Any, TypeVar

from tabb.context import Context
from tabb.parameter.base import (
    Parameter,
    ParameterKind,
    ParameterSource,
    ParameterValue,
)
from tabb.parameter.utils import get_base_type

ValueType = TypeVar("ValueType")


class DependsParameter(Parameter[ValueType]):
    def __init__(
        self,
        name: str,
        kind: ParameterKind,
        dependency: Callable[..., ValueType],
        *,
        use_cache: bool = True,
    ) -> None:
        super().__init__(name, kind)
        self.dependency = dependency
        self.use_cache = use_cache

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} {self.dependency.__name__}>"

    def get_sub_params(self, ctx: Context[Any]) -> list[Parameter[Any]]:
        from tabb.callback import Callback

        callback = self.get_callback(ctx)

        if isinstance(callback, Callback):
            return callback.get_params(ctx)

        return []

    def resolve(self, ctx: Context[Any]) -> ParameterValue[ValueType]:
        return ParameterValue(self.get_value(ctx), ParameterSource.DEPENDS, self)

    def make_callback(self) -> Callable[[Context[Any]], ValueType]:
        signature = inspect.signature(self.dependency)
        parameters = list(signature.parameters.values())

        if len(parameters) == 1:
            type_hints = typing.get_type_hints(self.dependency, include_extras=False)
            type_hint = type_hints[parameters[0].name]
            if get_base_type(type_hint) is Context:
                return self.dependency

        from tabb.callback import Callback

        return Callback(self.dependency)

    def get_callback(self, ctx: Context[Any]) -> Callable[[Context[Any]], ValueType]:
        if self.dependency not in ctx.dependencies.callbacks:
            ctx.dependencies.callbacks[self.dependency] = self.make_callback()
        return ctx.dependencies.callbacks[self.dependency]

    def get_value(self, ctx: Context[Any]) -> ValueType:
        if not self.use_cache:
            dependency = self.get_callback(ctx)
            return dependency(ctx)

        if self.dependency not in ctx.dependencies.values:
            dependency = self.get_callback(ctx)
            ctx.dependencies.values[self.dependency] = dependency(ctx)

        value: ValueType = ctx.dependencies.values[self.dependency]
        return value

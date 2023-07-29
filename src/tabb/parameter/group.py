from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING, Any

from tabb.parameter.depends import DependsParameter
from tabb.parameter.parser import ParserParameter

if TYPE_CHECKING:
    from tabb.context import Context
    from tabb.parameter.base import Parameter


class ParameterGroup:
    def __init__(
        self,
        ctx: Context[Any],
        params: Iterable[Parameter[Any]] = (),
    ) -> None:
        self.ctx = ctx
        self._params: dict[Parameter[Any], None] = {}
        self._parser_params: list[ParserParameter[Any]] = []
        self._depends_params: list[DependsParameter[Any]] = []

    def add_params(self, params: Iterable[Parameter[Any]]) -> None:
        for param in params:
            self.add_param(param)

    def add_param(self, param: Parameter[Any]) -> None:
        if param in self._params:
            return

        if isinstance(param, ParserParameter):
            self._parser_params.append(param)

        elif isinstance(param, DependsParameter):
            self.add_params(param.get_sub_params(self.ctx))
            self._depends_params.append(param)

        self._params[param] = None

    def get_params(self) -> list[Parameter[Any]]:
        return list(self._params)

    def get_parser_params(self) -> list[ParserParameter[Any]]:
        return list(self._parser_params)

    def get_depends_params(self) -> list[DependsParameter[Any]]:
        return list(self._depends_params)

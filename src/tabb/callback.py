from __future__ import annotations

import dataclasses
import importlib
from collections.abc import Callable, Iterable, Mapping
from typing import Any, Generic, ParamSpec, TypeVar, cast

from tabb.context import Context
from tabb.exceptions import UsageError
from tabb.missing import _MISSING_TYPE
from tabb.parameter import Parameter, resolve_params

T = TypeVar("T")
P = ParamSpec("P")

CALLBACK_ATTR = "__callbacks__"


def create_callback(
    callback: str | Callable[P, T],
    *,
    import_dependencies: str | None = None,
    localns: dict[str, Any] | None = None,
) -> Callback[P, T]:
    if isinstance(callback, str):
        return LazyCallback(callback, import_dependencies=import_dependencies)
    return Callback(callback, localns=localns)


def get_registered_callbacks(obj: object) -> list[Callback[..., Any]]:
    callbacks: list[Callback[..., Any]] = []
    while obj:
        callbacks.extend(getattr(obj, CALLBACK_ATTR, []))
        obj = getattr(obj, "__wrapped__", None)
    return callbacks


def register_callback(
    obj: object,
    callback: str | Callable[..., Any],
    *,
    import_dependencies: str | None = None,
    localns: dict[str, Any] | None = None,
) -> None:
    if not hasattr(obj, CALLBACK_ATTR):
        setattr(obj, CALLBACK_ATTR, [])
    callbacks: list[Callback[..., Any]] = getattr(obj, CALLBACK_ATTR)
    callbacks.append(
        create_callback(
            callback, import_dependencies=import_dependencies, localns=localns
        )
    )


@dataclasses.dataclass(frozen=True)
class Callback(Generic[P, T]):
    fn: Callable[P, T]
    params: tuple[Parameter[Any], ...]

    @property
    def name(self) -> str:
        return self.fn.__name__

    def __init__(
        self, fn: Callable[P, T], *, localns: dict[str, Any] | None = None
    ) -> None:
        object.__setattr__(self, "fn", fn)
        object.__setattr__(self, "params", tuple(resolve_params(fn, localns=localns)))

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} {self.name}>"

    def __call__(self, ctx: Context[Any]) -> T:
        for callback in get_registered_callbacks(self.fn):
            callback(ctx)

        args, kwargs = self.align_parameters(ctx)
        return self.fn(*args, **kwargs)

    def get_params(self, ctx: Context[Any]) -> list[Parameter[Any]]:
        result: list[Parameter[Any]] = []

        for callback in get_registered_callbacks(self.fn):
            result.extend(callback.get_params(ctx))

        result.extend(self.params)
        return result

    def align_parameters(self, ctx: Context[Any]) -> tuple[list[Any], dict[str, Any]]:
        stack = list(reversed(self.params))

        args = self._align_args(ctx, stack)
        kwargs = self._align_kwargs(ctx, stack)

        if not stack:
            return args, kwargs

        msg = f"Unexpected parameter: {stack[-1].name}"
        raise RuntimeError(msg)

    def _align_args(self, ctx: Context[Any], stack: list[Parameter[Any]]) -> list[Any]:
        args: list[Any] = []

        while stack:
            param = stack.pop()

            if param.kind != Parameter.POSITIONAL:
                stack.append(param)
                break

            item = ctx.values[param]

            if not item or isinstance(item.value, _MISSING_TYPE):
                return args

            args.append(item.value)

        while stack:
            param = stack.pop()

            if param.kind != Parameter.POSITIONAL_OR_KEYWORD:
                stack.append(param)
                break

            item = ctx.values[param]

            if not item or isinstance(item.value, _MISSING_TYPE):
                return args

            args.append(item.value)

        if stack and stack[-1].kind == Parameter.VAR_POSITIONAL:
            param = stack.pop()
            item = ctx.values[param]

            if not item or isinstance(item.value, _MISSING_TYPE):
                return args

            if not isinstance(item.value, Iterable):
                msg = (
                    "Expected iterable for VAR_POSITIONAL param "
                    f"{param.name}, got {item.value!r}"
                )
                raise TypeError(msg)

            args.extend(item.value)

        return args

    def _align_kwargs(
        self,
        ctx: Context[Any],
        stack: list[Parameter[Any]],
    ) -> dict[str, Any]:
        kwargs: dict[str, Any] = {}

        while stack:
            param = stack.pop()

            if param.kind not in (
                Parameter.POSITIONAL_OR_KEYWORD,
                Parameter.KEYWORD,
            ):
                stack.append(param)
                break

            item = ctx.values[param]

            if not item or isinstance(item.value, _MISSING_TYPE):
                continue

            if param.name in kwargs:
                msg = f"Got multiple values for keyword argument {param.name!r}."
                raise UsageError(msg, ctx=ctx)

            kwargs[param.name] = item.value

        if stack and stack[-1].kind == Parameter.VAR_KEYWORD:
            param = stack.pop()
            item = ctx.values[param]

            if not item or isinstance(item.value, _MISSING_TYPE):
                return kwargs

            if not isinstance(item.value, Mapping):
                msg = (
                    "Expected dict for VAR_KEYWORD param "
                    f"{param.name}, got {item.value!r}"
                )
                raise TypeError(msg)

            for key, value in item.value.items():
                if key in kwargs:
                    msg = f"Got multiple values for keyword argument {key!r}."
                    raise UsageError(msg, ctx=ctx)

                kwargs[key] = value

        return kwargs


@dataclasses.dataclass(frozen=True, slots=True)
class LazyCallback(Callback[P, T]):
    path: str
    import_dependencies: str | None = None

    def __init__(self, path: str, import_dependencies: str | None = None) -> None:
        object.__setattr__(self, "path", path)
        object.__setattr__(self, "import_dependencies", import_dependencies)

    @property
    def name(self) -> str:
        _, _, name = self.path.rpartition(":")
        return name

    def resolve(self) -> Callable[P, T]:
        module_name, _, callback_name = self.path.rpartition(":")

        try:
            module = importlib.import_module(module_name)
        except ImportError as error:
            if self.import_dependencies:
                package, _, _ = module_name.partition(".")
                message = (
                    f"{error}. Ensure `{package}[{self.import_dependencies}]` "
                    "extra is installed."
                )
                raise type(error)(message, *error.args[1:]) from error
            raise

        callback = getattr(module, callback_name)

        if not callable(callback):
            msg = f"Resolved callback {callback!r} is not callable"
            raise TypeError(msg)

        return cast(Callable[P, T], callback)

    def __getattr__(self, name: str) -> Any:
        if name in ("fn", "params"):
            Callback.__init__(self, self.resolve())
        return object.__getattribute__(self, name)

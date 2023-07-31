from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any, ParamSpec, TypeVar, overload

from tabb.base import BaseCommand
from tabb.command import Command
from tabb.group import Group

T = TypeVar("T")
P = ParamSpec("P")


@overload
def command(callback: Callable[P, T], /) -> Command[P, T]:
    ...


@overload
def command(
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
    name: Callable[P, T] | str | None = None,
    **kwargs: Any,
) -> Command[P, T] | Callable[[Callable[P, T]], Command[P, T]]:
    if callable(name):
        return Command(name)

    def decorator(callback: Callable[P, T]) -> Command[P, T]:
        if isinstance(callback, Command):
            raise TypeError("Attempted to convert a callback into a command twice.")

        return Command(callback, name=name, **kwargs)

    return decorator


@overload
def group(callback: Callable[..., Any], /) -> Group[Any]:
    ...


@overload
def group(
    name: str | None = None,
    commands: Mapping[str, BaseCommand[T]] | Sequence[BaseCommand[T]] | None = None,
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
) -> Callable[[Callable[..., Any]], Group[Any]]:
    ...


def group(
    name: Callable[..., Any] | str | None = None,
    **kwargs: Any,
) -> Group[Any] | Callable[[Callable[..., Any]], Group[Any]]:
    if callable(name):
        return Group(name)

    def decorator(callback: Callable[..., Any]) -> Group[Any]:
        if isinstance(callback, Group):
            raise TypeError("Attempted to convert a callback into a group twice.")

        return Group(callback, name=name, **kwargs)

    return decorator

from __future__ import annotations

import typing
from types import NoneType, UnionType
from typing import Annotated, Literal, TypeVar, Union

T = TypeVar("T")


def get_annotations(type_hint: object) -> tuple[object, list[object]]:
    if typing.get_origin(type_hint) is Annotated:
        type_args = typing.get_args(type_hint)
        return type_args[0], list(type_args[1:])
    return type_hint, []


def get_annotated_child_type(type_hint: object) -> tuple[bool, object]:
    if typing.get_origin(type_hint) is not Annotated:
        return False, type_hint

    type_args = typing.get_args(type_hint)
    return True, type_args[0]


def get_optional_child_type(type_hint: object) -> tuple[bool, object]:
    if typing.get_origin(type_hint) not in (Union, UnionType):
        return False, type_hint

    type_args = typing.get_args(type_hint)
    if len(type_args) != 2 or NoneType not in type_args:
        msg = "Union type arguments not supported."
        raise TypeError(msg)

    return True, next(t for t in type_args if t is not NoneType)


def get_list_child_type(type_hint: object) -> tuple[bool, object]:
    if typing.get_origin(type_hint) is not list:
        return False, type_hint

    type_args = typing.get_args(type_hint)
    if len(type_args) != 1:
        msg = "List type arguments should contain a single type."
        raise TypeError(msg)

    return True, type_args[0]


def get_tuple_child_type(type_hint: object) -> tuple[bool, object]:
    if typing.get_origin(type_hint) is not tuple:
        return False, type_hint

    type_args = typing.get_args(type_hint)
    if len(type_args) != 2 or type_args[1] != ...:
        msg = "Tuple type arguments should contain a single type and ellipsis."
        raise TypeError(msg)

    return True, type_args[0]


def get_literal_child_type(type_hint: object) -> tuple[bool, object]:
    if typing.get_origin(type_hint) is not Literal:
        return False, type_hint

    type_args = typing.get_args(type_hint)
    # Make sure just a single type has been used
    if len({type(arg) for arg in type_args}) != 1:
        msg = "Literal type arguments should contain iterms of a single type."
        raise TypeError(msg)

    return True, type(type_args[0])


def _strip_typing_extra(type_hint: object) -> object:
    if isinstance(origin := typing.get_origin(type_hint), type):
        return origin

    for resolvers in (
        get_annotated_child_type,
        get_optional_child_type,
        get_literal_child_type,
    ):
        found, child_type = resolvers(type_hint)
        if found:
            return child_type

    msg = f"Unexpted type {type_hint!r}."
    raise TypeError(msg)


def get_base_type(type_hint: object) -> type:
    while not isinstance(type_hint, type):
        type_hint = _strip_typing_extra(type_hint)
    return type_hint

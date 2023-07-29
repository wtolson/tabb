from __future__ import annotations

import inspect
import pathlib
import typing
from collections.abc import Callable
from typing import Any

from tabb.context import Context
from tabb.missing import _MISSING_TYPE, MISSING
from tabb.nargs import NArgs, NArgsLiteral
from tabb.parameter.base import Parameter, ParameterKind
from tabb.parameter.depends import DependsParameter
from tabb.parameter.parser import ArgumentParameter, OptionParameter
from tabb.parameter.types import (
    AnyType,
    Bool,
    ChoicesValidator,
    Dict,
    Flag,
    GreedyAdaptor,
    LengthValidator,
    List,
    Optional,
    ParameterType,
    Path,
    RangeValidator,
    Scalar,
    Tuple,
    Validator,
)
from tabb.parameter.utils import (
    get_annotations,
    get_base_type,
    get_list_child_type,
    get_literal_child_type,
    get_optional_child_type,
    get_tuple_child_type,
)
from tabb.types import (
    Argument,
    Choices,
    Depends,
    Greedy,
    Length,
    Matches,
    Option,
    Range,
    Validate,
)
from tabb.utils import to_kebab


def get_context(ctx: Context[Any]) -> Context[Any]:
    return ctx


def resolve_params(
    fn: Callable[..., Any], *, localns: dict[str, Any] | None = None
) -> list[Parameter[Any]]:
    params: list[Parameter[Any]] = []
    signature = inspect.signature(fn)
    type_hints = typing.get_type_hints(fn, localns=localns, include_extras=True)

    for name, param_signature in signature.parameters.items():
        try:
            params.append(_resolve_parameter(name, param_signature, type_hints[name]))
        except TypeError as error:
            msg = f"Invalid type for parameter {name!r}. {error}"
            raise TypeError(msg) from error

    return params


def _resolve_parameter(
    name: str, signature: inspect.Parameter, type_hint: object
) -> Parameter[Any]:
    param: Parameter[Any]

    # Arguments with a default of None are automatically made optional
    is_optional, type_hint = get_optional_child_type(type_hint)
    type_hint, annotations = get_annotations(type_hint)
    options = _resolve_options(signature, type_hint, annotations)

    if isinstance(options, Argument):
        param = _resolve_argument(
            name, signature, type_hint, annotations, options, is_optional
        )

    elif isinstance(options, Option):
        param = _resolve_option(
            name, signature, type_hint, annotations, options, is_optional
        )

    elif isinstance(options, Depends):
        return _get_depends(name, signature, options)

    else:
        msg = f"Unexpected options type: {options!r}."
        raise TypeError(msg)

    if options.default is not MISSING:
        param.default = options.default

    elif options.default_factory is not MISSING:
        param.default_factory = options.default_factory

    elif signature.default is not signature.empty:
        param.default = signature.default

    if isinstance(options.config, str):
        param.config = [options.config]
    elif not isinstance(options.config, _MISSING_TYPE):
        param.config = list(options.config)

    if isinstance(options.envvar, str):
        param.envvar = [options.envvar]
    elif not isinstance(options.envvar, _MISSING_TYPE):
        param.envvar = list(options.envvar)

    if not isinstance(options.help, _MISSING_TYPE):
        param.help = options.help

    if not isinstance(options.hidden, _MISSING_TYPE):
        param.hidden = options.hidden

    if not isinstance(options.metavar, _MISSING_TYPE):
        param.metavar = options.metavar

    return param


def _resolve_argument(
    name: str,
    signature: inspect.Parameter,
    type_hint: object,
    annotations: list[object],
    options: Argument[Any],
    is_optional: bool,
) -> ArgumentParameter[Any]:
    parameter_type = _get_argument_type(type_hint, options, is_optional)
    parameter_type, kind = _resolve_parameter_kind(signature, parameter_type, nargs="*")
    parameter_type = _resolve_validators(type_hint, annotations, parameter_type)
    return ArgumentParameter(name, kind, parameter_type)


def _resolve_option(
    name: str,
    signature: inspect.Parameter,
    type_hint: object,
    annotations: list[object],
    options: Option[Any],
    is_optional: bool,
) -> OptionParameter[Any]:
    parameter_type = _resolve_option_type(type_hint, options, is_optional)
    parameter_type, kind = _resolve_parameter_kind(signature, parameter_type)
    parameter_type = _resolve_validators(type_hint, annotations, parameter_type)
    flags = list(options.flags) if options.flags else [f"--{to_kebab(name)}"]
    option = OptionParameter(name, kind, parameter_type, flags)

    if not isinstance(options.show_config, _MISSING_TYPE):
        option.show_config = options.show_config

    if not isinstance(options.show_default, _MISSING_TYPE):
        option.show_default = options.show_default

    if not isinstance(options.show_envvar, _MISSING_TYPE):
        option.show_envvar = options.show_envvar

    return option


def _get_depends(
    name: str,
    signature: inspect.Parameter,
    options: Depends[Any],
) -> DependsParameter[Any]:
    _, kind = _resolve_parameter_kind(signature, AnyType())
    return DependsParameter(name, kind, options.dependency, use_cache=options.use_cache)


def _get_argument_type(
    type_hint: object,
    options: Argument[Any],
    is_optional: bool = False,
) -> ParameterType[Any]:
    if not isinstance(options.type, _MISSING_TYPE):
        return options.type

    # Resolve optional types
    child_is_optional, type_hint = get_optional_child_type(type_hint)
    if is_optional or child_is_optional:
        item_type = _get_argument_type(type_hint, options)
        return Optional(item_type)

    # Resolve list types
    is_list, child_type = get_list_child_type(type_hint)
    if is_list:
        item_type = _get_argument_type(child_type, options)
        return List(item_type, nargs="*")

    # Resolve tuple types
    is_tuple, child_type = get_tuple_child_type(type_hint)
    if is_tuple:
        item_type = _get_argument_type(child_type, options)
        return Tuple(item_type, nargs="*")

    # Resolve Literal types
    is_literal, literal_type = get_literal_child_type(type_hint)
    if is_literal:
        choices = list(typing.get_args(type_hint))
        child_type = _get_argument_type(literal_type, options)
        return ChoicesValidator(child_type, choices)

    # Handle bool aruments
    if type_hint is bool:
        return Bool()

    if (result := _resolve_special_types(type_hint)) is not None:
        return result

    if callable(type_hint):
        return Scalar(type_hint)

    msg = f"Unexpted type: {type_hint!r}."
    raise TypeError(msg)


def _resolve_option_type(
    type_hint: object,
    options: Option[Any],
    is_optional: bool = False,
) -> ParameterType[Any]:
    if not isinstance(options.type, _MISSING_TYPE):
        return options.type

    # Resolve optional types
    child_is_optional, type_hint = get_optional_child_type(type_hint)
    if is_optional or child_is_optional:
        item_type = _resolve_option_type(type_hint, options)
        return Optional(item_type)

    # Resolve list types
    is_list, child_type = get_list_child_type(type_hint)
    if is_list:
        item_type = _resolve_option_type(child_type, options)
        return List(item_type)

    # Resolve tuple types
    is_tuple, child_type = get_tuple_child_type(type_hint)
    if is_tuple:
        item_type = _resolve_option_type(child_type, options)
        return Tuple(item_type)

    # Resolve Literal types
    is_literal, literal_type = get_literal_child_type(type_hint)
    if is_literal:
        choices = list(typing.get_args(type_hint))
        child_type = _resolve_option_type(literal_type, options)
        return ChoicesValidator(child_type, choices)

    # Bool options become flags
    if type_hint is bool:
        return Flag()

    if (result := _resolve_special_types(type_hint)) is not None:
        return result

    if callable(type_hint):
        return Scalar(type_hint)

    msg = f"Unexpted type: {type_hint!r}."
    raise TypeError(msg)


def _resolve_parameter_kind(
    signature: inspect.Parameter,
    parameter_type: ParameterType[Any],
    nargs: NArgs | NArgsLiteral | None = None,
) -> tuple[ParameterType[Any], ParameterKind]:
    if signature.kind == signature.VAR_POSITIONAL:
        parameter_type = List(parameter_type, nargs=nargs)
        return parameter_type, ParameterKind.VAR_POSITIONAL

    if signature.kind == signature.VAR_KEYWORD:
        parameter_type = Dict(parameter_type, nargs=nargs)
        return parameter_type, ParameterKind.VAR_KEYWORD

    if signature.kind == signature.KEYWORD_ONLY:
        return parameter_type, ParameterKind.KEYWORD

    if signature.kind == signature.POSITIONAL_ONLY:
        return parameter_type, ParameterKind.POSITIONAL

    if signature.kind == signature.POSITIONAL_OR_KEYWORD:
        return parameter_type, ParameterKind.POSITIONAL_OR_KEYWORD

    msg = f"Unexpted parameter kind: {signature.kind!r}."
    raise TypeError(msg)


def _resolve_special_types(
    type_hint: object,
) -> ParameterType[Any] | None:
    base_type = get_base_type(type_hint)

    if base_type is pathlib.Path:
        return Path()

    return None


def _resolve_validators(
    type_hint: object,
    annotations: list[object],
    parameter_type: ParameterType[Any],
) -> ParameterType[Any]:
    for annotation in annotations:
        if isinstance(annotation, Length):
            parameter_type = LengthValidator(
                type=parameter_type,
                min_length=annotation.min,
                max_length=annotation.max,
            )

        elif isinstance(annotation, Range):
            cast = get_base_type(type_hint)
            if cast not in (int, float):
                msg = f"Cannot use min/max with type {cast!r}."
                raise TypeError(msg)

            parameter_type = RangeValidator(
                type=parameter_type,
                cast=cast,
                min=annotation.min,
                max=annotation.max,
                min_open=annotation.min_open,
                max_open=annotation.max_open,
                clamp=annotation.clamp,
            )

        elif isinstance(annotation, Choices):
            parameter_type = ChoicesValidator(
                type=parameter_type,
                choices=annotation.values,
            )

        elif isinstance(annotation, Matches):
            # FIXME: This is not implemented yet
            pass

        elif isinstance(annotation, Greedy):
            parameter_type = GreedyAdaptor(
                type=parameter_type, greedy=annotation.is_greedy
            )

        elif isinstance(annotation, Validate):
            parameter_type = Validator(parameter_type, annotation.validator)

    return parameter_type


def _resolve_options(
    signature: inspect.Parameter, type_hint: object, annotations: list[object]
) -> Argument[Any] | Option[Any] | Depends[Any]:
    for annotation in annotations:
        if isinstance(annotation, (Argument | Option | Depends)):
            return annotation

    if typing.get_origin(type_hint) is Context:
        return Depends(get_context)

    if (
        signature.kind in (signature.VAR_POSITIONAL, signature.VAR_KEYWORD)
        or signature.default is not signature.empty
    ):
        return Option()

    return Argument()

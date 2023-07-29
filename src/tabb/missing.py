from __future__ import annotations

from typing import TypeGuard


class _MISSING_TYPE:  # noqa: N801
    pass


MISSING = _MISSING_TYPE()


def is_missing(value: object) -> TypeGuard[_MISSING_TYPE]:
    return value is MISSING

from __future__ import annotations

import os
import sys
from shlex import shlex
from types import ModuleType
from typing import Any, TextIO, cast


def to_kebab(name: str) -> str:
    return name.translate(str.maketrans("_ ", "--"))


def to_snake(name: str) -> str:
    return name.translate(str.maketrans("- ", "__"))


def split_csv(value: str) -> list[str]:
    splitter = shlex(value, posix=True)
    splitter.whitespace = ","
    splitter.whitespace_split = True
    return [s.strip() for s in splitter]


def detect_program_name(
    path: str | None = None, main_module: ModuleType | None = None
) -> str:
    if main_module is None:
        main_module = sys.modules["__main__"]

    if not path:
        path = sys.argv[0]

    # The value of __package__ indicates how Python was called. It may
    # not exist if a setuptools script is installed as an egg. It may be
    # set incorrectly for entry points created with pip on Windows.
    if getattr(main_module, "__package__", None) is None or (
        os.name == "nt"
        and main_module.__package__ == ""
        and not os.path.exists(path)
        and os.path.exists(f"{path}.exe")
    ):
        # Executed a file, like "python app.py".
        return os.path.basename(path)

    # Executed a module, like "python -m example".
    # Rewritten by Python from "-m script" to "/path/to/script.py".
    # Need to look at main module to determine how it was executed.
    name = os.path.splitext(os.path.basename(path))[0]

    py_module = main_module.__package__
    assert py_module is not None  # noqa: S101

    # A submodule like "example.cli".
    if name != "__main__":
        py_module = f"{py_module}.{name}"

    return f"python -m {py_module.lstrip('.')}"


class PacifyFlushWrapper:
    """This wrapper is used to catch and suppress BrokenPipeErrors resulting
    from ``.flush()`` being called on broken pipe during the shutdown/final-GC
    of the Python interpreter. Notably ``.flush()`` is always called on
    ``sys.stdout`` and ``sys.stderr``. So as to have minimal impact on any
    other cleanup code, and the case where the underlying file is not a broken
    pipe, all calls and attributes are proxied.
    """

    def __init__(self, wrapped: TextIO) -> None:
        self.wrapped = wrapped

    def flush(self) -> None:
        try:
            self.wrapped.flush()
        except OSError as e:
            import errno

            if e.errno != errno.EPIPE:
                raise

    def __getattr__(self, attr: str) -> Any:
        return getattr(self.wrapped, attr)


def pacify_flush(file: TextIO) -> TextIO:
    """Return a wrapper around the given file that will suppress BrokenPipeErrors
    resulting from ``.flush()`` being called on a broken pipe.
    """
    return cast(TextIO, PacifyFlushWrapper(file))

from __future__ import annotations

import abc
import asyncio
import signal
import threading
from collections.abc import Callable, Coroutine
from types import FrameType, TracebackType
from typing import Any, TypeAlias, TypeVar, cast

T = TypeVar("T")

LoopFactory: TypeAlias = Callable[[], asyncio.AbstractEventLoop]
SignalHandler: TypeAlias = Callable[[int, FrameType | None], None] | int | None


class Scheduler(abc.ABC):
    @abc.abstractmethod
    def get(self, value: T | Coroutine[Any, Any, T]) -> T:
        ...

    @abc.abstractmethod
    def close(self) -> None:
        ...

    def __enter__(self) -> None:
        return None

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        self.close()


class AsyncScheduler(Scheduler):
    def __init__(self, *, loop_factory: LoopFactory | None = None) -> None:
        if loop_factory is None:
            loop_factory = asyncio.new_event_loop

        self._loop_factory: LoopFactory = loop_factory
        self._loop: asyncio.AbstractEventLoop | None = None

    def close(self) -> None:
        if not self._loop:
            return

        loop = self._loop
        self._loop = None
        self._context = None

        try:
            _cancel_all_tasks(loop)
            loop.run_until_complete(loop.shutdown_asyncgens())
            loop.run_until_complete(loop.shutdown_default_executor())
        finally:
            loop.close()

    def get_loop(self) -> asyncio.AbstractEventLoop:
        if self._loop is None:
            self._loop = self._loop_factory()
        return self._loop

    def get(self, value: T | Coroutine[Any, Any, T]) -> T:
        if asyncio.iscoroutine(value):
            loop = self.get_loop()
            task = loop.create_task(value)

            with SigintHandler(loop, task):
                value = loop.run_until_complete(task)

        return cast(T, value)


class SigintHandler:
    def __init__(
        self, loop: asyncio.AbstractEventLoop, task: asyncio.Task[Any]
    ) -> None:
        self._loop = loop
        self._task = task
        self._called = False
        self._prev_handler: SignalHandler = signal.default_int_handler

    def called(self) -> bool:
        return self._called

    def __enter__(self) -> None:
        if threading.current_thread() is threading.main_thread():
            prev_handler = signal.getsignal(signal.SIGINT)

            try:
                signal.signal(signal.SIGINT, self)
            except ValueError:
                # `signal.signal` may throw if `threading.main_thread` does
                # not support signals (e.g. embedded interpreter with signals
                # not registered - see gh-91880)
                pass
            else:
                self._prev_handler = prev_handler

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        uncancel: Callable[[], int] | None = None
        current_handler: SignalHandler = signal.getsignal(signal.SIGINT)

        if current_handler is self:
            signal.signal(signal.SIGINT, self._prev_handler)

        if (
            self.called()
            and exc_type is not None
            and issubclass(exc_type, asyncio.CancelledError)
            and (uncancel := getattr(self._task, "uncancel", None))
            and uncancel() == 0
        ):
            raise KeyboardInterrupt()

    def __call__(self, signum: int, frame: FrameType | None) -> None:
        if self._called or self._task.done():
            if callable(self._prev_handler):
                return self._prev_handler(signum, frame)
            raise KeyboardInterrupt()

        self._called = True
        self._task.cancel()

        # wakeup loop if it is blocked by select() with long timeout
        self._loop.call_soon_threadsafe(lambda: None)


def _cancel_all_tasks(loop: asyncio.AbstractEventLoop) -> None:
    to_cancel = asyncio.all_tasks(loop)
    if not to_cancel:
        return

    for task in to_cancel:
        task.cancel()

    loop.run_until_complete(asyncio.gather(*to_cancel, return_exceptions=True))

    for task in to_cancel:
        if task.cancelled():
            continue

        if task.exception() is not None:
            loop.call_exception_handler(
                {
                    "message": "unhandled exception during asyncio.run() shutdown",
                    "exception": task.exception(),
                    "task": task,
                }
            )

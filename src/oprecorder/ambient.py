"""Standing where a runner stands, for the calls an op makes while it runs.

An op reaches other ops through ``opspec.runtime.run``, and reports through
``opspec.runtime.progress``; both go to whatever is bound at the time.
:func:`ambient` binds a runner and a task for the length of a ``with``, which
is how a recorder comes to see the calls a workflow or a script makes.
"""

from __future__ import annotations

import contextlib
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any

from opspec.runtime import bind_runner, bind_task, unbind_runner, unbind_task

__all__ = ["HostTask", "Progress", "ambient"]


@dataclass(frozen=True)
class Progress:
    """One progress report from an op running on the host."""

    message: str | None = None
    current: int | None = None
    maximum: int | None = None


class HostTask:
    """The handle on a workflow running on the host, which has no worker.

    It takes the workflow's own progress, passes on what the ops it calls
    report, and carries a cancel to the workflow and to the op it is waiting
    on.
    """

    def __init__(self, on_progress: Callable[[Any], None] | None) -> None:
        self._on_progress = on_progress
        self.cancel_requested = False
        self._child: Any = None

    def update(
        self,
        message: str | None = None,
        current: int | None = None,
        maximum: int | None = None,
    ) -> None:
        self.relay(Progress(message, current, maximum))

    def relay(self, event: Any) -> None:
        """Pass an event on, whether it came from here or from a sub-op."""
        if self._on_progress is not None:
            self._on_progress(event)

    def adopt(self, task: Any) -> None:
        """Note the sub-op task now running, so a cancel can reach it."""
        self._child = task
        if self.cancel_requested:
            task.cancel()

    def cancel(self) -> None:
        self.cancel_requested = True
        if self._child is not None:
            self._child.cancel()


class _Through:
    """What ``opspec.runtime.run`` calls: the runner, told who is listening."""

    def __init__(self, runner: Any, task: HostTask) -> None:
        self._runner = runner
        self._task = task

    def run(self, fn: Callable, args: dict | None = None, **kwargs: Any) -> Any:
        kwargs.setdefault("on_progress", self._task.relay)
        kwargs.setdefault("on_start", self._task.adopt)
        return self._runner.run(fn, args, **kwargs)


@contextlib.contextmanager
def ambient(
    runner: Any,
    on_progress: Callable[[Any], None] | None = None,
    on_start: Callable[[Any], None] | None = None,
) -> Iterator[HostTask]:
    """Route ``opspec.runtime.run`` calls through *runner* while this runs.

    ``on_progress`` hears the progress of whatever runs inside, and
    ``on_start`` is handed the task, whose ``cancel()`` reaches it.
    """
    task = HostTask(on_progress)
    if on_start is not None:
        on_start(task)
    reporting = bind_task(task)
    routing = bind_runner(_Through(runner, task))
    try:
        yield task
    finally:
        unbind_runner(routing)
        unbind_task(reporting)

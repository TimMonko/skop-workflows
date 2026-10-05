"""Recording, as a layer around a runner.

Nothing here knows about napari, Icechunk or scikit-ops. A host supplies arrays,
names the step an op's output fills, and gets the result back.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any, Protocol

import numpy as np

from .derived import Graph
from .op import OpInfo, info, is_json
from .record import ACCEPTED, EDITED, Event, Handle, Run
from .store import Store


class MissingRoot(ValueError):
    """An array reached an op without the store having issued it a handle."""


class Runner(Protocol):
    """What a runner has to do: call an op and return its result."""

    def run(self, fn: Callable, args: dict) -> Any: ...


class InProcess:
    """The simplest runner: call the function here."""

    def run(self, fn: Callable, args: dict) -> Any:
        return fn(**args)


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


class Recorder:
    """A host's handle on recording: a store, and a runner to execute with.

    Every call of an op goes through :meth:`run`, which records it: array
    arguments must already have a handle, parameters must be JSON, and the
    result is saved under the step name before the run is appended.
    """

    def __init__(
        self,
        store: Store,
        inner: Runner | None = None,
        version: str | None = None,
    ) -> None:
        self.store = store
        self.inner = inner or InProcess()
        #: What ran: the package version, and the git commit for a checkout.
        self.version = version

    # -- host-facing -----------------------------------------------------

    def root(self, name: str, array: np.ndarray) -> Handle:
        """Declare an input. Anything not declared is refused, never assumed."""
        return self.store.put(name, array)

    def graph(self) -> Graph:
        return Graph(self.store.records())

    def mark_edited(self, step: str, note: str | None = None) -> Event:
        """Record that a step's output was changed by hand."""
        run = self._current_or_raise(step)
        event = Event(id=_new_id(), kind=EDITED, run=run.id, note=note)
        self.store.append(event)
        return event

    def accept_edit(self, step: str, note: str | None = None) -> Event:
        """Keep the hand-made pixels, and stop the step claiming to reproduce."""
        run = self._current_or_raise(step)
        event = Event(id=_new_id(), kind=ACCEPTED, run=run.id, note=note)
        self.store.append(event)
        return event

    # -- running ---------------------------------------------------------

    def run(self, fn: Callable, step: str, args: dict[str, Any]) -> Any:
        spec = info(fn)
        inputs = self._inputs(spec, args)
        params = {k: v for k, v in args.items() if k not in inputs}
        for name, value in params.items():
            if not is_json(value):
                raise TypeError(
                    f'{name}={value!r} is not JSON, so it cannot be recorded'
                )

        try:
            result = self.inner.run(fn, args)
        except Exception as error:  # noqa: BLE001 -- a failed run is recorded
            self.store.append(
                Run(
                    id=_new_id(),
                    step=step,
                    op=spec.id,
                    inputs=inputs,
                    params=params,
                    status='failed',
                    error=f'{type(error).__name__}: {error}',
                    op_version=self.version,
                )
            )
            raise

        outputs = self._save(spec, step, result)
        self.store.append(
            Run(
                id=_new_id(),
                step=step,
                op=spec.id,
                inputs=inputs,
                outputs=outputs,
                params=params,
                op_version=self.version,
            )
        )
        return result

    # -- internals -------------------------------------------------------

    def _inputs(self, spec: OpInfo, args: dict[str, Any]) -> dict[str, Handle]:
        found = {}
        for name in spec.array_params:
            value = args.get(name)
            if not isinstance(value, np.ndarray):
                raise TypeError(f'{spec.id} needs an array for {name!r}')
            handle = self.store.handle_of(value)
            if handle is None:
                raise MissingRoot(
                    f'{name!r} has no handle. Put it in the store first, with '
                    f'recorder.root(...): an array from nowhere is a root, and a '
                    f'root that is not declared is a broken lineage.'
                )
            found[name] = handle
        return found

    def _save(self, spec: OpInfo, step: str, result: Any) -> dict[str, Handle]:
        if len(spec.outputs) == 1:
            return {spec.outputs[0].name: self.store.put(step, result)}
        return {
            out.name: self.store.put(f'{step}.{out.name}', result[out.name])
            for out in spec.outputs
        }

    def _current_or_raise(self, step: str) -> Run:
        run = self.graph().current(step)
        if run is None:
            raise KeyError(f'no successful run of {step!r} to mark')
        return run

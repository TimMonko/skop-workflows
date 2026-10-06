"""Recording, as a layer around a runner.

Nothing here knows about napari, Icechunk or scikit-ops. A host supplies arrays,
names the step an op's output fills, and gets the result back.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping
from typing import Any, Protocol

import numpy as np
from skop import NDARRAY, OpSpec, type_spec
from skop import spec as spec_of

from .derived import Graph
from .params import is_json, to_json
from .record import ACCEPTED, EDITED, REVERTED, Event, Handle, Root, Run
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
        """Declare an input, and record where it went.

        Anything not declared is refused, never assumed. Every declaration is
        its own record, so a root that moves under its consumers is visible in
        the log and makes them stale.
        """
        handle = self.store.put(name, array)
        self.store.append(Root(id=_new_id(), name=name, handle=handle))
        return handle

    def graph(self) -> Graph:
        return Graph(self.store.records())

    def mark_edited(self, step: str, note: str | None = None) -> Event:
        """Record that a step's output was changed by hand."""
        run = self._current_or_raise(step)
        event = Event(id=_new_id(), kind=EDITED, run=run.id, note=note)
        self.store.append(event)
        return event

    def mark_reverted(self, step: str, note: str | None = None) -> Event:
        """Record that a step's output went back to what its run produced.

        The edit stays in the log; this mark supersedes it, so the step stops
        being edited and nothing downstream counts as affected any more.
        """
        run = self._current_or_raise(step)
        event = Event(id=_new_id(), kind=REVERTED, run=run.id, note=note)
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
        spec = spec_of(fn)
        inputs = self._inputs(spec, args)
        params = {
            name: to_json(value)
            for name, value in args.items()
            if name not in inputs
        }
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
                    op=spec.name,
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
                op=spec.name,
                inputs=inputs,
                outputs=outputs,
                params=params,
                op_version=self.version,
            )
        )
        return result

    def update(self, fn: Callable, step: str) -> Any:
        """Run a stale step again, taking each input from where it now is.

        A stale step read data that has since moved on. Updating it is the
        deliberate gesture that consumes the newer data; nothing does it on
        its own (decision 8).
        """
        graph = self.graph()
        run = graph.current(step)
        if run is None:
            raise KeyError(f'no successful run of {step!r} to update')
        args: dict[str, Any] = {
            name: self._current_array(graph, handle)
            for name, handle in run.inputs.items()
        }
        args.update(run.params)
        return self.run(fn, step, args)

    def rerun(self, fn: Callable, step: str) -> Any:
        """Run a step again from the run it is on: its inputs, its params.

        Unlike :meth:`update` this does not go looking for newer data; it is
        the deliberate "do that again", and it adds a run rather than moving
        the step (decision 3).
        """
        run = self.graph().current(step)
        if run is None:
            raise KeyError(f'no successful run of {step!r} to rerun')
        args: dict[str, Any] = {
            name: self.store.get(handle) for name, handle in run.inputs.items()
        }
        args.update(run.params)
        return self.run(fn, step, args)

    def produce(
        self, targets: list[str], registry: Mapping[str, Callable]
    ) -> list[str]:
        """Bring the targets' closure up to date, and say what that ran.

        Every step in the closure keeps the parameters it was last run with
        and takes its inputs from wherever they now are; a step already
        current is left alone. It is decision 8's manual gesture applied to a
        whole selection rather than one step -- the call behind "run what is
        needed".

        The log grows as this runs, so the graph is re-read each time round:
        updating one step is exactly what makes its consumers stale.
        """
        ran = []
        for step in self.graph().closure(list(targets)):
            graph = self.graph()
            if not graph.is_stale(step):
                continue
            run = graph.current(step)
            fn = None if run is None else registry.get(run.op)
            if fn is None:
                raise KeyError(f'cannot resolve the op of {step!r}')
            self.update(fn, step)
            ran.append(step)
        return ran

    # -- internals -------------------------------------------------------

    def _inputs(self, spec: OpSpec, args: dict[str, Any]) -> dict[str, Handle]:
        found = {}
        for name in _array_params(spec):
            value = args.get(name)
            if not isinstance(value, np.ndarray):
                raise TypeError(f'{spec.name} needs an array for {name!r}')
            handle = self.store.handle_of(value)
            if handle is None:
                raise MissingRoot(
                    f'{name!r} has no handle. Put it in the store first, with '
                    f'recorder.root(...): an array from nowhere is a root, and a '
                    f'root that is not declared is a broken lineage.'
                )
            found[name] = handle
        return found

    def _save(self, spec: OpSpec, step: str, result: Any) -> dict[str, Handle]:
        # ``OpSpec.outputs`` is a tuple of output *names* in scikit-ops -- the
        # wire view, used to label task outputs -- so a single unnamed output
        # is the string 'result' (or the Out/Mut parameter's name, or a
        # NamedTuple's fields). ``output_specs`` carries the roles, which the
        # host reads when it has a viewer to draw into.
        if len(spec.outputs) == 1:
            return {spec.outputs[0]: self.store.put(step, result)}
        return {
            name: self.store.put(f'{step}.{name}', result[name])
            for name in spec.outputs
        }

    def _current_array(self, graph: Graph, handle: Handle) -> np.ndarray:
        """Where the data behind an input is now, not where it was."""
        producer = graph.producer(handle)
        if producer is not None:
            # Which of the producer's outputs this came from, by value: an
            # op's output name and the parameter it feeds need not match.
            out = next(
                (
                    name
                    for name, made in producer.outputs.items()
                    if made == handle
                ),
                None,
            )
            latest = graph.current(producer.step)
            if latest is not None:
                handle = latest.outputs.get(out or '', handle)
            return self.store.get(handle)
        root = graph.root_of(handle)
        if root is not None:
            current = graph.current_root(root.name)
            if current is not None:
                handle = current.handle
        return self.store.get(handle)

    def _current_or_raise(self, step: str) -> Run:
        run = self.graph().current(step)
        if run is None:
            raise KeyError(f'no successful run of {step!r} to mark')
        return run


def _array_params(spec: OpSpec) -> tuple[str, ...]:
    """Which of an op's parameters are arrays.

    A wire type rather than a role: an array parameter may declare no role --
    deciding what to show it as is the host's business -- and a run still has
    to know it was given a handle for it.
    """
    return tuple(
        param.name
        for param in spec.params
        if type_spec(param.type).name == NDARRAY
    )

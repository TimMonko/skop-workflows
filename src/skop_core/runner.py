"""Recording, as a layer around a runner.

Nothing here knows about napari or Icechunk, and nothing here runs an op: that
is the inner runner's job, and the inner runner is scikit-ops' own, so an op
that names an environment runs in it exactly as it would without a recorder.
A host supplies arrays, names the step an op's output fills, and gets the
result back.

There are two ways in. :class:`Recorder` is called: ``run(fn, step, args)``.
:class:`RecordingRunner` is *listened through*: it looks like a scikit-ops
runner, so whatever already runs ops -- a panel, a script, a workflow calling
``skop.run`` -- is recorded by being pointed at it, and changes nothing else.
"""

from __future__ import annotations

import collections.abc
import contextvars
import typing
import uuid
from collections.abc import Callable, Mapping
from typing import Any, Protocol

import numpy as np
from skop import NDARRAY, OpSpec, is_op, type_spec

from .derived import Graph
from .params import is_json, to_json
from .record import ACCEPTED, EDITED, REVERTED, Event, Handle, Root, Run
from .store import Store


class MissingRoot(ValueError):
    """An array reached an op without the store having issued it a handle."""


class Runner(Protocol):
    """What a runner has to do: call an op and return its result.

    scikit-ops' ``Runner`` is one. It takes more than this -- ``plans``,
    ``on_progress``, ``on_start`` -- and the recorder passes those through
    untouched, so what a caller asked of the runner reaches it.
    """

    def run(self, fn: Callable, args: dict, **options: Any) -> Any: ...


class InProcess:
    """The simplest runner: call the function here.

    It has no worker to report from and no task to cancel, so the options a
    real runner honours are accepted and ignored.
    """

    def run(self, fn: Callable, args: dict, **options: Any) -> Any:
        return fn(**args)


#: The run, and its step, that a nested call is made from. A context variable
#: rather than an attribute: a workflow's calls happen on whichever thread the
#: runner used, and two threads must not see each other's parent.
_enclosing: contextvars.ContextVar[tuple[str, str] | None] = (
    contextvars.ContextVar('skop_enclosing_run', default=None)
)

#: What a scikit-ops runner takes besides the op's own arguments. Anything else
#: handed to ``RecordingRunner.run`` is an argument of the op.
_OPTIONS = frozenset(
    {'variant', 'axes', 'plans', 'position', 'on_progress', 'on_start'}
)


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
        #: Where an op ID is turned back into the function it names, when the
        #: op's own parameter does not say. A host that has a registry sets it.
        self.registry: Mapping[str, Callable] | None = None
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

    def run(
        self,
        fn: Callable,
        step: str,
        args: dict[str, Any],
        **options: Any,
    ) -> Any:
        """Call an op through the inner runner, and write the call down.

        ``options`` are the inner runner's, not the op's: progress, a cancel
        handle, an axis plan. A call made while another is running -- a
        workflow's -- is recorded as that run's child.
        """
        spec = OpSpec.from_op(fn)
        # A parameter may be an op itself -- a workflow's choice of kernel --
        # which is recorded as the op's ID and arrives here as one on a replay.
        args = self._revive(spec, args)
        inputs = self._inputs(spec, args)
        params = {
            name: _recordable(value)
            for name, value in args.items()
            if name not in inputs
        }
        for name, value in params.items():
            if not is_json(value):
                raise TypeError(
                    f'{name}={value!r} is not JSON, so it cannot be recorded'
                )

        # The id is issued before the call so that what the call makes can name
        # it as their parent; the record itself is only written afterwards.
        run_id = _new_id()
        enclosing = _enclosing.get()
        parent = enclosing[0] if enclosing else None
        token = _enclosing.set((run_id, step))
        try:
            result = self.inner.run(fn, args, **options)
        except Exception as error:  # noqa: BLE001 -- a failed run is recorded
            self.store.append(
                Run(
                    id=run_id,
                    step=step,
                    op=spec.name,
                    inputs=inputs,
                    params=params,
                    status='failed',
                    error=f'{type(error).__name__}: {error}',
                    op_version=self.version,
                    parent=parent,
                )
            )
            raise
        finally:
            _enclosing.reset(token)

        outputs = self._save(spec, step, result)
        self.store.append(
            Run(
                id=run_id,
                step=step,
                op=spec.name,
                inputs=inputs,
                outputs=outputs,
                params=params,
                op_version=self.version,
                parent=parent,
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

    def _revive(self, spec: OpSpec, args: dict[str, Any]) -> dict[str, Any]:
        """Turn the op IDs a recipe holds back into the ops they name.

        Only a parameter that takes a function is touched, and only when it was
        handed a string: a recipe never holds a callable (decision 2), so this
        is where one comes back. The parameter's own choices are asked first,
        since they are the ops it was written to accept; the registry is for
        an op outside them.
        """
        found = dict(args)
        for param in spec.params:
            value = found.get(param.name)
            if not isinstance(value, str) or not _takes_function(param):
                continue
            options = getattr(param.choices, 'options', ())
            named = {
                OpSpec.from_op(candidate).name: candidate
                for _, candidate in options
                if is_op(candidate)
            }
            fn = named.get(value) or (self.registry or {}).get(value)
            if fn is None:
                raise KeyError(
                    f'{param.name}={value!r} is not an op this run can find'
                )
            found[param.name] = fn
        return found

    def _inputs(self, spec: OpSpec, args: dict[str, Any]) -> dict[str, Handle]:
        found = {}
        optional = {p.name for p in spec.params if not p.required}
        for name in _array_params(spec):
            value = args.get(name)
            if value is None and name in optional:
                # An array the op may do without, and was not given, is not an
                # input at all: it is recorded as the parameter it is, None.
                continue
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
        # ``OpSpec.outputs`` are named: a single unnamed output is called
        # 'result' (or is the Out/Mut parameter's name, or a NamedTuple's
        # fields). Each also carries a role, which the host reads when it has
        # a viewer to draw into.
        names = [output.name for output in spec.outputs]
        if len(names) == 1:
            return {names[0]: self.store.put(step, result)}
        # scikit-ops hands several outputs back as a NamedTuple, which is
        # read by field; a plain mapping is read by key.
        return {
            name: self.store.put(
                f'{step}.{name}',
                getattr(result, name)
                if hasattr(result, '_fields')
                else result[name],
            )
            for name in names
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


class RecordingRunner:
    """A scikit-ops runner that writes down what passes through it.

    It is built to be *pointed at*, not called by a host that already knows
    what it wants recorded. A panel that runs an op, a script, and a workflow
    calling ``skop.run`` all say ``runner.run(fn, args, ...)``; give them this
    in place of the runner and they are recorded, and nothing else about how
    they work has to change. That is the difference from :class:`Recorder`,
    which is what a host calls when it is the one deciding to run something.

    A workflow is the case it exists for. ``skop.run`` inside a workflow goes
    to the *ambient* runner (decision 16), so a workflow run through this is
    recorded as a run of its own with each op it called recorded beneath it.
    Without that the recorder would see only the call that went in, and
    nothing about what that call did.

    Parameters
    ----------
    recorder
        Where the runs are written, and the runner that does the work.
    step_for
        Names the step a call fills, given the op's spec and the graph so far.
        The default is the op's function name. A call nested in a workflow is
        always prefixed with its parent's step, so the same op used in two
        workflows is two steps.
    """

    def __init__(
        self,
        recorder: Recorder,
        step_for: Callable[[OpSpec, Graph], str] | None = None,
    ) -> None:
        self.recorder = recorder
        self._step_for = step_for or _function_name

    def run(
        self,
        fn: Callable,
        args: dict | None = None,
        *,
        on_recorded: Callable[[str], None] | None = None,
        **kwargs: Any,
    ) -> Any:
        """Run an op through the inner runner, recorded.

        ``on_recorded`` is told the step a call filled, once, and only for a
        call made from outside any workflow: those are the runs whose output a
        caller goes on to draw, where the calls inside are detail.
        """
        options = {k: kwargs.pop(k) for k in tuple(kwargs) if k in _OPTIONS}
        call = dict(args or {})
        call.update(kwargs)

        spec = OpSpec.from_op(fn)
        enclosing = _enclosing.get()
        step = self._step_for(spec, self.recorder.graph())
        if enclosing is not None:
            step = f'{enclosing[1]}.{step}'

        if spec.is_workflow:
            # Install ourselves as the ambient runner, so the calls the
            # workflow makes come back through here. The workflow's own
            # progress and cancel handle go to the ambient, which hands them
            # to what it calls; giving them to the inner runner as well would
            # tell the caller about two tasks, and a cancel would reach the
            # one with nothing running.
            from skop import ambient

            on_progress = options.pop('on_progress', None)
            on_start = options.pop('on_start', None)
            with ambient(self, on_progress, on_start):
                result = self.recorder.run(fn, step, call, **options)
        else:
            result = self.recorder.run(fn, step, call, **options)

        if on_recorded is not None and enclosing is None:
            on_recorded(step)
        return result


def _takes_function(param: Any) -> bool:
    """Whether a parameter is given a function rather than data."""
    return param.type in (collections.abc.Callable, typing.Callable) or bool(
        getattr(param.choices, 'options', None)
    )


def _recordable(value: Any) -> Any:
    """A parameter as it is written down: an op as its ID, the rest as JSON."""
    if callable(value) and is_op(value):
        return OpSpec.from_op(value).name
    return to_json(value)


def _function_name(spec: OpSpec, graph: Graph) -> str:
    return spec.function


def _array_params(spec: OpSpec) -> tuple[str, ...]:
    """Which of an op's parameters are arrays the caller supplies.

    An ``Out`` buffer is not one: the caller allocates it for the op to fill,
    and what comes out of it is the output.

    A wire type rather than a role: an array parameter may declare no role --
    deciding what to show it as is the host's business -- and a run still has
    to know it was given a handle for it.
    """
    return tuple(
        param.name
        for param in spec.inputs
        if type_spec(param.type).name == NDARRAY
    )

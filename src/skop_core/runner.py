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
Both end in :meth:`Recorder.run`, which is the only place a run is written.
"""

from __future__ import annotations

import collections.abc
import contextlib
import contextvars
import os
import time
import types
import typing
import uuid
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path, PurePath
from typing import Any, Protocol, Union, get_args, get_origin

import numpy as np
from skop import (
    FUNCTION,
    NDARRAY,
    PATH,
    AdaptationPlan,
    OpSpec,
    is_op,
    type_spec,
)
from skop.types import Array

from .derived import Graph
from .params import is_json, to_json
from .record import (
    ACCEPTED,
    CANCELLED,
    EDITED,
    FAILED,
    OK,
    REVERTED,
    Detached,
    Event,
    Handle,
    Root,
    Run,
)
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

    It has no worker to report from and no task to cancel, so progress and
    cancel handles are accepted and ignored. Axis plans are honoured, the way
    scikit-ops' worker honours them, so a step recorded with a plan comes out
    the same shape when it is replayed here.
    """

    def run(self, fn: Callable, args: dict, **options: Any) -> Any:
        plans = dict(options.get('plans') or {})
        for name, labels in (options.get('axes') or {}).items():
            if name not in plans:
                from skop import plan

                plans[name] = plan(
                    fn, name, args[name], labels, options.get('position')
                )
        if not plans:
            return fn(**args)
        from skop._adapt import execute

        return execute(OpSpec.from_op(fn), fn, dict(args), plans)


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
#: The options that say *how* to run rather than who to tell: written into the
#: run, and asked again when the step is run again.
_RECORDED_OPTIONS = ('variant', 'axes', 'plans', 'position')


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


def _function_name(spec: OpSpec, graph: Graph) -> str:
    return spec.function


def outputs_of(
    spec: OpSpec, result: Any, args: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    """An op's result, labelled with its output names.

    ``Runner.run`` hands back what the op returned: a bare value for a plain
    return type, a NamedTuple when the op declared one, a plain tuple when it
    declared ``tuple[...]``. A computer- or inplace-form op returns nothing
    of note, and its outputs are the buffers the caller passed in ``args``.

    The NamedTuple case is tested on its fields rather than on how many there
    are, since a NamedTuple with one field names its one output.
    """
    names = tuple(output.name for output in spec.outputs)
    if not names:
        return {}
    if spec.form != FUNCTION:
        given = args or {}
        return {name: given[name] for name in names if name in given}
    if getattr(result, '_fields', None) == names:
        return dict(zip(names, result, strict=True))
    if len(names) == 1:
        return {names[0]: result}
    if isinstance(result, Mapping):
        return {name: result[name] for name in names}
    return dict(zip(names, result, strict=True))


class Recorder:
    """A host's handle on recording: a store, and a runner to execute with.

    Every call of an op goes through :meth:`run`, which records it: array
    arguments must already have a handle, parameters must be JSON, and the
    result is saved under the step name before the run is appended.

    Parameters
    ----------
    store
        Where arrays and records go.
    inner
        The runner that executes; :class:`InProcess` when none is given.
    version
        What ran: the package version, and the git commit for a checkout.
    step_for
        Names the step a call fills when the caller does not: a workflow's
        nested calls, and every call a :class:`RecordingRunner` sees. Given
        the op's spec and the graph so far; the op's function name when left
        out.
    """

    def __init__(
        self,
        store: Store,
        inner: Runner | None = None,
        version: str | None = None,
        step_for: Callable[[OpSpec, Graph], str] | None = None,
    ) -> None:
        self.store = store
        self.inner = inner or InProcess()
        #: Where an op ID is turned back into the function it names, when the
        #: op's own parameter does not say. A host that has a registry sets it.
        self.registry: Mapping[str, Callable] | None = None
        self.version = version
        self.step_for = step_for or _function_name

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

    def root_gone(self, name: str) -> Detached:
        """Record that an input's layer is no longer there.

        The data is kept, and a step that read it still says what it read. The
        mark is what lets the graph say the input has no home any more, until
        the name is declared again.
        """
        record = Detached(id=_new_id(), name=name)
        self.store.append(record)
        return record

    def graph(self) -> Graph:
        return Graph(self.store.records())

    def mark_edited(self, step: str, note: str | None = None) -> Event:
        """Record that a step's output was changed by hand."""
        return self._mark(step, EDITED, note)

    def mark_reverted(self, step: str, note: str | None = None) -> Event:
        """Record that a step's output went back to what its run produced.

        The edit stays in the log; this mark supersedes it, so the step stops
        being edited and nothing downstream counts as affected any more.
        """
        return self._mark(step, REVERTED, note)

    def accept_edit(
        self,
        step: str,
        array: np.ndarray | None = None,
        *,
        output: str | None = None,
        note: str | None = None,
    ) -> Event:
        """Keep the hand-made pixels in place of what the step's run made.

        The pixels are stored, and from then on they are the step's output:
        what reads the step reads them, what read the old output is stale,
        and :meth:`produce` never runs the step again over them. A recipe
        cannot recompute them, so it asks for them as a root named after the
        step (decision 34). Running the step again is a new run, and the kept
        pixels stop standing in for it.

        ``array`` is what the user kept; without it the run's own output is
        what is kept, for a host that cannot hand the pixels over. ``output``
        names which output they replace, when the step has several.
        """
        run = self._current_or_raise(step)
        handle = None
        if array is not None:
            name = output
            if name is None:
                if len(run.outputs) != 1:
                    raise ValueError(
                        f'{step!r} has outputs {sorted(run.outputs)}; say '
                        f'which one the kept pixels replace'
                    )
                name = next(iter(run.outputs))
            elif name not in run.outputs:
                raise KeyError(f'{step!r} has no output {name!r}')
            path = step if len(run.outputs) == 1 else f'{step}.{name}'
            handle = self.store.put(path, array)
            output = name if len(run.outputs) > 1 else None
        event = Event(
            id=_new_id(),
            kind=ACCEPTED,
            run=run.id,
            note=note,
            handle=handle,
            output=output,
        )
        self.store.append(event)
        return event

    # -- running ---------------------------------------------------------

    def run(
        self,
        fn: Callable,
        step: str,
        args: dict[str, Any],
        *,
        through: RecordingRunner | None = None,
        **options: Any,
    ) -> Any:
        """Call an op through the inner runner, and write the call down.

        ``options`` are the inner runner's, not the op's: progress, a cancel
        handle, an axis plan. The ones that say how to run are recorded with
        the run, so that running the step again asks the same.

        A workflow's own ``skop.run`` calls come back through a
        :class:`RecordingRunner` -- ``through``, or one over this recorder --
        so each is recorded as a child of this run, and runs on this
        recorder's inner runner rather than on some default nobody chose.
        """
        spec = OpSpec.from_op(fn)
        # A parameter may be an op itself -- a workflow's choice of kernel --
        # which is recorded as the op's ID and arrives here as one on a replay.
        args = self._revive(spec, args)
        inputs = self._inputs(spec, args)
        buffers = _buffers(spec)
        paths = {
            name: os.fspath(args[name])
            for name in _path_params(spec)
            if args.get(name) is not None
        }
        params = {
            name: _recordable(value)
            for name, value in args.items()
            if name not in inputs and name not in buffers and name not in paths
        }
        for name, value in params.items():
            if not is_json(value):
                raise TypeError(
                    f'{name}={value!r} is not JSON, so it cannot be recorded'
                )
        recorded = _recorded_options(options)

        # The id is issued before the call so that what the call makes can name
        # it as their parent; the record itself is only written afterwards.
        run_id = _new_id()
        enclosing = _enclosing.get()
        record = {
            'id': run_id,
            'step': step,
            'op': spec.name,
            'inputs': inputs,
            'params': params,
            'op_version': self.version,
            'parent': enclosing[0] if enclosing else None,
            'options': recorded,
            'paths': paths,
        }
        # The caller's cancel handle is watched on its way past, since an op
        # that is cancelled may stop early and return what it has so far --
        # which must not become the step's result.
        watched: list[_Watched] = []
        asked = options.get('on_start')

        def on_start(task: Any) -> None:
            handed = _Watched(task)
            watched.append(handed)
            if asked is not None:
                asked(handed)

        options['on_start'] = on_start
        record['started'] = datetime.now(timezone.utc).isoformat(
            timespec='seconds'
        )
        clock = time.perf_counter()
        token = _enclosing.set((run_id, step))
        try:
            with self._nested(spec, through, options):
                result = self.inner.run(fn, args, **options)
            outputs = self._save(spec, step, result, args)
        except Exception as error:  # noqa: BLE001 -- a failed run is recorded
            cancelled = any(handed.cancelled for handed in watched)
            self.store.append(
                Run(
                    **record,
                    status=CANCELLED if cancelled else FAILED,
                    error=f'{type(error).__name__}: {error}',
                    duration=_since(clock),
                )
            )
            raise
        finally:
            _enclosing.reset(token)
        cancelled = any(handed.cancelled for handed in watched)
        self.store.append(
            Run(
                **record,
                outputs=outputs,
                status=CANCELLED if cancelled else OK,
                duration=_since(clock),
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
        run = self._current_or_raise(step, graph)
        args: dict[str, Any] = {}
        for name, handle in run.inputs.items():
            now = graph.now(handle)
            if now is None:
                raise KeyError(
                    f'{step!r} read {name!r} from an output its source no '
                    f'longer makes'
                )
            args[name] = self.store.get(now)
        return self._again(fn, run, args)

    def rerun(self, fn: Callable, step: str) -> Any:
        """Run a step again from the run it is on: its inputs, its params.

        Unlike :meth:`update` this does not go looking for newer data; it is
        the deliberate "do that again", and it adds a run rather than moving
        the step (decision 3).
        """
        run = self._current_or_raise(step)
        args = {
            name: self.store.get(handle) for name, handle in run.inputs.items()
        }
        return self._again(fn, run, args)

    def produce(
        self, targets: list[str], registry: Mapping[str, Callable]
    ) -> list[str]:
        """Bring the targets' closure up to date, and say what that ran.

        Every step in the closure keeps the parameters it was last run with
        and takes its inputs from wherever they now are; a step already
        current is left alone, and so is one whose edit was kept. It is
        decision 8's manual gesture applied to a whole selection rather than
        one step -- the call behind "run what is needed".

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

    def _again(self, fn: Callable, run: Run, args: dict[str, Any]) -> Any:
        """Call a step's op again with its parameters, buffers and options."""
        args.update(run.params)
        args.update(run.paths)
        for name in _buffers(OpSpec.from_op(fn)):
            if name in run.outputs:
                # A buffer is the caller's to allocate; the last one the step
                # filled says what shape and type it has to be.
                args[name] = np.empty_like(self.store.get(run.outputs[name]))
        return self.run(fn, run.step, args, **_revived_options(run.options))

    @contextlib.contextmanager
    def _nested(
        self,
        spec: OpSpec,
        through: RecordingRunner | None,
        options: dict[str, Any],
    ) -> typing.Generator[None]:
        """Make the recorder ambient while a workflow runs, so its calls are
        recorded; an op that is not a workflow calls nothing, and needs none.

        The caller's progress and cancel handles go to the ambient, whose task
        scikit-ops' runner then uses for the workflow itself as well as for
        what it calls: one task, so the caller hears everything and a cancel
        reaches both the workflow and the sub-op it is waiting on.
        """
        if not spec.is_workflow:
            yield
            return
        from skop import ambient

        with ambient(
            through or RecordingRunner(self),
            options.pop('on_progress', None),
            options.pop('on_start', None),
        ):
            yield

    def _revive(self, spec: OpSpec, args: dict[str, Any]) -> dict[str, Any]:
        """Turn the JSON a recipe holds back into what the op declared.

        An enum member and a path are recorded as plain JSON; the type the op
        declares is what they become again. An op ID becomes the op it names,
        but only for a parameter that takes a function, and only when it was
        handed a string: a recipe never holds a callable (decision 2), so
        this is where one comes back. The parameter's own choices are asked
        first, since they are the ops it was written to accept; the registry
        is for an op outside them.
        """
        found = dict(args)
        for param in spec.params:
            value = found.get(param.name)
            declared = _declared_class(param.type)
            if declared is not None and value is not None:
                if issubclass(declared, Enum) and not isinstance(
                    value, declared
                ):
                    found[param.name] = declared(value)
                    continue
                if issubclass(declared, PurePath) and isinstance(value, str):
                    found[param.name] = declared(value)
                    continue
            if type_spec(param.type).name == PATH and isinstance(value, str):
                found[param.name] = Path(value)
                continue
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

    def sources(self, spec: OpSpec, args: dict[str, Any]) -> dict[str, str]:
        """Where each array argument comes from, as the graph names it.

        A root by its name, a step's output by the step's. An array the store
        never issued has no source, and is left out. This is what tells a call
        on the same data from a call on other data, before either is recorded.
        """
        graph = self.graph()
        found = {}
        for name in _array_params(spec):
            value = args.get(name)
            handle = (
                self.store.handle_of(value)
                if isinstance(value, Array)
                else None
            )
            if handle is not None:
                source = graph.source_of(handle)
                if source is not None:
                    found[name] = source
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
            # Anything array-shaped, as scikit-ops' runner takes it -- dask,
            # zarr, xarray -- known by identity like a numpy array is.
            if not isinstance(value, Array):
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

    def _save(
        self, spec: OpSpec, step: str, result: Any, args: dict[str, Any]
    ) -> dict[str, Handle]:
        """Store each output: under the step's name, or ``step.output``."""
        values = outputs_of(spec, result, args)
        if len(values) == 1:
            ((name, value),) = values.items()
            return {name: self.store.put(step, value)}
        return {
            name: self.store.put(f'{step}.{name}', value)
            for name, value in values.items()
        }

    def _mark(self, step: str, kind: str, note: str | None) -> Event:
        run = self._current_or_raise(step)
        event = Event(id=_new_id(), kind=kind, run=run.id, note=note)
        self.store.append(event)
        return event

    def _current_or_raise(self, step: str, graph: Graph | None = None) -> Run:
        run = (graph or self.graph()).current(step)
        if run is None:
            raise KeyError(f'no successful run of {step!r}')
        return run


class RecordingRunner:
    """A scikit-ops runner that writes down what passes through it.

    It is built to be *pointed at*, not called by a host that already knows
    what it wants recorded. A panel that runs an op, a script, and a workflow
    calling ``skop.run`` all say ``runner.run(fn, args, ...)``; give them this
    in place of the runner and they are recorded, and nothing else about how
    they work has to change. That is the difference from :class:`Recorder`,
    which is what a host calls when it is the one deciding to run something.

    Parameters
    ----------
    recorder
        Where the runs are written, and the runner that does the work.
    step_for
        Names the step a call fills, given the op's spec and the graph so far.
        The recorder's own ``step_for`` when left out. A call nested in a
        workflow is always prefixed with its parent's step, so the same op
        used in two workflows is two steps.
    """

    def __init__(
        self,
        recorder: Recorder,
        step_for: Callable[[OpSpec, Graph], str] | None = None,
    ) -> None:
        self.recorder = recorder
        self._step_for = step_for or recorder.step_for

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
        step = self._step(spec, call, enclosing)
        result = self.recorder.run(fn, step, call, through=self, **options)
        if on_recorded is not None and enclosing is None:
            on_recorded(step)
        return result

    def _step(
        self,
        spec: OpSpec,
        args: dict[str, Any],
        enclosing: tuple[str, str] | None,
    ) -> str:
        """The step a call fills: an earlier one on the same data, or a new one.

        A step is an op applied to particular inputs. Calling it again on the
        same inputs -- with other parameters, or after they moved -- is another
        run of that step, which is what makes trying parameters a history
        rather than a pile. Calling it on *other* inputs is other work, and
        gets a step of its own: ``smooth``, then ``smooth_2``.

        Inputs are compared by where they come from (a root's name, a step's
        name), not by their pixels, so a root that moved is still the same
        input and its reader goes stale rather than being forked.
        """
        graph = self.recorder.graph()
        base = self._step_for(spec, graph)
        if enclosing is not None:
            base = f'{enclosing[1]}.{base}'
        wanted = self.recorder.sources(spec, args)
        name, count = base, 1
        while name in graph.by_step:
            last = graph.runs_of(name)[-1]
            if last.op == spec.name and graph.sources_of(last) == wanted:
                return name
            count += 1
            name = f'{base}_{count}'
        return name


class _Watched:
    """A runner's task as the caller is handed it: it remembers a cancel.

    Everything else is the task's own, so a caller that holds this holds the
    task. A worker's task says nothing afterwards about having been asked to
    stop -- an op that honours a cancel simply returns early -- so the ask is
    noted here, where it passes.
    """

    def __init__(self, task: Any) -> None:
        self._task = task
        self.cancelled = False

    def cancel(self) -> None:
        self.cancelled = True
        self._task.cancel()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._task, name)


def _since(clock: float) -> float:
    return round(time.perf_counter() - clock, 4)


def _recorded_options(options: Mapping[str, Any]) -> dict[str, Any]:
    """The runner options worth writing down, as JSON."""
    found: dict[str, Any] = {}
    for key in _RECORDED_OPTIONS:
        value = options.get(key)
        if value is None:
            continue
        if key == 'plans':
            value = {
                name: plan.to_dict()
                if isinstance(plan, AdaptationPlan)
                else plan
                for name, plan in value.items()
            }
        found[key] = to_json(value)
        if not is_json(found[key]):
            raise TypeError(
                f'{key}={value!r} is not JSON, so it cannot be recorded'
            )
    return found


def _revived_options(options: Mapping[str, Any]) -> dict[str, Any]:
    """Recorded runner options, as a runner takes them again."""
    found = dict(options)
    if 'plans' in found:
        found['plans'] = {
            name: AdaptationPlan.from_dict(plan)
            for name, plan in found['plans'].items()
        }
    return found


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


def _declared_class(annotation: Any) -> type | None:
    """The class a parameter declares, seeing through ``X | None``."""
    if get_origin(annotation) in (Union, types.UnionType):
        found = [a for a in get_args(annotation) if a is not type(None)]
        annotation = found[0] if len(found) == 1 else None
    return annotation if isinstance(annotation, type) else None


def _path_params(spec: OpSpec) -> tuple[str, ...]:
    """The parameters that name a file rather than hold a value."""
    return tuple(
        param.name
        for param in spec.params
        if type_spec(param.type).name == PATH
    )


def _buffers(spec: OpSpec) -> set[str]:
    """The ``Out`` parameters: buffers the caller allocates and the op fills."""
    supplied = {param.name for param in spec.inputs}
    return {param.name for param in spec.params} - supplied


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

"""Recipe files, and replaying them.

A recipe holds op IDs and JSON parameters, never callables and never a handle.
It records a default target set and contains exactly the steps that set needs,
so every intermediate is present and can itself be asked for later.

Each input says where it comes from in so many words: ``{'root': name}`` or
``{'step': name, 'output': name}``. A root and a step may share a name -- a
layer called ``smoothed`` beside the step that made it -- and a step may have
several outputs, so neither can be left for a reader to guess.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path, PurePath
from typing import Any

import numpy as np
from skop import OpSpec, Role

from .derived import Graph
from .runner import Recorder, _revived_options, outputs_of
from .store import Store

FORMAT = 2


class MissingOp(KeyError):
    """A recipe names an op this interpreter cannot resolve."""


class UnboundRoot(ValueError):
    """A replay was not given an input the recipe needs."""


def export(
    graph: Graph, targets: list[str] | None, store: Store
) -> dict[str, Any]:
    """The closure of the targets, as a portable dict.

    ``targets`` defaults to the graph's leaves. Shapes and dtypes come from
    the store; names come from the log, and nothing here parses a handle.

    A step whose hand edit was kept is not exported as a step: its pixels
    cannot be recomputed, so it becomes a root the replay must supply,
    named after the step (``step.output`` when it has several outputs).
    """
    wanted = list(targets) if targets is not None else graph.leaves()
    closure = graph.closure(wanted)
    unknown = [t for t in wanted if t not in closure]
    if unknown:
        raise KeyError(
            f'no successful run to export for {unknown}; a target must be a '
            f'step that ran'
        )
    kept = [step for step in closure if graph.is_accepted(step)]
    if any(t in kept for t in wanted):
        raise ValueError(
            f'{[t for t in wanted if t in kept]} hold pixels kept by hand, '
            f'which a replay cannot produce; choose what reads them instead'
        )

    roots: dict[str, dict[str, Any]] = {}
    #: Which roots stand for kept pixels, so a layer root of the same name
    #: cannot quietly be taken for one.
    kept_roots: set[str] = set()

    def bind(name: str, handle: str, from_kept: bool) -> dict[str, str]:
        if name in roots and (name in kept_roots) != from_kept:
            raise ValueError(
                f'{name!r} is both an input and a step whose edit was kept; '
                f'rename one of them before exporting'
            )
        if name not in roots:
            described = store.describe(handle)
            roots[name] = {
                'ndim': described['ndim'],
                'dtype': described['dtype'],
            }
            if from_kept:
                kept_roots.add(name)
        return {'root': name}

    def ref(handle: str) -> dict[str, str]:
        root = graph.root_of(handle)
        if root is not None:
            return bind(root.name, handle, from_kept=False)
        origin = graph.origin(handle)
        if origin is None:
            raise ValueError(f'{handle!r} came from nowhere the log records')
        step, output = origin
        if graph.is_accepted(step):
            run = graph.current(step)
            assert run is not None
            name = step if len(run.outputs) == 1 else f'{step}.{output}'
            latest = graph.latest(step, output)
            assert latest is not None
            return bind(name, latest, from_kept=True)
        return {'step': step, 'output': output}

    steps: dict[str, dict[str, Any]] = {}
    for step in closure:
        if step in kept:
            continue
        run = graph.current(step)
        assert run is not None, step  # a closure names only current steps
        inputs = {param: ref(h) for param, h in run.inputs.items()}
        for param, path in run.paths.items():
            # A file is never carried: it is asked for, under a name of its
            # own, with the file's name as a hint (decision 6).
            name = f'{step}.{param}'
            roots[name] = {'path': PurePath(path).name}
            inputs[param] = {'root': name}
        entry: dict[str, Any] = {
            'op': run.op,
            'inputs': inputs,
            'params': dict(run.params),
        }
        if run.options:
            entry['options'] = dict(run.options)
        steps[step] = entry

    return {
        'format': FORMAT,
        'targets': wanted,
        'roots': roots,
        'steps': steps,
        'caution': {
            'edited': [s for s in steps if graph.is_edited(s)],
            'affected': [s for s in steps if graph.is_affected(s)],
            'kept': kept,
        },
    }


def save(recipe: dict[str, Any], path: str | Path) -> None:
    """Write a recipe as pretty-printed JSON, for humans and diffs."""
    _check_format(recipe)
    text = json.dumps(recipe, indent=2, ensure_ascii=False)
    Path(path).write_text(text + '\n', encoding='utf-8')


def load(path: str | Path) -> dict[str, Any]:
    """Read a recipe written by :func:`save`, refusing a format it is not."""
    recipe = json.loads(Path(path).read_text(encoding='utf-8'))
    _check_format(recipe)
    return recipe


def plan(
    recipe: dict[str, Any], targets: list[str] | None = None
) -> list[str]:
    """The recipe's steps needed for the targets, oldest first."""
    _check_format(recipe)
    wanted = list(targets if targets is not None else recipe['targets'])
    unknown = [t for t in wanted if t not in recipe['steps']]
    if unknown:
        raise KeyError(f'not in this recipe: {unknown}')
    order: list[str] = []
    seen: set[str] = set()

    def visit(step: str) -> None:
        if step in seen:
            return
        seen.add(step)
        for ref in recipe['steps'][step]['inputs'].values():
            if 'step' in ref:
                visit(ref['step'])
        order.append(step)

    for target in wanted:
        visit(target)
    return order


@dataclass(frozen=True)
class RootNeed:
    """One input a replay has to be handed, as a host shows it."""

    name: str
    #: How many axes, and of what type, the recorded data had. None for a
    #: path, which is not data.
    ndim: int | None
    dtype: str | None
    #: What the ops that read it take it to be, when they agree.
    role: Role | None
    #: For a file: the recorded file's name, as a hint. None for an array.
    path_hint: str | None
    #: For pixels kept by hand: the step they stood in for.
    kept_for: str | None
    #: The recipe's steps that read it, in order.
    read_by: tuple[str, ...]

    @property
    def is_path(self) -> bool:
        return self.path_hint is not None


@dataclass
class Replayed:
    """What a replay did: each recipe step's result, and where it went."""

    #: Recipe step -> what its op returned.
    results: dict[str, Any] = field(default_factory=dict)
    #: Recipe step -> the session step it was recorded as. The same name in a
    #: fresh recorder; another (``otsu_2``) where the name was taken.
    steps: dict[str, str] = field(default_factory=dict)
    #: Whether a cancel stopped it before every step ran.
    cancelled: bool = False


class Prepared:
    """A recipe made ready to replay: what it needs, and whether it can run.

    Built with :func:`prepare` before any data is at hand, so a host can show
    which inputs to bind and which ops are missing; then :meth:`check` the
    bindings, and :meth:`run`.
    """

    def __init__(
        self,
        recipe: dict[str, Any],
        registry: Mapping[str, Callable],
        targets: list[str] | None = None,
    ) -> None:
        _check_format(recipe)
        self.recipe = recipe
        self.registry = registry
        self.targets = list(
            targets if targets is not None else recipe['targets']
        )
        self.steps = plan(recipe, self.targets)
        missing = sorted(
            {
                recipe['steps'][s]['op']
                for s in self.steps
                if recipe['steps'][s]['op'] not in registry
            }
        )
        #: Why this cannot run, in words; empty when it can.
        self.problems: list[str] = [
            f'no op {op!r} here: is the package that provides it installed?'
            for op in missing
        ]
        self.roots = [
            self._need(name) for name in _roots_read(recipe, self.steps)
        ]

    def _need(self, name: str) -> RootNeed:
        hint = self.recipe['roots'].get(name, {})
        read_by = tuple(
            step
            for step in self.steps
            if any(
                ref.get('root') == name
                for ref in self.recipe['steps'][step]['inputs'].values()
            )
        )
        roles: set[Role | None] = set()
        for step in read_by:
            entry = self.recipe['steps'][step]
            fn = self.registry.get(entry['op'])
            if fn is None:
                continue
            by_name = {p.name: p for p in OpSpec.from_op(fn).params}
            for param, ref in entry['inputs'].items():
                if ref.get('root') == name and param in by_name:
                    roles.add(by_name[param].role)
        kept = self.recipe.get('caution', {}).get('kept', [])
        kept_for = next(
            (s for s in kept if name == s or name.startswith(f'{s}.')), None
        )
        return RootNeed(
            name=name,
            ndim=hint.get('ndim'),
            dtype=hint.get('dtype'),
            role=roles.pop() if len(roles) == 1 else None,
            path_hint=hint.get('path'),
            kept_for=kept_for,
            read_by=read_by,
        )

    def check(self, roots: Mapping[str, Any]) -> None:
        """Everything a replay needs, verified before anything runs."""
        if self.problems:
            raise MissingOp(' '.join(self.problems))
        for need in self.roots:
            if need.name not in roots:
                raise UnboundRoot(
                    f'{need.name!r} is needed by {need.read_by[0]!r} and '
                    f'was not supplied'
                )
            value = roots[need.name]
            if need.is_path:
                if not isinstance(value, (str, os.PathLike)):
                    raise UnboundRoot(
                        f'{need.name!r} wants a path, got {value!r}'
                    )
                continue
            ndim = getattr(value, 'ndim', None)
            if ndim is None:
                ndim = np.ndim(value)
            if need.ndim is not None and ndim != need.ndim:
                raise UnboundRoot(
                    f'{need.name!r} wants {need.ndim} axes, got {ndim}'
                )

    def run(
        self,
        roots: Mapping[str, Any],
        recorder: Recorder,
        *,
        overrides: Mapping[str, Mapping[str, Any]] | None = None,
        name_step: Callable[[str, OpSpec, dict[str, Any]], str] | None = None,
        on_step: Callable[[int, int, str, str], None] | None = None,
        on_done: Callable[[str, str], None] | None = None,
        cancelled: Callable[[], bool] | None = None,
        **options: Any,
    ) -> Replayed:
        """Run the closure of the targets, recording each step.

        Parameters
        ----------
        roots
            Each root's data -- or, for a path root, the path.
        recorder
            Where the runs are recorded. An array this recorder's store
            already knows is used as it is: it is a root (or a step's output)
            under its own name already, and declaring it again under the
            recipe's name would take its identity from it. Only data the
            store has never seen is declared, under the recipe's name.
        overrides
            Parameters to change, by recipe step.
        name_step
            The session step a recipe step is recorded as, given the recipe
            step, its op and its arguments. By default the recipe's name,
            reused when the same op last ran there on the same inputs, and
            numbered (``otsu_2``) when the name is taken by other work.
        on_step, on_done
            Told ``(index, total, recipe step, session step)`` before a step
            runs, and ``(recipe step, session step)`` once it is recorded.
        cancelled
            Asked before each step; a true answer stops the replay there.
        options
            For the runner, on every step: ``on_progress``, ``on_start``.
        """
        overrides = dict(overrides or {})
        stray = sorted(set(overrides) - set(self.steps))
        if stray:
            raise KeyError(
                f'overrides for steps this replay does not run: {stray}'
            )
        self.check(roots)
        name_step = name_step or _default_namer(recorder)

        bound: dict[str, Any] = {}
        for need in self.roots:
            value = roots[need.name]
            if not need.is_path and recorder.store.handle_of(value) is None:
                recorder.root(need.name, value)
            bound[need.name] = value

        done = Replayed()
        outputs: dict[str, dict[str, Any]] = {}
        total = len(self.steps)
        for index, step in enumerate(self.steps):
            if cancelled is not None and cancelled():
                done.cancelled = True
                break
            entry = self.recipe['steps'][step]
            fn = self.registry[entry['op']]
            spec = OpSpec.from_op(fn)
            args: dict[str, Any] = {}
            for param, ref in entry['inputs'].items():
                if 'root' in ref:
                    args[param] = bound[ref['root']]
                else:
                    args[param] = outputs[ref['step']][ref['output']]
            args.update(entry['params'])
            args.update(overrides.get(step, {}))
            session_step = name_step(step, spec, args)
            if on_step is not None:
                on_step(index, total, step, session_step)
            asked = {**_revived_options(entry.get('options', {})), **options}
            done.results[step] = recorder.run(fn, session_step, args, **asked)
            done.steps[step] = session_step
            outputs[step] = outputs_of(spec, done.results[step], args)
            if on_done is not None:
                on_done(step, session_step)
        return done


def prepare(
    recipe: dict[str, Any],
    registry: Mapping[str, Callable],
    targets: list[str] | None = None,
) -> Prepared:
    """Make a recipe ready to replay; see :class:`Prepared`."""
    return Prepared(recipe, registry, targets)


def replay(
    recipe: dict[str, Any],
    roots: Mapping[str, Any],
    recorder: Recorder,
    registry: Mapping[str, Callable],
    targets: list[str] | None = None,
    overrides: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Run the closure of the targets and hand back their results.

    Everything is checked before anything runs: the ops resolve, every root
    the closure reads was supplied with the right number of axes, and every
    override names a step that will run. The replay is recorded like any
    other run. A host that needs more -- what to bind, progress, where each
    step went -- uses :func:`prepare`.
    """
    prepared = prepare(recipe, registry, targets)
    done = prepared.run(roots, recorder, overrides=overrides)
    return {step: done.results[step] for step in prepared.targets}


def _default_namer(
    recorder: Recorder,
) -> Callable[[str, OpSpec, dict[str, Any]], str]:
    """Decision 50 for a replay: same op on the same inputs, same step."""

    def name(step: str, spec: OpSpec, args: dict[str, Any]) -> str:
        graph = recorder.graph()
        wanted = recorder.sources(spec, args)
        candidate, count = step, 1
        while candidate in graph.by_step:
            last = graph.runs_of(candidate)[-1]
            if last.op == spec.name and graph.sources_of(last) == wanted:
                return candidate
            count += 1
            candidate = f'{step}_{count}'
        return candidate

    return name


def batch(
    recipe: dict[str, Any],
    items: Iterable[tuple[str, Mapping[str, np.ndarray]]],
    make_recorder: Callable[[str], Recorder],
    registry: Mapping[str, Callable],
    targets: list[str] | None = None,
    *,
    stop_on_failure: bool = False,
) -> list[dict[str, Any]]:
    """One replay per input, carrying on after a failure and reporting each.

    Each outcome names the item, says whether it worked and why not, and
    carries the recorder it was replayed into, where its results are stored.
    The results themselves are not held: a batch over a thousand files must
    not keep a thousand images in memory. ``stop_on_failure`` ends the batch
    at the first item that fails (decision 19).
    """
    outcomes = []
    for name, roots in items:
        outcome: dict[str, Any] = {
            'name': name,
            'ok': True,
            'error': None,
            'recorder': None,
        }
        try:
            outcome['recorder'] = make_recorder(name)
            replay(recipe, roots, outcome['recorder'], registry, targets)
        except Exception as error:  # noqa: BLE001 -- report each, keep going
            outcome.update(ok=False, error=f'{type(error).__name__}: {error}')
        outcomes.append(outcome)
        if stop_on_failure and not outcome['ok']:
            break
    return outcomes


def _check_format(recipe: Mapping[str, Any]) -> None:
    found = recipe.get('format')
    if found != FORMAT:
        raise ValueError(
            f'this is a recipe of format {found!r}; this version reads '
            f'format {FORMAT} only'
        )


def _is_path(recipe: Mapping[str, Any], root: str) -> bool:
    return 'path' in recipe['roots'].get(root, {})


def _roots_read(recipe: dict[str, Any], steps: list[str]) -> list[str]:
    """The roots the given steps read, in the order they are first read."""
    found: list[str] = []
    for step in steps:
        for ref in recipe['steps'][step]['inputs'].values():
            if 'root' in ref and ref['root'] not in found:
                found.append(ref['root'])
    return found

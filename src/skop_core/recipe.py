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
from pathlib import Path, PurePath
from typing import Any

import numpy as np
from skop import OpSpec

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


def check(
    recipe: dict[str, Any],
    roots: Mapping[str, np.ndarray],
    steps: list[str],
    registry: Mapping[str, Callable],
) -> None:
    """Everything a replay needs, verified before anything runs."""
    missing = [
        recipe['steps'][s]['op']
        for s in steps
        if recipe['steps'][s]['op'] not in registry
    ]
    if missing:
        raise MissingOp(f'cannot resolve: {sorted(set(missing))}')
    for step in steps:
        for ref in recipe['steps'][step]['inputs'].values():
            if 'root' not in ref:
                continue
            name = ref['root']
            if name not in roots:
                raise UnboundRoot(
                    f'{name!r} is needed by {step!r} and was not supplied'
                )
            if _is_path(recipe, name):
                if not isinstance(roots[name], (str, os.PathLike)):
                    raise UnboundRoot(
                        f'{name!r} wants a path, got {roots[name]!r}'
                    )
                continue
            hint = recipe['roots'].get(name, {}).get('ndim')
            ndim = np.ndim(roots[name])
            if hint is not None and ndim != hint:
                raise UnboundRoot(f'{name!r} wants {hint} axes, got {ndim}')


def replay(
    recipe: dict[str, Any],
    roots: Mapping[str, np.ndarray],
    recorder: Recorder,
    registry: Mapping[str, Callable],
    targets: list[str] | None = None,
    overrides: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Run the closure of the targets and hand back their results.

    Everything is checked before anything runs: the ops resolve, every root
    the closure reads was supplied with the right number of axes, and every
    override names a step that will run. Each root is declared in the
    recorder, so the replay is recorded like any other run.
    """
    steps = plan(recipe, targets)
    overrides = dict(overrides or {})
    stray = sorted(set(overrides) - set(steps))
    if stray:
        raise KeyError(
            f'overrides for steps this replay does not run: {stray}'
        )
    check(recipe, roots, steps, registry)

    bound: dict[str, Any] = {}
    used: set[int] = set()
    for name in _roots_read(recipe, steps):
        if _is_path(recipe, name):
            bound[name] = roots[name]  # a parameter, not data to store
            continue
        array = np.asarray(roots[name])
        if id(array) in used:
            # One array given for two roots: each name needs an object of its
            # own, since the store knows an array by identity.
            array = array.view()
        used.add(id(array))
        recorder.root(name, array)
        bound[name] = array

    results: dict[str, Any] = {}
    outputs: dict[str, dict[str, Any]] = {}
    for step in steps:
        entry = recipe['steps'][step]
        fn = registry[entry['op']]
        args: dict[str, Any] = {}
        for param, ref in entry['inputs'].items():
            if 'root' in ref:
                args[param] = bound[ref['root']]
            else:
                args[param] = outputs[ref['step']][ref['output']]
        args.update(entry['params'])
        args.update(overrides.get(step, {}))
        options = _revived_options(entry.get('options', {}))
        results[step] = recorder.run(fn, step, args, **options)
        outputs[step] = outputs_of(OpSpec.from_op(fn), results[step], args)
    wanted = targets if targets is not None else recipe['targets']
    return {step: results[step] for step in wanted}


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

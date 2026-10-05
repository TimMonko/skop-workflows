"""Recipe files, and replaying them.

A recipe holds op IDs and JSON parameters, never callables and never a handle.
It records a default target set and contains exactly the steps that set needs,
so every intermediate is present and can itself be asked for later.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

import numpy as np

from .derived import Graph
from .runner import Recorder
from .store import Store

FORMAT = 1


class MissingOp(KeyError):
    """A recipe names an op this interpreter cannot resolve."""


class UnboundRoot(ValueError):
    """A replay was not given an input the recipe needs."""


def export(graph: Graph, targets: list[str], store: Store) -> dict:
    """The closure of the targets, as a portable dict.

    Root names, shapes and dtypes come from the store; a recipe never keeps a
    handle, and nothing here parses one.
    """
    recipe: dict[str, Any] = {
        'format': FORMAT,
        'targets': list(targets),
        'roots': {},
        'steps': {},
    }
    for step in graph.closure(targets):
        run = graph.current(step)
        assert run is not None, step  # closure names only current steps
        inputs = {}
        for param, handle in run.inputs.items():
            upstream = graph.producer(handle)
            if upstream is not None:
                inputs[param] = f'@{upstream.step}'
                continue
            described = store.describe(handle)
            name = described['name']
            inputs[param] = f'@{name}'
            if name not in recipe['roots']:
                recipe['roots'][name] = {
                    'ndim': described['ndim'],
                    'dtype': described['dtype'],
                }
        recipe['steps'][step] = {
            'op': run.op,
            'inputs': inputs,
            'params': run.params,
        }
    recipe['caution'] = {
        'edited': [s for s in recipe['steps'] if graph.is_edited(s)],
        'affected': [s for s in recipe['steps'] if graph.is_affected(s)],
    }
    return recipe


def plan(recipe: dict, targets: list[str] | None = None) -> list[str]:
    """The recipe's steps needed for the targets, oldest first."""
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
            name = ref.lstrip('@')
            if name in recipe['steps']:
                visit(name)
        order.append(step)

    for target in wanted:
        visit(target)
    return order


def check(
    recipe: dict,
    roots: dict[str, np.ndarray],
    steps: list[str],
    registry: dict[str, Callable],
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
            name = ref.lstrip('@')
            if name in recipe['steps']:
                continue
            if name not in roots:
                raise UnboundRoot(
                    f'{name!r} is needed by {step!r} and was not supplied'
                )
            hint = recipe['roots'].get(name, {}).get('ndim')
            if hint is not None and roots[name].ndim != hint:
                raise UnboundRoot(
                    f'{name!r} wants {hint} axes, got {roots[name].ndim}'
                )


def replay(
    recipe: dict,
    roots: dict[str, np.ndarray],
    recorder: Recorder,
    registry: dict[str, Callable],
    targets: list[str] | None = None,
    overrides: dict[str, dict] | None = None,
) -> dict[str, np.ndarray]:
    """Run the closure of the targets and hand back their results."""
    steps = plan(recipe, targets)
    check(recipe, roots, steps, registry)
    for name, array in roots.items():
        if recorder.store.handle_of(array) is None:
            recorder.root(name, array)
    produced: dict[str, np.ndarray] = {}
    for step in steps:
        spec = recipe['steps'][step]
        args: dict[str, Any] = {}
        for param, ref in spec['inputs'].items():
            name = ref.lstrip('@')
            args[param] = roots[name] if name in roots else produced[name]
        args.update(spec['params'])
        args.update((overrides or {}).get(step, {}))
        produced[step] = recorder.run(registry[spec['op']], step, args)
    return {step: produced[step] for step in (targets or recipe['targets'])}


def batch(
    recipe: dict,
    items: Iterable[tuple[str, dict[str, np.ndarray]]],
    make_recorder: Callable[[str], Recorder],
    registry: dict[str, Callable],
    targets: list[str] | None = None,
) -> list[dict[str, Any]]:
    """One replay per input, carrying on after a failure and reporting each."""
    outcomes = []
    for name, roots in items:
        record: dict[str, Any] = {'name': name, 'ok': True, 'error': None}
        try:
            replay(recipe, roots, make_recorder(name), registry, targets)
        except Exception as error:  # noqa: BLE001 -- report each, keep going
            record.update(ok=False, error=f'{type(error).__name__}: {error}')
        outcomes.append(record)
    return outcomes

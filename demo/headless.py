"""The headless parts of the demo contract (docs/demo.md).

    python demo/headless.py

No napari and no environments built. Every claim the design makes about the
log, staleness, edits, targets, replay and batch is asserted here, against
three numpy-only ops that stand in for the scikit-ops ones.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from demo_ops import gaussian, otsu, percentile  # noqa: E402
from scenario import blobs, session  # noqa: E402

from skop_core import (  # noqa: E402
    MissingRoot,
    batch,
    export,
    info,
    replay,
)
from skop_visual import to_mermaid, view  # noqa: E402

REGISTRY = {info(fn).id: fn for fn in (percentile, gaussian, otsu)}
RESULTS: list[bool] = []


def check(label: str, ok: bool, detail: str = '') -> None:
    RESULTS.append(bool(ok))
    print(
        f'  {"PASS" if ok else "FAIL"}  {label}{f"  ({detail})" if detail else ""}'
    )


def main() -> int:
    work = Path(tempfile.mkdtemp(prefix='skop-demo-'))
    recorder = session(work, 'session')
    image = blobs(seed=1)

    print('\n1-2. an image, declared as a root, and a normalizing op')
    recorder.root('image', image)
    normalized = recorder.run(
        percentile, 'normalized', {'image': image, 'low': 1.0, 'high': 99.8}
    )
    check(
        'the root is stored under its name',
        recorder.store.handle_of(image) == 'image@v1',
    )

    print('\n3-4. a blur, tried at three sigmas, then a threshold')
    recorder.run(gaussian, 'smoothed', {'image': normalized, 'sigma': 2.0})
    recorder.run(gaussian, 'smoothed', {'image': normalized, 'sigma': 17.0})
    smoothed = recorder.run(
        gaussian, 'smoothed', {'image': normalized, 'sigma': 18.0}
    )
    recorder.run(otsu, 'labels', {'image': smoothed})
    graph = recorder.graph()
    check('one step, three runs', len(graph.runs_of('smoothed')) == 3)
    check(
        'the last run is current',
        graph.current('smoothed').params['sigma'] == 18.0,
    )
    check('labels is fresh', not graph.is_stale('labels'))

    print('\n5. the sigma goes back to 2, and the threshold is left behind')
    recorder.run(gaussian, 'smoothed', {'image': normalized, 'sigma': 2.0})
    graph = recorder.graph()
    check('labels is stale', graph.is_stale('labels'))
    check('nothing reran on its own', len(graph.runs_of('labels')) == 1)

    print('\n6. the labels are painted on by hand')
    recorder.mark_edited('labels', 'painted two cells')
    graph = recorder.graph()
    check('labels is edited', graph.is_edited('labels'))
    check('the smooth step is untouched', not graph.is_edited('smoothed'))
    try:
        recorder.run(
            gaussian, 'smoothed', {'image': blobs(seed=5), 'sigma': 2.0}
        )
    except MissingRoot as error:
        check('an undeclared array is refused', 'has no handle' in str(error))
    else:
        check('an undeclared array is refused', False)

    print('\n7. a branch that was tried and abandoned')
    recorder.run(gaussian, 'smoothed_alt', {'image': normalized, 'sigma': 9.0})
    recipe = export(recorder.graph(), ['labels'], store=recorder.store)
    check(
        'the recipe is the closure of the target',
        set(recipe['steps']) == {'normalized', 'smoothed', 'labels'},
    )
    check(
        'the abandoned branch is absent', 'smoothed_alt' not in recipe['steps']
    )
    check(
        'the discarded sigmas are absent', json.dumps(recipe).count('@v') == 0
    )
    check(
        'the root is named, with a shape hint',
        recipe['roots'] == {'image': {'ndim': 2, 'dtype': 'float64'}},
    )
    check('the edit is flagged', recipe['caution']['edited'] == ['labels'])
    partial = export(recorder.graph(), ['smoothed'], store=recorder.store)
    check(
        'an intermediate can be a target',
        set(partial['steps']) == {'normalized', 'smoothed'},
    )

    print('\n7b. the graph view')
    everything = to_mermaid(view(recorder.graph()))
    check('the whole session draws the branch', 'smoothed_alt' in everything)
    drawn = to_mermaid(
        view(recorder.graph(), store=recorder.store, targets=['labels'])
    )
    check('the target view is the closure', 'smoothed_alt' not in drawn)
    check('the edit is drawn', ':::edited' in drawn)
    check('the root is drawn once', drawn.count('root image') == 1)

    print('\n8. replay on another image, in a store of its own')
    second = session(work, 'replay-second')
    produced = replay(recipe, {'image': blobs(seed=7)}, second, REGISTRY)
    check('the target came back', set(produced) == {'labels'})
    check(
        'only what the target needs ran',
        [r.step for r in second.store.records()]
        == ['normalized', 'smoothed', 'labels'],
    )
    check(
        'the replay is recorded like any other run',
        set(second.graph().steps()) == {'normalized', 'smoothed', 'labels'},
    )
    check(
        'nothing is stale after a replay',
        not any(second.graph().is_stale(s) for s in second.graph().steps()),
    )

    print('\n9. batch over three files, one of them wrong')
    items = [
        ('a', {'image': blobs(seed=2)}),
        ('b', {'image': blobs(seed=3)}),
        ('bad', {'image': np.zeros((3, 64, 64))}),
    ]
    outcomes = batch(
        recipe,
        items,
        lambda name: session(work, f'batch-{name}'),
        REGISTRY,
    )
    check(
        'the good files pass and the bad one does not',
        [o['ok'] for o in outcomes] == [True, True, False],
    )
    check(
        'the failure says why', 'wants 2 axes' in (outcomes[2]['error'] or '')
    )
    check('the batch carried on', (work / 'batch-b' / 'log.jsonl').exists())

    print('\n10. asking for less')
    third = session(work, 'replay-partial')
    replay(
        recipe, {'image': blobs(seed=4)}, third, REGISTRY, targets=['smoothed']
    )
    check(
        'the intermediate was produced on its own',
        [r.step for r in third.store.records()] == ['normalized', 'smoothed'],
    )
    fourth = session(work, 'replay-override')
    replay(
        recipe,
        {'image': blobs(seed=4)},
        fourth,
        REGISTRY,
        overrides={'smoothed': {'sigma': 5.0}},
    )
    check(
        'a parameter can be overridden',
        fourth.graph().current('smoothed').params['sigma'] == 5.0,
    )

    print(f'\nstore layout, under {work}')
    for path in sorted(work.rglob('*')):
        if path.is_file() or not any(path.iterdir()):
            print(f'  {path.relative_to(work)}')

    failed = RESULTS.count(False)
    print(f'\n{len(RESULTS) - failed}/{len(RESULTS)} checks passed')
    return 1 if failed else 0


if __name__ == '__main__':
    raise SystemExit(main())

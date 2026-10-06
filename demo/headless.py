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

import skop  # noqa: E402
from demo_ops import (  # noqa: E402
    blur_then_threshold,
    connect,
    gaussian,
    otsu,
    percentile,
    sharpen,
    smooth_then_threshold,
)
from scenario import blobs, session  # noqa: E402
from skop import (  # noqa: E402
    OpSpec,  # noqa: E402
    Role,
    ambient,
    is_op,
)

from skop_core import (  # noqa: E402
    InProcess,
    MissingRoot,
    Recorder,
    RecordingRunner,
    Run,
    batch,
    export,
    is_json,
    replay,
)
from skop_visual import to_mermaid, view  # noqa: E402

try:  # the Icechunk backend is an optional extra
    from skop_core.icechunk_store import IcechunkStore  # noqa: E402
except ImportError:
    IcechunkStore = None

REGISTRY = {OpSpec.from_op(fn).name: fn for fn in (percentile, gaussian, otsu)}
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
    labels = recorder.run(otsu, 'labels', {'image': smoothed})
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

    print('\n6b. a step downstream of the edit')
    recorder.run(connect, 'components', {'labels': labels})
    graph = recorder.graph()
    check('the downstream step is affected', graph.is_affected('components'))
    check('and not edited itself', not graph.is_edited('components'))

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
    downstream = to_mermaid(
        view(recorder.graph(), store=recorder.store, targets=['components'])
    )
    check('an affected step is drawn', ':::affected' in downstream)

    print('\n7c. leaves come from current runs only')
    alt = session(work, 'leaves-check')
    alt_image = blobs(seed=11)
    alt.root('image', alt_image)
    alt_normalized = alt.run(
        percentile,
        'normalized',
        {'image': alt_image, 'low': 1.0, 'high': 99.8},
    )
    alt.run(gaussian, 'smoothed', {'image': alt_normalized, 'sigma': 2.0})
    alt.run(gaussian, 'smoothed', {'image': alt_image, 'sigma': 2.0})
    check(
        'a superseded consumer no longer hides a leaf',
        'normalized' in alt.graph().leaves(),
    )

    print('\n7d. parameters are JSON, numpy scalars included')
    check(
        'JSON containers are allowed, objects are not',
        is_json({'sigmas': [1, 2.5, None]}) and not is_json(object()),
    )
    misc = session(work, 'params-check')
    misc_image = blobs(seed=12)
    misc.root('image', misc_image)
    misc.run(otsu, 'labels', {'image': misc_image, 'invert': np.True_})
    check(
        'a numpy scalar parameter is stored as plain JSON',
        misc.graph().current('labels').params == {'invert': True},
    )

    print('\n7e. what an op declares comes off its own annotation')
    spec = OpSpec.from_op(gaussian)
    otsu_spec = OpSpec.from_op(otsu)
    check(
        "the parameters are the function's",
        [p.name for p in spec.params] == ['image', 'sigma'],
    )
    check(
        'an array parameter is an array, and is required',
        (spec.params[0].type, spec.params[0].required) == (np.ndarray, True),
    )
    check(
        'and the role comes off the annotation, not the call',
        (spec.params[0].role, spec.return_role) == (Role.image, Role.image),
    )
    check(
        'a labels op says so, which is what a host draws it from',
        otsu_spec.return_role is Role.labels,
    )
    check(
        'a scalar keeps its type and its default',
        (spec.params[1].type, spec.params[1].default) == (float, 2.0),
    )
    check(
        'a bool default comes through as a bool',
        (otsu_spec.params[1].type, otsu_spec.params[1].default)
        == (bool, False),
    )

    print("\n7e-bis. the contract is scikit-ops' (decision 44)")
    check(
        'scikit-ops recognises the demo ops as ops',
        all(is_op(fn) for fn in (percentile, gaussian, otsu, sharpen)),
    )
    check(
        'an op naming no environment is a workflow',
        all(
            OpSpec.from_op(fn).is_workflow
            for fn in (percentile, gaussian, otsu)
        ),
    )
    check(
        'an op naming an environment is not',
        OpSpec.from_op(sharpen).env == 'demo'
        and not OpSpec.from_op(sharpen).is_workflow,
    )
    check(
        'boxes have a role of their own, apart from freeform shapes',
        hasattr(Role, 'boxes') and hasattr(Role, 'shapes'),
    )

    print('\n7f. a revert clears an edit without deleting it')
    undone = session(work, 'revert-check')
    undone_image = blobs(seed=13)
    undone.root('image', undone_image)
    undone.run(gaussian, 'smoothed', {'image': undone_image, 'sigma': 2.0})
    undone.mark_edited('smoothed', 'painted it')
    check('the step is edited', undone.graph().is_edited('smoothed'))
    undone.mark_reverted('smoothed', 'put back')
    check(
        'and a revert supersedes the mark',
        not undone.graph().is_edited('smoothed'),
    )
    check(
        'while the edit stays in the log',
        len(undone.graph().events) == 2,
    )

    print('\n7g. a root that moves makes its consumers stale')
    moved = session(work, 'root-move')
    moved_image = blobs(seed=14)
    moved.root('image', moved_image)
    moved.run(gaussian, 'smoothed', {'image': moved_image, 'sigma': 2.0})
    check(
        'nothing is stale to begin with',
        not moved.graph().is_stale('smoothed'),
    )
    moved.root('image', moved_image + 1.0)
    check(
        'the root has two versions', len(moved.graph().roots_of('image')) == 2
    )
    check('and the consumer went stale', moved.graph().is_stale('smoothed'))

    print('\n7h. bringing a selection up to date')
    check(
        'produce runs the stale step and says so',
        moved.produce(['smoothed'], REGISTRY) == ['smoothed'],
    )
    check(
        'and it is current afterwards',
        not moved.graph().is_stale('smoothed'),
    )
    check(
        'a second call has nothing left to do',
        moved.produce(['smoothed'], REGISTRY) == [],
    )
    runs = len(moved.graph().runs_of('smoothed'))
    moved.rerun(gaussian, 'smoothed')
    check(
        'a rerun adds a run rather than moving the step',
        len(moved.graph().runs_of('smoothed')) == runs + 1,
    )

    print('\n8. replay on another image, in a store of its own')
    second = session(work, 'replay-second')
    produced = replay(recipe, {'image': blobs(seed=7)}, second, REGISTRY)
    check('the target came back', set(produced) == {'labels'})
    check(
        'only what the target needs ran',
        [r.step for r in second.store.records() if isinstance(r, Run)]
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
        [r.step for r in third.store.records() if isinstance(r, Run)]
        == ['normalized', 'smoothed'],
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

    print('\n11. the Icechunk backend, behind the same store protocol')
    if IcechunkStore is None:
        print('  SKIP  icechunk is not installed (uv sync --group icechunk)')
    else:
        chunked = Recorder(
            IcechunkStore(work / 'icechunk'),
            InProcess(),
            version='demo 0.1',
        )
        chunk_image = blobs(seed=21)
        chunked.root('image', chunk_image)
        chunk_normalized = chunked.run(
            percentile,
            'normalized',
            {'image': chunk_image, 'low': 1.0, 'high': 99.8},
        )
        chunk_smoothed = chunked.run(
            gaussian, 'smoothed', {'image': chunk_normalized, 'sigma': 2.0}
        )
        chunked.mark_edited('smoothed', 'painted one cell')
        chunk_graph = chunked.graph()
        check(
            'the same graph answers come back',
            chunk_graph.current('smoothed').params['sigma'] == 2.0
            and chunk_graph.is_edited('smoothed')
            and not chunk_graph.is_stale('smoothed'),
        )
        check(
            'an array comes back through its handle',
            np.array_equal(
                chunked.store.get(
                    chunk_graph.current('smoothed').outputs['result']
                ),
                chunk_smoothed,
            ),
        )
        chunk_recipe = export(chunk_graph, ['smoothed'], store=chunked.store)
        handles = [
            handle
            for run in chunk_graph.runs
            for handle in (*run.inputs.values(), *run.outputs.values())
        ]
        check(
            'the recipe still carries no handle',
            all(handle not in json.dumps(chunk_recipe) for handle in handles),
        )
        check(
            'a root is still named, with a shape hint',
            chunk_recipe['roots']
            == {'image': {'ndim': 2, 'dtype': 'float64'}},
        )
        check(
            'the view draws it too',
            'root image' in to_mermaid(view(chunk_graph, store=chunked.store)),
        )
        commits = list(chunked.store.repo.ancestry(branch='main'))
        check(
            'one commit per record, plus the initial snapshot',
            len(commits) == len(chunked.store.records()) + 1,
        )
        chunk_second = Recorder(
            IcechunkStore(work / 'icechunk-replay'),
            InProcess(),
            version='demo 0.1',
        )
        produced = replay(
            chunk_recipe, {'image': blobs(seed=22)}, chunk_second, REGISTRY
        )
        check(
            'replay runs against it through the same code',
            set(produced) == {'smoothed'}
            and not any(
                chunk_second.graph().is_stale(step)
                for step in chunk_second.graph().steps()
            ),
        )

    print('\n12. a workflow, run through a runner that is listening')
    listening = session(work, 'listening')
    listener = RecordingRunner(listening)
    listening.root('image', image)
    told: list[str] = []
    mask = listener.run(
        smooth_then_threshold,
        {'image': image, 'sigma': 3.0},
        on_recorded=told.append,
        # What a real runner takes besides the op's arguments: passed through
        # to the inner runner, which here has no use for it.
        on_progress=print,
    )
    graph = listening.graph()
    parent = graph.current('smooth_then_threshold')
    children = graph.children_of(parent)
    check(
        'the workflow is recorded, and so is each op it called',
        parent is not None
        and [c.op.rpartition(':')[2] for c in children]
        == ['gaussian', 'otsu'],
    )
    check(
        'a call inside a workflow is named for the workflow it is in',
        [c.step for c in children]
        == ['smooth_then_threshold.gaussian', 'smooth_then_threshold.otsu'],
    )
    check(
        'the workflow is the step, and the ops are its detail',
        graph.steps() == ['smooth_then_threshold']
        and len(graph.steps(nested=True)) == 3
        and graph.leaves() == ['smooth_then_threshold'],
    )
    check(
        'lineage runs through the workflow: the threshold read the blur',
        children[1].inputs['image'] == children[0].outputs['result'],
    )
    check(
        'the workflow read the root, and parameters are recorded as JSON',
        parent.inputs == {'image': 'image@v1'}
        and parent.params == {'sigma': 3.0}
        and children[0].params == {'sigma': 3.0},
    )
    check(
        'the caller is told the step once, and only for the outer call',
        told == ['smooth_then_threshold'],
    )
    check(
        'the result is what the workflow returned',
        np.array_equal(mask, listening.store.get(parent.outputs['result'])),
    )

    print('\n12b. a script that calls skop.run, with a recorder installed')
    scripted = session(work, 'scripted')
    scripted.root('image', image)
    with ambient(RecordingRunner(scripted)):
        skop.run(gaussian, {'image': image, 'sigma': 2.0})
    check(
        'a plain skop.run is recorded, with no panel in sight',
        scripted.graph().steps() == ['gaussian'],
    )

    print('\n12c. a failure inside a workflow')
    try:
        listener.run(smooth_then_threshold, {'image': image, 'sigma': -1.0})
    except ValueError:
        graph = listening.graph()
        failed = [r for r in graph.runs if r.status == 'failed']
        check(
            'the op that failed and the workflow around it are both recorded',
            {r.step for r in failed}
            == {'smooth_then_threshold', 'smooth_then_threshold.gaussian'},
        )
        check(
            'neither failure becomes current',
            graph.current('smooth_then_threshold').id == parent.id,
        )
    else:
        check('a failure inside a workflow is raised', False)

    print('\n12d. a workflow handed an op as a parameter')
    handed = session(work, 'handed')
    handed.root('image', image)
    handed_listener = RecordingRunner(handed)
    handed_listener.run(
        blur_then_threshold, {'image': image, 'blur': gaussian}
    )
    run = handed.graph().current('blur_then_threshold')
    check(
        'an op given as a parameter is recorded as its ID, which is JSON',
        run.params == {'blur': OpSpec.from_op(gaussian).name}
        and is_json(run.params),
    )
    handed.rerun(blur_then_threshold, 'blur_then_threshold')
    check(
        'a run again takes the ID back to the op, and records it',
        len(handed.graph().runs_of('blur_then_threshold')) == 2,
    )
    try:
        handed.run(
            blur_then_threshold,
            'blur_then_threshold',
            {'image': image, 'blur': 'demo_ops:nowhere'},
        )
    except KeyError as error:
        check('an ID that names no op is refused', 'nowhere' in str(error))
    else:
        check('an ID that names no op is refused', False)

    print(f'\nstore layout, under {work}')
    for path in sorted(work.rglob('*')):
        if path.is_file() or not any(path.iterdir()):
            print(f'  {path.relative_to(work)}')

    failed = RESULTS.count(False)
    print(f'\n{len(RESULTS) - failed}/{len(RESULTS)} checks passed')
    return 1 if failed else 0


if __name__ == '__main__':
    raise SystemExit(main())

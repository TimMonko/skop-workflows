"""Export, plan, replay and batch: the recipe's round trip."""

from __future__ import annotations

import json

import numpy as np
import pytest
from ops import (
    REGISTRY,
    add,
    blur,
    blur_then_threshold,
    broken,
    configured,
    last_call,
    op_id,
    split,
    split_workflow,
    threshold,
)

from skop_core import InProcess, Recorder, SimpleStore, batch, export, plan
from skop_core import replay as _replay
from skop_core.recipe import FORMAT, MissingOp, UnboundRoot


def replay(recipe, roots, recorder, **kwargs):
    # Through a file, always: what a recipe is is what survives the trip.
    return _replay(
        json.loads(json.dumps(recipe)), roots, recorder, REGISTRY, **kwargs
    )


def fresh(tmp_path, name='replay') -> Recorder:
    return Recorder(SimpleStore(tmp_path / name), InProcess())


def chain(recorder, image):
    recorder.root('image', image)
    blurred = recorder.run(blur, 'blurred', {'image': image, 'sigma': 2.0})
    recorder.run(threshold, 'mask', {'image': blurred})
    return recorder


def test_a_recipe_names_its_references_unambiguously(recorder, image):
    chain(recorder, image)
    recipe = export(recorder.graph(), ['mask'], recorder.store)
    assert recipe['format'] == FORMAT
    assert recipe['steps']['blurred']['inputs'] == {'image': {'root': 'image'}}
    assert recipe['steps']['mask']['inputs'] == {
        'image': {'step': 'blurred', 'output': 'result'}
    }
    assert recipe['roots'] == {'image': {'ndim': 2, 'dtype': 'float64'}}


def test_a_recipe_carries_no_handle(recorder, image):
    chain(recorder, image)
    recipe = json.dumps(export(recorder.graph(), ['mask'], recorder.store))
    for run in recorder.graph().runs:
        for handle in [*run.inputs.values(), *run.outputs.values()]:
            assert handle not in recipe


def test_replay_reproduces_the_targets(recorder, image, tmp_path):
    chain(recorder, image)
    recipe = export(recorder.graph(), ['mask'], recorder.store)
    produced = replay(recipe, {'image': image}, fresh(tmp_path))
    original = recorder.store.get(
        recorder.graph().current('mask').outputs['result']
    )
    assert np.array_equal(produced['mask'], original)


def test_a_root_sharing_a_step_name_replays(recorder, image, tmp_path):
    recorder.root('blurred', image)
    out = recorder.run(blur, 'blurred', {'image': image})
    recorder.run(threshold, 'mask', {'image': out})
    recipe = export(recorder.graph(), ['mask'], recorder.store)
    assert recipe['steps']['blurred']['inputs'] == {
        'image': {'root': 'blurred'}
    }
    produced = replay(recipe, {'blurred': image}, fresh(tmp_path))
    assert np.array_equal(produced['mask'], threshold(blur(image)))


def test_a_consumer_of_one_named_output_replays_that_output(
    recorder, image, tmp_path
):
    recorder.root('image', image)
    parts = recorder.run(split, 'parts', {'image': image})
    recorder.run(blur, 'from_high', {'image': parts.high})
    recipe = export(recorder.graph(), ['from_high'], recorder.store)
    assert recipe['steps']['from_high']['inputs'] == {
        'image': {'step': 'parts', 'output': 'high'}
    }
    produced = replay(recipe, {'image': image}, fresh(tmp_path))
    assert np.array_equal(produced['from_high'], blur(np.maximum(image, 0.5)))


def test_a_workflow_replays_as_one_step_and_records_its_calls(
    recorder, image, tmp_path
):
    recorder.root('image', image)
    recorder.run(blur_then_threshold, 'wf', {'image': image, 'sigma': 0.5})
    recipe = export(recorder.graph(), ['wf'], recorder.store)
    assert list(recipe['steps']) == ['wf']
    again = fresh(tmp_path)
    replay(recipe, {'image': image}, again)
    graph = again.graph()
    assert len(graph.children_of(graph.current('wf'))) == 2


def test_a_nested_output_read_from_outside_the_workflow(
    recorder, image, tmp_path
):
    # A step outside a workflow may read what a call inside it made. That call
    # is a run like any other, with its own inputs, so it is exported as a
    # step of its own rather than by replaying the whole workflow.
    recorder.root('image', image)
    recorder.run(split_workflow, 'wf', {'image': image})
    inner = recorder.graph().children_of(recorder.graph().current('wf'))[0]
    low = recorder.store.get(inner.outputs['low'])
    recorder.run(blur, 'after', {'image': low})
    recipe = export(recorder.graph(), ['after'], recorder.store)
    assert recipe['steps']['after']['inputs'] == {
        'image': {'step': 'wf.split', 'output': 'low'}
    }
    assert 'wf' not in recipe['steps']
    produced = replay(recipe, {'image': image}, fresh(tmp_path))
    assert np.array_equal(produced['after'], blur(np.minimum(image, 0.5)))


def test_an_abandoned_branch_is_not_exported(recorder, image):
    chain(recorder, image)
    recorder.run(blur, 'side', {'image': image, 'sigma': 9.0})
    recipe = export(recorder.graph(), ['mask'], recorder.store)
    assert set(recipe['steps']) == {'blurred', 'mask'}


def test_export_refuses_a_target_it_cannot_produce(recorder, image):
    chain(recorder, image)
    with pytest.raises(KeyError, match='nowhere'):
        export(recorder.graph(), ['nowhere'], recorder.store)
    with pytest.raises(RuntimeError):
        recorder.run(broken, 'broken', {'image': image})
    with pytest.raises(KeyError, match='broken'):
        export(recorder.graph(), ['broken'], recorder.store)


def test_export_defaults_to_the_leaves(recorder, image):
    chain(recorder, image)
    recipe = export(recorder.graph(), None, recorder.store)
    assert recipe['targets'] == ['mask']


def test_an_edit_is_flagged_and_a_kept_edit_becomes_a_root(recorder, image):
    chain(recorder, image)
    recorder.mark_edited('blurred')
    recipe = export(recorder.graph(), ['mask'], recorder.store)
    assert recipe['caution']['edited'] == ['blurred']
    assert recipe['caution']['affected'] == ['mask']

    painted = recorder.store.get(
        recorder.graph().current('blurred').outputs['result']
    ).copy()
    painted[0] = 0
    recorder.accept_edit('blurred', painted)
    recorder.produce(['mask'], REGISTRY)
    recipe = export(recorder.graph(), ['mask'], recorder.store)
    # The kept pixels cannot be recomputed, so they are an input to supply.
    assert 'blurred' not in recipe['steps']
    assert recipe['roots'] == {'blurred': {'ndim': 2, 'dtype': 'float64'}}
    assert recipe['steps']['mask']['inputs'] == {'image': {'root': 'blurred'}}
    assert recipe['caution'] == {
        'edited': [],
        'affected': [],
        'kept': ['blurred'],
    }


def test_plan_is_the_closure_and_refuses_strangers(recorder, image):
    chain(recorder, image)
    recipe = export(recorder.graph(), ['mask'], recorder.store)
    assert plan(recipe) == ['blurred', 'mask']
    assert plan(recipe, ['blurred']) == ['blurred']
    with pytest.raises(KeyError):
        plan(recipe, ['nothing'])


def test_replay_checks_everything_before_running_anything(
    recorder, image, tmp_path
):
    chain(recorder, image)
    recipe = export(recorder.graph(), ['mask'], recorder.store)
    again = fresh(tmp_path)
    with pytest.raises(UnboundRoot, match="'image'"):
        replay(recipe, {}, again)
    with pytest.raises(UnboundRoot, match='2 axes'):
        replay(recipe, {'image': np.zeros((2, 2, 2))}, again)
    with pytest.raises(MissingOp):
        _replay(recipe, {'image': image}, again, {})
    assert again.store.records() == []


def test_an_override_for_a_step_not_replayed_is_refused(
    recorder, image, tmp_path
):
    chain(recorder, image)
    recipe = export(recorder.graph(), ['mask'], recorder.store)
    with pytest.raises(KeyError, match='blured'):
        replay(
            recipe, {'image': image}, fresh(tmp_path), overrides={'blured': {}}
        )


def test_an_override_changes_one_parameter(recorder, image, tmp_path):
    chain(recorder, image)
    recipe = export(recorder.graph(), ['mask'], recorder.store)
    again = fresh(tmp_path)
    replay(
        recipe, {'image': image}, again, overrides={'blurred': {'sigma': 0.1}}
    )
    assert again.graph().current('blurred').params == {'sigma': 0.1}


def test_an_empty_target_list_produces_nothing(recorder, image, tmp_path):
    chain(recorder, image)
    recipe = export(recorder.graph(), ['mask'], recorder.store)
    again = fresh(tmp_path)
    assert replay(recipe, {'image': image}, again, targets=[]) == {}
    assert [r.kind for r in again.store.records()] == []


def test_one_array_given_for_two_roots(recorder, image, tmp_path):
    other = image * 2
    recorder.root('a', image)
    recorder.root('b', other)
    recorder.run(add, 'sum', {'a': image, 'b': other})
    recipe = export(recorder.graph(), ['sum'], recorder.store)
    again = fresh(tmp_path)
    replay(recipe, {'a': image, 'b': image}, again)
    graph = again.graph()
    # The store knows an array by identity, so one array is one root: both
    # parameters read it, and lineage says so.
    assert graph.sources_of(graph.current('sum')) == {
        'a': 'root:a',
        'b': 'root:a',
    }


def test_replay_into_a_recorder_that_already_saw_the_array(recorder, image):
    chain(recorder, image)
    recipe = export(recorder.graph(), ['mask'], recorder.store)
    # The same recorder: the array is already a root here, and replaying must
    # still record that the recipe's root was bound to it.
    replay(recipe, {'image': image}, recorder)
    graph = recorder.graph()
    assert graph.current_root('image').handle == recorder.store.handle_of(
        image
    )


def test_batch_carries_on_and_reports_each(recorder, image, tmp_path):
    chain(recorder, image)
    recipe = export(recorder.graph(), ['mask'], recorder.store)
    items = [
        ('good', {'image': image}),
        ('wrong-shape', {'image': np.zeros(3)}),
        ('missing', {}),
        ('also-good', {'image': image + 1}),
    ]
    outcomes = batch(
        recipe, items, lambda name: fresh(tmp_path, name), REGISTRY
    )
    assert [o['ok'] for o in outcomes] == [True, False, False, True]
    assert 'axes' in outcomes[1]['error']
    assert "'image'" in outcomes[2]['error']


def test_batch_can_stop_at_the_first_failure(recorder, image, tmp_path):
    chain(recorder, image)
    recipe = export(recorder.graph(), ['mask'], recorder.store)
    items = [('bad', {'image': np.zeros(3)}), ('good', {'image': image})]
    outcomes = batch(
        recipe,
        items,
        lambda name: fresh(tmp_path, name),
        REGISTRY,
        stop_on_failure=True,
    )
    assert [o['name'] for o in outcomes] == ['bad']


def test_batch_hands_back_where_each_item_was_recorded(
    recorder, image, tmp_path
):
    chain(recorder, image)
    recipe = export(recorder.graph(), ['mask'], recorder.store)
    (outcome,) = batch(
        recipe,
        [('one', {'image': image})],
        lambda n: fresh(tmp_path, n),
        REGISTRY,
    )
    graph = outcome['recorder'].graph()
    assert graph.steps() == ['blurred', 'mask']


def test_a_recipe_of_an_unknown_format_is_refused(recorder, image, tmp_path):
    chain(recorder, image)
    recipe = export(recorder.graph(), ['mask'], recorder.store)
    recipe['format'] = FORMAT + 1
    with pytest.raises(ValueError, match='format'):
        replay(recipe, {'image': image}, fresh(tmp_path))


def test_an_unknown_op_names_itself(recorder, image, tmp_path):
    chain(recorder, image)
    recipe = export(recorder.graph(), ['mask'], recorder.store)
    with pytest.raises(MissingOp, match=op_id(threshold)):
        _replay(recipe, {'image': image}, fresh(tmp_path), {op_id(blur): blur})


def test_a_path_is_asked_for_never_carried(recorder, image, tmp_path):
    model = tmp_path / 'deep' / 'weights.pt'
    recorder.root('image', image)
    recorder.run(configured, 'configured', {'image': image, 'model': model})
    run = recorder.graph().current('configured')
    assert run.paths == {'model': str(model)} and 'model' not in run.params
    recipe = export(recorder.graph(), ['configured'], recorder.store)
    assert str(tmp_path) not in json.dumps(recipe)
    assert recipe['roots']['configured.model'] == {'path': 'weights.pt'}
    assert recipe['steps']['configured']['inputs']['model'] == {
        'root': 'configured.model'
    }
    again = fresh(tmp_path)
    with pytest.raises(UnboundRoot, match='configured.model'):
        replay(recipe, {'image': image}, again)
    with pytest.raises(UnboundRoot, match='wants a path'):
        replay(recipe, {'image': image, 'configured.model': image}, again)
    elsewhere = tmp_path / 'other.pt'
    last_call.clear()
    replay(recipe, {'image': image, 'configured.model': str(elsewhere)}, again)
    assert last_call['model'] == elsewhere
    assert again.graph().current('configured').paths == {
        'model': str(elsewhere)
    }


def test_a_path_param_survives_update(recorder, image):
    recorder.root('image', image)
    recorder.run(configured, 'configured', {'image': image, 'model': 'm.pt'})
    recorder.root('image', image + 1)
    last_call.clear()
    recorder.update(configured, 'configured')
    from pathlib import Path

    assert last_call['model'] == Path('m.pt')

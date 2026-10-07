"""Preparing a replay: what a host shows before anything runs, and the run."""

from __future__ import annotations

import numpy as np
import pytest
from ops import REGISTRY, blur, configured, split, threshold
from skop import Role

from skop_core import InProcess, Recorder, SimpleStore, export, prepare
from skop_core.recipe import MissingOp, UnboundRoot


def fresh(tmp_path, name='replay') -> Recorder:
    return Recorder(SimpleStore(tmp_path / name), InProcess())


def recipe_of(recorder, image, targets=('mask',)):
    recorder.root('image', image)
    blurred = recorder.run(blur, 'blurred', {'image': image, 'sigma': 2.0})
    recorder.run(threshold, 'mask', {'image': blurred})
    return export(recorder.graph(), list(targets), recorder.store)


def test_a_prepared_recipe_says_what_it_needs(recorder, image):
    prepared = prepare(recipe_of(recorder, image), REGISTRY)
    assert prepared.steps == ['blurred', 'mask']
    assert prepared.problems == []
    (need,) = prepared.roots
    assert (need.name, need.ndim, need.dtype) == ('image', 2, 'float64')
    assert need.role is Role.image
    assert not need.is_path and need.kept_for is None
    assert need.read_by == ('blurred',)


def test_a_missing_op_is_a_problem_before_anything_runs(recorder, image):
    prepared = prepare(recipe_of(recorder, image), {})
    assert len(prepared.problems) == 2
    with pytest.raises(MissingOp):
        prepared.check({'image': image})


def test_fewer_targets_need_fewer_steps(recorder, image):
    prepared = prepare(recipe_of(recorder, image), REGISTRY, ['blurred'])
    assert prepared.steps == ['blurred']


def test_a_path_root_and_a_kept_root_say_what_they_are(
    recorder, image, tmp_path
):
    recorder.root('image', image)
    blurred = recorder.run(blur, 'blurred', {'image': image})
    recorder.mark_edited('blurred')
    recorder.accept_edit('blurred', blurred + 1)
    kept = recorder.store.get(recorder.graph().accepted('blurred'))
    recorder.run(
        configured, 'configured', {'image': kept, 'model': tmp_path / 'w.pt'}
    )
    prepared = prepare(
        export(recorder.graph(), ['configured'], recorder.store), REGISTRY
    )
    needs = {need.name: need for need in prepared.roots}
    assert needs['blurred'].kept_for == 'blurred'
    assert needs['configured.model'].is_path
    assert needs['configured.model'].path_hint == 'w.pt'


def test_check_refuses_in_words(recorder, image):
    prepared = prepare(recipe_of(recorder, image), REGISTRY)
    with pytest.raises(UnboundRoot, match='needed by'):
        prepared.check({})
    with pytest.raises(UnboundRoot, match='2 axes'):
        prepared.check({'image': np.zeros(3)})


def test_a_known_array_is_used_as_it_is_not_declared_again(recorder, image):
    recipe = recipe_of(recorder, image)
    other = image + 5
    recorder.root('blobs', other)  # a layer, already a root in the session
    roots_before = len(recorder.graph().roots)
    done = prepare(recipe, REGISTRY).run({'image': other}, recorder)
    graph = recorder.graph()
    assert len(graph.roots) == roots_before
    run = graph.current(done.steps['blurred'])
    assert graph.sources_of(run) == {'image': 'root:blobs'}
    assert done.steps['blurred'] == 'blurred_2'


def test_replaying_onto_a_steps_output_chains_onto_it(
    recorder, image, tmp_path
):
    recipe = recipe_of(recorder, image)
    session = fresh(tmp_path)
    session.root('raw', image)
    blurred = session.run(blur, 'earlier', {'image': image})
    done = prepare(recipe, REGISTRY).run({'image': blurred}, session)
    graph = session.graph()
    assert graph.sources_of(graph.current(done.steps['blurred'])) == {
        'image': 'earlier'
    }


def test_step_names_follow_the_inputs(recorder, image, tmp_path):
    recipe = recipe_of(recorder, image)
    session = fresh(tmp_path)
    first, second = image, image * 2
    session.root('first', first)
    session.root('second', second)
    prepared = prepare(recipe, REGISTRY)
    one = prepared.run({'image': first}, session)
    again = prepared.run({'image': first}, session)
    other = prepared.run({'image': second}, session)
    assert one.steps == again.steps == {'blurred': 'blurred', 'mask': 'mask'}
    assert other.steps == {'blurred': 'blurred_2', 'mask': 'mask_2'}
    assert len(session.graph().runs_of('blurred')) == 2


def test_a_host_is_told_before_and_after_each_step(recorder, image, tmp_path):
    told = []
    prepare(recipe_of(recorder, image), REGISTRY).run(
        {'image': image},
        fresh(tmp_path),
        on_step=lambda *a: told.append(('step', *a)),
        on_done=lambda *a: told.append(('done', *a)),
    )
    assert told == [
        ('step', 0, 2, 'blurred', 'blurred'),
        ('done', 'blurred', 'blurred'),
        ('step', 1, 2, 'mask', 'mask'),
        ('done', 'mask', 'mask'),
    ]


def test_a_cancel_stops_between_steps(recorder, image, tmp_path):
    asked = iter([False, True])
    done = prepare(recipe_of(recorder, image), REGISTRY).run(
        {'image': image}, fresh(tmp_path), cancelled=lambda: next(asked)
    )
    assert done.cancelled and list(done.steps) == ['blurred']


def test_a_failure_leaves_the_earlier_steps_recorded(
    recorder, image, tmp_path
):
    recipe = recipe_of(recorder, image)
    session = fresh(tmp_path)
    with pytest.raises(TypeError):
        prepare(recipe, REGISTRY).run(
            {'image': image}, session, overrides={'mask': {'level': object()}}
        )
    assert session.graph().current('blurred') is not None


def test_a_multi_output_consumer_replays(recorder, image, tmp_path):
    recorder.root('image', image)
    parts = recorder.run(split, 'parts', {'image': image})
    recorder.run(blur, 'high', {'image': parts.high})
    prepared = prepare(
        export(recorder.graph(), ['high'], recorder.store), REGISTRY
    )
    done = prepared.run({'image': image}, fresh(tmp_path))
    assert np.array_equal(done.results['high'], blur(np.maximum(image, 0.5)))


# -- data with more axes than was recorded -----------------------------------


def plane_recipe(recorder, image):
    from ops import plane

    recorder.root('image', image)
    flat = recorder.run(plane, 'flat', {'image': image})
    recorder.run(plane, 'flatter', {'image': flat})
    return export(recorder.graph(), ['flatter'], recorder.store)


def test_an_input_read_only_by_planned_ops_takes_more_axes(recorder, image):
    prepared = prepare(plane_recipe(recorder, image), REGISTRY)
    (need,) = prepared.roots
    assert need.plannable
    assert need.fits(2) and need.fits(3) and not need.fits(1)


def test_an_input_an_op_reads_whole_wants_its_axes(recorder, image):
    prepared = prepare(recipe_of(recorder, image), REGISTRY)
    (need,) = prepared.roots
    assert not need.plannable and not need.fits(3)
    with pytest.raises(UnboundRoot, match='wants 2 axes, got 3'):
        prepared.check({'image': np.stack([image, image])})


def test_a_stack_is_run_plane_by_plane_through_every_step(
    recorder, image, tmp_path
):
    prepared = prepare(plane_recipe(recorder, image), REGISTRY)
    stack = np.stack([image, image * 2, image * 3])
    done = prepared.run(
        {'image': stack}, fresh(tmp_path), axes={'image': ['z', 'y', 'x']}
    )
    assert done.results['flatter'].shape == stack.shape
    assert np.allclose(done.results['flatter'], stack + 2)
    assert set(done.planned) == {'flat', 'flatter'}
    assert 'per z' in done.planned['flat']['image']
    # The second step was handed the first's stacked output, and knew its
    # axes from the plan that made it.
    assert 'per z' in done.planned['flatter']['image']


def test_unnamed_axes_are_planned_too(recorder, image, tmp_path):
    prepared = prepare(plane_recipe(recorder, image), REGISTRY)
    stack = np.stack([image, image])
    done = prepared.run({'image': stack}, fresh(tmp_path))
    assert done.results['flatter'].shape == stack.shape
    assert 'axis 0' in done.planned['flat']['image']


def test_data_of_the_recorded_shape_needs_no_new_plan(
    recorder, image, tmp_path
):
    prepared = prepare(plane_recipe(recorder, image), REGISTRY)
    done = prepared.run({'image': image}, fresh(tmp_path))
    assert done.planned == {}


def test_the_plan_a_replay_made_is_recorded(recorder, image, tmp_path):
    prepared = prepare(plane_recipe(recorder, image), REGISTRY)
    session = fresh(tmp_path)
    prepared.run({'image': np.stack([image, image])}, session)
    assert 'plans' in session.graph().current('flat').options

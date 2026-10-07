"""Recorder.run: what a call writes down, and what it refuses."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from ops import (
    REGISTRY,
    Mode,
    blur,
    blur_then_threshold,
    broken,
    configured,
    count,
    last_call,
    masked,
    op_id,
    same,
    scale_into,
    split,
    split_workflow,
    threshold,
    total,
)

from skop_core import MissingRoot, RecordingRunner


def test_an_array_from_nowhere_is_refused(recorder, image):
    with pytest.raises(MissingRoot, match='has no handle'):
        recorder.run(blur, 'blurred', {'image': image})
    assert recorder.store.records() == []


def test_a_view_of_a_root_is_refused_not_misrecorded(recorder, image):
    recorder.root('image', image)
    with pytest.raises(MissingRoot):
        recorder.run(blur, 'blurred', {'image': image[1:]})


def test_a_parameter_that_is_not_json_is_refused(recorder, image):
    recorder.root('image', image)
    with pytest.raises(TypeError, match='not JSON'):
        recorder.run(blur, 'blurred', {'image': image, 'sigma': object()})
    assert [r.kind for r in recorder.store.records()] == ['root']


def test_a_run_records_handles_params_and_version(recorder, image):
    root = recorder.root('image', image)
    recorder.run(blur, 'blurred', {'image': image, 'sigma': np.float32(2)})
    run = recorder.graph().current('blurred')
    assert run.inputs == {'image': root}
    assert run.params == {'sigma': 2.0}
    assert isinstance(run.params['sigma'], float)
    assert run.op == op_id(blur)
    assert run.op_version == 'test'
    assert set(run.outputs) == {'result'}


def test_a_default_parameter_left_out_is_not_recorded(recorder, image):
    # What was not said is not written down: the op's default stands, and a
    # replay reads it off the op as the original call did.
    recorder.root('image', image)
    recorder.run(blur, 'blurred', {'image': image})
    assert recorder.graph().current('blurred').params == {}


def test_a_failed_run_is_recorded_and_raised(recorder, image):
    recorder.root('image', image)
    with pytest.raises(RuntimeError, match='on purpose'):
        recorder.run(broken, 'broken', {'image': image})
    (run,) = recorder.graph().runs_of('broken')
    assert run.status == 'failed'
    assert 'RuntimeError: broken on purpose' in run.error
    assert run.outputs == {}
    assert recorder.graph().current('broken') is None


def test_named_outputs_are_stored_one_by_one(recorder, image):
    recorder.root('image', image)
    result = recorder.run(split, 'parts', {'image': image})
    run = recorder.graph().current('parts')
    assert set(run.outputs) == {'low', 'high'}
    assert np.array_equal(recorder.store.get(run.outputs['low']), result.low)
    assert np.array_equal(recorder.store.get(run.outputs['high']), result.high)


def test_a_plain_tuple_of_outputs_is_read_by_position(recorder, image):
    # What scikit-ops' Runner hands back for an op whose return type is not a
    # NamedTuple with those fields: the values, in the declared order.
    class AsTuple:
        def run(self, fn, args, **options):
            return tuple(fn(**args))

    recorder.inner = AsTuple()
    recorder.root('image', image)
    recorder.run(split, 'parts', {'image': image})
    run = recorder.graph().current('parts')
    low = recorder.store.get(run.outputs['low'])
    assert np.array_equal(low, np.minimum(image, 0.5))


def test_a_scalar_output_is_recorded(recorder, image):
    recorder.root('image', image)
    assert recorder.run(total, 'sum', {'image': image}) == pytest.approx(
        image.sum()
    )
    run = recorder.graph().current('sum')
    assert float(recorder.store.get(run.outputs['result'])) == pytest.approx(
        image.sum()
    )


def test_an_array_and_a_scalar_together(recorder, image):
    recorder.root('image', image)
    recorder.run(count, 'counted', {'image': image})
    run = recorder.graph().current('counted')
    assert int(recorder.store.get(run.outputs['count'])) == 15


def test_an_output_buffer_is_an_output_not_a_parameter(recorder, image):
    recorder.root('image', image)
    buffer = np.zeros_like(image)
    recorder.run(scale_into, 'scaled', {'image': image, 'result': buffer})
    run = recorder.graph().current('scaled')
    assert 'result' not in run.params
    assert 'result' not in run.inputs
    assert np.array_equal(recorder.store.get(run.outputs['result']), image * 2)
    # The buffer the caller owns is now known as that output, so it can be
    # handed to the next op.
    assert recorder.store.handle_of(buffer) == run.outputs['result']


def test_an_optional_array_not_given_is_a_parameter(recorder, image):
    root = recorder.root('image', image)
    recorder.run(masked, 'masked', {'image': image, 'mask': None})
    run = recorder.graph().current('masked')
    assert run.inputs == {'image': root}
    assert run.params == {'mask': None}


def test_an_optional_array_given_is_an_input(recorder, image):
    recorder.root('image', image)
    mask = recorder.run(threshold, 'mask', {'image': image})
    recorder.run(masked, 'masked', {'image': image, 'mask': mask})
    graph = recorder.graph()
    assert graph.sources_of(graph.current('masked')) == {
        'image': 'root:image',
        'mask': 'mask',
    }


def test_an_op_that_returns_its_input_keeps_the_root_known(recorder, image):
    root = recorder.root('image', image)
    out = recorder.run(same, 'copy', {'image': image})
    graph = recorder.graph()
    produced = graph.current('copy').outputs['result']
    # The same object is now the step's output; what reads it next reads the
    # step, which is the more recent account of where it came from.
    assert out is image
    assert recorder.store.handle_of(image) == produced
    assert graph.current('copy').inputs == {'image': root}


def test_an_enum_and_a_path_are_recorded_as_json_and_revived(recorder, image):
    recorder.root('image', image)
    recorder.run(
        configured,
        'configured',
        {'image': image, 'mode': Mode.slow, 'model': Path('weights.pt')},
    )
    run = recorder.graph().current('configured')
    assert run.params == {'mode': 'slow'}
    assert run.paths == {'model': 'weights.pt'}
    last_call.clear()
    recorder.rerun(configured, 'configured')
    assert last_call == {'mode': Mode.slow, 'model': Path('weights.pt')}


def test_a_root_declared_again_is_a_new_version(recorder, image):
    first = recorder.root('image', image)
    second = recorder.root('image', image + 1)
    graph = recorder.graph()
    assert first != second
    assert [r.handle for r in graph.roots_of('image')] == [first, second]
    assert graph.current_root('image').handle == second


def test_update_takes_inputs_from_where_they_are_now(recorder, image):
    recorder.root('image', image)
    recorder.run(blur, 'blurred', {'image': image, 'sigma': 1.0})
    moved = image + 10
    recorder.root('image', moved)
    assert recorder.graph().is_stale('blurred')
    recorder.update(blur, 'blurred')
    run = recorder.graph().current('blurred')
    assert run.params == {'sigma': 1.0}
    assert np.array_equal(
        recorder.store.get(run.outputs['result']), moved * 0.5 + 1.0
    )
    assert not recorder.graph().is_stale('blurred')


def test_update_follows_the_right_output_of_a_step(recorder, image):
    recorder.root('image', image)
    parts = recorder.run(split, 'parts', {'image': image})
    recorder.run(blur, 'blurred', {'image': parts.high})
    recorder.run(split, 'parts', {'image': image, 'at': 0.25})
    assert recorder.graph().is_stale('blurred')
    recorder.update(blur, 'blurred')
    graph = recorder.graph()
    assert graph.current('blurred').inputs == {
        'image': graph.current('parts').outputs['high']
    }


def test_rerun_uses_the_inputs_the_run_had(recorder, image):
    recorder.root('image', image)
    recorder.run(blur, 'blurred', {'image': image})
    recorder.root('image', image + 1)
    recorder.rerun(blur, 'blurred')
    graph = recorder.graph()
    first, second = graph.runs_of('blurred')
    assert first.inputs == second.inputs
    # It read the old version, which has moved on, so it is still stale.
    assert graph.is_stale('blurred')


def test_update_and_rerun_need_a_successful_run(recorder, image):
    recorder.root('image', image)
    with pytest.raises(RuntimeError):
        recorder.run(broken, 'broken', {'image': image})
    with pytest.raises(KeyError):
        recorder.update(broken, 'broken')
    with pytest.raises(KeyError):
        recorder.rerun(broken, 'broken')
    with pytest.raises(KeyError):
        recorder.mark_edited('nothing')


def test_produce_walks_the_closure_in_order(recorder, image):
    recorder.root('image', image)
    blurred = recorder.run(blur, 'blurred', {'image': image})
    recorder.run(threshold, 'mask', {'image': blurred})
    recorder.root('image', image + 1)
    assert recorder.produce(['mask'], REGISTRY) == ['blurred', 'mask']
    graph = recorder.graph()
    assert not graph.is_stale('blurred') and not graph.is_stale('mask')
    assert recorder.produce(['mask'], REGISTRY) == []


def test_produce_says_which_op_it_cannot_find(recorder, image):
    recorder.root('image', image)
    recorder.run(blur, 'blurred', {'image': image})
    recorder.root('image', image + 1)
    with pytest.raises(KeyError, match='blurred'):
        recorder.produce(['blurred'], {})


def test_a_workflow_run_directly_records_what_it_called(recorder, image):
    # Recorder.run, not RecordingRunner: replay, update and produce all come
    # in this way, and a workflow must still route its calls back here rather
    # than to some default runner nobody configured.
    recorder.root('image', image)
    recorder.run(blur_then_threshold, 'wf', {'image': image})
    graph = recorder.graph()
    parent = graph.current('wf')
    assert [c.step for c in graph.children_of(parent)] == [
        'wf.blur',
        'wf.threshold',
    ]
    assert graph.steps() == ['wf']


def test_a_workflow_update_records_what_it_called_again(recorder, image):
    recorder.root('image', image)
    recorder.run(blur_then_threshold, 'wf', {'image': image})
    recorder.root('image', image + 1)
    recorder.produce(['wf'], REGISTRY)
    graph = recorder.graph()
    assert len(graph.children_of(graph.current('wf'))) == 2


def test_a_workflow_with_named_outputs(recorder, image):
    recorder.root('image', image)
    recorder.run(split_workflow, 'wf', {'image': image})
    run = recorder.graph().current('wf')
    assert set(run.outputs) == {'low', 'high'}


def test_runner_options_are_recorded_and_replayed_on_update(recorder, image):
    seen = []

    class Remembers:
        def run(self, fn, args, **options):
            seen.append(options)
            return fn(**args)

    recorder.inner = Remembers()
    recorder.root('image', image)
    recorder.run(
        blur,
        'blurred',
        {'image': image},
        variant='cuda',
        position={'z': 3},
        on_progress=print,
    )
    run = recorder.graph().current('blurred')
    assert run.options == {'variant': 'cuda', 'position': {'z': 3}}
    recorder.root('image', image + 1)
    recorder.update(blur, 'blurred')
    assert seen[-1] == {'variant': 'cuda', 'position': {'z': 3}}


def test_a_recording_runner_names_steps_by_their_inputs(recorder, image):
    listener = RecordingRunner(recorder)
    other = image + 1
    recorder.root('image', image)
    recorder.root('other', other)
    listener.run(blur, {'image': image})
    listener.run(blur, {'image': image, 'sigma': 3.0})
    listener.run(blur, {'image': other})
    assert recorder.graph().steps() == ['blur', 'blur_2']
    assert len(recorder.graph().runs_of('blur')) == 2


class Stoppable:
    """A runner that hands out a task and lets the op stop early, the way a
    worker's op returns what it has when it sees a cancel."""

    def __init__(self, fail: bool = False) -> None:
        self.fail = fail

    def run(self, fn, args, *, on_start=None, **options):
        class Task:
            cancelled = False

            def cancel(self):
                self.cancelled = True

        task = Task()
        if on_start is not None:
            on_start(task)
        if self.fail:
            raise RuntimeError('stopped')
        return fn(**args)


def test_a_cancelled_run_is_kept_but_never_current(recorder, image):
    recorder.root('image', image)
    recorder.run(blur, 'blurred', {'image': image})
    recorder.inner = Stoppable()
    handed = []

    def cancel(task):
        handed.append(task)
        task.cancel()

    recorder.run(
        blur, 'blurred', {'image': image, 'sigma': 9.0}, on_start=cancel
    )
    graph = recorder.graph()
    first, second = graph.runs_of('blurred')
    assert second.status == 'cancelled' and second.outputs
    assert graph.current('blurred') is first
    assert len(handed) == 1


def test_a_cancel_that_ends_in_an_error_is_a_cancel(recorder, image):
    recorder.root('image', image)
    recorder.inner = Stoppable(fail=True)
    with pytest.raises(RuntimeError):
        recorder.run(
            blur, 'blurred', {'image': image}, on_start=lambda t: t.cancel()
        )
    (run,) = recorder.graph().runs_of('blurred')
    assert run.status == 'cancelled'


def test_a_run_says_when_it_started_and_how_long_it_took(recorder, image):
    recorder.root('image', image)
    recorder.run(blur, 'blurred', {'image': image})
    run = recorder.graph().current('blurred')
    assert run.started.endswith('+00:00')
    assert run.duration >= 0


class Lazy:
    """Array-shaped without being numpy, as a dask or zarr array is."""

    def __init__(self, data):
        self._data = np.asarray(data)
        self.shape, self.dtype, self.ndim = (
            self._data.shape,
            self._data.dtype,
            self._data.ndim,
        )

    @property
    def size(self):
        return self._data.size

    def __getitem__(self, key):
        return self._data[key]

    def __array__(self, dtype=None, copy=None):
        return self._data if dtype is None else self._data.astype(dtype)


def test_an_array_that_is_not_numpy_is_known_by_identity(recorder, image):
    lazy = Lazy(image)
    root = recorder.root('image', lazy)
    recorder.run(blur, 'blurred', {'image': lazy})
    run = recorder.graph().current('blurred')
    assert run.inputs == {'image': root}
    assert np.array_equal(recorder.store.get(root), image)


def test_a_value_that_is_not_array_shaped_is_refused(recorder, image):
    recorder.root('image', image)
    with pytest.raises(TypeError, match='needs an array'):
        recorder.run(blur, 'blurred', {'image': [[1, 2], [3, 4]]})


def test_declaring_a_root_copies_nothing(recorder, image, tmp_path):
    handle = recorder.root('image', image)
    assert recorder.store.get(handle) is image
    assert not list((tmp_path / 'store').rglob('*image*'))


def test_kept_pixels_are_held_not_copied(recorder, image):
    recorder.root('image', image)
    blurred = recorder.run(blur, 'blurred', {'image': image})
    recorder.mark_edited('blurred')
    painted = blurred + 1
    recorder.accept_edit('blurred', painted)
    assert recorder.store.get(recorder.graph().accepted('blurred')) is painted


def test_an_axis_plan_that_changes_nothing_is_not_recorded(recorder, image):
    import skop
    from ops import plane

    recorder.root('image', image)
    passing = skop.plan(plane, 'image', image, ['y', 'x'])
    recorder.run(plane, 'flat', {'image': image}, plans={'image': passing})
    assert recorder.graph().current('flat').options == {}


def test_an_axis_plan_that_does_something_is_recorded(recorder, image):
    import skop
    from ops import plane

    stack = np.stack([image, image])
    recorder.root('stack', stack)
    iterating = skop.plan(plane, 'image', stack, ['z', 'y', 'x'])
    assert iterating.iterate  # a stack, run plane by plane
    out = recorder.run(
        plane, 'flat', {'image': stack}, plans={'image': iterating}
    )
    assert out.shape == stack.shape
    assert set(recorder.graph().current('flat').options['plans']) == {'image'}

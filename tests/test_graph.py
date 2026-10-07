"""The graph: everything derived from the log, and nothing stored."""

from __future__ import annotations

import numpy as np
import pytest
from ops import REGISTRY, add, blur, broken, split, threshold


def test_an_empty_log_is_an_empty_graph(recorder):
    graph = recorder.graph()
    assert graph.steps() == []
    assert graph.leaves() == []
    assert graph.closure(['nothing']) == []
    assert graph.current('nothing') is None
    assert not graph.is_stale('nothing')


def test_the_newest_good_run_is_current(recorder, image):
    recorder.root('image', image)
    recorder.run(blur, 'blurred', {'image': image, 'sigma': 1.0})
    recorder.run(blur, 'blurred', {'image': image, 'sigma': 2.0})
    with pytest.raises(TypeError):
        recorder.run(blur, 'blurred', {'image': image, 'sigma': None, 'x': 1})
    assert recorder.graph().current('blurred').params == {'sigma': 2.0}


def test_a_step_whose_every_run_failed_is_not_in_a_closure(recorder, image):
    recorder.root('image', image)
    with pytest.raises(RuntimeError):
        recorder.run(broken, 'broken', {'image': image})
    graph = recorder.graph()
    assert graph.steps() == ['broken']
    assert graph.closure(['broken']) == []
    assert graph.leaves() == []


def test_staleness_is_one_hop_and_produce_carries_it(recorder, image):
    recorder.root('image', image)
    blurred = recorder.run(blur, 'blurred', {'image': image})
    mask = recorder.run(threshold, 'mask', {'image': blurred})
    recorder.run(blur, 'again', {'image': mask})
    recorder.run(blur, 'blurred', {'image': image, 'sigma': 5.0})
    graph = recorder.graph()
    assert graph.is_stale('mask')
    # 'again' read the mask's current run, which has not moved yet: it is
    # behind only once the mask is brought up to date.
    assert not graph.is_stale('again')
    assert recorder.produce(['again'], REGISTRY) == ['mask', 'again']


def test_a_diamond_closure_lists_each_step_once(recorder, image):
    recorder.root('image', image)
    left = recorder.run(blur, 'left', {'image': image, 'sigma': 1.0})
    right = recorder.run(blur, 'right', {'image': image, 'sigma': 2.0})
    recorder.run(add, 'joined', {'a': left, 'b': right})
    graph = recorder.graph()
    assert graph.closure(['joined']) == ['left', 'right', 'joined']
    assert graph.upstream('joined') == (['left', 'right'], ['image'])
    assert graph.downstream('left') == ['joined']
    assert graph.leaves() == ['joined']


def test_two_roots_feed_one_step(recorder, image):
    other = image * 3
    recorder.root('a', image)
    recorder.root('b', other)
    recorder.run(add, 'sum', {'a': image, 'b': other})
    graph = recorder.graph()
    assert graph.upstream('sum') == ([], ['a', 'b'])
    recorder.root('b', other + 1)
    assert recorder.graph().is_stale('sum')


def test_a_root_and_a_step_may_share_a_name(recorder, image):
    recorder.root('blurred', image)
    out = recorder.run(blur, 'blurred', {'image': image})
    recorder.run(threshold, 'mask', {'image': out})
    graph = recorder.graph()
    assert graph.sources_of(graph.current('blurred')) == {
        'image': 'root:blurred'
    }
    assert graph.sources_of(graph.current('mask')) == {'image': 'blurred'}
    assert graph.closure(['mask']) == ['blurred', 'mask']


def test_edited_and_affected(recorder, image):
    recorder.root('image', image)
    blurred = recorder.run(blur, 'blurred', {'image': image})
    mask = recorder.run(threshold, 'mask', {'image': blurred})
    recorder.run(blur, 'after', {'image': mask})
    recorder.mark_edited('blurred')
    graph = recorder.graph()
    assert graph.is_edited('blurred')
    assert graph.is_affected('mask') and graph.is_affected('after')
    assert not graph.is_affected('blurred')
    recorder.mark_reverted('blurred')
    graph = recorder.graph()
    assert not graph.is_edited('blurred') and not graph.is_affected('after')


def test_an_edit_belongs_to_the_run_it_was_made_on(recorder, image):
    recorder.root('image', image)
    recorder.run(blur, 'blurred', {'image': image})
    recorder.mark_edited('blurred')
    recorder.run(blur, 'blurred', {'image': image, 'sigma': 4.0})
    assert not recorder.graph().is_edited('blurred')


def test_a_missing_root_is_not_stale_and_comes_back(recorder, image):
    recorder.root('image', image)
    recorder.run(blur, 'blurred', {'image': image})
    recorder.root_gone('image')
    graph = recorder.graph()
    assert graph.missing_inputs('blurred') == ['image']
    assert not graph.is_stale('blurred')
    recorder.root('image', image)
    graph = recorder.graph()
    assert graph.missing_inputs('blurred') == []
    assert graph.is_stale('blurred')


def test_a_consumer_of_one_output_is_not_stale_when_another_moves(
    recorder, image
):
    recorder.root('image', image)
    parts = recorder.run(split, 'parts', {'image': image})
    recorder.run(blur, 'from_low', {'image': parts.low})
    graph = recorder.graph()
    assert graph.sources_of(graph.current('from_low')) == {'image': 'parts'}
    assert graph.closure(['from_low']) == ['parts', 'from_low']


class TestAcceptingAnEdit:
    """Decision 34: a kept edit is stored, and the step is a root from then."""

    def _session(self, recorder, image):
        recorder.root('image', image)
        blurred = recorder.run(blur, 'blurred', {'image': image})
        recorder.run(threshold, 'mask', {'image': blurred})
        recorder.mark_edited('blurred')
        return blurred

    def test_keeping_stores_the_pixels_and_clears_the_edit(
        self, recorder, image
    ):
        blurred = self._session(recorder, image)
        painted = blurred.copy()
        painted[0, 0] = 99
        recorder.accept_edit('blurred', painted)
        graph = recorder.graph()
        assert graph.is_accepted('blurred')
        assert not graph.is_edited('blurred')
        handle = graph.accepted('blurred')
        assert np.array_equal(recorder.store.get(handle), painted)
        assert recorder.store.handle_of(painted) == handle

    def test_what_read_the_old_output_is_stale(self, recorder, image):
        blurred = self._session(recorder, image)
        recorder.accept_edit('blurred', blurred + 1)
        assert recorder.graph().is_stale('mask')

    def test_produce_reads_the_kept_pixels_and_never_reruns_the_step(
        self, recorder, image
    ):
        blurred = self._session(recorder, image)
        kept = np.full_like(blurred, 7.0)
        recorder.accept_edit('blurred', kept)
        recorder.root('image', image + 1)  # the step's own input moves too
        assert recorder.produce(['mask'], REGISTRY) == ['mask']
        graph = recorder.graph()
        assert len(graph.runs_of('blurred')) == 1
        assert not graph.is_stale('blurred')
        assert graph.current('mask').inputs == {
            'image': graph.accepted('blurred')
        }
        assert graph.sources_of(graph.current('mask')) == {'image': 'blurred'}
        assert graph.closure(['mask']) == ['blurred', 'mask']

    def test_running_the_step_again_supersedes_the_kept_edit(
        self, recorder, image
    ):
        blurred = self._session(recorder, image)
        recorder.accept_edit('blurred', blurred + 1)
        recorder.run(blur, 'blurred', {'image': image, 'sigma': 3.0})
        graph = recorder.graph()
        assert not graph.is_accepted('blurred')
        assert graph.accepted('blurred') is None

    def test_keeping_with_no_pixels_keeps_what_was_recorded(
        self, recorder, image
    ):
        self._session(recorder, image)
        recorder.accept_edit('blurred')
        graph = recorder.graph()
        assert graph.is_accepted('blurred')
        assert (
            graph.accepted('blurred')
            == graph.current('blurred').outputs['result']
        )


def test_each_output_of_a_step_can_be_kept(recorder, image):
    recorder.root('image', image)
    parts = recorder.run(split, 'parts', {'image': image})
    recorder.mark_edited('parts')
    recorder.accept_edit('parts', parts.low + 1, output='low')
    recorder.accept_edit('parts', parts.high + 2, output='high')
    graph = recorder.graph()
    low, high = graph.accepted('parts', 'low'), graph.accepted('parts', 'high')
    assert np.array_equal(recorder.store.get(low), parts.low + 1)
    assert np.array_equal(recorder.store.get(high), parts.high + 2)
    with pytest.raises(ValueError, match='say which'):
        recorder.accept_edit('parts', parts.low)
    with pytest.raises(KeyError):
        recorder.accept_edit('parts', parts.low, output='middle')


def test_reverting_a_kept_edit_moves_its_readers_back(recorder, image):
    recorder.root('image', image)
    blurred = recorder.run(blur, 'blurred', {'image': image})
    recorder.mark_edited('blurred')
    recorder.accept_edit('blurred', blurred + 1)
    kept = recorder.store.get(recorder.graph().accepted('blurred'))
    recorder.run(threshold, 'mask', {'image': kept})
    assert not recorder.graph().is_stale('mask')
    recorder.mark_reverted('blurred')
    graph = recorder.graph()
    assert not graph.is_accepted('blurred')
    assert graph.is_stale('mask')
    assert graph.sources_of(graph.current('mask')) == {'image': 'blurred'}
    assert recorder.produce(['mask'], REGISTRY) == ['mask']
    assert recorder.graph().current('mask').inputs == {
        'image': recorder.graph().current('blurred').outputs['result']
    }

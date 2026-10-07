"""The graph view: one model, a layout, and the Mermaid renderer."""

from __future__ import annotations

import pytest
from ops import add, blur, blur_then_threshold, broken, threshold

from skop_visual import (
    AFFECTED,
    COLOURS,
    EDITED,
    FAILED,
    FRESH,
    KEPT,
    SIGNALS,
    STALE,
    layout,
    lineage,
    to_mermaid,
    view,
)


def badges(recorder) -> dict[str, str]:
    return {node.step: node.badge for node in view(recorder.graph()).nodes}


def test_every_badge_has_a_signal_and_a_colour():
    assert set(SIGNALS) == set(COLOURS)


def test_an_empty_graph_draws(recorder):
    picture = view(recorder.graph())
    assert picture.nodes == () and picture.edges == ()
    grid = layout(picture)
    assert grid.nodes == () and grid.columns == 1
    assert to_mermaid(picture).startswith('flowchart')


def test_badges_follow_the_log(recorder, image):
    recorder.root('image', image)
    blurred = recorder.run(blur, 'blurred', {'image': image})
    recorder.run(threshold, 'mask', {'image': blurred})
    assert badges(recorder) == {'blurred': FRESH, 'mask': FRESH}
    recorder.mark_edited('blurred')
    assert badges(recorder) == {'blurred': EDITED, 'mask': AFFECTED}
    recorder.accept_edit('blurred', blurred + 1)
    assert badges(recorder) == {'blurred': KEPT, 'mask': STALE}
    with pytest.raises(RuntimeError):
        recorder.run(broken, 'broken', {'image': image})
    assert badges(recorder)['broken'] == FAILED


def test_a_failed_rerun_still_shows_the_run_that_stands(recorder, image):
    recorder.root('image', image)
    recorder.run(blur, 'blurred', {'image': image})
    with pytest.raises(TypeError):
        recorder.run(blur, 'blurred', {'image': image, 'sigma': {1, 2}})
    (node,) = view(recorder.graph()).nodes
    # A refused call is never run, so it is not a run; the one before stands.
    assert node.badge == FRESH and node.current is not None


def test_a_root_and_a_step_of_one_name_are_two_nodes(recorder, image):
    recorder.root('blurred', image)
    recorder.run(blur, 'blurred', {'image': image})
    grid = layout(view(recorder.graph()))
    assert {n.key for n in grid.nodes} == {'root:blurred', 'blurred'}
    assert grid.edges == (('root:blurred', 'blurred', 'image'),)


def test_a_kept_step_draws_as_a_step_its_readers_hang_off(recorder, image):
    recorder.root('image', image)
    blurred = recorder.run(blur, 'blurred', {'image': image})
    recorder.mark_edited('blurred')
    recorder.accept_edit('blurred', blurred + 1)
    recorder.run(
        threshold,
        'mask',
        {'image': recorder.store.get(recorder.graph().accepted('blurred'))},
    )
    picture = view(recorder.graph())
    (edge,) = [e for e in picture.edges if e.target == 'mask']
    assert edge.source == 'blurred' and edge.root is None


def test_a_workflow_draws_as_one_node(recorder, image):
    recorder.root('image', image)
    recorder.run(blur_then_threshold, 'wf', {'image': image})
    picture = view(recorder.graph())
    assert [n.step for n in picture.nodes] == ['wf']


def test_the_layout_puts_every_edge_rightwards(recorder, image):
    recorder.root('image', image)
    left = recorder.run(blur, 'left', {'image': image})
    right = recorder.run(blur, 'right', {'image': left})
    recorder.run(add, 'joined', {'a': left, 'b': right})
    grid = layout(view(recorder.graph()))
    col = {n.key: n.col for n in grid.nodes}
    assert all(col[a] < col[b] for a, b, _ in grid.edges)
    assert col['joined'] == 3


def test_mermaid_escapes_what_it_cannot_carry(recorder, image):
    recorder.root('say "hi" & bye', image)
    recorder.run(blur, 'a "quoted" step', {'image': image})
    text = to_mermaid(view(recorder.graph()))
    assert '"hi"' not in text and '#quot;' in text and '&amp;' in text


def test_lineage_of_a_step_with_no_inputs_upstream(recorder, image):
    recorder.root('image', image)
    recorder.run(blur, 'blurred', {'image': image})
    path = lineage(recorder.graph(), 'blurred')
    assert path.upstream == () and path.roots == ('image',)
    assert path.touches('root:image') and not path.touches('image')

"""The recorder in front of scikit-ops' own Runner, as a host uses it.

Only workflows and ops that name no environment, so nothing is built: what is
under test is the ambient-runner contract (decision 16), progress reaching
the caller, and nested calls staying with the thread that made them.
"""

from __future__ import annotations

import threading

import numpy as np
import pytest
import skop
from ops import blur, blur_then_threshold
from skop import op
from skop.types import ImageOf

from skop_core import Recorder, RecordingRunner


@op()
def reports(image: ImageOf[np.ndarray]) -> ImageOf[np.ndarray]:
    """A workflow that says how far along it is, then calls an op."""
    skop.progress('halfway', 1, 2)
    return skop.run(blur, {'image': image})


@op()
def stops(image: ImageOf[np.ndarray]) -> ImageOf[np.ndarray]:
    """A workflow that stops early when asked, between two ops."""
    first = skop.run(blur, {'image': image})
    if skop.cancel_requested():
        return first
    return skop.run(blur, {'image': first})


@pytest.fixture
def runner():
    with skop.Runner() as found:
        yield found


@pytest.fixture
def recorded(store, runner) -> Recorder:
    return Recorder(store, runner)


def test_a_workflow_on_the_real_runner_records_its_calls(recorded, image):
    recorded.root('image', image)
    recorded.run(blur_then_threshold, 'wf', {'image': image})
    graph = recorded.graph()
    children = graph.children_of(graph.current('wf'))
    assert [c.step for c in children] == ['wf.blur', 'wf.threshold']
    assert children[1].inputs['image'] == children[0].outputs['result']


def test_a_listener_installed_by_hand_records_a_script(recorded, image):
    recorded.root('image', image)
    with skop.ambient(RecordingRunner(recorded)):
        skop.run(blur, {'image': image, 'sigma': 3.0})
    assert recorded.graph().current('blur').params == {'sigma': 3.0}


def test_progress_from_a_workflow_reaches_the_caller(recorded, image):
    recorded.root('image', image)
    heard = []
    RecordingRunner(recorded).run(
        reports, {'image': image}, on_progress=heard.append
    )
    assert any(getattr(e, 'message', None) == 'halfway' for e in heard)


def test_a_cancel_handle_is_handed_over_once(recorded, image):
    recorded.root('image', image)
    started = []
    RecordingRunner(recorded).run(
        blur_then_threshold, {'image': image}, on_start=started.append
    )
    assert len(started) == 1 and hasattr(started[0], 'cancel')


def test_a_cancel_reaches_the_workflow_itself(recorded, image):
    recorded.root('image', image)

    def cancel_at_once(task):
        task.cancel()

    RecordingRunner(recorded).run(
        stops, {'image': image}, on_start=cancel_at_once
    )
    graph = recorded.graph()
    (run,) = graph.runs_of('stops')
    assert run.status == 'cancelled'
    assert len(graph.children_of(run)) == 1
    # What it handed back is kept to look at, and stands for nothing.
    assert graph.current('stops') is None and run.outputs


def test_two_threads_keep_their_own_parents(recorded, image):
    other = image + 1
    recorded.root('a', image)
    recorded.root('b', other)
    listener = RecordingRunner(recorded)
    errors: list[BaseException] = []

    def go(array: np.ndarray) -> None:
        try:
            for _ in range(5):
                listener.run(blur_then_threshold, {'image': array})
        except BaseException as error:  # noqa: BLE001 -- surfaced below
            errors.append(error)

    threads = [threading.Thread(target=go, args=(a,)) for a in (image, other)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert not errors
    graph = recorded.graph()
    for parent in [r for r in graph.runs if r.parent is None]:
        children = graph.children_of(parent)
        assert len(children) == 2
        assert all(c.step.startswith(parent.step + '.') for c in children)
        assert children[0].inputs['image'] == parent.inputs['image']

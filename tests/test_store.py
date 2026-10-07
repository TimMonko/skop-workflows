"""The Store protocol, held to the same account by every backend."""

from __future__ import annotations

import gc
import threading

import numpy as np
import pytest
from conftest import open_store

from skop_core import Event, Root, Run


def test_put_then_get_round_trips(store, image):
    handle = store.put('image', image)
    assert np.array_equal(store.get(handle), image)
    assert store.get(handle).dtype == image.dtype


def test_each_put_is_a_new_handle(store, image):
    first = store.put('image', image)
    second = store.put('image', image + 1)
    assert first != second
    assert np.array_equal(store.get(first), image)
    assert np.array_equal(store.get(second), image + 1)


def test_handle_of_knows_the_exact_object(store, image):
    handle = store.put('image', image)
    assert store.handle_of(image) == handle
    assert store.handle_of(image.copy()) is None
    # A view shares the pixels but is not the array the store was handed.
    assert store.handle_of(image[:]) is None


def test_what_get_returns_is_known_by_its_handle(store, image):
    handle = store.put('image', image)
    loaded = store.get(handle)
    assert store.handle_of(loaded) == handle


def test_a_collected_array_does_not_lend_its_id(store):
    store.put('image', np.ones(3))
    gc.collect()
    # Allocate until an id is reused; whatever reuses it is a stranger.
    for _ in range(200):
        fresh = np.zeros(3)
        assert store.handle_of(fresh) is None


def test_describe_says_name_ndim_dtype(store, image):
    handle = store.put('image', image.astype(np.uint16))
    assert store.describe(handle) == {
        'name': 'image',
        'ndim': 2,
        'dtype': 'uint16',
    }


@pytest.mark.parametrize(
    'name',
    [
        'ch1: DAPI',  # a colon is not a file name on Windows
        'a/b',  # nor is a slash anywhere
        '..',
        'Image',  # and case does not tell files apart on Windows or macOS
        'image',
        'smooth.result',
        'blobs [1] (2)',
        'con',  # a reserved device name on Windows
        'v1@v2',
        'ünïcode',
    ],
)
def test_any_layer_name_can_be_stored(store, name, image):
    handle = store.put(name, image)
    assert np.array_equal(store.get(handle), image)
    assert store.describe(handle)['name'] == name


def test_names_that_differ_only_in_case_stay_apart(store, image):
    upper = store.put('Image', image)
    lower = store.put('image', image + 1)
    assert np.array_equal(store.get(upper), image)
    assert np.array_equal(store.get(lower), image + 1)


def test_a_scalar_output_is_stored(store):
    handle = store.put('count', np.int64(7))
    assert int(store.get(handle)) == 7
    assert store.describe(handle)['ndim'] == 0


def test_an_object_that_is_not_an_array_is_refused(store):
    with pytest.raises(TypeError, match='not an array'):
        store.put('things', {'a': 1})


def test_an_unknown_handle_is_refused(store):
    with pytest.raises((KeyError, ValueError)):
        store.get('nothing@v1')


def test_records_come_back_in_order(store, image):
    handle = store.put('image', image)
    records = [
        Root(id='r1', name='image', handle=handle),
        Run(id='a', step='s', op='m:f', inputs={'image': handle}),
        Event(id='e', kind='edited', run='a', note='painted'),
    ]
    for record in records:
        store.append(record)
    assert store.records() == records


def test_a_reopened_store_has_its_log_and_arrays(backend, tmp_path, image):
    first = open_store(backend, tmp_path / 's')
    handle = first.put('image', image)
    first.append(Root(id='r1', name='image', handle=handle))
    second_handle = first.put('image', image * 2)
    first.append(Root(id='r2', name='image', handle=second_handle))

    again = open_store(backend, tmp_path / 's')
    assert [r.id for r in again.records()] == ['r1', 'r2']
    assert np.array_equal(again.get(second_handle), image * 2)
    # And a new version does not overwrite one written before reopening.
    third = again.put('image', image * 3)
    assert third not in (handle, second_handle)
    assert np.array_equal(again.get(handle), image)


def test_puts_from_two_threads_do_not_collide(backend, tmp_path):
    if backend == 'icechunk':
        pytest.skip('one Icechunk session is not shared across threads')
    store = open_store(backend, tmp_path / 's')
    handles: list[str] = []

    def put(value: float) -> None:
        for _ in range(10):
            handles.append(store.put('image', np.full(3, value)))

    threads = [threading.Thread(target=put, args=(v,)) for v in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(set(handles)) == 40


class TestReferences:
    """A root is held by reference: never written, handed back as itself."""

    def test_a_referred_object_comes_back_as_itself(self, store, image):
        handle = store.refer('image', image)
        assert store.get(handle) is image
        assert store.handle_of(image) == handle

    def test_nothing_is_written(self, store, image, tmp_path):
        before = sorted(p.name for p in (tmp_path / 'store').rglob('*'))
        store.refer('image', image)
        after = sorted(p.name for p in (tmp_path / 'store').rglob('*'))
        assert before == after

    def test_it_is_described_without_being_read(self, store, image):
        handle = store.refer('ch1: DAPI', image.astype(np.uint8))
        assert store.describe(handle) == {
            'name': 'ch1: DAPI',
            'ndim': 2,
            'dtype': 'uint8',
        }

    def test_each_reference_is_a_new_handle(self, store, image):
        first = store.refer('image', image)
        second = store.refer('image', image)
        assert first != second
        assert store.handle_of(image) == second

    def test_the_newest_version_is_kept_alive(self, store):
        handle = store.refer('image', np.ones(3))  # nobody else holds it
        gc.collect()
        assert np.array_equal(store.get(handle), np.ones(3))

    def test_an_older_version_lives_only_as_long_as_its_owner(self, store):
        older = store.refer('image', np.ones(3))
        store.refer('image', np.zeros(3))
        gc.collect()
        with pytest.raises(KeyError, match='no longer'):
            store.get(older)
        # Still described: what it was is recorded, not read.
        assert store.describe(older)['ndim'] == 1

    def test_what_is_not_array_shaped_is_refused(self, store):
        with pytest.raises(TypeError, match='not an array'):
            store.refer('things', {'a': 1})

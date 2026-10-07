"""Where arrays and run records land: Icechunk.

The second backend, behind the same ``Store`` protocol as ``SimpleStore``;
nothing above ``store.py`` knows which one is in use.

The commit shape is the point of this one. Everything a run writes is staged
in an Icechunk session and lands in a single commit: the arrays, the run
record itself (as the commit metadata), and a small index saying which handle
belongs to which array. Every snapshot is therefore one complete run, and a
crash between two runs loses nothing.

Handles are this store's own tokens -- ``<name>@<short id>`` -- and nothing
outside the store parses them; an index carried in each commit is how a
handle finds its snapshot and path again.

Icechunk is an optional extra, so import the backend by its own path::

    uv sync --group icechunk
    from skop_core.icechunk_store import IcechunkStore

One instance owns the repository: commits made elsewhere are not seen until
the store is reopened. It is safe to use from two threads -- a host records
off its GUI thread while drawing the graph on it -- because every call holds
one lock, and Icechunk sessions are not to be shared unguarded. Icechunk warns that local-filesystem storage is unsafe
for concurrent commits, which is fine for one recorder and not for a shared
folder.
"""

from __future__ import annotations

import contextlib
import re
import threading
import uuid
import weakref
from pathlib import Path
from typing import TYPE_CHECKING, Any

import icechunk
import numpy as np
import zarr

from .record import Handle, Record, from_dict
from .store import as_storable, decode_name, encode_name

if TYPE_CHECKING:
    from .store import Store

#: The branch every commit lands on.
BRANCH = 'main'

_ARRAYS = 'arrays'
_VERSION = re.compile(r'^v(?P<version>\d+)$')


class IcechunkStore:
    """Arrays and records in an Icechunk repository, one commit per run."""

    def __init__(self, root: str | Path) -> None:
        storage = icechunk.local_filesystem_storage(str(root))
        self.repo = icechunk.Repository.open_or_create(storage)
        self._ids: dict[int, tuple[weakref.ref, Handle]] = {}
        self._session: Any = None
        self._staged: dict[Handle, str] = {}
        self._records: list[Record] = []
        self._places: dict[Handle, tuple[str, str]] = {}
        self._versions: dict[str, int] = {}
        self._readers: dict[str, Any] = {}
        self._lock = threading.RLock()
        self._load()

    # -- arrays ----------------------------------------------------------

    def put(self, path: str, array: Any) -> Handle:
        with self._lock:
            stored = as_storable(array)
            session = self._writable()
            version = self._versions.get(path, 0) + 1
            self._versions[path] = version
            place = f'{_ARRAYS}/{encode_name(path)}/v{version}'
            zarr.create_array(
                session.store, name=place, data=stored, overwrite=True
            )
            handle = f'{path}@{uuid.uuid4().hex[:8]}'
            self._staged[handle] = place
            self._remember(array, handle)
            return handle

    def get(self, handle: Handle) -> np.ndarray:
        with self._lock:
            snapshot, place = self._where(handle)
            array = zarr.open_array(
                self._reader(snapshot).store, path=place, mode='r'
            )
            found = np.asarray(array[...])
            self._remember(found, handle)
            return found

    def handle_of(self, array: object) -> Handle | None:
        seen = self._ids.get(id(array))
        if seen is None:
            return None
        ref, handle = seen
        # id() is reused after collection, so the weakref is the real check.
        return handle if ref() is array else None

    def describe(self, handle: Handle) -> dict[str, Any]:
        with self._lock:
            snapshot, place = self._where(handle)
            array = zarr.open_array(
                self._reader(snapshot).store, path=place, mode='r'
            )
            return {
                'name': decode_name(place.split('/')[1]),
                'ndim': array.ndim,
                'dtype': str(array.dtype),
            }

    # -- records ---------------------------------------------------------

    def append(self, record: Record) -> None:
        with self._lock:
            session = self._writable()
            what = getattr(record, 'step', None) or record.id
            snapshot = session.commit(
                message=f'{record.kind} {what}',
                metadata={
                    'record': record.to_dict(),
                    'places': dict(self._staged),
                },
                allow_empty=True,
            )
            self._records.append(record)
            for handle, place in self._staged.items():
                self._places[handle] = (snapshot, place)
            # A committed session's store is read-only; the next write opens one.
            self._session = None
            self._staged = {}

    def records(self) -> list[Record]:
        with self._lock:
            return list(self._records)

    # -- internals -------------------------------------------------------

    def _writable(self) -> Any:
        if self._session is None:
            self._session = self.repo.writable_session(BRANCH)
        return self._session

    def _where(self, handle: Handle) -> tuple[str | None, str]:
        """The snapshot and path a handle names, staged or committed."""
        if handle in self._places:
            return self._places[handle]
        if handle in self._staged:
            return None, self._staged[handle]
        raise KeyError(f'{handle!r} is not a handle this store issued')

    def _reader(self, snapshot: str | None) -> Any:
        """A session to read one snapshot from, or the open write session."""
        if snapshot is None:
            return self._writable()
        if snapshot not in self._readers:
            self._readers[snapshot] = self.repo.readonly_session(
                snapshot_id=snapshot
            )
        return self._readers[snapshot]

    def _load(self) -> None:
        """Rebuild the log, the handle index and the version counts."""
        commits = reversed(list(self.repo.ancestry(branch=BRANCH)))
        for commit in commits:
            metadata = dict(commit.metadata)
            record = metadata.get('record')
            if record is not None:
                self._records.append(from_dict(record))
            for handle, place in dict(metadata.get('places', {})).items():
                self._places[handle] = (commit.id, place)
                parts = place.split('/')
                match = _VERSION.match(parts[2]) if len(parts) == 3 else None
                if parts[0] == _ARRAYS and match is not None:
                    name = decode_name(parts[1])
                    number = int(match['version'])
                    self._versions[name] = max(
                        self._versions.get(name, 0), number
                    )

    def _remember(self, array: object, handle: Handle) -> None:
        # A Python scalar cannot be weakly referenced; see SimpleStore.
        with contextlib.suppress(TypeError):
            self._ids[id(array)] = (weakref.ref(array), handle)


if TYPE_CHECKING:
    # Only here so the type checker proves the protocol is satisfied.
    def _conforms(store: IcechunkStore) -> Store:
        return store

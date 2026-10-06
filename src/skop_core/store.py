"""Where arrays and run records land.

Icechunk is one such place. This is the other: a directory of ``.npy`` files
beside a JSON Lines log, which needs nothing but numpy and shows that nothing
above the store depends on which one is in use.
"""

from __future__ import annotations

import contextlib
import json
import re
import threading
import weakref
from pathlib import Path
from typing import Any, Protocol

import numpy as np

from .record import Event, Handle, Root, Run, from_dict

_HANDLE = re.compile(r'^(?P<path>.+)@v(?P<version>\d+)$')


class Store(Protocol):
    """What the recorder needs from wherever the data lives."""

    def put(self, path: str, array: np.ndarray) -> Handle: ...

    def get(self, handle: Handle) -> np.ndarray: ...

    def handle_of(self, array: np.ndarray) -> Handle | None:
        """The handle an array already has, or None if the store never saw it."""
        ...

    def describe(self, handle: Handle) -> dict[str, Any]:
        """What a handle is, without resolving it: its name, ndim and dtype."""
        ...

    def append(self, record: Run | Root | Event) -> None: ...

    def records(self) -> list[Run | Root | Event]: ...


class SimpleStore:
    """A directory of arrays and an append-only log.

    Safe to use from two threads, because a host that runs ops off its GUI
    thread records on one thread while drawing the graph from another.
    """

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        (self.root / 'arrays').mkdir(parents=True, exist_ok=True)
        self.log_path = self.root / 'log.jsonl'
        self._ids: dict[int, tuple[weakref.ref, Handle]] = {}
        self._lock = threading.RLock()

    # -- arrays ----------------------------------------------------------

    def put(self, path: str, array: np.ndarray) -> Handle:
        with self._lock:
            version = len(list(self._versions(path))) + 1
            target = self._array_path(path, version)
            target.parent.mkdir(parents=True, exist_ok=True)
            np.save(target, np.asarray(array))
            handle = f'{path}@v{version}'
            self._remember(array, handle)
            return handle

    def get(self, handle: Handle) -> np.ndarray:
        path, version = self._split(handle)
        array = np.load(self._array_path(path, version))
        self._remember(array, handle)
        return array

    def handle_of(self, array: np.ndarray) -> Handle | None:
        found = self._ids.get(id(array))
        if found is None:
            return None
        ref, handle = found
        # id() is reused after collection, so the weakref is the real check.
        return handle if ref() is array else None

    def describe(self, handle: Handle) -> dict[str, Any]:
        path, version = self._split(handle)
        array = np.load(self._array_path(path, version), mmap_mode='r')
        return {'name': path, 'ndim': array.ndim, 'dtype': str(array.dtype)}

    def versions(self, path: str) -> list[Handle]:
        return [f'{path}@v{v}' for v in self._versions(path)]

    # -- records ---------------------------------------------------------

    def append(self, record: Run | Root | Event) -> None:
        with self._lock, self.log_path.open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(record.to_dict()) + '\n')

    def records(self) -> list[Run | Root | Event]:
        with self._lock:
            if not self.log_path.exists():
                return []
            lines = self.log_path.read_text(encoding='utf-8').splitlines()
        return [from_dict(json.loads(line)) for line in lines if line.strip()]

    # -- internals -------------------------------------------------------

    def _array_path(self, path: str, version: int) -> Path:
        return self.root / 'arrays' / path / f'v{version}.npy'

    def _versions(self, path: str) -> list[int]:
        folder = self.root / 'arrays' / path
        if not folder.is_dir():
            return []
        return sorted(int(p.stem[1:]) for p in folder.glob('v*.npy'))

    def _split(self, handle: Handle) -> tuple[str, int]:
        match = _HANDLE.match(handle)
        if match is None:
            raise ValueError(f'{handle!r} is not a handle this store issued')
        return match['path'], int(match['version'])

    def _remember(self, array: np.ndarray, handle: Handle) -> None:
        # A Python scalar cannot be weakly referenced, and nothing reads one
        # as an array input, so there is no lineage to keep for it.
        with contextlib.suppress(TypeError):
            self._ids[id(array)] = (weakref.ref(array), handle)

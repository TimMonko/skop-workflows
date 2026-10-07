"""Where arrays and run records land.

Icechunk is one such place. This is the other: a directory of ``.npy`` files
beside a JSON Lines log, which needs nothing but numpy and shows that nothing
above the store depends on which one is in use.

Both backends share the rules that are about names and values rather than
storage: how a step's or a layer's name becomes a path segment
(:func:`encode_name`), and what a store will write at all
(:func:`as_storable`).
"""

from __future__ import annotations

import contextlib
import json
import re
import threading
import weakref
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import unquote

import numpy as np

from .record import Handle, Record, from_dict

_HANDLE = re.compile(r'^(?P<path>.+)@v(?P<version>\d+)$')

#: What may stand for itself in a stored name; everything else is escaped.
#: Lower case only, because Windows and macOS do not tell 'Image' from
#: 'image', and no dot, so that no name is ever '.' or '..'.
_PLAIN = frozenset('abcdefghijklmnopqrstuvwxyz0123456789_-')
#: Names Windows will not create a file or folder under.
_RESERVED = frozenset(
    {'con', 'prn', 'aux', 'nul'}
    | {f'com{i}' for i in range(10)}
    | {f'lpt{i}' for i in range(10)}
)


def _escape(char: str) -> str:
    return ''.join(f'%{byte:02X}' for byte in char.encode('utf-8'))


def encode_name(name: str) -> str:
    """A name as one path segment that every filesystem keeps apart.

    A name is a step's or a layer's, and a layer may be called anything --
    ``ch1: DAPI``, ``a/b``, ``Image`` beside ``image`` -- none of which
    survives as a folder name everywhere. The encoding is reversible
    (:func:`decode_name`) and stays one-to-one where case is not significant,
    and it serves zarr's node names too, which must not hold a slash or begin
    with two underscores.
    """
    if not name:
        raise ValueError('a stored name cannot be empty')
    out = ''.join(c if c in _PLAIN else _escape(c) for c in name)
    if out in _RESERVED or out.startswith('__'):
        out = _escape(out[0]) + out[1:]
    return out


def decode_name(segment: str) -> str:
    """The name :func:`encode_name` was given."""
    return unquote(segment)


def as_storable(value: Any) -> np.ndarray:
    """A value as the array a store writes, or a refusal in words.

    A scalar output -- a count, a threshold -- is stored as a 0-d array. What
    numpy can only hold as Python objects (a dict, a ragged list) has no
    portable form, and is refused rather than pickled.
    """
    array = np.asarray(value)
    if array.dtype == object:
        raise TypeError(
            f'{type(value).__name__} is not an array, so it cannot be stored'
        )
    return array


class Store(Protocol):
    """What the recorder needs from wherever the data lives."""

    def put(self, path: str, array: Any) -> Handle: ...

    def get(self, handle: Handle) -> np.ndarray: ...

    def handle_of(self, array: object) -> Handle | None:
        """The handle an array already has, or None if the store never saw it."""
        ...

    def describe(self, handle: Handle) -> dict[str, Any]:
        """What a handle is, without resolving it: its name, ndim and dtype."""
        ...

    def append(self, record: Record) -> None: ...

    def records(self) -> list[Record]: ...


class SimpleStore:
    """A directory of arrays and an append-only log.

    Safe to use from two threads, because a host that runs ops off its GUI
    thread records on one thread while drawing the graph from another.

    The log is read once, when it is first asked for, and kept: this instance
    is its only writer. A second instance on the same folder sees the first's
    records only if it is opened after them, as with ``IcechunkStore``.
    """

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        (self.root / 'arrays').mkdir(parents=True, exist_ok=True)
        self.log_path = self.root / 'log.jsonl'
        self._ids: dict[int, tuple[weakref.ref, Handle]] = {}
        self._lock = threading.RLock()
        self._records: list[Record] | None = None

    # -- arrays ----------------------------------------------------------

    def put(self, path: str, array: Any) -> Handle:
        stored = as_storable(array)
        with self._lock:
            versions = self._versions(path)
            version = (versions[-1] if versions else 0) + 1
            target = self._array_path(path, version)
            target.parent.mkdir(parents=True, exist_ok=True)
            np.save(target, stored, allow_pickle=False)
            handle = f'{path}@v{version}'
            self._remember(array, handle)
            return handle

    def get(self, handle: Handle) -> np.ndarray:
        target = self._array_path(*self._split(handle))
        if not target.is_file():
            raise KeyError(f'{handle!r} is not a handle this store issued')
        array = np.load(target)
        self._remember(array, handle)
        return array

    def handle_of(self, array: object) -> Handle | None:
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

    def append(self, record: Record) -> None:
        line = json.dumps(record.to_dict())
        with self._lock:
            records = self._loaded()
            with self.log_path.open('a', encoding='utf-8') as stream:
                stream.write(line + '\n')
            records.append(record)

    def records(self) -> list[Record]:
        with self._lock:
            return list(self._loaded())

    # -- internals -------------------------------------------------------

    def _loaded(self) -> list[Record]:
        if self._records is None:
            lines = (
                self.log_path.read_text(encoding='utf-8').splitlines()
                if self.log_path.exists()
                else []
            )
            self._records = [
                from_dict(json.loads(line)) for line in lines if line.strip()
            ]
        return self._records

    def _array_path(self, path: str, version: int) -> Path:
        return self.root / 'arrays' / encode_name(path) / f'v{version}.npy'

    def _versions(self, path: str) -> list[int]:
        folder = self.root / 'arrays' / encode_name(path)
        if not folder.is_dir():
            return []
        return sorted(int(p.stem[1:]) for p in folder.glob('v*.npy'))

    def _split(self, handle: Handle) -> tuple[str, int]:
        match = _HANDLE.match(handle)
        if match is None:
            raise KeyError(f'{handle!r} is not a handle this store issued')
        return match['path'], int(match['version'])

    def _remember(self, array: object, handle: Handle) -> None:
        # A Python scalar cannot be weakly referenced, and nothing reads one
        # as an array input, so there is no lineage to keep for it.
        with contextlib.suppress(TypeError):
            self._ids[id(array)] = (weakref.ref(array), handle)

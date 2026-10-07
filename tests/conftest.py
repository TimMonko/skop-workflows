"""Fixtures: a store of each kind, and a recorder over it."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from skop_core import InProcess, Recorder, SimpleStore  # noqa: E402

try:  # the Icechunk backend is an optional extra
    from skop_core.icechunk_store import IcechunkStore
except ImportError:  # pragma: no cover - depends on the environment
    IcechunkStore = None

BACKENDS = ['simple'] + (['icechunk'] if IcechunkStore is not None else [])


def open_store(kind: str, path: Path):
    if kind == 'simple':
        return SimpleStore(path)
    assert IcechunkStore is not None
    return IcechunkStore(path)


@pytest.fixture(params=BACKENDS)
def backend(request) -> str:
    return request.param


@pytest.fixture
def store(backend, tmp_path):
    return open_store(backend, tmp_path / 'store')


@pytest.fixture
def recorder(store) -> Recorder:
    return Recorder(store, InProcess(), version='test')


@pytest.fixture
def image() -> np.ndarray:
    return np.arange(16, dtype=float).reshape(4, 4) / 16

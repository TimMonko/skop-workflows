"""The demo scenario: a recorded session to look at.

Shared by ``headless.py`` (which asserts it) and the marimo graph app (which
draws it). Numpy-only ops; nothing built, nothing imported beyond skop_core.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from demo_ops import connect, gaussian, otsu, percentile

from skop_core import InProcess, Recorder, SimpleStore


def blobs(
    shape: tuple[int, int] = (96, 96), seed: int = 0, count: int = 10
) -> np.ndarray:
    """A deterministic image of soft round things."""
    rng = np.random.default_rng(seed)
    rows, cols = np.mgrid[0 : shape[0], 0 : shape[1]]
    image = np.zeros(shape, dtype=float)
    for _ in range(count):
        cy, cx = rng.uniform(16, shape[0] - 16), rng.uniform(16, shape[1] - 16)
        radius = rng.uniform(4, 9)
        image += np.exp(
            -((rows - cy) ** 2 + (cols - cx) ** 2) / (2 * radius**2)
        )
    return image + rng.normal(0.0, 0.01, shape)


def session(work: Path, name: str) -> Recorder:
    """A recorder in its own store under ``work``."""
    return Recorder(SimpleStore(work / name), InProcess(), version='demo 0.1')


def build(work: Path, name: str = 'graph-demo') -> Recorder:
    """Record the demo's steps 1-7, ready to draw.

    Ends in the state the demo cares about: a sigma sweep with one current
    run, a stale step, a hand edit, a step downstream of that edit, and an
    abandoned branch.
    """
    recorder = session(work, name)
    image = blobs(seed=1)
    recorder.root('image', image)
    normalized = recorder.run(
        percentile, 'normalized', {'image': image, 'low': 1.0, 'high': 99.8}
    )
    recorder.run(gaussian, 'smoothed', {'image': normalized, 'sigma': 2.0})
    recorder.run(gaussian, 'smoothed', {'image': normalized, 'sigma': 17.0})
    smoothed = recorder.run(
        gaussian, 'smoothed', {'image': normalized, 'sigma': 18.0}
    )
    labels = recorder.run(otsu, 'labels', {'image': smoothed})
    recorder.run(connect, 'components', {'labels': labels})
    recorder.run(gaussian, 'smoothed', {'image': normalized, 'sigma': 2.0})
    recorder.mark_edited('labels', 'painted two cells')
    recorder.run(gaussian, 'smoothed_alt', {'image': normalized, 'sigma': 9.0})
    return recorder

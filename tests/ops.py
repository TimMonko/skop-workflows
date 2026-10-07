"""Small ops for the tests, numpy only and run in this process.

Each one is shaped to reach a corner of the recorder: several outputs as a
NamedTuple and as a plain tuple, a scalar output, an output buffer, an
optional array, an op that hands its input straight back, and workflows that
call other ops through the ambient runner.
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Annotated, NamedTuple

import numpy as np
import skop
from skop import Axes, Out, op
from skop.types import ImageOf, LabelsOf


@op()
def blur(
    image: ImageOf[np.ndarray], sigma: float = 1.0
) -> ImageOf[np.ndarray]:
    """A stand-in for a smoothing op: deterministic, and depends on sigma."""
    return np.asarray(image, dtype=float) * 0.5 + sigma


@op()
def threshold(
    image: ImageOf[np.ndarray], level: float = 0.5
) -> LabelsOf[np.ndarray]:
    """A mask of what lies above a level."""
    return (np.asarray(image) > level).astype(np.uint8)


@op()
def add(a: ImageOf[np.ndarray], b: ImageOf[np.ndarray]) -> ImageOf[np.ndarray]:
    """Two inputs, so a step can join two branches."""
    return np.asarray(a) + np.asarray(b)


class Split(NamedTuple):
    low: np.ndarray
    high: np.ndarray


@op()
def split(image: ImageOf[np.ndarray], at: float = 0.5) -> Split:
    """Two named outputs, as a NamedTuple."""
    image = np.asarray(image, dtype=float)
    return Split(low=np.minimum(image, at), high=np.maximum(image, at))


class Counted(NamedTuple):
    labels: np.ndarray
    count: int


@op()
def count(image: ImageOf[np.ndarray]) -> Counted:
    """An array and a scalar, side by side."""
    labels = (np.asarray(image) > 0).astype(np.int32)
    return Counted(labels=labels, count=int(labels.sum()))


@op()
def total(image: ImageOf[np.ndarray]) -> float:
    """A single scalar output, as a measurement op returns."""
    return float(np.asarray(image).sum())


@op()
def scale_into(
    image: ImageOf[np.ndarray],
    result: Out[ImageOf[np.ndarray]],
    factor: float = 2.0,
) -> None:
    """Computer form: fill a buffer the caller allocated."""
    np.multiply(image, factor, out=result, casting='unsafe')


@op()
def masked(
    image: ImageOf[np.ndarray], mask: LabelsOf[np.ndarray] | None = None
) -> ImageOf[np.ndarray]:
    """An optional array: an input when given, a parameter when not."""
    image = np.asarray(image, dtype=float)
    return image if mask is None else image * (np.asarray(mask) > 0)


@op()
def same(image: ImageOf[np.ndarray]) -> ImageOf[np.ndarray]:
    """Hands its input straight back: the same object, not a copy."""
    return image


@op()
def broken(image: ImageOf[np.ndarray]) -> ImageOf[np.ndarray]:
    """Always fails."""
    raise RuntimeError('broken on purpose')


@op()
def blur_then_threshold(
    image: ImageOf[np.ndarray], sigma: float = 1.0
) -> LabelsOf[np.ndarray]:
    """A workflow: it calls two ops through the ambient runner."""
    blurred = skop.run(blur, {'image': image, 'sigma': sigma})
    return skop.run(threshold, {'image': blurred, 'level': 1.0})


@op()
def split_workflow(image: ImageOf[np.ndarray]) -> Split:
    """A workflow with two outputs, made by a nested op."""
    return skop.run(split, {'image': image})


class Mode(Enum):
    fast = 'fast'
    slow = 'slow'


#: What ``configured`` was last called with.
last_call: dict = {}


@op()
def configured(
    image: ImageOf[np.ndarray], mode: Mode = Mode.fast, model: Path = Path('m')
) -> ImageOf[np.ndarray]:
    """An enum and a path: neither is JSON until it is recorded."""
    last_call.update(mode=mode, model=model)
    return np.asarray(image, dtype=float)


@op()
def plane(
    image: Annotated[ImageOf[np.ndarray], Axes('y', 'x')],
) -> ImageOf[np.ndarray]:
    """A strictly 2-D op, so a stack has to be planned onto it."""
    assert np.ndim(image) == 2
    return np.asarray(image, dtype=float) + 1


ALL = (
    blur,
    threshold,
    add,
    split,
    count,
    total,
    scale_into,
    masked,
    same,
    broken,
    blur_then_threshold,
    split_workflow,
    configured,
    plane,
)

#: Every op above by its ID, as a host's registry holds them.
REGISTRY = {skop.OpSpec.from_op(fn).name: fn for fn in ALL}


def op_id(fn) -> str:
    return skop.OpSpec.from_op(fn).name

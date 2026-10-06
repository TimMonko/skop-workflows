"""Ops, numpy only, so the demo needs no environment built.

They are declared exactly the way scikit-ops asks -- the contract this repo
tracks (decision 44) -- and stand in for the real scikit-ops ops the demo will
use one day. Each one declares what its data *means* and what type each
parameter is, so a host reads the op instead of being told about it.

``@op()`` with no environment is a *workflow*: it runs wherever the caller is.
``sharpen`` names one instead, so the demo can show what an op that is not a
workflow looks like to the recorder; nothing here builds that environment.
"""

from __future__ import annotations

import numpy as np
from skop import op
from skop.types import ImageOf, LabelsOf


@op()
def percentile(
    image: ImageOf[np.ndarray], low: float = 1.0, high: float = 99.8
) -> ImageOf[np.ndarray]:
    """Rescale so that two percentiles land on 0 and 1."""
    if image.ndim != 2:
        raise ValueError(
            f'percentile takes a 2-D image, got {image.ndim} axes'
        )
    lo, hi = np.percentile(image, [low, high])
    span = hi - lo or 1.0
    return np.clip((image - lo) / span, 0.0, 1.0)


@op()
def gaussian(
    image: ImageOf[np.ndarray], sigma: float = 2.0
) -> ImageOf[np.ndarray]:
    """Blur with a Gaussian kernel, one axis at a time."""
    if sigma <= 0:
        raise ValueError(f'sigma must be positive, got {sigma}')
    kernel = _kernel(sigma)
    out = image.astype(float)
    for axis in range(out.ndim):
        out = _convolve(out, kernel, axis)
    return out


@op()
def otsu(
    image: ImageOf[np.ndarray], invert: bool = False
) -> LabelsOf[np.ndarray]:
    """Keep what lies above Otsu's threshold."""
    flat = np.asarray(image, dtype=float).ravel()
    counts, edges = np.histogram(flat, bins=256)
    centres = (edges[:-1] + edges[1:]) / 2
    weights = np.cumsum(counts)
    total = weights[-1]
    means = np.cumsum(counts * centres)
    best, threshold = -1.0, centres[0]
    for i in range(len(counts) - 1):
        below, above = weights[i], total - weights[i]
        if below == 0 or above == 0:
            continue
        between = (means[i] / below - (means[-1] - means[i]) / above) ** 2
        if between * below * above > best:
            best, threshold = between * below * above, centres[i]
    mask = flat.reshape(np.shape(image))
    return mask <= threshold if invert else mask > threshold


@op()
def connect(labels: LabelsOf[np.ndarray]) -> LabelsOf[np.ndarray]:
    """Number the connected components of a mask, four-connected."""
    mask = np.asarray(labels, dtype=bool)
    out = np.zeros(mask.shape, dtype=np.int32)
    rows, cols = mask.shape
    count = 0
    for row in range(rows):
        for col in range(cols):
            if not mask[row, col] or out[row, col]:
                continue
            count += 1
            stack = [(row, col)]
            while stack:
                y, x = stack.pop()
                if not (0 <= y < rows and 0 <= x < cols):
                    continue
                if not mask[y, x] or out[y, x]:
                    continue
                out[y, x] = count
                stack.append((y - 1, x))
                stack.append((y + 1, x))
                stack.append((y, x - 1))
                stack.append((y, x + 1))
    return out


@op(env='demo')
def sharpen(image: ImageOf[np.ndarray]) -> ImageOf[np.ndarray]:
    """A stand-in for an op that names an environment, not a workflow.

    The recorder reads its spec exactly as it reads any other op's; what
    differs is that ``OpSpec.env`` is set, so a host knows the op belongs in
    scikit-ops' ``envs/demo/`` rather than wherever the caller is. Nothing in
    this repo builds that environment -- the real ones live in scikit-ops --
    so this op exists only so the demo can show the spec's own account of the
    difference (decision 44).
    """
    return image + (image - gaussian(image, sigma=1.0))


def _kernel(sigma: float) -> np.ndarray:
    radius = max(1, int(round(3 * sigma)))
    offsets = np.arange(-radius, radius + 1, dtype=float)
    kernel = np.exp(-(offsets**2) / (2 * sigma * sigma))
    return kernel / kernel.sum()


def _convolve(array: np.ndarray, kernel: np.ndarray, axis: int) -> np.ndarray:
    moved = np.moveaxis(array, axis, -1)
    pad = len(kernel) // 2
    padded = np.pad(
        moved, [(0, 0)] * (moved.ndim - 1) + [(pad, pad)], mode='edge'
    )
    out = np.zeros_like(moved)
    for index, weight in enumerate(kernel):
        out += weight * padded[..., index : index + moved.shape[-1]]
    return np.moveaxis(out, -1, axis)

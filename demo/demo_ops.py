"""Three ops, numpy only, so the demo needs no environment built.

They stand in for the scikit-ops ops the real demo will use; the shape of a run
is the same either way.
"""

from __future__ import annotations

import numpy as np

from skop_core import op


@op(('image',), array_params=('image',), roles=('image',))
def percentile(
    image: np.ndarray, low: float = 1.0, high: float = 99.8
) -> np.ndarray:
    """Rescale so that two percentiles land on 0 and 1."""
    if image.ndim != 2:
        raise ValueError(
            f'percentile takes a 2-D image, got {image.ndim} axes'
        )
    lo, hi = np.percentile(image, [low, high])
    span = hi - lo or 1.0
    return np.clip((image - lo) / span, 0.0, 1.0)


@op(('image',), array_params=('image',), roles=('image',))
def gaussian(image: np.ndarray, sigma: float = 2.0) -> np.ndarray:
    """Blur with a Gaussian kernel, one axis at a time."""
    if sigma <= 0:
        raise ValueError(f'sigma must be positive, got {sigma}')
    kernel = _kernel(sigma)
    out = image.astype(float)
    for axis in range(out.ndim):
        out = _convolve(out, kernel, axis)
    return out


@op(('image',), array_params=('image',), roles=('labels',))
def otsu(image: np.ndarray, invert: bool = False) -> np.ndarray:
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


@op(('components',), array_params=('labels',), roles=('labels',))
def connect(labels: np.ndarray) -> np.ndarray:
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

"""What a parameter may be, for it to travel in a recipe.

Parameters must be JSON: a recipe holds op IDs and JSON parameters and never a
callable (decision 2), so a run's parameters have to survive a round trip
through a file. This is the whole of what that rule needs, and it lives apart
from the op contract, which is scikit-ops'.
"""

from __future__ import annotations

import os
from enum import Enum
from typing import Any


def to_json(value: Any) -> Any:
    """The value as it will be recorded.

    Containers are rebuilt, and a stand-in scalar -- a numpy scalar, say -- is
    unwrapped through its own ``item()``. An enum member is recorded as its
    value and a path as its string: the op's declared type is what turns them
    back (``Recorder._revive``). Everything else passes through for
    :func:`is_json` to judge. This module stays free of numpy, because the
    contract it belongs to is.
    """
    if isinstance(value, Enum):
        return to_json(value.value)
    if isinstance(value, os.PathLike):
        return os.fspath(value)
    if isinstance(value, (bool, int, float, str)) or value is None:
        return value
    if isinstance(value, (list, tuple)):
        return [to_json(item) for item in value]
    if isinstance(value, dict):
        return {key: to_json(item) for key, item in value.items()}
    item = getattr(value, 'item', None)
    if callable(item):
        try:
            return to_json(item())
        except (TypeError, ValueError):
            return value
    return value


def is_json(value: Any) -> bool:
    """Whether a value can live in a recipe: JSON scalars and containers."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return True
    if isinstance(value, (list, tuple)):
        return all(is_json(item) for item in value)
    if isinstance(value, dict):
        return all(
            isinstance(key, str) and is_json(item)
            for key, item in value.items()
        )
    return False

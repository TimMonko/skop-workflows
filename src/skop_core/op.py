"""The small contract an op must satisfy to be recorded.

This stands in for `opspec.OpSpec` until opspec is settled; the fields here are
the ones opspec already has (id, env, outputs, params).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Output:
    """One output of an op, as the graph names it."""

    name: str
    role: str | None = None


@dataclass(frozen=True)
class OpInfo:
    """An op's public shape, enough to record a run and to replay it."""

    id: str
    env: str | None
    outputs: tuple[Output, ...]
    array_params: tuple[str, ...]

    @property
    def is_workflow(self) -> bool:
        """An op with no environment runs on the host, calling other ops."""
        return self.env is None


def op(
    outputs: tuple[str, ...] = ('image',),
    *,
    env: str | None = None,
    array_params: tuple[str, ...] = ('image',),
    roles: tuple[str | None, ...] = (),
) -> Callable:
    """Declare a function as an op. Sets an attribute and returns the function."""

    def decorate(fn: Callable) -> Callable:
        fn.__skop_op__ = OpInfo(  # pyrefly: ignore [missing-attribute]
            id=f'{fn.__module__}:{fn.__name__}',
            env=env,
            outputs=tuple(
                Output(name, role)
                for name, role in zip(
                    outputs, roles or (None,) * len(outputs), strict=True
                )
            ),
            array_params=array_params,
        )
        return fn

    return decorate


def info(fn: Callable) -> OpInfo:
    """The op contract attached to a function."""
    found = getattr(fn, '__skop_op__', None)
    if not isinstance(found, OpInfo):
        raise TypeError(f'{fn!r} is not an op; decorate it with @op')
    return found


def to_json(value: Any) -> Any:
    """The value as it will be recorded.

    Containers are rebuilt, and a stand-in scalar -- a numpy scalar, say -- is
    unwrapped through its own ``item()``. Everything else passes through for
    :func:`is_json` to judge. This module stays free of numpy, because it
    mirrors the stdlib-only spec it is meant to be proposed back to.
    """
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

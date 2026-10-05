"""The small contract an op must satisfy to be recorded.

This stands in for `opspec.OpSpec` until opspec is settled; the fields here are
the ones opspec already has (id, env, outputs, params) plus the ones it does
not (cost), so the difference is visible rather than assumed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

#: How expensive one run is, which decides whether a stale step updates itself.
CHEAP = "cheap"
EXPENSIVE = "expensive"


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
    cost: str = CHEAP

    @property
    def is_workflow(self) -> bool:
        """An op with no environment runs on the host, calling other ops."""
        return self.env is None


def op(
    outputs: tuple[str, ...] = ("image",),
    *,
    env: str | None = None,
    array_params: tuple[str, ...] = ("image",),
    cost: str = CHEAP,
    roles: tuple[str | None, ...] = (),
) -> Callable:
    """Declare a function as an op. Sets an attribute and returns the function."""

    def decorate(fn: Callable) -> Callable:
        fn.__skop_op__ = OpInfo(
            id=f"{fn.__module__}:{fn.__name__}",
            env=env,
            outputs=tuple(
                Output(name, role)
                for name, role in zip(outputs, roles or (None,) * len(outputs))
            ),
            array_params=array_params,
            cost=cost,
        )
        return fn

    return decorate


def info(fn: Callable) -> OpInfo:
    """The op contract attached to a function."""
    found = getattr(fn, "__skop_op__", None)
    if not isinstance(found, OpInfo):
        raise TypeError(f"{fn!r} is not an op; decorate it with @op")
    return found


def is_json(value: Any) -> bool:
    """Whether a parameter value can live in a recipe unchanged."""
    return value is None or isinstance(value, (bool, int, float, str))

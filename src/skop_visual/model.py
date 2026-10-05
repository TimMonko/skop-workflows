"""The workflow graph as data a renderer can draw.

One model, however it is shown: steps become nodes, the current run's inputs
become edges, and every node carries its sibling runs and their metadata.
Nothing here draws, and nothing here parses a handle: a root's name comes
from the store's own description when a store is given.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from skop_core import Graph, Run, Store

#: The badge a node wears when nothing is wrong.
FRESH = 'fresh'
#: The other badges, in the order in which they outrank each other.
STALE = 'stale'
AFFECTED = 'affected'
EDITED = 'edited'
FAILED = 'failed'


@dataclass(frozen=True)
class Edge:
    """One input: its parameter name, and where the data came from."""

    param: str
    #: The producing step, or None when the data is a root.
    source: str | None
    #: The step this edge feeds.
    target: str
    #: The root's name, when a store could describe the handle.
    root: str | None = None


@dataclass(frozen=True)
class RunInfo:
    """One recorded run, as a detail panel shows it."""

    id: str
    status: str
    current: bool
    params: dict[str, Any]
    inputs: tuple[Edge, ...]
    outputs: dict[str, str]
    error: str | None = None


@dataclass(frozen=True)
class Node:
    """One step: its badge, its flags, and its runs newest first."""

    step: str
    op: str
    badge: str
    flags: tuple[str, ...]
    runs: tuple[RunInfo, ...]


@dataclass(frozen=True)
class GraphView:
    """The whole picture: nodes, current-run edges, and the targets cut for."""

    nodes: tuple[Node, ...]
    edges: tuple[Edge, ...]
    targets: tuple[str, ...]


def view(
    graph: Graph,
    store: Store | None = None,
    targets: list[str] | None = None,
) -> GraphView:
    """The graph as renderer-ready data.

    With targets, only their closure is shown — the same rule export uses.
    """
    steps = graph.closure(list(targets)) if targets else graph.steps()
    names: dict[str, str] = {}

    def root_name(handle: str) -> str | None:
        if store is None:
            return None
        if handle not in names:
            names[handle] = store.describe(handle)['name']
        return names[handle]

    def edges_of(run: Run) -> tuple[Edge, ...]:
        found = []
        for param, handle in run.inputs.items():
            producer = graph.producer(handle)
            source = producer.step if producer is not None else None
            found.append(
                Edge(
                    param=param,
                    source=source,
                    target=run.step,
                    root=None if source is not None else root_name(handle),
                )
            )
        return tuple(found)

    nodes = []
    edges = []
    for step in steps:
        runs = graph.runs_of(step)
        current = graph.current(step)
        flags = []
        if current is None or runs[-1].status != 'ok':
            flags.append(FAILED)
        if graph.is_edited(step):
            flags.append(EDITED)
        if graph.is_affected(step):
            flags.append(AFFECTED)
        if graph.is_stale(step):
            flags.append(STALE)
        nodes.append(
            Node(
                step=step,
                op=runs[-1].op,
                badge=flags[0] if flags else FRESH,
                flags=tuple(flags),
                runs=tuple(
                    RunInfo(
                        id=run.id,
                        status=run.status,
                        current=run is current,
                        params=dict(run.params),
                        inputs=edges_of(run),
                        outputs=dict(run.outputs),
                        error=run.error,
                    )
                    for run in reversed(runs)
                ),
            )
        )
        if current is not None:
            edges.extend(edges_of(current))
    return GraphView(
        nodes=tuple(nodes), edges=tuple(edges), targets=tuple(targets or ())
    )

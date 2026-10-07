"""The workflow graph as data a renderer can draw.

One model, however it is shown: steps become nodes, the current run's inputs
become edges, and every node carries its sibling runs and their metadata.
Nothing here draws, and nothing here parses a handle: every name comes from
the log.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from skop_core import Graph, Run

#: The badge a node wears when nothing is wrong.
FRESH = 'fresh'
#: The other badges, in the order in which they outrank each other.
STALE = 'stale'
AFFECTED = 'affected'
EDITED = 'edited'
FAILED = 'failed'
#: The newest run was cancelled: what it handed back is kept, not used.
CANCELLED = 'cancelled'
#: A step whose input's layer has gone. It is not stale -- there is nothing
#: newer to catch up with -- so it ranks below the badges that ask for action.
MISSING = 'missing'
#: A step whose hand edit was kept: its output is the user's pixels, and a
#: recipe asks for them as a root. Nothing to do about it, so it ranks last.
KEPT = 'kept'

#: A quick visual signal per badge, for graph labels and panels.
SIGNALS = {
    FRESH: '✅ fresh',
    STALE: '⏳ stale',
    AFFECTED: '⚠️ affected',
    EDITED: '✏️ edited',
    FAILED: '❌ failed',
    CANCELLED: '⏹️ cancelled',
    MISSING: '🕳️ input gone',
    KEPT: '📌 kept edit',
}

#: A fill and a stroke per badge, so every renderer agrees on what a badge
#: looks like. The Mermaid flowchart and the napari widget both take these.
COLOURS = {
    FRESH: ('#e6f4ea', '#137333'),
    STALE: ('#fef7e0', '#b06000'),
    AFFECTED: ('#f3e8fd', '#8430ce'),
    EDITED: ('#fce8e6', '#a50e0e'),
    FAILED: ('#f1f3f4', '#5f6368'),
    CANCELLED: ('#f1f3f4', '#5f6368'),
    MISSING: ('#e3e8ef', '#475569'),
    KEPT: ('#e0f2f1', '#00695c'),
}

#: A root is not a badge -- it never fails and never goes stale -- so it keeps
#: a colour of its own.
ROOT_COLOURS = ('#e8f0fe', '#1967d2')


@dataclass(frozen=True)
class Edge:
    """One input: its parameter name, and where the data came from."""

    param: str
    #: The producing step, or None when the data is a root.
    source: str | None
    #: The step this edge feeds.
    target: str
    #: The store's handle for the data, for a host that wants to load it.
    handle: str | None = None
    #: The root's name, when the data is a root.
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
    #: The roots the current run read whose layer has gone.
    missing: tuple[str, ...] = ()

    @property
    def current(self) -> RunInfo | None:
        """The run the step stands on, or None when every run failed."""
        return next((run for run in self.runs if run.current), None)


@dataclass(frozen=True)
class GraphView:
    """The whole picture: nodes, current-run edges, and the targets cut for."""

    nodes: tuple[Node, ...]
    edges: tuple[Edge, ...]
    targets: tuple[str, ...]
    #: Roots whose layer has gone, by name.
    gone: tuple[str, ...] = ()


def view(graph: Graph, targets: list[str] | None = None) -> GraphView:
    """The graph as renderer-ready data.

    With targets, only their closure is shown — the same rule export uses.
    """
    steps = graph.closure(list(targets)) if targets else graph.steps()

    def edges_of(run: Run) -> tuple[Edge, ...]:
        found = []
        for param, handle in run.inputs.items():
            origin = graph.origin(handle)
            root = graph.root_of(handle)
            found.append(
                Edge(
                    param=param,
                    source=origin[0] if origin is not None else None,
                    target=run.step,
                    handle=handle,
                    root=root.name if root is not None else None,
                )
            )
        return tuple(found)

    nodes = []
    edges = []
    for step in steps:
        runs = graph.runs_of(step)
        current = graph.current(step)
        flags = []
        if runs[-1].status == 'cancelled':
            flags.append(CANCELLED)
        elif current is None or runs[-1].status != 'ok':
            flags.append(FAILED)
        if graph.is_edited(step):
            flags.append(EDITED)
        if graph.is_affected(step):
            flags.append(AFFECTED)
        if graph.is_stale(step):
            flags.append(STALE)
        missing = graph.missing_inputs(step)
        if missing:
            flags.append(MISSING)
        if graph.is_accepted(step):
            flags.append(KEPT)
        nodes.append(
            Node(
                step=step,
                op=runs[-1].op,
                badge=flags[0] if flags else FRESH,
                flags=tuple(flags),
                missing=tuple(missing),
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
        nodes=tuple(nodes),
        edges=tuple(edges),
        targets=tuple(targets or ()),
        gone=tuple(sorted(graph.gone)),
    )


@dataclass(frozen=True)
class Lineage:
    """What a step comes from and what comes from it.

    The path a result took, for a reader who points at one node and asks.
    """

    step: str
    #: Every step it was made from, oldest first.
    upstream: tuple[str, ...]
    #: The roots under those steps and this one.
    roots: tuple[str, ...]
    #: Every step that reads it, directly or not.
    downstream: tuple[str, ...]

    def touches(self, key: str) -> bool:
        """Whether a node key (see :func:`layout`) is on the path."""
        return (
            key == self.step
            or key in self.upstream
            or key in self.downstream
            or (
                key.startswith(ROOT_PREFIX)
                and key[len(ROOT_PREFIX) :] in self.roots
            )
        )


def lineage(graph: Graph, step: str) -> Lineage:
    """The path through the graph that a step sits on."""
    steps, roots = graph.upstream(step)
    return Lineage(
        step=step,
        upstream=tuple(steps),
        roots=tuple(roots),
        downstream=tuple(graph.downstream(step)),
    )


#: A root's node key is its name behind this, so it cannot be mistaken for a
#: step that happens to share the name -- and one often does: a layer called
#: 'smoothed' is a root, and so is the step that made it.
ROOT_PREFIX = 'root:'


@dataclass(frozen=True)
class Placed:
    """One node of the drawn graph, and where it goes on the grid."""

    key: str
    label: str
    #: 'root' or 'step'.
    kind: str
    #: A step's badge; a root has none.
    badge: str | None
    #: Left to right: roots in column 0, then each step one past its latest
    #: source, so every edge runs rightwards.
    col: int
    #: Top to bottom within the column.
    row: int


@dataclass(frozen=True)
class Layout:
    """The graph as a grid a renderer can draw without thinking."""

    nodes: tuple[Placed, ...]
    #: ``(source key, target key, parameter)``.
    edges: tuple[tuple[str, str, str], ...]
    columns: int
    rows: int

    def node(self, key: str) -> Placed:
        return next(n for n in self.nodes if n.key == key)


def layout(view: GraphView) -> Layout:
    """Place a view's steps and roots on a left-to-right grid.

    The column is the longest path from a root, so a step is always to the
    right of everything it reads. Within a column, a node sits near what feeds
    it, which keeps most edges short and uncrossed without any search: this is
    a handful of steps, not a circuit. Rendering is the caller's, which is why
    this is plain numbers and no Qt.
    """
    steps = {node.step: node for node in view.nodes}
    edges: list[tuple[str, str, str]] = []
    roots: list[str] = []
    for edge in view.edges:
        if edge.target not in steps:
            continue
        if edge.source is None:
            name = edge.root or edge.param
            if name not in roots:
                roots.append(name)
            source = ROOT_PREFIX + name
        elif edge.source in steps:
            source = edge.source
        else:
            continue
        edges.append((source, edge.target, edge.param))

    column: dict[str, int] = {ROOT_PREFIX + name: 0 for name in roots}
    pending = [node.step for node in view.nodes]
    # Depth is found by relaxing until nothing moves. The graph is acyclic, so
    # this stops within as many passes as there are steps.
    for _ in range(len(pending) + 1):
        moved = False
        for step in pending:
            sources = [
                column.get(src, 0) for src, dst, _ in edges if dst == step
            ]
            depth = 1 + max(sources, default=0)
            if column.get(step) != depth:
                column[step] = depth
                moved = True
        if not moved:
            break

    by_column: dict[int, list[str]] = {}
    for key in [ROOT_PREFIX + name for name in roots] + pending:
        by_column.setdefault(column[key], []).append(key)

    row: dict[str, int] = {}
    for col in sorted(by_column):
        keys = by_column[col]

        def pull(key: str) -> float:
            fed = [
                row[src] for src, dst, _ in edges if dst == key and src in row
            ]
            return sum(fed) / len(fed) if fed else float('inf')

        # sorted() is stable, so nodes with no one feeding them keep the order
        # the log gave them.
        for index, key in enumerate(sorted(keys, key=pull) if col else keys):
            row[key] = index

    placed = []
    for key, col in column.items():
        if key.startswith(ROOT_PREFIX):
            placed.append(
                Placed(
                    key, key[len(ROOT_PREFIX) :], 'root', None, col, row[key]
                )
            )
        else:
            node = steps[key]
            placed.append(Placed(key, key, 'step', node.badge, col, row[key]))
    placed.sort(key=lambda n: (n.col, n.row))
    return Layout(
        nodes=tuple(placed),
        edges=tuple(edges),
        columns=1 + max((n.col for n in placed), default=0),
        rows=1 + max((n.row for n in placed), default=0),
    )

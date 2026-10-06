"""The graph, derived from the run records.

Nothing here is stored: which run is current, whether a step is stale, whether
it was edited, and what a set of targets needs are all read off the log.
"""

from __future__ import annotations

from .record import EDITED, Detached, Event, Handle, Root, Run


class Graph:
    """The steps a log describes, and the questions a host asks about them."""

    def __init__(self, records: list[Run | Root | Detached | Event]) -> None:
        self.runs = [r for r in records if isinstance(r, Run)]
        self.roots = [r for r in records if isinstance(r, Root)]
        self.events = [e for e in records if isinstance(e, Event)]
        #: The roots whose newest record says they went away. Read in log
        #: order, so declaring a name again after it was detached undoes it.
        self.gone: set[str] = set()
        for record in records:
            if isinstance(record, Detached):
                self.gone.add(record.name)
            elif isinstance(record, Root):
                self.gone.discard(record.name)
        self.by_step: dict[str, list[Run]] = {}
        for run in self.runs:
            self.by_step.setdefault(run.step, []).append(run)
        self._producer: dict[Handle, Run] = {}
        for run in self.runs:
            for handle in run.outputs.values():
                self._producer[handle] = run
        #: Every version of a root, oldest first, by name.
        self._root_versions: dict[str, list[Root]] = {}
        #: Which root a handle was recorded as, so no handle needs parsing.
        self._root_of: dict[Handle, Root] = {}
        for root in self.roots:
            self._root_versions.setdefault(root.name, []).append(root)
            self._root_of[root.handle] = root

    # -- steps -----------------------------------------------------------

    def steps(self, nested: bool = False) -> list[str]:
        """The steps the log describes, in the order they first ran.

        A step only ever run from inside a workflow is that workflow's detail
        rather than a step of its own, and is left out unless asked for.
        """
        return [
            step
            for step, runs in self.by_step.items()
            if nested or any(run.parent is None for run in runs)
        ]

    def children_of(self, run: Run) -> list[Run]:
        """The runs a workflow's run made, in the order they happened."""
        return [r for r in self.runs if r.parent == run.id]

    def runs_of(self, step: str) -> list[Run]:
        return list(self.by_step.get(step, ()))

    def current(self, step: str) -> Run | None:
        """The newest successful run; a failed run never becomes current."""
        succeeded = [r for r in self.runs_of(step) if r.status == 'ok']
        return succeeded[-1] if succeeded else None

    def producer(self, handle: Handle) -> Run | None:
        """The run that produced a handle, or None if it is a root."""
        return self._producer.get(handle)

    def root_of(self, handle: Handle) -> Root | None:
        """The root a handle was recorded as, or None if a step made it."""
        return self._root_of.get(handle)

    def roots_of(self, name: str) -> list[Root]:
        return list(self._root_versions.get(name, ()))

    def current_root(self, name: str) -> Root | None:
        """The newest version stored under a name, or None if never stored."""
        found = self._root_versions.get(name)
        return found[-1] if found else None

    def edge(self, run: Run, param: str) -> str | None:
        """The step a parameter comes from, or None if it is a root."""
        produced = self.producer(run.inputs[param])
        return produced.step if produced else None

    # -- derived flags ---------------------------------------------------

    def is_stale(self, step: str) -> bool:
        run = self.current(step)
        if run is None:
            return False
        for handle in run.inputs.values():
            upstream = self.producer(handle)
            if upstream is not None:
                if self.current(upstream.step) is not upstream:
                    return True
                continue
            # A root has no producer, but it can still move: a newer version
            # stored under the same name supersedes the one read here.
            root = self._root_of.get(handle)
            if root is not None and self.current_root(root.name) is not root:
                return True
        return False

    def missing_inputs(self, step: str) -> list[str]:
        """The roots the step read whose layer has since gone.

        Not staleness: nothing newer exists to bring the step up to date with,
        and the data it read is still in the store. What is lost is where the
        data came from, so the step can be read but no longer reproduced from
        the session it was made in.
        """
        run = self.current(step)
        if run is None:
            return []
        found = []
        for handle in run.inputs.values():
            root = self._root_of.get(handle)
            if root is not None and root.name in self.gone:
                found.append(root.name)
        return sorted(set(found))

    def is_edited(self, step: str) -> bool:
        run = self.current(step)
        if run is None:
            return False
        marks = [e for e in self.events if e.run == run.id]
        return bool(marks) and marks[-1].kind == EDITED

    def is_affected(self, step: str) -> bool:
        """Whether an edited step feeds this one, directly or not."""
        return any(
            other != step and self.is_edited(other)
            for other in self.closure([step])[:-1]
        )

    # -- selection -------------------------------------------------------

    def closure(self, targets: list[str]) -> list[str]:
        """The steps producing the targets, oldest first, and nothing else."""
        order: list[str] = []
        seen: set[str] = set()

        def visit(step: str) -> None:
            if step in seen or step not in self.by_step:
                return
            seen.add(step)
            run = self.current(step)
            if run is None:
                # A step whose every run failed produces nothing, so nothing
                # downstream can be built from it either.
                return
            for handle in run.inputs.values():
                upstream = self.producer(handle)
                if upstream is not None:
                    visit(upstream.step)
            order.append(step)

        for target in targets:
            visit(target)
        return order

    def upstream(self, step: str) -> tuple[list[str], list[str]]:
        """Everything a step comes from: its steps, and the roots under them.

        Both oldest first, and neither includes the step itself. This is the
        path a result took, which is what a reader asks for when they point
        at one and want to know where it came from.
        """
        steps = [s for s in self.closure([step]) if s != step]
        roots: list[str] = []
        for name in [*steps, step]:
            run = self.current(name)
            if run is None:
                continue
            for handle in run.inputs.values():
                root = self._root_of.get(handle)
                if root is not None and root.name not in roots:
                    roots.append(root.name)
        return steps, roots

    def downstream(self, step: str) -> list[str]:
        """Every step that reads this one, directly or not."""
        found: list[str] = []
        for other in self.steps():
            if other != step and step in self.closure([other])[:-1]:
                found.append(other)
        return found

    def leaves(self) -> list[str]:
        """Steps no current run consumes: the default targets."""
        consumed = set()
        for step in self.steps():
            run = self.current(step)
            if run is None:
                continue
            for handle in run.inputs.values():
                upstream = self.producer(handle)
                if upstream is not None:
                    consumed.add(upstream.step)
        return [
            s for s in self.steps() if s not in consumed and self.current(s)
        ]

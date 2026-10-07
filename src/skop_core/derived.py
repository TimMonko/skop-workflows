"""The graph, derived from the run records.

Nothing here is stored: which run is current, whether a step is stale, whether
it was edited, and what a set of targets needs are all read off the log.

One question underlies most of the others: *where is the data a handle stood
for now?* (:meth:`Graph.now`). A root's data is wherever its newest version
is; a step's output is in the step's current run, or in the pixels a user
kept in its place. A run whose inputs are not where they are now is stale,
and bringing it up to date means reading them from there.
"""

from __future__ import annotations

from .record import (
    ACCEPTED,
    EDITED,
    OK,
    Detached,
    Event,
    Handle,
    Record,
    Root,
    Run,
)


class Graph:
    """The steps a log describes, and the questions a host asks about them.

    A snapshot: built from the records it is given, and not updated after.
    Ask the recorder for a new one once the log has grown.
    """

    def __init__(self, records: list[Record]) -> None:
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
        self._current: dict[str, Run | None] = {}
        for step, runs in self.by_step.items():
            succeeded = [r for r in runs if r.status == OK]
            self._current[step] = succeeded[-1] if succeeded else None
        self._producer: dict[Handle, tuple[Run, str]] = {}
        for run in self.runs:
            for output, handle in run.outputs.items():
                self._producer[handle] = (run, output)
        #: Every version of a root, oldest first, by name.
        self._root_versions: dict[str, list[Root]] = {}
        #: Which root a handle was recorded as, so no handle needs parsing.
        self._root_of: dict[Handle, Root] = {}
        for root in self.roots:
            self._root_versions.setdefault(root.name, []).append(root)
            self._root_of[root.handle] = root
        #: The marks on each run, in log order.
        self._marks: dict[str, list[Event]] = {}
        for event in self.events:
            self._marks.setdefault(event.run, []).append(event)
        #: Pixels kept in place of a step's output: (step, output) -> handle,
        #: while the current run's latest mark is a keep. Keeps in a row add
        #: up, one output each, so a step with several outputs can keep each.
        self._kept: dict[tuple[str, str], Handle] = {}
        #: Every set of pixels ever kept, by the (step, output) it stood in
        #: for -- kept now or not -- so a run that read them knows where its
        #: data went after a revert or a new run.
        self._kept_as: dict[Handle, tuple[str, str]] = {}
        runs_by_id = {run.id: run for run in self.runs}
        for event in self.events:
            run = runs_by_id.get(event.run)
            if event.kind == ACCEPTED and event.handle and run is not None:
                self._kept_as[event.handle] = (
                    run.step,
                    _output_of(event, run),
                )
        for step, run in self._current.items():
            marks = [] if run is None else self._marks.get(run.id, [])
            if run is None or not marks or marks[-1].kind != ACCEPTED:
                continue
            replaced: dict[str, Handle] = {}
            for mark in reversed(marks):
                if mark.kind != ACCEPTED:
                    break
                if mark.handle is not None:
                    replaced.setdefault(_output_of(mark, run), mark.handle)
            for output, handle in run.outputs.items():
                self._kept[(step, output)] = replaced.get(output, handle)

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
        return self._current.get(step)

    def producer(self, handle: Handle) -> Run | None:
        """The run that produced a handle, or None if it is a root."""
        found = self._producer.get(handle)
        return found[0] if found is not None else None

    def root_of(self, handle: Handle) -> Root | None:
        """The root a handle was recorded as, or None if a step made it."""
        return self._root_of.get(handle)

    def roots_of(self, name: str) -> list[Root]:
        return list(self._root_versions.get(name, ()))

    def current_root(self, name: str) -> Root | None:
        """The newest version stored under a name, or None if never stored."""
        found = self._root_versions.get(name)
        return found[-1] if found else None

    def origin(self, handle: Handle) -> tuple[str, str] | None:
        """The (step, output) a handle is the data of, or None for a root.

        Kept pixels are the data of the step they were kept in place of.
        """
        if handle in self._kept_as:
            return self._kept_as[handle]
        found = self._producer.get(handle)
        if found is None:
            return None
        run, output = found
        return run.step, output

    def now(self, handle: Handle) -> Handle | None:
        """Where the data a handle stood for is now.

        A root's newest version; a step output's current run, or the pixels
        kept in its place. The handle itself when nothing has moved, and None
        when the step no longer makes that output at all.
        """
        root = self._root_of.get(handle)
        if root is not None:
            newest = self.current_root(root.name)
            return newest.handle if newest is not None else handle
        origin = self.origin(handle)
        if origin is None:
            return handle
        return self.latest(*origin)

    def latest(self, step: str, output: str) -> Handle | None:
        """The handle a step's output is now: kept pixels, else the run's."""
        if (step, output) in self._kept:
            return self._kept[(step, output)]
        run = self.current(step)
        return None if run is None else run.outputs.get(output)

    def source_of(self, handle: Handle) -> str | None:
        """Where a handle came from: a root's name, or the step that made it.

        A root's name carries the prefix ``root:``, so it can never be taken
        for a step that happens to share it.
        """
        root = self._root_of.get(handle)
        if root is not None:
            return f'root:{root.name}'
        origin = self.origin(handle)
        return origin[0] if origin is not None else None

    def sources_of(self, run: Run) -> dict[str, str]:
        """Where each input of a run came from, by parameter."""
        found = {}
        for param, handle in run.inputs.items():
            source = self.source_of(handle)
            if source is not None:
                found[param] = source
        return found

    def _upstream_steps(self, run: Run) -> list[str]:
        """The steps whose outputs a run read, in parameter order."""
        found = []
        for handle in run.inputs.values():
            origin = self.origin(handle)
            if origin is not None and origin[0] not in found:
                found.append(origin[0])
        return found

    # -- derived flags ---------------------------------------------------

    def is_stale(self, step: str) -> bool:
        """Whether an input the current run read has moved on since.

        A step whose edit was kept is not stale: its output is the user's
        pixels now, and there is nothing to catch up with.
        """
        run = self.current(step)
        if run is None or self.is_accepted(step):
            return False
        return any(self.now(h) != h for h in run.inputs.values())

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
        """Whether the current run's output was changed by hand, unresolved."""
        mark = self._last_mark(self.current(step))
        return mark is not None and mark.kind == EDITED

    def is_accepted(self, step: str) -> bool:
        """Whether a hand edit to the current run's output was kept."""
        mark = self._last_mark(self.current(step))
        return mark is not None and mark.kind == ACCEPTED

    def accepted(self, step: str, output: str | None = None) -> Handle | None:
        """Where a step's kept pixels are, or None when nothing was kept.

        ``output`` may be left out for a step with one output.
        """
        if not self.is_accepted(step):
            return None
        run = self.current(step)
        assert run is not None
        name = output if output is not None else _only(run)
        return self._kept.get((step, name))

    def is_affected(self, step: str) -> bool:
        """Whether an edited step feeds this one, directly or not."""
        return any(
            other != step and self.is_edited(other)
            for other in self.closure([step])[:-1]
        )

    def _last_mark(self, run: Run | None) -> Event | None:
        if run is None:
            return None
        marks = self._marks.get(run.id)
        return marks[-1] if marks else None

    # -- selection -------------------------------------------------------

    def closure(self, targets: list[str]) -> list[str]:
        """The steps producing the targets, oldest first, and nothing else.

        A step whose edit was kept is where a closure stops: its output is
        no longer made from its inputs, so nothing upstream of it is needed.
        """
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
            if not self.is_accepted(step):
                for upstream in self._upstream_steps(run):
                    visit(upstream)
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
            if run is None or (name != step and self.is_accepted(name)):
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
        consumed: set[str] = set()
        for step in self.steps():
            run = self.current(step)
            if run is not None:
                consumed.update(self._upstream_steps(run))
        return [
            s for s in self.steps() if s not in consumed and self.current(s)
        ]


def _only(run: Run) -> str:
    """A run's one output, or a refusal naming the choice it needs."""
    if len(run.outputs) != 1:
        raise ValueError(
            f'{run.step!r} has outputs {sorted(run.outputs)}; say which'
        )
    return next(iter(run.outputs))


def _output_of(mark: Event, run: Run) -> str:
    """Which output a keep replaced: its own note of it, else the only one."""
    return mark.output if mark.output is not None else _only(run)

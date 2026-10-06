"""Runs, the roots they read, and the events that mark them.

The log is append-only: a run is never edited, and an edit to a step's output
is its own record. A root is recorded too, once per version, so that moving an
input under its consumers is visible to everything derived from the log.
Everything else (staleness, which run is current) is derived.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

#: Opaque; issued by the store and parsed only by it.
Handle = str

RUN = 'run'
ROOT = 'root'
EDITED = 'edited'
ACCEPTED = 'accepted'
REVERTED = 'reverted'
DETACHED = 'detached'


@dataclass(frozen=True)
class Run:
    """One invocation of an op, however it was started."""

    id: str
    step: str
    op: str
    inputs: dict[str, Handle] = field(default_factory=dict)
    outputs: dict[str, Handle] = field(default_factory=dict)
    params: dict[str, Any] = field(default_factory=dict)
    status: str = 'ok'
    error: str | None = None
    op_version: str | None = None
    #: The run of the workflow that called this one, when a workflow did. A
    #: workflow's own run is the whole call and its nested runs are what it
    #: did; the graph shows the first and keeps the second as detail.
    parent: str | None = None

    @property
    def kind(self) -> str:
        return RUN

    def to_dict(self) -> dict[str, Any]:
        return {'kind': RUN, **self.__dict__}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Run:
        return cls(**{k: v for k, v in data.items() if k != 'kind'})


@dataclass(frozen=True)
class Root:
    """One named input, as it was stored: a root at one version.

    A root is not a step -- it has no op, and a recipe supplies it at replay --
    but it is recorded, because a step that read it has to be able to go stale
    when the input under it moves.
    """

    id: str
    name: str
    handle: Handle

    @property
    def kind(self) -> str:
        return ROOT

    def to_dict(self) -> dict[str, Any]:
        return {'kind': ROOT, **self.__dict__}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Root:
        return cls(**{k: v for k, v in data.items() if k != 'kind'})


@dataclass(frozen=True)
class Detached:
    """A root that is no longer there: its layer was deleted.

    Nothing about the data is lost -- the store still holds every version --
    but the session can no longer say where the root is *from*, and whoever
    read it should say so. Declaring the name again brings it back, and the
    order of the log is what says which of the two came last.
    """

    id: str
    name: str

    @property
    def kind(self) -> str:
        return DETACHED

    def to_dict(self) -> dict[str, Any]:
        return {'kind': DETACHED, **self.__dict__}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Detached:
        return cls(**{k: v for k, v in data.items() if k != 'kind'})


@dataclass(frozen=True)
class Event:
    """A mark on an existing run: hand-edited, or the edit accepted."""

    id: str
    kind: str
    run: str
    note: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            'id': self.id,
            'kind': self.kind,
            'run': self.run,
            'note': self.note,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Event:
        return cls(
            id=data['id'],
            kind=data['kind'],
            run=data['run'],
            note=data.get('note'),
        )


def from_dict(data: dict[str, Any]) -> Run | Root | Detached | Event:
    if data['kind'] == RUN:
        return Run.from_dict(data)
    if data['kind'] == ROOT:
        return Root.from_dict(data)
    if data['kind'] == DETACHED:
        return Detached.from_dict(data)
    return Event.from_dict(data)

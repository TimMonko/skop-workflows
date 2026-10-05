"""Runs and the events that mark them.

The log is append-only: a run is never edited, and an edit to a step's output is
its own record. Everything else (staleness, which run is current) is derived.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

#: Opaque; issued by the store and parsed only by it.
Handle = str

RUN = 'run'
EDITED = 'edited'
ACCEPTED = 'accepted'


@dataclass(frozen=True)
class Run:
    """One invocation of an op."""

    id: str
    step: str
    op: str
    inputs: dict[str, Handle] = field(default_factory=dict)
    outputs: dict[str, Handle] = field(default_factory=dict)
    params: dict[str, Any] = field(default_factory=dict)
    status: str = 'ok'
    error: str | None = None
    op_version: str | None = None

    @property
    def kind(self) -> str:
        return RUN

    def to_dict(self) -> dict[str, Any]:
        return {'kind': RUN, **self.__dict__}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Run:
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


def from_dict(data: dict[str, Any]) -> Run | Event:
    return (
        Run.from_dict(data) if data['kind'] == RUN else Event.from_dict(data)
    )

"""Canonical simulation event representation."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class Event:
    sequence: int
    possession: int
    action: int
    kind: str
    offense: str
    actor: str | None = None
    target: str | None = None
    zone: str | None = None
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class SimulationResult:
    seed: int
    events: tuple[Event, ...]
    summary: dict[str, Any]

"""Structured AI decision traces, separate from canonical game events."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from courtsim.artifacts import write_jsonl


class TraceError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class TraceOption:
    id: str
    weight: float
    probability: float
    factors: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class DecisionTrace:
    sequence: int
    possession: int
    action: int
    phase: str
    actor: str
    selected: str
    rng_stream: str
    options: tuple[TraceOption, ...]
    data: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        if not self.options:
            raise TraceError("trace must contain at least one option")
        ids = tuple(option.id for option in self.options)
        if len(ids) != len(set(ids)):
            raise TraceError("trace option ids must be unique")
        if self.selected not in ids:
            raise TraceError("selected option is not present in trace options")
        for option in self.options:
            values = (option.weight, option.probability, *option.factors.values())
            if any(not math.isfinite(value) for value in values):
                raise TraceError("trace numeric values must be finite")
            if option.weight < 0 or option.probability < 0:
                raise TraceError("trace weights and probabilities must be non-negative")
        probability_sum = math.fsum(option.probability for option in self.options)
        if not math.isclose(probability_sum, 1.0, rel_tol=1e-9, abs_tol=1e-12):
            raise TraceError("trace probabilities must sum to 1")

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return asdict(self)


def write_traces(path: str | Path, traces: tuple[DecisionTrace, ...]) -> None:
    write_jsonl(Path(path), (trace.to_dict() for trace in traces))

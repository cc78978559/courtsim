"""Interfaces between the engine, runners and persistence layer."""

from __future__ import annotations

from typing import Protocol

from courtsim.events import SimulationResult


class Simulator(Protocol):
    def run(self, seed: int) -> SimulationResult:
        """Run one independent simulation from the supplied seed."""
        ...

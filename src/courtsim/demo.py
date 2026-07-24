"""A deliberately small simulator used only to verify foundation plumbing."""

from __future__ import annotations

from dataclasses import dataclass

from courtsim.config import ScenarioConfig
from courtsim.events import Event, SimulationResult
from courtsim.randomness import RandomStreams


@dataclass(frozen=True, slots=True)
class FoundationDemoSimulator:
    config: ScenarioConfig
    possessions: int = 12

    def run(self, seed: int) -> SimulationResult:
        streams = RandomStreams(seed)
        events: list[Event] = []
        sequence = 0
        team_points = {"home": 0, "away": 0}

        for possession in range(self.possessions):
            offense = "home" if possession % 2 == 0 else "away"
            rng = streams.stream("possession", possession)
            budget = rng.randint(
                self.config.engine.min_action_budget,
                self.config.engine.max_action_budget,
            )
            zone = rng.choice(self.config.zones)
            sequence += 1
            events.append(
                Event(
                    sequence,
                    possession,
                    0,
                    "possession_started",
                    offense,
                    zone=zone,
                    data={"budget": budget},
                )
            )
            for action in range(1, budget + 1):
                sequence += 1
                terminal = action == budget
                kind = "attempt" if terminal else rng.choice(("pass", "reposition"))
                events.append(Event(sequence, possession, action, kind, offense, zone=zone))
            made = rng.random() < 0.45
            points = rng.choice((2, 3)) if made else 0
            team_points[offense] += points
            sequence += 1
            events.append(
                Event(
                    sequence,
                    possession,
                    budget + 1,
                    "possession_ended",
                    offense,
                    zone=zone,
                    data={"made": made, "points": points},
                )
            )

        return SimulationResult(
            seed=seed,
            events=tuple(events),
            summary={"possessions": self.possessions, "score": team_points},
        )

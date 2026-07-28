"""Deterministic scouting uncertainty that keeps true prospect potential hidden."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, fields

from courtsim.career import CareerPlayer, CareerStatus
from courtsim.domain.player import AbilityRatings
from courtsim.randomness import derive_seed

SCOUTING_VERSION = "scouting-v1"


@dataclass(frozen=True, slots=True)
class ScoutingRules:
    base_uncertainty: int = 14
    minimum_uncertainty: int = 3
    uncertainty_reduction_per_exposure: int = 2
    maximum_exposures: int = 5
    version: str = SCOUTING_VERSION

    def __post_init__(self) -> None:
        values = (
            self.base_uncertainty,
            self.minimum_uncertainty,
            self.uncertainty_reduction_per_exposure,
            self.maximum_exposures,
        )
        if any(
            not isinstance(value, int) or isinstance(value, bool) or value < 0 for value in values
        ):
            raise ValueError("scouting rule values must be non-negative integers")
        if self.minimum_uncertainty > self.base_uncertainty:
            raise ValueError("minimum scouting uncertainty cannot exceed the base")
        if self.maximum_exposures < 1:
            raise ValueError("maximum scouting exposures must be positive")
        if self.version != SCOUTING_VERSION:
            raise ValueError("unsupported scouting version")


@dataclass(frozen=True, slots=True)
class ScoutingReport:
    manager_id: str
    team_id: str
    player_id: int
    exposures: int
    uncertainty: int
    confidence: int
    estimated_potential: AbilityRatings
    version: str = SCOUTING_VERSION

    def __post_init__(self) -> None:
        if not self.manager_id.strip() or not self.team_id.strip():
            raise ValueError("scouting manager and team ids must not be blank")
        if self.player_id < 0 or self.exposures < 0 or self.uncertainty < 0:
            raise ValueError("scouting numeric values must be non-negative")
        if not 0 <= self.confidence <= 100:
            raise ValueError("scouting confidence must be from zero through one hundred")
        if self.version != SCOUTING_VERSION:
            raise ValueError("unsupported scouting report version")


def generate_scouting_reports(
    *,
    prospects: Sequence[CareerPlayer],
    scouts: Mapping[str, str],
    master_seed: int,
    exposures: Mapping[tuple[str, int], int] | None = None,
    rules: ScoutingRules | None = None,
) -> tuple[ScoutingReport, ...]:
    active_rules = rules or ScoutingRules()
    if master_seed < 0:
        raise ValueError("scouting master_seed must be non-negative")
    if any(not team_id.strip() or not manager_id.strip() for team_id, manager_id in scouts.items()):
        raise ValueError("scouting identities must not be blank")
    ordered = tuple(sorted(prospects, key=lambda player: player.player_id))
    if any(player.status is not CareerStatus.PROSPECT for player in ordered):
        raise ValueError("scouting reports can only evaluate prospects")
    exposure_map = exposures or {}
    reports: list[ScoutingReport] = []
    for team_id in sorted(scouts):
        for player in ordered:
            exposure_count = exposure_map.get((team_id, player.player_id), 0)
            if not 0 <= exposure_count <= active_rules.maximum_exposures:
                raise ValueError("scouting exposure is outside configured bounds")
            uncertainty = max(
                active_rules.minimum_uncertainty,
                active_rules.base_uncertainty
                - exposure_count * active_rules.uncertainty_reduction_per_exposure,
            )
            estimates = {}
            for item in fields(AbilityRatings):
                truth = int(getattr(player.potential, item.name))
                span = uncertainty * 2 + 1
                noise = (
                    derive_seed(
                        master_seed,
                        active_rules.version,
                        team_id,
                        player.player_id,
                        item.name,
                        exposure_count,
                    )
                    % span
                    - uncertainty
                )
                estimates[item.name] = max(0, min(100, truth + noise))
            reports.append(
                ScoutingReport(
                    scouts[team_id],
                    team_id,
                    player.player_id,
                    exposure_count,
                    uncertainty,
                    max(0, min(100, 100 - uncertainty * 4)),
                    AbilityRatings(**estimates),
                )
            )
    return tuple(reports)


def scouting_reports_to_dict(
    reports: Sequence[ScoutingReport],
) -> list[dict[str, object]]:
    return [
        {
            **{key: value for key, value in asdict(report).items() if key != "estimated_potential"},
            "estimated_potential": asdict(report.estimated_potential),
        }
        for report in reports
    ]

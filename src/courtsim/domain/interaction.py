"""Interaction candidates produced before a finisher and shot zone are selected."""

from dataclasses import dataclass
from math import isfinite

from courtsim.domain.enums import CreationMode, FinisherRoute
from courtsim.domain.plans import (
    LEGAL_ROUTES_BY_PLAY,
    Lineup,
    OffensivePlan,
    PlayerId,
    creation_mode_for,
    expected_fixed_finisher,
    plan_participants,
    validate_lineup,
    validate_plan,
    validate_route,
)


def _require_finite(value: float, field: str) -> None:
    if not isfinite(value):
        raise ValueError(f"{field} must be finite")


@dataclass(frozen=True, slots=True)
class FinisherCandidateProfile:
    route: FinisherRoute
    finisher_id: PlayerId
    availability: float
    primary_contest: float
    help_contest: float
    rim_access: float
    primary_defender_id: PlayerId | None
    help_defender_id: PlayerId | None

    def __post_init__(self) -> None:
        if self.finisher_id < 0:
            raise ValueError("finisher_id must be non-negative")
        for field, value in (
            ("availability", self.availability),
            ("primary_contest", self.primary_contest),
            ("help_contest", self.help_contest),
            ("rim_access", self.rim_access),
        ):
            _require_finite(value, field)
        for field, player_id in (
            ("primary_defender_id", self.primary_defender_id),
            ("help_defender_id", self.help_defender_id),
        ):
            if player_id is not None and player_id < 0:
                raise ValueError(f"{field} must be non-negative")


@dataclass(frozen=True, slots=True)
class InteractionState:
    ball_pressure: float
    pass_release: float
    finisher_candidates: tuple[FinisherCandidateProfile, ...]

    def __post_init__(self) -> None:
        _require_finite(self.ball_pressure, "ball_pressure")
        _require_finite(self.pass_release, "pass_release")
        if not self.finisher_candidates:
            raise ValueError("interaction state needs at least one finisher candidate")
        keys = [(item.route, item.finisher_id) for item in self.finisher_candidates]
        if len(keys) != len(set(keys)):
            raise ValueError("finisher candidates must be unique by (route, finisher_id)")


@dataclass(frozen=True, slots=True)
class FinisherSelection:
    route: FinisherRoute
    finisher_id: PlayerId

    def __post_init__(self) -> None:
        if self.finisher_id < 0:
            raise ValueError("finisher_id must be non-negative")

    @property
    def creation_mode(self) -> CreationMode:
        return creation_mode_for(self.route)


def validate_interaction_state(
    plan: OffensivePlan,
    state: InteractionState,
    offense_lineup: Lineup,
    defense_lineup: Lineup,
) -> None:
    validate_plan(plan, offense_lineup)
    validate_lineup(defense_lineup)
    if set(offense_lineup) & set(defense_lineup):
        raise ValueError("offense and defense lineups must be disjoint")

    candidates_by_route: dict[FinisherRoute, list[FinisherCandidateProfile]] = {}
    for candidate in state.finisher_candidates:
        validate_route(plan, candidate.route)
        if candidate.finisher_id not in offense_lineup:
            raise ValueError("finisher candidate must belong to offense")
        for defender_id in (
            candidate.primary_defender_id,
            candidate.help_defender_id,
        ):
            if defender_id is not None and defender_id not in defense_lineup:
                raise ValueError("candidate defender must belong to defense")
        candidates_by_route.setdefault(candidate.route, []).append(candidate)

    if set(candidates_by_route) != set(LEGAL_ROUTES_BY_PLAY[plan.family]):
        raise ValueError("interaction state must cover every and only legal route")

    for route, candidates in candidates_by_route.items():
        fixed_finisher = expected_fixed_finisher(plan, route)
        if fixed_finisher is not None:
            if len(candidates) != 1 or candidates[0].finisher_id != fixed_finisher:
                raise ValueError(f"{route.name} needs exactly its fixed finisher")
        else:
            participants = set(plan_participants(plan))
            if any(item.finisher_id in participants for item in candidates):
                raise ValueError("help release candidates must be weak-side players")


def select_candidate(
    state: InteractionState, selection: FinisherSelection
) -> FinisherCandidateProfile:
    matches = [
        item
        for item in state.finisher_candidates
        if item.route is selection.route and item.finisher_id == selection.finisher_id
    ]
    if len(matches) != 1:
        raise ValueError("selection must identify exactly one interaction candidate")
    return matches[0]

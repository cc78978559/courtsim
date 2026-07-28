"""White-box annual strategic objectives for manager policy coordination."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from enum import IntEnum
from typing import cast

from courtsim.manager_ai import ManagerProfile

MANAGER_OBJECTIVE_VERSION = "manager-objective-v1"


class ManagerObjective(IntEnum):
    CONTEND = 0
    DEVELOP = 1
    REBUILD = 2
    CAP_RELIEF = 3
    BALANCED = 4


@dataclass(frozen=True, slots=True)
class ManagerObjectiveContext:
    team_id: str
    current_ability: int
    potential: int
    average_age: int
    payroll_bps: int
    future_firsts: int

    def __post_init__(self) -> None:
        if not self.team_id.strip():
            raise ValueError("manager objective team_id must not be blank")
        ratings = (self.current_ability, self.potential)
        if any(not 0 <= value <= 100 for value in ratings):
            raise ValueError("manager objective ratings must be from zero through one hundred")
        if not 18 <= self.average_age <= 50:
            raise ValueError("manager objective average age is invalid")
        if not 0 <= self.payroll_bps <= 30_000 or self.future_firsts < 0:
            raise ValueError("manager objective financial or asset context is invalid")


@dataclass(frozen=True, slots=True)
class ManagerObjectiveScore:
    objective: ManagerObjective
    score: int
    contributions: tuple[tuple[str, int], ...]

    def __post_init__(self) -> None:
        if not isinstance(self.objective, ManagerObjective) or self.score < 0:
            raise ValueError("manager objective score is invalid")
        if not self.contributions or self.score != sum(value for _, value in self.contributions):
            raise ValueError("manager objective contributions must sum to its score")


@dataclass(frozen=True, slots=True)
class ManagerObjectiveDecision:
    team_id: str
    selected: ManagerObjective
    scores: tuple[ManagerObjectiveScore, ...]
    original_profile: ManagerProfile
    effective_profile: ManagerProfile
    version: str = MANAGER_OBJECTIVE_VERSION

    def __post_init__(self) -> None:
        if (
            self.team_id != self.original_profile.team_id
            or self.team_id != self.effective_profile.team_id
        ):
            raise ValueError("manager objective profiles must match the decision team")
        if tuple(item.objective for item in self.scores) != tuple(ManagerObjective):
            raise ValueError("manager objective scores must use canonical order")
        if (
            self.selected
            is not max(
                self.scores,
                key=lambda item: (item.score, -int(item.objective)),
            ).objective
        ):
            raise ValueError("manager objective selection must match its scores")
        if self.version != MANAGER_OBJECTIVE_VERSION:
            raise ValueError("unsupported manager objective version")


def select_manager_objective(
    profile: ManagerProfile,
    context: ManagerObjectiveContext,
) -> ManagerObjectiveDecision:
    if profile.team_id != context.team_id:
        raise ValueError("manager profile and objective context teams must match")
    upside = max(0, context.potential - context.current_ability)
    youth = _bounded((30 - context.average_age) * 8)
    firsts = min(100, context.future_firsts * 20)
    payroll_pressure = _bounded((context.payroll_bps - 9_000) // 50)
    scores = (
        _score(
            ManagerObjective.CONTEND,
            ("current-ability", context.current_ability * 45),
            ("win-now", profile.win_now * 35),
            ("star-preference", profile.star_preference * 20),
        ),
        _score(
            ManagerObjective.DEVELOP,
            ("potential", context.potential * 25),
            ("upside", upside * 30),
            ("development-bias", profile.development_bias * 30),
            ("patience", profile.patience * 15),
        ),
        _score(
            ManagerObjective.REBUILD,
            ("talent-deficit", (100 - context.current_ability) * 32),
            ("upside", upside * 25),
            ("patience", profile.patience * 25),
            ("future-firsts", firsts * 10),
            ("youth", youth * 10),
        ),
        _score(
            ManagerObjective.CAP_RELIEF,
            ("payroll-pressure", payroll_pressure * 45),
            ("cap-discipline", profile.cap_discipline * 35),
            ("risk-restraint", (100 - profile.risk_tolerance) * 20),
        ),
        _score(
            ManagerObjective.BALANCED,
            ("baseline", 3_500),
            ("continuity", profile.continuity * 20),
        ),
    )
    selected = max(scores, key=lambda item: (item.score, -int(item.objective))).objective
    effective = _effective_profile(profile, selected)
    return ManagerObjectiveDecision(
        profile.team_id,
        selected,
        scores,
        profile,
        effective,
    )


def manager_objective_to_dict(
    context: ManagerObjectiveContext,
    decision: ManagerObjectiveDecision,
) -> dict[str, object]:
    return {
        "version": decision.version,
        "team_id": decision.team_id,
        "selected": decision.selected.name.lower().replace("_", "-"),
        "context": asdict(context),
        "scores": [
            {
                "objective": item.objective.name.lower().replace("_", "-"),
                "score": item.score,
                "contributions": dict(item.contributions),
            }
            for item in decision.scores
        ],
        "original_profile": asdict(decision.original_profile),
        "effective_profile": asdict(decision.effective_profile),
    }


def _score(
    objective: ManagerObjective,
    *contributions: tuple[str, int],
) -> ManagerObjectiveScore:
    return ManagerObjectiveScore(
        objective,
        sum(value for _, value in contributions),
        contributions,
    )


def _effective_profile(
    profile: ManagerProfile,
    objective: ManagerObjective,
) -> ManagerProfile:
    adjustments = {
        ManagerObjective.CONTEND: {
            "win_now": 15,
            "patience": -10,
            "development_bias": -10,
            "star_preference": 10,
            "cap_discipline": -5,
        },
        ManagerObjective.DEVELOP: {
            "patience": 10,
            "development_bias": 15,
            "depth_preference": 5,
        },
        ManagerObjective.REBUILD: {
            "win_now": -15,
            "patience": 15,
            "development_bias": 15,
            "star_preference": -5,
        },
        ManagerObjective.CAP_RELIEF: {
            "risk_tolerance": -10,
            "continuity": -10,
            "cap_discipline": 20,
        },
        ManagerObjective.BALANCED: {},
    }[objective]
    return replace(
        profile,
        win_now=_adjusted(profile, adjustments, "win_now"),
        patience=_adjusted(profile, adjustments, "patience"),
        risk_tolerance=_adjusted(profile, adjustments, "risk_tolerance"),
        development_bias=_adjusted(profile, adjustments, "development_bias"),
        star_preference=_adjusted(profile, adjustments, "star_preference"),
        depth_preference=_adjusted(profile, adjustments, "depth_preference"),
        continuity=_adjusted(profile, adjustments, "continuity"),
        cap_discipline=_adjusted(profile, adjustments, "cap_discipline"),
    )


def _adjusted(
    profile: ManagerProfile,
    adjustments: dict[str, int],
    field: str,
) -> int:
    return _bounded(cast(int, getattr(profile, field)) + adjustments.get(field, 0))


def _bounded(value: int) -> int:
    return max(0, min(100, value))

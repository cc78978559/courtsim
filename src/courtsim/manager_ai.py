"""Auditable white-box manager decisions for draft and free agency."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, fields
from enum import IntEnum
from math import isfinite
from typing import cast

from courtsim.career import (
    CareerPlayer,
    CareerStatus,
    DraftPickAsset,
    DraftPlan,
    DraftSelection,
)
from courtsim.domain.player import AbilityRatings, SizeClass
from courtsim.management import (
    ContractRules,
    LeagueManagementState,
    MarketAction,
    MarketActionKind,
    MarketPlan,
)

MANAGER_AI_VERSION = "manager-ai-v1"


class ManagerPolicyMode(IntEnum):
    """Authority granted to a manager policy."""

    SHADOW = 0
    ASSIST = 1
    ACTIVE = 2


@dataclass(frozen=True, slots=True)
class ManagerProfile:
    manager_id: str
    team_id: str
    win_now: int = 50
    patience: int = 50
    risk_tolerance: int = 50
    development_bias: int = 50
    star_preference: int = 50
    depth_preference: int = 50
    continuity: int = 50
    cap_discipline: int = 50
    version: str = MANAGER_AI_VERSION

    def __post_init__(self) -> None:
        if not self.manager_id.strip() or not self.team_id.strip():
            raise ValueError("manager_id and team_id must not be blank")
        ratings = (
            self.win_now,
            self.patience,
            self.risk_tolerance,
            self.development_bias,
            self.star_preference,
            self.depth_preference,
            self.continuity,
            self.cap_discipline,
        )
        if any(
            not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= 100
            for value in ratings
        ):
            raise ValueError("manager ratings must be integers from 0 through 100")
        if self.version != MANAGER_AI_VERSION:
            raise ValueError(f"unsupported manager AI version: {self.version}")


@dataclass(frozen=True, slots=True)
class DecisionContribution:
    contribution_id: str
    group: str
    source: str
    value: float
    reason: str

    def __post_init__(self) -> None:
        if not all(
            value.strip() for value in (self.contribution_id, self.group, self.source, self.reason)
        ):
            raise ValueError("decision contribution text must not be blank")
        if not isfinite(self.value):
            raise ValueError("decision contribution value must be finite")


@dataclass(frozen=True, slots=True)
class ManagerCandidate:
    candidate_id: str
    hard_rejections: tuple[str, ...]
    rational: tuple[DecisionContribution, ...]
    style: tuple[DecisionContribution, ...] = ()

    def __post_init__(self) -> None:
        if not self.candidate_id.strip():
            raise ValueError("manager candidate id must not be blank")
        contribution_ids = tuple(item.contribution_id for item in (*self.rational, *self.style))
        if len(contribution_ids) != len(set(contribution_ids)):
            raise ValueError("manager candidate contribution ids must be unique")


@dataclass(frozen=True, slots=True)
class ManagerCandidateTrace:
    candidate_id: str
    eligible: bool
    reasonable: bool
    hard_rejections: tuple[str, ...]
    rational_score: float | None
    raw_style_score: float | None
    applied_style_score: float | None
    final_score: float | None
    contributions: tuple[DecisionContribution, ...]


@dataclass(frozen=True, slots=True)
class ManagerDecisionTrace:
    decision_id: str
    selected: str | None
    incumbent: str | None
    agrees_with_incumbent: bool | None
    reasonable_band: float
    style_contribution_limit: float
    candidates: tuple[ManagerCandidateTrace, ...]
    version: str = MANAGER_AI_VERSION


@dataclass(frozen=True, slots=True)
class ManagerDecisionRecord:
    sequence: int
    decision_id: str
    stage: str
    manager_id: str
    team_id: str
    selected: str | None
    incumbent: str | None
    rationale: tuple[str, ...]
    alternatives: tuple[str, ...]
    outcome: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True, slots=True)
class ManagerDecisionLedger:
    records: tuple[ManagerDecisionRecord, ...] = ()
    version: str = MANAGER_AI_VERSION

    def __post_init__(self) -> None:
        if self.version != MANAGER_AI_VERSION:
            raise ValueError("unsupported manager decision ledger version")
        if tuple(record.sequence for record in self.records) != tuple(
            range(1, len(self.records) + 1)
        ):
            raise ValueError("manager decision records must have contiguous sequences")

    def add(
        self,
        *,
        trace: ManagerDecisionTrace,
        stage: str,
        profile: ManagerProfile,
    ) -> ManagerDecisionLedger:
        selected = next(
            (
                candidate
                for candidate in trace.candidates
                if candidate.candidate_id == trace.selected
            ),
            None,
        )
        rationale = (
            tuple(
                f"{item.contribution_id}:{item.value:+.6f} {item.reason}"
                for item in selected.contributions
            )
            if selected
            else ("no eligible candidate",)
        )
        record = ManagerDecisionRecord(
            len(self.records) + 1,
            trace.decision_id,
            stage,
            profile.manager_id,
            profile.team_id,
            trace.selected,
            trace.incumbent,
            rationale,
            tuple(candidate.candidate_id for candidate in trace.candidates[:5]),
        )
        return ManagerDecisionLedger((*self.records, record))


@dataclass(frozen=True, slots=True)
class DraftShadowResult:
    plan: DraftPlan
    traces: tuple[ManagerDecisionTrace, ...]
    ledger: ManagerDecisionLedger
    mode: ManagerPolicyMode = ManagerPolicyMode.SHADOW
    version: str = MANAGER_AI_VERSION


@dataclass(frozen=True, slots=True)
class MarketShadowResult:
    plan: MarketPlan
    traces: tuple[ManagerDecisionTrace, ...]
    ledger: ManagerDecisionLedger
    mode: ManagerPolicyMode = ManagerPolicyMode.SHADOW
    version: str = MANAGER_AI_VERSION


def evaluate_manager_decision(
    *,
    decision_id: str,
    candidates: Sequence[ManagerCandidate],
    reasonable_band: float = 0.08,
    style_contribution_limit: float = 0.04,
    incumbent: str | None = None,
) -> ManagerDecisionTrace:
    """Evaluate without executing; style may only separate rationally close choices."""
    if not decision_id.strip():
        raise ValueError("decision_id must not be blank")
    if (
        not isfinite(reasonable_band)
        or reasonable_band < 0
        or not isfinite(style_contribution_limit)
        or style_contribution_limit < 0
    ):
        raise ValueError("decision bands must be finite and non-negative")
    ids = tuple(candidate.candidate_id for candidate in candidates)
    if len(ids) != len(set(ids)):
        raise ValueError("manager candidate ids must be unique")

    provisional: list[ManagerCandidateTrace] = []
    for candidate in candidates:
        eligible = not candidate.hard_rejections
        rational_score = _rounded(sum(item.value for item in candidate.rational))
        style_score = _rounded(sum(item.value for item in candidate.style))
        provisional.append(
            ManagerCandidateTrace(
                candidate.candidate_id,
                eligible,
                False,
                candidate.hard_rejections,
                rational_score if eligible else None,
                style_score if eligible else None,
                0.0 if eligible else None,
                0.0 if eligible else None,
                (*candidate.rational, *candidate.style),
            )
        )
    eligible_scores = tuple(
        item.rational_score for item in provisional if item.rational_score is not None
    )
    best_rational = max(eligible_scores, default=None)
    traces: list[ManagerCandidateTrace] = []
    for item in provisional:
        reasonable = (
            item.eligible
            and best_rational is not None
            and best_rational - item.rational_score <= reasonable_band  # type: ignore[operator]
        )
        applied_style = (
            _rounded(
                max(
                    -style_contribution_limit,
                    min(style_contribution_limit, item.raw_style_score),
                )
            )
            if reasonable and item.raw_style_score is not None
            else 0.0
            if item.eligible
            else None
        )
        final_score = (
            _rounded(item.rational_score + applied_style)
            if reasonable and item.rational_score is not None and applied_style is not None
            else None
        )
        traces.append(
            ManagerCandidateTrace(
                item.candidate_id,
                item.eligible,
                reasonable,
                item.hard_rejections,
                item.rational_score,
                item.raw_style_score,
                applied_style,
                final_score,
                item.contributions,
            )
        )
    ordered = tuple(
        sorted(
            traces,
            key=lambda item: (
                item.final_score is None,
                -(item.final_score or 0.0),
                -(item.rational_score or 0.0),
                item.candidate_id,
            ),
        )
    )
    selected = next(
        (item.candidate_id for item in ordered if item.final_score is not None),
        None,
    )
    return ManagerDecisionTrace(
        decision_id,
        selected,
        incumbent,
        selected == incumbent if incumbent is not None else None,
        reasonable_band,
        style_contribution_limit,
        ordered,
    )


def generate_draft_shadow(
    *,
    management: LeagueManagementState,
    players: Sequence[CareerPlayer],
    picks: Sequence[DraftPickAsset],
    profiles: Mapping[str, ManagerProfile],
    contract_rules: ContractRules,
    rookie_salary: int,
    incumbent: DraftPlan | None = None,
    scouted_potential: Mapping[tuple[str, int], AbilityRatings] | None = None,
) -> DraftShadowResult:
    """Create a deterministic draft plan and audit trail without executing it."""
    if rookie_salary < 1:
        raise ValueError("rookie_salary must be positive")
    _validate_profiles(management, profiles)
    player_map = {player.player_id: player for player in players}
    available = {player.player_id for player in players if player.status is CareerStatus.PROSPECT}
    roster_sizes = {roster.team_id: len(roster.player_ids) for roster in management.rosters}
    provisional_rosters = {roster.team_id: roster.player_ids for roster in management.rosters}
    payrolls = _payrolls(management)
    incumbent_map = (
        {item.selection_number: f"player:{item.player_id}" for item in incumbent.selections}
        if incumbent
        else {}
    )
    selections: list[DraftSelection] = []
    traces: list[ManagerDecisionTrace] = []
    ledger = ManagerDecisionLedger()
    for pick in sorted(picks, key=lambda item: item.selection_number):
        profile = profiles[pick.owner_team_id]
        candidates = tuple(
            _player_candidate(
                player_map[player_id],
                profile,
                team_player_ids=provisional_rosters[pick.owner_team_id],
                player_map=player_map,
                salary=rookie_salary,
                evaluated_potential=(
                    scouted_potential.get((pick.owner_team_id, player_id))
                    if scouted_potential is not None
                    else None
                ),
                hard_rejections=_draft_rejections(
                    player_map[player_id],
                    available,
                    roster_sizes[pick.owner_team_id],
                    payrolls[pick.owner_team_id],
                    contract_rules,
                    rookie_salary,
                ),
            )
            for player_id in sorted(available)
        )
        trace = evaluate_manager_decision(
            decision_id=f"draft:{pick.selection_number}:{pick.owner_team_id}",
            candidates=candidates,
            incumbent=incumbent_map.get(pick.selection_number),
        )
        if trace.selected is None:
            raise ValueError(f"no eligible prospect for selection {pick.selection_number}")
        player_id = _candidate_player_id(trace.selected)
        selections.append(DraftSelection(pick.selection_number, pick.owner_team_id, player_id))
        traces.append(trace)
        ledger = ledger.add(trace=trace, stage="draft", profile=profile)
        available.remove(player_id)
        roster_sizes[pick.owner_team_id] += 1
        provisional_rosters[pick.owner_team_id] = (
            *provisional_rosters[pick.owner_team_id],
            player_id,
        )
        payrolls[pick.owner_team_id] += rookie_salary
    return DraftShadowResult(DraftPlan(tuple(selections)), tuple(traces), ledger)


def generate_market_shadow(
    *,
    management: LeagueManagementState,
    players: Sequence[CareerPlayer],
    profiles: Mapping[str, ManagerProfile],
    contract_rules: ContractRules,
    annual_salary: int | None = None,
    years: int = 1,
    incumbent: MarketPlan | None = None,
) -> MarketShadowResult:
    """Recommend at most one free-agent signing per team in deterministic order."""
    _validate_profiles(management, profiles)
    salary = contract_rules.minimum_salary if annual_salary is None else annual_salary
    if not contract_rules.minimum_salary <= salary <= contract_rules.maximum_salary:
        raise ValueError("shadow signing salary is outside configured bounds")
    if not 1 <= years <= contract_rules.maximum_years:
        raise ValueError("shadow signing years are outside configured bounds")
    player_map = {player.player_id: player for player in players}
    available = set(management.free_agent_ids)
    roster_sizes = {roster.team_id: len(roster.player_ids) for roster in management.rosters}
    payrolls = _payrolls(management)
    incumbent_by_team = (
        {
            action.team_id: f"player:{action.player_id}"
            for action in incumbent.actions
            if action.kind is MarketActionKind.SIGN
        }
        if incumbent
        else {}
    )
    actions: list[MarketAction] = []
    traces: list[ManagerDecisionTrace] = []
    ledger = ManagerDecisionLedger()
    action_id = 1
    for team_id in sorted(profiles):
        profile = profiles[team_id]
        candidates = [
            _pass_candidate(profile),
            *(
                _player_candidate(
                    player_map[player_id],
                    profile,
                    team_player_ids=_team_player_ids(management, team_id),
                    player_map=player_map,
                    salary=salary,
                    hard_rejections=_market_rejections(
                        player_id,
                        available,
                        roster_sizes[team_id],
                        payrolls[team_id],
                        contract_rules,
                        salary,
                        player_map,
                    ),
                )
                for player_id in sorted(available)
                if player_id in player_map
            ),
        ]
        trace = evaluate_manager_decision(
            decision_id=f"market:{management.season_year}:{team_id}",
            candidates=tuple(candidates),
            incumbent=incumbent_by_team.get(team_id, "pass"),
        )
        traces.append(trace)
        ledger = ledger.add(trace=trace, stage="market", profile=profile)
        if trace.selected is not None and trace.selected != "pass":
            player_id = _candidate_player_id(trace.selected)
            actions.append(
                MarketAction(
                    action_id,
                    MarketActionKind.SIGN,
                    player_id,
                    team_id,
                    salary,
                    years,
                )
            )
            action_id += 1
            available.remove(player_id)
            roster_sizes[team_id] += 1
            payrolls[team_id] += salary
    return MarketShadowResult(MarketPlan(tuple(actions)), tuple(traces), ledger)


def _player_candidate(
    player: CareerPlayer,
    profile: ManagerProfile,
    *,
    team_player_ids: Sequence[int],
    player_map: Mapping[int, CareerPlayer],
    salary: int,
    hard_rejections: tuple[str, ...],
    evaluated_potential: AbilityRatings | None = None,
) -> ManagerCandidate:
    ability = _rating_mean(player.profile.abilities) / 100
    potential = _rating_mean(evaluated_potential or player.potential) / 100
    upside = max(0.0, potential - ability)
    fit = _size_need(player.profile.size_class, team_player_ids, player_map)
    age_value = max(0.0, min(1.0, (34 - player.age) / 16))
    salary_value = 1 / (1 + salary / 10_000_000)
    rational = (
        _contribution("ability", "competence", ability * 0.45, "current ability"),
        _contribution("potential", "development", potential * 0.18, "career ceiling"),
        _contribution("upside", "development", upside * 0.12, "remaining upside"),
        _contribution("fit", "roster", fit * 0.15, "size-class roster need"),
        _contribution("age", "timeline", age_value * 0.05, "age-curve value"),
        _contribution("salary", "economics", salary_value * 0.05, "salary efficiency"),
    )
    star_signal = max(0.0, ability - 0.65)
    style = (
        _contribution(
            "win-now",
            "style",
            (profile.win_now - 50) / 50 * ability * 0.025,
            "manager win-now preference",
            source="personality",
        ),
        _contribution(
            "development-bias",
            "style",
            (profile.development_bias - 50) / 50 * upside * 0.05,
            "manager development preference",
            source="personality",
        ),
        _contribution(
            "star-preference",
            "style",
            (profile.star_preference - 50) / 50 * star_signal * 0.04,
            "manager star preference",
            source="personality",
        ),
        _contribution(
            "depth-preference",
            "style",
            (profile.depth_preference - 50) / 50 * fit * 0.025,
            "manager depth preference",
            source="personality",
        ),
        _contribution(
            "risk",
            "style",
            (profile.risk_tolerance - 50) / 50 * upside * 0.025,
            "manager risk tolerance",
            source="risk",
        ),
    )
    return ManagerCandidate(
        f"player:{player.player_id}",
        hard_rejections,
        rational,
        style,
    )


def _pass_candidate(profile: ManagerProfile) -> ManagerCandidate:
    return ManagerCandidate(
        "pass",
        (),
        (
            _contribution(
                "preserve-cap",
                "economics",
                0.18 + profile.cap_discipline / 100 * 0.12,
                "preserve cap space and roster flexibility",
            ),
        ),
        (
            _contribution(
                "continuity",
                "style",
                (profile.continuity - 50) / 50 * 0.03,
                "manager continuity preference",
                source="personality",
            ),
        ),
    )


def _draft_rejections(
    player: CareerPlayer,
    available: set[int],
    roster_size: int,
    payroll: int,
    rules: ContractRules,
    salary: int,
) -> tuple[str, ...]:
    rejected: list[str] = []
    if player.status is not CareerStatus.PROSPECT or player.player_id not in available:
        rejected.append("not-available-prospect")
    if roster_size >= rules.maximum_roster_players:
        rejected.append("roster-full")
    if payroll + salary > rules.salary_cap:
        rejected.append("salary-cap")
    return tuple(rejected)


def _market_rejections(
    player_id: int,
    available: set[int],
    roster_size: int,
    payroll: int,
    rules: ContractRules,
    salary: int,
    player_map: Mapping[int, CareerPlayer],
) -> tuple[str, ...]:
    rejected: list[str] = []
    player = player_map.get(player_id)
    if player_id not in available or player is None:
        rejected.append("not-available-free-agent")
    elif player.status is not CareerStatus.FREE_AGENT:
        rejected.append("invalid-career-status")
    if roster_size >= rules.maximum_roster_players:
        rejected.append("roster-full")
    if payroll + salary > rules.salary_cap:
        rejected.append("salary-cap")
    return tuple(rejected)


def _validate_profiles(
    management: LeagueManagementState,
    profiles: Mapping[str, ManagerProfile],
) -> None:
    team_ids = {roster.team_id for roster in management.rosters}
    if set(profiles) != team_ids:
        raise ValueError("manager profiles must cover every league team exactly")
    if any(key != profile.team_id for key, profile in profiles.items()):
        raise ValueError("manager profile keys must match profile team ids")


def _payrolls(management: LeagueManagementState) -> dict[str, int]:
    result = {roster.team_id: 0 for roster in management.rosters}
    for contract in management.contracts:
        result[contract.team_id] += contract.annual_salary
    return result


def _team_player_ids(management: LeagueManagementState, team_id: str) -> tuple[int, ...]:
    return next(roster.player_ids for roster in management.rosters if roster.team_id == team_id)


def _size_need(
    size: SizeClass,
    team_player_ids: Sequence[int],
    player_map: Mapping[int, CareerPlayer],
) -> float:
    counts = {item: 0 for item in SizeClass}
    for player_id in team_player_ids:
        player = player_map.get(player_id)
        if player is not None:
            counts[player.profile.size_class] += 1
    total = sum(counts.values())
    if total == 0:
        return 1.0
    return max(0.0, min(1.0, 1 - counts[size] / max(1, total)))


def _rating_mean(ratings: AbilityRatings) -> float:
    values = tuple(cast(int, getattr(ratings, item.name)) for item in fields(AbilityRatings))
    return sum(values) / len(values)


def _candidate_player_id(candidate_id: str) -> int:
    prefix, separator, value = candidate_id.partition(":")
    if prefix != "player" or separator != ":":
        raise ValueError("selected candidate is not a player")
    return int(value)


def _contribution(
    contribution_id: str,
    group: str,
    value: float,
    reason: str,
    *,
    source: str = "competence",
) -> DecisionContribution:
    return DecisionContribution(contribution_id, group, source, _rounded(value), reason)


def _rounded(value: float) -> float:
    return round(value, 6)

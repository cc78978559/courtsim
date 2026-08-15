"""Thirty-team franchise adapter for focal-team manager experiments."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field, fields
from math import fsum
from pathlib import Path
from typing import Any, cast

from courtsim.analysis.nba_quick_sim_executor import build_nba_player_season_summaries
from courtsim.analysis.nba_shot_profiles import NBAShotProfileSet
from courtsim.analysis.quick_sim_comparison import QuickSimSeasonSummary
from courtsim.cap_mechanics import cap_rules_for_salary_cap
from courtsim.career import CareerRules, DraftRules
from courtsim.domain.game import GameClockConfig
from courtsim.domain.player import AbilityRatings
from courtsim.management import ContractRules
from courtsim.manager_ai import (
    REALITY_BASELINE_POLICY,
    WHITE_BOX_CANDIDATE_POLICY,
    FrontOfficePolicySpec,
    ManagerProfile,
)
from courtsim.manager_rotation import ManagerRotationRules
from courtsim.manager_trade import ManagerTradeRules
from courtsim.model.trace_mode import TraceMode
from courtsim.nba_franchise import NBAFranchiseSeasonExecution, execute_nba_franchise_season
from courtsim.nba_franchise_artifacts import (
    nba_franchise_state_from_json,
    nba_franchise_state_to_json,
)
from courtsim.nba_manager_evaluation import NBAFrontOfficeOutcome
from courtsim.nba_manager_experiment import (
    NBA_MANAGER_EXPERIMENT_VERSION,
    NBAManagerExperimentArm,
    NBAManagerSeasonExecution,
    NBAManagerSeasonRequest,
)
from courtsim.parameters import ModelParameters
from courtsim.prospects import ProspectGenerationRules
from courtsim.randomness import derive_seed
from courtsim.scouting import ScoutingRules
from courtsim.season import SeasonConfig
from courtsim.three_team_market import ThreeTeamMarketRules
from courtsim.trade_market import TradeMarketRules
from courtsim.trades import TradeRules

NBA_MANAGER_ADAPTER_VERSION = "nba-manager-adapter-v1"


@dataclass(frozen=True, slots=True)
class MacroMetricRange:
    metric: str
    minimum: float
    maximum: float

    def __post_init__(self) -> None:
        if not self.metric.strip() or self.minimum > self.maximum:
            raise ValueError("NBA manager macro metric range is invalid")


@dataclass(frozen=True, slots=True)
class NBAFrontOfficeExperimentAdapter:
    parameters: ModelParameters
    game_config: GameClockConfig
    profiles: Mapping[str, ManagerProfile]
    contract_rules: ContractRules
    draft_rules: DraftRules
    career_rules: CareerRules = field(default_factory=CareerRules)
    scouting_rules: ScoutingRules = field(default_factory=ScoutingRules)
    season_config: SeasonConfig = field(default_factory=SeasonConfig)
    rotation_rules: ManagerRotationRules = field(default_factory=ManagerRotationRules)
    prospect_rules: ProspectGenerationRules | None = None
    trade_rules: TradeRules = field(default_factory=TradeRules)
    manager_trade_rules: ManagerTradeRules = field(default_factory=ManagerTradeRules)
    trade_market_rules: TradeMarketRules = field(default_factory=TradeMarketRules)
    three_team_market_rules: ThreeTeamMarketRules = field(default_factory=ThreeTeamMarketRules)
    shot_zone_profiles: NBAShotProfileSet | None = None
    macro_ranges: tuple[MacroMetricRange, ...] = ()
    minimum_roster_players: int = 12
    trace_mode: TraceMode = TraceMode.AGGREGATE_ONLY
    version: str = NBA_MANAGER_ADAPTER_VERSION

    def __post_init__(self) -> None:
        if len(self.profiles) != 30 or set(self.profiles) != {
            profile.team_id for profile in self.profiles.values()
        }:
            raise ValueError("NBA manager adapter requires thirty keyed manager profiles")
        if self.version != NBA_MANAGER_ADAPTER_VERSION:
            raise ValueError("unsupported NBA manager adapter version")
        if not 5 <= self.minimum_roster_players <= self.contract_rules.maximum_roster_players:
            raise ValueError("NBA manager minimum roster size is outside contract bounds")
        if self.trace_mode is not TraceMode.AGGREGATE_ONLY:
            raise ValueError("formal NBA manager experiments require aggregate-only traces")

    def __call__(self, request: NBAManagerSeasonRequest) -> NBAManagerSeasonExecution:
        state, stored_contract_rules = nba_franchise_state_from_json(request.state_payload)
        if stored_contract_rules != self.contract_rules:
            raise ValueError("NBA manager state contract rules differ from adapter")
        if state.management.season_year != request.season_year:
            raise ValueError("NBA manager state season differs from request")
        policies = _policy_map(
            tuple(roster.team_id for roster in state.management.rosters),
            request.arm,
            request.focal_team_id,
        )
        season_seed = derive_seed(
            request.master_seed,
            NBA_MANAGER_EXPERIMENT_VERSION,
            request.source_id,
            request.season_year,
        )
        execution = execute_nba_franchise_season(
            state,
            seed=season_seed,
            parameters=self.parameters,
            game_config=self.game_config,
            profiles=dict(self.profiles),
            contract_rules=self.contract_rules,
            draft_rules=self.draft_rules,
            career_rules=self.career_rules,
            scouting_rules=self.scouting_rules,
            season_config=self.season_config,
            rotation_rules=self.rotation_rules,
            prospect_rules=self.prospect_rules,
            trade_rules=self.trade_rules,
            manager_trade_rules=self.manager_trade_rules,
            trade_market_rules=self.trade_market_rules,
            three_team_market_rules=self.three_team_market_rules,
            shot_zone_profiles=self.shot_zone_profiles,
            front_office_policies=policies,
            minimum_offseason_roster_players=self.minimum_roster_players,
            trace_mode=self.trace_mode,
        )
        outcome = _outcome(request, execution, self.contract_rules, self.macro_ranges)
        audit = _compact_audit(request, execution, policies, outcome)
        return NBAManagerSeasonExecution(
            nba_franchise_state_to_json(execution.final_state, self.contract_rules),
            outcome,
            json.dumps(audit, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        )


def load_macro_metric_ranges(reference_path: str | Path) -> tuple[MacroMetricRange, ...]:
    try:
        value: object = json.loads(Path(reference_path).read_text(encoding="utf-8"))
        root = _object(value, "quick-sim reference")
        raw_metrics = root["metrics"]
        if not isinstance(raw_metrics, list):
            raise ValueError("quick-sim reference metrics must be a list")
        return tuple(
            MacroMetricRange(
                str(_object(item, "quick-sim metric")["metric"]),
                float(_object(item, "quick-sim metric")["minimum"]),
                float(_object(item, "quick-sim metric")["maximum"]),
            )
            for item in raw_metrics
        )
    except (KeyError, OSError, TypeError, json.JSONDecodeError) as error:
        raise ValueError("cannot load NBA manager macro reference") from error


def _policy_map(
    team_ids: tuple[str, ...],
    arm: NBAManagerExperimentArm,
    focal_team_id: str,
) -> dict[str, FrontOfficePolicySpec]:
    if focal_team_id not in team_ids:
        raise ValueError("NBA manager focal team is absent from league")
    policies = {team_id: REALITY_BASELINE_POLICY for team_id in team_ids}
    if arm is NBAManagerExperimentArm.TREATMENT:
        policies[focal_team_id] = WHITE_BOX_CANDIDATE_POLICY
    return policies


def _outcome(
    request: NBAManagerSeasonRequest,
    execution: NBAFranchiseSeasonExecution,
    contract_rules: ContractRules,
    macro_ranges: tuple[MacroMetricRange, ...],
) -> NBAFrontOfficeOutcome:
    focal = request.focal_team_id
    standing = next(item for item in execution.simulation.season.standings if item.team_id == focal)
    games = standing.wins + standing.losses + standing.ties
    opened, accepted, rounds, stale = _negotiation_metrics(execution, focal)
    return NBAFrontOfficeOutcome(
        request.source_id,
        request.master_seed,
        request.season_year,
        focal,
        standing.wins / games if games else 0.0,
        _postseason_progress(execution, focal),
        _player_asset_value(execution, focal, contract_rules),
        _draft_asset_value(execution, focal),
        _cap_health(execution, focal, contract_rules),
        _roster_continuity(execution, focal),
        opened,
        accepted,
        rounds,
        stale,
        illegal_transactions=0,
        unplayable_rosters=sum(
            len(roster.player_ids) < 5 for roster in execution.final_state.management.rosters
        ),
        macro_gate_passed=_macro_gate(execution.simulation.summary, macro_ranges),
    )


def _postseason_progress(execution: NBAFranchiseSeasonExecution, team_id: str) -> float:
    postseason = execution.simulation.postseason
    if postseason.champion_team_id == team_id:
        return 1.0
    rounds = [
        item.round_number
        for item in postseason.series
        if team_id in {item.first_team_id, item.second_team_id}
    ]
    if rounds:
        return {1: 0.25, 2: 0.50, 3: 0.70, 4: 0.85}[max(rounds)]
    play_in_teams = {
        item.team_id
        for result in (execution.simulation.east_play_in, execution.simulation.west_play_in)
        for item in result.regular_season_seeds[6:10]
    }
    return 0.10 if team_id in play_in_teams else 0.0


def _player_asset_value(
    execution: NBAFranchiseSeasonExecution,
    team_id: str,
    rules: ContractRules,
) -> float:
    state = execution.final_state
    roster = next(item for item in state.management.rosters if item.team_id == team_id)
    players = {player.player_id: player for player in state.players}
    contracts = {item.player_id: item for item in state.management.contracts}
    values = []
    for player_id in roster.player_ids:
        player = players[player_id]
        contract = contracts[player_id]
        ability = _rating_mean(player.profile.abilities) / 100
        potential = _rating_mean(player.potential) / 100
        age_value = max(0.0, min(1.0, (34 - player.age) / 16))
        contract_value = max(0.0, 1 - contract.annual_salary / rules.maximum_salary)
        values.append(0.55 * ability + 0.25 * potential + 0.10 * age_value + 0.10 * contract_value)
    top = sorted(values, reverse=True)[:12]
    return max(0.0, min(1.0, fsum(top) / len(top) if top else 0.0))


def _draft_asset_value(execution: NBAFranchiseSeasonExecution, team_id: str) -> float:
    state = execution.final_state
    season_year = state.management.season_year
    owned = [item for item in state.draft_assets.picks if item.owner_team_id == team_id]
    raw = 0.0
    maximum = 0.0
    for ahead in range(1, 8):
        discount = 0.85 ** (ahead - 1)
        maximum += 1.25 * discount
    for pick in owned:
        ahead = max(1, pick.draft_year - season_year)
        if ahead > 7:
            continue
        round_value = 1.0 if pick.round_number == 1 else 0.25
        protection = 1.0
        if pick.protected_top_n:
            protection = max(0.5, 1 - pick.protected_top_n / 60)
        elif pick.conditions:
            protection = 0.75
        raw += round_value * protection * 0.85 ** (ahead - 1)
    raw += 0.15 * sum(
        0.85 ** max(0, swap.draft_year - season_year - 1)
        for swap in state.draft_assets.swaps
        if swap.controller_team_id == team_id and swap.draft_year <= season_year + 7
    )
    return max(0.0, min(1.0, raw / maximum if maximum else 0.0))


def _cap_health(
    execution: NBAFranchiseSeasonExecution,
    team_id: str,
    rules: ContractRules,
) -> float:
    state = execution.final_state
    contracts = [item for item in state.management.contracts if item.team_id == team_id]
    payroll = sum(item.annual_salary for item in contracts)
    cap_rules = cap_rules_for_salary_cap(rules.salary_cap)
    floor = rules.salary_cap * 85 // 100
    payroll_score = 1 - max(0, payroll - floor) / max(1, cap_rules.second_apron - floor)
    future_commitment = sum(item.annual_salary * item.years_remaining for item in contracts) / max(
        1, rules.maximum_roster_players * rules.maximum_salary * rules.maximum_years
    )
    future_score = 1 - min(1.0, future_commitment)
    rights_score = min(
        1.0,
        sum(item.team_id == team_id for item in state.cap_ledger.bird_rights)
        / rules.maximum_roster_players,
    )
    exception_score = min(
        1.0,
        sum(
            item.remaining_amount
            for item in state.cap_ledger.trade_exceptions
            if item.team_id == team_id
        )
        / rules.salary_cap,
    )
    return max(
        0.0,
        min(
            1.0,
            0.60 * payroll_score
            + 0.25 * future_score
            + 0.10 * rights_score
            + 0.05 * exception_score,
        ),
    )


def _roster_continuity(execution: NBAFranchiseSeasonExecution, team_id: str) -> float:
    initial_roster = next(
        item for item in execution.initial_state.management.rosters if item.team_id == team_id
    )
    final_roster = set(
        next(
            item for item in execution.final_state.management.rosters if item.team_id == team_id
        ).player_ids
    )
    summaries = {
        item.player_id: item
        for item in build_nba_player_season_summaries(
            execution.simulation,
            execution.initial_state.players,
        )
    }
    top = sorted(
        initial_roster.player_ids,
        key=lambda player_id: (-summaries[player_id].seconds_played, player_id),
    )[:8]
    weights = [summaries[player_id].seconds_played for player_id in top]
    if not any(weights):
        return sum(player_id in final_roster for player_id in top) / len(top) if top else 0.0
    return sum(
        weight for player_id, weight in zip(top, weights, strict=True) if player_id in final_roster
    ) / sum(weights)


def _negotiation_metrics(
    execution: NBAFranchiseSeasonExecution,
    team_id: str,
) -> tuple[int, int, int, int]:
    bilateral = [
        item
        for item in execution.bilateral_trade_market.negotiations
        if team_id in {item.team_a_id, item.team_b_id}
    ]
    three_team = [
        item for item in execution.three_team_trade_market.negotiations if team_id in item.team_ids
    ]
    opened = len(bilateral) + len(three_team)
    accepted = sum(item.accepted_trade_id is not None for item in bilateral) + sum(
        any(node.status == "accepted" for node in tree.nodes) for tree in three_team
    )
    rounds = sum(item.rounds_completed for item in bilateral) + sum(
        max(node.round_number for node in tree.nodes) for tree in three_team
    )
    stale = sum(
        "stale" in rejection
        for evaluation in execution.bilateral_trade_market.evaluations
        for rejection in evaluation.shadow.hard_rejections
    ) + sum(
        "stale" in rejection
        for evaluation in execution.three_team_trade_market.evaluations
        for rejection in evaluation.shadow.hard_rejections
    )
    return opened, accepted, rounds, stale


def _macro_gate(
    summary: QuickSimSeasonSummary,
    ranges: tuple[MacroMetricRange, ...],
) -> bool:
    if not ranges:
        return True
    values = {
        "win-rate-stddev": summary.win_rate_stddev,
        "pace-possessions-per-team": summary.pace_possessions_per_team,
        "offensive-rating": summary.offensive_rating,
        "point-differential-stddev": summary.point_differential_stddev,
        "playoff-upset-rate": summary.playoff_upset_rate,
        "champion-seed-mean": summary.champion_seed,
    }
    return all(
        values[item.metric] is not None
        and item.minimum <= cast(float, values[item.metric]) <= item.maximum
        for item in ranges
    )


def _compact_audit(
    request: NBAManagerSeasonRequest,
    execution: NBAFranchiseSeasonExecution,
    policies: Mapping[str, FrontOfficePolicySpec],
    outcome: NBAFrontOfficeOutcome,
) -> dict[str, object]:
    return {
        "version": NBA_MANAGER_ADAPTER_VERSION,
        "arm": request.arm.name.lower(),
        "focal_team_id": request.focal_team_id,
        "candidate_teams": [
            team_id
            for team_id, policy in sorted(policies.items())
            if policy == WHITE_BOX_CANDIDATE_POLICY
        ],
        "trade_clearing_choice": execution.trade_clearing_choice,
        "bilateral_executed": len(execution.bilateral_trade_execution.plan.offers),
        "three_team_executed": len(execution.three_team_trade_execution.plan.offers),
        "draft_selections": len(execution.offseason.offseason.selections),
        "market_actions": len(execution.offseason.offseason.market_actions),
        "summary": asdict(execution.simulation.summary),
        "outcome": asdict(outcome),
    }


def _rating_mean(ratings: AbilityRatings) -> float:
    values = tuple(cast(int, getattr(ratings, item.name)) for item in fields(AbilityRatings))
    return sum(values) / len(values)


def _object(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return cast(dict[str, Any], value)

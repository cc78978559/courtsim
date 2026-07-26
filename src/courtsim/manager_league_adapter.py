"""Production adapter from CourtSim league engines to manager experiments."""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import asdict, dataclass, field, fields, replace
from typing import Any, cast

from courtsim.cap_mechanics import (
    CapLedger,
    CapMechanicsRules,
    cap_ledger_from_dict,
    cap_ledger_to_dict,
    cap_rules_for_salary_cap,
    expire_cap_ledger,
)
from courtsim.career import (
    CareerPlayer,
    CareerRules,
    CareerStatus,
    DevelopmentTraits,
    DraftPickAsset,
    DraftPlan,
    DraftRules,
    DraftSelection,
    PlayerSeasonSummary,
    advance_careers,
    advance_offseason,
    apply_draft,
    offseason_result_to_dict,
)
from courtsim.domain.enums import Coverage, PlayFamily, ShotZone
from courtsim.domain.game import GameClockConfig
from courtsim.domain.player import AbilityRatings, PlayerProfile
from courtsim.domain.player_serialization import (
    player_profile_from_dict,
    player_profile_to_dict,
)
from courtsim.domain.results import (
    BlockedShotSegmentResult,
    MadeShotSegmentResult,
    MissedShotSegmentResult,
    ShootingFoulSegmentResult,
)
from courtsim.draft_assets import (
    DraftAssetLedger,
    DraftAssetSettlement,
    FutureDraftPickAsset,
    draft_asset_ledger_from_dict,
    draft_asset_ledger_to_dict,
    seed_future_draft_picks,
    settle_draft_assets,
)
from courtsim.draft_lottery import (
    DraftLotteryResult,
    DraftLotteryRules,
    resolve_draft_lottery,
)
from courtsim.management import (
    ContractRules,
    LeagueManagementState,
    MarketAction,
    MarketActionKind,
    MarketPlan,
    MarketResult,
    advance_contract_year,
    apply_market_plan,
    market_result_from_dict,
    market_result_to_dict,
    validate_management_state,
)
from courtsim.manager_ai import (
    ManagerProfile,
    generate_draft_shadow,
    generate_market_shadow,
)
from courtsim.manager_authority import (
    ManagerDecisionStage,
    default_manager_authority_policy,
    manager_authority_to_dict,
    manager_execution_receipt,
)
from courtsim.manager_experiment import (
    ManagerExperimentArm,
    ManagerSeasonExecution,
    ManagerSeasonMetrics,
    ManagerSeasonRequest,
)
from courtsim.manager_learning import (
    ManagerLearningState,
    OpponentObservation,
    OpponentTacticalAdjustment,
    manager_learning_from_dict,
    manager_learning_to_dict,
    opponent_rotation_adjustment,
    opponent_tactical_adjustment,
    update_manager_learning,
)
from courtsim.manager_rotation import (
    ManagerRotationResult,
    ManagerRotationRules,
    generate_manager_rotation,
)
from courtsim.manager_trade import ManagerTradeRules
from courtsim.model.action_setup import TeamDefenseStrategy, TeamOffenseStrategy
from courtsim.model.game_runtime import (
    GameMatchups,
    GameTeam,
    TeamTempoStrategy,
    sample_game,
)
from courtsim.model.interaction_compiler import (
    DefensiveMatchups,
    Matchup,
    ProfileLineup,
)
from courtsim.model.trace_mode import TraceMode
from courtsim.nba_league import (
    NBAConferenceAlignment,
    nba_alignment_from_dict,
    nba_alignment_to_dict,
)
from courtsim.parameters import ModelParameters
from courtsim.playoffs import (
    PlayoffConfig,
    PlayoffGame,
    PlayoffResult,
    PlayoffSeed,
    playoff_result_to_dict,
    resolve_playoffs,
)
from courtsim.prospects import (
    ProspectGenerationRules,
    generate_prospect_class,
    prospect_class_to_dict,
)
from courtsim.randomness import RandomFrame, RandomFrameAddress, derive_seed
from courtsim.rosters import RosterRules, RosterSnapshot
from courtsim.rotations import FatigueConfig
from courtsim.rules import GameRules
from courtsim.scouting import (
    ScoutingRules,
    generate_scouting_reports,
    scouting_reports_to_dict,
)
from courtsim.season import (
    INJURY_VERSION,
    InjuryRecord,
    PlayerSeasonState,
    ScheduledGame,
    SeasonConfig,
    SeasonResult,
    SeasonSchedule,
    available_game_team,
    sample_season,
    season_result_to_dict,
)
from courtsim.three_team_market import (
    ThreeTeamMarketExecution,
    ThreeTeamMarketPlan,
    ThreeTeamMarketRules,
    ThreeTeamMarketShadowResult,
    apply_three_team_market_plan,
    generate_three_team_market_shadow,
    three_team_shadow_gain,
)
from courtsim.trade_market import (
    TradeMarketExecution,
    TradeMarketPlan,
    TradeMarketRules,
    TradeMarketShadowResult,
    apply_trade_market_plan,
    generate_trade_market_shadow,
)
from courtsim.trades import TradeRules

MANAGER_LEAGUE_ADAPTER_VERSION = "manager-league-adapter-v1"


class ManagerLeagueAdapterError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class PostseasonGameState:
    round_number: int
    series_index: int
    game_number: int
    day: int
    home_team_id: str
    away_team_id: str
    home_unavailable: tuple[int, ...]
    away_unavailable: tuple[int, ...]
    forfeit_team_id: str | None
    maximum_initial_fatigue: int
    maximum_final_fatigue: int


@dataclass(frozen=True, slots=True)
class PostseasonSimulation:
    result: PlayoffResult
    initial_player_states: tuple[PlayerSeasonState, ...]
    final_player_states: tuple[PlayerSeasonState, ...]
    injuries: tuple[InjuryRecord, ...]
    games: tuple[PostseasonGameState, ...]
    player_seconds: tuple[tuple[int, int], ...]
    player_games: tuple[tuple[int, int], ...]
    team_games: tuple[tuple[str, int], ...]


@dataclass(frozen=True, slots=True)
class CourtSimLeagueState:
    contract_rules: ContractRules
    management: LeagueManagementState
    players: tuple[CareerPlayer, ...]
    draft_assets: DraftAssetLedger = field(default_factory=DraftAssetLedger)
    cap_ledger: CapLedger = field(default_factory=CapLedger)
    manager_learning: tuple[ManagerLearningState, ...] = ()
    nba_alignment: NBAConferenceAlignment | None = None
    version: str = MANAGER_LEAGUE_ADAPTER_VERSION

    def __post_init__(self) -> None:
        if self.version != MANAGER_LEAGUE_ADAPTER_VERSION:
            raise ValueError("unsupported manager league adapter version")
        validate_management_state(
            self.management,
            self.contract_rules,
            maximum_payroll=cap_rules_for_salary_cap(self.contract_rules.salary_cap).second_apron,
        )
        if self.players != tuple(sorted(self.players, key=lambda item: item.player_id)):
            raise ValueError("manager league players must be ordered by player_id")
        player_ids = tuple(player.player_id for player in self.players)
        if len(player_ids) != len(set(player_ids)):
            raise ValueError("manager league player ids must be unique")
        governed_ids = {
            player_id for roster in self.management.rosters for player_id in roster.player_ids
        } | set(self.management.free_agent_ids)
        if not governed_ids <= set(player_ids):
            raise ValueError("manager league management references unknown players")
        team_ids = {roster.team_id for roster in self.management.rosters}
        if any(
            pick.original_team_id not in team_ids or pick.owner_team_id not in team_ids
            for pick in self.draft_assets.picks
        ):
            raise ValueError("manager league draft picks reference unknown teams")
        if any(
            swap.controller_team_id not in team_ids or swap.target_original_team_id not in team_ids
            for swap in self.draft_assets.swaps
        ):
            raise ValueError("manager league draft swaps reference unknown teams")
        if any(item.team_id not in team_ids for item in self.cap_ledger.bird_rights) or any(
            item.team_id not in team_ids for item in self.cap_ledger.trade_exceptions
        ):
            raise ValueError("manager league cap ledger references unknown teams")
        if self.manager_learning != tuple(
            sorted(self.manager_learning, key=lambda item: item.team_id)
        ) or any(item.team_id not in team_ids for item in self.manager_learning):
            raise ValueError("manager learning states must be ordered and reference league teams")
        if len({item.team_id for item in self.manager_learning}) != len(self.manager_learning):
            raise ValueError("manager learning states must have unique teams")
        if self.nba_alignment is not None and (
            set(self.nba_alignment.east_team_ids) | set(self.nba_alignment.west_team_ids)
            != team_ids
        ):
            raise ValueError("NBA alignment must cover every league team exactly")


@dataclass(frozen=True, slots=True)
class CourtSimManagerLeagueAdapter:
    parameters: ModelParameters
    game_config: GameClockConfig
    manager_profiles: tuple[ManagerProfile, ...]
    career_rules: CareerRules = field(default_factory=CareerRules)
    draft_rules: DraftRules = field(default_factory=DraftRules)
    lottery_rules: DraftLotteryRules = field(default_factory=DraftLotteryRules)
    season_config: SeasonConfig = field(default_factory=SeasonConfig)
    fatigue_config: FatigueConfig = field(default_factory=FatigueConfig)
    game_rules: GameRules = field(default_factory=GameRules)
    playoff_config: PlayoffConfig = field(default_factory=lambda: PlayoffConfig(1, (True,)))
    prospect_rules: ProspectGenerationRules = field(default_factory=ProspectGenerationRules)
    rotation_rules: ManagerRotationRules = field(default_factory=ManagerRotationRules)
    trade_rules: TradeRules = field(default_factory=TradeRules)
    manager_trade_rules: ManagerTradeRules = field(default_factory=ManagerTradeRules)
    trade_market_rules: TradeMarketRules = field(default_factory=TradeMarketRules)
    three_team_market_rules: ThreeTeamMarketRules = field(default_factory=ThreeTeamMarketRules)
    scouting_rules: ScoutingRules = field(default_factory=ScoutingRules)
    games_per_pair: int = 2
    trace_mode: TraceMode = TraceMode.AGGREGATE_ONLY
    version: str = MANAGER_LEAGUE_ADAPTER_VERSION
    postseason_rest_days: int = 2
    playoff_game_rest_days: int = 1
    playoff_round_rest_days: int = 2

    def __post_init__(self) -> None:
        if self.version != MANAGER_LEAGUE_ADAPTER_VERSION:
            raise ValueError("unsupported manager league adapter version")
        if (
            not isinstance(self.games_per_pair, int)
            or isinstance(self.games_per_pair, bool)
            or self.games_per_pair < 1
        ):
            raise ValueError("games_per_pair must be a positive integer")
        rest_values = (
            self.postseason_rest_days,
            self.playoff_game_rest_days,
            self.playoff_round_rest_days,
        )
        if any(
            not isinstance(value, int) or isinstance(value, bool) or value < 0
            for value in rest_values
        ):
            raise ValueError("postseason rest days must be non-negative integers")
        if len(self.manager_profiles) != 4:
            raise ValueError("manager league adapter v1 requires exactly four teams")
        team_ids = tuple(profile.team_id for profile in self.manager_profiles)
        if team_ids != tuple(sorted(set(team_ids))):
            raise ValueError("manager profiles must be ordered by unique team_id")
        if not self.game_config.overtime_enabled:
            raise ValueError("manager league playoff games require overtime")

    def __call__(self, request: ManagerSeasonRequest) -> ManagerSeasonExecution:
        state = league_state_from_json(request.state_payload)
        state, prospect_audit = _ensure_annual_prospects(
            state,
            request=request,
            rules=self.prospect_rules,
        )
        state = _ensure_future_draft_assets(
            state,
            draft_rules=self.draft_rules,
        )
        if (
            not state.contract_rules.minimum_salary
            <= self.draft_rules.rookie_salary
            <= state.contract_rules.maximum_salary
            or self.draft_rules.rookie_contract_years > state.contract_rules.maximum_years
        ):
            raise ManagerLeagueAdapterError("draft rules are incompatible with league contracts")
        if state.management.season_year != request.season_year:
            raise ManagerLeagueAdapterError("league state season does not match experiment request")
        team_ids = tuple(roster.team_id for roster in state.management.rosters)
        cap_rules = cap_rules_for_salary_cap(state.contract_rules.salary_cap)
        profiles = {profile.team_id: profile for profile in self.manager_profiles}
        if team_ids != tuple(profiles):
            raise ManagerLeagueAdapterError("league state teams do not match manager profiles")

        trade_audit: dict[str, object] | None = None
        three_team_audit: dict[str, object] | None = None
        trade_clearing_choice: str | None = None
        trade_ledger: dict[str, object] | None = None
        three_team_ledger: dict[str, object] | None = None
        trade_recommendations = 0
        if request.arm is ManagerExperimentArm.SHADOW:
            trade_shadow = generate_trade_market_shadow(
                management=state.management,
                players=state.players,
                picks=state.draft_assets.picks,
                profiles=profiles,
                contract_rules=state.contract_rules,
                trade_rules=self.trade_rules,
                manager_rules=self.manager_trade_rules,
                market_rules=self.trade_market_rules,
            )
            three_team_shadow = generate_three_team_market_shadow(
                management=state.management,
                players=state.players,
                picks=state.draft_assets.picks,
                profiles=profiles,
                contract_rules=state.contract_rules,
                trade_rules=self.trade_rules,
                manager_rules=self.manager_trade_rules,
                market_rules=self.three_team_market_rules,
            )
            bilateral_gain = _selected_bilateral_gain(trade_shadow)
            three_team_gain = _selected_three_team_gain(three_team_shadow)
            choose_three_team = (
                bool(three_team_shadow.plan.offers) and three_team_gain > bilateral_gain
            )
            bilateral_plan = TradeMarketPlan(()) if choose_three_team else trade_shadow.plan
            three_team_plan = (
                three_team_shadow.plan if choose_three_team else ThreeTeamMarketPlan(())
            )
            trade_recommendations = len(bilateral_plan.offers) + len(three_team_plan.offers)
            trade_execution = apply_trade_market_plan(
                state.management,
                state.draft_assets.picks,
                bilateral_plan,
                state.contract_rules,
                self.trade_rules,
                cap_ledger=state.cap_ledger,
                cap_rules=cap_rules,
            )
            three_team_execution = apply_three_team_market_plan(
                trade_execution.final_management,
                trade_execution.final_picks,
                three_team_plan,
                state.contract_rules,
                self.trade_rules,
                cap_ledger=trade_execution.final_cap_ledger,
                cap_rules=cap_rules,
            )
            state = replace(
                state,
                management=three_team_execution.final_management,
                cap_ledger=three_team_execution.final_cap_ledger or state.cap_ledger,
                draft_assets=replace(
                    state.draft_assets,
                    picks=cast(
                        tuple[FutureDraftPickAsset, ...],
                        three_team_execution.final_picks,
                    ),
                ),
            )
            trade_audit = _trade_market_audit(trade_shadow, trade_execution)
            three_team_audit = _three_team_market_audit(
                three_team_shadow,
                three_team_execution,
            )
            trade_clearing_choice = (
                "three-team"
                if choose_three_team
                else "bilateral"
                if bilateral_plan.offers
                else "none"
            )
            trade_ledger = asdict(trade_shadow.ledger)
            three_team_ledger = asdict(three_team_shadow.ledger)

        teams, rotation_audit, matchup_teams = _game_teams(
            state,
            profiles,
            self.game_config,
            self.rotation_rules,
        )
        schedule = _round_robin_schedule(team_ids, self.games_per_pair)
        season_seed = derive_seed(
            request.master_seed,
            MANAGER_LEAGUE_ADAPTER_VERSION,
            request.season_year,
            "season",
        )
        frame = RandomFrame(
            season_seed,
            RandomFrameAddress(request.source_id, 0, 0, 0, 0),
        )
        roster_rules = RosterRules(5, state.contract_rules.maximum_roster_players)
        season = sample_season(
            parameters=self.parameters,
            game_config=self.game_config,
            schedule=schedule,
            teams=teams,
            frame=frame,
            rules=self.game_rules,
            fatigue_config=self.fatigue_config,
            season_config=self.season_config,
            roster_rules=roster_rules,
            trace_mode=self.trace_mode,
            team_resolver=lambda scheduled, _: (
                matchup_teams[(scheduled.home_team_id, scheduled.away_team_id)],
                matchup_teams[(scheduled.away_team_id, scheduled.home_team_id)],
            ),
        )
        postseason = _sample_playoffs(
            season,
            teams,
            matchup_teams=matchup_teams,
            request=request,
            parameters=self.parameters,
            game_config=self.game_config,
            rules=self.game_rules,
            fatigue_config=self.fatigue_config,
            season_config=self.season_config,
            config=self.playoff_config,
            trace_mode=self.trace_mode,
            postseason_rest_days=self.postseason_rest_days,
            game_rest_days=self.playoff_game_rest_days,
            round_rest_days=self.playoff_round_rest_days,
        )
        playoffs = postseason.result
        summaries = _season_summaries(season, state.players, postseason)
        offseason_seed = derive_seed(
            request.master_seed,
            MANAGER_LEAGUE_ADAPTER_VERSION,
            request.season_year,
            "offseason",
        )
        draft_settlement, draft_lottery = _draft_asset_settlement(
            season,
            state,
            summaries,
            master_seed=offseason_seed,
            career_rules=self.career_rules,
            draft_rules=self.draft_rules,
            lottery_rules=self.lottery_rules,
        )
        picks = draft_settlement.picks
        draft_plan, market_plan, manager_audit, offseason_authority = _offseason_plans(
            state,
            summaries,
            profiles,
            picks,
            arm=request.arm,
            master_seed=offseason_seed,
            career_rules=self.career_rules,
            draft_rules=self.draft_rules,
            scouting_rules=self.scouting_rules,
            cap_ledger=state.cap_ledger,
            cap_rules=cap_rules,
        )
        if trade_ledger is not None:
            manager_audit["trade"] = trade_ledger
        if three_team_ledger is not None:
            manager_audit["three_team_trade"] = three_team_ledger
        offseason = advance_offseason(
            season_year=request.season_year,
            master_seed=offseason_seed,
            management=state.management,
            players=state.players,
            summaries=summaries,
            picks=picks,
            draft_plan=draft_plan,
            market_plan=market_plan,
            career_rules=self.career_rules,
            contract_rules=state.contract_rules,
            draft_rules=self.draft_rules,
            cap_ledger=state.cap_ledger,
            cap_rules=cap_rules,
        )
        next_learning = _advance_manager_learning(
            season,
            state.manager_learning,
            profiles,
            self.game_config,
            completed_season=request.season_year,
        )
        next_state = CourtSimLeagueState(
            state.contract_rules,
            offseason.final_management,
            offseason.final_players,
            draft_settlement.final_ledger,
            expire_cap_ledger(
                state.cap_ledger,
                season_year=offseason.final_management.season_year,
            ),
            next_learning,
            state.nba_alignment,
        )
        metrics = _manager_metrics(season, playoffs, next_state)
        authority_policy = default_manager_authority_policy()
        isolated_shadow = request.arm is ManagerExperimentArm.SHADOW
        tactical_recommendations = sum(
            matchup["tactics"] is not None
            for team in rotation_audit.values()
            for matchup in cast(
                dict[str, dict[str, object]],
                cast(dict[str, object], team)["opponents"],
            ).values()
        )
        authority_receipts = (
            manager_execution_receipt(
                authority_policy,
                ManagerDecisionStage.DRAFT,
                evaluated=bool(offseason_authority["draft_evaluated"]),
                recommendation_count=int(offseason_authority["draft_recommendations"]),
                executed_count=int(offseason_authority["draft_executed"]),
                isolated_shadow=isolated_shadow,
            ),
            manager_execution_receipt(
                authority_policy,
                ManagerDecisionStage.FREE_AGENCY,
                evaluated=bool(offseason_authority["market_evaluated"]),
                recommendation_count=int(offseason_authority["market_recommendations"]),
                executed_count=int(offseason_authority["market_executed"]),
                isolated_shadow=isolated_shadow,
            ),
            manager_execution_receipt(
                authority_policy,
                ManagerDecisionStage.TRADE,
                evaluated=isolated_shadow,
                recommendation_count=trade_recommendations,
                executed_count=trade_recommendations,
                isolated_shadow=isolated_shadow,
            ),
            manager_execution_receipt(
                authority_policy,
                ManagerDecisionStage.ROTATION,
                evaluated=True,
                recommendation_count=len(teams),
                executed_count=len(teams),
            ),
            manager_execution_receipt(
                authority_policy,
                ManagerDecisionStage.TACTICS,
                evaluated=True,
                recommendation_count=tactical_recommendations,
                executed_count=tactical_recommendations,
            ),
        )
        audit = {
            "adapter_version": self.version,
            "arm": request.arm.name.lower(),
            "manager_authority": manager_authority_to_dict(
                authority_policy,
                authority_receipts,
            ),
            "season": season_result_to_dict(season),
            "playoffs": playoff_result_to_dict(playoffs),
            "postseason_continuity": _postseason_audit(postseason),
            "offseason": offseason_result_to_dict(offseason),
            "manager_decisions": manager_audit,
            "prospect_class": prospect_audit,
            "rotations": rotation_audit,
            "trade_market": trade_audit,
            "three_team_market": three_team_audit,
            "trade_clearing_choice": trade_clearing_choice,
            "manager_learning": [manager_learning_to_dict(item) for item in next_learning],
            "draft_assets": asdict(draft_settlement),
            "draft_lottery": asdict(draft_lottery),
        }
        return ManagerSeasonExecution(
            league_state_to_json(next_state),
            metrics,
            json.dumps(audit, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        )


def _trade_market_audit(
    shadow: TradeMarketShadowResult,
    execution: TradeMarketExecution,
) -> dict[str, object]:
    return {
        "version": shadow.version,
        "candidate_count": len(shadow.evaluations),
        "approved_candidate_count": sum(
            evaluation.shadow.approved for evaluation in shadow.evaluations
        ),
        "selected_offers": [asdict(offer) for offer in execution.plan.offers],
        "evaluations": [
            {
                "kind": evaluation.kind,
                "parent_trade_id": evaluation.parent_trade_id,
                "offer": asdict(evaluation.shadow.offer),
                "legal": evaluation.shadow.legal,
                "approved": evaluation.shadow.approved,
                "hard_rejections": list(evaluation.shadow.hard_rejections),
                "approvals": [
                    {
                        "team_id": approval.team_id,
                        "manager_id": approval.manager_id,
                        "accepted": approval.accepted,
                        "rational_gain": approval.rational_gain,
                    }
                    for approval in evaluation.shadow.approvals
                ],
            }
            for evaluation in shadow.evaluations
        ],
        "execution_audits": [asdict(audit) for audit in execution.audits],
    }


def _three_team_market_audit(
    shadow: ThreeTeamMarketShadowResult,
    execution: ThreeTeamMarketExecution,
) -> dict[str, object]:
    return {
        "version": shadow.version,
        "candidate_count": len(shadow.evaluations),
        "approved_candidate_count": sum(
            evaluation.shadow.approved for evaluation in shadow.evaluations
        ),
        "selected_offers": [asdict(offer) for offer in execution.plan.offers],
        "evaluations": [
            {
                "kind": evaluation.kind,
                "parent_trade_id": evaluation.parent_trade_id,
                "negotiation_round": evaluation.negotiation_round,
                "salary_imbalance": evaluation.salary_imbalance,
                "offer": asdict(evaluation.shadow.offer),
                "legal": evaluation.shadow.legal,
                "approved": evaluation.shadow.approved,
                "hard_rejections": list(evaluation.shadow.hard_rejections),
                "approvals": [
                    {
                        "team_id": approval.team_id,
                        "manager_id": approval.manager_id,
                        "accepted": approval.accepted,
                        "rational_gain": approval.rational_gain,
                    }
                    for approval in evaluation.shadow.approvals
                ],
            }
            for evaluation in shadow.evaluations
        ],
        "execution_audits": [asdict(audit) for audit in execution.audits],
    }


def _selected_bilateral_gain(shadow: TradeMarketShadowResult) -> float:
    selected = {offer.trade_id for offer in shadow.plan.offers}
    return sum(
        sum(approval.rational_gain or 0.0 for approval in evaluation.shadow.approvals)
        for evaluation in shadow.evaluations
        if evaluation.shadow.offer.trade_id in selected
    )


def _selected_three_team_gain(shadow: ThreeTeamMarketShadowResult) -> float:
    selected = {offer.trade_id for offer in shadow.plan.offers}
    return sum(
        three_team_shadow_gain(evaluation.shadow)
        for evaluation in shadow.evaluations
        if evaluation.shadow.offer.trade_id in selected
    )


def league_state_to_json(state: CourtSimLeagueState) -> str:
    management = market_result_to_dict(
        MarketResult(
            state.contract_rules,
            state.management,
            (),
            state.management,
        )
    )
    payload = {
        "schema_version": 4,
        "version": state.version,
        "management": management,
        "players": [_career_player_to_dict(player) for player in state.players],
        "draft_assets": draft_asset_ledger_to_dict(state.draft_assets),
        "cap_ledger": cap_ledger_to_dict(state.cap_ledger),
        "manager_learning": [manager_learning_to_dict(item) for item in state.manager_learning],
        "nba_alignment": (
            nba_alignment_to_dict(state.nba_alignment) if state.nba_alignment is not None else None
        ),
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def league_state_from_json(payload: str) -> CourtSimLeagueState:
    try:
        value: object = json.loads(payload)
        raw = _object(value, "manager league state")
        schema_version = raw.get("schema_version")
        if schema_version == 1:
            expected_keys = {"schema_version", "version", "management", "players"}
        elif schema_version == 2:
            expected_keys = {
                "schema_version",
                "version",
                "management",
                "players",
                "draft_assets",
            }
        else:
            expected_keys = {
                "schema_version",
                "version",
                "management",
                "players",
                "draft_assets",
                "cap_ledger",
                "manager_learning",
                "nba_alignment",
            }
        _exact(raw, expected_keys, "manager league state")
        if schema_version not in {1, 2, 3, 4} or raw["version"] != MANAGER_LEAGUE_ADAPTER_VERSION:
            raise ManagerLeagueAdapterError("unsupported manager league state")
        management_envelope = _object(raw["management"], "manager league management")
        management_rules = _object(
            management_envelope.get("rules"),
            "manager league contract rules",
        )
        salary_cap = management_rules.get("salary_cap")
        if not isinstance(salary_cap, int) or isinstance(salary_cap, bool) or salary_cap < 1:
            raise ManagerLeagueAdapterError("manager league salary cap is invalid")
        market = market_result_from_dict(
            raw["management"],
            maximum_payroll=cap_rules_for_salary_cap(salary_cap).second_apron,
        )
        if market.actions or market.initial_state != market.final_state:
            raise ManagerLeagueAdapterError("manager league management envelope is not a snapshot")
        raw_players = raw["players"]
        if not isinstance(raw_players, list):
            raise ManagerLeagueAdapterError("manager league players must be a list")
        players = tuple(_career_player_from_dict(item) for item in raw_players)
        draft_assets = (
            DraftAssetLedger()
            if schema_version == 1
            else draft_asset_ledger_from_dict(raw["draft_assets"])
        )
        cap_ledger = (
            cap_ledger_from_dict(raw["cap_ledger"]) if schema_version in {3, 4} else CapLedger()
        )
        if schema_version in {3, 4}:
            learning_raw = raw["manager_learning"]
            if not isinstance(learning_raw, list):
                raise ManagerLeagueAdapterError("manager learning must be a list")
            manager_learning = tuple(manager_learning_from_dict(item) for item in learning_raw)
            alignment_raw = raw["nba_alignment"]
            nba_alignment = (
                nba_alignment_from_dict(alignment_raw) if alignment_raw is not None else None
            )
        else:
            manager_learning = ()
            nba_alignment = None
        return CourtSimLeagueState(
            market.rules,
            market.final_state,
            players,
            draft_assets,
            cap_ledger,
            manager_learning,
            nba_alignment,
        )
    except (KeyError, TypeError, ValueError) as error:
        if isinstance(error, ManagerLeagueAdapterError):
            raise
        raise ManagerLeagueAdapterError(f"invalid manager league state: {error}") from error


def _ensure_annual_prospects(
    state: CourtSimLeagueState,
    *,
    request: ManagerSeasonRequest,
    rules: ProspectGenerationRules,
) -> tuple[CourtSimLeagueState, dict[str, object] | None]:
    prospects = tuple(player for player in state.players if player.status is CareerStatus.PROSPECT)
    if len(prospects) >= rules.class_size:
        return state, None
    if prospects:
        raise ManagerLeagueAdapterError(
            "league contains an incomplete prospect class; supply zero or a full class"
        )
    templates = tuple(
        player.profile for player in state.players if player.status is CareerStatus.ACTIVE
    )
    generated = generate_prospect_class(
        draft_year=request.season_year + 1,
        master_seed=derive_seed(
            request.master_seed,
            MANAGER_LEAGUE_ADAPTER_VERSION,
            request.season_year,
            "prospect-class",
        ),
        templates=templates,
        existing_player_ids=frozenset(player.player_id for player in state.players),
        rules=rules,
    )
    updated = replace(
        state,
        players=tuple(
            sorted((*state.players, *generated.players), key=lambda item: item.player_id)
        ),
    )
    return updated, prospect_class_to_dict(generated)


def _ensure_future_draft_assets(
    state: CourtSimLeagueState,
    *,
    draft_rules: DraftRules,
) -> CourtSimLeagueState:
    team_ids = tuple(roster.team_id for roster in state.management.rosters)
    first_draft_year = state.management.season_year + 1
    ledger = seed_future_draft_picks(
        state.draft_assets,
        team_ids=team_ids,
        draft_years=tuple(range(first_draft_year, first_draft_year + 3)),
        rounds=draft_rules.rounds,
    )
    return replace(state, draft_assets=ledger)


def _round_robin_schedule(
    team_ids: tuple[str, ...],
    games_per_pair: int,
) -> SeasonSchedule:
    games: list[ScheduledGame] = []
    game_id = 0
    day = 1
    for meeting in range(games_per_pair):
        for first_index, first in enumerate(team_ids):
            for second in team_ids[first_index + 1 :]:
                home, away = (first, second) if meeting % 2 == 0 else (second, first)
                games.append(ScheduledGame(game_id, day, home, away))
                game_id += 1
                day += 1
    return SeasonSchedule(team_ids, tuple(games))


def _advance_manager_learning(
    season: SeasonResult,
    existing: tuple[ManagerLearningState, ...],
    profiles: dict[str, ManagerProfile],
    game_config: GameClockConfig,
    *,
    completed_season: int,
) -> tuple[ManagerLearningState, ...]:
    existing_by_team = {item.team_id: item for item in existing}
    result = []
    for team_id in sorted(profiles):
        totals: dict[str, list[int]] = defaultdict(lambda: [0] * 8)
        for record in season.games:
            scheduled = record.scheduled_game
            if scheduled.home_team_id == team_id:
                opponent = scheduled.away_team_id
                team_points, opponent_points = record.home_score, record.away_score
            elif scheduled.away_team_id == team_id:
                opponent = scheduled.home_team_id
                team_points, opponent_points = record.away_score, record.home_score
            else:
                continue
            totals[opponent][0] += 1
            totals[opponent][1] += opponent_points
            totals[opponent][2] += team_points
            if record.result is None:
                continue
            for possession in record.result.possessions:
                offense_index = 3 if possession.offense_team_id == opponent else 4
                totals[opponent][offense_index] += 1
                if possession.offense_team_id != opponent:
                    continue
                for segment in possession.result.segments:
                    if not isinstance(
                        segment,
                        (
                            MadeShotSegmentResult,
                            MissedShotSegmentResult,
                            BlockedShotSegmentResult,
                            ShootingFoulSegmentResult,
                        ),
                    ):
                        continue
                    totals[opponent][5] += 1
                    totals[opponent][6] += segment.zone is ShotZone.THREE
                    totals[opponent][7] += segment.zone is ShotZone.RIM
        observations = tuple(
            _opponent_observation(opponent, values, game_config)
            for opponent, values in sorted(totals.items())
        )
        profile = profiles[team_id]
        prior = existing_by_team.get(
            team_id,
            ManagerLearningState(
                profile.manager_id,
                team_id,
                completed_season - 1,
            ),
        )
        if prior.manager_id != profile.manager_id:
            prior = ManagerLearningState(
                profile.manager_id,
                team_id,
                completed_season - 1,
            )
        result.append(
            update_manager_learning(
                prior,
                observations,
                completed_season=completed_season,
            )
        )
    return tuple(result)


def _opponent_observation(
    opponent_team_id: str,
    totals: list[int],
    game_config: GameClockConfig,
) -> OpponentObservation:
    (
        games,
        opponent_points,
        team_points,
        opponent_possessions,
        team_possessions,
        opponent_shots,
        opponent_threes,
        opponent_rim_shots,
    ) = totals
    reference_possessions = (
        game_config.regulation_periods
        * game_config.period_seconds
        / (2 * game_config.possession_seconds)
    )
    possessions_per_game = opponent_possessions / max(1, games)
    return OpponentObservation(
        opponent_team_id,
        games,
        _bounded_rating(round(opponent_points * 50 / max(1, opponent_possessions))),
        _bounded_rating(100 - round(team_points * 50 / max(1, team_possessions))),
        _bounded_rating(round(50 * possessions_per_game / reference_possessions)),
        _percentage(opponent_threes, opponent_shots),
        _percentage(opponent_rim_shots, opponent_shots),
    )


def _percentage(part: int, whole: int) -> int:
    return 50 if whole == 0 else _bounded_rating(round(part * 100 / whole))


def _bounded_rating(value: int) -> int:
    return max(0, min(100, value))


def _game_teams(
    state: CourtSimLeagueState,
    manager_profiles: dict[str, ManagerProfile],
    game_config: GameClockConfig,
    rotation_rules: ManagerRotationRules,
) -> tuple[
    tuple[GameTeam, ...],
    dict[str, object],
    dict[tuple[str, str], GameTeam],
]:
    player_map = {player.player_id: player for player in state.players}
    teams: list[GameTeam] = []
    audit: dict[str, object] = {}
    matchup_teams: dict[tuple[str, str], GameTeam] = {}
    learning = {item.team_id: item for item in state.manager_learning}
    for roster in state.management.rosters:
        if len(roster.player_ids) < 5:
            raise ManagerLeagueAdapterError("league roster has fewer than five playable players")
        try:
            profiles = tuple(player_map[player_id].profile for player_id in roster.player_ids)
        except KeyError as error:
            raise ManagerLeagueAdapterError("league roster references an unknown player") from error
        career_roster = tuple(player_map[player_id] for player_id in roster.player_ids)
        base_rotation = generate_manager_rotation(
            team_id=roster.team_id,
            roster=career_roster,
            profile=manager_profiles[roster.team_id],
            game_config=game_config,
            rules=rotation_rules,
        )
        base_team = _game_team_from_rotation(roster.team_id, profiles, base_rotation)
        teams.append(base_team)
        opponent_audit: dict[str, object] = {}
        for opponent_team_id in sorted(
            team_id for team_id in manager_profiles if team_id != roster.team_id
        ):
            adjustment = (
                opponent_rotation_adjustment(
                    learning[roster.team_id],
                    opponent_team_id,
                )
                if roster.team_id in learning
                else None
            )
            tactical_adjustment = (
                opponent_tactical_adjustment(
                    learning[roster.team_id],
                    opponent_team_id,
                )
                if roster.team_id in learning
                else None
            )
            rotation = (
                base_rotation
                if adjustment is None
                else generate_manager_rotation(
                    team_id=roster.team_id,
                    roster=career_roster,
                    profile=manager_profiles[roster.team_id],
                    game_config=game_config,
                    rules=rotation_rules,
                    opponent_adjustment=adjustment,
                )
            )
            matchup_teams[(roster.team_id, opponent_team_id)] = _game_team_from_rotation(
                roster.team_id,
                profiles,
                rotation,
                tactical_adjustment=tactical_adjustment,
            )
            opponent_audit[opponent_team_id] = {
                "adjustment": asdict(adjustment) if adjustment is not None else None,
                "tactics": (
                    _tactical_adjustment_to_dict(tactical_adjustment)
                    if tactical_adjustment is not None
                    else None
                ),
                "rotation": asdict(rotation),
            }
        audit[roster.team_id] = {
            "base": asdict(base_rotation),
            "opponents": opponent_audit,
        }
    return tuple(teams), audit, matchup_teams


def _game_team_from_rotation(
    team_id: str,
    profiles: tuple[PlayerProfile, ...],
    rotation: ManagerRotationResult,
    *,
    tactical_adjustment: OpponentTacticalAdjustment | None = None,
) -> GameTeam:
    profile_map = {profile.player_id: profile for profile in profiles}
    lineup = rotation.lineup
    active = cast(
        ProfileLineup,
        tuple(profile_map[player_id] for player_id in lineup),
    )
    bench = tuple(
        profile_map[player_id]
        for player_id in rotation.substitution_order
        if player_id not in lineup
    )
    offense_strategy = TeamOffenseStrategy()
    defense_strategy = TeamDefenseStrategy()
    tempo_strategy = TeamTempoStrategy()
    if tactical_adjustment is not None:
        offense_strategy = TeamOffenseStrategy(tactical_adjustment.play_family_logit_biases)
        defense_strategy = TeamDefenseStrategy(tactical_adjustment.coverage_logit_biases)
        tempo_strategy = TeamTempoStrategy(50 + tactical_adjustment.tempo_delta)
    return GameTeam(
        team_id,
        lineup,
        active,
        offense_strategy=offense_strategy,
        defense_strategy=defense_strategy,
        tempo_strategy=tempo_strategy,
        bench_profiles=bench,
        substitution_order=rotation.substitution_order,
        rotation_plan=rotation.plan,
    )


def _tactical_adjustment_to_dict(
    adjustment: OpponentTacticalAdjustment,
) -> dict[str, object]:
    return {
        "opponent_team_id": adjustment.opponent_team_id,
        "play_family_logit_biases": {
            PlayFamily(key).name: value for key, value in adjustment.play_family_logit_biases
        },
        "coverage_logit_biases": {
            Coverage(key).name: value for key, value in adjustment.coverage_logit_biases
        },
        "tempo_delta": adjustment.tempo_delta,
        "effective_tempo": 50 + adjustment.tempo_delta,
        "confidence_bps": adjustment.confidence_bps,
        "matchup_net_rating": adjustment.matchup_net_rating,
        "response_multiplier_bps": adjustment.response_multiplier_bps,
        "games_observed": adjustment.games_observed,
        "version": adjustment.version,
    }


def _matchups(home: GameTeam, away: GameTeam) -> GameMatchups:
    return GameMatchups(
        DefensiveMatchups(
            cast(
                tuple[Matchup, Matchup, Matchup, Matchup, Matchup],
                tuple(
                    Matchup(offender, defender)
                    for offender, defender in zip(home.lineup, away.lineup, strict=True)
                ),
            )
        ),
        DefensiveMatchups(
            cast(
                tuple[Matchup, Matchup, Matchup, Matchup, Matchup],
                tuple(
                    Matchup(offender, defender)
                    for offender, defender in zip(away.lineup, home.lineup, strict=True)
                ),
            )
        ),
    )


def _sample_playoffs(
    season: SeasonResult,
    teams: tuple[GameTeam, ...],
    *,
    matchup_teams: dict[tuple[str, str], GameTeam],
    request: ManagerSeasonRequest,
    parameters: ModelParameters,
    game_config: GameClockConfig,
    rules: GameRules,
    fatigue_config: FatigueConfig,
    season_config: SeasonConfig,
    config: PlayoffConfig,
    trace_mode: TraceMode,
    postseason_rest_days: int,
    game_rest_days: int,
    round_rest_days: int,
) -> PostseasonSimulation:
    seeds = tuple(
        PlayoffSeed(index, standing.team_id)
        for index, standing in enumerate(season.standings[:4], start=1)
    )
    team_map = {team.team_id: team for team in teams}
    games: list[PlayoffGame] = []
    state_games: list[PostseasonGameState] = []
    injuries: list[InjuryRecord] = []
    states = {(state.team_id, state.player_id): state for state in season.final_player_states}
    initial_states = tuple(states[key] for key in sorted(states))
    regular_end_by_team = {
        team_id: max(
            game.day
            for game in season.schedule.games
            if team_id in {game.home_team_id, game.away_team_id}
        )
        for team_id in season.schedule.team_ids
    }
    state_day = {
        (team.team_id, player_id): regular_end_by_team[team.team_id]
        for team in teams
        for player_id in team.roster_order
    }
    player_seconds: dict[int, int] = defaultdict(int)
    player_games: dict[int, int] = defaultdict(int)
    team_games: dict[str, int] = defaultdict(int)

    def available_team(
        original: GameTeam,
        day: int,
    ) -> tuple[GameTeam | None, tuple[int, ...]]:
        for player_id in original.roster_order:
            key = (original.team_id, player_id)
            state = states[key]
            rest_days = max(0, day - state_day[key] - 1)
            states[key] = replace(
                state,
                fatigue=max(
                    0,
                    state.fatigue - rest_days * season_config.daily_fatigue_recovery,
                ),
                unavailable_until_day=(
                    0
                    if state.unavailable_until_day and day >= state.unavailable_until_day
                    else state.unavailable_until_day
                ),
            )
            state_day[key] = day
        unavailable = tuple(
            player_id
            for player_id in original.roster_order
            if day < states[(original.team_id, player_id)].unavailable_until_day
        )
        return available_game_team(original, frozenset(unavailable)), unavailable

    def series(
        round_number: int,
        series_index: int,
        first: PlayoffSeed,
        second: PlayoffSeed,
        start_day: int,
    ) -> tuple[PlayoffSeed, int]:
        higher, lower = (first, second) if first.seed < second.seed else (second, first)
        wins = {higher.team_id: 0, lower.team_id: 0}
        game_number = 1
        day = start_day
        while max(wins.values()) < config.wins_required:
            home_seed = higher if config.higher_seed_home[game_number - 1] else lower
            away_seed = lower if home_seed is higher else higher
            original_home = matchup_teams.get(
                (home_seed.team_id, away_seed.team_id),
                team_map[home_seed.team_id],
            )
            original_away = matchup_teams.get(
                (away_seed.team_id, home_seed.team_id),
                team_map[away_seed.team_id],
            )
            home, home_unavailable = available_team(original_home, day)
            away, away_unavailable = available_team(original_away, day)
            game_seed = derive_seed(
                request.master_seed,
                MANAGER_LEAGUE_ADAPTER_VERSION,
                request.season_year,
                "playoff",
                round_number,
                series_index,
                game_number,
            )
            initial_fatigue: dict[int, int] = {}
            game_participants: tuple[int, ...] = ()
            forfeit_team_id = None
            if home is None or away is None:
                if home is None and away is not None:
                    home_score, away_score = 0, season_config.forfeit_score
                    forfeit_team_id = original_home.team_id
                elif away is None and (
                    home is not None or derive_seed(game_seed, "double-forfeit") % 2
                ):
                    home_score, away_score = season_config.forfeit_score, 0
                    forfeit_team_id = original_away.team_id
                else:
                    home_score, away_score = 0, season_config.forfeit_score
                    forfeit_team_id = original_home.team_id
            else:
                initial_fatigue = {
                    player_id: states[(team.team_id, player_id)].fatigue
                    for team in (home, away)
                    for player_id in team.roster_order
                }
                sampled = sample_game(
                    parameters=parameters,
                    config=game_config,
                    home=home,
                    away=away,
                    matchups=_matchups(home, away),
                    frame=RandomFrame(
                        game_seed,
                        RandomFrameAddress(
                            request.source_id,
                            0,
                            len(games),
                            0,
                            0,
                        ),
                    ),
                    rules=rules,
                    fatigue_config=fatigue_config,
                    initial_fatigue=initial_fatigue,
                    trace_mode=trace_mode,
                )
                home_score = sampled.result.home_score
                away_score = sampled.result.away_score
                for snapshot in sampled.result.final_fatigue:
                    team_id = (
                        home.team_id if snapshot.player_id in home.roster_order else away.team_id
                    )
                    key = (team_id, snapshot.player_id)
                    states[key] = replace(states[key], fatigue=snapshot.fatigue)
                for playing_time in sampled.result.playing_time:
                    player_seconds[playing_time.player_id] += playing_time.seconds
                    if playing_time.seconds > 0:
                        player_games[playing_time.player_id] += 1
                game_participants = tuple(
                    item.player_id for item in sampled.result.playing_time if item.seconds > 0
                )
                playoff_game_id = len(season.games) + len(games) + 1
                for team in (home, away):
                    for player_id in team.roster_order:
                        if player_id not in game_participants:
                            continue
                        roll = (
                            derive_seed(
                                request.master_seed,
                                INJURY_VERSION,
                                "postseason",
                                playoff_game_id,
                                player_id,
                                "roll",
                            )
                            % 10_000
                        )
                        if roll >= season_config.injury_probability_bps:
                            continue
                        span = season_config.maximum_days_out - season_config.minimum_days_out + 1
                        days_out = season_config.minimum_days_out + (
                            derive_seed(
                                request.master_seed,
                                INJURY_VERSION,
                                "postseason",
                                playoff_game_id,
                                player_id,
                                "duration",
                            )
                            % span
                        )
                        injury = InjuryRecord(
                            team.team_id,
                            player_id,
                            playoff_game_id,
                            day,
                            day + days_out + 1,
                        )
                        injuries.append(injury)
                        key = (team.team_id, player_id)
                        states[key] = replace(
                            states[key],
                            unavailable_until_day=injury.return_day,
                        )
            if home_score == away_score:
                if (
                    derive_seed(
                        game_seed,
                        MANAGER_LEAGUE_ADAPTER_VERSION,
                        "playoff-safety-tiebreak",
                    )
                    % 2
                ):
                    home_score += 1
                else:
                    away_score += 1
            game = PlayoffGame(
                round_number,
                series_index,
                game_number,
                original_home.team_id,
                original_away.team_id,
                home_score,
                away_score,
            )
            games.append(game)
            team_games[original_home.team_id] += 1
            team_games[original_away.team_id] += 1
            final_fatigue = tuple(
                states[(team.team_id, player_id)].fatigue
                for team in (original_home, original_away)
                for player_id in team.roster_order
            )
            state_games.append(
                PostseasonGameState(
                    round_number,
                    series_index,
                    game_number,
                    day,
                    original_home.team_id,
                    original_away.team_id,
                    home_unavailable,
                    away_unavailable,
                    forfeit_team_id,
                    max(initial_fatigue.values(), default=0),
                    max(final_fatigue, default=0),
                )
            )
            wins[game.winner_team_id] += 1
            game_number += 1
            day += game_rest_days + 1
        winner = higher if wins[higher.team_id] > wins[lower.team_id] else lower
        return winner, day - game_rest_days - 1

    regular_season_end = max(game.day for game in season.schedule.games)
    first_round_start = regular_season_end + postseason_rest_days + 1
    first, first_end = series(1, 1, seeds[0], seeds[3], first_round_start)
    second, second_end = series(1, 2, seeds[1], seeds[2], first_round_start)
    final_start = max(first_end, second_end) + round_rest_days + 1
    series(2, 1, first, second, final_start)
    result = resolve_playoffs(seeds=seeds, games=tuple(games), config=config)
    return PostseasonSimulation(
        result,
        initial_states,
        tuple(states[key] for key in sorted(states)),
        tuple(injuries),
        tuple(state_games),
        tuple(sorted(player_seconds.items())),
        tuple(sorted(player_games.items())),
        tuple(sorted(team_games.items())),
    )


def _postseason_audit(simulation: PostseasonSimulation) -> dict[str, object]:
    initial = {
        (state.team_id, state.player_id): state for state in simulation.initial_player_states
    }
    final = {(state.team_id, state.player_id): state for state in simulation.final_player_states}
    postseason_start_day = min(game.day for game in simulation.games)
    return {
        "initial_player_states": [asdict(state) for state in simulation.initial_player_states],
        "final_player_states": [asdict(state) for state in simulation.final_player_states],
        "games": [asdict(game) for game in simulation.games],
        "injuries": [asdict(injury) for injury in simulation.injuries],
        "player_seconds": dict(simulation.player_seconds),
        "player_games": dict(simulation.player_games),
        "team_games": dict(simulation.team_games),
        "players_with_fatigue_change": sum(
            initial[key].fatigue != final[key].fatigue for key in initial
        ),
        "regular_season_injuries_carried": sum(
            postseason_start_day < state.unavailable_until_day
            for state in simulation.initial_player_states
        ),
        "postseason_injuries": len(simulation.injuries),
    }


def _season_summaries(
    season: SeasonResult,
    players: tuple[CareerPlayer, ...],
    postseason: PostseasonSimulation | None = None,
) -> tuple[PlayerSeasonSummary, ...]:
    seconds: dict[int, int] = defaultdict(int)
    games_played: dict[int, int] = defaultdict(int)
    available_by_team = CounterSchedule(season.schedule)
    injury_days: dict[int, int] = defaultdict(int)
    for record in season.games:
        if record.result is None:
            continue
        for item in record.result.playing_time:
            seconds[item.player_id] += item.seconds
            if item.seconds > 0:
                games_played[item.player_id] += 1
    for injury in season.injuries:
        injury_days[injury.player_id] += max(0, injury.return_day - injury.injury_day - 1)
    postseason_team_games = dict(postseason.team_games) if postseason is not None else {}
    if postseason is not None:
        for player_id, value in postseason.player_seconds:
            seconds[player_id] += value
        for player_id, value in postseason.player_games:
            games_played[player_id] += value
        for injury in postseason.injuries:
            injury_days[injury.player_id] += max(
                0,
                injury.return_day - injury.injury_day - 1,
            )
    team_by_player = {
        player_id: roster.team_id
        for roster in season.initial_rosters
        for player_id in roster.player_ids
    }
    return tuple(
        PlayerSeasonSummary(
            player.player_id,
            available_by_team.games.get(team_by_player.get(player.player_id, ""), 0)
            + postseason_team_games.get(team_by_player.get(player.player_id, ""), 0),
            games_played[player.player_id],
            seconds[player.player_id],
            injury_days[player.player_id],
        )
        for player in players
        if player.status in {CareerStatus.ACTIVE, CareerStatus.FREE_AGENT}
    )


@dataclass(frozen=True, slots=True)
class CounterSchedule:
    games: dict[str, int]

    def __init__(self, schedule: SeasonSchedule) -> None:
        values: dict[str, int] = defaultdict(int)
        for game in schedule.games:
            values[game.home_team_id] += 1
            values[game.away_team_id] += 1
        object.__setattr__(self, "games", dict(values))


def _transition_preview(
    state: CourtSimLeagueState,
    summaries: tuple[PlayerSeasonSummary, ...],
    *,
    master_seed: int,
    career_rules: CareerRules,
) -> tuple[LeagueManagementState, tuple[CareerPlayer, ...]]:
    transition = advance_careers(
        state.players,
        summaries,
        season_year=state.management.season_year,
        master_seed=master_seed,
        rules=career_rules,
    )
    retired = set(transition.retired_player_ids)
    after_retirement = LeagueManagementState(
        state.management.season_year,
        tuple(
            RosterSnapshot(
                roster.team_id,
                tuple(player_id for player_id in roster.player_ids if player_id not in retired),
            )
            for roster in state.management.rosters
        ),
        tuple(
            player_id for player_id in state.management.free_agent_ids if player_id not in retired
        ),
        tuple(
            contract for contract in state.management.contracts if contract.player_id not in retired
        ),
    )
    contract_year = advance_contract_year(
        after_retirement,
        state.contract_rules,
        maximum_payroll=cap_rules_for_salary_cap(state.contract_rules.salary_cap).second_apron,
    )
    players = _sync_player_statuses(transition.final_players, contract_year.final_state)
    return contract_year.final_state, players


def _sync_player_statuses(
    players: tuple[CareerPlayer, ...],
    management: LeagueManagementState,
) -> tuple[CareerPlayer, ...]:
    active = {player_id for roster in management.rosters for player_id in roster.player_ids}
    free_agents = set(management.free_agent_ids)
    result: list[CareerPlayer] = []
    for player in players:
        if player.status in {CareerStatus.PROSPECT, CareerStatus.RETIRED}:
            result.append(player)
        elif player.player_id in active:
            result.append(replace(player, status=CareerStatus.ACTIVE))
        elif player.player_id in free_agents:
            result.append(replace(player, status=CareerStatus.FREE_AGENT))
        else:
            raise ManagerLeagueAdapterError("career player is absent from management preview")
    return tuple(result)


def _draft_asset_settlement(
    season: SeasonResult,
    state: CourtSimLeagueState,
    summaries: tuple[PlayerSeasonSummary, ...],
    *,
    master_seed: int,
    career_rules: CareerRules,
    draft_rules: DraftRules,
    lottery_rules: DraftLotteryRules,
) -> tuple[DraftAssetSettlement, DraftLotteryResult]:
    management, players = _transition_preview(
        state,
        summaries,
        master_seed=master_seed,
        career_rules=career_rules,
    )
    available = sum(player.status is CareerStatus.PROSPECT for player in players)
    standings = tuple(reversed(season.standings))
    base_order = tuple(standing.team_id for standing in standings)
    lottery = resolve_draft_lottery(
        draft_year=state.management.season_year + 1,
        master_seed=master_seed,
        base_order=base_order,
        rules=lottery_rules,
    )
    settlement = settle_draft_assets(
        state.draft_assets,
        draft_year=state.management.season_year + 1,
        original_team_order=base_order,
        first_round_order=lottery.final_order,
    )
    roster_sizes = {roster.team_id: len(roster.player_ids) for roster in management.rosters}
    payrolls = {roster.team_id: 0 for roster in management.rosters}
    for contract in management.contracts:
        payrolls[contract.team_id] += contract.annual_salary
    picks: list[DraftPickAsset] = []
    for pick in settlement.picks:
        if len(picks) >= available:
            break
        team_id = pick.owner_team_id
        if (
            roster_sizes[team_id] >= state.contract_rules.maximum_roster_players
            or payrolls[team_id] + draft_rules.rookie_salary > state.contract_rules.salary_cap
        ):
            continue
        picks.append(replace(pick, selection_number=len(picks) + 1))
        roster_sizes[team_id] += 1
        payrolls[team_id] += draft_rules.rookie_salary
    return replace(settlement, picks=tuple(picks)), lottery


def _offseason_plans(
    state: CourtSimLeagueState,
    summaries: tuple[PlayerSeasonSummary, ...],
    profiles: dict[str, ManagerProfile],
    picks: tuple[DraftPickAsset, ...],
    *,
    arm: ManagerExperimentArm,
    master_seed: int,
    career_rules: CareerRules,
    draft_rules: DraftRules,
    scouting_rules: ScoutingRules,
    cap_ledger: CapLedger,
    cap_rules: CapMechanicsRules,
) -> tuple[DraftPlan, MarketPlan, dict[str, object], dict[str, int | bool]]:
    management, players = _transition_preview(
        state,
        summaries,
        master_seed=master_seed,
        career_rules=career_rules,
    )
    decision_audit: dict[str, object] = {}
    authority: dict[str, int | bool] = {
        "draft_evaluated": False,
        "draft_recommendations": 0,
        "draft_executed": 0,
        "market_evaluated": False,
        "market_recommendations": 0,
        "market_executed": 0,
    }
    if arm is ManagerExperimentArm.SHADOW and picks:
        scouting_reports = generate_scouting_reports(
            prospects=tuple(player for player in players if player.status is CareerStatus.PROSPECT),
            scouts={team_id: profile.manager_id for team_id, profile in profiles.items()},
            master_seed=master_seed,
            rules=scouting_rules,
        )
        shadow_draft = generate_draft_shadow(
            management=management,
            players=players,
            picks=picks,
            profiles=profiles,
            contract_rules=state.contract_rules,
            rookie_salary=draft_rules.rookie_salary,
            scouted_potential={
                (report.team_id, report.player_id): report.estimated_potential
                for report in scouting_reports
            },
        )
        draft_plan = shadow_draft.plan
        authority["draft_evaluated"] = True
        authority["draft_recommendations"] = len(shadow_draft.plan.selections)
        authority["draft_executed"] = len(shadow_draft.plan.selections)
        decision_audit["draft"] = asdict(shadow_draft.ledger)
        decision_audit["scouting"] = scouting_reports_to_dict(scouting_reports)
    else:
        draft_plan = _incumbent_draft_plan(picks, players)
    drafted = apply_draft(
        management,
        players,
        picks,
        draft_plan,
        season_year=state.management.season_year + 1,
        contract_rules=state.contract_rules,
        draft_rules=draft_rules,
        maximum_payroll=cap_rules.second_apron,
    )
    if arm is ManagerExperimentArm.SHADOW:
        shadow_market = generate_market_shadow(
            management=drafted.final_management,
            players=drafted.final_players,
            profiles=profiles,
            contract_rules=state.contract_rules,
        )
        market_plan = _ensure_playable_market(
            drafted.final_management,
            drafted.final_players,
            state.contract_rules,
            shadow_market.plan,
            cap_ledger,
            cap_rules,
        )
        authority["market_evaluated"] = True
        authority["market_recommendations"] = len(shadow_market.plan.actions)
        authority["market_executed"] = len(shadow_market.plan.actions)
        decision_audit["market"] = asdict(shadow_market.ledger)
    else:
        market_plan = _ensure_playable_market(
            drafted.final_management,
            drafted.final_players,
            state.contract_rules,
            MarketPlan(()),
            cap_ledger,
            cap_rules,
        )
    return draft_plan, market_plan, decision_audit, authority


def _incumbent_draft_plan(
    picks: tuple[DraftPickAsset, ...],
    players: tuple[CareerPlayer, ...],
) -> DraftPlan:
    available = [player for player in players if player.status is CareerStatus.PROSPECT]
    available.sort(
        key=lambda player: (
            -_ability_mean(player.profile.abilities),
            -_ability_mean(player.potential),
            player.player_id,
        )
    )
    return DraftPlan(
        tuple(
            DraftSelection(pick.selection_number, pick.owner_team_id, player.player_id)
            for pick, player in zip(picks, available[: len(picks)], strict=True)
        )
    )


def _ensure_playable_market(
    management: LeagueManagementState,
    players: tuple[CareerPlayer, ...],
    rules: ContractRules,
    plan: MarketPlan,
    cap_ledger: CapLedger,
    cap_rules: CapMechanicsRules,
) -> MarketPlan:
    preview = apply_market_plan(
        management,
        plan,
        rules,
        cap_ledger=cap_ledger,
        cap_rules=cap_rules,
    ).final_state
    actions = list(plan.actions)
    available = set(preview.free_agent_ids)
    player_map = {player.player_id: player for player in players}
    next_action_id = max((action.action_id for action in actions), default=0) + 1
    for roster in preview.rosters:
        current = next(item for item in preview.rosters if item.team_id == roster.team_id)
        while len(current.player_ids) < 5:
            payroll = sum(
                contract.annual_salary
                for contract in preview.contracts
                if contract.team_id == roster.team_id
            )
            legal = [
                player_map[player_id]
                for player_id in available
                if payroll + rules.minimum_salary <= rules.salary_cap
            ]
            if not legal:
                raise ManagerLeagueAdapterError("free-agent pool cannot restore a playable roster")
            selected = max(
                legal,
                key=lambda player: (
                    _ability_mean(player.profile.abilities),
                    -player.player_id,
                ),
            )
            action = MarketAction(
                next_action_id,
                MarketActionKind.SIGN,
                selected.player_id,
                roster.team_id,
                rules.minimum_salary,
                1,
            )
            actions.append(action)
            next_action_id += 1
            available.remove(selected.player_id)
            preview = apply_market_plan(
                preview,
                MarketPlan((action,)),
                rules,
                cap_ledger=cap_ledger,
                cap_rules=cap_rules,
            ).final_state
            current = next(item for item in preview.rosters if item.team_id == roster.team_id)
    return MarketPlan(tuple(actions))


def _manager_metrics(
    season: SeasonResult,
    playoffs: PlayoffResult,
    state: CourtSimLeagueState,
) -> tuple[ManagerSeasonMetrics, ...]:
    playoff_progress = {seed.team_id: 0.5 for seed in playoffs.seeds}
    final = playoffs.series[-1]
    playoff_progress[final.higher_seed.team_id] = 0.75
    playoff_progress[final.lower_seed.team_id] = 0.75
    playoff_progress[playoffs.champion_team_id] = 1.0
    standings = {standing.team_id: standing for standing in season.standings}
    players = {player.player_id: player for player in state.players}
    payrolls = {roster.team_id: 0 for roster in state.management.rosters}
    for contract in state.management.contracts:
        payrolls[contract.team_id] += contract.annual_salary
    metrics: list[ManagerSeasonMetrics] = []
    for roster in state.management.rosters:
        standing = standings[roster.team_id]
        games = standing.wins + standing.losses + standing.ties
        roster_players = tuple(players[player_id] for player_id in roster.player_ids)
        asset_value = (
            sum(
                _ability_mean(player.profile.abilities) * 0.65
                + _ability_mean(player.potential) * 0.35
                for player in roster_players
            )
            / len(roster_players)
            / 100
        )
        metrics.append(
            ManagerSeasonMetrics(
                roster.team_id,
                standing.wins / games if games else 0,
                playoff_progress[roster.team_id],
                max(0.0, min(1.0, asset_value)),
                max(
                    0.0,
                    min(
                        1.0,
                        1 - payrolls[roster.team_id] / state.contract_rules.salary_cap,
                    ),
                ),
            )
        )
    return tuple(metrics)


def _ability_mean(value: AbilityRatings) -> float:
    ratings = tuple(cast(int, getattr(value, field.name)) for field in fields(AbilityRatings))
    return sum(ratings) / len(ratings)


def _career_player_to_dict(player: CareerPlayer) -> dict[str, object]:
    return {
        "profile": player_profile_to_dict(player.profile),
        "age": player.age,
        "seasons_pro": player.seasons_pro,
        "development": asdict(player.development),
        "potential": {
            field.name: getattr(player.potential, field.name) for field in fields(AbilityRatings)
        },
        "status": player.status.name,
        "draft_year": player.draft_year,
        "draft_round": player.draft_round,
        "draft_pick": player.draft_pick,
        "injury_burden": player.injury_burden,
    }


def _career_player_from_dict(value: object) -> CareerPlayer:
    raw = _object(value, "career player")
    _exact(
        raw,
        {
            "profile",
            "age",
            "seasons_pro",
            "development",
            "potential",
            "status",
            "draft_year",
            "draft_round",
            "draft_pick",
            "injury_burden",
        },
        "career player",
    )
    development = _object(raw["development"], "development")
    potential = _object(raw["potential"], "potential")
    try:
        status = CareerStatus[str(raw["status"])]
        return CareerPlayer(
            player_profile_from_dict(raw["profile"]),
            _integer(raw, "age"),
            _integer(raw, "seasons_pro"),
            DevelopmentTraits(**development),
            AbilityRatings(**potential),
            status,
            _integer(raw, "draft_year"),
            _integer(raw, "draft_round"),
            _integer(raw, "draft_pick"),
            _integer(raw, "injury_burden"),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise ManagerLeagueAdapterError(f"invalid career player: {error}") from error


def _object(value: object, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ManagerLeagueAdapterError(f"{field} must be an object")
    return cast(dict[str, Any], value)


def _exact(value: dict[str, Any], keys: set[str], field: str) -> None:
    if set(value) != keys:
        raise ManagerLeagueAdapterError(f"{field} keys must be exactly {sorted(keys)}")


def _integer(value: dict[str, Any], key: str) -> int:
    raw = value[key]
    if not isinstance(raw, int) or isinstance(raw, bool):
        raise ManagerLeagueAdapterError(f"{key} must be an integer")
    return raw

"""Production adapter from CourtSim league engines to manager experiments."""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import asdict, dataclass, field, fields, replace
from typing import Any, cast

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
from courtsim.domain.game import GameClockConfig
from courtsim.domain.player import AbilityRatings
from courtsim.domain.player_serialization import (
    player_profile_from_dict,
    player_profile_to_dict,
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
from courtsim.manager_experiment import (
    ManagerExperimentArm,
    ManagerSeasonExecution,
    ManagerSeasonMetrics,
    ManagerSeasonRequest,
)
from courtsim.manager_rotation import (
    ManagerRotationRules,
    generate_manager_rotation,
)
from courtsim.manager_trade import ManagerTradeRules
from courtsim.model.game_runtime import (
    GameMatchups,
    GameTeam,
    sample_game,
)
from courtsim.model.interaction_compiler import (
    DefensiveMatchups,
    Matchup,
    ProfileLineup,
)
from courtsim.model.trace_mode import TraceMode
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
from courtsim.season import (
    ScheduledGame,
    SeasonConfig,
    SeasonResult,
    SeasonSchedule,
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
class CourtSimLeagueState:
    contract_rules: ContractRules
    management: LeagueManagementState
    players: tuple[CareerPlayer, ...]
    draft_assets: DraftAssetLedger = field(default_factory=DraftAssetLedger)
    version: str = MANAGER_LEAGUE_ADAPTER_VERSION

    def __post_init__(self) -> None:
        if self.version != MANAGER_LEAGUE_ADAPTER_VERSION:
            raise ValueError("unsupported manager league adapter version")
        validate_management_state(self.management, self.contract_rules)
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
    games_per_pair: int = 2
    trace_mode: TraceMode = TraceMode.AGGREGATE_ONLY
    version: str = MANAGER_LEAGUE_ADAPTER_VERSION

    def __post_init__(self) -> None:
        if self.version != MANAGER_LEAGUE_ADAPTER_VERSION:
            raise ValueError("unsupported manager league adapter version")
        if (
            not isinstance(self.games_per_pair, int)
            or isinstance(self.games_per_pair, bool)
            or self.games_per_pair < 1
        ):
            raise ValueError("games_per_pair must be a positive integer")
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
        profiles = {profile.team_id: profile for profile in self.manager_profiles}
        if team_ids != tuple(profiles):
            raise ManagerLeagueAdapterError("league state teams do not match manager profiles")

        trade_audit: dict[str, object] | None = None
        three_team_audit: dict[str, object] | None = None
        trade_clearing_choice: str | None = None
        trade_ledger: dict[str, object] | None = None
        three_team_ledger: dict[str, object] | None = None
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
            trade_execution = apply_trade_market_plan(
                state.management,
                state.draft_assets.picks,
                bilateral_plan,
                state.contract_rules,
                self.trade_rules,
            )
            three_team_execution = apply_three_team_market_plan(
                trade_execution.final_management,
                trade_execution.final_picks,
                three_team_plan,
                state.contract_rules,
                self.trade_rules,
            )
            state = replace(
                state,
                management=three_team_execution.final_management,
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

        teams, rotation_audit = _game_teams(
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
        )
        playoffs = _sample_playoffs(
            season,
            teams,
            request=request,
            parameters=self.parameters,
            game_config=self.game_config,
            rules=self.game_rules,
            fatigue_config=self.fatigue_config,
            config=self.playoff_config,
            trace_mode=self.trace_mode,
        )
        summaries = _season_summaries(season, state.players)
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
        draft_plan, market_plan, manager_audit = _offseason_plans(
            state,
            summaries,
            profiles,
            picks,
            arm=request.arm,
            master_seed=offseason_seed,
            career_rules=self.career_rules,
            draft_rules=self.draft_rules,
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
        )
        next_state = CourtSimLeagueState(
            state.contract_rules,
            offseason.final_management,
            offseason.final_players,
            draft_settlement.final_ledger,
        )
        metrics = _manager_metrics(season, playoffs, next_state)
        audit = {
            "adapter_version": self.version,
            "arm": request.arm.name.lower(),
            "season": season_result_to_dict(season),
            "playoffs": playoff_result_to_dict(playoffs),
            "offseason": offseason_result_to_dict(offseason),
            "manager_decisions": manager_audit,
            "prospect_class": prospect_audit,
            "rotations": rotation_audit,
            "trade_market": trade_audit,
            "three_team_market": three_team_audit,
            "trade_clearing_choice": trade_clearing_choice,
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
        "schema_version": 2,
        "version": state.version,
        "management": management,
        "players": [_career_player_to_dict(player) for player in state.players],
        "draft_assets": draft_asset_ledger_to_dict(state.draft_assets),
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def league_state_from_json(payload: str) -> CourtSimLeagueState:
    try:
        value: object = json.loads(payload)
        raw = _object(value, "manager league state")
        schema_version = raw.get("schema_version")
        expected_keys = (
            {"schema_version", "version", "management", "players"}
            if schema_version == 1
            else {"schema_version", "version", "management", "players", "draft_assets"}
        )
        _exact(raw, expected_keys, "manager league state")
        if schema_version not in {1, 2} or raw["version"] != MANAGER_LEAGUE_ADAPTER_VERSION:
            raise ManagerLeagueAdapterError("unsupported manager league state")
        market = market_result_from_dict(raw["management"])
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
        return CourtSimLeagueState(market.rules, market.final_state, players, draft_assets)
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
    updated = CourtSimLeagueState(
        state.contract_rules,
        state.management,
        tuple(sorted((*state.players, *generated.players), key=lambda item: item.player_id)),
        state.draft_assets,
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


def _game_teams(
    state: CourtSimLeagueState,
    manager_profiles: dict[str, ManagerProfile],
    game_config: GameClockConfig,
    rotation_rules: ManagerRotationRules,
) -> tuple[tuple[GameTeam, ...], dict[str, object]]:
    player_map = {player.player_id: player for player in state.players}
    teams: list[GameTeam] = []
    audit: dict[str, object] = {}
    for roster in state.management.rosters:
        if len(roster.player_ids) < 5:
            raise ManagerLeagueAdapterError("league roster has fewer than five playable players")
        try:
            profiles = tuple(player_map[player_id].profile for player_id in roster.player_ids)
        except KeyError as error:
            raise ManagerLeagueAdapterError("league roster references an unknown player") from error
        rotation = generate_manager_rotation(
            team_id=roster.team_id,
            roster=tuple(player_map[player_id] for player_id in roster.player_ids),
            profile=manager_profiles[roster.team_id],
            game_config=game_config,
            rules=rotation_rules,
        )
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
        teams.append(
            GameTeam(
                roster.team_id,
                lineup,
                active,
                bench_profiles=bench,
                substitution_order=rotation.substitution_order,
                rotation_plan=rotation.plan,
            )
        )
        audit[roster.team_id] = asdict(rotation)
    return tuple(teams), audit


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
    request: ManagerSeasonRequest,
    parameters: ModelParameters,
    game_config: GameClockConfig,
    rules: GameRules,
    fatigue_config: FatigueConfig,
    config: PlayoffConfig,
    trace_mode: TraceMode,
) -> PlayoffResult:
    seeds = tuple(
        PlayoffSeed(index, standing.team_id)
        for index, standing in enumerate(season.standings[:4], start=1)
    )
    team_map = {team.team_id: team for team in teams}
    games: list[PlayoffGame] = []

    def series(
        round_number: int,
        series_index: int,
        first: PlayoffSeed,
        second: PlayoffSeed,
    ) -> PlayoffSeed:
        higher, lower = (first, second) if first.seed < second.seed else (second, first)
        wins = {higher.team_id: 0, lower.team_id: 0}
        game_number = 1
        while max(wins.values()) < config.wins_required:
            home_seed = higher if config.higher_seed_home[game_number - 1] else lower
            away_seed = lower if home_seed is higher else higher
            home = team_map[home_seed.team_id]
            away = team_map[away_seed.team_id]
            game_seed = derive_seed(
                request.master_seed,
                MANAGER_LEAGUE_ADAPTER_VERSION,
                request.season_year,
                "playoff",
                round_number,
                series_index,
                game_number,
            )
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
                trace_mode=trace_mode,
            )
            home_score = sampled.result.home_score
            away_score = sampled.result.away_score
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
                home.team_id,
                away.team_id,
                home_score,
                away_score,
            )
            games.append(game)
            wins[game.winner_team_id] += 1
            game_number += 1
        winner = higher if wins[higher.team_id] > wins[lower.team_id] else lower
        return winner

    first = series(1, 1, seeds[0], seeds[3])
    second = series(1, 2, seeds[1], seeds[2])
    series(2, 1, first, second)
    return resolve_playoffs(seeds=seeds, games=tuple(games), config=config)


def _season_summaries(
    season: SeasonResult,
    players: tuple[CareerPlayer, ...],
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
    team_by_player = {
        player_id: roster.team_id
        for roster in season.initial_rosters
        for player_id in roster.player_ids
    }
    return tuple(
        PlayerSeasonSummary(
            player.player_id,
            available_by_team.games.get(team_by_player.get(player.player_id, ""), 0),
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
    contract_year = advance_contract_year(after_retirement, state.contract_rules)
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
) -> tuple[DraftPlan, MarketPlan, dict[str, object]]:
    management, players = _transition_preview(
        state,
        summaries,
        master_seed=master_seed,
        career_rules=career_rules,
    )
    decision_audit: dict[str, object] = {}
    if arm is ManagerExperimentArm.SHADOW and picks:
        shadow_draft = generate_draft_shadow(
            management=management,
            players=players,
            picks=picks,
            profiles=profiles,
            contract_rules=state.contract_rules,
            rookie_salary=draft_rules.rookie_salary,
        )
        draft_plan = shadow_draft.plan
        decision_audit["draft"] = asdict(shadow_draft.ledger)
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
        )
        decision_audit["market"] = asdict(shadow_market.ledger)
    else:
        market_plan = _ensure_playable_market(
            drafted.final_management,
            drafted.final_players,
            state.contract_rules,
            MarketPlan(()),
        )
    return draft_plan, market_plan, decision_audit


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
) -> MarketPlan:
    preview = apply_market_plan(management, plan, rules).final_state
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
            preview = apply_market_plan(preview, MarketPlan((action,)), rules).final_state
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

"""Composable deterministic thirty-team franchise season loop."""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from courtsim.analysis.nba_quick_sim_executor import (
    NBAQuickSimExecution,
    NBAQuickSimExecutor,
    NBAQuickSimMatchupTeam,
    build_nba_player_season_summaries,
)
from courtsim.career import CareerPlayer, CareerStatus, DraftRules
from courtsim.domain.game import GameClockConfig
from courtsim.draft_assets import DraftAssetLedger, seed_future_draft_picks
from courtsim.management import ContractRules, LeagueManagementState
from courtsim.manager_ai import ManagerProfile
from courtsim.manager_learning import (
    ManagerLearningState,
    OpponentTacticalAdjustment,
    advance_manager_learning_from_season,
    opponent_rotation_adjustment,
    opponent_tactical_adjustment,
)
from courtsim.manager_rotation import (
    ManagerRotationResult,
    ManagerRotationRules,
    generate_manager_rotation,
)
from courtsim.model.action_setup import TeamDefenseStrategy, TeamOffenseStrategy
from courtsim.model.game_runtime import GameTeam, TeamTempoStrategy
from courtsim.model.interaction_compiler import ProfileLineup
from courtsim.nba_draft_lottery import (
    NBADraftAssetSettlement,
    resolve_nba_draft_lottery_from_results,
    settle_nba_draft_assets,
)
from courtsim.nba_league import NBAConferenceAlignment
from courtsim.nba_offseason import NBAOffseasonExecution, execute_nba_offseason
from courtsim.parameters import ModelParameters
from courtsim.prospects import (
    ProspectGenerationRules,
    generate_prospect_class,
)
from courtsim.randomness import derive_seed
from courtsim.season import SeasonConfig

NBA_FRANCHISE_VERSION = "nba-franchise-v3"


@dataclass(frozen=True, slots=True)
class NBAFranchiseState:
    league_id: str
    management: LeagueManagementState
    players: tuple[CareerPlayer, ...]
    draft_assets: DraftAssetLedger
    teams: tuple[GameTeam, ...]
    alignment: NBAConferenceAlignment
    completed_seasons: int = 0
    manager_learning: tuple[ManagerLearningState, ...] = ()
    version: str = NBA_FRANCHISE_VERSION

    def __post_init__(self) -> None:
        team_ids = tuple(roster.team_id for roster in self.management.rosters)
        if not self.league_id.strip() or len(team_ids) != 30:
            raise ValueError("NBA franchise requires an identity and thirty teams")
        if team_ids != tuple(team.team_id for team in self.teams):
            raise ValueError("NBA franchise game teams differ from management teams")
        if set((*self.alignment.east_team_ids, *self.alignment.west_team_ids)) != set(team_ids):
            raise ValueError("NBA franchise alignment differs from management teams")
        if self.completed_seasons < 0 or self.version != NBA_FRANCHISE_VERSION:
            raise ValueError("NBA franchise state version or season count is invalid")
        learning_team_ids = tuple(item.team_id for item in self.manager_learning)
        if self.manager_learning and (
            learning_team_ids != tuple(sorted(team_ids))
            or any(
                item.last_completed_season != self.management.season_year - 1
                or item.seasons_observed != self.completed_seasons
                for item in self.manager_learning
            )
        ):
            raise ValueError("NBA franchise manager learning is not season-aligned")
        if self.completed_seasons and len(self.manager_learning) != 30:
            raise ValueError("NBA franchise requires persistent learning for every manager")


@dataclass(frozen=True, slots=True)
class NBAFranchiseSeasonExecution:
    season_id: str
    seed: int
    initial_state: NBAFranchiseState
    simulation: NBAQuickSimExecution
    asset_settlement: NBADraftAssetSettlement
    offseason: NBAOffseasonExecution
    final_state: NBAFranchiseState
    version: str = NBA_FRANCHISE_VERSION


def execute_nba_franchise_season(
    state: NBAFranchiseState,
    *,
    seed: int,
    parameters: ModelParameters,
    game_config: GameClockConfig,
    profiles: dict[str, ManagerProfile],
    contract_rules: ContractRules,
    draft_rules: DraftRules,
    season_config: SeasonConfig | None = None,
    rotation_rules: ManagerRotationRules | None = None,
    prospect_rules: ProspectGenerationRules | None = None,
) -> NBAFranchiseSeasonExecution:
    team_ids = tuple(roster.team_id for roster in state.management.rosters)
    if set(profiles) != set(team_ids):
        raise ValueError("NBA franchise requires one manager profile per team")
    active_prospect_rules = prospect_rules or ProspectGenerationRules(class_size=30)
    if active_prospect_rules.class_size != 30:
        raise ValueError("NBA franchise requires a thirty-player prospect class")
    players = state.players
    prospects = tuple(player for player in players if player.status is CareerStatus.PROSPECT)
    if prospects and len(prospects) != 30:
        raise ValueError("NBA franchise requires zero or thirty incoming prospects")
    if not prospects:
        prospect_class = generate_prospect_class(
            draft_year=state.management.season_year + 1,
            master_seed=derive_seed(seed, NBA_FRANCHISE_VERSION, "prospects"),
            templates=tuple(
                player.profile for player in players if player.status is CareerStatus.ACTIVE
            ),
            existing_player_ids=frozenset(player.player_id for player in players),
            rules=active_prospect_rules,
        )
        players = tuple(
            sorted((*players, *prospect_class.players), key=lambda item: item.player_id)
        )
    season_id = f"{state.league_id}:season-{state.management.season_year}"
    matchup_teams = _build_matchup_teams(
        state.management,
        players,
        state.teams,
        profiles,
        state.manager_learning,
        game_config,
        rotation_rules or ManagerRotationRules(),
    )
    simulation = NBAQuickSimExecutor(
        parameters,
        game_config,
        state.teams,
        state.alignment,
        matchup_teams=matchup_teams,
        season_config=season_config or SeasonConfig(),
    ).execute(season_id, seed)
    next_learning = advance_manager_learning_from_season(
        simulation.season,
        state.manager_learning,
        profiles,
        game_config,
        completed_season=state.management.season_year,
        additional_totals=simulation.postseason_state.learning_totals,
    )
    summaries = build_nba_player_season_summaries(simulation, players)
    lottery = resolve_nba_draft_lottery_from_results(
        draft_year=state.management.season_year + 1,
        master_seed=derive_seed(seed, NBA_FRANCHISE_VERSION, "lottery"),
        season=simulation.season,
        postseason=simulation.postseason,
    )
    ledger = seed_future_draft_picks(
        state.draft_assets,
        team_ids=team_ids,
        draft_years=(lottery.draft_year,),
        rounds=draft_rules.rounds,
    )
    asset_settlement = settle_nba_draft_assets(ledger, lottery)
    offseason = execute_nba_offseason(
        management=state.management,
        players=players,
        summaries=summaries,
        asset_settlement=asset_settlement,
        profiles=profiles,
        contract_rules=contract_rules,
        draft_rules=draft_rules,
        master_seed=derive_seed(seed, NBA_FRANCHISE_VERSION, "offseason"),
    )
    next_teams = _rebuild_teams(
        offseason.offseason.final_management,
        offseason.offseason.final_players,
        state.teams,
        profiles,
        game_config,
        rotation_rules or ManagerRotationRules(),
    )
    final_state = NBAFranchiseState(
        league_id=state.league_id,
        management=offseason.offseason.final_management,
        players=offseason.offseason.final_players,
        draft_assets=offseason.final_draft_assets,
        teams=next_teams,
        alignment=state.alignment,
        completed_seasons=state.completed_seasons + 1,
        manager_learning=next_learning,
    )
    return NBAFranchiseSeasonExecution(
        season_id,
        seed,
        state,
        simulation,
        asset_settlement,
        offseason,
        final_state,
    )


def _rebuild_teams(
    management: LeagueManagementState,
    players: tuple[CareerPlayer, ...],
    previous_teams: tuple[GameTeam, ...],
    profiles: dict[str, ManagerProfile],
    game_config: GameClockConfig,
    rotation_rules: ManagerRotationRules,
) -> tuple[GameTeam, ...]:
    player_map = {player.player_id: player for player in players}
    previous = {team.team_id: team for team in previous_teams}
    return tuple(
        _team_from_rotation(
            roster.team_id,
            tuple(player_map[player_id] for player_id in roster.player_ids),
            generate_manager_rotation(
                team_id=roster.team_id,
                roster=tuple(player_map[player_id] for player_id in roster.player_ids),
                profile=profiles[roster.team_id],
                game_config=game_config,
                rules=rotation_rules,
            ),
            previous[roster.team_id],
        )
        for roster in management.rosters
    )


def _build_matchup_teams(
    management: LeagueManagementState,
    players: tuple[CareerPlayer, ...],
    base_teams: tuple[GameTeam, ...],
    profiles: dict[str, ManagerProfile],
    learning_states: tuple[ManagerLearningState, ...],
    game_config: GameClockConfig,
    rotation_rules: ManagerRotationRules,
) -> tuple[NBAQuickSimMatchupTeam, ...]:
    if not learning_states:
        return ()
    player_map = {player.player_id: player for player in players}
    base_by_team = {team.team_id: team for team in base_teams}
    learning_by_team = {item.team_id: item for item in learning_states}
    result = []
    for roster in management.rosters:
        career_roster = tuple(player_map[player_id] for player_id in roster.player_ids)
        learning = learning_by_team[roster.team_id]
        for opponent_team_id in sorted(
            team_id for team_id in profiles if team_id != roster.team_id
        ):
            rotation_adjustment = opponent_rotation_adjustment(
                learning,
                opponent_team_id,
            )
            tactical_adjustment = opponent_tactical_adjustment(
                learning,
                opponent_team_id,
            )
            rotation = generate_manager_rotation(
                team_id=roster.team_id,
                roster=career_roster,
                profile=profiles[roster.team_id],
                game_config=game_config,
                rules=rotation_rules,
                opponent_adjustment=rotation_adjustment,
            )
            result.append(
                NBAQuickSimMatchupTeam(
                    opponent_team_id,
                    _team_from_rotation(
                        roster.team_id,
                        career_roster,
                        rotation,
                        base_by_team[roster.team_id],
                        tactical_adjustment=tactical_adjustment,
                    ),
                )
            )
    return tuple(result)


def _team_from_rotation(
    team_id: str,
    roster: tuple[CareerPlayer, ...],
    rotation: ManagerRotationResult,
    previous: GameTeam,
    *,
    tactical_adjustment: OpponentTacticalAdjustment | None = None,
) -> GameTeam:
    profile_map = {player.player_id: player.profile for player in roster}
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
    offense_strategy = previous.offense_strategy
    defense_strategy = previous.defense_strategy
    tempo_strategy = previous.tempo_strategy
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

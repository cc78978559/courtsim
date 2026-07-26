from typing import cast

import pytest
from test_game_runtime import PARAMETERS, player
from test_phase12_manager_league_adapter import career_player

from courtsim.career import CareerStatus, DraftRules
from courtsim.domain.game import GameClockConfig
from courtsim.domain.plans import Lineup
from courtsim.draft_assets import DraftAssetLedger
from courtsim.management import ContractRules, LeagueManagementState, PlayerContract
from courtsim.manager_ai import ManagerProfile
from courtsim.model.game_runtime import GameTeam
from courtsim.model.interaction_compiler import ProfileLineup
from courtsim.nba_franchise import (
    NBAFranchiseState,
    execute_nba_franchise_season,
)
from courtsim.nba_league import NBAConferenceAlignment
from courtsim.prospects import ProspectGenerationRules
from courtsim.rosters import RosterSnapshot
from courtsim.season import SeasonConfig


def _state() -> tuple[NBAFranchiseState, dict[str, ManagerProfile], ContractRules]:
    team_ids = tuple(f"T{index:02d}" for index in range(1, 31))
    rosters = tuple(
        RosterSnapshot(team_id, tuple(range(index * 5 + 1, index * 5 + 6)))
        for index, team_id in enumerate(team_ids)
    )
    teams = tuple(
        GameTeam(
            roster.team_id,
            cast(Lineup, roster.player_ids),
            cast(
                ProfileLineup,
                tuple(player(player_id) for player_id in roster.player_ids),
            ),
        )
        for roster in rosters
    )
    rules = ContractRules(
        salary_cap=100_000_000,
        minimum_salary=1_000_000,
        maximum_salary=20_000_000,
        maximum_years=5,
        maximum_roster_players=15,
    )
    management = LeagueManagementState(
        2029,
        rosters,
        (),
        tuple(
            PlayerContract(player_id, roster.team_id, 1_000_000, 4)
            for roster in rosters
            for player_id in roster.player_ids
        ),
    )
    return (
        NBAFranchiseState(
            "league",
            management,
            tuple(career_player(player_id) for player_id in range(1, 151)),
            DraftAssetLedger(),
            teams,
            NBAConferenceAlignment(team_ids[:15], team_ids[15:]),
        ),
        {team_id: ManagerProfile(f"manager-{team_id}", team_id) for team_id in team_ids},
        rules,
    )


def test_franchise_season_composes_into_a_second_complete_season() -> None:
    state, profiles, contract_rules = _state()
    game_config = GameClockConfig(1, 5, 5, 5, 8, True)
    draft_rules = DraftRules(
        rounds=1,
        rookie_salary=1_000_000,
        rookie_contract_years=2,
    )
    first = execute_nba_franchise_season(
        state,
        seed=101,
        parameters=PARAMETERS,
        game_config=game_config,
        profiles=profiles,
        contract_rules=contract_rules,
        draft_rules=draft_rules,
        season_config=SeasonConfig(injury_probability_bps=0),
    )
    assert first.final_state.management.season_year == 2030
    assert first.final_state.completed_seasons == 1
    assert len(first.simulation.season.games) == 1_230
    assert len(first.offseason.offseason.selections) == 30
    assert {len(roster.player_ids) for roster in first.final_state.management.rosters} == {6}
    assert all(
        set(team.roster_order) == set(roster.player_ids)
        for team, roster in zip(
            first.final_state.teams,
            first.final_state.management.rosters,
            strict=True,
        )
    )

    second = execute_nba_franchise_season(
        first.final_state,
        seed=202,
        parameters=PARAMETERS,
        game_config=game_config,
        profiles=profiles,
        contract_rules=contract_rules,
        draft_rules=draft_rules,
        season_config=SeasonConfig(injury_probability_bps=0),
    )
    assert second.initial_state == first.final_state
    assert second.final_state.management.season_year == 2031
    assert second.final_state.completed_seasons == 2
    assert len(second.simulation.postseason.series) == 15
    assert len(second.offseason.offseason.selections) == 30
    assert {len(roster.player_ids) for roster in second.final_state.management.rosters} == {7}
    assert not any(career.status is CareerStatus.PROSPECT for career in second.final_state.players)


def test_nba_franchise_rejects_nonstandard_prospect_class_size() -> None:
    state, profiles, contract_rules = _state()

    with pytest.raises(ValueError, match="thirty-player prospect class"):
        execute_nba_franchise_season(
            state,
            seed=101,
            parameters=PARAMETERS,
            game_config=GameClockConfig(1, 5, 5, 5, 8, True),
            profiles=profiles,
            contract_rules=contract_rules,
            draft_rules=DraftRules(rounds=1),
            prospect_rules=ProspectGenerationRules(class_size=29),
        )

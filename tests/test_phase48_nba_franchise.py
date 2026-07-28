import json
from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest
from test_game_runtime import PARAMETERS, player
from test_phase12_manager_league_adapter import career_player

from courtsim.cap_mechanics import CapLedger, TradeException
from courtsim.career import CareerStatus, DraftRules
from courtsim.cli import main
from courtsim.domain.game import GameClockConfig
from courtsim.domain.plans import Lineup
from courtsim.draft_assets import DraftAssetLedger
from courtsim.management import ContractRules, LeagueManagementState, PlayerContract
from courtsim.manager_ai import ManagerProfile
from courtsim.model.game_runtime import GameTeam
from courtsim.model.interaction_compiler import ProfileLineup
from courtsim.nba_franchise import (
    NBAFranchiseSeasonExecution,
    NBAFranchiseState,
    execute_nba_franchise_season,
)
from courtsim.nba_franchise_artifacts import (
    load_nba_franchise_checkpoint,
    write_nba_franchise_checkpoint,
)
from courtsim.nba_franchise_runner import (
    NBAFranchiseRetentionPolicy,
    NBAFranchiseRunSpec,
    inspect_nba_franchise_manifest,
    run_nba_franchise_checkpoint,
)
from courtsim.nba_league import NBAConferenceAlignment
from courtsim.prospects import ProspectGenerationRules
from courtsim.rosters import RosterSnapshot
from courtsim.season import SeasonConfig
from courtsim.three_team_market import ThreeTeamMarketRules
from courtsim.trade_market import TradeMarketRules

pytestmark = [pytest.mark.slow, pytest.mark.nba, pytest.mark.franchise]


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


def test_franchise_season_composes_into_a_second_complete_season(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    state, profiles, contract_rules = _state()
    state = replace(
        state,
        cap_ledger=CapLedger(
            trade_exceptions=(TradeException(1, "T01", 500_000, 2030),),
            next_exception_id=2,
        ),
    )
    game_config = GameClockConfig(1, 5, 5, 5, 8, True)
    draft_rules = DraftRules(
        rounds=1,
        rookie_salary=1_000_000,
        rookie_contract_years=2,
    )

    def execute(
        current: NBAFranchiseState,
        seed: int,
    ) -> NBAFranchiseSeasonExecution:
        return execute_nba_franchise_season(
            current,
            seed=seed,
            parameters=PARAMETERS,
            game_config=game_config,
            profiles=profiles,
            contract_rules=contract_rules,
            draft_rules=draft_rules,
            season_config=SeasonConfig(injury_probability_bps=0),
            trade_market_rules=TradeMarketRules(
                maximum_candidates_per_pair=1,
                generate_pick_counteroffers=False,
                generate_player_for_pick_offers=False,
                generate_two_for_one_offers=False,
                maximum_round_three_candidates=1,
                generate_round_three_counteroffers=False,
            ),
            three_team_market_rules=ThreeTeamMarketRules(
                maximum_candidates_per_trio=2,
                maximum_cyclic_candidates_per_trio=1,
                maximum_hub_candidates_per_trio=1,
                search_pick_compensation=False,
                maximum_compensation_picks=1,
            ),
        )

    spec = NBAFranchiseRunSpec("league-run", 101, 2)
    retention = NBAFranchiseRetentionPolicy(keep_last=1, keep_every=5, compress_after=1)
    first_run = run_nba_franchise_checkpoint(
        spec,
        state,
        contract_rules,
        execute,
        tmp_path / "run",
        maximum_new_seasons=1,
        retention_policy=retention,
    )
    assert first_run.completed_before == 0
    assert first_run.completed_after == 1
    assert not first_run.complete
    assert len(first_run.executions) == 1
    assert (tmp_path / "run" / "season-00000.json.gz").is_file()
    first = first_run.executions[0]
    assert first.trade_clearing_choice in {"none", "bilateral", "three-team"}
    assert first.bilateral_trade_market.evaluations
    assert first.three_team_trade_market.evaluations
    assert first.bilateral_trade_execution.initial_cap_ledger == state.cap_ledger
    assert first.final_state.cap_ledger.trade_exceptions == state.cap_ledger.trade_exceptions
    assert first.final_state.management.season_year == 2030
    assert first.final_state.completed_seasons == 1
    assert first.simulation.matchup_team_count == 0
    assert len(first.final_state.manager_learning) == 30
    assert all(
        learning.last_completed_season == 2029
        and learning.seasons_observed == 1
        and len(learning.opponents) == 29
        for learning in first.final_state.manager_learning
    )
    assert len(first.simulation.postseason_state.learning_totals) == (
        len(first.simulation.postseason_state.games) * 2
    )
    assert (
        sum(
            opponent.games_observed
            for learning in first.final_state.manager_learning
            for opponent in learning.opponents
        )
        == 2_460 + len(first.simulation.postseason_state.games) * 2
    )
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

    receipt = write_nba_franchise_checkpoint(
        first.final_state,
        contract_rules,
        tmp_path / "franchise.json",
    )
    restored, restored_rules, loaded_receipt = load_nba_franchise_checkpoint(
        tmp_path / "franchise.json",
        expected_file_sha256=receipt.file_sha256,
    )
    assert restored == first.final_state
    assert restored_rules == contract_rules
    assert loaded_receipt == receipt

    second_run = run_nba_franchise_checkpoint(
        spec,
        state,
        restored_rules,
        execute,
        tmp_path / "run",
        maximum_new_seasons=1,
    )
    assert second_run.completed_before == 1
    assert second_run.completed_after == 2
    assert second_run.complete
    assert len(second_run.executions) == 1
    assert not (tmp_path / "run" / "season-00001.json").exists()
    assert (tmp_path / "run" / "season-00002.json").is_file()
    second = second_run.executions[0]
    assert second.initial_state == first.final_state
    assert second.final_state.management.season_year == 2031
    assert second.final_state.completed_seasons == 2
    assert second.final_state.cap_ledger.trade_exceptions == ()
    assert second.simulation.matchup_team_count == 870
    assert all(
        learning.last_completed_season == 2030
        and learning.seasons_observed == 2
        and len(learning.opponents) == 29
        for learning in second.final_state.manager_learning
    )
    first_games = {
        (learning.team_id, opponent.opponent_team_id): opponent.games_observed
        for learning in first.final_state.manager_learning
        for opponent in learning.opponents
    }
    assert all(
        opponent.games_observed > first_games[(learning.team_id, opponent.opponent_team_id)]
        for learning in second.final_state.manager_learning
        for opponent in learning.opponents
    )
    assert sum(
        opponent.games_observed
        for learning in second.final_state.manager_learning
        for opponent in learning.opponents
    ) == (
        4_920
        + len(first.simulation.postseason_state.games) * 2
        + len(second.simulation.postseason_state.games) * 2
    )
    assert len(second.simulation.postseason.series) == 15
    assert len(second.offseason.offseason.selections) == 30
    assert {len(roster.player_ids) for roster in second.final_state.management.rosters} == {7}
    assert not any(career.status is CareerStatus.PROSPECT for career in second.final_state.players)

    def must_not_execute(
        current: NBAFranchiseState,
        seed: int,
    ) -> NBAFranchiseSeasonExecution:
        raise AssertionError((current.completed_seasons, seed))

    completed_run = run_nba_franchise_checkpoint(
        spec,
        state,
        contract_rules,
        must_not_execute,
        tmp_path / "run",
    )
    assert completed_run.completed_before == 2
    assert completed_run.completed_after == 2
    assert completed_run.complete
    assert completed_run.executions == ()
    inspection = inspect_nba_franchise_manifest(tmp_path / "run" / "manifest.json")
    assert inspection.run_id == spec.run_id
    assert inspection.completed_seasons == 2
    assert inspection.target_seasons == 2
    assert inspection.complete
    assert inspection.retained_checkpoints == 2
    assert inspection.compressed_checkpoints == 1
    assert inspection.pruned_checkpoints == 1
    assert main(["nba-franchise-status", str(tmp_path / "run" / "manifest.json")]) == 0
    assert json.loads(capsys.readouterr().out)["complete"] is True


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

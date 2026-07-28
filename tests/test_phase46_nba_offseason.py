from test_phase12_manager_league_adapter import career_player

from courtsim.career import CareerStatus, DraftRules, PlayerSeasonSummary, audit_offseason
from courtsim.draft_assets import DraftAssetLedger, seed_future_draft_picks
from courtsim.management import ContractRules, LeagueManagementState, PlayerContract
from courtsim.manager_ai import ManagerProfile
from courtsim.nba_draft_lottery import (
    resolve_nba_draft_lottery,
    settle_nba_draft_assets,
)
from courtsim.nba_offseason import execute_nba_offseason
from courtsim.rosters import RosterSnapshot


def test_complete_nba_offseason_advances_careers_contracts_draft_market_and_assets() -> None:
    team_ids = tuple(f"T{index:02d}" for index in range(1, 31))
    rosters = tuple(
        RosterSnapshot(team_id, tuple(range(index * 5 + 1, index * 5 + 6)))
        for index, team_id in enumerate(team_ids)
    )
    contracts = tuple(
        PlayerContract(
            player_id,
            roster.team_id,
            1_000_000,
            1 if player_id == roster.player_ids[0] else 3,
        )
        for roster in rosters
        for player_id in roster.player_ids
    )
    contract_rules = ContractRules(
        salary_cap=100_000_000,
        minimum_salary=1_000_000,
        maximum_salary=20_000_000,
        maximum_years=5,
        maximum_roster_players=15,
    )
    management = LeagueManagementState(2029, rosters, (), contracts)
    players = (
        *(career_player(player_id) for player_id in range(1, 151)),
        *(
            career_player(
                player_id,
                value=50 + player_id % 20,
                potential=70 + player_id % 25,
                status=CareerStatus.PROSPECT,
            )
            for player_id in range(1_001, 1_031)
        ),
    )
    summaries = tuple(
        PlayerSeasonSummary(player_id, 82, 82, 1_000, 0) for player_id in range(1, 151)
    )
    lottery = resolve_nba_draft_lottery(
        draft_year=2030,
        master_seed=7,
        non_playoff_order=team_ids[:14],
        playoff_order=team_ids[14:],
    )
    settlement = settle_nba_draft_assets(
        seed_future_draft_picks(
            DraftAssetLedger(),
            team_ids=team_ids,
            draft_years=(2030,),
            rounds=1,
        ),
        lottery,
    )
    execution = execute_nba_offseason(
        management=management,
        players=players,
        summaries=summaries,
        asset_settlement=settlement,
        profiles={team_id: ManagerProfile(f"manager-{team_id}", team_id) for team_id in team_ids},
        contract_rules=contract_rules,
        draft_rules=DraftRules(
            rounds=1,
            rookie_salary=1_000_000,
            rookie_contract_years=2,
        ),
        master_seed=11,
    )
    result = execution.offseason
    assert result.final_management.season_year == 2030
    assert len(result.changes) == 150
    assert len(result.expired_player_ids) == 30
    assert len(result.selections) == 30
    assert len(result.market_actions) == 30
    assert {len(roster.player_ids) for roster in result.final_management.rosters} == {6}
    assert len(execution.scouting_reports) == 900
    assert len(execution.draft_shadow.ledger.records) == 30
    assert len(execution.market_shadow.ledger.records) == 30
    assert {pick.draft_year for pick in execution.final_draft_assets.picks} == {
        2031,
        2032,
        2033,
    }
    assert len(execution.final_draft_assets.picks) == 90
    assert audit_offseason(result).players_drafted == 30

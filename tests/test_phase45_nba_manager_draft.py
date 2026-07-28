from test_phase12_manager_league_adapter import career_player

from courtsim.career import CareerStatus, DraftRules
from courtsim.draft_assets import DraftAssetLedger, seed_future_draft_picks
from courtsim.management import (
    ContractRules,
    LeagueManagementState,
    PlayerContract,
)
from courtsim.manager_ai import ManagerProfile
from courtsim.nba_draft_lottery import (
    resolve_nba_draft_lottery,
    settle_nba_draft_assets,
)
from courtsim.nba_draft_offseason import execute_nba_manager_draft
from courtsim.rosters import RosterSnapshot


def test_thirty_white_box_managers_scout_and_execute_complete_first_round() -> None:
    team_ids = tuple(f"T{index:02d}" for index in range(1, 31))
    rosters = tuple(
        RosterSnapshot(
            team_id,
            tuple(range(index * 5 + 1, index * 5 + 6)),
        )
        for index, team_id in enumerate(team_ids)
    )
    contracts = tuple(
        PlayerContract(player_id, roster.team_id, 1_000_000, 3)
        for roster in rosters
        for player_id in roster.player_ids
    )
    rules = ContractRules(
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
    lottery = resolve_nba_draft_lottery(
        draft_year=2029,
        master_seed=7,
        non_playoff_order=team_ids[:14],
        playoff_order=team_ids[14:],
    )
    assets = settle_nba_draft_assets(
        seed_future_draft_picks(
            DraftAssetLedger(),
            team_ids=team_ids,
            draft_years=(2029,),
            rounds=1,
        ),
        lottery,
    )
    draft_rules = DraftRules(
        rounds=1,
        rookie_salary=1_000_000,
        rookie_contract_years=2,
    )
    result = execute_nba_manager_draft(
        management=management,
        players=players,
        asset_settlement=assets,
        profiles={team_id: ManagerProfile(f"manager-{team_id}", team_id) for team_id in team_ids},
        contract_rules=rules,
        draft_rules=draft_rules,
        master_seed=11,
    )
    assert len(result.scouting_reports) == 900
    assert len(result.shadow.traces) == 30
    assert len(result.shadow.ledger.records) == 30
    assert len(result.draft.selections) == 30
    assert len({item.player_id for item in result.draft.selections}) == 30
    assert {len(roster.player_ids) for roster in result.draft.final_management.rosters} == {6}
    drafted = {
        item.player_id: item for item in result.draft.final_players if item.player_id >= 1_001
    }
    assert all(player.status is CareerStatus.ACTIVE for player in drafted.values())
    assert all(player.draft_year == 2029 and player.draft_round == 1 for player in drafted.values())
    assert (
        sum(
            contract.annual_salary == 1_000_000 and contract.years_remaining == 2
            for contract in result.draft.final_management.contracts
        )
        >= 30
    )

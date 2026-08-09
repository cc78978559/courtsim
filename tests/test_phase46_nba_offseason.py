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


def test_two_round_offseason_restores_rosters_after_concentrated_expirations() -> None:
    team_ids = tuple(f"T{index:02d}" for index in range(1, 31))
    rosters = tuple(
        RosterSnapshot(team_id, tuple(range(index * 5 + 1, index * 5 + 6)))
        for index, team_id in enumerate(team_ids)
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
            PlayerContract(player_id, roster.team_id, 1_000_000, 1)
            for roster in rosters
            for player_id in roster.player_ids
        ),
    )
    players = (
        *(career_player(player_id) for player_id in range(1, 151)),
        *(
            career_player(
                player_id,
                value=50 + player_id % 20,
                potential=70 + player_id % 25,
                status=CareerStatus.PROSPECT,
            )
            for player_id in range(1_001, 1_061)
        ),
    )
    summaries = tuple(
        PlayerSeasonSummary(player_id, 82, 82, 1_000, 0) for player_id in range(1, 151)
    )
    lottery = resolve_nba_draft_lottery(
        draft_year=2030,
        master_seed=17,
        non_playoff_order=team_ids[:14],
        playoff_order=team_ids[14:],
    )
    settlement = settle_nba_draft_assets(
        seed_future_draft_picks(
            DraftAssetLedger(),
            team_ids=team_ids,
            draft_years=(2030,),
            rounds=2,
        ),
        lottery,
    )
    execution = execute_nba_offseason(
        management=management,
        players=players,
        summaries=summaries,
        asset_settlement=settlement,
        profiles={team_id: ManagerProfile(f"manager-{team_id}", team_id) for team_id in team_ids},
        contract_rules=rules,
        draft_rules=DraftRules(
            rounds=2,
            rookie_salary=1_000_000,
            rookie_contract_years=2,
        ),
        master_seed=19,
    )
    assert len(execution.offseason.expired_player_ids) == 150
    assert len(execution.offseason.selections) == 60
    assert len(execution.offseason.market_actions) == 90
    assert {len(roster.player_ids) for roster in execution.offseason.final_management.rosters} == {
        5
    }
    assert all(
        action.annual_salary == rules.minimum_salary
        for action in execution.offseason.market_actions
    )


def test_six_consecutive_offseasons_survive_fifth_year_contract_cliff() -> None:
    team_ids = tuple(f"T{index:02d}" for index in range(1, 31))
    rosters = tuple(
        RosterSnapshot(team_id, tuple(range(index * 5 + 1, index * 5 + 6)))
        for index, team_id in enumerate(team_ids)
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
            PlayerContract(player_id, roster.team_id, 1_000_000, 5)
            for roster in rosters
            for player_id in roster.player_ids
        ),
    )
    players = tuple(career_player(player_id) for player_id in range(1, 151))
    profiles = {team_id: ManagerProfile(f"manager-{team_id}", team_id) for team_id in team_ids}
    ledger = DraftAssetLedger()
    expired_counts = []
    for season_index in range(6):
        draft_year = management.season_year + 1
        prospect_base = 10_000 + season_index * 100
        prospects = tuple(
            career_player(
                prospect_base + offset,
                value=50 + offset % 20,
                potential=70 + offset % 25,
                status=CareerStatus.PROSPECT,
            )
            for offset in range(60)
        )
        players = tuple(sorted((*players, *prospects), key=lambda player: player.player_id))
        summaries = tuple(
            PlayerSeasonSummary(player.player_id, 82, 82, 1_000, 0)
            for player in players
            if player.status in {CareerStatus.ACTIVE, CareerStatus.FREE_AGENT}
        )
        lottery = resolve_nba_draft_lottery(
            draft_year=draft_year,
            master_seed=100 + season_index,
            non_playoff_order=team_ids[:14],
            playoff_order=team_ids[14:],
        )
        settlement = settle_nba_draft_assets(
            seed_future_draft_picks(
                ledger,
                team_ids=team_ids,
                draft_years=(draft_year,),
                rounds=2,
            ),
            lottery,
        )
        execution = execute_nba_offseason(
            management=management,
            players=players,
            summaries=summaries,
            asset_settlement=settlement,
            profiles=profiles,
            contract_rules=rules,
            draft_rules=DraftRules(
                rounds=2,
                rookie_salary=1_000_000,
                rookie_contract_years=2,
            ),
            master_seed=200 + season_index,
        )
        management = execution.offseason.final_management
        players = execution.offseason.final_players
        ledger = execution.final_draft_assets
        expired_counts.append(len(execution.offseason.expired_player_ids))
        assert min(len(roster.player_ids) for roster in management.rosters) >= 5
        assert max(len(roster.player_ids) for roster in management.rosters) <= 15
    assert management.season_year == 2035
    assert expired_counts[4] >= 150

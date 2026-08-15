from dataclasses import replace
from typing import cast

from test_game_runtime import player

from courtsim.analysis.nba_manager_state import (
    NBAManagerPlayerSource,
    NBAManagerStateSource,
    build_nba_manager_initial_state,
)
from courtsim.analysis.nba_player_targets import (
    NBAPlayerSourceReceipt,
    NBAPlayerTarget,
    NBAPlayerTargetSet,
)
from courtsim.domain.plans import Lineup
from courtsim.management import ContractRules
from courtsim.model.game_runtime import GameTeam
from courtsim.model.interaction_compiler import ProfileLineup
from courtsim.nba_league import NBAConferenceAlignment


def _inputs() -> tuple[
    tuple[GameTeam, ...],
    NBAConferenceAlignment,
    NBAPlayerTargetSet,
    NBAManagerStateSource,
    ContractRules,
]:
    team_ids = tuple(f"T{index:02d}" for index in range(1, 31))
    teams = []
    targets = []
    sources = []
    for team_index, team_id in enumerate(team_ids):
        profiles = tuple(
            replace(
                player(team_index * 10 + offset + 1),
                nominal_role_tags=("WING",),
            )
            for offset in range(10)
        )
        teams.append(
            GameTeam(
                team_id,
                cast(Lineup, tuple(item.player_id for item in profiles[:5])),
                cast(ProfileLineup, profiles[:5]),
                bench_profiles=profiles[5:],
                substitution_order=tuple(item.player_id for item in profiles),
            )
        )
        for offset, profile in enumerate(profiles):
            targets.append(
                NBAPlayerTarget(
                    profile.player_id,
                    profile.name,
                    team_id,
                    82,
                    24.0,
                    0.20,
                    0.58,
                    0.10,
                    (0.35, 0.25, 0.40),
                    (0.65, 0.42, 0.37),
                )
            )
            sources.append(
                NBAManagerPlayerSource(
                    profile.player_id,
                    age=25 if offset != 9 or team_index >= 15 else None,
                    annual_salary=5_000_000 if offset != 9 else None,
                    contract_years_remaining=3 if offset < 5 else None,
                    team_tenure_seasons=3 if offset < 5 else None,
                )
            )
    target_set = NBAPlayerTargetSet(
        "targets",
        "2024-25",
        "test",
        1,
        1.0,
        (NBAPlayerSourceReceipt("box", "box.json", "0" * 64),),
        tuple(targets),
    )
    source = NBAManagerStateSource("management", "2024-25", "1" * 64, tuple(sources))
    rules = ContractRules(
        salary_cap=140_000_000,
        minimum_salary=1_000_000,
        maximum_salary=60_000_000,
        maximum_years=5,
        maximum_roster_players=15,
    )
    return (
        tuple(teams),
        NBAConferenceAlignment(team_ids[:15], team_ids[15:]),
        target_set,
        source,
        rules,
    )


def test_real_manager_state_marks_fallbacks_and_meets_formal_coverage() -> None:
    teams, alignment, targets, source, rules = _inputs()
    result = build_nba_manager_initial_state(
        league_id="nba-manager",
        season_year=2025,
        teams=teams,
        alignment=alignment,
        player_targets=targets,
        player_source=source,
        contract_rules=rules,
    )
    assert result.receipt.formal_source_eligible
    assert result.receipt.source_age_coverage == 0.95
    assert result.receipt.minute_weighted_source_salary_coverage == 0.90
    assert len(result.state.management.rosters) == 30
    assert {len(item.player_ids) for item in result.state.management.rosters} == {10}
    assert len(result.state.draft_assets.picks) == 30 * 7 * 2
    assert len(result.state.cap_ledger.bird_rights) == 300
    assert len(result.receipt.proxy_age_player_ids) == 15
    assert len(result.receipt.proxy_salary_player_ids) == 30
    assert len(result.receipt.default_contract_player_ids) == 150
    assert len(result.receipt.non_bird_fallback_player_ids) == 150
    fallback_id = result.receipt.proxy_salary_player_ids[0]
    fallback = next(item for item in result.resolutions if item.nba_player_id == fallback_id)
    assert fallback.salary_source == "proxy-role-performance:WING"
    assert fallback.contract_source == "proxy-one-year"
    assert fallback.bird_seasons == 1


def test_real_manager_state_receipt_is_deterministic() -> None:
    teams, alignment, targets, source, rules = _inputs()
    first = build_nba_manager_initial_state(
        league_id="nba-manager",
        season_year=2025,
        teams=teams,
        alignment=alignment,
        player_targets=targets,
        player_source=source,
        contract_rules=rules,
    )
    second = build_nba_manager_initial_state(
        league_id="nba-manager",
        season_year=2025,
        teams=teams,
        alignment=alignment,
        player_targets=targets,
        player_source=source,
        contract_rules=rules,
    )
    assert first.receipt == second.receipt
    assert first.state == second.state

from pathlib import Path

from courtsim.analysis.nba_player_targets import (
    NBAPlayerSourceReceipt,
    NBAPlayerTarget,
    NBAPlayerTargetSet,
)
from courtsim.analysis.nba_real_rosters import (
    ESPN_TEAM_NAMES,
    build_nba_real_game_team,
    build_nba_real_roster_teams,
)
from courtsim.domain.player_serialization import player_lineup_from_json

ROOT = Path(__file__).resolve().parents[1]


def _targets() -> NBAPlayerTargetSet:
    players = tuple(
        NBAPlayerTarget(
            team_number * 100 + player_number,
            f"Real Player {team_number}-{player_number}",
            str(team_number),
            70 if player_number <= 10 else 20 + player_number,
            36.0 - player_number,
            0.30 - player_number * 0.01,
            0.58,
            0.18 - player_number * 0.005,
            (0.4, 0.2, 0.4),
            (0.62, 0.42, 0.37),
        )
        for team_number in range(1, 31)
        for player_number in range(1, 16)
    )
    return NBAPlayerTargetSet(
        "real-roster-test",
        "2024-25",
        "test",
        10,
        8.0,
        (NBAPlayerSourceReceipt("box", "box.json", "0" * 64),),
        players,
    )


def test_real_rosters_preserve_identity_and_balance_rotation_minutes() -> None:
    templates = player_lineup_from_json(
        (ROOT / "examples" / "calibration_lineup_v1.json").read_text(encoding="utf-8")
    )
    team_ids = tuple(ESPN_TEAM_NAMES[str(index)] for index in range(1, 31))
    teams = build_nba_real_roster_teams(_targets(), templates, team_ids)
    assert len(teams) == 30
    assert len({player_id for team in teams for player_id in team.roster_order}) == 450
    assert all(len(team.roster_order) == 15 for team in teams)
    assert teams[0].roster_profiles[0].name == "Real Player 1-1"
    for team in teams:
        assert team.rotation_plan is not None
        assert len(team.rotation_plan.stints) == 16
        appearances = sum(len(stint.lineup) for stint in team.rotation_plan.stints)
        assert appearances * 3 == 240


def test_real_rotation_uses_depth_probabilistically_with_low_sample_shrinkage() -> None:
    targets = _targets()
    templates = player_lineup_from_json(
        (ROOT / "examples" / "calibration_lineup_v1.json").read_text(encoding="utf-8")
    )
    team_ids = tuple(ESPN_TEAM_NAMES[str(index)] for index in range(1, 31))
    team = build_nba_real_roster_teams(targets, templates, team_ids)[0]
    appearances = {player_id: 0 for player_id in team.roster_order}
    for game_id in range(1, 83):
        game_team = build_nba_real_game_team(
            team,
            targets,
            game_id=game_id,
            master_seed=911,
        )
        assert game_team.rotation_plan is not None
        active = {
            player_id for stint in game_team.rotation_plan.stints for player_id in stint.lineup
        }
        for player_id in active:
            appearances[player_id] += 1
    depth = tuple(team.roster_order[10:])
    assert all(0 < appearances[player_id] < 82 for player_id in depth)
    assert sum(appearances[player_id] for player_id in depth) > 0

import json
from pathlib import Path

import pytest

from courtsim.analysis.nba_player_targets import (
    NBAPlayerSourceReceipt,
    NBAPlayerTarget,
    NbaPlayerTargetError,
    NBAPlayerTargetSet,
    build_nba_player_target_payload,
    load_nba_player_target_set,
    nba_player_target_set_to_dict,
)
from courtsim.artifacts import write_json


def _targets() -> NBAPlayerTargetSet:
    return NBAPlayerTargetSet(
        "nba-2024-25-player-realism-v1",
        "2024-25",
        "local-fixture",
        10,
        8.0,
        (NBAPlayerSourceReceipt("box_scores", "sources/box.json", "a" * 64),),
        (
            NBAPlayerTarget(
                10,
                "Player A",
                "A",
                70,
                32.5,
                0.25,
                0.61,
                0.22,
                (0.4, 0.2, 0.4),
                (0.7, 0.45, 0.38),
            ),
        ),
    )


def test_nba_player_targets_round_trip(tmp_path: Path) -> None:
    targets = _targets()
    path = tmp_path / "targets.json"
    write_json(path, nba_player_target_set_to_dict(targets))
    assert load_nba_player_target_set(path) == targets


def test_nba_player_targets_reject_incomplete_zones(tmp_path: Path) -> None:
    payload = nba_player_target_set_to_dict(_targets())
    players = payload["players"]
    assert isinstance(players, list)
    players[0]["shot_zone_shares"].pop("THREE")
    path = tmp_path / "targets.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(NbaPlayerTargetError, match="zones are invalid"):
        load_nba_player_target_set(path)


def test_build_player_targets_from_pinned_local_summaries(tmp_path: Path) -> None:
    box = tmp_path / "box.json"
    shots = tmp_path / "shots.json"
    identity = tmp_path / "identity.json"
    write_json(
        box,
        {
            "schema_version": 1,
            "season": "2024-25",
            "groups": [
                {
                    "key": {
                        "team_id": "1",
                        "athlete_id": "10",
                        "athlete_display_name": "Player A",
                    },
                    "metrics": {
                        "games_played": 20,
                        "minutes": 600.0,
                        "field_goal_attempts": 200.0,
                        "free_throw_attempts": 50.0,
                        "turnovers": 30.0,
                        "points": 300.0,
                    },
                }
            ],
        },
    )
    write_json(
        shots,
        {
            "schema_version": 1,
            "season": "2024-25",
            "groups": [
                {
                    "key": {"TEAM_ID": "100", "PLAYER_ID": "1000", "PLAYER_NAME": "Player A"},
                    "metrics": {
                        "rim_attempts": 80,
                        "rim_made": 50,
                        "midrange_attempts": 40,
                        "midrange_made": 18,
                        "three_attempts": 80,
                        "three_made": 30,
                    },
                }
            ],
        },
    )
    write_json(
        identity,
        {
            "schema_version": 1,
            "season": "2024-25",
            "mappings": [{"espn_player_id": 10, "nba_player_id": 1000}],
        },
    )
    payload = build_nba_player_target_payload(
        box,
        shots,
        identity,
        target_id="fixture",
        minimum_games=10,
        minimum_minutes_per_game=8.0,
    )
    players = payload["players"]
    assert isinstance(players, list)
    assert len(players) == 1
    assert players[0]["minutes_per_game"] == 30.0
    assert players[0]["shot_zone_shares"] == {"RIM": 0.4, "MIDRANGE": 0.2, "THREE": 0.4}

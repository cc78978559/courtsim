import json
import math
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest

import courtsim.analysis.nba_player_targets as target_module
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


@pytest.mark.parametrize(
    ("role", "path", "sha256", "message"),
    [
        ("", "box.json", "a" * 64, "identity"),
        ("box", "../box.json", "a" * 64, "portable"),
        ("box", "box.json", "A" * 64, "sha256"),
    ],
)
def test_source_receipt_rejects_nonportable_identity(
    role: str, path: str, sha256: str, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        NBAPlayerSourceReceipt(role, path, sha256)


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"nba_player_id": 0}, "identity"),
        ({"player_name": " "}, "identity"),
        ({"games_played": True}, "identity"),
        ({"minutes_per_game": math.nan}, "minutes"),
        ({"minutes_per_game": 61.0}, "minutes"),
        ({"usage_rate": 1.1}, "usage_rate"),
        ({"true_shooting_percentage": math.inf}, "true_shooting_percentage"),
        ({"field_goal_attempt_share": -0.1}, "field_goal_attempt_share"),
        ({"shot_zone_shares": (0.5, 0.5)}, "incomplete"),
        ({"shot_zone_shares": (-0.1, 0.5, 0.6)}, "shares are invalid"),
        ({"shot_zone_shares": (0.2, 0.2, 0.2)}, "sum to one"),
        ({"shot_zone_percentages": (0.2, 0.3, 1.1)}, "percentages are invalid"),
    ],
)
def test_player_target_strict_scalar_and_zone_validation(
    changes: dict[str, object], message: str
) -> None:
    player = _targets().players[0]
    with pytest.raises(ValueError, match=message):
        replace(player, **changes)  # type: ignore[arg-type]


def test_target_set_rejects_duplicate_sources_order_and_eligibility() -> None:
    targets = _targets()
    source = targets.sources[0]
    player = targets.players[0]
    with pytest.raises(ValueError, match="source roles"):
        replace(targets, sources=(source, replace(source, path="other.json")))
    with pytest.raises(ValueError, match="ordered unique"):
        replace(targets, players=(replace(player, nba_player_id=11), player))
    with pytest.raises(ValueError, match="eligibility"):
        replace(targets, minimum_games=71)
    with pytest.raises(ValueError, match="unsupported"):
        replace(targets, version="future-v2")
    with pytest.raises(ValueError, match="contain sources and players"):
        replace(targets, sources=())


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda payload: payload.pop("provider"), "root is invalid"),
        (lambda payload: payload.__setitem__("schema_version", 2), "schema version differs"),
        (
            lambda payload: payload["eligibility"].__setitem__("extra", 1),
            "eligibility is invalid",
        ),
        (lambda payload: payload.__setitem__("sources", {}), "collections are invalid"),
        (lambda payload: payload["sources"][0].__setitem__("extra", 1), "source is invalid"),
        (lambda payload: payload["players"][0].__setitem__("extra", 1), "row is invalid"),
        (
            lambda payload: payload["players"][0].__setitem__("nba_player_id", True),
            "must be an integer",
        ),
        (
            lambda payload: payload["players"][0].__setitem__("usage_rate", "high"),
            "must be numeric",
        ),
    ],
)
def test_target_payload_rejects_schema_and_type_drift(mutation: object, message: str) -> None:
    payload = deepcopy(nba_player_target_set_to_dict(_targets()))
    assert callable(mutation)
    mutation(payload)
    with pytest.raises(NbaPlayerTargetError, match=message):
        target_module._target_set_from_object(payload)


def test_target_loader_wraps_invalid_json_and_missing_file(tmp_path: Path) -> None:
    invalid = tmp_path / "invalid.json"
    invalid.write_text("not-json", encoding="utf-8")
    for path in (invalid, tmp_path / "missing.json"):
        with pytest.raises(NbaPlayerTargetError, match="cannot read"):
            load_nba_player_target_set(path)

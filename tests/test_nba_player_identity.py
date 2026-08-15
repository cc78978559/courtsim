from pathlib import Path
from typing import Any, cast

from courtsim.analysis.nba_player_identity import (
    augment_nba_player_crosswalk_payload,
    build_nba_player_identity_payload,
)
from courtsim.artifacts import write_json


def _summary(
    path: Path,
    *,
    dataset_id: str,
    group_by: list[str],
    groups: list[dict[str, object]],
    season: str = "2024-25",
) -> None:
    write_json(
        path,
        {
            "schema_version": 1,
            "dataset_id": dataset_id,
            "season": season,
            "source": {"sha256": "a" * 64},
            "group_by": group_by,
            "groups": groups,
        },
    )


def test_player_identity_build_is_id_only_and_reports_coverage(tmp_path: Path) -> None:
    box = tmp_path / "box.json"
    crosswalk = tmp_path / "crosswalk.json"
    _summary(
        box,
        dataset_id="box",
        group_by=["team_id", "athlete_id", "athlete_display_name"],
        groups=[
            {
                "key": {
                    "team_id": "1",
                    "athlete_id": "10",
                    "athlete_display_name": "Mapped Player",
                },
                "metrics": {"games_played": 4, "minutes": 100.0},
            },
            {
                "key": {
                    "team_id": "2",
                    "athlete_id": "20",
                    "athlete_display_name": "Same Name As Crosswalk",
                },
                "metrics": {"games_played": 2, "minutes": 25.0},
            },
        ],
    )
    _summary(
        crosswalk,
        dataset_id="crosswalk",
        season="2025-26",
        group_by=[
            "espn_athlete_id",
            "nba_player_id",
            "espn_full_name",
            "nba_player_name",
            "match_method",
            "match_confidence",
        ],
        groups=[
            {
                "key": {
                    "espn_athlete_id": "10",
                    "nba_player_id": "100",
                    "espn_full_name": "Mapped Player",
                    "nba_player_name": "Mapped Player",
                    "match_method": "exact_name",
                    "match_confidence": "1.0",
                },
                "metrics": {"records": 1},
            },
            {
                "key": {
                    "espn_athlete_id": "99",
                    "nba_player_id": "200",
                    "espn_full_name": "Same Name As Crosswalk",
                    "nba_player_name": "Same Name As Crosswalk",
                    "match_method": "exact_name",
                    "match_confidence": "1.0",
                },
                "metrics": {"records": 1},
            },
        ],
    )

    payload = build_nba_player_identity_payload(box, crosswalk)

    assert payload["coverage"] == {
        "box_players": 2,
        "mapped_players": 1,
        "unmapped_players": 1,
        "player_coverage": 0.5,
        "total_minutes": 125.0,
        "mapped_minutes": 100.0,
        "minutes_coverage": 0.8,
    }
    policy = cast(dict[str, Any], payload["policy"])
    promotion = cast(dict[str, Any], payload["promotion"])
    mappings = cast(list[dict[str, Any]], payload["mappings"])
    unmatched = cast(list[dict[str, Any]], payload["unmatched"])
    assert policy["name_fallback"] is False
    assert promotion["ready"] is False
    assert mappings[0]["nba_player_id"] == 100
    assert mappings[0]["courtsim_player_id"] is None
    assert unmatched[0]["reason"] == "missing_from_pinned_crosswalk"


def test_player_identity_aggregates_traded_player_teams(tmp_path: Path) -> None:
    box = tmp_path / "box.json"
    crosswalk = tmp_path / "crosswalk.json"
    box_groups = [
        {
            "key": {"team_id": team, "athlete_id": "10", "athlete_display_name": "A"},
            "metrics": {"games_played": games, "minutes": minutes},
        }
        for team, games, minutes in (("2", 3, 50.0), ("1", 2, 25.0))
    ]
    _summary(
        box,
        dataset_id="box",
        group_by=["team_id", "athlete_id", "athlete_display_name"],
        groups=box_groups,
    )
    _summary(
        crosswalk,
        dataset_id="crosswalk",
        group_by=[
            "espn_athlete_id",
            "nba_player_id",
            "espn_full_name",
            "nba_player_name",
            "match_method",
            "match_confidence",
        ],
        groups=[
            {
                "key": {
                    "espn_athlete_id": "10",
                    "nba_player_id": "100",
                    "espn_full_name": "A",
                    "nba_player_name": "A",
                    "match_method": "exact_name",
                    "match_confidence": "1.0",
                },
                "metrics": {"records": 1},
            }
        ],
    )

    payload = build_nba_player_identity_payload(box, crosswalk)
    mappings = cast(list[dict[str, Any]], payload["mappings"])
    mapping = mappings[0]
    assert mapping["team_ids"] == ["1", "2"]
    assert mapping["games_played"] == 5
    assert mapping["minutes"] == 75.0
    promotion = cast(dict[str, Any], payload["promotion"])
    assert promotion["ready"] is True


def test_crosswalk_augmentation_uses_only_unique_exact_pinned_names(tmp_path: Path) -> None:
    box = tmp_path / "box.json"
    crosswalk = tmp_path / "crosswalk.json"
    shots = tmp_path / "shots.json"
    _summary(
        box,
        dataset_id="box",
        group_by=["team_id", "athlete_id", "athlete_display_name"],
        groups=[
            {
                "key": {"team_id": "1", "athlete_id": "7", "athlete_display_name": "A Player"},
                "metrics": {"games_played": 4, "minutes": 100.0},
            }
        ],
    )
    _summary(
        crosswalk,
        dataset_id="crosswalk",
        group_by=[
            "espn_athlete_id",
            "nba_player_id",
            "espn_full_name",
            "nba_player_name",
            "match_method",
            "match_confidence",
        ],
        groups=[],
    )
    _summary(
        shots,
        dataset_id="shots",
        group_by=["TEAM_ID", "PLAYER_ID", "PLAYER_NAME"],
        groups=[
            {
                "key": {"TEAM_ID": "10", "PLAYER_ID": "70", "PLAYER_NAME": "A Player"},
                "metrics": {"field_goal_attempts": 1},
            }
        ],
    )
    augmented = augment_nba_player_crosswalk_payload(box, crosswalk, shots)
    augmentation = augmented["augmentation"]
    groups = augmented["groups"]
    assert isinstance(augmentation, dict)
    assert isinstance(groups, list)
    assert augmentation["added_mappings"] == 1
    assert groups[0]["key"]["nba_player_id"] == "70"

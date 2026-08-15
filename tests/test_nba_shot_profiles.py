import hashlib
import json
from pathlib import Path
from typing import cast

import pytest
from test_game_runtime import player

from courtsim.analysis.nba_shot_profiles import (
    NbaShotProfileError,
    apply_nba_team_shot_profile,
    build_nba_shot_profile_payload,
    load_nba_shot_profile_set,
)
from courtsim.artifacts import sha256_file, write_json
from courtsim.cli import main
from courtsim.domain.plans import Lineup
from courtsim.model.game_runtime import GameTeam
from courtsim.model.interaction_compiler import ProfileLineup


def _artifacts(tmp_path: Path) -> tuple[Path, Path]:
    summary = tmp_path / "summary.json"
    write_json(
        summary,
        {
            "schema_version": 1,
            "dataset_id": "shots",
            "season": "2024-25",
            "group_by": "TEAM_NAME",
            "source": {"sha256": hashlib.sha256(b"raw").hexdigest()},
            "metrics": {
                "teams": 2,
                "field_goal_attempts": 200,
                "restricted_area_attempts": 80,
                "paint_non_ra_attempts": 20,
                "mid_range_attempts": 20,
                "three_point_attempts": 80,
            },
            "groups": {
                "A": {
                    "field_goal_attempts": 100,
                    "restricted_area_attempts": 30,
                    "paint_non_ra_attempts": 10,
                    "mid_range_attempts": 10,
                    "three_point_attempts": 50,
                },
                "B": {
                    "field_goal_attempts": 100,
                    "restricted_area_attempts": 50,
                    "paint_non_ra_attempts": 10,
                    "mid_range_attempts": 10,
                    "three_point_attempts": 30,
                },
            },
        },
    )
    audit = tmp_path / "audit.json"
    write_json(
        audit,
        {
            "schema_version": 1,
            "status": "passed",
            "sources": {"shot_summary": {"sha256": sha256_file(summary)}},
            "promotion": {
                "reconciled_metrics": [
                    "teams",
                    "games",
                    "field_goals_made",
                    "field_goal_attempts",
                    "three_points_made",
                    "three_point_attempts",
                    "field_goal_percentage",
                    "three_point_percentage",
                ],
                "warning_metrics": [],
                "rejected_metrics": [],
            },
        },
    )
    return summary, audit


def test_build_load_cli_and_apply_team_shot_profiles(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    summary, audit = _artifacts(tmp_path)
    payload = build_nba_shot_profile_payload(summary, audit)
    rows = payload["teams"]
    assert isinstance(rows, list)
    assert rows[0]["team_id"] == "A"
    assert rows[0]["rating_offsets"]["THREE"] > 0
    output = tmp_path / "profiles.json"
    assert (
        main(
            [
                "nba-data",
                "build-shot-profiles",
                str(summary),
                str(audit),
                str(output),
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out) == json.loads(output.read_text(encoding="utf-8"))
    profiles = load_nba_shot_profile_set(output)
    lineup: Lineup = (1, 2, 3, 4, 5)
    team = GameTeam(
        "A",
        lineup,
        cast(ProfileLineup, tuple(player(player_id) for player_id in lineup)),
    )
    adjusted = apply_nba_team_shot_profile(team, profiles.teams[0])
    original_mix = team.profiles[0].tendencies.shot_zone_mix
    adjusted_mix = adjusted.profiles[0].tendencies.shot_zone_mix
    assert adjusted_mix.three > original_mix.three
    assert adjusted_mix.rim < original_mix.rim
    assert team.profiles[0].tendencies.shot_zone_mix == original_mix


def test_profiles_reject_stale_audit(tmp_path: Path) -> None:
    summary, audit = _artifacts(tmp_path)
    payload = json.loads(summary.read_text(encoding="utf-8"))
    payload["season"] = "changed"
    write_json(summary, payload)
    with pytest.raises(NbaShotProfileError, match="does not pin"):
        build_nba_shot_profile_payload(summary, audit)

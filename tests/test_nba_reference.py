import hashlib
import json
from pathlib import Path

import pytest

from courtsim.analysis.nba_reference import (
    NbaReferenceError,
    build_nba_core_target_payload,
    build_nba_team_target_payload,
    calculate_nba_core_metrics,
    calculate_nba_team_metrics,
)
from courtsim.analysis.realism_targets import load_realism_target_set
from courtsim.artifacts import write_json
from courtsim.cli import main

ROOT = Path(__file__).parents[1]
SOURCE = ROOT / "experiments" / "sources" / "nba-2024-25-team-core.json"


def test_pinned_nba_snapshot_produces_expected_core_metrics() -> None:
    metrics = calculate_nba_core_metrics(SOURCE)
    assert tuple(metrics) == (
        "mean_team_possessions",
        "points_per_100_possessions",
        "field_goal_percentage",
        "three_point_percentage",
        "turnover_rate",
        "offensive_rebound_rate",
        "assist_per_field_goal",
        "block_rate",
        "steal_rate",
        "shot_zone_share.THREE",
    )
    assert metrics["mean_team_possessions"] == pytest.approx(99.5796666667)
    assert metrics["points_per_100_possessions"] == pytest.approx(113.6916386846)
    assert metrics["field_goal_percentage"] == pytest.approx(0.4672136001)
    assert metrics["three_point_percentage"] == pytest.approx(0.3602223809)
    assert metrics["turnover_rate"] == pytest.approx(0.1428159601)
    assert metrics["offensive_rebound_rate"] == pytest.approx(0.2520642117)


def test_target_payload_pins_source_hash_and_relative_envelope() -> None:
    payload = build_nba_core_target_payload(
        SOURCE,
        artifact_path="sources/nba-2024-25-team-core.json",
    )
    expected_digest = hashlib.sha256(SOURCE.read_bytes()).hexdigest()
    assert payload["status"] == "active"
    assert payload["sources"][0]["content_sha256"] == expected_digest  # type: ignore[index]
    metric = payload["metrics"][0]  # type: ignore[index]
    assert metric["metric"] == "mean_team_possessions"
    assert metric["lower"] == pytest.approx(metric["target"] * 0.95)
    assert metric["upper"] == pytest.approx(metric["target"] * 1.05)


def test_nba_target_builder_command_writes_loadable_active_contract(tmp_path: Path) -> None:
    source = tmp_path / "sources" / SOURCE.name
    source.parent.mkdir()
    source.write_bytes(SOURCE.read_bytes())
    output = tmp_path / "targets.json"
    assert main(["targets-build-nba", str(source), str(output)]) == 0
    targets = load_realism_target_set(output)
    assert targets.status == "active"
    assert len(targets.metrics) == 10
    assert not targets.planned_metrics


def test_snapshot_team_set_mismatch_is_rejected(tmp_path: Path) -> None:
    payload = json.loads(SOURCE.read_text(encoding="utf-8"))
    payload["advanced"]["rows"][0][0] = "Not A Real Team"
    source = tmp_path / "bad-source.json"
    write_json(source, payload)
    with pytest.raises(NbaReferenceError, match="team sets differ"):
        calculate_nba_core_metrics(source)


def test_target_builder_rejects_parent_traversal() -> None:
    with pytest.raises(NbaReferenceError, match="portable"):
        build_nba_core_target_payload(SOURCE, artifact_path="../source.json")


def test_team_metrics_preserve_observed_style_axes() -> None:
    boston = calculate_nba_team_metrics(SOURCE, "Boston Celtics")
    denver = calculate_nba_team_metrics(SOURCE, "Denver Nuggets")
    assert tuple(boston) == (
        "mean_team_possessions",
        "points_per_100_possessions",
        "field_goal_percentage",
        "three_point_percentage",
        "turnover_rate",
        "assist_per_field_goal",
        "block_rate",
        "steal_rate",
        "shot_zone_share.THREE",
    )
    assert boston["mean_team_possessions"] == pytest.approx(96.59)
    assert boston["shot_zone_share.THREE"] == pytest.approx(3955 / 7382)
    assert denver["assist_per_field_goal"] == pytest.approx(2542 / 3724)


def test_team_target_builder_supports_reviewed_metric_subsets() -> None:
    payload = build_nba_team_target_payload(
        SOURCE,
        team="Boston Celtics",
        artifact_path="sources/nba-2024-25-team-core.json",
        metrics=("mean_team_possessions", "shot_zone_share.THREE"),
        audit_team_id="home",
    )
    assert payload["status"] == "active"
    assert payload["population"] == "Boston Celtics, NBA 2024-25 regular season, 82 team-games"
    assert payload["target_set_id"] == "nba-2024-25-boston-celtics-home-style-v1"
    raw_metrics = payload["metrics"]
    assert isinstance(raw_metrics, list)
    assert [metric["metric"] for metric in raw_metrics] == [
        "team.home.mean_team_possessions",
        "team.home.shot_zone_share.THREE",
    ]


def test_team_target_builder_rejects_unknown_team_and_metric() -> None:
    with pytest.raises(NbaReferenceError, match="unknown NBA team"):
        calculate_nba_team_metrics(SOURCE, "Seattle Supersonics")
    with pytest.raises(NbaReferenceError, match="unsupported team target metrics"):
        build_nba_team_target_payload(
            SOURCE,
            team="Boston Celtics",
            artifact_path="source.json",
            metrics=("not_a_metric",),
        )


def test_nba_team_target_builder_command_writes_selected_metrics(
    tmp_path: Path,
) -> None:
    source = tmp_path / "sources" / SOURCE.name
    source.parent.mkdir()
    source.write_bytes(SOURCE.read_bytes())
    output = tmp_path / "team-targets.json"
    assert (
        main(
            [
                "targets-build-nba-team",
                str(source),
                str(output),
                "--team",
                "Denver Nuggets",
                "--metric",
                "assist_per_field_goal",
                "--metric",
                "shot_zone_share.THREE",
            ]
        )
        == 0
    )
    targets = load_realism_target_set(output)
    assert targets.status == "active"
    assert tuple(metric.metric for metric in targets.metrics) == (
        "assist_per_field_goal",
        "shot_zone_share.THREE",
    )

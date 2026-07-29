import hashlib
import json
from pathlib import Path

import pytest

from courtsim.analysis.nba_data_audit import (
    NbaDataAuditError,
    build_nba_data_audit,
    build_nba_possession_audit,
)
from courtsim.analysis.nba_reference import (
    NbaReferenceError,
    calculate_nba_reference_totals,
)
from courtsim.artifacts import write_json
from courtsim.cli import main

ROOT = Path(__file__).parents[1]
CORE = ROOT / "experiments" / "sources" / "nba-2024-25-team-core.json"
FREE_THROWS = ROOT / "experiments" / "sources" / "nba-2024-25-team-free-throws.json"


def _summary(tmp_path: Path, *, three_attempt_delta: int = 820) -> Path:
    totals = calculate_nba_reference_totals(CORE, FREE_THROWS)
    field_goal_attempts = totals["field_goal_attempts"] + 1
    three_point_attempts = totals["three_point_attempts"] + three_attempt_delta
    metrics: dict[str, float | int] = {
        **totals,
        "field_goal_attempts": field_goal_attempts,
        "three_point_attempts": three_point_attempts,
        "rebounds": totals["rebounds"] + 20_184,
        "field_goal_percentage": totals["field_goals_made"] / field_goal_attempts,
        "three_point_percentage": totals["three_points_made"] / three_point_attempts,
        "free_throw_percentage": (totals["free_throws_made"] / totals["free_throw_attempts"]),
        "turnovers_per_game": totals["turnovers"] / totals["games"],
        "events": 606_538,
        "fouls": 46_916,
    }
    metrics.pop("possessions")
    metrics.pop("offensive_rebounds")
    path = tmp_path / "summary.json"
    write_json(
        path,
        {
            "schema_version": 1,
            "dataset_id": "event-fixture-2024",
            "season": "2024-25",
            "metrics": metrics,
            "source": {
                "bytes": 8_781_060,
                "sha256": hashlib.sha256(b"raw-event-fixture").hexdigest(),
            },
        },
    )
    return path


def test_reference_totals_are_strict_and_complete() -> None:
    assert calculate_nba_reference_totals(CORE, FREE_THROWS) == {
        "teams": 30,
        "games": 1230,
        "possessions": 246289,
        "field_goals_made": 102566,
        "field_goal_attempts": 219527,
        "three_points_made": 33304,
        "three_point_attempts": 92454,
        "free_throws_made": 41574,
        "free_throw_attempts": 53312,
        "turnovers": 35174,
        "offensive_rebounds": 27353,
        "rebounds": 108516,
    }


def test_audit_promotes_only_reconciled_metrics(tmp_path: Path) -> None:
    summary = _summary(tmp_path)
    report = build_nba_data_audit(summary, CORE, FREE_THROWS)
    assert report["status"] == "partial"
    audit_summary = report["summary"]
    assert isinstance(audit_summary, dict)
    assert audit_summary == {"compared": 14, "passed": 11, "warnings": 0, "rejected": 3}
    promotion = report["promotion"]
    assert isinstance(promotion, dict)
    assert promotion["rejected_metrics"] == [
        "three_point_attempts",
        "rebounds",
        "three_point_percentage",
    ]
    assert promotion["derived_metrics"] == [
        "field_goal_percentage",
        "free_throw_percentage",
        "turnovers_per_game",
    ]
    assert promotion["unmatched_event_metrics"] == ["events", "fouls"]
    sources = report["sources"]
    assert isinstance(sources, dict)
    assert sources["event_summary"]["sha256"] == hashlib.sha256(summary.read_bytes()).hexdigest()


def test_warning_band_and_cli_output(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    summary = _summary(tmp_path, three_attempt_delta=200)
    payload = json.loads(summary.read_text(encoding="utf-8"))
    payload["metrics"]["rebounds"] = calculate_nba_reference_totals(CORE, FREE_THROWS)["rebounds"]
    write_json(summary, payload)
    output = tmp_path / "audit.json"
    assert (
        main(
            [
                "nba-data",
                "audit",
                str(summary),
                str(CORE),
                str(FREE_THROWS),
                str(output),
            ]
        )
        == 0
    )
    emitted = json.loads(capsys.readouterr().out)
    assert emitted["status"] == "warning"
    assert emitted["promotion"]["warning_metrics"] == [
        "three_point_attempts",
        "three_point_percentage",
    ]
    assert json.loads(output.read_text(encoding="utf-8")) == emitted


def test_audit_rejects_invalid_thresholds_and_summary(tmp_path: Path) -> None:
    summary = _summary(tmp_path)
    with pytest.raises(NbaDataAuditError, match="tolerance"):
        build_nba_data_audit(summary, CORE, FREE_THROWS, tolerance=-1.0)
    with pytest.raises(NbaDataAuditError, match="warning_multiplier"):
        build_nba_data_audit(summary, CORE, FREE_THROWS, warning_multiplier=1.0)
    payload = json.loads(summary.read_text(encoding="utf-8"))
    payload["metrics"].pop("turnovers")
    write_json(summary, payload)
    with pytest.raises(NbaDataAuditError, match="turnovers must be numeric"):
        build_nba_data_audit(summary, CORE, FREE_THROWS)


def test_reference_totals_reject_tampered_free_throw_snapshot(tmp_path: Path) -> None:
    payload = json.loads(FREE_THROWS.read_text(encoding="utf-8"))
    payload["totals"]["FTA"] += 1
    candidate = tmp_path / "free-throws.json"
    write_json(candidate, payload)
    with pytest.raises(NbaReferenceError, match="totals do not match"):
        calculate_nba_reference_totals(CORE, candidate)


def test_possession_audit_separates_reconciled_and_source_only_metrics(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    summary = tmp_path / "possessions.json"
    write_json(
        summary,
        {
            "schema_version": 1,
            "dataset_id": "pbpstats-2024",
            "season": "2024-25",
            "source": {
                "bytes": 13_739_644,
                "sha256": hashlib.sha256(b"pbpstats").hexdigest(),
            },
            "metrics": {
                "teams": 30,
                "games": 1230,
                "possessions": 243782,
                "two_points_made": 69233,
                "two_point_attempts": 126988,
                "three_points_made": 33302,
                "three_point_attempts": 91812,
                "turnovers": 35096,
                "offensive_rebounds": 33250,
                "combined_possessions_per_game": 198.19674796748,
                "two_point_percentage": 0.545193246606,
                "three_point_percentage": 0.362719470222,
                "turnover_per_possession": 0.143964689764,
                "mean_possession_seconds": 14.601418480446,
            },
        },
    )
    report = build_nba_possession_audit(summary, CORE)
    assert report["status"] == "partial"
    audit_summary = report["summary"]
    assert isinstance(audit_summary, dict)
    assert audit_summary == {"compared": 13, "passed": 6, "warnings": 1, "rejected": 6}
    promotion = report["promotion"]
    assert isinstance(promotion, dict)
    assert promotion["warning_metrics"] == ["turnovers"]
    assert promotion["source_only_metrics"] == ["mean_possession_seconds"]
    assert "possessions" in promotion["rejected_metrics"]
    output = tmp_path / "possession-audit.json"
    assert (
        main(
            [
                "nba-data",
                "audit-possessions",
                str(summary),
                str(CORE),
                str(output),
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out) == json.loads(output.read_text(encoding="utf-8"))

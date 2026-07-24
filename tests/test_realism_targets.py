import hashlib
import json
from pathlib import Path

import pytest

from courtsim.analysis import load_distribution_audit
from courtsim.analysis.realism_targets import (
    RealismTargetError,
    load_realism_target_set,
    score_audit_against_realism_targets,
)

ROOT = Path(__file__).parents[1]
BASELINE = ROOT / "data" / "baselines" / "model-audit-demo-0.4.0.json"
TEMPLATE = ROOT / "experiments" / "realism-targets-template-v1.json"
FOUL_BASELINE = ROOT / "data" / "baselines" / "model-audit-demo-0.7.0.json"
FREE_THROW_TARGETS = ROOT / "experiments" / "nba-2024-25-regular-season-free-throws-v1.json"


SOURCE_BYTES = b"synthetic,target,source\n"
SOURCE_DIGEST = hashlib.sha256(SOURCE_BYTES).hexdigest()


def active_payload(digest: str = SOURCE_DIGEST) -> dict[str, object]:
    return {
        "format_version": 1,
        "target_set_id": "test-targets",
        "status": "active",
        "population": "test population",
        "season": "test season",
        "notes": "Synthetic contract test, not a realism claim.",
        "sources": [
            {
                "source_id": "test-source",
                "label": "Synthetic test source",
                "origin": "synthetic:test",
                "artifact_path": "source.csv",
                "retrieved_on": "2026-07-23",
                "content_sha256": digest,
            }
        ],
        "metrics": [
            {
                "metric": "points_per_100_possessions",
                "lower": 130.0,
                "target": 135.0,
                "upper": 140.0,
                "weight": 2.0,
                "required": True,
                "source_id": "test-source",
            },
            {
                "metric": "shot_zone_share.THREE",
                "lower": 0.2,
                "target": 0.3,
                "upper": 0.4,
                "weight": 1.0,
                "required": True,
                "source_id": "test-source",
            },
        ],
        "planned_metrics": [],
    }


def write(path: Path, payload: object) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def write_source(directory: Path) -> None:
    (directory / "source.csv").write_bytes(SOURCE_BYTES)


def test_draft_template_is_explicitly_not_scored() -> None:
    targets = load_realism_target_set(TEMPLATE)
    assert targets.status == "draft"
    assert targets.planned_metrics
    report = score_audit_against_realism_targets(
        load_distribution_audit(BASELINE),
        targets,
    )
    assert report.metrics_evaluated == 0
    assert report.weighted_rmse is None
    assert report.gate_passed is None


def test_active_targets_score_and_rank_out_of_range_metrics(tmp_path: Path) -> None:
    write_source(tmp_path)
    targets = load_realism_target_set(write(tmp_path / "targets.json", active_payload()))
    report = score_audit_against_realism_targets(
        load_distribution_audit(BASELINE),
        targets,
    )
    assert report.metrics_evaluated == 2
    assert report.required_failures == 1
    assert report.gate_passed is False
    assert report.weighted_rmse is not None and report.weighted_rmse > 0.0
    assert report.metric_results[0].metric == "shot_zone_share.THREE"
    assert report.metric_results[0].direction == "HIGH"
    assert report.metric_results[1].direction == "IN_RANGE"


def test_active_status_requires_pinned_sources_and_complete_metrics(tmp_path: Path) -> None:
    draft = json.loads(TEMPLATE.read_text(encoding="utf-8"))
    draft["status"] = "active"
    with pytest.raises(RealismTargetError, match="active targets"):
        load_realism_target_set(write(tmp_path / "empty-active.json", draft))

    bad_digest = active_payload()
    bad_digest["sources"][0]["content_sha256"] = "not-a-hash"  # type: ignore[index]
    with pytest.raises(RealismTargetError, match="content_sha256"):
        load_realism_target_set(write(tmp_path / "bad-digest.json", bad_digest))

    write_source(tmp_path)
    wrong_hash = active_payload("b" * 64)
    with pytest.raises(RealismTargetError, match="hash mismatch"):
        load_realism_target_set(write(tmp_path / "wrong-hash.json", wrong_hash))


def test_unknown_audit_metric_is_rejected_at_scoring_boundary(tmp_path: Path) -> None:
    write_source(tmp_path)
    payload = active_payload()
    payload["metrics"][0]["metric"] = "not_a_metric"  # type: ignore[index]
    targets = load_realism_target_set(write(tmp_path / "unknown.json", payload))
    with pytest.raises(RealismTargetError, match="unknown audit metrics"):
        score_audit_against_realism_targets(
            load_distribution_audit(BASELINE),
            targets,
        )


def test_frozen_foul_baseline_passes_pinned_free_throw_targets() -> None:
    targets = load_realism_target_set(FREE_THROW_TARGETS)
    report = score_audit_against_realism_targets(
        load_distribution_audit(FOUL_BASELINE),
        targets,
    )
    assert report.metrics_evaluated == 3
    assert report.required_failures == 0
    assert report.gate_passed

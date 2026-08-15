import json
from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest

from courtsim.analysis.quick_sim_batch import (
    QuickSimBatchSpec,
    quick_sim_batch_to_json,
    run_quick_sim_batch,
)
from courtsim.analysis.quick_sim_comparison import QuickSimSeasonSummary
from courtsim.analysis.quick_sim_pairing import (
    QuickSimPairingError,
    compare_paired_quick_sim_batches,
)
from courtsim.cli import main


def _baseline(season_id: str, seed: int) -> QuickSimSeasonSummary:
    offset = seed % 5
    return QuickSimSeasonSummary(
        season_id,
        30,
        1_230,
        0.1 + offset * 0.001,
        99.0 + offset,
        112.0 + offset,
        4.0 + offset * 0.1,
        0.25,
        2,
    )


def _candidate(season_id: str, seed: int) -> QuickSimSeasonSummary:
    return replace(
        _baseline(season_id, seed),
        offensive_rating=_baseline(season_id, seed).offensive_rating + 1.5,
        point_differential_stddev=(_baseline(season_id, seed).point_differential_stddev + 0.25),
    )


def test_paired_quick_sim_report_requires_and_preserves_identical_seeds(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    spec = QuickSimBatchSpec("shot-profile-ab", 20260730, 3)
    baseline = run_quick_sim_batch(spec, _baseline)
    candidate = run_quick_sim_batch(spec, _candidate)
    report = compare_paired_quick_sim_batches(baseline, candidate)
    assert report["status"] == "changed"
    metric_rows = cast(list[dict[str, object]], report["metrics"])
    metrics = {item["metric"]: item for item in metric_rows}
    assert metrics["offensive-rating"]["mean_delta"] == 1.5
    assert metrics["point-differential-stddev"]["mean_delta"] == 0.25
    baseline_path = tmp_path / "baseline.json"
    candidate_path = tmp_path / "candidate.json"
    output = tmp_path / "paired.json"
    baseline_path.write_text(quick_sim_batch_to_json(baseline), encoding="utf-8")
    candidate_path.write_text(quick_sim_batch_to_json(candidate), encoding="utf-8")
    assert (
        main(
            [
                "nba-quick-sim-paired-diff",
                str(baseline_path),
                str(candidate_path),
                str(output),
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out) == json.loads(output.read_text(encoding="utf-8"))


def test_paired_quick_sim_rejects_incomplete_or_different_specs() -> None:
    spec = QuickSimBatchSpec("paired", 1, 2)
    incomplete = run_quick_sim_batch(spec, _baseline, maximum_new_seasons=1)
    complete = run_quick_sim_batch(spec, _baseline)
    with pytest.raises(QuickSimPairingError, match="complete"):
        compare_paired_quick_sim_batches(incomplete, complete)
    other = run_quick_sim_batch(QuickSimBatchSpec("other", 1, 2), _baseline)
    with pytest.raises(QuickSimPairingError, match="same spec"):
        compare_paired_quick_sim_batches(complete, other)

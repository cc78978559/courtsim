from pathlib import Path

import pytest

from courtsim.analysis.quick_sim_artifacts import (
    run_quick_sim_checkpoint,
    write_observed_quick_sim_reference,
)
from courtsim.analysis.quick_sim_batch import (
    QuickSimBatchError,
    QuickSimBatchSpec,
    quick_sim_batch_from_json,
)
from courtsim.analysis.quick_sim_comparison import (
    QuickSimSeasonSummary,
    load_quick_sim_reference,
)
from courtsim.artifacts import sha256_file


def _summary(season_id: str, seed: int) -> QuickSimSeasonSummary:
    offset = seed % 4
    return QuickSimSeasonSummary(
        season_id,
        30,
        1_230,
        0.10 + offset * 0.01,
        97.0 + offset,
        110.0 + offset,
        4.0 + offset * 0.2,
        0.20 + offset * 0.05,
        1 + offset,
    )


def test_checkpoint_survives_failure_and_resumes_without_repeating_cells(tmp_path: Path) -> None:
    path = tmp_path / "study" / "checkpoint.json"
    spec = QuickSimBatchSpec("court-sim-study", 20260726, 4)
    calls: list[str] = []

    def interrupted(season_id: str, seed: int) -> QuickSimSeasonSummary:
        calls.append(season_id)
        if len(calls) == 3:
            raise RuntimeError("simulated process failure")
        return _summary(season_id, seed)

    with pytest.raises(RuntimeError, match="process failure"):
        run_quick_sim_checkpoint(spec, interrupted, path)
    saved = quick_sim_batch_from_json(path.read_text(encoding="utf-8"))
    assert len(saved.cells) == 2

    resumed_calls: list[str] = []

    def resumed(season_id: str, seed: int) -> QuickSimSeasonSummary:
        resumed_calls.append(season_id)
        return _summary(season_id, seed)

    result, receipt = run_quick_sim_checkpoint(spec, resumed, path)
    assert result.complete
    assert receipt.completed_before == 2
    assert receipt.completed_after == 4
    assert resumed_calls == [
        "court-sim-study:season-0003",
        "court-sim-study:season-0004",
    ]
    assert receipt.file_sha256 == sha256_file(path)


def test_checkpoint_budget_and_spec_identity_are_enforced(tmp_path: Path) -> None:
    path = tmp_path / "checkpoint.json"
    spec = QuickSimBatchSpec("study", 7, 3)
    partial, receipt = run_quick_sim_checkpoint(
        spec,
        _summary,
        path,
        maximum_new_seasons=1,
    )
    assert len(partial.cells) == 1
    assert not receipt.complete
    with pytest.raises(QuickSimBatchError, match="spec differs"):
        run_quick_sim_checkpoint(QuickSimBatchSpec("other", 7, 3), _summary, path)
    with pytest.raises(QuickSimBatchError, match="positive"):
        run_quick_sim_checkpoint(spec, _summary, path, maximum_new_seasons=0)


def test_complete_checkpoint_exports_hash_verified_observed_reference(tmp_path: Path) -> None:
    checkpoint = tmp_path / "checkpoint.json"
    result, _ = run_quick_sim_checkpoint(
        QuickSimBatchSpec("observed", 9, 3),
        _summary,
        checkpoint,
    )
    target = tmp_path / "reference.json"
    reference, receipt = write_observed_quick_sim_reference(
        result,
        target,
        reference_id="2k-observed",
        source_label="controlled exports",
        game_version="exact-build",
        roster_date="2026-07-26",
    )
    assert load_quick_sim_reference(target.read_text(encoding="utf-8")) == reference
    assert receipt.observed_seasons == 3
    assert receipt.file_sha256 == sha256_file(target)

    partial, _ = run_quick_sim_checkpoint(
        QuickSimBatchSpec("partial", 9, 2),
        _summary,
        tmp_path / "partial.json",
        maximum_new_seasons=1,
    )
    with pytest.raises(QuickSimBatchError, match="complete"):
        write_observed_quick_sim_reference(
            partial,
            target,
            reference_id="invalid",
            source_label="source",
            game_version="build",
            roster_date="2026-07-26",
        )

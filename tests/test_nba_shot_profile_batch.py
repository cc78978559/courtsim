import json
from pathlib import Path

import pytest

from courtsim.analysis.nba_shot_profile_batch import (
    NbaShotProfileBatchError,
    inspect_nba_shot_profile_batch,
    run_nba_shot_profile_batch,
)
from courtsim.artifacts import write_json
from courtsim.cli import main
from courtsim.domain.game import GameClockConfig


def _evaluation() -> dict[str, object]:
    return {
        "schema_version": 1,
        "profile_id": "profile",
        "season": "2024-25",
        "teams": 1,
        "status": "improved",
        "baseline_rmse": 0.1,
        "candidate_rmse": 0.05,
        "zone_rmse": [
            {"zone": zone, "baseline": 0.1, "candidate": 0.05, "improvement": 0.05}
            for zone in ("RIM", "MIDRANGE", "THREE")
        ],
        "team_results": [
            {
                "team_id": "A",
                "baseline_rmse": 0.1,
                "candidate_rmse": 0.05,
                "rmse_improvement": 0.05,
            }
        ],
    }


def test_batch_checkpoints_resumes_and_verifies_cells(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    inputs = []
    for name in ("profile", "schema", "parameters", "lineup"):
        path = tmp_path / f"{name}.json"
        path.write_text("{}", encoding="utf-8")
        inputs.append(path)
    calls: list[int] = []

    def fake_runner(**kwargs: object) -> dict[str, object]:
        output = Path(str(kwargs["output_directory"]))
        seed = kwargs["seed"]
        assert isinstance(seed, int)
        calls.append(seed)
        summary = {"status": "improved", "games": 1}
        write_json(output / "evaluation.json", _evaluation())
        write_json(output / "manifest.json", {"summary": summary, "seed": seed})
        return {"summary": summary}

    def run(maximum_new_runs: int | None = None, workers: int = 1) -> dict[str, object]:
        return run_nba_shot_profile_batch(
            profile_path=inputs[0],
            schema_path=inputs[1],
            parameters_path=inputs[2],
            lineup_path=inputs[3],
            output_directory=tmp_path / "batch",
            master_seed=7,
            runs=2,
            game_config=GameClockConfig(1, 120, 24, 60, overtime_enabled=True),
            maximum_new_runs=maximum_new_runs,
            workers=workers,
            experiment_runner=fake_runner,
        )

    with pytest.raises(NbaShotProfileBatchError, match="workers must be positive"):
        run(workers=0)
    with pytest.raises(NbaShotProfileBatchError, match="require the default runner"):
        run(workers=2)

    first = run(1)
    assert first["completed_runs"] == 1
    assert first["complete"] is False
    second = run(1)
    assert second["completed_runs"] == 2
    assert second["complete"] is True
    assert len(calls) == 2
    assert (tmp_path / "batch" / "evaluation-batch.json").is_file()

    # A completed batch is a verified no-op: it does not rerun or rewrite artifacts.
    manifest_path = tmp_path / "batch" / "batch-manifest.json"
    aggregate_path = tmp_path / "batch" / "evaluation-batch.json"
    manifest_mtime = manifest_path.stat().st_mtime_ns
    aggregate_mtime = aggregate_path.stat().st_mtime_ns
    assert run() == second
    assert len(calls) == 2
    assert manifest_path.stat().st_mtime_ns == manifest_mtime
    assert aggregate_path.stat().st_mtime_ns == aggregate_mtime
    inspection = inspect_nba_shot_profile_batch(manifest_path)
    assert inspection["artifact_hashes_ok"] is True
    assert inspection["completed_runs"] == 2
    assert inspection["remaining_runs"] == 0
    assert main(["nba-shot-profile-batch-status", str(manifest_path)]) == 0
    assert json.loads(capsys.readouterr().out)["complete"] is True

    completed_cells = second["cells"]
    assert isinstance(completed_cells, list)
    assert all(isinstance(cell, dict) for cell in completed_cells)
    copied_cells = [dict(cell) for cell in completed_cells]
    copied_cells[0]["seed"] = -1
    tampered_manifest = {**second, "cells": copied_cells}
    write_json(manifest_path, tampered_manifest)
    with pytest.raises(NbaShotProfileBatchError, match="contiguous"):
        run()
    write_json(manifest_path, second)

    write_json(tmp_path / "batch" / "run-0001" / "evaluation.json", {"tampered": True})
    with pytest.raises(NbaShotProfileBatchError, match="hash differs"):
        run()


def test_batch_rejects_tampered_aggregate(tmp_path: Path) -> None:
    inputs = []
    for name in ("profile", "schema", "parameters", "lineup"):
        path = tmp_path / f"{name}.json"
        path.write_text("{}", encoding="utf-8")
        inputs.append(path)

    def fake_runner(**kwargs: object) -> dict[str, object]:
        output = Path(str(kwargs["output_directory"]))
        summary = {"status": "improved", "games": 1}
        write_json(output / "evaluation.json", _evaluation())
        write_json(output / "manifest.json", {"summary": summary})
        return {"summary": summary}

    def run() -> dict[str, object]:
        return run_nba_shot_profile_batch(
            profile_path=inputs[0],
            schema_path=inputs[1],
            parameters_path=inputs[2],
            lineup_path=inputs[3],
            output_directory=tmp_path / "batch",
            master_seed=7,
            runs=1,
            game_config=GameClockConfig(1, 120, 24, 60, overtime_enabled=True),
            experiment_runner=fake_runner,
        )

    run()
    write_json(tmp_path / "batch" / "evaluation-batch.json", {"tampered": True})
    with pytest.raises(NbaShotProfileBatchError, match="aggregate artifact differs"):
        run()

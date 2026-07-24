import json
from pathlib import Path

import pytest

from courtsim.analysis.experiment_matrix import run_experiment_matrix
from courtsim.analysis.matrix_robustness import (
    MatrixRobustnessError,
    run_matrix_robustness,
)
from courtsim.artifacts import sha256_file
from courtsim.cli import main
from courtsim.randomness import derive_seed
from courtsim.verification import verify_manifest

ROOT = Path(__file__).parents[1]
SCHEMA = ROOT / "data" / "model_schema_demo_v1_3.json"
PARAMETERS = ROOT / "data" / "model_parameters_demo_0.4.0.json"
PROFILE = ROOT / "examples" / "player_profile_v1.json"
CORE_TARGETS = ROOT / "experiments" / "nba-2024-25-regular-season-core-v1.json"
CORE_SOURCE = ROOT / "experiments" / "sources" / "nba-2024-25-team-core.json"


def write_wide_target(path: Path) -> Path:
    source_directory = path.parent / "sources"
    source_directory.mkdir(parents=True)
    copied_source = source_directory / "nba-core.json"
    copied_source.write_bytes(CORE_SOURCE.read_bytes())
    payload = json.loads(CORE_TARGETS.read_text(encoding="utf-8"))
    metric = next(item for item in payload["metrics"] if item["metric"] == "mean_team_possessions")
    metric.update({"lower": 0.0, "target": 1.0, "upper": 2.0})
    payload["metrics"] = [metric]
    payload["target_set_id"] = "robustness-test-wide-active-v1"
    payload["sources"][0]["artifact_path"] = "sources/nba-core.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def write_matrix_spec(path: Path, targets: list[Path]) -> Path:
    payload = {
        "format_version": 1,
        "matrix_id": "robustness-test",
        "base_directory": ".",
        "master_seed": 919,
        "defaults": {
            "schema": str(SCHEMA),
            "profile": str(PROFILE),
            "games": 2,
            "workers": 1,
            "start_index": 0,
            "trace_mode": "aggregate-only",
            "clock": {
                "regulation_periods": 1,
                "period_seconds": 20,
                "possession_seconds": 10,
            },
        },
        "targets": [str(target) for target in targets],
        "cells": [
            {"cell_id": "alpha", "parameters": str(PARAMETERS)},
            {"cell_id": "beta", "parameters": str(PARAMETERS)},
        ],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_robustness_reuses_primary_and_ranks_independent_replicates(
    tmp_path: Path,
) -> None:
    target = write_wide_target(tmp_path / "wide-target.json")
    spec = write_matrix_spec(tmp_path / "matrix.json", [target])
    matrix_directory = tmp_path / "matrix-output"
    matrix_report = run_experiment_matrix(
        spec_path=spec,
        output_directory=matrix_directory,
    )
    output = tmp_path / "robustness"

    assert (
        main(
            [
                "matrix-robustness",
                str(matrix_report),
                "--output",
                str(output),
                "--replicates",
                "3",
            ]
        )
        == 0
    )

    report_path = output / "robustness-report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["recommendation"] == {
        "status": "tie",
        "candidate_cell_ids": ["alpha", "beta"],
        "automatic_promotion": False,
    }
    assert report["summary"] == {
        "cells": 2,
        "completed": 2,
        "failed": 0,
        "eligible": 2,
        "executed_replicates": 6,
        "reused_replicates": 0,
    }
    for cell in report["cells"]:
        assert cell["pass_rate"] == 1.0
        assert cell["maximum_center_weighted_rmse"] == 0.0
        assert cell["center_weighted_rmse_stddev"] == 0.0
        results = []
        for artifact in cell["replicate_results"]:
            result_path = output / artifact["path"]
            assert sha256_file(result_path) == artifact["sha256"]
            results.append(json.loads(result_path.read_text(encoding="utf-8")))
        assert results[0]["source"] == "matrix-primary"
        assert results[0]["seed"] != results[1]["seed"]
        assert results[1]["seed"] == derive_seed(
            results[0]["seed"],
            "robustness-replicate",
            1,
        )
        assert len({result["seed"] for result in results}) == 3
        for result in results:
            manifest = Path(result["manifest"])
            assert sha256_file(manifest) == result["manifest_sha256"]
            assert verify_manifest(manifest).ok


def test_robustness_requires_replicates_and_reports_no_active_target(
    tmp_path: Path,
) -> None:
    spec = write_matrix_spec(tmp_path / "matrix.json", [])
    payload = json.loads(spec.read_text(encoding="utf-8"))
    payload["cells"] = payload["cells"][:1]
    spec.write_text(json.dumps(payload), encoding="utf-8")
    matrix_report = run_experiment_matrix(
        spec_path=spec,
        output_directory=tmp_path / "matrix-output",
    )
    with pytest.raises(MatrixRobustnessError, match="at least 2"):
        run_matrix_robustness(
            matrix_report_path=matrix_report,
            output_directory=tmp_path / "invalid",
            replicates=1,
        )

    output = tmp_path / "robustness"
    assert (
        main(
            [
                "matrix-robustness",
                str(matrix_report),
                "--output",
                str(output),
                "--replicates",
                "2",
            ]
        )
        == 11
    )
    report = json.loads((output / "robustness-report.json").read_text(encoding="utf-8"))
    assert report["recommendation"]["status"] == "no-eligible-candidate"
    assert report["cells"][0]["pass_rate"] == 0.0
    assert report["cells"][0]["mean_center_weighted_rmse"] is None


def test_resume_reuses_verified_results_and_reruns_only_tampered_replicate(
    tmp_path: Path,
) -> None:
    target = write_wide_target(tmp_path / "wide-target.json")
    spec = write_matrix_spec(tmp_path / "matrix.json", [target])
    payload = json.loads(spec.read_text(encoding="utf-8"))
    payload["cells"] = payload["cells"][:1]
    spec.write_text(json.dumps(payload), encoding="utf-8")
    matrix_report = run_experiment_matrix(
        spec_path=spec,
        output_directory=tmp_path / "matrix-output",
    )
    output = tmp_path / "robustness"
    report_path = run_matrix_robustness(
        matrix_report_path=matrix_report,
        output_directory=output,
        replicates=3,
    )
    target_path = output / "cells" / "alpha" / "replicate-001" / "target-001.json"
    original_target_hash = sha256_file(target_path)
    target_payload = json.loads(target_path.read_text(encoding="utf-8"))
    target_payload["metric_results"][0]["value"] = 999.0
    target_path.write_text(json.dumps(target_payload), encoding="utf-8")

    resumed_path = run_matrix_robustness(
        matrix_report_path=matrix_report,
        output_directory=output,
        replicates=3,
        resume=True,
    )
    assert resumed_path == report_path
    resumed = json.loads(report_path.read_text(encoding="utf-8"))
    assert resumed["summary"]["executed_replicates"] == 1
    assert resumed["summary"]["reused_replicates"] == 2
    assert sha256_file(target_path) == original_target_hash

    with pytest.raises(MatrixRobustnessError, match="does not match resume plan"):
        run_matrix_robustness(
            matrix_report_path=matrix_report,
            output_directory=output,
            replicates=4,
            resume=True,
        )

    report_path.unlink()
    run_matrix_robustness(
        matrix_report_path=matrix_report,
        output_directory=output,
        replicates=3,
        resume=True,
    )
    recovered = json.loads(report_path.read_text(encoding="utf-8"))
    assert recovered["summary"]["executed_replicates"] == 0
    assert recovered["summary"]["reused_replicates"] == 3

import json
from pathlib import Path

import pytest

from courtsim.analysis.experiment_matrix import (
    ExperimentMatrixError,
    load_experiment_matrix,
    run_experiment_matrix,
)
from courtsim.cli import main
from courtsim.verification import verify_manifest

ROOT = Path(__file__).parents[1]
SCHEMA = ROOT / "data" / "model_schema_demo_v1_3.json"
PARAMETERS = ROOT / "data" / "model_parameters_demo_0.4.0.json"
PROFILE = ROOT / "examples" / "player_profile_v1.json"
OPPONENT_PROFILE = ROOT / "examples" / "calibration_lineup_v1.json"
TARGETS = ROOT / "experiments" / "nba-2024-25-regular-season-core-v1.json"


def spec_payload(cells: list[dict[str, object]]) -> dict[str, object]:
    return {
        "format_version": 1,
        "matrix_id": "test-matrix",
        "base_directory": ".",
        "master_seed": 818,
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
        "targets": [str(TARGETS)],
        "cells": cells,
    }


def write_spec(path: Path, cells: list[dict[str, object]]) -> Path:
    path.write_text(json.dumps(spec_payload(cells)), encoding="utf-8")
    return path


def test_matrix_executes_scores_verifies_and_resumes(tmp_path: Path) -> None:
    spec = write_spec(
        tmp_path / "matrix.json",
        [
            {"cell_id": "first", "parameters": str(PARAMETERS)},
            {"cell_id": "second", "parameters": str(PARAMETERS)},
        ],
    )
    output = tmp_path / "output"
    report_path = run_experiment_matrix(spec_path=spec, output_directory=output)
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["status"] == "completed"
    assert report["summary"] == {
        "cells": 2,
        "completed": 2,
        "failed": 0,
        "reused": 0,
    }
    for row in report["cells"]:
        result_path = output / row["result"]
        result = json.loads(result_path.read_text(encoding="utf-8"))
        assert verify_manifest(result_path.parent / result["manifest"]).ok
        assert result["targets"][0]["target_set_id"]

    resumed = run_experiment_matrix(spec_path=spec, output_directory=output, resume=True)
    resumed_report = json.loads(resumed.read_text(encoding="utf-8"))
    assert resumed_report["summary"]["reused"] == 2
    assert {row["execution"] for row in resumed_report["cells"]} == {"reused"}


def test_matrix_isolates_failed_cells_and_cli_returns_eight(tmp_path: Path) -> None:
    spec = write_spec(
        tmp_path / "matrix.json",
        [
            {"cell_id": "broken", "parameters": str(tmp_path / "missing.json")},
            {"cell_id": "healthy", "parameters": str(PARAMETERS)},
        ],
    )
    output = tmp_path / "output"
    assert main(["experiment-matrix", str(spec), "--output", str(output)]) == 8
    report = json.loads((output / "matrix-report.json").read_text(encoding="utf-8"))
    assert report["status"] == "partial"
    assert report["summary"]["completed"] == 1
    assert report["summary"]["failed"] == 1
    broken = json.loads(
        (output / "cells" / "broken" / "cell-result.json").read_text(encoding="utf-8")
    )
    assert broken["status"] == "failed"
    assert broken["error_type"] == "FileNotFoundError"


def test_matrix_rejects_duplicate_cell_ids(tmp_path: Path) -> None:
    spec = write_spec(
        tmp_path / "matrix.json",
        [
            {"cell_id": "same", "parameters": str(PARAMETERS)},
            {"cell_id": "same", "parameters": str(PARAMETERS)},
        ],
    )
    with pytest.raises(ExperimentMatrixError, match="unique"):
        load_experiment_matrix(spec)


def test_matrix_rejects_invalid_seed_group(tmp_path: Path) -> None:
    spec = write_spec(
        tmp_path / "matrix.json",
        [
            {
                "cell_id": "first",
                "parameters": str(PARAMETERS),
                "seed_group": "NOT VALID",
            },
        ],
    )
    with pytest.raises(ExperimentMatrixError, match="seed_group"):
        load_experiment_matrix(spec)


def test_matrix_cell_can_override_default_targets(tmp_path: Path) -> None:
    spec = write_spec(
        tmp_path / "matrix.json",
        [
            {
                "cell_id": "first",
                "parameters": str(PARAMETERS),
                "targets": [str(TARGETS)],
            }
        ],
    )
    matrix = load_experiment_matrix(spec)
    assert matrix.cells[0].target_paths == (TARGETS.resolve(),)


def test_matrix_rejects_empty_cell_target_override(tmp_path: Path) -> None:
    spec = write_spec(
        tmp_path / "matrix.json",
        [
            {
                "cell_id": "first",
                "parameters": str(PARAMETERS),
                "targets": [],
            }
        ],
    )
    with pytest.raises(ExperimentMatrixError, match="non-empty"):
        load_experiment_matrix(spec)


def test_matrix_records_and_executes_a_distinct_opponent_profile(
    tmp_path: Path,
) -> None:
    spec = write_spec(
        tmp_path / "matrix.json",
        [
            {
                "cell_id": "first",
                "parameters": str(PARAMETERS),
                "opponent_profile": str(OPPONENT_PROFILE),
            }
        ],
    )
    matrix = load_experiment_matrix(spec)
    assert matrix.cells[0].opponent_profile_path == OPPONENT_PROFILE.resolve()
    report = run_experiment_matrix(
        spec_path=spec,
        output_directory=tmp_path / "output",
    )
    report_payload = json.loads(report.read_text(encoding="utf-8"))
    result_path = report.parent / report_payload["cells"][0]["result"]
    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert result["plan"]["inputs"]["opponent_profile"]["path"] == str(OPPONENT_PROFILE.resolve())
    manifest = json.loads((result_path.parent / result["manifest"]).read_text(encoding="utf-8"))
    assert len(manifest["inputs"]) == 4

import json
from pathlib import Path

import pytest

from courtsim.analysis.experiment_matrix import run_experiment_matrix
from courtsim.analysis.matrix_contrast import (
    MatrixContrastError,
    load_matrix_contrast_spec,
)
from courtsim.analysis.matrix_robustness import run_matrix_robustness
from courtsim.cli import main

ROOT = Path(__file__).parents[1]
SCHEMA = ROOT / "data" / "model_schema_demo_v1_3.json"
PARAMETERS = ROOT / "data" / "model_parameters_demo_0.4.0.json"
PROFILE = ROOT / "examples" / "player_profile_v1.json"


def write_matrix_spec(path: Path, *, paired: bool) -> Path:
    cells = [
        {"cell_id": "baseline", "parameters": str(PARAMETERS)},
        {"cell_id": "candidate", "parameters": str(PARAMETERS)},
    ]
    if paired:
        for cell in cells:
            cell["seed_group"] = "paired-a"
    payload = {
        "format_version": 1,
        "matrix_id": "contrast-test",
        "base_directory": ".",
        "master_seed": 1717,
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
        "targets": [],
        "cells": cells,
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def write_contrast_spec(path: Path, *, minimum: float, maximum: float) -> Path:
    payload = {
        "format_version": 1,
        "kind": "courtsim-matrix-contrast-spec",
        "contrast_set_id": "identical-cells",
        "comparisons": [
            {
                "contrast_id": "candidate-vs-baseline",
                "baseline_cell_id": "baseline",
                "candidate_cell_id": "candidate",
                "gates": [
                    {
                        "metric": "field_goal_percentage",
                        "minimum_delta": minimum,
                        "maximum_delta": maximum,
                    },
                    {
                        "metric": "shot_zone_share.THREE",
                        "minimum_delta": minimum,
                        "maximum_delta": maximum,
                    },
                ],
            }
        ],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_paired_seed_contrast_passes_exact_zero_delta(tmp_path: Path) -> None:
    matrix_spec = write_matrix_spec(tmp_path / "matrix.json", paired=True)
    matrix_output = tmp_path / "matrix-output"
    matrix_report = run_experiment_matrix(
        spec_path=matrix_spec,
        output_directory=matrix_output,
    )
    baseline_result = json.loads(
        (matrix_output / "cells" / "baseline" / "cell-result.json").read_text(encoding="utf-8")
    )
    candidate_result = json.loads(
        (matrix_output / "cells" / "candidate" / "cell-result.json").read_text(encoding="utf-8")
    )
    assert baseline_result["plan"]["seed_group"] == "paired-a"
    assert baseline_result["plan"]["seed"] == candidate_result["plan"]["seed"]

    contrast_spec = write_contrast_spec(tmp_path / "contrast.json", minimum=0.0, maximum=0.0)
    output = tmp_path / "contrast-output"
    assert (
        main(
            [
                "matrix-contrast",
                str(matrix_report),
                str(contrast_spec),
                "--output",
                str(output),
            ]
        )
        == 0
    )
    report = json.loads((output / "contrast-report.json").read_text(encoding="utf-8"))
    assert report["status"] == "passed"
    assert report["summary"] == {
        "comparisons": 1,
        "completed": 1,
        "execution_failures": 0,
        "passed": 1,
        "failed_gates": 0,
    }
    assert all(gate["delta"] == 0.0 for gate in report["comparisons"][0]["gates"])
    assert report["policy"]["automatic_promotion"] is False


def test_contrast_rejects_unpaired_cells_and_reports_gate_failures(tmp_path: Path) -> None:
    unpaired_spec = write_matrix_spec(tmp_path / "unpaired-matrix.json", paired=False)
    unpaired_report = run_experiment_matrix(
        spec_path=unpaired_spec,
        output_directory=tmp_path / "unpaired-matrix-output",
    )
    contrast_spec = write_contrast_spec(tmp_path / "contrast.json", minimum=0.0, maximum=0.0)
    unpaired_output = tmp_path / "unpaired-contrast-output"
    assert (
        main(
            [
                "matrix-contrast",
                str(unpaired_report),
                str(contrast_spec),
                "--output",
                str(unpaired_output),
            ]
        )
        == 12
    )
    unpaired = json.loads((unpaired_output / "contrast-report.json").read_text(encoding="utf-8"))
    assert unpaired["summary"]["execution_failures"] == 1
    assert "seed_group" in unpaired["comparisons"][0]["error"]

    paired_spec = write_matrix_spec(tmp_path / "paired-matrix.json", paired=True)
    paired_report = run_experiment_matrix(
        spec_path=paired_spec,
        output_directory=tmp_path / "paired-matrix-output",
    )
    failing_spec = write_contrast_spec(
        tmp_path / "failing-contrast.json",
        minimum=0.1,
        maximum=1.0,
    )
    failing_output = tmp_path / "failing-contrast-output"
    assert (
        main(
            [
                "matrix-contrast",
                str(paired_report),
                str(failing_spec),
                "--output",
                str(failing_output),
            ]
        )
        == 12
    )
    failing = json.loads((failing_output / "contrast-report.json").read_text(encoding="utf-8"))
    assert failing["summary"]["execution_failures"] == 0
    assert failing["summary"]["failed_gates"] == 2


def test_contrast_spec_rejects_inverted_bounds(tmp_path: Path) -> None:
    spec = write_contrast_spec(tmp_path / "contrast.json", minimum=1.0, maximum=-1.0)
    with pytest.raises(MatrixContrastError, match="inverted"):
        load_matrix_contrast_spec(spec)


def test_contrast_robustness_pairs_replicates_and_rejects_tampered_audit(
    tmp_path: Path,
) -> None:
    matrix_spec = write_matrix_spec(tmp_path / "matrix.json", paired=True)
    matrix_report = run_experiment_matrix(
        spec_path=matrix_spec,
        output_directory=tmp_path / "matrix-output",
    )
    robustness_directory = tmp_path / "robustness"
    robustness_report = run_matrix_robustness(
        matrix_report_path=matrix_report,
        output_directory=robustness_directory,
        replicates=3,
    )
    contrast_spec = write_contrast_spec(
        tmp_path / "contrast.json",
        minimum=0.0,
        maximum=0.0,
    )
    output = tmp_path / "contrast-robustness.json"
    assert (
        main(
            [
                "matrix-contrast-robustness",
                str(robustness_report),
                str(contrast_spec),
                "--output",
                str(output),
            ]
        )
        == 0
    )
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["status"] == "passed"
    assert report["summary"]["passed"] == 1
    assert all(gate["pass_rate"] == 1.0 for gate in report["comparisons"][0]["gates"])
    assert all(gate["delta_stddev"] == 0.0 for gate in report["comparisons"][0]["gates"])

    robustness = json.loads(robustness_report.read_text(encoding="utf-8"))
    candidate = next(cell for cell in robustness["cells"] if cell["cell_id"] == "candidate")
    result_path = robustness_directory / candidate["replicate_results"][1]["path"]
    result = json.loads(result_path.read_text(encoding="utf-8"))
    audit_path = Path(result["audit"])
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    audit["mean_team_score"] += 1.0
    audit_path.write_text(json.dumps(audit), encoding="utf-8")

    tampered_output = tmp_path / "tampered-contrast-robustness.json"
    assert (
        main(
            [
                "matrix-contrast-robustness",
                str(robustness_report),
                str(contrast_spec),
                "--output",
                str(tampered_output),
            ]
        )
        == 13
    )
    tampered = json.loads(tampered_output.read_text(encoding="utf-8"))
    assert tampered["summary"]["execution_failures"] == 1
    assert "artifacts changed" in tampered["comparisons"][0]["error"]

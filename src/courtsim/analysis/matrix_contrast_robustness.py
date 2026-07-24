"""Multi-seed aggregation for paired matrix counterfactual gates."""

from __future__ import annotations

import json
import math
import statistics
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from courtsim.analysis.audit_gates import audit_metric_map, load_distribution_audit
from courtsim.analysis.matrix_contrast import (
    MatrixContrastError,
    load_matrix_contrast_spec,
)
from courtsim.artifacts import sha256_file, write_json
from courtsim.verification import verify_manifest


class MatrixContrastRobustnessError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class VerifiedReplicate:
    replicate: int
    seed: int
    audit_path: Path
    audit_sha256: str
    manifest: dict[str, Any]


def _load_object(path: Path, context: str) -> dict[str, Any]:
    try:
        raw: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise MatrixContrastRobustnessError(f"cannot load {context}: {path}") from error
    if not isinstance(raw, dict):
        raise MatrixContrastRobustnessError(f"{context} must contain an object")
    return cast(dict[str, Any], raw)


def _contained_path(root: Path, relative: object, context: str) -> Path:
    if not isinstance(relative, str):
        raise MatrixContrastRobustnessError(f"{context} path is invalid")
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()):
        raise MatrixContrastRobustnessError(f"{context} path escapes report directory")
    return path


def _verified_replicates(
    *,
    report_directory: Path,
    cell: dict[str, Any],
    expected_replicates: int,
) -> dict[int, VerifiedReplicate]:
    cell_id = cell.get("cell_id")
    raw_artifacts = cell.get("replicate_results")
    if (
        cell.get("status") != "completed"
        or not isinstance(cell_id, str)
        or not isinstance(raw_artifacts, list)
        or len(raw_artifacts) != expected_replicates
    ):
        raise MatrixContrastRobustnessError(f"cell {cell_id} replicate list is invalid")
    verified: dict[int, VerifiedReplicate] = {}
    for artifact_index, raw_artifact in enumerate(raw_artifacts):
        if not isinstance(raw_artifact, dict):
            raise MatrixContrastRobustnessError(
                f"cell {cell_id} replicate artifact {artifact_index} is invalid"
            )
        result_path = _contained_path(
            report_directory,
            raw_artifact.get("path"),
            f"cell {cell_id} replicate {artifact_index}",
        )
        expected_result_hash = raw_artifact.get("sha256")
        if (
            not isinstance(expected_result_hash, str)
            or not result_path.is_file()
            or sha256_file(result_path) != expected_result_hash
        ):
            raise MatrixContrastRobustnessError(
                f"cell {cell_id} replicate {artifact_index} result changed"
            )
        result = _load_object(result_path, "replicate result")
        replicate = result.get("replicate")
        seed = result.get("seed")
        if (
            result.get("cell_id") != cell_id
            or not isinstance(replicate, int)
            or isinstance(replicate, bool)
            or replicate < 0
            or not isinstance(seed, int)
            or isinstance(seed, bool)
        ):
            raise MatrixContrastRobustnessError(
                f"cell {cell_id} replicate {artifact_index} identity is invalid"
            )
        if replicate in verified:
            raise MatrixContrastRobustnessError(f"cell {cell_id} replicate IDs are duplicated")
        raw_manifest = result.get("manifest")
        raw_audit = result.get("audit")
        if not isinstance(raw_manifest, str) or not isinstance(raw_audit, str):
            raise MatrixContrastRobustnessError(
                f"cell {cell_id} replicate {replicate} paths are invalid"
            )
        manifest_path = Path(raw_manifest)
        audit_path = Path(raw_audit)
        if (
            not manifest_path.is_file()
            or sha256_file(manifest_path) != result.get("manifest_sha256")
            or not audit_path.is_file()
            or sha256_file(audit_path) != result.get("audit_sha256")
        ):
            raise MatrixContrastRobustnessError(
                f"cell {cell_id} replicate {replicate} artifacts changed"
            )
        verification = verify_manifest(manifest_path)
        if not verification.ok:
            raise MatrixContrastRobustnessError(
                f"cell {cell_id} replicate {replicate} manifest failed"
            )
        manifest = _load_object(manifest_path, "replicate manifest")
        if manifest.get("master_seed") != seed:
            raise MatrixContrastRobustnessError(
                f"cell {cell_id} replicate {replicate} seed mismatch"
            )
        verified[replicate] = VerifiedReplicate(
            replicate,
            seed,
            audit_path,
            sha256_file(audit_path),
            manifest,
        )
    if set(verified) != set(range(expected_replicates)):
        raise MatrixContrastRobustnessError(f"cell {cell_id} replicate IDs are incomplete")
    return verified


def _pair_error(
    baseline: VerifiedReplicate,
    candidate: VerifiedReplicate,
) -> str | None:
    if baseline.seed != candidate.seed:
        return "paired replicate seeds differ"
    for field in ("game_indices", "clock"):
        if baseline.manifest.get(field) != candidate.manifest.get(field):
            return f"paired replicate manifests differ in {field}"
    return None


def run_matrix_contrast_robustness(
    *,
    robustness_report_path: str | Path,
    spec_path: str | Path,
    output_path: str | Path,
    minimum_pass_rate: float = 1.0,
) -> Path:
    if (
        not isinstance(minimum_pass_rate, (int, float))
        or isinstance(minimum_pass_rate, bool)
        or not math.isfinite(minimum_pass_rate)
        or not 0.0 <= minimum_pass_rate <= 1.0
    ):
        raise MatrixContrastRobustnessError("minimum_pass_rate must be within [0, 1]")
    robustness_path = Path(robustness_report_path).resolve()
    contrast_spec_path = Path(spec_path).resolve()
    destination = Path(output_path)
    if destination.exists():
        raise MatrixContrastRobustnessError(f"output already exists: {destination}")
    robustness = _load_object(robustness_path, "matrix robustness report")
    if robustness.get("kind") != "courtsim-matrix-robustness":
        raise MatrixContrastRobustnessError("unsupported robustness report kind")
    configuration = robustness.get("configuration")
    raw_cells = robustness.get("cells")
    if not isinstance(configuration, dict) or not isinstance(raw_cells, list):
        raise MatrixContrastRobustnessError("robustness report structure is invalid")
    replicates = configuration.get("replicates")
    if not isinstance(replicates, int) or isinstance(replicates, bool) or replicates < 2:
        raise MatrixContrastRobustnessError("robustness replicate count is invalid")
    try:
        spec = load_matrix_contrast_spec(contrast_spec_path)
    except MatrixContrastError as error:
        raise MatrixContrastRobustnessError(str(error)) from error
    cells = {
        str(cell.get("cell_id")): cast(dict[str, Any], cell)
        for cell in raw_cells
        if isinstance(cell, dict) and isinstance(cell.get("cell_id"), str)
    }
    verified_cache: dict[str, dict[int, VerifiedReplicate]] = {}

    def verified_cell(cell_id: str) -> dict[int, VerifiedReplicate]:
        if cell_id not in verified_cache:
            verified_cache[cell_id] = _verified_replicates(
                report_directory=robustness_path.parent,
                cell=cells[cell_id],
                expected_replicates=replicates,
            )
        return verified_cache[cell_id]

    comparison_rows: list[dict[str, Any]] = []
    for comparison in spec.comparisons:
        try:
            baseline = verified_cell(comparison.baseline_cell_id)
            candidate = verified_cell(comparison.candidate_cell_id)
            gate_deltas: dict[str, list[float]] = {gate.metric: [] for gate in comparison.gates}
            gate_passes: dict[str, int] = {gate.metric: 0 for gate in comparison.gates}
            replicate_rows: list[dict[str, Any]] = []
            for replicate_index in range(replicates):
                baseline_replicate = baseline[replicate_index]
                candidate_replicate = candidate[replicate_index]
                pair_error = _pair_error(baseline_replicate, candidate_replicate)
                if pair_error is not None:
                    raise MatrixContrastRobustnessError(
                        f"replicate {replicate_index}: {pair_error}"
                    )
                baseline_metrics = audit_metric_map(
                    load_distribution_audit(baseline_replicate.audit_path)
                )
                candidate_metrics = audit_metric_map(
                    load_distribution_audit(candidate_replicate.audit_path)
                )
                if set(baseline_metrics) != set(candidate_metrics):
                    raise MatrixContrastRobustnessError(
                        f"replicate {replicate_index}: audit metric sets differ"
                    )
                unknown = sorted(
                    gate.metric for gate in comparison.gates if gate.metric not in baseline_metrics
                )
                if unknown:
                    raise MatrixContrastRobustnessError(
                        f"replicate {replicate_index}: unknown metrics {unknown}"
                    )
                replicate_gates = []
                for gate in comparison.gates:
                    delta = candidate_metrics[gate.metric] - baseline_metrics[gate.metric]
                    replicate_gate_passed = gate.minimum_delta <= delta <= gate.maximum_delta
                    gate_deltas[gate.metric].append(delta)
                    gate_passes[gate.metric] += replicate_gate_passed
                    replicate_gates.append(
                        {
                            "metric": gate.metric,
                            "delta": delta,
                            "passed": replicate_gate_passed,
                        }
                    )
                replicate_rows.append(
                    {
                        "replicate": replicate_index,
                        "seed": baseline_replicate.seed,
                        "baseline_audit_sha256": baseline_replicate.audit_sha256,
                        "candidate_audit_sha256": candidate_replicate.audit_sha256,
                        "passed": all(row["passed"] for row in replicate_gates),
                        "gates": replicate_gates,
                    }
                )
            gate_rows = []
            for gate in comparison.gates:
                deltas = gate_deltas[gate.metric]
                pass_rate = gate_passes[gate.metric] / replicates
                gate_rows.append(
                    {
                        "metric": gate.metric,
                        "minimum_delta": gate.minimum_delta,
                        "maximum_delta": gate.maximum_delta,
                        "passed_replicates": gate_passes[gate.metric],
                        "replicates": replicates,
                        "pass_rate": pass_rate,
                        "mean_delta": statistics.fmean(deltas),
                        "minimum_observed_delta": min(deltas),
                        "maximum_observed_delta": max(deltas),
                        "delta_stddev": statistics.pstdev(deltas),
                        "passed": pass_rate >= minimum_pass_rate,
                    }
                )
            comparison_rows.append(
                {
                    "contrast_id": comparison.contrast_id,
                    "status": "completed",
                    "passed": all(row["passed"] for row in gate_rows),
                    "baseline_cell_id": comparison.baseline_cell_id,
                    "candidate_cell_id": comparison.candidate_cell_id,
                    "replicates": replicates,
                    "minimum_pass_rate": minimum_pass_rate,
                    "gates": gate_rows,
                    "replicate_results": replicate_rows,
                }
            )
        except (KeyError, ValueError) as error:
            comparison_rows.append(
                {
                    "contrast_id": comparison.contrast_id,
                    "status": "failed",
                    "passed": False,
                    "baseline_cell_id": comparison.baseline_cell_id,
                    "candidate_cell_id": comparison.candidate_cell_id,
                    "error_type": type(error).__name__,
                    "error": str(error),
                }
            )
    completed = [row for row in comparison_rows if row["status"] == "completed"]
    passed_comparisons = [row for row in completed if row["passed"]]
    write_json(
        destination,
        {
            "format_version": 1,
            "kind": "courtsim-matrix-contrast-robustness",
            "contrast_set_id": spec.contrast_set_id,
            "source": {
                "robustness_report": str(robustness_path),
                "robustness_report_sha256": sha256_file(robustness_path),
                "contrast_spec": str(contrast_spec_path),
                "contrast_spec_sha256": sha256_file(contrast_spec_path),
            },
            "policy": {
                "minimum_pass_rate": minimum_pass_rate,
                "paired_replicate_seed_required": True,
                "automatic_promotion": False,
            },
            "status": ("passed" if len(passed_comparisons) == len(comparison_rows) else "failed"),
            "summary": {
                "comparisons": len(comparison_rows),
                "completed": len(completed),
                "execution_failures": len(comparison_rows) - len(completed),
                "passed": len(passed_comparisons),
                "failed_gates": sum(
                    sum(not gate["passed"] for gate in row["gates"]) for row in completed
                ),
            },
            "comparisons": comparison_rows,
        },
    )
    return destination

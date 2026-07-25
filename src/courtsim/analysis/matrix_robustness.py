"""Multi-seed robustness audits for completed experiment matrices."""

from __future__ import annotations

import json
import math
import statistics
from dataclasses import asdict
from pathlib import Path
from typing import Any, cast

from courtsim.analysis.audit_gates import load_distribution_audit
from courtsim.analysis.matrix_ranking import (
    MatrixRankingError,
    center_error_components,
    rank_experiment_matrix,
)
from courtsim.analysis.model_audit_runner import run_model_audit_to_directory
from courtsim.analysis.realism_targets import (
    load_realism_target_set,
    realism_score_report_to_json,
    score_audit_against_realism_targets,
)
from courtsim.artifacts import sha256_file, write_json
from courtsim.domain.game import GameClockConfig
from courtsim.model.trace_mode import TraceMode
from courtsim.randomness import derive_seed
from courtsim.verification import verify_manifest


class MatrixRobustnessError(ValueError):
    pass


def _load_object(path: Path, context: str) -> dict[str, Any]:
    try:
        raw: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise MatrixRobustnessError(f"cannot load {context}: {path}") from error
    if not isinstance(raw, dict):
        raise MatrixRobustnessError(f"{context} must contain an object")
    return cast(dict[str, Any], raw)


def _path_from_plan(raw: object, context: str) -> Path:
    if not isinstance(raw, dict) or not isinstance(raw.get("path"), str):
        raise MatrixRobustnessError(f"{context} path is invalid")
    path = Path(raw["path"])
    if not path.is_file() or sha256_file(path) != raw.get("sha256"):
        raise MatrixRobustnessError(f"{context} is missing or changed")
    return path


def _score_replicate(
    *,
    audit_path: Path,
    target_paths: tuple[Path, ...],
    output_directory: Path,
    validate_existing: bool = False,
) -> dict[str, Any]:
    audit = load_distribution_audit(audit_path)
    targets: list[dict[str, Any]] = []
    weighted_squared = 0.0
    total_weight = 0.0
    active_targets = 0
    failed_active_targets = 0
    required_failures = 0
    worst_normalized_distance = 0.0
    for index, target_path in enumerate(target_paths, start=1):
        report = score_audit_against_realism_targets(
            audit,
            load_realism_target_set(target_path),
        )
        payload = json.loads(realism_score_report_to_json(report))
        score_path = output_directory / f"target-{index:03d}.json"
        if validate_existing:
            if _load_object(score_path, f"target score {index}") != payload:
                raise MatrixRobustnessError(f"target score changed: {score_path}")
        else:
            write_json(score_path, payload)
        squared, weight = center_error_components(
            payload,
            f"robustness target {report.target_set_id}",
        )
        weighted_squared += squared
        total_weight += weight
        if isinstance(report.gate_passed, bool):
            active_targets += 1
            failed_active_targets += not report.gate_passed
        required_failures += report.required_failures
        worst_normalized_distance = max(
            worst_normalized_distance,
            *(float(item["normalized_distance"]) for item in payload["metric_results"]),
        )
        targets.append(
            {
                "target_set_id": report.target_set_id,
                "path": score_path.name,
                "sha256": sha256_file(score_path),
                "gate_passed": report.gate_passed,
                "required_failures": report.required_failures,
                "weighted_rmse": report.weighted_rmse,
            }
        )
    center_rmse = math.sqrt(weighted_squared / total_weight) if total_weight else None
    passed = active_targets > 0 and failed_active_targets == 0 and required_failures == 0
    return {
        "passed": passed,
        "active_targets": active_targets,
        "failed_active_targets": failed_active_targets,
        "required_failures": required_failures,
        "worst_normalized_distance": worst_normalized_distance,
        "center_weighted_rmse": center_rmse,
        "targets": targets,
    }


def _replicate_seed(base_seed: int, index: int) -> int:
    return base_seed if index == 0 else derive_seed(base_seed, "robustness-replicate", index)


def _optional_float_sort_value(value: int | float | None) -> float:
    return math.inf if value is None else float(value)


def _configuration(
    *,
    replicates: int,
    minimum_pass_rate: float,
    maximum_worst_required_failures: int,
    maximum_center_rmse: float | None,
    maximum_center_rmse_stddev: float | None,
) -> dict[str, Any]:
    return {
        "replicates": replicates,
        "minimum_pass_rate": minimum_pass_rate,
        "maximum_worst_required_failures": maximum_worst_required_failures,
        "maximum_center_rmse": maximum_center_rmse,
        "maximum_center_rmse_stddev": maximum_center_rmse_stddev,
    }


def _validate_resume_report(
    *,
    report_path: Path,
    matrix_report: Path,
    configuration: dict[str, Any],
) -> None:
    report = _load_object(report_path, "existing robustness report")
    source = report.get("source")
    if (
        report.get("kind") != "courtsim-matrix-robustness"
        or not isinstance(source, dict)
        or source.get("matrix_report") != str(matrix_report)
        or source.get("matrix_report_sha256") != sha256_file(matrix_report)
        or report.get("configuration") != configuration
    ):
        raise MatrixRobustnessError("existing robustness report does not match resume plan")


def _manifest_matches_plan(
    *,
    manifest_path: Path,
    seed: int,
    schema_path: Path,
    parameters_path: Path,
    profile_path: Path,
    opponent_profile_path: Path,
    games: int,
    start_index: int,
    clock: GameClockConfig,
    trace_mode: TraceMode,
) -> bool:
    manifest = _load_object(manifest_path, "replicate manifest")
    expected_inputs = [
        {"path": str(path.resolve()), "sha256": sha256_file(path)}
        for path in (schema_path, parameters_path, profile_path)
    ]
    if opponent_profile_path != profile_path:
        expected_inputs.append(
            {
                "path": str(opponent_profile_path.resolve()),
                "sha256": sha256_file(opponent_profile_path),
            }
        )
    return (
        manifest.get("kind") == "courtsim-model-distribution-audit"
        and manifest.get("master_seed") == seed
        and manifest.get("game_indices") == list(range(start_index, start_index + games))
        and manifest.get("clock") == asdict(clock)
        and manifest.get("inputs") == expected_inputs
        and (
            manifest.get("artifact_mode")
            == (TraceMode.AGGREGATE_ONLY.value if trace_mode is TraceMode.AGGREGATE_ONLY else None)
        )
    )


def _reusable_replicate(
    *,
    result_path: Path,
    cell_id: str,
    replicate_index: int,
    source: str,
    seed: int,
    manifest_path: Path,
    audit_path: Path,
    schema_path: Path,
    parameters_path: Path,
    profile_path: Path,
    opponent_profile_path: Path,
    target_paths: tuple[Path, ...],
    games: int,
    start_index: int,
    clock: GameClockConfig,
    trace_mode: TraceMode,
    destination: Path,
) -> dict[str, Any] | None:
    if not result_path.is_file():
        return None
    try:
        result = _load_object(result_path, "replicate result")
        verification = verify_manifest(manifest_path)
        if (
            not verification.ok
            or not _manifest_matches_plan(
                manifest_path=manifest_path,
                seed=seed,
                schema_path=schema_path,
                parameters_path=parameters_path,
                profile_path=profile_path,
                opponent_profile_path=opponent_profile_path,
                games=games,
                start_index=start_index,
                clock=clock,
                trace_mode=trace_mode,
            )
            or not audit_path.is_file()
        ):
            return None
        scores = _score_replicate(
            audit_path=audit_path,
            target_paths=target_paths,
            output_directory=result_path.parent,
            validate_existing=True,
        )
        expected = {
            "format_version": 1,
            "cell_id": cell_id,
            "replicate": replicate_index,
            "source": source,
            "seed": seed,
            "manifest": str(manifest_path.resolve()),
            "manifest_sha256": sha256_file(manifest_path),
            "audit": str(audit_path.resolve()),
            "audit_sha256": sha256_file(audit_path),
            "manifest_verification": {
                "checked": verification.checked,
                "ok": verification.ok,
            },
            **scores,
        }
        if result != expected:
            return None
        return {
            **result,
            "result": result_path.relative_to(destination).as_posix(),
            "result_sha256": sha256_file(result_path),
        }
    except (KeyError, OSError, ValueError):
        return None


def run_matrix_robustness(
    *,
    matrix_report_path: str | Path,
    output_directory: str | Path,
    replicates: int,
    minimum_pass_rate: float = 1.0,
    maximum_worst_required_failures: int = 0,
    maximum_center_rmse: float | None = None,
    maximum_center_rmse_stddev: float | None = None,
    resume: bool = False,
) -> Path:
    if not isinstance(replicates, int) or isinstance(replicates, bool) or replicates < 2:
        raise MatrixRobustnessError("replicates must be an integer of at least 2")
    if not 0.0 <= minimum_pass_rate <= 1.0:
        raise MatrixRobustnessError("minimum_pass_rate must be within [0, 1]")
    if maximum_worst_required_failures < 0:
        raise MatrixRobustnessError("maximum_worst_required_failures must be non-negative")
    for value, name in (
        (maximum_center_rmse, "maximum_center_rmse"),
        (maximum_center_rmse_stddev, "maximum_center_rmse_stddev"),
    ):
        if value is not None and (not math.isfinite(value) or value < 0):
            raise MatrixRobustnessError(f"{name} must be finite and non-negative")

    matrix_report = Path(matrix_report_path).resolve()
    destination = Path(output_directory)
    report_path = destination / "robustness-report.json"
    configuration = _configuration(
        replicates=replicates,
        minimum_pass_rate=minimum_pass_rate,
        maximum_worst_required_failures=maximum_worst_required_failures,
        maximum_center_rmse=maximum_center_rmse,
        maximum_center_rmse_stddev=maximum_center_rmse_stddev,
    )
    if report_path.exists() and not resume:
        raise MatrixRobustnessError(f"robustness report already exists: {report_path}")
    if report_path.exists():
        _validate_resume_report(
            report_path=report_path,
            matrix_report=matrix_report,
            configuration=configuration,
        )
    source_ranking_path = destination / "source-ranking.json"
    try:
        rank_experiment_matrix(
            matrix_report_path=matrix_report,
            output_path=source_ranking_path,
        )
    except MatrixRankingError as error:
        raise MatrixRobustnessError(str(error)) from error
    source_ranking = _load_object(source_ranking_path, "source ranking")
    raw_candidates = source_ranking.get("ranking")
    if not isinstance(raw_candidates, list) or not raw_candidates:
        raise MatrixRobustnessError("source matrix has no completed candidates")

    cell_rows: list[dict[str, Any]] = []
    executed_replicates = 0
    reused_replicates = 0
    for candidate in raw_candidates:
        if not isinstance(candidate, dict):
            raise MatrixRobustnessError("source ranking candidate is invalid")
        cell_id = candidate.get("cell_id")
        raw_result_path = candidate.get("result_path")
        if not isinstance(cell_id, str) or not isinstance(raw_result_path, str):
            raise MatrixRobustnessError("source ranking candidate paths are invalid")
        try:
            source_result_path = matrix_report.parent / raw_result_path
            source_result = _load_object(source_result_path, f"cell {cell_id} result")
            plan = source_result["plan"]
            if not isinstance(plan, dict):
                raise MatrixRobustnessError(f"cell {cell_id} plan is invalid")
            inputs = plan["inputs"]
            if not isinstance(inputs, dict):
                raise MatrixRobustnessError(f"cell {cell_id} inputs are invalid")
            schema_path = _path_from_plan(inputs.get("schema"), f"cell {cell_id} schema")
            parameters_path = _path_from_plan(
                inputs.get("parameters"), f"cell {cell_id} parameters"
            )
            profile_path = _path_from_plan(inputs.get("profile"), f"cell {cell_id} profile")
            opponent_profile_path = (
                _path_from_plan(
                    inputs.get("opponent_profile"),
                    f"cell {cell_id} opponent profile",
                )
                if "opponent_profile" in inputs
                else profile_path
            )
            raw_target_paths = plan["targets"]
            if not isinstance(raw_target_paths, list):
                raise MatrixRobustnessError(f"cell {cell_id} targets are invalid")
            target_paths = tuple(
                _path_from_plan(raw, f"cell {cell_id} target {index}")
                for index, raw in enumerate(raw_target_paths)
            )
            clock_payload = plan["clock"]
            if not isinstance(clock_payload, dict):
                raise MatrixRobustnessError(f"cell {cell_id} clock is invalid")
            clock = GameClockConfig(
                clock_payload["regulation_periods"],
                clock_payload["period_seconds"],
                clock_payload["possession_seconds"],
                clock_payload.get("overtime_seconds", 300),
                clock_payload.get("max_overtimes", 8),
                clock_payload.get("overtime_enabled", False),
            )
            base_seed = int(plan["seed"])
            games = int(plan["games"])
            workers = int(plan["workers"])
            start_index = int(plan["start_index"])
            trace_mode = TraceMode(plan["trace_mode"])
            raw_team_tempo = plan.get("team_tempo", {})
            if not isinstance(raw_team_tempo, dict):
                raise MatrixRobustnessError(f"cell {cell_id} team tempo is invalid")
            home_tempo = int(raw_team_tempo.get("home", 50))
            away_tempo = int(raw_team_tempo.get("away", 50))
            replicate_rows: list[dict[str, Any]] = []
            for replicate_index in range(replicates):
                replicate_directory = (
                    destination / "cells" / cell_id / f"replicate-{replicate_index:03d}"
                )
                replicate_result_path = replicate_directory / "replicate-result.json"
                seed = _replicate_seed(base_seed, replicate_index)
                if replicate_index == 0:
                    manifest_path = source_result_path.parent / source_result["manifest"]
                    audit_path = source_result_path.parent / source_result["audit"]
                    source = "matrix-primary"
                else:
                    manifest_path = replicate_directory / "run" / "manifest.json"
                    audit_path = replicate_directory / "run" / "audit.json"
                    source = "robustness-run"
                existing = (
                    _reusable_replicate(
                        result_path=replicate_result_path,
                        cell_id=cell_id,
                        replicate_index=replicate_index,
                        source=source,
                        seed=seed,
                        manifest_path=manifest_path,
                        audit_path=audit_path,
                        schema_path=schema_path,
                        parameters_path=parameters_path,
                        profile_path=profile_path,
                        opponent_profile_path=opponent_profile_path,
                        target_paths=target_paths,
                        games=games,
                        start_index=start_index,
                        clock=clock,
                        trace_mode=trace_mode,
                        destination=destination,
                    )
                    if resume
                    else None
                )
                if existing is not None:
                    replicate_rows.append(existing)
                    reused_replicates += 1
                    continue
                if replicate_index != 0:
                    manifest_path = run_model_audit_to_directory(
                        schema_path=schema_path,
                        parameters_path=parameters_path,
                        profile_path=profile_path,
                        opponent_profile_path=opponent_profile_path,
                        home_tempo=home_tempo,
                        away_tempo=away_tempo,
                        output_directory=replicate_directory / "run",
                        master_seed=seed,
                        games=games,
                        start_index=start_index,
                        clock=clock,
                        workers=workers,
                        trace_mode=trace_mode,
                    )
                    audit_path = manifest_path.parent / "audit.json"
                verification = verify_manifest(manifest_path)
                if not verification.ok:
                    raise MatrixRobustnessError(
                        f"cell {cell_id} replicate {replicate_index} manifest failed"
                    )
                scores = _score_replicate(
                    audit_path=audit_path,
                    target_paths=target_paths,
                    output_directory=replicate_directory,
                )
                replicate_result = {
                    "format_version": 1,
                    "cell_id": cell_id,
                    "replicate": replicate_index,
                    "source": source,
                    "seed": seed,
                    "manifest": str(manifest_path.resolve()),
                    "manifest_sha256": sha256_file(manifest_path),
                    "audit": str(audit_path.resolve()),
                    "audit_sha256": sha256_file(audit_path),
                    "manifest_verification": {
                        "checked": verification.checked,
                        "ok": verification.ok,
                    },
                    **scores,
                }
                write_json(replicate_result_path, replicate_result)
                replicate_rows.append(
                    {
                        **replicate_result,
                        "result": replicate_result_path.relative_to(destination).as_posix(),
                        "result_sha256": sha256_file(replicate_result_path),
                    }
                )
                executed_replicates += 1

            pass_rate = sum(bool(row["passed"]) for row in replicate_rows) / replicates
            worst_required_failures = max(int(row["required_failures"]) for row in replicate_rows)
            center_values = [
                float(row["center_weighted_rmse"])
                for row in replicate_rows
                if row["center_weighted_rmse"] is not None
            ]
            mean_center = statistics.fmean(center_values) if center_values else None
            maximum_center = max(center_values) if center_values else None
            center_stddev = statistics.pstdev(center_values) if center_values else None
            eligible = (
                pass_rate >= minimum_pass_rate
                and worst_required_failures <= maximum_worst_required_failures
                and (
                    maximum_center_rmse is None
                    or (maximum_center is not None and maximum_center <= maximum_center_rmse)
                )
                and (
                    maximum_center_rmse_stddev is None
                    or (center_stddev is not None and center_stddev <= maximum_center_rmse_stddev)
                )
            )
            cell_rows.append(
                {
                    "cell_id": cell_id,
                    "status": "completed",
                    "eligible": eligible,
                    "pass_rate": pass_rate,
                    "passed_replicates": sum(bool(row["passed"]) for row in replicate_rows),
                    "replicates": replicates,
                    "worst_required_failures": worst_required_failures,
                    "worst_normalized_distance": max(
                        float(row["worst_normalized_distance"]) for row in replicate_rows
                    ),
                    "mean_center_weighted_rmse": mean_center,
                    "maximum_center_weighted_rmse": maximum_center,
                    "center_weighted_rmse_stddev": center_stddev,
                    "replicate_results": [
                        {
                            "path": row["result"],
                            "sha256": row["result_sha256"],
                        }
                        for row in replicate_rows
                    ],
                }
            )
        except Exception as error:
            cell_rows.append(
                {
                    "cell_id": str(cell_id),
                    "status": "failed",
                    "eligible": False,
                    "error_type": type(error).__name__,
                    "error": str(error),
                }
            )

    completed = [row for row in cell_rows if row["status"] == "completed"]
    ranked = sorted(
        completed,
        key=lambda row: (
            not bool(row["eligible"]),
            -float(row["pass_rate"]),
            int(row["worst_required_failures"]),
            _optional_float_sort_value(row["maximum_center_weighted_rmse"]),
            _optional_float_sort_value(row["mean_center_weighted_rmse"]),
            _optional_float_sort_value(row["center_weighted_rmse_stddev"]),
            str(row["cell_id"]),
        ),
    )
    eligible_rows = [row for row in ranked if row["eligible"]]
    if not eligible_rows:
        recommendation_status = "no-eligible-candidate"
        recommended: list[str] = []
    else:
        best = eligible_rows[0]
        best_key = (
            best["pass_rate"],
            best["worst_required_failures"],
            best["maximum_center_weighted_rmse"],
            best["mean_center_weighted_rmse"],
            best["center_weighted_rmse_stddev"],
        )
        recommended = [
            str(row["cell_id"])
            for row in eligible_rows
            if (
                row["pass_rate"],
                row["worst_required_failures"],
                row["maximum_center_weighted_rmse"],
                row["mean_center_weighted_rmse"],
                row["center_weighted_rmse_stddev"],
            )
            == best_key
        ]
        recommendation_status = "single-candidate" if len(recommended) == 1 else "tie"
    rank_by_id = {str(row["cell_id"]): index for index, row in enumerate(ranked, start=1)}
    for row in cell_rows:
        row["rank"] = rank_by_id.get(str(row["cell_id"]))
    write_json(
        report_path,
        {
            "format_version": 1,
            "kind": "courtsim-matrix-robustness",
            "source": {
                "matrix_report": str(matrix_report),
                "matrix_report_sha256": sha256_file(matrix_report),
                "source_ranking": source_ranking_path.name,
                "source_ranking_sha256": sha256_file(source_ranking_path),
            },
            "configuration": configuration,
            "recommendation": {
                "status": recommendation_status,
                "candidate_cell_ids": recommended,
                "automatic_promotion": False,
            },
            "summary": {
                "cells": len(cell_rows),
                "completed": len(completed),
                "failed": len(cell_rows) - len(completed),
                "eligible": len(eligible_rows),
                "executed_replicates": executed_replicates,
                "reused_replicates": reused_replicates,
            },
            "cells": sorted(
                cell_rows,
                key=lambda row: (
                    row["rank"] is None,
                    row["rank"] if row["rank"] is not None else math.inf,
                    str(row["cell_id"]),
                ),
            ),
        },
    )
    return report_path

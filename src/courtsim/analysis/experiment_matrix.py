"""Sequential, resumable local experiment matrices."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, cast

from courtsim.analysis.audit_gates import load_distribution_audit
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

CELL_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")


class ExperimentMatrixError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class MatrixCell:
    cell_id: str
    schema_path: Path
    parameters_path: Path
    profile_path: Path
    opponent_profile_path: Path
    target_paths: tuple[Path, ...]
    seed_group: str | None = None
    home_tempo: int = 50
    away_tempo: int = 50


@dataclass(frozen=True, slots=True)
class ExperimentMatrix:
    matrix_id: str
    master_seed: int
    games: int
    workers: int
    start_index: int
    trace_mode: TraceMode
    clock: GameClockConfig
    targets: tuple[Path, ...]
    cells: tuple[MatrixCell, ...]


def _load_object(path: Path) -> dict[str, Any]:
    try:
        raw: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ExperimentMatrixError(f"cannot load matrix spec: {path}") from error
    if not isinstance(raw, dict):
        raise ExperimentMatrixError("matrix spec must contain an object")
    return cast(dict[str, Any], raw)


def _exact_keys(raw: dict[str, Any], expected: set[str], context: str) -> None:
    if set(raw) != expected:
        raise ExperimentMatrixError(
            f"{context} keys must be exactly {sorted(expected)}; got {sorted(raw)}"
        )


def _positive_int(value: object, field: str, *, allow_zero: bool = False) -> int:
    minimum = 0 if allow_zero else 1
    if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
        qualifier = "non-negative" if allow_zero else "positive"
        raise ExperimentMatrixError(f"{field} must be a {qualifier} integer")
    return value


def _rating(value: object, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= 100:
        raise ExperimentMatrixError(f"{field} must be an integer from 0 through 100")
    return value


def _path(root: Path, value: object, field: str) -> Path:
    if not isinstance(value, str) or not value:
        raise ExperimentMatrixError(f"{field} must be a non-empty path string")
    return (root / value).resolve()


def load_experiment_matrix(path: str | Path) -> ExperimentMatrix:
    spec_path = Path(path).resolve()
    raw = _load_object(spec_path)
    _exact_keys(
        raw,
        {
            "format_version",
            "matrix_id",
            "base_directory",
            "master_seed",
            "defaults",
            "targets",
            "cells",
        },
        "matrix",
    )
    if raw["format_version"] != 1:
        raise ExperimentMatrixError("unsupported matrix format_version")
    matrix_id = raw["matrix_id"]
    if not isinstance(matrix_id, str) or not CELL_ID_PATTERN.fullmatch(matrix_id):
        raise ExperimentMatrixError("matrix_id must be a lowercase ASCII identifier")
    base_directory = raw["base_directory"]
    if not isinstance(base_directory, str) or not base_directory:
        raise ExperimentMatrixError("base_directory must be a non-empty path string")
    root = (spec_path.parent / base_directory).resolve()

    defaults = raw["defaults"]
    if not isinstance(defaults, dict):
        raise ExperimentMatrixError("defaults must be an object")
    defaults = cast(dict[str, Any], defaults)
    _exact_keys(
        defaults,
        {
            "schema",
            "profile",
            "games",
            "workers",
            "start_index",
            "trace_mode",
            "clock",
        },
        "defaults",
    )
    try:
        trace_mode = TraceMode(defaults["trace_mode"])
    except (TypeError, ValueError) as error:
        raise ExperimentMatrixError("defaults.trace_mode is invalid") from error
    clock = defaults["clock"]
    if not isinstance(clock, dict):
        raise ExperimentMatrixError("defaults.clock must be an object")
    clock = cast(dict[str, Any], clock)
    legacy_clock_keys = {"regulation_periods", "period_seconds", "possession_seconds"}
    complete_clock_keys = legacy_clock_keys | {
        "overtime_seconds",
        "max_overtimes",
        "overtime_enabled",
    }
    if frozenset(clock) not in {
        frozenset(legacy_clock_keys),
        frozenset(complete_clock_keys),
    }:
        raise ExperimentMatrixError(
            f"defaults.clock keys must be exactly {sorted(legacy_clock_keys)} "
            f"or {sorted(complete_clock_keys)}"
        )
    try:
        clock_config = GameClockConfig(
            clock["regulation_periods"],
            clock["period_seconds"],
            clock["possession_seconds"],
            clock.get("overtime_seconds", 300),
            clock.get("max_overtimes", 8),
            clock.get("overtime_enabled", False),
        )
    except (TypeError, ValueError) as error:
        raise ExperimentMatrixError("defaults.clock is invalid") from error

    raw_targets = raw["targets"]
    if not isinstance(raw_targets, list) or any(not isinstance(item, str) for item in raw_targets):
        raise ExperimentMatrixError("targets must be a list of path strings")
    targets = tuple(_path(root, item, "targets") for item in raw_targets)
    raw_cells = raw["cells"]
    if not isinstance(raw_cells, list) or not raw_cells:
        raise ExperimentMatrixError("cells must be a non-empty list")
    cells: list[MatrixCell] = []
    default_schema = _path(root, defaults["schema"], "defaults.schema")
    default_profile = _path(root, defaults["profile"], "defaults.profile")
    for index, raw_cell in enumerate(raw_cells):
        if not isinstance(raw_cell, dict):
            raise ExperimentMatrixError(f"cells[{index}] must be an object")
        raw_cell = cast(dict[str, Any], raw_cell)
        allowed = {
            "cell_id",
            "parameters",
            "schema",
            "profile",
            "opponent_profile",
            "targets",
            "seed_group",
            "tempo",
            "opponent_tempo",
        }
        required = {"cell_id", "parameters"}
        if not required <= set(raw_cell) or not set(raw_cell) <= allowed:
            raise ExperimentMatrixError(
                f"cells[{index}] requires {sorted(required)} and permits {sorted(allowed)}"
            )
        cell_id = raw_cell["cell_id"]
        if not isinstance(cell_id, str) or not CELL_ID_PATTERN.fullmatch(cell_id):
            raise ExperimentMatrixError(f"cells[{index}].cell_id is invalid")
        seed_group = raw_cell.get("seed_group")
        if seed_group is not None and (
            not isinstance(seed_group, str) or not CELL_ID_PATTERN.fullmatch(seed_group)
        ):
            raise ExperimentMatrixError(f"cells[{index}].seed_group is invalid")
        cell_targets = raw_cell.get("targets")
        if cell_targets is not None and (
            not isinstance(cell_targets, list)
            or not cell_targets
            or any(not isinstance(item, str) for item in cell_targets)
        ):
            raise ExperimentMatrixError(
                f"cells[{index}].targets must be a non-empty list of path strings"
            )
        cell_profile = (
            _path(root, raw_cell["profile"], f"cells[{index}].profile")
            if "profile" in raw_cell
            else default_profile
        )
        cells.append(
            MatrixCell(
                cell_id,
                (
                    _path(root, raw_cell["schema"], f"cells[{index}].schema")
                    if "schema" in raw_cell
                    else default_schema
                ),
                _path(root, raw_cell["parameters"], f"cells[{index}].parameters"),
                cell_profile,
                (
                    _path(
                        root,
                        raw_cell["opponent_profile"],
                        f"cells[{index}].opponent_profile",
                    )
                    if "opponent_profile" in raw_cell
                    else cell_profile
                ),
                (
                    tuple(_path(root, item, f"cells[{index}].targets") for item in cell_targets)
                    if cell_targets is not None
                    else targets
                ),
                seed_group,
                _rating(raw_cell.get("tempo", 50), f"cells[{index}].tempo"),
                _rating(
                    raw_cell.get("opponent_tempo", 50),
                    f"cells[{index}].opponent_tempo",
                ),
            )
        )
    ids = tuple(cell.cell_id for cell in cells)
    if len(ids) != len(set(ids)):
        raise ExperimentMatrixError("cell_id values must be unique")
    master_seed = _positive_int(raw["master_seed"], "master_seed", allow_zero=True)
    return ExperimentMatrix(
        matrix_id,
        master_seed,
        _positive_int(defaults["games"], "defaults.games"),
        _positive_int(defaults["workers"], "defaults.workers"),
        _positive_int(defaults["start_index"], "defaults.start_index", allow_zero=True),
        trace_mode,
        clock_config,
        targets,
        tuple(cells),
    )


def _plan(matrix: ExperimentMatrix, cell: MatrixCell) -> dict[str, Any]:
    seed_key = cell.seed_group if cell.seed_group is not None else cell.cell_id
    inputs: dict[str, Any] = {
        "schema": {
            "path": str(cell.schema_path),
            "sha256": sha256_file(cell.schema_path),
        },
        "parameters": {
            "path": str(cell.parameters_path),
            "sha256": sha256_file(cell.parameters_path),
        },
        "profile": {
            "path": str(cell.profile_path),
            "sha256": sha256_file(cell.profile_path),
        },
    }
    plan = {
        "matrix_id": matrix.matrix_id,
        "cell_id": cell.cell_id,
        "seed": derive_seed(matrix.master_seed, "matrix-cell", seed_key),
        "games": matrix.games,
        "workers": matrix.workers,
        "start_index": matrix.start_index,
        "trace_mode": matrix.trace_mode.value,
        "clock": asdict(matrix.clock),
        "inputs": inputs,
        "targets": [{"path": str(path), "sha256": sha256_file(path)} for path in cell.target_paths],
    }
    if cell.opponent_profile_path != cell.profile_path:
        inputs["opponent_profile"] = {
            "path": str(cell.opponent_profile_path),
            "sha256": sha256_file(cell.opponent_profile_path),
        }
    if cell.seed_group is not None:
        plan["seed_group"] = cell.seed_group
    if cell.home_tempo != 50 or cell.away_tempo != 50:
        plan["team_tempo"] = {
            "home": cell.home_tempo,
            "away": cell.away_tempo,
        }
    return plan


def _plan_hash(plan: dict[str, Any]) -> str:
    encoded = json.dumps(
        plan,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _reusable_result(result_path: Path, plan_sha256: str) -> dict[str, Any] | None:
    if not result_path.is_file():
        return None
    try:
        result = _load_object(result_path)
        manifest = result_path.parent / result["manifest"]
        audit = result_path.parent / result["audit"]
    except (ExperimentMatrixError, KeyError, TypeError):
        return None
    if (
        result.get("status") != "completed"
        or result.get("plan_sha256") != plan_sha256
        or not audit.is_file()
        or result.get("audit_sha256") != sha256_file(audit)
        or not verify_manifest(manifest).ok
    ):
        return None
    targets = result.get("targets")
    if not isinstance(targets, list):
        return None
    for target in targets:
        if not isinstance(target, dict):
            return None
        raw_path = target.get("path")
        expected = target.get("sha256")
        if not isinstance(raw_path, str) or not isinstance(expected, str):
            return None
        score_path = result_path.parent / raw_path
        if not score_path.is_file() or sha256_file(score_path) != expected:
            return None
    return result


def run_experiment_matrix(
    *,
    spec_path: str | Path,
    output_directory: str | Path,
    resume: bool = False,
) -> Path:
    matrix = load_experiment_matrix(spec_path)
    destination = Path(output_directory)
    report_path = destination / "matrix-report.json"
    if report_path.exists() and not resume:
        raise ExperimentMatrixError(f"matrix report already exists: {report_path}")
    rows: list[dict[str, Any]] = []
    completed = 0
    failed = 0
    reused = 0
    for cell in matrix.cells:
        cell_directory = destination / "cells" / cell.cell_id
        result_path = cell_directory / "cell-result.json"
        try:
            plan = _plan(matrix, cell)
            plan_sha256 = _plan_hash(plan)
            existing = _reusable_result(result_path, plan_sha256) if resume else None
            if existing is not None:
                rows.append(
                    {
                        "cell_id": cell.cell_id,
                        "execution": "reused",
                        "status": "completed",
                        "result": result_path.relative_to(destination).as_posix(),
                        "plan_sha256": plan_sha256,
                    }
                )
                completed += 1
                reused += 1
                continue

            run_directory = cell_directory / f"run-{plan_sha256[:12]}"
            manifest_path = run_model_audit_to_directory(
                schema_path=cell.schema_path,
                parameters_path=cell.parameters_path,
                profile_path=cell.profile_path,
                opponent_profile_path=cell.opponent_profile_path,
                home_tempo=cell.home_tempo,
                away_tempo=cell.away_tempo,
                output_directory=run_directory,
                master_seed=plan["seed"],
                games=matrix.games,
                start_index=matrix.start_index,
                clock=matrix.clock,
                workers=matrix.workers,
                trace_mode=matrix.trace_mode,
            )
            verification = verify_manifest(manifest_path)
            if not verification.ok:
                raise ExperimentMatrixError(
                    f"cell {cell.cell_id} manifest verification failed: {verification.issues}"
                )
            audit_path = run_directory / "audit.json"
            audit = load_distribution_audit(audit_path)
            target_results: list[dict[str, Any]] = []
            for index, target_path in enumerate(cell.target_paths, start=1):
                target = load_realism_target_set(target_path)
                score = score_audit_against_realism_targets(audit, target)
                score_path = cell_directory / f"target-{index:03d}.json"
                write_json(score_path, json.loads(realism_score_report_to_json(score)))
                target_results.append(
                    {
                        "target_set_id": score.target_set_id,
                        "path": score_path.relative_to(cell_directory).as_posix(),
                        "sha256": sha256_file(score_path),
                        "gate_passed": score.gate_passed,
                        "required_failures": score.required_failures,
                    }
                )
            result = {
                "format_version": 1,
                "status": "completed",
                "cell_id": cell.cell_id,
                "plan": plan,
                "plan_sha256": plan_sha256,
                "manifest": manifest_path.relative_to(cell_directory).as_posix(),
                "audit": audit_path.relative_to(cell_directory).as_posix(),
                "audit_sha256": sha256_file(audit_path),
                "manifest_verification": {
                    "checked": verification.checked,
                    "ok": verification.ok,
                },
                "targets": target_results,
            }
            write_json(result_path, result)
            rows.append(
                {
                    "cell_id": cell.cell_id,
                    "execution": "executed",
                    "status": "completed",
                    "result": result_path.relative_to(destination).as_posix(),
                    "plan_sha256": plan_sha256,
                }
            )
            completed += 1
        except Exception as error:
            failed += 1
            failure = {
                "format_version": 1,
                "status": "failed",
                "cell_id": cell.cell_id,
                "error_type": type(error).__name__,
                "error": str(error),
            }
            write_json(result_path, failure)
            rows.append(
                {
                    "cell_id": cell.cell_id,
                    "execution": "executed",
                    "status": "failed",
                    "result": result_path.relative_to(destination).as_posix(),
                }
            )
    write_json(
        report_path,
        {
            "format_version": 1,
            "kind": "courtsim-experiment-matrix",
            "matrix_id": matrix.matrix_id,
            "spec_path": str(Path(spec_path).resolve()),
            "spec_sha256": sha256_file(spec_path),
            "status": "completed" if failed == 0 else "partial",
            "summary": {
                "cells": len(matrix.cells),
                "completed": completed,
                "failed": failed,
                "reused": reused,
            },
            "cells": rows,
        },
    )
    return report_path

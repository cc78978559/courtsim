"""Resumable paired multi-season experiment orchestration for manager policies."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import asdict, dataclass
from enum import IntEnum
from math import isfinite
from pathlib import Path
from typing import Any, cast

from courtsim.artifacts import sha256_file, write_json
from courtsim.manager_evaluation import (
    MANAGER_EVIDENCE_VERSION,
    ManagerEvaluationWeights,
    ManagerEvidenceResult,
    ManagerEvidenceThresholds,
    ManagerOutcome,
    PairedManagerOutcome,
    evaluate_manager_policy,
)

MANAGER_EXPERIMENT_VERSION = "manager-experiment-v1"


class ManagerExperimentError(ValueError):
    pass


class ManagerExperimentArm(IntEnum):
    INCUMBENT = 0
    SHADOW = 1


@dataclass(frozen=True, slots=True)
class ManagerExperimentSpec:
    experiment_id: str
    policy_version: str
    master_seeds: tuple[int, ...]
    start_season: int
    seasons: int
    team_ids: tuple[str, ...]
    initial_state_payload: str
    version: str = MANAGER_EXPERIMENT_VERSION

    def __post_init__(self) -> None:
        if not self.experiment_id.strip() or not self.policy_version.strip():
            raise ValueError("experiment_id and policy_version must not be blank")
        if (
            not self.master_seeds
            or len(self.master_seeds) != len(set(self.master_seeds))
            or any(
                not isinstance(seed, int) or isinstance(seed, bool) or seed < 0
                for seed in self.master_seeds
            )
        ):
            raise ValueError("experiment master_seeds must be unique non-negative integers")
        if (
            not isinstance(self.start_season, int)
            or isinstance(self.start_season, bool)
            or self.start_season < 1
            or not isinstance(self.seasons, int)
            or isinstance(self.seasons, bool)
            or self.seasons < 1
        ):
            raise ValueError("experiment season values must be positive integers")
        if (
            len(self.team_ids) < 2
            or self.team_ids != tuple(sorted(set(self.team_ids)))
            or any(not team_id.strip() for team_id in self.team_ids)
        ):
            raise ValueError("experiment team_ids must be sorted unique non-blank identifiers")
        if not self.initial_state_payload:
            raise ValueError("initial_state_payload must not be empty")
        if self.version != MANAGER_EXPERIMENT_VERSION:
            raise ValueError("unsupported manager experiment version")


@dataclass(frozen=True, slots=True)
class ManagerSeasonRequest:
    experiment_id: str
    policy_version: str
    arm: ManagerExperimentArm
    source_id: str
    master_seed: int
    season_year: int
    state_payload: str


@dataclass(frozen=True, slots=True)
class ManagerSeasonMetrics:
    team_id: str
    win_rate: float
    playoff_progress: float
    roster_value: float
    cap_flexibility: float

    def __post_init__(self) -> None:
        if not self.team_id.strip():
            raise ValueError("manager season metric team_id must not be blank")
        values = (
            self.win_rate,
            self.playoff_progress,
            self.roster_value,
            self.cap_flexibility,
        )
        if any(not isfinite(value) or not 0 <= value <= 1 for value in values):
            raise ValueError("manager season metrics must be finite values from zero through one")


@dataclass(frozen=True, slots=True)
class ManagerSeasonExecution:
    next_state_payload: str
    metrics: tuple[ManagerSeasonMetrics, ...]
    audit_payload: str = "{}"

    def __post_init__(self) -> None:
        if not self.next_state_payload:
            raise ValueError("manager season next_state_payload must not be empty")
        if not self.audit_payload:
            raise ValueError("manager season audit_payload must not be empty")
        if self.metrics != tuple(sorted(self.metrics, key=lambda item: item.team_id)):
            raise ValueError("manager season metrics must be ordered by team_id")
        ids = tuple(item.team_id for item in self.metrics)
        if not ids or len(ids) != len(set(ids)):
            raise ValueError("manager season metrics must contain unique teams")


ManagerSeasonExecutor = Callable[[ManagerSeasonRequest], ManagerSeasonExecution]


@dataclass(frozen=True, slots=True)
class ManagerExperimentResult:
    report_path: Path
    manifest_path: Path
    evidence: ManagerEvidenceResult
    executed_cells: int
    reused_cells: int
    version: str = MANAGER_EXPERIMENT_VERSION


def run_manager_experiment(
    *,
    spec: ManagerExperimentSpec,
    executor: ManagerSeasonExecutor,
    output_directory: str | Path,
    weights: ManagerEvaluationWeights | None = None,
    thresholds: ManagerEvidenceThresholds | None = None,
) -> ManagerExperimentResult:
    """Run or resume exact paired arms while carrying each arm's state between seasons."""
    destination = Path(output_directory)
    destination.mkdir(parents=True, exist_ok=True)
    active_weights = weights or ManagerEvaluationWeights()
    active_thresholds = thresholds or ManagerEvidenceThresholds()
    plan = _plan(spec, active_weights, active_thresholds)
    plan_path = destination / "plan.json"
    initial_path = destination / "initial-state.json"
    _establish_artifact(plan_path, plan, "manager experiment plan")
    _establish_artifact(
        initial_path,
        {"state_payload": spec.initial_state_payload},
        "manager experiment initial state",
    )
    existing_report = destination / "report.json"
    if existing_report.exists():
        verify_manager_experiment(existing_report)

    outcomes: dict[tuple[str, int, int, str, ManagerExperimentArm], ManagerOutcome] = {}
    cell_paths: list[Path] = []
    executed_cells = 0
    reused_cells = 0
    for source_index, master_seed in enumerate(spec.master_seeds, start=1):
        source_id = f"source-{source_index:04d}"
        for arm in ManagerExperimentArm:
            state_payload = spec.initial_state_payload
            for offset in range(spec.seasons):
                season_year = spec.start_season + offset
                request = ManagerSeasonRequest(
                    spec.experiment_id,
                    spec.policy_version,
                    arm,
                    source_id,
                    master_seed,
                    season_year,
                    state_payload,
                )
                cell_path = (
                    destination
                    / "sources"
                    / source_id
                    / arm.name.lower()
                    / f"season-{season_year}.json"
                )
                request_digest = _digest(_request_payload(request))
                if cell_path.exists():
                    execution = _load_reusable_cell(
                        cell_path,
                        request_digest=request_digest,
                        team_ids=spec.team_ids,
                    )
                    reused_cells += 1
                else:
                    execution = executor(request)
                    _validate_execution(execution, spec.team_ids)
                    write_json(
                        cell_path,
                        _cell_payload(request_digest, request, execution),
                    )
                    executed_cells += 1
                cell_paths.append(cell_path)
                for metric in execution.metrics:
                    outcome = ManagerOutcome(
                        source_id,
                        master_seed,
                        season_year,
                        metric.team_id,
                        metric.win_rate,
                        metric.playoff_progress,
                        metric.roster_value,
                        metric.cap_flexibility,
                    )
                    outcomes[(*outcome.address, arm)] = outcome
                state_payload = execution.next_state_payload

    paired = _paired_outcomes(outcomes)
    evidence = evaluate_manager_policy(
        policy_version=spec.policy_version,
        observations=paired,
        weights=active_weights,
        thresholds=active_thresholds,
    )
    report_path = existing_report
    report = {
        "format_version": 1,
        "kind": "courtsim-manager-experiment",
        "experiment_version": MANAGER_EXPERIMENT_VERSION,
        "evidence_version": MANAGER_EVIDENCE_VERSION,
        "plan_sha256": sha256_file(plan_path),
        "initial_state_sha256": sha256_file(initial_path),
        "cell_count": len(cell_paths),
        "observation_count": len(paired),
        "evidence": asdict(evidence),
        "cells": [
            {
                "path": cell_path.relative_to(destination).as_posix(),
                "sha256": sha256_file(cell_path),
            }
            for cell_path in cell_paths
        ],
    }
    write_json(report_path, report)
    manifest_path = destination / "manifest.json"
    write_json(
        manifest_path,
        {
            "format_version": 1,
            "kind": "courtsim-manager-experiment-manifest",
            "experiment_version": MANAGER_EXPERIMENT_VERSION,
            "plan": {"path": "plan.json", "sha256": sha256_file(plan_path)},
            "initial_state": {
                "path": "initial-state.json",
                "sha256": sha256_file(initial_path),
            },
            "report": {"path": "report.json", "sha256": sha256_file(report_path)},
            "cells": report["cells"],
        },
    )
    verify_manager_experiment(report_path)
    return ManagerExperimentResult(
        report_path,
        manifest_path,
        evidence,
        executed_cells,
        reused_cells,
    )


def verify_manager_experiment(report_path: str | Path) -> ManagerEvidenceResult:
    """Verify every artifact and recompute evidence from stored paired cells."""
    report_file = Path(report_path)
    destination = report_file.parent
    report = _load_object(report_file, "manager experiment report")
    _exact(
        report,
        {
            "format_version",
            "kind",
            "experiment_version",
            "evidence_version",
            "plan_sha256",
            "initial_state_sha256",
            "cell_count",
            "observation_count",
            "evidence",
            "cells",
        },
        "manager experiment report",
    )
    if (
        report["format_version"] != 1
        or report["kind"] != "courtsim-manager-experiment"
        or report["experiment_version"] != MANAGER_EXPERIMENT_VERSION
        or report["evidence_version"] != MANAGER_EVIDENCE_VERSION
    ):
        raise ManagerExperimentError("unsupported manager experiment report")
    plan_path = destination / "plan.json"
    initial_path = destination / "initial-state.json"
    if (
        not plan_path.is_file()
        or sha256_file(plan_path) != report["plan_sha256"]
        or not initial_path.is_file()
        or sha256_file(initial_path) != report["initial_state_sha256"]
    ):
        raise ManagerExperimentError("manager experiment plan or initial state changed")
    plan = _load_object(plan_path, "manager experiment plan")
    spec, weights, thresholds = _parse_plan(plan)
    initial = _load_object(initial_path, "manager experiment initial state")
    _exact(initial, {"state_payload"}, "manager experiment initial state")
    if initial["state_payload"] != spec.initial_state_payload:
        raise ManagerExperimentError("manager experiment initial state does not match plan")

    raw_cells = report["cells"]
    if not isinstance(raw_cells, list) or len(raw_cells) != report["cell_count"]:
        raise ManagerExperimentError("manager experiment cell index is invalid")
    outcomes: dict[tuple[str, int, int, str, ManagerExperimentArm], ManagerOutcome] = {}
    previous_states: dict[tuple[str, ManagerExperimentArm], str] = {}
    actual_requests: list[tuple[str, int, ManagerExperimentArm, int]] = []
    for index, raw_cell in enumerate(raw_cells):
        cell_index = _object(raw_cell, f"manager experiment cells[{index}]")
        _exact(cell_index, {"path", "sha256"}, f"manager experiment cells[{index}]")
        relative = cell_index["path"]
        expected_hash = cell_index["sha256"]
        if not isinstance(relative, str) or not isinstance(expected_hash, str):
            raise ManagerExperimentError("manager experiment cell index values are invalid")
        cell_path = (destination / relative).resolve()
        if destination.resolve() not in cell_path.parents:
            raise ManagerExperimentError("manager experiment cell path escapes output directory")
        if not cell_path.is_file() or sha256_file(cell_path) != expected_hash:
            raise ManagerExperimentError(f"manager experiment cell changed: {relative}")
        raw = _load_object(cell_path, "manager experiment cell")
        request = _parse_request(raw)
        actual_requests.append(
            (
                request.source_id,
                request.master_seed,
                request.arm,
                request.season_year,
            )
        )
        expected_state = previous_states.get(
            (request.source_id, request.arm),
            spec.initial_state_payload,
        )
        if request.state_payload != expected_state:
            raise ManagerExperimentError("manager experiment state continuity is broken")
        execution = _parse_execution(raw)
        _validate_execution(execution, spec.team_ids)
        if raw["request_sha256"] != _digest(_request_payload(request)):
            raise ManagerExperimentError("manager experiment cell request hash changed")
        if raw["next_state_sha256"] != _text_digest(execution.next_state_payload):
            raise ManagerExperimentError("manager experiment next-state hash changed")
        if raw["execution_sha256"] != _digest(_execution_payload(execution)):
            raise ManagerExperimentError("manager experiment execution hash changed")
        previous_states[(request.source_id, request.arm)] = execution.next_state_payload
        for metric in execution.metrics:
            outcome = ManagerOutcome(
                request.source_id,
                request.master_seed,
                request.season_year,
                metric.team_id,
                metric.win_rate,
                metric.playoff_progress,
                metric.roster_value,
                metric.cap_flexibility,
            )
            outcomes[(*outcome.address, request.arm)] = outcome
    expected_requests = [
        (
            f"source-{source_index:04d}",
            master_seed,
            arm,
            spec.start_season + offset,
        )
        for source_index, master_seed in enumerate(spec.master_seeds, start=1)
        for arm in ManagerExperimentArm
        for offset in range(spec.seasons)
    ]
    if actual_requests != expected_requests:
        raise ManagerExperimentError("manager experiment cell sequence does not match plan")
    paired = _paired_outcomes(outcomes)
    if len(paired) != report["observation_count"]:
        raise ManagerExperimentError("manager experiment observation count changed")
    evidence = evaluate_manager_policy(
        policy_version=spec.policy_version,
        observations=paired,
        weights=weights,
        thresholds=thresholds,
    )
    if _json_value(asdict(evidence)) != report["evidence"]:
        raise ManagerExperimentError("manager experiment evidence does not derive from cells")
    manifest_path = destination / "manifest.json"
    manifest = _load_object(manifest_path, "manager experiment manifest")
    _exact(
        manifest,
        {
            "format_version",
            "kind",
            "experiment_version",
            "plan",
            "initial_state",
            "report",
            "cells",
        },
        "manager experiment manifest",
    )
    if (
        manifest["format_version"] != 1
        or manifest["kind"] != "courtsim-manager-experiment-manifest"
        or manifest["experiment_version"] != MANAGER_EXPERIMENT_VERSION
        or manifest["plan"] != {"path": "plan.json", "sha256": sha256_file(plan_path)}
        or manifest["initial_state"]
        != {"path": "initial-state.json", "sha256": sha256_file(initial_path)}
        or manifest["report"] != {"path": "report.json", "sha256": sha256_file(report_file)}
        or manifest["cells"] != report["cells"]
    ):
        raise ManagerExperimentError("manager experiment manifest does not match artifacts")
    return evidence


def _plan(
    spec: ManagerExperimentSpec,
    weights: ManagerEvaluationWeights,
    thresholds: ManagerEvidenceThresholds,
) -> dict[str, object]:
    return {
        "format_version": 1,
        "experiment_version": spec.version,
        "experiment_id": spec.experiment_id,
        "policy_version": spec.policy_version,
        "master_seeds": list(spec.master_seeds),
        "start_season": spec.start_season,
        "seasons": spec.seasons,
        "team_ids": list(spec.team_ids),
        "initial_state_payload": spec.initial_state_payload,
        "weights": asdict(weights),
        "thresholds": asdict(thresholds),
    }


def _parse_plan(
    raw: dict[str, Any],
) -> tuple[ManagerExperimentSpec, ManagerEvaluationWeights, ManagerEvidenceThresholds]:
    _exact(
        raw,
        {
            "format_version",
            "experiment_version",
            "experiment_id",
            "policy_version",
            "master_seeds",
            "start_season",
            "seasons",
            "team_ids",
            "initial_state_payload",
            "weights",
            "thresholds",
        },
        "manager experiment plan",
    )
    if raw["format_version"] != 1:
        raise ManagerExperimentError("unsupported manager experiment plan")
    try:
        spec = ManagerExperimentSpec(
            str(raw["experiment_id"]),
            str(raw["policy_version"]),
            tuple(cast(list[int], raw["master_seeds"])),
            cast(int, raw["start_season"]),
            cast(int, raw["seasons"]),
            tuple(cast(list[str], raw["team_ids"])),
            cast(str, raw["initial_state_payload"]),
            cast(str, raw["experiment_version"]),
        )
        weights = ManagerEvaluationWeights(**_object(raw["weights"], "weights"))
        thresholds = ManagerEvidenceThresholds(**_object(raw["thresholds"], "thresholds"))
    except (TypeError, ValueError) as error:
        raise ManagerExperimentError(f"invalid manager experiment plan: {error}") from error
    return spec, weights, thresholds


def _request_payload(request: ManagerSeasonRequest) -> dict[str, object]:
    return {
        "experiment_id": request.experiment_id,
        "policy_version": request.policy_version,
        "arm": request.arm.name.lower(),
        "source_id": request.source_id,
        "master_seed": request.master_seed,
        "season_year": request.season_year,
        "state_sha256": _text_digest(request.state_payload),
    }


def _cell_payload(
    request_digest: str,
    request: ManagerSeasonRequest,
    execution: ManagerSeasonExecution,
) -> dict[str, object]:
    execution_payload = _execution_payload(execution)
    return {
        "format_version": 1,
        "request_sha256": request_digest,
        "request": {
            **_request_payload(request),
            "state_payload": request.state_payload,
        },
        "next_state_payload": execution.next_state_payload,
        "next_state_sha256": _text_digest(execution.next_state_payload),
        "metrics": [asdict(metric) for metric in execution.metrics],
        "audit_payload": execution.audit_payload,
        "execution_sha256": _digest(execution_payload),
    }


def _load_reusable_cell(
    path: Path,
    *,
    request_digest: str,
    team_ids: tuple[str, ...],
) -> ManagerSeasonExecution:
    raw = _load_object(path, "manager experiment cell")
    if raw.get("request_sha256") != request_digest:
        raise ManagerExperimentError(f"manager experiment cell plan changed: {path}")
    execution = _parse_execution(raw)
    _validate_execution(execution, team_ids)
    if raw.get("next_state_sha256") != _text_digest(execution.next_state_payload):
        raise ManagerExperimentError(f"manager experiment cell state changed: {path}")
    if raw.get("execution_sha256") != _digest(_execution_payload(execution)):
        raise ManagerExperimentError(f"manager experiment cell execution changed: {path}")
    return execution


def _parse_request(raw: dict[str, Any]) -> ManagerSeasonRequest:
    request = _object(raw.get("request"), "manager experiment request")
    expected = {
        "experiment_id",
        "policy_version",
        "arm",
        "source_id",
        "master_seed",
        "season_year",
        "state_sha256",
        "state_payload",
    }
    _exact(request, expected, "manager experiment request")
    try:
        arm = ManagerExperimentArm[str(request["arm"]).upper()]
        parsed = ManagerSeasonRequest(
            str(request["experiment_id"]),
            str(request["policy_version"]),
            arm,
            str(request["source_id"]),
            cast(int, request["master_seed"]),
            cast(int, request["season_year"]),
            str(request["state_payload"]),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise ManagerExperimentError("invalid manager experiment request") from error
    if request["state_sha256"] != _text_digest(parsed.state_payload):
        raise ManagerExperimentError("manager experiment request state hash changed")
    return parsed


def _parse_execution(raw: dict[str, Any]) -> ManagerSeasonExecution:
    expected = {
        "format_version",
        "request_sha256",
        "request",
        "next_state_payload",
        "next_state_sha256",
        "metrics",
        "audit_payload",
        "execution_sha256",
    }
    _exact(raw, expected, "manager experiment cell")
    if raw["format_version"] != 1:
        raise ManagerExperimentError("unsupported manager experiment cell")
    metrics = raw["metrics"]
    if not isinstance(metrics, list):
        raise ManagerExperimentError("manager experiment metrics must be a list")
    try:
        parsed_metrics = tuple(
            ManagerSeasonMetrics(**_object(item, "manager season metrics")) for item in metrics
        )
        return ManagerSeasonExecution(
            str(raw["next_state_payload"]),
            parsed_metrics,
            str(raw["audit_payload"]),
        )
    except (TypeError, ValueError) as error:
        raise ManagerExperimentError(f"invalid manager experiment cell: {error}") from error


def _validate_execution(
    execution: ManagerSeasonExecution,
    team_ids: tuple[str, ...],
) -> None:
    if tuple(metric.team_id for metric in execution.metrics) != team_ids:
        raise ManagerExperimentError("manager season execution must cover every experiment team")


def _execution_payload(execution: ManagerSeasonExecution) -> dict[str, object]:
    return {
        "next_state_payload": execution.next_state_payload,
        "metrics": [asdict(metric) for metric in execution.metrics],
        "audit_payload": execution.audit_payload,
    }


def _paired_outcomes(
    outcomes: dict[tuple[str, int, int, str, ManagerExperimentArm], ManagerOutcome],
) -> tuple[PairedManagerOutcome, ...]:
    addresses = sorted({key[:-1] for key in outcomes})
    paired: list[PairedManagerOutcome] = []
    for address in addresses:
        incumbent = outcomes.get((*address, ManagerExperimentArm.INCUMBENT))
        shadow = outcomes.get((*address, ManagerExperimentArm.SHADOW))
        if incumbent is None or shadow is None:
            raise ManagerExperimentError("manager experiment is missing a paired arm")
        paired.append(PairedManagerOutcome(incumbent, shadow))
    return tuple(paired)


def _establish_artifact(path: Path, payload: dict[str, object], context: str) -> None:
    if path.exists():
        if _load_object(path, context) != payload:
            raise ManagerExperimentError(f"{context} conflicts with existing output")
        return
    write_json(path, payload)


def _load_object(path: Path, context: str) -> dict[str, Any]:
    try:
        raw: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ManagerExperimentError(f"cannot load {context}: {path}") from error
    return _object(raw, context)


def _object(value: object, context: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ManagerExperimentError(f"{context} must be an object")
    return cast(dict[str, Any], value)


def _exact(value: dict[str, Any], keys: set[str], context: str) -> None:
    if set(value) != keys:
        raise ManagerExperimentError(f"{context} keys must be exactly {sorted(keys)}")


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _text_digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _json_value(value: object) -> object:
    return json.loads(json.dumps(value, ensure_ascii=False, sort_keys=True))

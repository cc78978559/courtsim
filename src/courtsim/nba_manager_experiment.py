"""Resumable focal-team experiments for thirty-team front-office policies."""

from __future__ import annotations

import gzip
import hashlib
import json
import math
import os
import subprocess
import tempfile
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from enum import IntEnum
from pathlib import Path, PurePosixPath, PureWindowsPath
from threading import Lock
from typing import Any, cast

from courtsim.artifacts import sha256_file, write_json
from courtsim.manager_ai import REALITY_BASELINE_POLICY_ID, WHITE_BOX_CANDIDATE_POLICY_ID
from courtsim.nba_manager_evaluation import (
    DEFAULT_SEASON_WEIGHTS,
    NBA_MANAGER_EVIDENCE_VERSION,
    NBAFrontOfficeEvaluationWeights,
    NBAFrontOfficeEvidenceResult,
    NBAFrontOfficeEvidenceThresholds,
    NBAFrontOfficeOutcome,
    PairedNBAFrontOfficeOutcome,
    evaluate_nba_front_office_policy,
)
from courtsim.nba_manager_protocol import (
    NBA_MANAGER_CANONICAL_TEAM_IDS,
    NBA_MANAGER_PROTOCOL_ID,
    NBA_MANAGER_PROTOCOL_INPUT_ROLES,
    NBA_MANAGER_PROTOCOL_SOURCE_ROLE,
    canonical_nba_manager_protocol_path,
    load_nba_manager_promotion_protocol,
    verify_nba_manager_protocol_file,
)
from courtsim.nba_manager_protocol import (
    NBA_MANAGER_FORMAL_MASTER_SEEDS as PROTOCOL_FORMAL_MASTER_SEEDS,
)

NBA_MANAGER_EXPERIMENT_VERSION = "nba-manager-experiment-v1"
NBA_MANAGER_EXPERIMENT_SCHEMA_VERSION = 1
NBA_MANAGER_REQUIRED_CI = (
    "clean-checkout-tests",
    "strict-mypy",
    "coverage-85",
    "ubuntu-ci",
    "windows-ci",
    "wheel-smoke",
)
NBA_MANAGER_CI_PROOFS = (
    (
        "clean-checkout-tests",
        "Quality (ubuntu-latest)",
        ("Checkout clean repository", "Test with coverage"),
    ),
    ("strict-mypy", "Quality (ubuntu-latest)", ("Type check",)),
    ("coverage-85", "Quality (ubuntu-latest)", ("Test with coverage",)),
    ("ubuntu-ci", "Quality (ubuntu-latest)", ()),
    ("windows-ci", "Quality (windows-latest)", ()),
    (
        "wheel-smoke",
        "Package smoke test",
        ("Build wheel and source distribution", "Verify installed package metadata"),
    ),
)
NBA_MANAGER_FORMAL_MASTER_SEEDS = PROTOCOL_FORMAL_MASTER_SEEDS


class NBAManagerExperimentError(ValueError):
    pass


class NBAManagerExperimentArm(IntEnum):
    CONTROL = 0
    TREATMENT = 1


@dataclass(frozen=True, slots=True)
class NBAManagerExperimentSpec:
    experiment_id: str
    baseline_policy_id: str
    candidate_policy_id: str
    master_seeds: tuple[int, ...]
    focal_team_ids: tuple[str, ...]
    start_season: int
    seasons: int
    team_ids: tuple[str, ...]
    initial_state_sha256: str
    source_hashes: tuple[tuple[str, str], ...]
    execution_config_sha256: str
    macro_ranges: tuple[tuple[str, float, float], ...]
    code_commit: str
    code_tree_sha256: str
    version: str = NBA_MANAGER_EXPERIMENT_VERSION
    formal_run: bool = True

    def __post_init__(self) -> None:
        if not all(
            value.strip()
            for value in (self.experiment_id, self.baseline_policy_id, self.candidate_policy_id)
        ):
            raise ValueError("NBA manager experiment identity must not be blank")
        source_count = len(self.master_seeds)
        if (
            len(self.team_ids) != 30
            or self.team_ids != tuple(sorted(set(self.team_ids)))
            or not 1 <= source_count <= 30
            or len(self.master_seeds) != len(set(self.master_seeds))
            or any(
                not isinstance(seed, int) or isinstance(seed, bool) or seed < 0
                for seed in self.master_seeds
            )
            or len(self.focal_team_ids) != source_count
            or len(set(self.focal_team_ids)) != source_count
            or not set(self.focal_team_ids) <= set(self.team_ids)
            or (self.formal_run and tuple(sorted(self.focal_team_ids)) != self.team_ids)
        ):
            raise ValueError("NBA manager experiment seed and focal-team mapping is invalid")
        if not isinstance(self.formal_run, bool):
            raise ValueError("NBA manager experiment formal marker must be boolean")
        if (
            not isinstance(self.start_season, int)
            or isinstance(self.start_season, bool)
            or self.start_season < 1
            or not isinstance(self.seasons, int)
            or isinstance(self.seasons, bool)
            or self.seasons < 1
        ):
            raise ValueError("NBA manager experiment seasons are invalid")
        _validate_digest(self.initial_state_sha256, "initial state")
        _validate_digest(self.execution_config_sha256, "execution configuration")
        macro_names = tuple(name for name, _, _ in self.macro_ranges)
        if macro_names != tuple(sorted(set(macro_names))) or any(
            not name.strip()
            or not isinstance(minimum, (int, float))
            or isinstance(minimum, bool)
            or not isinstance(maximum, (int, float))
            or isinstance(maximum, bool)
            or not math.isfinite(minimum)
            or not math.isfinite(maximum)
            or minimum > maximum
            for name, minimum, maximum in self.macro_ranges
        ):
            raise ValueError("NBA manager macro ranges are invalid")
        if self.formal_run and not self.macro_ranges:
            raise ValueError("formal NBA manager experiment requires macro ranges")
        if len(self.code_commit) != 40 or any(
            character not in "0123456789abcdef" for character in self.code_commit
        ):
            raise ValueError("NBA manager code commit is invalid")
        _validate_digest(self.code_tree_sha256, "code tree")
        names = tuple(name for name, _ in self.source_hashes)
        if names != tuple(sorted(set(names))) or any(not name.strip() for name in names):
            raise ValueError("NBA manager source hashes must use sorted unique names")
        for _, digest in self.source_hashes:
            _validate_digest(digest, "source")
        if self.version != NBA_MANAGER_EXPERIMENT_VERSION:
            raise ValueError("unsupported NBA manager experiment version")
        if self.formal_run and (
            self.experiment_id != NBA_MANAGER_PROTOCOL_ID
            or self.baseline_policy_id != REALITY_BASELINE_POLICY_ID
            or self.candidate_policy_id != WHITE_BOX_CANDIDATE_POLICY_ID
            or self.master_seeds != NBA_MANAGER_FORMAL_MASTER_SEEDS
            or self.team_ids != NBA_MANAGER_CANONICAL_TEAM_IDS
            or self.focal_team_ids != NBA_MANAGER_CANONICAL_TEAM_IDS
            or self.seasons != 5
            or set(names) != {*NBA_MANAGER_PROTOCOL_INPUT_ROLES, NBA_MANAGER_PROTOCOL_SOURCE_ROLE}
        ):
            raise ValueError("formal NBA manager experiment identity is not frozen")


@dataclass(frozen=True, slots=True)
class NBAManagerSeasonRequest:
    experiment_id: str
    baseline_policy_id: str
    candidate_policy_id: str
    arm: NBAManagerExperimentArm
    source_id: str
    master_seed: int
    focal_team_id: str
    season_year: int
    state_payload: str


@dataclass(frozen=True, slots=True)
class NBAManagerSeasonExecution:
    next_state_payload: str
    outcome: NBAFrontOfficeOutcome
    audit_payload: str = "{}"

    def __post_init__(self) -> None:
        if not self.next_state_payload or not self.audit_payload:
            raise ValueError("NBA manager season execution payloads must not be empty")
        try:
            parsed = json.loads(self.audit_payload)
        except json.JSONDecodeError as error:
            raise ValueError("NBA manager audit payload must be JSON") from error
        if not isinstance(parsed, dict):
            raise ValueError("NBA manager audit payload must be an object")


NBAManagerSeasonExecutor = Callable[[NBAManagerSeasonRequest], NBAManagerSeasonExecution]


@dataclass(frozen=True, slots=True)
class NBAManagerExperimentResult:
    complete: bool
    executed_cells: int
    reused_cells: int
    completed_sources: int
    progress_path: Path
    report_path: Path | None = None
    manifest_path: Path | None = None
    evidence: NBAFrontOfficeEvidenceResult | None = None
    version: str = NBA_MANAGER_EXPERIMENT_VERSION
    stopped: bool = False


def nba_manager_execution_config_sha256(config: object) -> str:
    try:
        payload = json.dumps(config, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError) as error:
        raise ValueError("NBA manager execution configuration must be canonical JSON") from error
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def nba_manager_code_identity(*, require_clean: bool = False) -> tuple[str, str]:
    """Return the current Git commit and a content hash of the executable package sources."""
    repository = Path(__file__).resolve().parents[2]
    try:
        completed = subprocess.run(
            ("git", "rev-parse", "HEAD"),
            cwd=repository,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        raise NBAManagerExperimentError("cannot establish NBA manager code identity") from error
    commit = completed.stdout.strip().lower()
    if len(commit) != 40 or any(character not in "0123456789abcdef" for character in commit):
        raise NBAManagerExperimentError("NBA manager Git commit is invalid")
    if require_clean:
        try:
            status = subprocess.run(
                ("git", "status", "--porcelain", "--untracked-files=all", "--", "src/courtsim"),
                cwd=repository,
                check=True,
                capture_output=True,
                text=True,
            )
        except (OSError, subprocess.CalledProcessError) as error:
            raise NBAManagerExperimentError("cannot inspect NBA manager code tree") from error
        if status.stdout.strip():
            raise NBAManagerExperimentError("candidate receipt requires a clean code tree")
    source_root = Path(__file__).resolve().parent
    digest = hashlib.sha256()
    for path in sorted(source_root.rglob("*.py")):
        relative = path.relative_to(source_root).as_posix().encode("utf-8")
        payload = path.read_bytes().replace(b"\r\n", b"\n")
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        digest.update(len(payload).to_bytes(8, "big"))
        digest.update(payload)
    return commit, digest.hexdigest()


def run_nba_manager_experiment(
    *,
    spec: NBAManagerExperimentSpec,
    initial_state_payload: str,
    executor: NBAManagerSeasonExecutor,
    output_directory: str | Path,
    weights: NBAFrontOfficeEvaluationWeights | None = None,
    thresholds: NBAFrontOfficeEvidenceThresholds | None = None,
    season_weights: tuple[float, ...] = DEFAULT_SEASON_WEIGHTS,
    maximum_new_sources: int | None = None,
    workers: int = 1,
    stop_file: str | Path | None = None,
) -> NBAManagerExperimentResult:
    """Run paired trajectories with verified cell resume and cooperative boundary stops."""
    if _sha256_text(initial_state_payload) != spec.initial_state_sha256:
        raise NBAManagerExperimentError("NBA manager initial state hash differs from spec")
    if maximum_new_sources is not None and (
        not isinstance(maximum_new_sources, int)
        or isinstance(maximum_new_sources, bool)
        or maximum_new_sources < 0
    ):
        raise ValueError("maximum_new_sources must be a non-negative integer")
    if not isinstance(workers, int) or isinstance(workers, bool) or workers < 1:
        raise ValueError("workers must be a positive integer")
    # Worker count is dispatch-only and excluded from the semantic plan hash. Each task
    # owns one source directory, while the parent alone publishes the progress manifest.
    active_weights = weights or NBAFrontOfficeEvaluationWeights()
    active_thresholds = thresholds or NBAFrontOfficeEvidenceThresholds()
    destination = Path(output_directory)
    destination.mkdir(parents=True, exist_ok=True)
    stop_path = Path(stop_file) if stop_file is not None else None
    plan_path = destination / "plan.json"
    initial_path = destination / "initial-state.json.gz"
    plan = _plan_payload(spec, active_weights, active_thresholds, season_weights)
    _establish_json(plan_path, plan, "NBA manager experiment plan")
    _establish_gzip(
        initial_path,
        {"state_payload": initial_state_payload},
        "NBA manager initial state",
    )
    progress_path = destination / "progress.json"
    indexed = (
        _load_progress(progress_path, plan_path, initial_path) if progress_path.exists() else {}
    )
    executed = reused = 0
    sources_started = 0
    observations: dict[
        tuple[str, int, int, str, NBAManagerExperimentArm], NBAFrontOfficeOutcome
    ] = {}
    cell_index: dict[str, str] = dict(indexed)
    progress_lock = Lock()
    tasks: list[tuple[int, int, str]] = []
    for source_index, (master_seed, focal_team_id) in enumerate(
        zip(spec.master_seeds, spec.focal_team_ids, strict=True),
        start=1,
    ):
        source_id = f"source-{source_index:04d}"
        source_complete_before = _source_complete(destination, source_id, spec)
        if not source_complete_before:
            if maximum_new_sources is not None and sources_started >= maximum_new_sources:
                continue
            sources_started += 1
        tasks.append((source_index, master_seed, focal_team_id))

    def execute_source(
        task: tuple[int, int, str],
    ) -> tuple[
        int,
        int,
        dict[tuple[str, int, int, str, NBAManagerExperimentArm], NBAFrontOfficeOutcome],
        dict[str, str],
        bool,
    ]:
        source_index, master_seed, focal_team_id = task
        source_id = f"source-{source_index:04d}"
        source_executed = source_reused = 0
        source_observations: dict[
            tuple[str, int, int, str, NBAManagerExperimentArm], NBAFrontOfficeOutcome
        ] = {}
        source_indexed: dict[str, str] = {}
        source_stopped = False
        for arm in NBAManagerExperimentArm:
            state_payload = initial_state_payload
            for offset in range(spec.seasons):
                if stop_path is not None and stop_path.exists():
                    source_stopped = True
                    break
                season_year = spec.start_season + offset
                request = NBAManagerSeasonRequest(
                    spec.experiment_id,
                    spec.baseline_policy_id,
                    spec.candidate_policy_id,
                    arm,
                    source_id,
                    master_seed,
                    focal_team_id,
                    season_year,
                    state_payload,
                )
                relative = _cell_relative(source_id, arm, season_year)
                cell_path = destination / relative
                request_digest = _digest(_request_payload(request))
                if cell_path.exists():
                    execution = _load_cell(cell_path, request_digest, request, spec.formal_run)
                    source_reused += 1
                else:
                    execution = executor(request)
                    _validate_execution(execution, request, formal_run=spec.formal_run)
                    _write_gzip_json(cell_path, _cell_payload(request_digest, request, execution))
                    source_executed += 1
                state_payload = execution.next_state_payload
                source_observations[(*execution.outcome.address, arm)] = execution.outcome
                relative_key = relative.as_posix()
                cell_digest = sha256_file(cell_path)
                source_indexed[relative_key] = cell_digest
                with progress_lock:
                    if cell_index.get(relative_key) != cell_digest:
                        cell_index[relative_key] = cell_digest
                        _write_progress(progress_path, plan_path, initial_path, cell_index)
            if source_stopped:
                break
        return (
            source_executed,
            source_reused,
            source_observations,
            source_indexed,
            source_stopped,
        )

    stop_requested = False
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for (
            source_executed,
            source_reused,
            source_observations,
            source_indexed,
            source_stopped,
        ) in pool.map(execute_source, tasks):
            executed += source_executed
            reused += source_reused
            stop_requested = stop_requested or source_stopped
            observations.update(source_observations)
            with progress_lock:
                cell_index.update(source_indexed)
                _write_progress(progress_path, plan_path, initial_path, cell_index)

    completed_sources = sum(
        _source_complete(destination, f"source-{index:04d}", spec)
        for index in range(1, len(spec.master_seeds) + 1)
    )

    expected_cells = len(spec.master_seeds) * len(NBAManagerExperimentArm) * spec.seasons
    complete = len(cell_index) == expected_cells and completed_sources == len(spec.master_seeds)
    if not complete:
        return NBAManagerExperimentResult(
            False,
            executed,
            reused,
            completed_sources,
            progress_path,
            stopped=stop_requested,
        )

    paired = _paired_outcomes(observations)
    evidence = evaluate_nba_front_office_policy(
        baseline_policy_id=spec.baseline_policy_id,
        candidate_policy_id=spec.candidate_policy_id,
        observations=paired,
        weights=active_weights,
        thresholds=active_thresholds,
        season_weights=season_weights,
        macro_ranges=spec.macro_ranges,
    )
    report_path = destination / "report.json"
    report = {
        "schema_version": NBA_MANAGER_EXPERIMENT_SCHEMA_VERSION,
        "version": NBA_MANAGER_EXPERIMENT_VERSION,
        "evidence_version": NBA_MANAGER_EVIDENCE_VERSION,
        "plan_sha256": sha256_file(plan_path),
        "initial_state_sha256": sha256_file(initial_path),
        "cell_count": expected_cells,
        "evidence": asdict(evidence),
        "cells": [{"path": path, "sha256": digest} for path, digest in sorted(cell_index.items())],
    }
    write_json(report_path, report)
    manifest_path = destination / "manifest.json"
    write_json(
        manifest_path,
        {
            "schema_version": NBA_MANAGER_EXPERIMENT_SCHEMA_VERSION,
            "version": NBA_MANAGER_EXPERIMENT_VERSION,
            "plan": {"path": "plan.json", "sha256": sha256_file(plan_path)},
            "initial_state": {
                "path": "initial-state.json.gz",
                "sha256": sha256_file(initial_path),
            },
            "progress": {"path": "progress.json", "sha256": sha256_file(progress_path)},
            "report": {"path": "report.json", "sha256": sha256_file(report_path)},
            "cells": report["cells"],
        },
    )
    verified = verify_nba_manager_experiment(report_path)
    return NBAManagerExperimentResult(
        True,
        executed,
        reused,
        completed_sources,
        progress_path,
        report_path,
        manifest_path,
        verified,
    )


def verify_nba_manager_experiment(report_path: str | Path) -> NBAFrontOfficeEvidenceResult:
    report_file = Path(report_path)
    destination = report_file.parent
    report = _load_json_object(report_file, "NBA manager report")
    _exact(
        report,
        {
            "schema_version",
            "version",
            "evidence_version",
            "plan_sha256",
            "initial_state_sha256",
            "cell_count",
            "evidence",
            "cells",
        },
        "NBA manager report",
    )
    if (
        report["schema_version"] != NBA_MANAGER_EXPERIMENT_SCHEMA_VERSION
        or report["version"] != NBA_MANAGER_EXPERIMENT_VERSION
        or report["evidence_version"] != NBA_MANAGER_EVIDENCE_VERSION
    ):
        raise NBAManagerExperimentError("unsupported NBA manager report")
    plan_path = destination / "plan.json"
    initial_path = destination / "initial-state.json.gz"
    if (
        not plan_path.is_file()
        or sha256_file(plan_path) != report["plan_sha256"]
        or not initial_path.is_file()
        or sha256_file(initial_path) != report["initial_state_sha256"]
    ):
        raise NBAManagerExperimentError("NBA manager plan or initial state changed")
    spec, weights, thresholds, season_weights = _parse_plan(plan_path)
    initial = _load_gzip_object(initial_path, "NBA manager initial state")
    _exact(initial, {"state_payload"}, "NBA manager initial state")
    state_payload = initial["state_payload"]
    if (
        not isinstance(state_payload, str)
        or _sha256_text(state_payload) != spec.initial_state_sha256
    ):
        raise NBAManagerExperimentError("NBA manager initial state differs from plan")
    raw_cells = report["cells"]
    if not isinstance(raw_cells, list) or len(raw_cells) != report["cell_count"]:
        raise NBAManagerExperimentError("NBA manager cell index is invalid")
    outcomes: dict[tuple[str, int, int, str, NBAManagerExperimentArm], NBAFrontOfficeOutcome] = {}
    previous: dict[tuple[str, NBAManagerExperimentArm], str] = {}
    for raw in raw_cells:
        item = _object(raw, "NBA manager cell index entry")
        _exact(item, {"path", "sha256"}, "NBA manager cell index entry")
        relative = _safe_relative(item["path"])
        cell_path = destination / relative
        if not cell_path.is_file() or sha256_file(cell_path) != item["sha256"]:
            raise NBAManagerExperimentError("NBA manager cell changed")
        cell = _load_gzip_object(cell_path, "NBA manager cell")
        request = _request_from_cell(cell)
        _validate_request_against_spec(request, spec)
        if relative != _cell_relative(request.source_id, request.arm, request.season_year):
            raise NBAManagerExperimentError("NBA manager cell path differs from request")
        expected_state = previous.get((request.source_id, request.arm), state_payload)
        if request.state_payload != expected_state:
            raise NBAManagerExperimentError("NBA manager state continuity is broken")
        execution = _execution_from_cell(cell)
        _validate_execution(execution, request, formal_run=spec.formal_run)
        if cell["request_sha256"] != _digest(_request_payload(request)):
            raise NBAManagerExperimentError("NBA manager request digest differs")
        previous[(request.source_id, request.arm)] = execution.next_state_payload
        outcomes[(*execution.outcome.address, request.arm)] = execution.outcome
    evidence = evaluate_nba_front_office_policy(
        baseline_policy_id=spec.baseline_policy_id,
        candidate_policy_id=spec.candidate_policy_id,
        observations=_paired_outcomes(outcomes),
        weights=weights,
        thresholds=thresholds,
        season_weights=season_weights,
        macro_ranges=spec.macro_ranges,
    )
    if _json_value(asdict(evidence)) != report["evidence"]:
        raise NBAManagerExperimentError("NBA manager evidence cannot be reproduced")
    return evidence


def inspect_nba_manager_experiment(path: str | Path) -> dict[str, object]:
    """Verify a complete report or summarize a hash-verified partial study."""
    candidate = Path(path)
    destination = candidate if candidate.is_dir() else candidate.parent
    report_path = destination / "report.json"
    if candidate.name == "report.json":
        report_path = candidate
    if report_path.is_file():
        evidence = verify_nba_manager_experiment(report_path)
        report = _load_json_object(report_path, "NBA manager report")
        return {
            "version": NBA_MANAGER_EXPERIMENT_VERSION,
            "complete": True,
            "status": "candidate-pass" if evidence.recommended else "candidate-fail",
            "completed_cells": report["cell_count"],
            "independent_sources": evidence.independent_sources,
            "evidence_digest": evidence.evidence_digest,
            "recommended": evidence.recommended,
        }
    plan_path = destination / "plan.json"
    initial_path = destination / "initial-state.json.gz"
    progress_path = destination / "progress.json"
    if not all(item.is_file() for item in (plan_path, initial_path, progress_path)):
        raise NBAManagerExperimentError("NBA manager partial study is incomplete")
    spec, _, _, _ = _parse_plan(plan_path)
    cells = _load_progress(progress_path, plan_path, initial_path)
    expected = len(spec.master_seeds) * len(NBAManagerExperimentArm) * spec.seasons
    completed_sources = sum(
        _source_complete(destination, f"source-{index:04d}", spec)
        for index in range(1, len(spec.master_seeds) + 1)
    )
    return {
        "version": NBA_MANAGER_EXPERIMENT_VERSION,
        "complete": False,
        "status": "running",
        "completed_cells": len(cells),
        "expected_cells": expected,
        "completed_sources": completed_sources,
        "expected_sources": len(spec.master_seeds),
        "formal_run": spec.formal_run,
    }


def build_nba_manager_candidate_receipt(
    report_path: str | Path,
    *,
    git_commit: str,
    ci_checks: Mapping[str, str],
) -> dict[str, object]:
    """Build a WIP-only candidate receipt after all required CI checks pass."""
    report_file = Path(report_path)
    evidence = verify_nba_manager_experiment(report_file)
    spec, weights, thresholds, season_weights = _parse_plan(report_file.parent / "plan.json")
    if not spec.formal_run:
        raise NBAManagerExperimentError("development studies cannot produce candidate receipts")
    current_commit, current_tree = nba_manager_code_identity(require_clean=True)
    if git_commit != spec.code_commit or current_commit != spec.code_commit:
        raise NBAManagerExperimentError("candidate receipt Git commit differs from the study")
    if current_tree != spec.code_tree_sha256:
        raise NBAManagerExperimentError("candidate receipt code tree differs from the study")
    protocol_sha256 = dict(spec.source_hashes).get(NBA_MANAGER_PROTOCOL_SOURCE_ROLE)
    if protocol_sha256 is None:
        raise NBAManagerExperimentError("candidate receipt lacks the frozen promotion protocol")
    verify_nba_manager_protocol_file(
        canonical_nba_manager_protocol_path(),
        protocol_sha256,
    )
    protocol = load_nba_manager_promotion_protocol(canonical_nba_manager_protocol_path())
    input_hashes = tuple(
        item for item in spec.source_hashes if item[0] != NBA_MANAGER_PROTOCOL_SOURCE_ROLE
    )
    if (
        protocol.experiment_id != spec.experiment_id
        or protocol.start_season != spec.start_season
        or protocol.initial_state_sha256 != spec.initial_state_sha256
        or protocol.source_hashes != input_hashes
        or protocol.execution_config_sha256 != spec.execution_config_sha256
        or protocol.macro_ranges != spec.macro_ranges
        or protocol.team_ids != spec.team_ids
        or protocol.master_seeds != spec.master_seeds
        or protocol.focal_team_ids != spec.focal_team_ids
        or protocol.seasons != spec.seasons
    ):
        raise NBAManagerExperimentError("candidate receipt differs from frozen promotion protocol")
    if set(ci_checks) != set(NBA_MANAGER_REQUIRED_CI):
        raise NBAManagerExperimentError("NBA manager candidate receipt requires exact CI checks")
    ci_attestations: dict[str, dict[str, object]] = {}
    for name, value in ci_checks.items():
        status, separator, remainder = value.partition("@")
        commit, second_separator, url = remainder.partition("@")
        if (
            status != "passed"
            or not separator
            or not second_separator
            or commit != spec.code_commit
            or not url.startswith("https://github.com/")
            or "/actions/runs/" not in url
        ):
            raise NBAManagerExperimentError(
                "NBA manager candidate receipt requires commit-bound GitHub CI attestations"
            )
        _verify_github_ci_attestation(name, url, spec.code_commit)
        _, job_name, steps = _ci_proof(name)
        ci_attestations[name] = {
            "status": status,
            "commit": commit,
            "url": url,
            "job": job_name,
            "steps": list(steps),
        }
    return {
        "schema_version": NBA_MANAGER_EXPERIMENT_SCHEMA_VERSION,
        "version": "nba-manager-policy-candidate-v1",
        "status": "candidate-pass" if evidence.recommended else "candidate-fail",
        "governance": "wip-not-promoted",
        "active_registry_modified": False,
        "release_created": False,
        "git_commit": git_commit,
        "experiment_id": spec.experiment_id,
        "baseline_policy_id": spec.baseline_policy_id,
        "candidate_policy_id": spec.candidate_policy_id,
        "execution_config_sha256": spec.execution_config_sha256,
        "initial_state_sha256": spec.initial_state_sha256,
        "source_hashes": dict(spec.source_hashes),
        "evidence": asdict(evidence),
        "weights": asdict(weights),
        "thresholds": asdict(thresholds),
        "season_weights": list(season_weights),
        "report_sha256": sha256_file(report_file),
        "code_tree_sha256": spec.code_tree_sha256,
        "ci": dict(sorted(ci_attestations.items())),
    }


def _verify_github_ci_attestation(name: str, url: str, commit: str) -> None:
    _, expected_job_name, expected_steps = _ci_proof(name)
    prefix = "https://github.com/cc78978559/courtsim/actions/runs/"
    run_id = url.removeprefix(prefix).split("/", 1)[0]
    if not url.startswith(prefix) or not run_id.isdigit():
        raise NBAManagerExperimentError("NBA manager CI URL must identify the courtsim repository")
    api_root = f"https://api.github.com/repos/cc78978559/courtsim/actions/runs/{run_id}"
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "courtsim-promotion"}
    try:
        with urllib.request.urlopen(
            urllib.request.Request(api_root, headers=headers), timeout=20
        ) as response:
            run = _object(json.loads(response.read().decode("utf-8")), "GitHub Actions run")
        with urllib.request.urlopen(
            urllib.request.Request(f"{api_root}/jobs?per_page=100", headers=headers), timeout=20
        ) as response:
            jobs = _object(json.loads(response.read().decode("utf-8")), "GitHub Actions jobs")
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, urllib.error.URLError) as error:
        raise NBAManagerExperimentError(
            "cannot verify NBA manager GitHub CI attestation"
        ) from error
    raw_jobs = jobs.get("jobs")
    successful_job = (
        next(
            (
                job
                for job in raw_jobs
                if isinstance(job, dict)
                and job.get("name") == expected_job_name
                and job.get("conclusion") == "success"
            ),
            None,
        )
        if isinstance(raw_jobs, list)
        else None
    )
    if (
        run.get("head_sha") != commit
        or run.get("conclusion") != "success"
        or _object(run.get("repository"), "GitHub repository").get("full_name")
        != "cc78978559/courtsim"
        or successful_job is None
    ):
        raise NBAManagerExperimentError("NBA manager GitHub CI attestation is not successful")
    if expected_steps:
        raw_steps = successful_job.get("steps")
        successful_steps = (
            {
                str(step.get("name"))
                for step in raw_steps
                if isinstance(step, dict) and step.get("conclusion") == "success"
            }
            if isinstance(raw_steps, list)
            else set()
        )
        if not set(expected_steps) <= successful_steps:
            raise NBAManagerExperimentError("NBA manager GitHub CI proof steps are incomplete")


def _ci_proof(name: str) -> tuple[str, str, tuple[str, ...]]:
    try:
        return next(item for item in NBA_MANAGER_CI_PROOFS if item[0] == name)
    except StopIteration as error:
        raise NBAManagerExperimentError("unknown NBA manager CI proof") from error


def _plan_payload(
    spec: NBAManagerExperimentSpec,
    weights: NBAFrontOfficeEvaluationWeights,
    thresholds: NBAFrontOfficeEvidenceThresholds,
    season_weights: tuple[float, ...],
) -> dict[str, object]:
    return _json_object(
        {
            "schema_version": NBA_MANAGER_EXPERIMENT_SCHEMA_VERSION,
            "version": NBA_MANAGER_EXPERIMENT_VERSION,
            "spec": asdict(spec),
            "weights": asdict(weights),
            "thresholds": asdict(thresholds),
            "season_weights": list(season_weights),
        }
    )


def _parse_plan(
    plan_path: Path,
) -> tuple[
    NBAManagerExperimentSpec,
    NBAFrontOfficeEvaluationWeights,
    NBAFrontOfficeEvidenceThresholds,
    tuple[float, ...],
]:
    plan = _load_json_object(plan_path, "NBA manager plan")
    _exact(
        plan,
        {"schema_version", "version", "spec", "weights", "thresholds", "season_weights"},
        "NBA manager plan",
    )
    spec_raw = _object(plan["spec"], "NBA manager spec")
    spec_raw["master_seeds"] = tuple(spec_raw["master_seeds"])
    spec_raw["focal_team_ids"] = tuple(spec_raw["focal_team_ids"])
    spec_raw["team_ids"] = tuple(spec_raw["team_ids"])
    spec_raw["source_hashes"] = tuple(tuple(item) for item in spec_raw["source_hashes"])
    spec_raw["macro_ranges"] = tuple(tuple(item) for item in spec_raw["macro_ranges"])
    return (
        NBAManagerExperimentSpec(**spec_raw),
        NBAFrontOfficeEvaluationWeights(**_object(plan["weights"], "weights")),
        NBAFrontOfficeEvidenceThresholds(**_object(plan["thresholds"], "thresholds")),
        tuple(cast(list[float], plan["season_weights"])),
    )


def _request_payload(request: NBAManagerSeasonRequest) -> dict[str, object]:
    return {
        "experiment_id": request.experiment_id,
        "baseline_policy_id": request.baseline_policy_id,
        "candidate_policy_id": request.candidate_policy_id,
        "arm": request.arm.name.lower(),
        "source_id": request.source_id,
        "master_seed": request.master_seed,
        "focal_team_id": request.focal_team_id,
        "season_year": request.season_year,
        "state_sha256": _sha256_text(request.state_payload),
    }


def _cell_payload(
    request_digest: str,
    request: NBAManagerSeasonRequest,
    execution: NBAManagerSeasonExecution,
) -> dict[str, object]:
    execution_value = {
        "next_state_payload": execution.next_state_payload,
        "outcome": asdict(execution.outcome),
        "audit_payload": execution.audit_payload,
    }
    return {
        "schema_version": NBA_MANAGER_EXPERIMENT_SCHEMA_VERSION,
        "version": NBA_MANAGER_EXPERIMENT_VERSION,
        "request_sha256": request_digest,
        "request": {**_request_payload(request), "state_payload": request.state_payload},
        "execution_sha256": _digest(execution_value),
        "execution": execution_value,
    }


def _load_cell(
    path: Path,
    request_digest: str,
    request: NBAManagerSeasonRequest,
    formal_run: bool,
) -> NBAManagerSeasonExecution:
    cell = _load_gzip_object(path, "NBA manager cell")
    if cell.get("request_sha256") != request_digest:
        raise NBAManagerExperimentError("NBA manager cell request differs")
    stored_request = _request_from_cell(cell)
    if stored_request != request:
        raise NBAManagerExperimentError("NBA manager stored request differs")
    execution = _execution_from_cell(cell)
    _validate_execution(execution, request, formal_run=formal_run)
    return execution


def _request_from_cell(cell: Mapping[str, object]) -> NBAManagerSeasonRequest:
    request = _object(cell["request"], "NBA manager request")
    try:
        arm = NBAManagerExperimentArm[str(request["arm"]).upper()]
        return NBAManagerSeasonRequest(
            str(request["experiment_id"]),
            str(request["baseline_policy_id"]),
            str(request["candidate_policy_id"]),
            arm,
            str(request["source_id"]),
            int(request["master_seed"]),
            str(request["focal_team_id"]),
            int(request["season_year"]),
            str(request["state_payload"]),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise NBAManagerExperimentError("invalid NBA manager cell request") from error


def _execution_from_cell(cell: Mapping[str, object]) -> NBAManagerSeasonExecution:
    execution = _object(cell["execution"], "NBA manager execution")
    if cell.get("execution_sha256") != _digest(execution):
        raise NBAManagerExperimentError("NBA manager execution digest differs")
    try:
        outcome = _object(execution["outcome"], "NBA manager outcome")
        outcome["macro_metrics"] = tuple(
            (str(item[0]), float(cast(int | float, item[1])))
            for item in cast(list[list[object]], outcome.get("macro_metrics", []))
        )
        return NBAManagerSeasonExecution(
            str(execution["next_state_payload"]),
            NBAFrontOfficeOutcome(**outcome),
            str(execution["audit_payload"]),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise NBAManagerExperimentError("invalid NBA manager execution") from error


def _validate_execution(
    execution: NBAManagerSeasonExecution,
    request: NBAManagerSeasonRequest,
    *,
    formal_run: bool,
) -> None:
    expected = (request.source_id, request.master_seed, request.season_year, request.focal_team_id)
    if execution.outcome.address != expected:
        raise NBAManagerExperimentError("NBA manager execution outcome address differs")
    if formal_run:
        audit = _object(json.loads(execution.audit_payload), "NBA manager canonical audit")
        expected_candidates = (
            [] if request.arm is NBAManagerExperimentArm.CONTROL else [request.focal_team_id]
        )
        if (
            audit.get("version") != "nba-manager-adapter-v1"
            or audit.get("arm") != request.arm.name.lower()
            or audit.get("focal_team_id") != request.focal_team_id
            or audit.get("candidate_teams") != expected_candidates
            or audit.get("outcome") != _json_value(asdict(execution.outcome))
        ):
            raise NBAManagerExperimentError("formal NBA manager execution lacks canonical audit")


def _validate_request_against_spec(
    request: NBAManagerSeasonRequest,
    spec: NBAManagerExperimentSpec,
) -> None:
    try:
        source_index = int(request.source_id.removeprefix("source-")) - 1
    except ValueError as error:
        raise NBAManagerExperimentError("NBA manager request source identity is invalid") from error
    if (
        request.experiment_id != spec.experiment_id
        or request.baseline_policy_id != spec.baseline_policy_id
        or request.candidate_policy_id != spec.candidate_policy_id
        or not 0 <= source_index < len(spec.master_seeds)
        or request.source_id != f"source-{source_index + 1:04d}"
        or request.master_seed != spec.master_seeds[source_index]
        or request.focal_team_id != spec.focal_team_ids[source_index]
        or not spec.start_season <= request.season_year < spec.start_season + spec.seasons
    ):
        raise NBAManagerExperimentError("NBA manager request differs from frozen plan")


def _paired_outcomes(
    outcomes: Mapping[tuple[str, int, int, str, NBAManagerExperimentArm], NBAFrontOfficeOutcome],
) -> tuple[PairedNBAFrontOfficeOutcome, ...]:
    addresses = sorted({key[:-1] for key in outcomes})
    paired = []
    for address in addresses:
        control = outcomes.get((*address, NBAManagerExperimentArm.CONTROL))
        treatment = outcomes.get((*address, NBAManagerExperimentArm.TREATMENT))
        if control is None or treatment is None:
            raise NBAManagerExperimentError("NBA manager evidence is missing a paired arm")
        paired.append(PairedNBAFrontOfficeOutcome(control, treatment))
    return tuple(paired)


def _source_complete(destination: Path, source_id: str, spec: NBAManagerExperimentSpec) -> bool:
    return all(
        (destination / _cell_relative(source_id, arm, spec.start_season + offset)).is_file()
        for arm in NBAManagerExperimentArm
        for offset in range(spec.seasons)
    )


def _cell_relative(source_id: str, arm: NBAManagerExperimentArm, season_year: int) -> Path:
    return Path("sources") / source_id / arm.name.lower() / f"season-{season_year}.json.gz"


def _write_progress(
    path: Path,
    plan_path: Path,
    initial_path: Path,
    cells: Mapping[str, str],
) -> None:
    write_json(
        path,
        {
            "schema_version": NBA_MANAGER_EXPERIMENT_SCHEMA_VERSION,
            "version": NBA_MANAGER_EXPERIMENT_VERSION,
            "plan_sha256": sha256_file(plan_path),
            "initial_state_sha256": sha256_file(initial_path),
            "cells": [{"path": key, "sha256": value} for key, value in sorted(cells.items())],
        },
    )


def _load_progress(path: Path, plan_path: Path, initial_path: Path) -> dict[str, str]:
    value = _load_json_object(path, "NBA manager progress")
    _exact(
        value,
        {"schema_version", "version", "plan_sha256", "initial_state_sha256", "cells"},
        "NBA manager progress",
    )
    if value["plan_sha256"] != sha256_file(plan_path) or value[
        "initial_state_sha256"
    ] != sha256_file(initial_path):
        raise NBAManagerExperimentError("NBA manager progress inputs differ")
    result: dict[str, str] = {}
    for raw in cast(list[object], value["cells"]):
        item = _object(raw, "NBA manager progress cell")
        relative = _safe_relative(item["path"])
        cell = path.parent / relative
        if not cell.is_file() or sha256_file(cell) != item["sha256"]:
            raise NBAManagerExperimentError("NBA manager progress cell changed")
        result[relative.as_posix()] = str(item["sha256"])
    return result


def _establish_json(path: Path, value: object, label: str) -> None:
    if path.exists():
        if _load_json_object(path, label) != value:
            raise NBAManagerExperimentError(f"existing {label} conflicts with requested run")
    else:
        write_json(path, value)


def _establish_gzip(path: Path, value: object, label: str) -> None:
    if path.exists():
        if _load_gzip_object(path, label) != value:
            raise NBAManagerExperimentError(f"existing {label} conflicts with requested run")
    else:
        _write_gzip_json(path, value)


def _write_gzip_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")
    handle, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(handle, "wb") as stream:
            with gzip.GzipFile(fileobj=stream, mode="wb", mtime=0) as compressed:
                compressed.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _load_gzip_object(path: Path, label: str) -> dict[str, Any]:
    try:
        return _object(json.loads(gzip.decompress(path.read_bytes()).decode("utf-8")), label)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise NBAManagerExperimentError(f"invalid {label}") from error


def _load_json_object(path: Path, label: str) -> dict[str, Any]:
    try:
        return _object(json.loads(path.read_text(encoding="utf-8")), label)
    except (OSError, json.JSONDecodeError) as error:
        raise NBAManagerExperimentError(f"invalid {label}") from error


def _safe_relative(value: object) -> Path:
    if not isinstance(value, str) or not value:
        raise NBAManagerExperimentError("NBA manager artifact path is invalid")
    posix_path = PurePosixPath(value)
    windows_path = PureWindowsPath(value)
    if (
        posix_path.is_absolute()
        or windows_path.is_absolute()
        or bool(windows_path.drive)
        or ".." in posix_path.parts
        or ".." in windows_path.parts
    ):
        raise NBAManagerExperimentError("NBA manager artifact path escapes its run")
    return Path(*posix_path.parts)


def _object(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise NBAManagerExperimentError(f"{label} must be an object")
    return cast(dict[str, Any], value)


def _json_value(value: object) -> object:
    return json.loads(json.dumps(value, ensure_ascii=False, sort_keys=True))


def _json_object(value: object) -> dict[str, object]:
    return cast(dict[str, object], _json_value(value))


def _exact(value: Mapping[str, object], keys: set[str], label: str) -> None:
    if set(value) != keys:
        raise NBAManagerExperimentError(f"{label} fields differ")


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _validate_digest(value: str, label: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"NBA manager {label} SHA-256 is invalid")

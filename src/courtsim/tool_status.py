"""Compact, machine-readable readiness status for local CourtSim workspaces."""

from __future__ import annotations

import hashlib
import json
import platform
import subprocess
import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any, cast

from courtsim import __version__

PROJECT_STATUS_SCHEMA_VERSION = 3

_SPECIAL_ARTIFACT_FIELDS = (
    ("model.schema", "model", "schema_path", "schema_file_sha256"),
    ("model.parameters", "model", "parameter_path", "parameter_file_sha256"),
    ("audit.baseline", "audit", "baseline_path", "baseline_sha256"),
)


class ProjectStatusError(ValueError):
    """Raised when a workspace cannot produce a trustworthy status report."""


def build_project_status(root: str | Path) -> dict[str, object]:
    workspace = Path(root).resolve()
    release_path = workspace / "governance" / "current-release.json"
    candidate_path = workspace / "governance" / "current-candidate.json"
    development_map_path = workspace / "docs" / "development-map-v1.json"
    manager_protocol_path = (
        workspace / "experiments" / "promotion" / "nba-manager-policy-v1-protocol.json"
    )
    release_object = _load_registry(release_path, "current release")
    candidate_object = _load_registry(candidate_path, "current candidate")
    development_map = _load_registry(development_map_path, "development map")
    manager_protocol = _load_registry(manager_protocol_path, "NBA manager promotion protocol")
    if development_map.get("version") != "courtsim-development-map-v1":
        raise ProjectStatusError("development map version differs")
    if manager_protocol.get("status") != "frozen":
        raise ProjectStatusError("NBA manager promotion protocol is not frozen")
    master_seeds = manager_protocol.get("master_seeds")
    seasons = manager_protocol.get("seasons")
    if not isinstance(master_seeds, list) or not all(
        isinstance(seed, int) for seed in master_seeds
    ):
        raise ProjectStatusError("NBA manager promotion seeds are invalid")
    if not isinstance(seasons, int) or seasons < 1:
        raise ProjectStatusError("NBA manager promotion seasons are invalid")
    release_engine_version = release_object.get("engine_version")
    candidate_engine_version = candidate_object.get("engine_version")
    if not isinstance(release_engine_version, str):
        raise ProjectStatusError("current release engine version is missing")
    if candidate_engine_version != __version__:
        raise ProjectStatusError("current candidate engine version differs")
    if candidate_object.get("base_release_engine_version") != release_engine_version:
        raise ProjectStatusError("current candidate base release differs")
    try:
        installed_version = version("courtsim")
    except PackageNotFoundError as error:
        raise ProjectStatusError("courtsim distribution metadata is missing") from error
    if installed_version != __version__:
        raise ProjectStatusError("installed courtsim distribution version differs")
    release_verified, release_mismatches = _verify_registry(workspace, release_object)
    candidate_verified, candidate_mismatches = _verify_registry(workspace, candidate_object)
    git = _git_status(workspace)
    return {
        "schema_version": PROJECT_STATUS_SCHEMA_VERSION,
        "courtsim_version": __version__,
        "installed_distribution_version": installed_version,
        "python_version": platform.python_version(),
        "python_executable": sys.executable,
        "release": {
            "format_version": release_object.get("format_version"),
            "status": release_object.get("status"),
            "engine_version": release_engine_version,
            "matches_workspace": release_engine_version == __version__,
            "registry_sha256": _sha256(release_path),
            "verified_files": release_verified,
            "hashes_ok": not release_mismatches,
            "mismatches": release_mismatches,
        },
        "candidate": {
            "format_version": candidate_object.get("format_version"),
            "status": candidate_object.get("status"),
            "engine_version": candidate_engine_version,
            "base_release_engine_version": candidate_object.get("base_release_engine_version"),
            "capability_scope": candidate_object.get("capability_scope"),
            "capabilities": candidate_object.get("capabilities"),
            "registry_sha256": _sha256(candidate_path),
            "verified_files": candidate_verified,
            "hashes_ok": not candidate_mismatches,
            "mismatches": candidate_mismatches,
        },
        "workspace": git,
        "development": {
            "map_version": development_map["version"],
            "map_path": development_map_path.relative_to(workspace).as_posix(),
            "map_sha256": _sha256(development_map_path),
            "fast_target_seconds": 35,
            "timing_receipt": "work/metrics/check-timed-latest.json",
            "cli_modules": [
                "courtsim.cli",
                "courtsim.cli_artifacts",
                "courtsim.cli_manager",
            ],
            "ci_coverage_shards": ["not slow", "slow"],
        },
        "manager_formal_holdout": {
            "policy_status": "shadow",
            "protocol_status": manager_protocol["status"],
            "protocol_path": manager_protocol_path.relative_to(workspace).as_posix(),
            "protocol_sha256": _sha256(manager_protocol_path),
            "holdout_id": manager_protocol.get("holdout_id"),
            "independent_sources": len(master_seeds),
            "seasons_per_source": seasons,
            "arms": 2,
            "total_cells": len(master_seeds) * seasons * 2,
            "partial_effect_access": "forbidden-until-complete",
            "activation": "not-authorized",
        },
        "capabilities": [
            "deterministic-game-simulation",
            "local-nba-data-pipeline",
            "nba-data-source-audit",
            "nba-possession-source-audit",
            "nba-shot-zone-source-audit",
            "nba-team-shot-zone-profiles",
            "nba-team-shot-zone-evaluation",
            "nba-team-shot-zone-baseline-recalibration",
            "nba-team-shot-zone-calibrated-artifacts",
            "nba-team-shot-zone-experiment-runner",
            "nba-team-shot-zone-resumable-batch",
            "nba-team-shot-zone-batch-inspection",
            "nba-player-realism-target-schema",
            "nba-player-box-score-parquet-source",
            "nba-player-id-crosswalk-audit",
            "nba-player-simulation-audit",
            "nba-player-multiseed-evaluation",
            "route-creation-tactical-audit",
            "derived-tactical-action-vocabulary",
            "draft-obligation-freeze-ledger-v3",
            "draft-obligation-read-only-audit",
            "draft-obligation-transaction-enforcement",
            "three-team-market-v2-contract-tree",
            "three-team-market-v2-franchise-integration",
            "local-composite-group-reduction",
            "nba-reference-targets",
            "nba-quick-sim-inspection",
            "nba-quick-sim-comparison",
            "nba-quick-sim-paired-comparison",
            "nba-multiseason-standings-playoffs-reality",
            "nba-quick-sim-formal-gate",
            "nba-quick-sim-input-pinned-runner",
            "nba-source-pinned-real-player-rosters",
            "nba-quick-sim-parallel-checkpoint-waves",
            "nba-source-derived-team-strength",
            "nba-source-pinned-conference-alignment",
            "nba-source-pinned-division-alignment",
            "nba-aggregate-quick-sim-runner",
            "nba-aggregate-quick-sim-formal-gate",
            "nba-franchise-checkpoint-verification",
            "nba-franchise-manifest-inspection",
            "artifact-retention",
        ],
        "recommended_commands": {
            "changed": ".\\tools.cmd check-changed",
            "fast": ".\\tools.cmd check-fast",
            "timed": ".\\tools.cmd check-timed",
            "static": ".\\tools.cmd check-static",
            "unit": ".\\tools.cmd check-unit",
            "franchise": ".\\tools.cmd check-franchise",
            "full": ".\\tools.cmd check",
        },
    }


def _load_registry(path: Path, label: str) -> dict[str, Any]:
    if not path.is_file():
        raise ProjectStatusError(f"{path.as_posix()} is missing")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as error:
        raise ProjectStatusError(f"{label} cannot be read: {error}") from error
    if not isinstance(value, dict):
        raise ProjectStatusError(f"{label} must be an object")
    return cast(dict[str, Any], value)


def _verify_registry(
    workspace: Path,
    registry: dict[str, Any],
) -> tuple[int, list[str]]:
    references: list[tuple[str, object, object]] = []
    for name, value in sorted(registry.items()):
        if isinstance(value, dict) and ("path" in value or "file_sha256" in value):
            references.append((name, value.get("path"), value.get("file_sha256")))
    for label, section, path_field, digest_field in _SPECIAL_ARTIFACT_FIELDS:
        value = registry.get(section)
        if isinstance(value, dict) and (path_field in value or digest_field in value):
            references.append((label, value.get(path_field), value.get(digest_field)))
    verified = 0
    mismatches: list[str] = []
    for label, path_value, digest_value in references:
        if not isinstance(path_value, str) or not isinstance(digest_value, str):
            mismatches.append(label)
            continue
        governed_path = workspace / path_value
        if not governed_path.is_file() or _sha256(governed_path) != digest_value:
            mismatches.append(label)
            continue
        verified += 1
    return verified, mismatches


def _git_status(root: Path) -> dict[str, object]:
    branch = _git(root, "branch", "--show-current")
    porcelain = _git(root, "status", "--porcelain")
    upstream = _git(root, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}")
    ahead = None
    behind = None
    if upstream:
        counts = _git(root, "rev-list", "--left-right", "--count", f"{upstream}...HEAD")
        if counts:
            parts = counts.split()
            if len(parts) == 2 and all(part.isdigit() for part in parts):
                behind, ahead = (int(part) for part in parts)
    return {
        "branch": branch or None,
        "upstream": upstream or None,
        "dirty": bool(porcelain),
        "ahead": ahead,
        "behind": behind,
    }


def _git(root: Path, *arguments: str) -> str:
    try:
        completed = subprocess.run(
            ("git", *arguments),
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return completed.stdout.strip() if completed.returncode == 0 else ""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()

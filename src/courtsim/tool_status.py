"""Compact, machine-readable readiness status for local CourtSim workspaces."""

from __future__ import annotations

import hashlib
import json
import platform
import subprocess
import sys
from pathlib import Path
from typing import Any, cast

from courtsim import __version__

PROJECT_STATUS_SCHEMA_VERSION = 1


class ProjectStatusError(ValueError):
    """Raised when a workspace cannot produce a trustworthy status report."""


def build_project_status(root: str | Path) -> dict[str, object]:
    workspace = Path(root).resolve()
    release_path = workspace / "governance" / "current-release.json"
    if not release_path.is_file():
        raise ProjectStatusError("governance/current-release.json is missing")
    try:
        release = json.loads(release_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as error:
        raise ProjectStatusError(f"current release cannot be read: {error}") from error
    if not isinstance(release, dict):
        raise ProjectStatusError("current release must be an object")
    release_object = cast(dict[str, Any], release)
    engine_version = release_object.get("engine_version")
    if engine_version != __version__:
        raise ProjectStatusError("current release engine version differs")
    verified_files = 0
    mismatches: list[str] = []
    for name, value in sorted(release_object.items()):
        if not isinstance(value, dict) or "path" not in value or "file_sha256" not in value:
            continue
        path_value = value["path"]
        digest_value = value["file_sha256"]
        if not isinstance(path_value, str) or not isinstance(digest_value, str):
            mismatches.append(name)
            continue
        governed_path = workspace / path_value
        if not governed_path.is_file() or _sha256(governed_path) != digest_value:
            mismatches.append(name)
            continue
        verified_files += 1
    git = _git_status(workspace)
    return {
        "schema_version": PROJECT_STATUS_SCHEMA_VERSION,
        "courtsim_version": __version__,
        "python_version": platform.python_version(),
        "python_executable": sys.executable,
        "release": {
            "format_version": release_object.get("format_version"),
            "status": release_object.get("status"),
            "registry_sha256": _sha256(release_path),
            "verified_files": verified_files,
            "hashes_ok": not mismatches,
            "mismatches": mismatches,
        },
        "workspace": git,
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
            "three-team-market-v2-contract-tree",
            "local-composite-group-reduction",
            "nba-reference-targets",
            "nba-quick-sim-inspection",
            "nba-quick-sim-comparison",
            "nba-quick-sim-paired-comparison",
            "nba-multiseason-standings-playoffs-reality",
            "nba-quick-sim-formal-gate",
            "nba-quick-sim-input-pinned-runner",
            "nba-source-derived-team-strength",
            "nba-franchise-checkpoint-verification",
            "nba-franchise-manifest-inspection",
            "artifact-retention",
        ],
        "recommended_commands": {
            "fast": ".\\tools.cmd check-fast",
            "static": ".\\tools.cmd check-static",
            "unit": ".\\tools.cmd check-unit",
            "franchise": ".\\tools.cmd check-franchise",
            "full": ".\\tools.cmd check",
        },
    }


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

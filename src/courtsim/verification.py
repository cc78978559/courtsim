"""Verify hashes in a local simulation manifest."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from courtsim.artifacts import sha256_file


class VerificationError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class VerificationReport:
    checked: int
    issues: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.issues


def _load_manifest(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise VerificationError(f"cannot read {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise VerificationError(f"{path}:{exc.lineno}:{exc.colno}: {exc.msg}") from exc
    if not isinstance(raw, dict):
        raise VerificationError("manifest root must be an object")
    return raw


def verify_manifest(path: str | Path, *, check_inputs: bool = True) -> VerificationReport:
    manifest_path = Path(path)
    manifest = _load_manifest(manifest_path)
    groups = ["outputs"]
    if check_inputs:
        groups.append("inputs")
    checked = 0
    issues: list[str] = []
    for group in groups:
        entries = manifest.get(group)
        if not isinstance(entries, list):
            issues.append(f"manifest field {group!r} must be a list")
            continue
        for index, entry in enumerate(entries):
            if not isinstance(entry, dict):
                issues.append(f"{group}[{index}] must be an object")
                continue
            raw_path = entry.get("path")
            expected = entry.get("sha256")
            if not isinstance(raw_path, str) or not isinstance(expected, str):
                issues.append(f"{group}[{index}] requires string path and sha256")
                continue
            candidate = Path(raw_path)
            if not candidate.is_absolute():
                candidate = (
                    manifest_path.parent / candidate
                    if group == "outputs"
                    else Path.cwd() / candidate
                )
            if not candidate.is_file():
                issues.append(f"missing {group[:-1]}: {candidate}")
                continue
            checked += 1
            actual = sha256_file(candidate)
            if actual != expected:
                issues.append(f"hash mismatch: {candidate}")
    return VerificationReport(checked=checked, issues=tuple(issues))

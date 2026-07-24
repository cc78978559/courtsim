"""Read-only retention classification for generated artifacts."""

from __future__ import annotations

import json
from pathlib import Path, PurePosixPath
from typing import Any, cast

from courtsim.analysis.artifact_archive import (
    ArtifactArchiveError,
    build_artifact_archive_plan,
)
from courtsim.artifacts import sha256_file

POLICY_KIND = "courtsim-artifact-retention-policy"
REPORT_KIND = "courtsim-artifact-retention-report"
RULE_CATEGORIES = frozenset({"archive_candidate", "ignored", "protected"})
CATEGORY_PRECEDENCE = ("protected", "ignored", "archive_candidate")
ALL_CATEGORIES = ("unsafe", "protected", "ignored", "archive_candidate", "unclassified")
COMPARISON_KIND = "courtsim-artifact-retention-comparison"


class ArtifactRetentionError(ValueError):
    pass


def _load_json_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ArtifactRetentionError(f"cannot load {label}: {path}") from error
    if not isinstance(value, dict):
        raise ArtifactRetentionError(f"{label} must be an object")
    return cast(dict[str, Any], value)


def _valid_pattern(value: object) -> str:
    if not isinstance(value, str):
        raise ArtifactRetentionError("retention rule patterns must be strings")
    normalized = value.replace("\\", "/").strip()
    if (
        not normalized
        or PurePosixPath(normalized).is_absolute()
        or ":" in normalized
        or ".." in normalized.split("/")
    ):
        raise ArtifactRetentionError(f"invalid retention rule pattern: {value}")
    return normalized


def _load_policy(path: str | Path) -> tuple[Path, dict[str, Any]]:
    policy_path = Path(path).resolve()
    policy = _load_json_object(policy_path, "retention policy")
    if set(policy) != {
        "format_version",
        "kind",
        "policy_id",
        "status",
        "default_category",
        "rules",
    }:
        raise ArtifactRetentionError("retention policy fields do not match the v1 contract")
    if policy["format_version"] != 1 or policy["kind"] != POLICY_KIND:
        raise ArtifactRetentionError("retention policy identity is invalid")
    if (
        not isinstance(policy["policy_id"], str)
        or not policy["policy_id"].strip()
        or policy["status"] != "draft"
        or policy["default_category"] != "unclassified"
        or not isinstance(policy["rules"], list)
    ):
        raise ArtifactRetentionError("retention policy metadata is invalid")

    rule_ids: set[str] = set()
    normalized_rules: list[dict[str, Any]] = []
    for index, value in enumerate(policy["rules"]):
        if not isinstance(value, dict) or set(value) != {
            "id",
            "category",
            "patterns",
            "reason",
        }:
            raise ArtifactRetentionError(f"retention rule {index} is invalid")
        rule_id = value["id"]
        category = value["category"]
        reason = value["reason"]
        patterns = value["patterns"]
        if (
            not isinstance(rule_id, str)
            or not rule_id.strip()
            or rule_id in rule_ids
            or category not in RULE_CATEGORIES
            or not isinstance(reason, str)
            or not reason.strip()
            or not isinstance(patterns, list)
            or not patterns
        ):
            raise ArtifactRetentionError(f"retention rule {index} is invalid")
        rule_ids.add(rule_id)
        normalized_rules.append(
            {
                "id": rule_id,
                "category": category,
                "patterns": [_valid_pattern(pattern) for pattern in patterns],
                "reason": reason,
            }
        )
    normalized = dict(policy)
    normalized["rules"] = normalized_rules
    return policy_path, normalized


def _matches(relative: PurePosixPath, patterns: list[str]) -> bool:
    return any(relative.match(pattern) for pattern in patterns)


def _classify(
    relative: PurePosixPath,
    rules: list[dict[str, Any]],
    *,
    unsafe: bool,
) -> tuple[str, str | None, list[str]]:
    matched = [
        cast(str, rule["id"])
        for rule in rules
        if _matches(relative, cast(list[str], rule["patterns"]))
    ]
    if unsafe:
        return "unsafe", None, matched
    for category in CATEGORY_PRECEDENCE:
        for rule in rules:
            if rule["category"] == category and rule["id"] in matched:
                return category, cast(str, rule["id"]), matched
    return "unclassified", None, matched


def build_artifact_retention_report(
    root: str | Path,
    policy_path: str | Path,
) -> dict[str, Any]:
    directory = Path(root).resolve()
    if not directory.is_dir():
        raise ArtifactRetentionError(f"artifact root is not a directory: {directory}")
    resolved_policy, policy = _load_policy(policy_path)
    entries: list[dict[str, Any]] = []
    rules = cast(list[dict[str, Any]], policy["rules"])
    for path in directory.rglob("*"):
        relative = PurePosixPath(path.relative_to(directory).as_posix())
        is_symlink = path.is_symlink()
        if not is_symlink and not path.is_file():
            continue
        category, rule_id, matched_rule_ids = _classify(
            relative,
            rules,
            unsafe=is_symlink,
        )
        entries.append(
            {
                "path": relative.as_posix(),
                "bytes": path.lstat().st_size,
                "category": category,
                "rule_id": rule_id,
                "matched_rule_ids": matched_rule_ids,
            }
        )
    entries.sort(key=lambda entry: cast(str, entry["path"]))
    summary = {
        category: {
            "files": sum(entry["category"] == category for entry in entries),
            "bytes": sum(
                cast(int, entry["bytes"]) for entry in entries if entry["category"] == category
            ),
        }
        for category in ALL_CATEGORIES
    }
    summary["total"] = {
        "files": len(entries),
        "bytes": sum(cast(int, entry["bytes"]) for entry in entries),
    }
    return {
        "format_version": 1,
        "kind": REPORT_KIND,
        "root": directory.as_posix(),
        "policy": {
            "path": resolved_policy.as_posix(),
            "sha256": sha256_file(resolved_policy),
            "policy_id": policy["policy_id"],
            "status": policy["status"],
        },
        "summary": summary,
        "entries": entries,
    }


def _path_is_within(path: Path, directory: Path) -> bool:
    try:
        path.relative_to(directory)
    except ValueError:
        return False
    return True


def _load_report(path: str | Path) -> tuple[Path, dict[str, Any]]:
    report_path = Path(path).resolve()
    report = _load_json_object(report_path, "retention report")
    if set(report) != {"format_version", "kind", "root", "policy", "summary", "entries"}:
        raise ArtifactRetentionError("retention report fields do not match the v1 contract")
    if report["format_version"] != 1 or report["kind"] != REPORT_KIND:
        raise ArtifactRetentionError("retention report identity is invalid")
    if not isinstance(report["root"], str) or not isinstance(report["policy"], dict):
        raise ArtifactRetentionError("retention report metadata is invalid")
    root = Path(report["root"]).resolve()
    if not root.is_dir():
        raise ArtifactRetentionError("retention report root is unavailable")
    if _path_is_within(report_path, root):
        raise ArtifactRetentionError("retention report must be stored outside its scanned root")
    policy = cast(dict[str, Any], report["policy"])
    if set(policy) != {"path", "sha256", "policy_id", "status"}:
        raise ArtifactRetentionError("retention report policy reference is invalid")
    if (
        not isinstance(policy["path"], str)
        or not isinstance(policy["sha256"], str)
        or len(policy["sha256"]) != 64
        or any(character not in "0123456789abcdef" for character in policy["sha256"])
        or not isinstance(policy["policy_id"], str)
        or not policy["policy_id"]
        or policy["status"] != "draft"
    ):
        raise ArtifactRetentionError("retention report policy reference is invalid")
    _validated_report_entries(report)
    return report_path, report


def _validated_report_entries(report: dict[str, Any]) -> list[dict[str, Any]]:
    entries = report["entries"]
    if not isinstance(entries, list):
        raise ArtifactRetentionError("retention report entries are invalid")
    paths: list[str] = []
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict) or set(entry) != {
            "path",
            "bytes",
            "category",
            "rule_id",
            "matched_rule_ids",
        }:
            raise ArtifactRetentionError(f"retention report entry {index} is invalid")
        relative = entry["path"]
        size = entry["bytes"]
        category = entry["category"]
        rule_id = entry["rule_id"]
        matched = entry["matched_rule_ids"]
        if (
            not isinstance(relative, str)
            or not relative
            or "\\" in relative
            or ":" in relative
            or PurePosixPath(relative).is_absolute()
            or ".." in PurePosixPath(relative).parts
            or not isinstance(size, int)
            or isinstance(size, bool)
            or size < 0
            or category not in ALL_CATEGORIES
            or (rule_id is not None and not isinstance(rule_id, str))
            or not isinstance(matched, list)
            or not all(isinstance(value, str) and value for value in matched)
            or len(matched) != len(set(matched))
        ):
            raise ArtifactRetentionError(f"retention report entry {index} is invalid")
        paths.append(relative)
    if paths != sorted(set(paths)):
        raise ArtifactRetentionError("retention report entry paths must be unique and sorted")
    expected_summary = {
        category: {
            "files": sum(entry["category"] == category for entry in entries),
            "bytes": sum(
                cast(int, entry["bytes"]) for entry in entries if entry["category"] == category
            ),
        }
        for category in ALL_CATEGORIES
    }
    expected_summary["total"] = {
        "files": len(entries),
        "bytes": sum(cast(int, entry["bytes"]) for entry in entries),
    }
    if report["summary"] != expected_summary:
        raise ArtifactRetentionError("retention report summary does not match its entries")
    return cast(list[dict[str, Any]], entries)


def compare_artifact_retention_reports(
    baseline_path: str | Path,
    candidate_path: str | Path,
) -> dict[str, Any]:
    baseline_file, baseline = _load_report(baseline_path)
    candidate_file, candidate = _load_report(candidate_path)
    baseline_root = Path(cast(str, baseline["root"])).resolve()
    candidate_root = Path(cast(str, candidate["root"])).resolve()
    if baseline_root != candidate_root:
        raise ArtifactRetentionError("retention reports must describe the same root")
    baseline_entries = {
        cast(str, entry["path"]): entry for entry in _validated_report_entries(baseline)
    }
    candidate_entries = {
        cast(str, entry["path"]): entry for entry in _validated_report_entries(candidate)
    }
    changes: list[dict[str, Any]] = []
    for relative in sorted(baseline_entries.keys() | candidate_entries.keys()):
        before = baseline_entries.get(relative)
        after = candidate_entries.get(relative)
        change_kinds: list[str] = []
        if before is None:
            change_kinds.append("added")
        elif after is None:
            change_kinds.append("removed")
        else:
            if before["bytes"] != after["bytes"]:
                change_kinds.append("size_changed")
            if before["category"] != after["category"]:
                change_kinds.append("category_changed")
            if (
                before["rule_id"] != after["rule_id"]
                or before["matched_rule_ids"] != after["matched_rule_ids"]
            ):
                change_kinds.append("rule_changed")
        if change_kinds:
            changes.append(
                {
                    "path": relative,
                    "change_kinds": change_kinds,
                    "bytes_before": before["bytes"] if before is not None else None,
                    "bytes_after": after["bytes"] if after is not None else None,
                    "category_before": before["category"] if before is not None else None,
                    "category_after": after["category"] if after is not None else None,
                    "rule_id_before": before["rule_id"] if before is not None else None,
                    "rule_id_after": after["rule_id"] if after is not None else None,
                }
            )
    protection_losses = [
        change
        for change in changes
        if change["category_before"] == "protected" and change["category_after"] != "protected"
    ]
    archive_expansions = [
        change
        for change in changes
        if change["category_before"] != "archive_candidate"
        and change["category_after"] == "archive_candidate"
    ]
    newly_protected = [
        change
        for change in changes
        if change["category_before"] != "protected" and change["category_after"] == "protected"
    ]
    return {
        "format_version": 1,
        "kind": COMPARISON_KIND,
        "root": baseline_root.as_posix(),
        "baseline": {
            "path": baseline_file.as_posix(),
            "sha256": sha256_file(baseline_file),
            "policy_id": baseline["policy"]["policy_id"],
            "policy_sha256": baseline["policy"]["sha256"],
        },
        "candidate": {
            "path": candidate_file.as_posix(),
            "sha256": sha256_file(candidate_file),
            "policy_id": candidate["policy"]["policy_id"],
            "policy_sha256": candidate["policy"]["sha256"],
        },
        "summary": {
            "changed_paths": len(changes),
            "added_paths": sum("added" in change["change_kinds"] for change in changes),
            "removed_paths": sum("removed" in change["change_kinds"] for change in changes),
            "protection_losses": len(protection_losses),
            "archive_candidate_expansions": len(archive_expansions),
            "newly_protected": len(newly_protected),
            "protection_gate": "failed" if protection_losses else "passed",
        },
        "protection_losses": protection_losses,
        "archive_candidate_expansions": archive_expansions,
        "newly_protected": newly_protected,
        "changes": changes,
    }


def build_archive_plan_from_retention_report(
    report_path: str | Path,
) -> dict[str, Any]:
    _, report = _load_report(report_path)
    root = Path(cast(str, report["root"])).resolve()
    policy_reference = cast(dict[str, Any], report["policy"])
    policy_path = Path(cast(str, policy_reference["path"])).resolve()
    if not policy_path.is_file() or sha256_file(policy_path) != policy_reference["sha256"]:
        raise ArtifactRetentionError("retention policy changed after the report was created")
    current = build_artifact_retention_report(root, policy_path)
    if current != report:
        raise ArtifactRetentionError("retention report is stale or has been modified")
    entries = report["entries"]
    if not isinstance(entries, list):
        raise ArtifactRetentionError("retention report entries are invalid")
    candidates = tuple(
        entry["path"]
        for entry in entries
        if isinstance(entry, dict)
        and entry.get("category") == "archive_candidate"
        and isinstance(entry.get("path"), str)
    )
    if not candidates:
        raise ArtifactRetentionError("retention report has no archive candidates")
    try:
        return build_artifact_archive_plan(root, include=candidates)
    except ArtifactArchiveError as error:
        raise ArtifactRetentionError(str(error)) from error

"""Hash-verified, non-destructive archives for generated artifacts."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, cast

from courtsim.artifacts import sha256_file, write_json

ARCHIVE_MANIFEST_NAME = "_courtsim_archive_manifest.json"
RESTORE_RECEIPT_NAME = "_courtsim_restore_receipt.json"
RESERVED_NAMES = frozenset({ARCHIVE_MANIFEST_NAME, RESTORE_RECEIPT_NAME})


class ArtifactArchiveError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ArtifactArchiveResult:
    path: Path
    files: int
    source_bytes: int
    archive_bytes: int
    sha256: str


@dataclass(frozen=True, slots=True)
class ArtifactArchiveVerification:
    path: Path
    files: int
    source_bytes: int
    archive_bytes: int
    sha256: str


@dataclass(frozen=True, slots=True)
class ArtifactRestoreResult:
    path: Path
    files: int
    restored_bytes: int
    archive_sha256: str


def _patterns(values: tuple[str, ...], field: str, *, required: bool) -> tuple[str, ...]:
    if required and not values:
        raise ArtifactArchiveError(f"{field} must contain at least one pattern")
    result: list[str] = []
    for value in values:
        normalized = value.replace("\\", "/").strip()
        if (
            not normalized
            or PurePosixPath(normalized).is_absolute()
            or ".." in normalized.split("/")
        ):
            raise ArtifactArchiveError(f"{field} contains an invalid pattern")
        result.append(normalized)
    return tuple(result)


def _matches(path: PurePosixPath, patterns: tuple[str, ...]) -> bool:
    return any(path.match(pattern) for pattern in patterns)


def build_artifact_archive_plan(
    root: str | Path,
    *,
    include: tuple[str, ...],
    exclude: tuple[str, ...] = (),
) -> dict[str, Any]:
    directory = Path(root).resolve()
    if not directory.is_dir():
        raise ArtifactArchiveError(f"artifact root is not a directory: {directory}")
    includes = _patterns(include, "include", required=True)
    excludes = _patterns(exclude, "exclude", required=False)
    entries: list[dict[str, Any]] = []
    for path in directory.rglob("*"):
        relative = PurePosixPath(path.relative_to(directory).as_posix())
        if not _matches(relative, includes) or _matches(relative, excludes):
            continue
        if path.is_symlink():
            raise ArtifactArchiveError(f"archive inputs cannot be symlinks: {relative}")
        if not path.is_file():
            continue
        if relative.as_posix() in RESERVED_NAMES:
            raise ArtifactArchiveError(f"archive input uses reserved name: {relative}")
        entries.append(
            {
                "path": relative.as_posix(),
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    entries.sort(key=lambda item: cast(str, item["path"]))
    return {
        "format_version": 1,
        "kind": "courtsim-artifact-archive-plan",
        "root": directory.as_posix(),
        "include": list(includes),
        "exclude": list(excludes),
        "summary": {
            "files": len(entries),
            "bytes": sum(cast(int, item["bytes"]) for item in entries),
        },
        "entries": entries,
    }


def _validated_entries(
    entries: object,
    summary: object,
    field: str,
) -> list[dict[str, Any]]:
    if not isinstance(entries, list) or not isinstance(summary, dict):
        raise ArtifactArchiveError(f"{field} entries or summary are invalid")
    expected_paths: list[str] = []
    total_bytes = 0
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict) or set(entry) != {"path", "bytes", "sha256"}:
            raise ArtifactArchiveError(f"{field} entry {index} is invalid")
        relative = entry["path"]
        size = entry["bytes"]
        digest = entry["sha256"]
        if (
            not isinstance(relative, str)
            or not relative
            or "\\" in relative
            or ":" in relative
            or PurePosixPath(relative).is_absolute()
            or ".." in PurePosixPath(relative).parts
            or relative in RESERVED_NAMES
            or not isinstance(size, int)
            or isinstance(size, bool)
            or size < 0
            or not isinstance(digest, str)
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
        ):
            raise ArtifactArchiveError(f"{field} entry {index} is invalid")
        expected_paths.append(relative)
        total_bytes += size
    if expected_paths != sorted(set(expected_paths)):
        raise ArtifactArchiveError(f"{field} entry paths must be unique and sorted")
    if summary != {"files": len(entries), "bytes": total_bytes}:
        raise ArtifactArchiveError(f"{field} summary does not match its entries")
    return cast(list[dict[str, Any]], entries)


def _load_plan(path: str | Path) -> tuple[Path, dict[str, Any]]:
    plan_path = Path(path)
    try:
        raw: object = json.loads(plan_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ArtifactArchiveError(f"cannot load archive plan: {plan_path}") from error
    if not isinstance(raw, dict):
        raise ArtifactArchiveError("archive plan must be an object")
    plan = cast(dict[str, Any], raw)
    if set(plan) != {
        "format_version",
        "kind",
        "root",
        "include",
        "exclude",
        "summary",
        "entries",
    }:
        raise ArtifactArchiveError("archive plan fields do not match the v1 contract")
    if plan["format_version"] != 1 or plan["kind"] != "courtsim-artifact-archive-plan":
        raise ArtifactArchiveError("archive plan identity is invalid")
    if (
        not isinstance(plan["include"], list)
        or not all(isinstance(item, str) for item in plan["include"])
        or not isinstance(plan["exclude"], list)
        or not all(isinstance(item, str) for item in plan["exclude"])
    ):
        raise ArtifactArchiveError("archive plan patterns are invalid")
    _patterns(tuple(plan["include"]), "include", required=True)
    _patterns(tuple(plan["exclude"]), "exclude", required=False)
    root = Path(plan["root"]).resolve() if isinstance(plan["root"], str) else Path()
    if not root.is_absolute() or not root.is_dir():
        raise ArtifactArchiveError("archive plan root is unavailable")
    _validated_entries(plan["entries"], plan["summary"], "archive plan")
    return root, plan


def _stream_digest(stream: Any) -> str:
    digest = hashlib.sha256()
    for block in iter(lambda: stream.read(1024 * 1024), b""):
        digest.update(block)
    return digest.hexdigest()


def _zip_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o100644 << 16
    return info


def _valid_digest(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _verify_artifact_archive(
    archive_path: str | Path,
) -> tuple[ArtifactArchiveVerification, dict[str, Any]]:
    path = Path(archive_path)
    if not path.is_file():
        raise ArtifactArchiveError(f"archive is not a file: {path}")
    try:
        with zipfile.ZipFile(path, "r") as archive:
            names = archive.namelist()
            if len(names) != len(set(names)):
                raise ArtifactArchiveError("archive contains duplicate paths")
            if names.count(ARCHIVE_MANIFEST_NAME) != 1:
                raise ArtifactArchiveError("archive manifest is missing")
            manifest_info = archive.getinfo(ARCHIVE_MANIFEST_NAME)
            if manifest_info.file_size > 10 * 1024 * 1024 or manifest_info.flag_bits & 1:
                raise ArtifactArchiveError("archive manifest is unsafe")
            raw: object = json.loads(archive.read(ARCHIVE_MANIFEST_NAME))
            if not isinstance(raw, dict):
                raise ArtifactArchiveError("archive manifest must be an object")
            manifest = cast(dict[str, Any], raw)
            if set(manifest) != {
                "format_version",
                "kind",
                "source_plan_sha256",
                "source_root",
                "summary",
                "entries",
            }:
                raise ArtifactArchiveError("archive manifest fields do not match v1")
            if (
                manifest["format_version"] != 1
                or manifest["kind"] != "courtsim-artifact-archive"
                or not _valid_digest(manifest["source_plan_sha256"])
                or not isinstance(manifest["source_root"], str)
                or not manifest["source_root"]
            ):
                raise ArtifactArchiveError("archive manifest identity is invalid")
            entries = _validated_entries(
                manifest["entries"],
                manifest["summary"],
                "archive manifest",
            )
            if not entries:
                raise ArtifactArchiveError("archive contains no source files")
            expected_names = [ARCHIVE_MANIFEST_NAME, *[cast(str, item["path"]) for item in entries]]
            if sorted(names) != sorted(expected_names):
                raise ArtifactArchiveError("archive entries do not match its manifest")
            for entry in entries:
                info = archive.getinfo(cast(str, entry["path"]))
                file_type = (info.external_attr >> 16) & 0o170000
                if (
                    info.is_dir()
                    or info.flag_bits & 1
                    or file_type == 0o120000
                    or info.file_size != entry["bytes"]
                ):
                    raise ArtifactArchiveError(f"archive entry is unsafe: {entry['path']}")
            if archive.testzip() is not None:
                raise ArtifactArchiveError("archive CRC verification failed")
            for entry in entries:
                with archive.open(cast(str, entry["path"]), "r") as stream:
                    if _stream_digest(stream) != entry["sha256"]:
                        raise ArtifactArchiveError(
                            f"archived content hash mismatch: {entry['path']}"
                        )
    except (OSError, json.JSONDecodeError, zipfile.BadZipFile) as error:
        raise ArtifactArchiveError(f"cannot verify archive: {path}") from error
    return (
        ArtifactArchiveVerification(
            path,
            len(entries),
            cast(int, manifest["summary"]["bytes"]),
            path.stat().st_size,
            sha256_file(path),
        ),
        manifest,
    )


def verify_artifact_archive(
    archive_path: str | Path,
) -> ArtifactArchiveVerification:
    verification, _ = _verify_artifact_archive(archive_path)
    return verification


def create_artifact_archive(
    plan_path: str | Path,
    output_path: str | Path,
) -> ArtifactArchiveResult:
    root, plan = _load_plan(plan_path)
    destination = Path(output_path)
    if destination.exists():
        raise ArtifactArchiveError(f"archive output already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    entries = cast(list[dict[str, Any]], plan["entries"])
    if not entries:
        raise ArtifactArchiveError("archive plan contains no files")
    for entry in entries:
        candidate = root / cast(str, entry["path"])
        source = candidate.resolve()
        if candidate.is_symlink() or not source.is_relative_to(root) or not source.is_file():
            raise ArtifactArchiveError(f"archive source is unavailable: {entry['path']}")
        if source.stat().st_size != entry["bytes"] or sha256_file(source) != entry["sha256"]:
            raise ArtifactArchiveError(f"archive source changed after planning: {entry['path']}")

    handle, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.",
        suffix=".tmp",
        dir=destination.parent,
    )
    os.close(handle)
    temporary = Path(temporary_name)
    try:
        manifest = {
            "format_version": 1,
            "kind": "courtsim-artifact-archive",
            "source_plan_sha256": sha256_file(plan_path),
            "source_root": root.as_posix(),
            "summary": plan["summary"],
            "entries": entries,
        }
        with zipfile.ZipFile(
            temporary,
            "w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=6,
        ) as archive:
            archive.writestr(
                _zip_info(ARCHIVE_MANIFEST_NAME),
                json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
            )
            for entry in entries:
                source = root / cast(str, entry["path"])
                with (
                    source.open("rb") as source_stream,
                    archive.open(
                        _zip_info(cast(str, entry["path"])),
                        "w",
                    ) as archive_stream,
                ):
                    shutil.copyfileobj(source_stream, archive_stream, length=1024 * 1024)
        verification, _ = _verify_artifact_archive(temporary)
        os.replace(temporary, destination)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return ArtifactArchiveResult(
        destination,
        len(entries),
        cast(int, plan["summary"]["bytes"]),
        verification.archive_bytes,
        verification.sha256,
    )


def restore_artifact_archive(
    archive_path: str | Path,
    destination_path: str | Path,
) -> ArtifactRestoreResult:
    verification, manifest = _verify_artifact_archive(archive_path)
    destination = Path(destination_path).resolve()
    if destination.exists():
        raise ArtifactArchiveError(f"restore destination already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(
        tempfile.mkdtemp(
            prefix=f".{destination.name}.restore-",
            dir=destination.parent,
        )
    )
    entries = cast(list[dict[str, Any]], manifest["entries"])
    try:
        with zipfile.ZipFile(verification.path, "r") as archive:
            for entry in entries:
                relative = PurePosixPath(cast(str, entry["path"]))
                target = temporary.joinpath(*relative.parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(relative.as_posix(), "r") as source, target.open("xb") as output:
                    shutil.copyfileobj(source, output, length=1024 * 1024)
                if (
                    target.stat().st_size != entry["bytes"]
                    or sha256_file(target) != entry["sha256"]
                ):
                    raise ArtifactArchiveError(f"restored content hash mismatch: {relative}")
        write_json(
            temporary / RESTORE_RECEIPT_NAME,
            {
                "format_version": 1,
                "kind": "courtsim-artifact-restore-receipt",
                "archive_sha256": verification.sha256,
                "summary": {
                    "files": verification.files,
                    "bytes": verification.source_bytes,
                },
            },
        )
        if destination.exists():
            raise ArtifactArchiveError(f"restore destination already exists: {destination}")
        os.replace(temporary, destination)
    except BaseException:
        if temporary.exists():
            shutil.rmtree(temporary)
        raise
    return ArtifactRestoreResult(
        destination,
        verification.files,
        verification.source_bytes,
        verification.sha256,
    )

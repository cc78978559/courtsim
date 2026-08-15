"""Offline-first acquisition and streaming reduction of public NBA datasets."""

from __future__ import annotations

import csv
import gzip
import hashlib
import importlib
import json
import lzma
import math
import os
import shutil
import tarfile
import tempfile
import urllib.request
import zipfile
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import IO, Any, TextIO, cast
from urllib.parse import urlparse

from courtsim.artifacts import sha256_file, write_json

NBA_DATA_MANIFEST_VERSION = 1
NBA_DATA_SUMMARY_VERSION = 1
_OPERATIONS = {"clock_delta_sum", "count", "distinct_count", "sum", "ratio"}
_CONDITION_OPERATORS = {
    "equals",
    "in",
    "not_equals",
    "contains",
    "contains_ci",
    "not_contains",
    "not_contains_ci",
    "truthy",
}


class NbaDataPipelineError(ValueError):
    """Raised when a local NBA dataset cannot be trusted or reduced."""


def sync_nba_data(
    manifest_path: str | Path,
    cache_directory: str | Path,
    *,
    offline: bool = False,
    force: bool = False,
) -> dict[str, object]:
    """Copy or download declared resources into a content-verified local cache."""
    manifest_file = Path(manifest_path).resolve()
    manifest = _load_manifest(manifest_file)
    dataset_directory = Path(cache_directory).resolve() / _dataset_id(manifest)
    dataset_directory.mkdir(parents=True, exist_ok=True)
    resources_report: list[dict[str, object]] = []
    for resource in _resources(manifest):
        destination = dataset_directory / _resource_filename(resource)
        expected_hash = _optional_sha256(resource.get("sha256"))
        if destination.is_file() and not force:
            digest = sha256_file(destination)
            if expected_hash is None or digest == expected_hash:
                resources_report.append(_resource_report(resource, destination, digest, "cached"))
                continue
        if offline:
            raise NbaDataPipelineError(
                f"resource is not available in verified cache: {_resource_id(resource)}"
            )
        _acquire_resource(resource, manifest_file.parent, destination)
        digest = sha256_file(destination)
        if expected_hash is not None and digest != expected_hash:
            destination.unlink(missing_ok=True)
            raise NbaDataPipelineError(f"sha256 mismatch for resource {_resource_id(resource)}")
        resources_report.append(_resource_report(resource, destination, digest, "synced"))
    receipt: dict[str, object] = {
        "schema_version": NBA_DATA_MANIFEST_VERSION,
        "dataset_id": _dataset_id(manifest),
        "manifest_sha256": sha256_file(manifest_file),
        "synced_at": datetime.now(UTC).isoformat(),
        "resources": resources_report,
    }
    write_json(dataset_directory / "sync-receipt.json", receipt)
    return receipt


def build_nba_data_summary(
    manifest_path: str | Path,
    cache_directory: str | Path,
    output_path: str | Path,
    *,
    force: bool = False,
) -> dict[str, object]:
    """Stream a cached CSV resource into a compact, provenance-pinned JSON summary."""
    manifest_file = Path(manifest_path).resolve()
    manifest = _load_manifest(manifest_file)
    build = _mapping(manifest.get("build"), "build")
    resource_id = _text(build.get("resource_id"), "build.resource_id")
    resource = _resource_by_id(manifest, resource_id)
    source = Path(cache_directory).resolve() / _dataset_id(manifest) / _resource_filename(resource)
    if not source.is_file():
        raise NbaDataPipelineError(f"cached resource is missing: {resource_id}")
    source_sha256 = sha256_file(source)
    expected_hash = _optional_sha256(resource.get("sha256"))
    if expected_hash is not None and source_sha256 != expected_hash:
        raise NbaDataPipelineError(f"cached resource sha256 mismatch: {resource_id}")
    manifest_sha256 = sha256_file(manifest_file)
    output = Path(output_path).resolve()
    if not force and _is_current_summary(output, manifest_sha256, source_sha256):
        cached = _load_json_object(output, "NBA data summary")
        return {**cached, "cached": True}

    metric_specs = _metric_specs(build)
    delimiter = _delimiter(build.get("delimiter", ","))
    encoding = _text(build.get("encoding", "utf-8-sig"), "build.encoding")
    archive_member = _optional_text(build.get("archive_member"), "build.archive_member")
    deduplicate_by = _deduplicate_by(build.get("deduplicate_by"))
    group_by = _group_by(build.get("group_by"))
    row_filter = build.get("where")
    row_count = 0
    source_row_count = 0
    filtered_row_count = 0
    duplicate_count = 0
    seen_keys: set[bytes] = set()
    values = _initial_metric_values(metric_specs)
    grouped_values: dict[tuple[str, ...], dict[str, float | int | set[str]]] = {}
    required_columns = _required_columns(metric_specs, deduplicate_by, group_by, row_filter)

    with _open_rows(
        source,
        encoding=encoding,
        archive_member=archive_member,
        delimiter=delimiter,
        projected_columns=required_columns,
    ) as (columns, rows):
        _validate_columns(metric_specs, set(columns), deduplicate_by, group_by, row_filter)
        for row in rows:
            source_row_count += 1
            if not _matches(row, row_filter):
                filtered_row_count += 1
                continue
            if deduplicate_by:
                key = _row_key(row, deduplicate_by)
                if key in seen_keys:
                    duplicate_count += 1
                    continue
                seen_keys.add(key)
            row_count += 1
            _accumulate_metric_values(values, metric_specs, row)
            if group_by:
                group = tuple((row.get(column) or "").strip() for column in group_by)
                if any(not value for value in group):
                    raise NbaDataPipelineError(
                        f"group_by columns {list(group_by)} contain a blank value"
                    )
                group_values = grouped_values.setdefault(
                    group, _initial_metric_values(metric_specs)
                )
                _accumulate_metric_values(group_values, metric_specs, row)

    metrics = _finalize_metric_values(values, metric_specs)

    payload: dict[str, object] = {
        "schema_version": NBA_DATA_SUMMARY_VERSION,
        "dataset_id": _dataset_id(manifest),
        "season": _text(manifest.get("season"), "season"),
        "provider": _text(manifest.get("provider"), "provider"),
        "source": {
            "resource_id": resource_id,
            "filename": source.name,
            "bytes": source.stat().st_size,
            "sha256": source_sha256,
        },
        "provenance": {
            "manifest_sha256": manifest_sha256,
            "terms_note": _text(manifest.get("terms_note"), "terms_note"),
        },
        "rows_processed": row_count,
        "source_rows": source_row_count,
        "filtered_rows": filtered_row_count,
        "duplicates_skipped": duplicate_count,
        "metrics": metrics,
        "cached": False,
    }
    if len(group_by) == 1:
        payload["group_by"] = group_by[0]
        payload["groups"] = {
            group[0]: _finalize_metric_values(grouped_values[group], metric_specs)
            for group in sorted(grouped_values)
        }
    elif group_by:
        payload["group_by"] = list(group_by)
        payload["groups"] = [
            {
                "key": dict(zip(group_by, group, strict=True)),
                "metrics": _finalize_metric_values(grouped_values[group], metric_specs),
            }
            for group in sorted(grouped_values)
        ]
    payload["local_reduction"] = {
        "raw_bytes": source.stat().st_size,
        "summary_bytes": 0,
        "context_reduction_ratio": 0.0,
    }
    _write_summary_with_stable_size(output, payload, source.stat().st_size)
    return payload


def inspect_nba_data(
    manifest_path: str | Path,
    cache_directory: str | Path,
    output_path: str | Path | None = None,
) -> dict[str, object]:
    """Return a compact cache/build status without opening raw dataset rows."""
    manifest_file = Path(manifest_path).resolve()
    manifest = _load_manifest(manifest_file)
    manifest_sha256 = sha256_file(manifest_file)
    dataset_directory = Path(cache_directory).resolve() / _dataset_id(manifest)
    resource_reports: list[dict[str, object]] = []
    ready = True
    for resource in _resources(manifest):
        path = dataset_directory / _resource_filename(resource)
        present = path.is_file()
        digest = sha256_file(path) if present else None
        expected = _optional_sha256(resource.get("sha256"))
        verified = present and (expected is None or digest == expected)
        ready = ready and verified
        resource_reports.append(
            {
                "resource_id": _resource_id(resource),
                "present": present,
                "verified": verified,
                "bytes": path.stat().st_size if present else 0,
                "sha256": digest,
            }
        )
    summary_current = False
    if output_path is not None and len(resource_reports) > 0:
        build = _mapping(manifest.get("build"), "build")
        source_report = next(
            (item for item in resource_reports if item["resource_id"] == build.get("resource_id")),
            None,
        )
        if source_report is not None and isinstance(source_report["sha256"], str):
            summary_current = _is_current_summary(
                Path(output_path),
                manifest_sha256,
                source_report["sha256"],
            )
    return {
        "schema_version": NBA_DATA_MANIFEST_VERSION,
        "dataset_id": _dataset_id(manifest),
        "season": _text(manifest.get("season"), "season"),
        "ready": ready,
        "summary_current": summary_current,
        "resources": resource_reports,
    }


def _load_manifest(path: Path) -> dict[str, Any]:
    manifest = _load_json_object(path, "NBA data manifest")
    if manifest.get("schema_version") != NBA_DATA_MANIFEST_VERSION:
        raise NbaDataPipelineError("NBA data manifest schema_version must be 1")
    expected = {
        "schema_version",
        "dataset_id",
        "season",
        "provider",
        "terms_note",
        "resources",
        "build",
    }
    if set(manifest) != expected:
        raise NbaDataPipelineError("NBA data manifest fields do not match schema version 1")
    _dataset_id(manifest)
    _text(manifest.get("season"), "season")
    _text(manifest.get("provider"), "provider")
    _text(manifest.get("terms_note"), "terms_note")
    resources = _resources(manifest)
    resource_ids = [_resource_id(resource) for resource in resources]
    if len(resource_ids) != len(set(resource_ids)):
        raise NbaDataPipelineError("resource ids must be unique")
    build = _mapping(manifest.get("build"), "build")
    if set(build) - {
        "resource_id",
        "delimiter",
        "encoding",
        "archive_member",
        "deduplicate_by",
        "group_by",
        "where",
        "metrics",
    }:
        raise NbaDataPipelineError("build contains unsupported fields")
    _resource_by_id(manifest, _text(build.get("resource_id"), "build.resource_id"))
    _delimiter(build.get("delimiter", ","))
    _text(build.get("encoding", "utf-8-sig"), "build.encoding")
    _optional_text(build.get("archive_member"), "build.archive_member")
    _deduplicate_by(build.get("deduplicate_by"))
    _group_by(build.get("group_by"))
    _validate_where(build.get("where"), "build")
    _metric_specs(build)
    return manifest


def _metric_specs(build: Mapping[str, Any]) -> list[dict[str, Any]]:
    raw_metrics = build.get("metrics")
    if not isinstance(raw_metrics, list) or not raw_metrics:
        raise NbaDataPipelineError("build.metrics must be a non-empty list")
    metrics: list[dict[str, Any]] = []
    names: set[str] = set()
    for index, raw in enumerate(raw_metrics):
        spec = dict(_mapping(raw, f"build.metrics[{index}]"))
        name = _text(spec.get("name"), f"build.metrics[{index}].name")
        operation = _text(spec.get("operation"), f"build.metrics[{index}].operation")
        if name in names:
            raise NbaDataPipelineError(f"duplicate metric name: {name}")
        if operation not in _OPERATIONS:
            raise NbaDataPipelineError(f"unsupported metric operation: {operation}")
        allowed = (
            {"name", "operation", "numerator", "denominator"}
            if operation == "ratio"
            else {"name", "operation", "start_column", "end_column", "where"}
            if operation == "clock_delta_sum"
            else {"name", "operation", "where"}
            if operation == "count"
            else {"name", "operation", "column", "where"}
        )
        if set(spec) - allowed:
            raise NbaDataPipelineError(f"metric {name} contains unsupported fields")
        if operation in {"sum", "distinct_count"}:
            _text(spec.get("column"), f"metric {name}.column")
        if operation == "clock_delta_sum":
            _text(spec.get("start_column"), f"metric {name}.start_column")
            _text(spec.get("end_column"), f"metric {name}.end_column")
        if operation == "ratio":
            _text(spec.get("numerator"), f"metric {name}.numerator")
            _text(spec.get("denominator"), f"metric {name}.denominator")
        _validate_where(spec.get("where"), name)
        spec["name"] = name
        spec["operation"] = operation
        metrics.append(spec)
        names.add(name)
    for spec in metrics:
        if spec["operation"] != "ratio":
            continue
        numerator = cast(str, spec["numerator"])
        denominator = cast(str, spec["denominator"])
        if numerator not in names or denominator not in names:
            raise NbaDataPipelineError(f"ratio metric {spec['name']} references an unknown metric")
    return metrics


def _validate_where(raw: object, metric: str) -> None:
    if raw is None:
        return
    where = _mapping(raw, f"metric {metric}.where")
    for column, raw_condition in where.items():
        _text(column, f"metric {metric}.where column")
        condition = _mapping(raw_condition, f"metric {metric}.where.{column}")
        if len(condition) != 1:
            raise NbaDataPipelineError(f"metric {metric} conditions require one operator")
        operator, expected = next(iter(condition.items()))
        if operator not in _CONDITION_OPERATORS:
            raise NbaDataPipelineError(f"unsupported condition operator: {operator}")
        if operator == "truthy":
            if not isinstance(expected, bool):
                raise NbaDataPipelineError("truthy condition must be boolean")
        elif operator == "in":
            if not isinstance(expected, list) or not all(
                isinstance(item, str) for item in expected
            ):
                raise NbaDataPipelineError("in condition must contain a string list")
        elif not isinstance(expected, str):
            raise NbaDataPipelineError(f"{operator} condition must contain a string")


def _required_columns(
    metrics: list[dict[str, Any]],
    deduplicate_by: tuple[str, ...],
    group_by: tuple[str, ...],
    row_filter: object,
) -> set[str]:
    required: set[str] = set(deduplicate_by)
    required.update(group_by)
    if isinstance(row_filter, dict):
        required.update(row_filter)
    for spec in metrics:
        column = spec.get("column")
        if isinstance(column, str):
            required.add(column)
        for clock_column in (spec.get("start_column"), spec.get("end_column")):
            if isinstance(clock_column, str):
                required.add(clock_column)
        where = spec.get("where")
        if isinstance(where, dict):
            required.update(where)
    return required


def _validate_columns(
    metrics: list[dict[str, Any]],
    columns: set[str],
    deduplicate_by: tuple[str, ...],
    group_by: tuple[str, ...],
    row_filter: object,
) -> None:
    required = _required_columns(metrics, deduplicate_by, group_by, row_filter)
    missing = sorted(required - columns)
    if missing:
        raise NbaDataPipelineError(f"data resource is missing columns: {missing}")


def _initial_metric_values(
    metric_specs: list[dict[str, Any]],
) -> dict[str, float | int | set[str]]:
    values: dict[str, float | int | set[str]] = {}
    for spec in metric_specs:
        name = cast(str, spec["name"])
        operation = cast(str, spec["operation"])
        if operation == "distinct_count":
            values[name] = set()
        elif operation != "ratio":
            values[name] = 0.0 if operation in {"sum", "clock_delta_sum"} else 0
    return values


def _accumulate_metric_values(
    values: dict[str, float | int | set[str]],
    metric_specs: list[dict[str, Any]],
    row: Mapping[str, str | None],
) -> None:
    for spec in metric_specs:
        name = cast(str, spec["name"])
        operation = cast(str, spec["operation"])
        if operation == "ratio" or not _matches(row, spec.get("where")):
            continue
        if operation == "count":
            values[name] = cast(int, values[name]) + 1
        elif operation == "distinct_count":
            column = cast(str, spec["column"])
            value = (row.get(column) or "").strip()
            if value:
                cast(set[str], values[name]).add(value)
        elif operation == "sum":
            column = cast(str, spec["column"])
            raw_value = (row.get(column) or "").strip().replace(",", "")
            if raw_value:
                try:
                    values[name] = cast(float, values[name]) + float(raw_value)
                except ValueError as error:
                    raise NbaDataPipelineError(
                        f"metric {name} encountered non-numeric value in {column}"
                    ) from error
        else:
            start_column = cast(str, spec["start_column"])
            end_column = cast(str, spec["end_column"])
            delta = _clock_seconds(row.get(start_column), start_column) - _clock_seconds(
                row.get(end_column), end_column
            )
            if delta < 0:
                raise NbaDataPipelineError(f"metric {name} encountered a negative clock delta")
            values[name] = cast(float, values[name]) + delta


def _finalize_metric_values(
    values: dict[str, float | int | set[str]],
    metric_specs: list[dict[str, Any]],
) -> dict[str, float | int]:
    metrics: dict[str, float | int] = {}
    for spec in metric_specs:
        name = cast(str, spec["name"])
        operation = cast(str, spec["operation"])
        if operation == "distinct_count":
            metrics[name] = len(cast(set[str], values[name]))
        elif operation != "ratio":
            value = cast(float | int, values[name])
            metrics[name] = int(value) if operation == "count" else round(float(value), 12)
    for spec in metric_specs:
        if spec["operation"] != "ratio":
            continue
        name = cast(str, spec["name"])
        numerator = metrics[cast(str, spec["numerator"])]
        denominator = metrics[cast(str, spec["denominator"])]
        if denominator == 0:
            raise NbaDataPipelineError(f"metric {name} has a zero denominator")
        metrics[name] = round(float(numerator) / float(denominator), 12)
    return metrics


def _deduplicate_by(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or not value or not all(isinstance(item, str) for item in value):
        raise NbaDataPipelineError("build.deduplicate_by must be a non-empty string list")
    columns = tuple(_text(item, "build.deduplicate_by[]") for item in value)
    if len(columns) != len(set(columns)):
        raise NbaDataPipelineError("build.deduplicate_by columns must be unique")
    return columns


def _group_by(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (_text(value, "build.group_by"),)
    if not isinstance(value, list) or not value or not all(isinstance(item, str) for item in value):
        raise NbaDataPipelineError("build.group_by must be a string or non-empty string list")
    columns = tuple(_text(item, "build.group_by[]") for item in value)
    if len(columns) != len(set(columns)):
        raise NbaDataPipelineError("build.group_by columns must be unique")
    return columns


def _row_key(row: Mapping[str, str | None], columns: tuple[str, ...]) -> bytes:
    digest = hashlib.sha256()
    for column in columns:
        value = (row.get(column) or "").encode("utf-8")
        digest.update(len(value).to_bytes(8, "big"))
        digest.update(value)
    return digest.digest()


def _clock_seconds(value: object, column: str) -> float:
    if not isinstance(value, str):
        raise NbaDataPipelineError(f"clock column {column} must be text")
    parts = value.strip().split(":")
    if len(parts) != 2:
        raise NbaDataPipelineError(f"clock column {column} must use MM:SS")
    try:
        minutes = int(parts[0])
        seconds = float(parts[1])
    except ValueError as error:
        raise NbaDataPipelineError(f"clock column {column} must use MM:SS") from error
    if minutes < 0 or not math.isfinite(seconds) or not 0.0 <= seconds < 60.0:
        raise NbaDataPipelineError(f"clock column {column} is out of range")
    return minutes * 60.0 + seconds


def _matches(row: Mapping[str, str | None], raw_where: object) -> bool:
    if raw_where is None:
        return True
    where = cast(Mapping[str, Mapping[str, object]], raw_where)
    for column, condition in where.items():
        value = (row.get(column) or "").strip()
        operator, expected = next(iter(condition.items()))
        if operator == "equals" and value != expected:
            return False
        if operator == "not_equals" and value == expected:
            return False
        if operator == "in" and value not in cast(list[str], expected):
            return False
        if operator == "contains" and cast(str, expected) not in value:
            return False
        if operator == "contains_ci" and cast(str, expected).casefold() not in value.casefold():
            return False
        if operator == "not_contains" and cast(str, expected) in value:
            return False
        if operator == "not_contains_ci" and cast(str, expected).casefold() in value.casefold():
            return False
        if operator == "truthy":
            truthy = value.lower() in {"1", "true", "yes", "y"}
            if truthy is not expected:
                return False
    return True


@contextmanager
def _open_rows(
    path: Path,
    *,
    encoding: str,
    archive_member: str | None,
    delimiter: str,
    projected_columns: set[str],
) -> Iterator[tuple[tuple[str, ...], Iterator[Mapping[str, str | None]]]]:
    if path.suffix.lower() == ".parquet":
        if archive_member is not None:
            raise NbaDataPipelineError("Parquet resources cannot use archive_member")
        try:
            parquet = importlib.import_module("pyarrow.parquet")
        except ImportError as error:
            raise NbaDataPipelineError(
                "Parquet data requires optional tools: run '.\\tools.cmd bootstrap-data'"
            ) from error
        parquet_file = parquet.ParquetFile(path)
        columns = tuple(parquet_file.schema_arrow.names)

        def rows() -> Iterator[Mapping[str, str | None]]:
            selected = tuple(column for column in columns if column in projected_columns)
            for batch in parquet_file.iter_batches(batch_size=65_536, columns=list(selected)):
                values = batch.to_pydict()
                for row_index in range(batch.num_rows):
                    yield {column: _parquet_text(values[column][row_index]) for column in selected}

        yield columns, rows()
        return
    with _open_csv_text(path, encoding=encoding, archive_member=archive_member) as stream:
        reader = csv.DictReader(stream, delimiter=delimiter)
        if reader.fieldnames is None:
            raise NbaDataPipelineError("CSV resource has no header")
        yield tuple(reader.fieldnames), reader


def _parquet_text(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


@contextmanager
def _open_csv_text(
    path: Path,
    *,
    encoding: str,
    archive_member: str | None,
) -> Iterator[TextIO]:
    suffixes = tuple(suffix.lower() for suffix in path.suffixes)
    if suffixes[-2:] in {(".tar", ".xz"), (".tar", ".gz")}:
        with tarfile.open(path, mode="r:*") as archive:
            members = [
                member
                for member in archive.getmembers()
                if member.isfile()
                and (archive_member is None or member.name == archive_member)
                and (archive_member is not None or member.name.lower().endswith(".csv"))
            ]
            if len(members) != 1:
                raise NbaDataPipelineError("archive must resolve to exactly one CSV member")
            extracted = archive.extractfile(members[0])
            if extracted is None:
                raise NbaDataPipelineError("cannot open CSV archive member")
            with extracted as archive_binary, _text_wrapper(archive_binary, encoding) as text:
                yield text
        return
    if path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as archive:
            names = [
                name
                for name in archive.namelist()
                if (archive_member is None or name == archive_member)
                and (archive_member is not None or name.lower().endswith(".csv"))
            ]
            if len(names) != 1:
                raise NbaDataPipelineError("archive must resolve to exactly one CSV member")
            with archive.open(names[0]) as zip_binary, _text_wrapper(zip_binary, encoding) as text:
                yield text
        return
    opener = (
        gzip.open
        if path.suffix.lower() == ".gz"
        else lzma.open
        if path.suffix.lower() == ".xz"
        else open
    )
    with (
        opener(path, "rb") as plain_binary,
        _text_wrapper(cast(IO[bytes], plain_binary), encoding) as text,
    ):
        yield text


@contextmanager
def _text_wrapper(binary: IO[bytes], encoding: str) -> Iterator[TextIO]:
    import io

    wrapper = io.TextIOWrapper(binary, encoding=encoding, newline="")
    try:
        yield wrapper
    finally:
        wrapper.detach()


def _acquire_resource(
    resource: Mapping[str, Any],
    manifest_directory: Path,
    destination: Path,
) -> None:
    source_path = resource.get("path")
    source_url = resource.get("url")
    if (source_path is None) == (source_url is None):
        raise NbaDataPipelineError(
            f"resource {_resource_id(resource)} must declare exactly one of path or url"
        )
    destination.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".download", dir=destination.parent
    )
    os.close(handle)
    temporary = Path(temporary_name)
    try:
        if source_path is not None:
            source = (manifest_directory / _text(source_path, "resource.path")).resolve()
            if not source.is_file():
                raise NbaDataPipelineError(f"local source is missing: {source}")
            with source.open("rb") as input_stream, temporary.open("wb") as output_stream:
                shutil.copyfileobj(input_stream, output_stream, length=1024 * 1024)
        else:
            url = _text(source_url, "resource.url")
            if urlparse(url).scheme != "https":
                raise NbaDataPipelineError("resource URLs must use HTTPS")
            request = urllib.request.Request(url, headers={"User-Agent": "CourtSim/0.54"})
            with (
                urllib.request.urlopen(request, timeout=60) as response,
                temporary.open("wb") as output_stream,
            ):
                shutil.copyfileobj(response, output_stream, length=1024 * 1024)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def _resource_report(
    resource: Mapping[str, Any],
    path: Path,
    digest: str,
    status: str,
) -> dict[str, object]:
    return {
        "resource_id": _resource_id(resource),
        "filename": path.name,
        "bytes": path.stat().st_size,
        "sha256": digest,
        "status": status,
    }


def _write_summary_with_stable_size(
    path: Path,
    payload: dict[str, object],
    raw_bytes: int,
) -> None:
    reduction = cast(dict[str, object], payload["local_reduction"])
    for _ in range(4):
        write_json(path, payload)
        summary_bytes = path.stat().st_size
        if reduction["summary_bytes"] == summary_bytes:
            return
        reduction["summary_bytes"] = summary_bytes
        reduction["context_reduction_ratio"] = round(
            max(0.0, 1.0 - summary_bytes / max(1, raw_bytes)),
            6,
        )
    write_json(path, payload)


def _is_current_summary(path: Path, manifest_hash: str, source_hash: str) -> bool:
    if not path.is_file():
        return False
    try:
        summary = _load_json_object(path, "NBA data summary")
        provenance = _mapping(summary.get("provenance"), "summary.provenance")
        source = _mapping(summary.get("source"), "summary.source")
    except NbaDataPipelineError:
        return False
    return (
        summary.get("schema_version") == NBA_DATA_SUMMARY_VERSION
        and provenance.get("manifest_sha256") == manifest_hash
        and source.get("sha256") == source_hash
    )


def _resources(manifest: Mapping[str, Any]) -> list[dict[str, Any]]:
    raw = manifest.get("resources")
    if not isinstance(raw, list) or not raw:
        raise NbaDataPipelineError("resources must be a non-empty list")
    resources: list[dict[str, Any]] = []
    for index, item in enumerate(raw):
        resource = dict(_mapping(item, f"resources[{index}]"))
        allowed = {"resource_id", "filename", "sha256", "path", "url"}
        if set(resource) - allowed:
            raise NbaDataPipelineError(f"resource {index} contains unsupported fields")
        _resource_id(resource)
        _resource_filename(resource)
        _optional_sha256(resource.get("sha256"))
        if ("path" in resource) == ("url" in resource):
            raise NbaDataPipelineError("each resource requires exactly one of path or url")
        resources.append(resource)
    return resources


def _resource_by_id(manifest: Mapping[str, Any], resource_id: str) -> dict[str, Any]:
    for resource in _resources(manifest):
        if _resource_id(resource) == resource_id:
            return resource
    raise NbaDataPipelineError(f"build references unknown resource: {resource_id}")


def _dataset_id(manifest: Mapping[str, Any]) -> str:
    dataset_id = _text(manifest.get("dataset_id"), "dataset_id")
    if any(character not in "abcdefghijklmnopqrstuvwxyz0123456789-_" for character in dataset_id):
        raise NbaDataPipelineError("dataset_id must use lowercase ASCII, digits, '-' or '_'")
    return dataset_id


def _resource_id(resource: Mapping[str, Any]) -> str:
    return _text(resource.get("resource_id"), "resource_id")


def _resource_filename(resource: Mapping[str, Any]) -> str:
    filename = _text(resource.get("filename"), "resource.filename")
    if Path(filename).name != filename:
        raise NbaDataPipelineError("resource filename must not contain directories")
    return filename


def _load_json_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise NbaDataPipelineError(f"cannot load {label}: {path}") from error
    if not isinstance(value, dict):
        raise NbaDataPipelineError(f"{label} root must be an object")
    return cast(dict[str, Any], value)


def _mapping(value: object, field: str) -> Mapping[str, Any]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise NbaDataPipelineError(f"{field} must be an object")
    return cast(Mapping[str, Any], value)


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise NbaDataPipelineError(f"{field} must be a non-empty string")
    return value.strip()


def _optional_text(value: object, field: str) -> str | None:
    return None if value is None else _text(value, field)


def _optional_sha256(value: object) -> str | None:
    if value is None:
        return None
    digest = _text(value, "resource.sha256").lower()
    if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
        raise NbaDataPipelineError("resource.sha256 must be a lowercase SHA-256 digest")
    return digest


def _delimiter(value: object) -> str:
    delimiter = _text(value, "build.delimiter")
    if len(delimiter) != 1:
        raise NbaDataPipelineError("build.delimiter must be one character")
    return delimiter

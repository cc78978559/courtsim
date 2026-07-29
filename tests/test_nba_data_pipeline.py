import gzip
import hashlib
import io
import json
import lzma
import tarfile
import zipfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from courtsim.analysis.nba_data_pipeline import (
    NbaDataPipelineError,
    build_nba_data_summary,
    inspect_nba_data,
    sync_nba_data,
)
from courtsim.artifacts import write_json
from courtsim.cli import main


def _fixture(tmp_path: Path, *, compressed: bool = False) -> tuple[Path, Path]:
    raw = (
        b"game_id,event_type,points,team_id\n"
        b"g1,shot,2,A\n"
        b"g1,turnover,0,B\n"
        b"g2,shot,3,A\n"
        b"g2,shot,0,B\n"
    )
    source = tmp_path / ("events.csv.gz" if compressed else "events.csv")
    source.write_bytes(gzip.compress(raw) if compressed else raw)
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    manifest = tmp_path / "manifest.json"
    write_json(
        manifest,
        {
            "schema_version": 1,
            "dataset_id": "nba-test-season",
            "season": "2024-25",
            "provider": "local-test",
            "terms_note": "Personal research fixture.",
            "resources": [
                {
                    "resource_id": "events",
                    "filename": source.name,
                    "path": source.name,
                    "sha256": digest,
                }
            ],
            "build": {
                "resource_id": "events",
                "metrics": [
                    {
                        "name": "games",
                        "operation": "distinct_count",
                        "column": "game_id",
                    },
                    {"name": "events", "operation": "count"},
                    {
                        "name": "shots",
                        "operation": "count",
                        "where": {"event_type": {"equals": "shot"}},
                    },
                    {
                        "name": "points",
                        "operation": "sum",
                        "column": "points",
                    },
                    {
                        "name": "points_per_shot",
                        "operation": "ratio",
                        "numerator": "points",
                        "denominator": "shots",
                    },
                ],
            },
        },
    )
    return manifest, source


@pytest.mark.parametrize("compressed", [False, True])
def test_sync_build_and_status_are_local_incremental_and_compact(
    tmp_path: Path,
    compressed: bool,
) -> None:
    manifest, source = _fixture(tmp_path, compressed=compressed)
    cache = tmp_path / "cache"
    output = tmp_path / "summary.json"

    receipt = sync_nba_data(manifest, cache)
    assert receipt["resources"][0]["status"] == "synced"  # type: ignore[index]
    source.unlink()

    offline_receipt = sync_nba_data(manifest, cache, offline=True)
    assert offline_receipt["resources"][0]["status"] == "cached"  # type: ignore[index]
    summary = build_nba_data_summary(manifest, cache, output)
    assert summary["rows_processed"] == 4
    assert summary["metrics"] == {
        "events": 4,
        "games": 2,
        "points": 5.0,
        "points_per_shot": 1.666666666667,
        "shots": 3,
    }
    assert summary["source"]["sha256"] == receipt["resources"][0]["sha256"]  # type: ignore[index]
    assert summary["local_reduction"]["raw_bytes"] > 0  # type: ignore[index]
    assert summary["local_reduction"]["summary_bytes"] == output.stat().st_size  # type: ignore[index]

    cached = build_nba_data_summary(manifest, cache, output)
    assert cached["cached"] is True
    status = inspect_nba_data(manifest, cache, output)
    assert status["ready"] is True
    assert status["summary_current"] is True


def test_cli_pipeline_emits_compact_json(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    manifest, _ = _fixture(tmp_path)
    cache = tmp_path / "cache"
    output = tmp_path / "summary.json"
    assert main(["nba-data", "sync", str(manifest), "--cache", str(cache)]) == 0
    capsys.readouterr()
    assert (
        main(
            [
                "nba-data",
                "build",
                str(manifest),
                str(output),
                "--cache",
                str(cache),
            ]
        )
        == 0
    )
    report = json.loads(capsys.readouterr().out)
    assert report["metrics"]["games"] == 2
    assert "\n  " not in json.dumps(report, separators=(",", ":"))


def test_build_rejects_unverified_or_incompatible_inputs(tmp_path: Path) -> None:
    manifest, source = _fixture(tmp_path)
    cache = tmp_path / "cache"
    sync_nba_data(manifest, cache)
    cached_source = cache / "nba-test-season" / source.name
    cached_source.write_text("changed", encoding="utf-8")
    with pytest.raises(NbaDataPipelineError, match="sha256 mismatch"):
        build_nba_data_summary(manifest, cache, tmp_path / "summary.json")

    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["build"]["metrics"][0]["column"] = "missing"
    payload["resources"][0]["sha256"] = hashlib.sha256(source.read_bytes()).hexdigest()
    write_json(manifest, payload)
    sync_nba_data(manifest, cache)
    with pytest.raises(NbaDataPipelineError, match="missing columns"):
        build_nba_data_summary(manifest, cache, tmp_path / "summary.json")


@pytest.mark.parametrize("archive_kind", ["xz", "zip", "tar.xz"])
def test_supported_archives_are_streamed(tmp_path: Path, archive_kind: str) -> None:
    manifest, source = _fixture(tmp_path)
    raw = source.read_bytes()
    archived = tmp_path / f"events.csv.{archive_kind}"
    if archive_kind == "xz":
        archived.write_bytes(lzma.compress(raw))
    elif archive_kind == "zip":
        with zipfile.ZipFile(archived, "w") as bundle:
            bundle.writestr("nested/events.csv", raw)
    else:
        with tarfile.open(archived, "w:xz") as bundle:
            member = tarfile.TarInfo("nested/events.csv")
            member.size = len(raw)
            bundle.addfile(member, io.BytesIO(raw))
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["resources"][0].update(
        {
            "filename": archived.name,
            "path": archived.name,
            "sha256": hashlib.sha256(archived.read_bytes()).hexdigest(),
        }
    )
    payload["build"]["archive_member"] = "nested/events.csv" if archive_kind != "xz" else None
    write_json(manifest, payload)
    cache = tmp_path / "cache"
    sync_nba_data(manifest, cache)
    summary = build_nba_data_summary(manifest, cache, tmp_path / "summary.json")
    assert summary["rows_processed"] == 4


def test_all_row_condition_operators_are_local(tmp_path: Path) -> None:
    manifest, source = _fixture(tmp_path)
    source.write_text(
        "game_id,event_type,points,team_id,flag\ng1,shot,2,A,true\ng1,turnover,0,B,false\n",
        encoding="utf-8",
    )
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["resources"][0]["sha256"] = hashlib.sha256(source.read_bytes()).hexdigest()
    payload["build"]["metrics"] = [
        {
            "name": "not_shots",
            "operation": "count",
            "where": {"event_type": {"not_equals": "shot"}},
        },
        {
            "name": "selected",
            "operation": "count",
            "where": {"event_type": {"in": ["shot"]}},
        },
        {
            "name": "contains",
            "operation": "count",
            "where": {"event_type": {"contains": "turn"}},
        },
        {
            "name": "not_contains",
            "operation": "count",
            "where": {"event_type": {"not_contains": "turn"}},
        },
        {
            "name": "false_flags",
            "operation": "count",
            "where": {"flag": {"truthy": False}},
        },
    ]
    write_json(manifest, payload)
    cache = tmp_path / "cache"
    sync_nba_data(manifest, cache)
    summary = build_nba_data_summary(manifest, cache, tmp_path / "summary.json")
    assert summary["metrics"] == {
        "contains": 1,
        "false_flags": 1,
        "not_contains": 1,
        "not_shots": 1,
        "selected": 1,
    }


def test_download_policy_force_refresh_and_offline_miss(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest, source = _fixture(tmp_path)
    raw = source.read_bytes()
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    resource = payload["resources"][0]
    resource.pop("path")
    resource["url"] = "http://example.invalid/events.csv"
    write_json(manifest, payload)
    with pytest.raises(NbaDataPipelineError, match="HTTPS"):
        sync_nba_data(manifest, tmp_path / "cache")
    with pytest.raises(NbaDataPipelineError, match="verified cache"):
        sync_nba_data(manifest, tmp_path / "offline", offline=True)

    resource["url"] = "https://example.invalid/events.csv"
    write_json(manifest, payload)
    monkeypatch.setattr(
        "courtsim.analysis.nba_data_pipeline.urllib.request.urlopen",
        lambda request, timeout: io.BytesIO(raw),
    )
    first = sync_nba_data(manifest, tmp_path / "cache")
    second = sync_nba_data(manifest, tmp_path / "cache", force=True)
    assert first["resources"][0]["status"] == "synced"  # type: ignore[index]
    assert second["resources"][0]["status"] == "synced"  # type: ignore[index]


def test_bad_rows_and_empty_denominator_fail_explicitly(tmp_path: Path) -> None:
    manifest, source = _fixture(tmp_path)
    cache = tmp_path / "cache"
    source.write_text("game_id,event_type,points,team_id\ng1,shot,nope,A\n", encoding="utf-8")
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["resources"][0]["sha256"] = hashlib.sha256(source.read_bytes()).hexdigest()
    write_json(manifest, payload)
    sync_nba_data(manifest, cache)
    with pytest.raises(NbaDataPipelineError, match="non-numeric"):
        build_nba_data_summary(manifest, cache, tmp_path / "bad-number.json")

    source.write_text("game_id,event_type,points,team_id\n", encoding="utf-8")
    payload["resources"][0]["sha256"] = hashlib.sha256(source.read_bytes()).hexdigest()
    write_json(manifest, payload)
    sync_nba_data(manifest, cache, force=True)
    with pytest.raises(NbaDataPipelineError, match="zero denominator"):
        build_nba_data_summary(manifest, cache, tmp_path / "zero.json")


def test_manifest_validation_rejects_ambiguous_contracts(tmp_path: Path) -> None:
    manifest, _ = _fixture(tmp_path)
    base: dict[str, Any] = json.loads(manifest.read_text(encoding="utf-8"))

    def mutate_duplicate_metric(payload: dict[str, Any]) -> None:
        payload["build"]["metrics"].append(dict(payload["build"]["metrics"][0]))

    def mutate_duplicate_resource(payload: dict[str, Any]) -> None:
        payload["resources"].append(dict(payload["resources"][0]))

    cases: list[tuple[str, Callable[[dict[str, Any]], None]]] = [
        ("schema_version", lambda payload: payload.update(schema_version=2)),
        ("fields", lambda payload: payload.update(extra=True)),
        ("unique", mutate_duplicate_resource),
        ("unsupported fields", lambda payload: payload["build"].update(extra=True)),
        ("non-empty list", lambda payload: payload["build"].update(metrics=[])),
        ("duplicate metric", mutate_duplicate_metric),
        (
            "unsupported metric operation",
            lambda payload: payload["build"]["metrics"][0].update(operation="median"),
        ),
        (
            "metric games contains unsupported fields",
            lambda payload: payload["build"]["metrics"][0].update(extra=True),
        ),
        (
            "unknown metric",
            lambda payload: payload["build"]["metrics"][-1].update(numerator="missing"),
        ),
        ("dataset_id", lambda payload: payload.update(dataset_id="NBA BAD")),
        (
            "filename",
            lambda payload: payload["resources"][0].update(filename="nested/events.csv"),
        ),
        (
            "SHA-256",
            lambda payload: payload["resources"][0].update(sha256="bad"),
        ),
        (
            "exactly one",
            lambda payload: payload["resources"][0].update(url="https://example.invalid"),
        ),
        ("one character", lambda payload: payload["build"].update(delimiter="||")),
    ]
    for index, (message, mutate) in enumerate(cases):
        payload = json.loads(json.dumps(base))
        mutate(payload)
        candidate = tmp_path / f"bad-{index}.json"
        write_json(candidate, payload)
        with pytest.raises(NbaDataPipelineError, match=message):
            inspect_nba_data(candidate, tmp_path / "cache")


@pytest.mark.parametrize(
    ("condition", "message"),
    [
        ({"equals": "shot", "contains": "s"}, "one operator"),
        ({"unknown": "shot"}, "unsupported condition"),
        ({"truthy": "yes"}, "must be boolean"),
        ({"in": "shot"}, "string list"),
        ({"equals": 1}, "must contain a string"),
    ],
)
def test_manifest_rejects_bad_conditions(
    tmp_path: Path,
    condition: dict[str, object],
    message: str,
) -> None:
    manifest, _ = _fixture(tmp_path)
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["build"]["metrics"][2]["where"]["event_type"] = condition
    write_json(manifest, payload)
    with pytest.raises(NbaDataPipelineError, match=message):
        inspect_nba_data(manifest, tmp_path / "cache")

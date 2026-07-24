"""Atomic local artifacts and provenance manifests."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import tempfile
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from courtsim import __version__
from courtsim.events import Event


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent, text=True
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def write_json(path: str | Path, value: Any) -> None:
    _atomic_text(
        Path(path),
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )


def write_events(path: str | Path, events: Iterable[Event]) -> None:
    write_jsonl(path, (event.to_dict() for event in events))


def write_jsonl(path: str | Path, records: Iterable[Mapping[str, Any]]) -> None:
    lines = [
        json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        for record in records
    ]
    _atomic_text(Path(path), "\n".join(lines) + ("\n" if lines else ""))


def build_manifest(
    *, seed: int, scenario_path: str | Path, outputs: Iterable[str | Path]
) -> dict[str, Any]:
    scenario = Path(scenario_path)
    output_paths = [Path(item) for item in outputs]
    return {
        "format_version": 1,
        "engine_version": __version__,
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "seed": seed,
        "inputs": [{"path": str(scenario), "sha256": sha256_file(scenario)}],
        "outputs": [
            {"path": item.name, "sha256": sha256_file(item), "bytes": item.stat().st_size}
            for item in output_paths
        ],
    }

"""Verified on-disk merge for independently produced audit shards."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any, cast

from courtsim import __version__
from courtsim.analysis.distribution import audit_game_results
from courtsim.artifacts import sha256_file, write_json, write_jsonl
from courtsim.domain.game import GameClockConfig, GameResult
from courtsim.domain.game_serialization import game_result_from_dict, game_result_to_dict
from courtsim.randomness import derive_seed
from courtsim.verification import verify_manifest


class ShardMergeError(ValueError):
    pass


def _load_object(path: Path) -> dict[str, Any]:
    try:
        value: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ShardMergeError(f"cannot load {path}") from error
    if not isinstance(value, dict):
        raise ShardMergeError(f"{path} must contain an object")
    return cast(dict[str, Any], value)


def _clock(manifest: dict[str, Any]) -> GameClockConfig:
    raw = manifest.get("clock")
    if not isinstance(raw, dict):
        raise ShardMergeError("manifest clock must be an object")
    try:
        return GameClockConfig(
            raw["regulation_periods"],
            raw["period_seconds"],
            raw["possession_seconds"],
        )
    except (KeyError, ValueError) as error:
        raise ShardMergeError("manifest clock is invalid") from error


def _games_path(manifest_path: Path, manifest: dict[str, Any]) -> Path:
    outputs = manifest.get("outputs")
    if not isinstance(outputs, list):
        raise ShardMergeError("manifest outputs must be a list")
    for output in outputs:
        if isinstance(output, dict) and output.get("path") == "games.jsonl":
            return manifest_path.parent / "games.jsonl"
    raise ShardMergeError("shard manifest does not declare games.jsonl")


def _read_games(
    path: Path,
    config: GameClockConfig,
) -> tuple[tuple[int, int, GameResult], ...]:
    rows: list[tuple[int, int, GameResult]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise ShardMergeError(f"cannot read {path}") from error
    for line_number, line in enumerate(lines, start=1):
        try:
            raw: object = json.loads(line)
            if not isinstance(raw, dict) or set(raw) != {"game_index", "seed", "result"}:
                raise ValueError
            index = raw["game_index"]
            seed = raw["seed"]
            if (
                not isinstance(index, int)
                or isinstance(index, bool)
                or index < 0
                or not isinstance(seed, int)
                or isinstance(seed, bool)
            ):
                raise ValueError
            result = game_result_from_dict(raw["result"], config)
        except (json.JSONDecodeError, ValueError) as error:
            raise ShardMergeError(f"{path}:{line_number}: invalid game record") from error
        rows.append((index, seed, result))
    if not rows:
        raise ShardMergeError(f"{path} contains no games")
    return tuple(rows)


def merge_batch_audit_shards(
    *,
    shard_manifests: tuple[str | Path, ...],
    output_directory: str | Path,
) -> Path:
    if len(shard_manifests) < 2:
        raise ShardMergeError("at least two shard manifests are required")
    loaded: list[tuple[Path, dict[str, Any]]] = []
    for raw_path in shard_manifests:
        path = Path(raw_path).resolve()
        report = verify_manifest(path)
        if not report.ok:
            raise ShardMergeError(f"shard verification failed: {path}: {report.issues}")
        loaded.append((path, _load_object(path)))

    first = loaded[0][1]
    identity_fields = ("master_seed", "clock", "teams", "model")
    for path, manifest in loaded[1:]:
        if any(manifest.get(field) != first.get(field) for field in identity_fields):
            raise ShardMergeError(f"incompatible shard metadata: {path}")
    master_seed = first.get("master_seed")
    if not isinstance(master_seed, int) or isinstance(master_seed, bool):
        raise ShardMergeError("master_seed must be an integer")
    config = _clock(first)
    rows = [
        row for path, manifest in loaded for row in _read_games(_games_path(path, manifest), config)
    ]
    rows.sort(key=lambda item: item[0])
    indices = tuple(row[0] for row in rows)
    if len(indices) != len(set(indices)):
        raise ShardMergeError("shards contain duplicate game indices")
    expected = tuple(range(indices[0], indices[-1] + 1))
    if indices != expected:
        missing = sorted(set(expected) - set(indices))
        raise ShardMergeError(f"shards have missing game indices: {missing}")
    for index, seed, _ in rows:
        if seed != derive_seed(master_seed, "model-game", index):
            raise ShardMergeError(f"game {index} seed does not match the master seed")

    destination = Path(output_directory)
    destination.mkdir(parents=True, exist_ok=True)
    games_path = destination / "games.jsonl"
    audit_path = destination / "audit.json"
    manifest_path = destination / "manifest.json"
    write_jsonl(
        games_path,
        (
            {
                "game_index": index,
                "seed": seed,
                "result": game_result_to_dict(result),
            }
            for index, seed, result in rows
        ),
    )
    write_json(audit_path, asdict(audit_game_results(tuple(row[2] for row in rows))))
    write_json(
        manifest_path,
        {
            "format_version": 1,
            "kind": "courtsim-model-distribution-audit-merged",
            "engine_version": __version__,
            "master_seed": master_seed,
            "game_indices": list(indices),
            "clock": first["clock"],
            "teams": first["teams"],
            "model": first["model"],
            "inputs": [{"path": str(path), "sha256": sha256_file(path)} for path, _ in loaded],
            "outputs": [
                {
                    "path": games_path.name,
                    "sha256": sha256_file(games_path),
                    "bytes": games_path.stat().st_size,
                },
                {
                    "path": audit_path.name,
                    "sha256": sha256_file(audit_path),
                    "bytes": audit_path.stat().st_size,
                },
            ],
        },
    )
    return manifest_path

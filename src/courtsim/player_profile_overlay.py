"""Strict single-leaf overlays for reproducible player-lineup experiments."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, cast

from courtsim.artifacts import sha256_file, write_json
from courtsim.domain.player_serialization import (
    PlayerSerializationError,
    player_lineup_from_dict,
)


class PlayerProfileOverlayError(ValueError):
    pass


def _validate_lineup(value: object, context: str) -> None:
    try:
        player_lineup_from_dict(value)
    except PlayerSerializationError as error:
        raise PlayerProfileOverlayError(f"{context} is invalid: {error}") from error


def _load_object(path: str | Path, context: str) -> dict[str, Any]:
    source = Path(path)
    try:
        raw: object = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise PlayerProfileOverlayError(f"cannot load {context}: {source}") from error
    if not isinstance(raw, dict):
        raise PlayerProfileOverlayError(f"{context} must contain an object")
    return cast(dict[str, Any], raw)


def apply_player_lineup_overlay(
    base_path: str | Path,
    overlay_path: str | Path,
) -> dict[str, Any]:
    base = copy.deepcopy(_load_object(base_path, "base player lineup"))
    _validate_lineup(base, "base player lineup")
    overlay = _load_object(overlay_path, "player lineup overlay")
    if (
        set(overlay)
        != {
            "format_version",
            "kind",
            "overlay_id",
            "lineup_id",
            "notes",
            "overrides",
        }
        or overlay.get("format_version") != 1
        or overlay.get("kind") != "courtsim-player-lineup-overlay"
    ):
        raise PlayerProfileOverlayError("player lineup overlay does not match format version 1")
    for field in ("overlay_id", "lineup_id", "notes"):
        if not isinstance(overlay[field], str) or not overlay[field].strip():
            raise PlayerProfileOverlayError(f"{field} must be a non-empty string")
    overrides = overlay["overrides"]
    if not isinstance(overrides, list) or not overrides:
        raise PlayerProfileOverlayError("overrides must be a non-empty list")
    raw_players = base.get("players")
    if not isinstance(raw_players, list):
        raise PlayerProfileOverlayError("base player lineup players are invalid")
    players = {
        player.get("player_id"): cast(dict[str, Any], player)
        for player in raw_players
        if isinstance(player, dict) and isinstance(player.get("player_id"), int)
    }
    seen: set[tuple[int | str, ...]] = set()
    for index, raw_override in enumerate(overrides):
        if not isinstance(raw_override, dict) or set(raw_override) != {
            "player_id",
            "path",
            "value",
        }:
            raise PlayerProfileOverlayError(f"overrides[{index}] is invalid")
        player_id = raw_override["player_id"]
        path = raw_override["path"]
        value = raw_override["value"]
        if (
            not isinstance(player_id, int)
            or isinstance(player_id, bool)
            or player_id not in players
        ):
            raise PlayerProfileOverlayError(f"overrides[{index}].player_id is invalid")
        if (
            not isinstance(path, list)
            or len(path) not in {2, 3}
            or not all(isinstance(part, str) and part for part in path)
            or path[0] not in {"abilities", "tendencies"}
            or (
                len(path) == 3
                and path[:2]
                not in (
                    ["tendencies", "play_role_mix"],
                    ["tendencies", "shot_zone_mix"],
                )
            )
            or (len(path) == 2 and path[1] in {"play_role_mix", "shot_zone_mix"})
        ):
            raise PlayerProfileOverlayError(f"overrides[{index}].path is invalid")
        if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= 100:
            raise PlayerProfileOverlayError(
                f"overrides[{index}].value must be an integer from 0 through 100"
            )
        key = (player_id, *path)
        if key in seen:
            raise PlayerProfileOverlayError(f"duplicate override path: {key}")
        seen.add(key)
        parent: object = players[player_id]
        for part in path[:-1]:
            if not isinstance(parent, dict) or part not in parent:
                raise PlayerProfileOverlayError(f"override path does not exist: {key}")
            parent = parent[part]
        leaf = path[-1]
        if (
            not isinstance(parent, dict)
            or leaf not in parent
            or not isinstance(parent[leaf], int)
            or isinstance(parent[leaf], bool)
        ):
            raise PlayerProfileOverlayError(f"override leaf is not a rating: {key}")
        parent[leaf] = value
    base["lineup_id"] = overlay["lineup_id"]
    _validate_lineup(base, "materialized player lineup")
    return base


def materialize_player_lineup_overlay(
    *,
    base_path: str | Path,
    overlay_path: str | Path,
    output_path: str | Path,
) -> tuple[Path, Path]:
    base = Path(base_path).resolve()
    overlay = Path(overlay_path).resolve()
    output = Path(output_path)
    manifest = output.with_suffix(f"{output.suffix}.manifest.json")
    if output.exists() or manifest.exists():
        raise PlayerProfileOverlayError(f"output already exists: {output}")
    candidate = apply_player_lineup_overlay(base, overlay)
    write_json(output, candidate)
    _validate_lineup(
        _load_object(output, "materialized player lineup"),
        "materialized player lineup",
    )
    overlay_payload = _load_object(overlay, "player lineup overlay")
    write_json(
        manifest,
        {
            "format_version": 1,
            "kind": "courtsim-player-lineup-overlay-manifest",
            "overlay_id": overlay_payload["overlay_id"],
            "inputs": [
                {"role": "base", "path": str(base), "sha256": sha256_file(base)},
                {
                    "role": "overlay",
                    "path": str(overlay),
                    "sha256": sha256_file(overlay),
                },
            ],
            "outputs": [
                {
                    "path": output.name,
                    "sha256": sha256_file(output),
                    "bytes": output.stat().st_size,
                }
            ],
        },
    )
    return output, manifest

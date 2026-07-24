"""Strict, auditable overlays for materializing calibration candidates."""

from __future__ import annotations

import copy
import json
import math
from pathlib import Path
from typing import Any, cast


class ParameterOverlayError(ValueError):
    pass


def _object(value: object, field: str) -> dict[str, Any]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ParameterOverlayError(f"{field} must be an object")
    return cast(dict[str, Any], value)


def _load(path: str | Path, field: str) -> dict[str, Any]:
    try:
        value: object = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ParameterOverlayError(f"cannot load {field}: {path}") from error
    return _object(value, field)


def apply_parameter_overlay(
    base_path: str | Path,
    overlay_path: str | Path,
) -> dict[str, Any]:
    base = copy.deepcopy(_load(base_path, "base parameters"))
    overlay = _load(overlay_path, "parameter overlay")
    if (
        set(overlay)
        != {
            "format_version",
            "overlay_id",
            "parameter_version",
            "notes",
            "overrides",
        }
        or overlay["format_version"] != 1
    ):
        raise ParameterOverlayError("parameter overlay does not match format version 1")
    for field in ("overlay_id", "parameter_version", "notes"):
        if not isinstance(overlay[field], str) or not overlay[field].strip():
            raise ParameterOverlayError(f"{field} must be a non-empty string")
    overrides = overlay["overrides"]
    if not isinstance(overrides, list) or not overrides:
        raise ParameterOverlayError("overrides must be a non-empty list")

    seen: set[tuple[str, ...]] = set()
    for index, item in enumerate(overrides):
        if not isinstance(item, dict) or set(item) != {"path", "value"}:
            raise ParameterOverlayError(f"overrides[{index}] is invalid")
        path = item["path"]
        value = item["value"]
        if (
            not isinstance(path, list)
            or not path
            or not all(isinstance(part, str) and part for part in path)
            or path[0] not in {"nodes", "rules"}
        ):
            raise ParameterOverlayError(f"overrides[{index}].path is invalid")
        path_key = tuple(path)
        if path_key in seen:
            raise ParameterOverlayError(f"duplicate override path: {path_key}")
        seen.add(path_key)
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise ParameterOverlayError(f"overrides[{index}].value must be numeric")
        if not math.isfinite(float(value)):
            raise ParameterOverlayError(f"overrides[{index}].value must be finite")
        parent: object = base
        for part in path[:-1]:
            if not isinstance(parent, dict) or part not in parent:
                raise ParameterOverlayError(f"override path does not exist: {path_key}")
            parent = parent[part]
        leaf = path[-1]
        if (
            not isinstance(parent, dict)
            or leaf not in parent
            or not isinstance(parent[leaf], (int, float))
            or isinstance(parent[leaf], bool)
        ):
            raise ParameterOverlayError(f"override leaf is not numeric: {path_key}")
        parent[leaf] = value

    metadata = _object(base.get("metadata"), "base metadata")
    metadata["parameter_version"] = overlay["parameter_version"]
    metadata["notes"] = overlay["notes"]
    metadata["parameter_hash"] = None
    return base


def add_assist_resolution_node(
    base_path: str | Path,
    migration_path: str | Path,
) -> dict[str, Any]:
    base = copy.deepcopy(_load(base_path, "base parameters"))
    migration = _load(migration_path, "assist migration")
    if (
        set(migration)
        != {
            "format_version",
            "migration_id",
            "parameter_version",
            "notes",
            "assist_resolution",
        }
        or migration["format_version"] != 1
    ):
        raise ParameterOverlayError("assist migration does not match format version 1")
    for field in ("migration_id", "parameter_version", "notes"):
        if not isinstance(migration[field], str) or not migration[field].strip():
            raise ParameterOverlayError(f"{field} must be a non-empty string")
    metadata = _object(base.get("metadata"), "base metadata")
    if metadata.get("schema_version") != "demo-v1.3":
        raise ParameterOverlayError("assist migration requires demo-v1.3 base parameters")
    nodes = _object(base.get("nodes"), "base nodes")
    if "assist_resolution" in nodes:
        raise ParameterOverlayError("base parameters already contain assist_resolution")
    assist = _object(migration["assist_resolution"], "assist_resolution")
    nodes["assist_resolution"] = copy.deepcopy(assist)
    metadata["schema_version"] = "demo-v1.4"
    metadata["parameter_version"] = migration["parameter_version"]
    metadata["notes"] = migration["notes"]
    metadata["parameter_hash"] = None
    return base


def add_foul_free_throw_nodes(
    base_path: str | Path,
    migration_path: str | Path,
) -> dict[str, Any]:
    base = copy.deepcopy(_load(base_path, "base parameters"))
    migration = _load(migration_path, "foul/free-throw migration")
    if (
        set(migration)
        != {
            "format_version",
            "migration_id",
            "parameter_version",
            "notes",
            "shooting_foul",
            "free_throw_make",
        }
        or migration["format_version"] != 1
    ):
        raise ParameterOverlayError("foul/free-throw migration does not match format version 1")
    for field in ("migration_id", "parameter_version", "notes"):
        if not isinstance(migration[field], str) or not migration[field].strip():
            raise ParameterOverlayError(f"{field} must be a non-empty string")
    metadata = _object(base.get("metadata"), "base metadata")
    if metadata.get("schema_version") != "demo-v1.4":
        raise ParameterOverlayError("foul/free-throw migration requires demo-v1.4 base parameters")
    nodes = _object(base.get("nodes"), "base nodes")
    if "shooting_foul" in nodes or "free_throw_make" in nodes:
        raise ParameterOverlayError("base parameters already contain foul/free-throw nodes")
    nodes["shooting_foul"] = copy.deepcopy(_object(migration["shooting_foul"], "shooting_foul"))
    nodes["free_throw_make"] = copy.deepcopy(
        _object(migration["free_throw_make"], "free_throw_make")
    )
    metadata["schema_version"] = "demo-v1.5"
    metadata["parameter_version"] = migration["parameter_version"]
    metadata["notes"] = migration["notes"]
    metadata["parameter_hash"] = None
    return base


def add_non_shooting_foul_node(
    base_path: str | Path,
    migration_path: str | Path,
) -> dict[str, Any]:
    base = copy.deepcopy(_load(base_path, "base parameters"))
    migration = _load(migration_path, "non-shooting foul migration")
    if (
        set(migration)
        != {
            "format_version",
            "migration_id",
            "parameter_version",
            "notes",
            "bonus_foul_threshold",
            "non_shooting_foul",
        }
        or migration["format_version"] != 1
    ):
        raise ParameterOverlayError("non-shooting foul migration does not match format version 1")
    for field in ("migration_id", "parameter_version", "notes"):
        if not isinstance(migration[field], str) or not migration[field].strip():
            raise ParameterOverlayError(f"{field} must be a non-empty string")
    threshold = migration["bonus_foul_threshold"]
    if not isinstance(threshold, int) or isinstance(threshold, bool) or threshold < 1:
        raise ParameterOverlayError("bonus_foul_threshold must be a positive integer")
    metadata = _object(base.get("metadata"), "base metadata")
    if metadata.get("schema_version") != "demo-v1.5":
        raise ParameterOverlayError("non-shooting foul migration requires demo-v1.5 parameters")
    nodes = _object(base.get("nodes"), "base nodes")
    if "non_shooting_foul" in nodes:
        raise ParameterOverlayError("base parameters already contain non_shooting_foul")
    rules = _object(base.get("rules"), "base rules")
    if "bonus_foul_threshold" in rules:
        raise ParameterOverlayError("base parameters already contain bonus_foul_threshold")
    nodes["non_shooting_foul"] = copy.deepcopy(
        _object(migration["non_shooting_foul"], "non_shooting_foul")
    )
    rules["bonus_foul_threshold"] = threshold
    metadata["schema_version"] = "demo-v1.6"
    metadata["parameter_version"] = migration["parameter_version"]
    metadata["notes"] = migration["notes"]
    metadata["parameter_hash"] = None
    return base


def add_assist_occurrence_effects(
    base_path: str | Path,
    migration_path: str | Path,
) -> dict[str, Any]:
    base = copy.deepcopy(_load(base_path, "base parameters"))
    migration = _load(migration_path, "assist occurrence migration")
    if (
        set(migration)
        != {
            "format_version",
            "migration_id",
            "parameter_version",
            "notes",
            "occurrence_logit_intercept",
            "occurrence_playmaking_coefficient",
            "occurrence_decision_coefficient",
        }
        or migration["format_version"] != 1
    ):
        raise ParameterOverlayError("assist occurrence migration does not match format version 1")
    for field in ("migration_id", "parameter_version", "notes"):
        if not isinstance(migration[field], str) or not migration[field].strip():
            raise ParameterOverlayError(f"{field} must be a non-empty string")
    metadata = _object(base.get("metadata"), "base metadata")
    if metadata.get("schema_version") != "demo-v1.6":
        raise ParameterOverlayError("assist occurrence migration requires demo-v1.6 parameters")
    assist = _object(
        _object(base.get("nodes"), "base nodes").get("assist_resolution"),
        "assist_resolution",
    )
    intercept = migration["occurrence_logit_intercept"]
    if (
        not isinstance(intercept, (int, float))
        or isinstance(intercept, bool)
        or not math.isfinite(float(intercept))
        or abs(float(intercept)) > 0.8
    ):
        raise ParameterOverlayError("occurrence_logit_intercept must be between -0.8 and 0.8")
    if "occurrence_logit_intercept" in assist:
        raise ParameterOverlayError("assist_resolution already contains occurrence_logit_intercept")
    assist["occurrence_logit_intercept"] = intercept
    for field in (
        "occurrence_playmaking_coefficient",
        "occurrence_decision_coefficient",
    ):
        if field in assist:
            raise ParameterOverlayError(f"assist_resolution already contains {field}")
        value = migration[field]
        if (
            not isinstance(value, (int, float))
            or isinstance(value, bool)
            or not math.isfinite(float(value))
            or not 0.0 <= float(value) <= 0.8
        ):
            raise ParameterOverlayError(f"{field} must be between zero and 0.8")
        assist[field] = value
    metadata["schema_version"] = "demo-v1.7"
    metadata["parameter_version"] = migration["parameter_version"]
    metadata["notes"] = migration["notes"]
    metadata["parameter_hash"] = None
    return base


def add_possession_duration_node(
    base_path: str | Path,
    migration_path: str | Path,
) -> dict[str, Any]:
    base = copy.deepcopy(_load(base_path, "base parameters"))
    migration = _load(migration_path, "possession duration migration")
    if (
        set(migration)
        != {
            "format_version",
            "migration_id",
            "parameter_version",
            "notes",
            "possession_duration",
        }
        or migration["format_version"] != 1
    ):
        raise ParameterOverlayError("possession duration migration does not match format version 1")
    for field in ("migration_id", "parameter_version", "notes"):
        if not isinstance(migration[field], str) or not migration[field].strip():
            raise ParameterOverlayError(f"{field} must be a non-empty string")
    metadata = _object(base.get("metadata"), "base metadata")
    if metadata.get("schema_version") != "demo-v1.7":
        raise ParameterOverlayError("possession duration migration requires demo-v1.7 parameters")
    nodes = _object(base.get("nodes"), "base nodes")
    if "possession_duration" in nodes:
        raise ParameterOverlayError("base parameters already contain possession_duration")
    node = _object(migration["possession_duration"], "possession_duration")
    nodes["possession_duration"] = copy.deepcopy(node)
    metadata["schema_version"] = "demo-v1.8"
    metadata["parameter_version"] = migration["parameter_version"]
    metadata["notes"] = migration["notes"]
    metadata["parameter_hash"] = None
    return base


def add_late_game_tempo_adjustments(
    base_path: str | Path,
    migration_path: str | Path,
) -> dict[str, Any]:
    base = copy.deepcopy(_load(base_path, "base parameters"))
    migration = _load(migration_path, "late-game tempo migration")
    if (
        set(migration)
        != {
            "format_version",
            "migration_id",
            "parameter_version",
            "notes",
            "late_game_adjustments",
        }
        or migration["format_version"] != 1
    ):
        raise ParameterOverlayError("late-game tempo migration does not match format version 1")
    for field in ("migration_id", "parameter_version", "notes"):
        if not isinstance(migration[field], str) or not migration[field].strip():
            raise ParameterOverlayError(f"{field} must be a non-empty string")
    metadata = _object(base.get("metadata"), "base metadata")
    if metadata.get("schema_version") != "demo-v1.8":
        raise ParameterOverlayError("late-game tempo migration requires demo-v1.8 parameters")
    duration = _object(
        _object(base.get("nodes"), "base nodes").get("possession_duration"),
        "possession_duration",
    )
    if "late_game_adjustments" in duration:
        raise ParameterOverlayError("possession_duration already contains late_game_adjustments")
    duration["late_game_adjustments"] = copy.deepcopy(
        _object(migration["late_game_adjustments"], "late_game_adjustments")
    )
    metadata["schema_version"] = "demo-v1.9"
    metadata["parameter_version"] = migration["parameter_version"]
    metadata["notes"] = migration["notes"]
    metadata["parameter_hash"] = None
    return base


def add_late_game_strategy_node(
    base_path: str | Path,
    migration_path: str | Path,
) -> dict[str, Any]:
    base = copy.deepcopy(_load(base_path, "base parameters"))
    migration = _load(migration_path, "late-game strategy migration")
    if (
        set(migration)
        != {
            "format_version",
            "migration_id",
            "parameter_version",
            "notes",
            "late_game_strategy",
        }
        or migration["format_version"] != 1
    ):
        raise ParameterOverlayError("late-game strategy migration does not match format version 1")
    for field in ("migration_id", "parameter_version", "notes"):
        if not isinstance(migration[field], str) or not migration[field].strip():
            raise ParameterOverlayError(f"{field} must be a non-empty string")
    metadata = _object(base.get("metadata"), "base metadata")
    if metadata.get("schema_version") != "demo-v1.9":
        raise ParameterOverlayError("late-game strategy migration requires demo-v1.9 parameters")
    nodes = _object(base.get("nodes"), "base nodes")
    if "late_game_strategy" in nodes:
        raise ParameterOverlayError("base parameters already contain late_game_strategy")
    nodes["late_game_strategy"] = copy.deepcopy(
        _object(migration["late_game_strategy"], "late_game_strategy")
    )
    metadata["schema_version"] = "demo-v1.10"
    metadata["parameter_version"] = migration["parameter_version"]
    metadata["notes"] = migration["notes"]
    metadata["parameter_hash"] = None
    return base


def promote_intentional_foul_execution(
    base_path: str | Path,
    migration_path: str | Path,
) -> dict[str, Any]:
    base = copy.deepcopy(_load(base_path, "base parameters"))
    migration = _load(migration_path, "intentional-foul execution migration")
    if (
        set(migration)
        != {
            "format_version",
            "migration_id",
            "parameter_version",
            "notes",
            "intentional_foul_clock_seconds",
        }
        or migration["format_version"] != 1
    ):
        raise ParameterOverlayError(
            "intentional-foul execution migration does not match format version 1"
        )
    for field in ("migration_id", "parameter_version", "notes"):
        if not isinstance(migration[field], str) or not migration[field].strip():
            raise ParameterOverlayError(f"{field} must be a non-empty string")
    seconds = migration["intentional_foul_clock_seconds"]
    if not isinstance(seconds, int) or isinstance(seconds, bool) or not 1 <= seconds <= 10:
        raise ParameterOverlayError("intentional_foul_clock_seconds must be within [1, 10]")
    metadata = _object(base.get("metadata"), "base metadata")
    if metadata.get("schema_version") != "demo-v1.10":
        raise ParameterOverlayError(
            "intentional-foul execution migration requires demo-v1.10 parameters"
        )
    strategy = _object(
        _object(base.get("nodes"), "base nodes").get("late_game_strategy"),
        "late_game_strategy",
    )
    if "intentional_foul_clock_seconds" in strategy:
        raise ParameterOverlayError("late_game_strategy already enables intentional fouls")
    strategy["intentional_foul_clock_seconds"] = seconds
    metadata["schema_version"] = "demo-v1.11"
    metadata["parameter_version"] = migration["parameter_version"]
    metadata["notes"] = migration["notes"]
    metadata["parameter_hash"] = None
    return base


def enable_non_bonus_intentional_fouls(
    base_path: str | Path,
    migration_path: str | Path,
) -> dict[str, Any]:
    base = copy.deepcopy(_load(base_path, "base parameters"))
    migration = _load(migration_path, "non-bonus intentional-foul migration")
    if (
        set(migration)
        != {
            "format_version",
            "migration_id",
            "parameter_version",
            "notes",
            "intentional_foul_non_bonus_enabled",
        }
        or migration["format_version"] != 1
        or migration["intentional_foul_non_bonus_enabled"] is not True
    ):
        raise ParameterOverlayError(
            "non-bonus intentional-foul migration does not match format version 1"
        )
    for field in ("migration_id", "parameter_version", "notes"):
        if not isinstance(migration[field], str) or not migration[field].strip():
            raise ParameterOverlayError(f"{field} must be a non-empty string")
    metadata = _object(base.get("metadata"), "base metadata")
    if metadata.get("schema_version") != "demo-v1.11":
        raise ParameterOverlayError(
            "non-bonus intentional-foul migration requires demo-v1.11 parameters"
        )
    strategy = _object(
        _object(base.get("nodes"), "base nodes").get("late_game_strategy"),
        "late_game_strategy",
    )
    if "intentional_foul_non_bonus_enabled" in strategy:
        raise ParameterOverlayError("late_game_strategy already enables non-bonus execution")
    strategy["intentional_foul_non_bonus_enabled"] = True
    metadata["schema_version"] = "demo-v1.12"
    metadata["parameter_version"] = migration["parameter_version"]
    metadata["notes"] = migration["notes"]
    metadata["parameter_hash"] = None
    return base

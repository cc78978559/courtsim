"""JSON loading and strict validation for foundation configuration."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class ConfigError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class EngineConfig:
    min_action_budget: int
    max_action_budget: int


@dataclass(frozen=True, slots=True)
class ScenarioConfig:
    schema_version: int
    name: str
    zones: tuple[str, ...]
    engine: EngineConfig


def _require_exact_keys(value: dict[str, Any], expected: set[str], path: str) -> None:
    missing = expected - value.keys()
    extra = value.keys() - expected
    if missing:
        raise ConfigError(f"{path}: missing keys: {', '.join(sorted(missing))}")
    if extra:
        raise ConfigError(f"{path}: unknown keys: {', '.join(sorted(extra))}")


def parse_scenario(raw: Any) -> ScenarioConfig:
    if not isinstance(raw, dict):
        raise ConfigError("root: expected an object")
    _require_exact_keys(raw, {"schema_version", "name", "court", "engine"}, "root")

    if raw["schema_version"] != 1:
        raise ConfigError("schema_version: only version 1 is supported")
    if not isinstance(raw["name"], str) or not raw["name"].strip():
        raise ConfigError("name: expected a non-empty string")

    court = raw["court"]
    if not isinstance(court, dict):
        raise ConfigError("court: expected an object")
    _require_exact_keys(court, {"zones"}, "court")
    zones = court["zones"]
    if (
        not isinstance(zones, list)
        or not zones
        or any(not isinstance(zone, str) or not zone.strip() for zone in zones)
    ):
        raise ConfigError("court.zones: expected a non-empty list of non-empty strings")
    if len(zones) != len(set(zones)):
        raise ConfigError("court.zones: zone names must be unique")

    engine = raw["engine"]
    if not isinstance(engine, dict):
        raise ConfigError("engine: expected an object")
    _require_exact_keys(engine, {"min_action_budget", "max_action_budget"}, "engine")
    minimum = engine["min_action_budget"]
    maximum = engine["max_action_budget"]
    if type(minimum) is not int or type(maximum) is not int:
        raise ConfigError("engine: action budgets must be integers")
    if minimum < 1 or maximum < minimum:
        raise ConfigError("engine: require 1 <= min_action_budget <= max_action_budget")

    return ScenarioConfig(
        schema_version=1,
        name=raw["name"].strip(),
        zones=tuple(zones),
        engine=EngineConfig(minimum, maximum),
    )


def load_scenario(path: str | Path) -> ScenarioConfig:
    source = Path(path)
    try:
        raw = json.loads(source.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ConfigError(f"cannot read {source}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ConfigError(f"{source}:{exc.lineno}:{exc.colno}: {exc.msg}") from exc
    return parse_scenario(raw)

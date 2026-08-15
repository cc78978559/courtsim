"""Resumable compact player evidence paired with full-engine season batches."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from statistics import fmean
from typing import Any, cast

from courtsim.analysis.nba_player_aggregates import NBAPlayerSeasonAggregate
from courtsim.analysis.nba_player_evaluation import (
    aggregate_nba_player_evaluations,
    audit_nba_player_aggregates,
    evaluate_nba_player_audit,
)
from courtsim.analysis.nba_player_targets import NBAPlayerTargetSet

NBA_PLAYER_HOLDOUT_VERSION = "nba-player-holdout-batch-v1"
NBA_PLAYER_HOLDOUT_GATE_VERSION = "nba-player-holdout-gate-v1"


class NbaPlayerHoldoutError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class NBAPlayerHoldoutCell:
    season_index: int
    season_id: str
    seed: int
    evaluation: dict[str, object]
    zero_minute_rate: float
    mean_rotation_coverage: float
    cell_sha256: str


@dataclass(frozen=True, slots=True)
class NBAPlayerHoldoutBatch:
    batch_id: str
    master_seed: int
    seasons: int
    target_id: str
    target_season: str
    cells: tuple[NBAPlayerHoldoutCell, ...]
    complete: bool
    batch_sha256: str
    version: str = NBA_PLAYER_HOLDOUT_VERSION


def build_nba_player_holdout_cell(
    season_index: int,
    season_id: str,
    seed: int,
    aggregates: tuple[NBAPlayerSeasonAggregate, ...],
    targets: NBAPlayerTargetSet,
) -> NBAPlayerHoldoutCell:
    audit = audit_nba_player_aggregates(aggregates, targets)
    evaluation = evaluate_nba_player_audit(audit, targets)
    rows = cast(list[dict[str, object]], audit["players"])
    zero_minute_rate = sum(_number(row["minutes"], "minutes") == 0.0 for row in rows) / len(rows)
    coverage = fmean(item.rotation_coverage for item in aggregates) if aggregates else 0.0
    payload = {
        "season_index": season_index,
        "season_id": season_id,
        "seed": seed,
        "evaluation": evaluation,
        "zero_minute_rate": zero_minute_rate,
        "mean_rotation_coverage": coverage,
    }
    return NBAPlayerHoldoutCell(
        season_index,
        season_id,
        seed,
        evaluation,
        zero_minute_rate,
        coverage,
        _digest(payload),
    )


def append_nba_player_holdout_cells(
    *,
    batch_id: str,
    master_seed: int,
    seasons: int,
    targets: NBAPlayerTargetSet,
    cells: tuple[NBAPlayerHoldoutCell, ...],
    previous: NBAPlayerHoldoutBatch | None = None,
) -> NBAPlayerHoldoutBatch:
    prior = list(previous.cells if previous is not None else ())
    identity = (batch_id, master_seed, seasons, targets.target_id, targets.season)
    if (
        previous is not None
        and (
            previous.batch_id,
            previous.master_seed,
            previous.seasons,
            previous.target_id,
            previous.target_season,
        )
        != identity
    ):
        raise NbaPlayerHoldoutError("player holdout resume identity differs")
    for cell in cells:
        if cell.season_index != len(prior):
            raise NbaPlayerHoldoutError("player holdout cells must be contiguous")
        prior.append(cell)
    if len(prior) > seasons:
        raise NbaPlayerHoldoutError("player holdout contains too many seasons")
    canonical = tuple(prior)
    return NBAPlayerHoldoutBatch(
        batch_id,
        master_seed,
        seasons,
        targets.target_id,
        targets.season,
        canonical,
        len(canonical) == seasons,
        _batch_digest(identity, canonical),
    )


def nba_player_holdout_to_dict(batch: NBAPlayerHoldoutBatch) -> dict[str, object]:
    return {
        "version": batch.version,
        "spec": {
            "batch_id": batch.batch_id,
            "master_seed": batch.master_seed,
            "seasons": batch.seasons,
            "target_id": batch.target_id,
            "target_season": batch.target_season,
        },
        "cells": [_cell_payload(cell) | {"cell_sha256": cell.cell_sha256} for cell in batch.cells],
        "complete": batch.complete,
        "batch_sha256": batch.batch_sha256,
    }


def nba_player_holdout_from_dict(value: object) -> NBAPlayerHoldoutBatch:
    root = _object(value, "player holdout")
    if (
        set(root) != {"version", "spec", "cells", "complete", "batch_sha256"}
        or root.get("version") != NBA_PLAYER_HOLDOUT_VERSION
    ):
        raise NbaPlayerHoldoutError("player holdout schema differs")
    spec = _object(root["spec"], "player holdout spec")
    raw_cells = root["cells"]
    if not isinstance(raw_cells, list) or not isinstance(root["complete"], bool):
        raise NbaPlayerHoldoutError("player holdout cells or completion state is invalid")
    cells = []
    for raw in raw_cells:
        item = _object(raw, "player holdout cell")
        evaluation = _object(item.get("evaluation"), "player holdout evaluation")
        cell = NBAPlayerHoldoutCell(
            _integer(item.get("season_index"), "season_index"),
            _text(item.get("season_id"), "season_id"),
            _integer(item.get("seed"), "seed"),
            evaluation,
            _number(item.get("zero_minute_rate"), "zero_minute_rate"),
            _number(item.get("mean_rotation_coverage"), "mean_rotation_coverage"),
            _text(item.get("cell_sha256"), "cell_sha256"),
        )
        if cell.cell_sha256 != _digest(_cell_payload(cell)):
            raise NbaPlayerHoldoutError("player holdout cell hash differs")
        cells.append(cell)
    identity = (
        _text(spec.get("batch_id"), "batch_id"),
        _integer(spec.get("master_seed"), "master_seed"),
        _integer(spec.get("seasons"), "seasons"),
        _text(spec.get("target_id"), "target_id"),
        _text(spec.get("target_season"), "target_season"),
    )
    canonical = tuple(cells)
    batch = NBAPlayerHoldoutBatch(
        *identity,
        canonical,
        root["complete"],
        _text(root.get("batch_sha256"), "batch_sha256"),
    )
    if tuple(cell.season_index for cell in canonical) != tuple(range(len(canonical))):
        raise NbaPlayerHoldoutError("player holdout cells are not contiguous")
    if batch.complete != (len(canonical) == batch.seasons) or batch.batch_sha256 != _batch_digest(
        identity, canonical
    ):
        raise NbaPlayerHoldoutError("player holdout batch integrity differs")
    return batch


def load_nba_player_holdout_gate(value: object) -> dict[str, object]:
    root = _object(value, "player holdout gate")
    expected = {
        "version",
        "gate_id",
        "frozen_at",
        "minimum_seasons",
        "forbidden_master_seeds",
        "batch_id_prefix",
        "target_id",
        "target_season",
        "maximums",
    }
    if set(root) != expected or root.get("version") != NBA_PLAYER_HOLDOUT_GATE_VERSION:
        raise NbaPlayerHoldoutError("player holdout gate schema differs")
    raw_thresholds = _object(root.get("maximums"), "player holdout gate maximums")
    required = {
        "minutes_mae",
        "usage_mae",
        "true_shooting_mae",
        "shot_structure_mae",
        "zero_minute_rate",
    }
    if set(raw_thresholds) != required:
        raise NbaPlayerHoldoutError("player holdout gate metrics differ")
    minimum = _integer(root["minimum_seasons"], "minimum_seasons")
    seeds = root["forbidden_master_seeds"]
    if (
        minimum < 30
        or not isinstance(seeds, list)
        or seeds != sorted(set(seeds))
        or any(not isinstance(seed, int) or isinstance(seed, bool) for seed in seeds)
    ):
        raise NbaPlayerHoldoutError("player holdout gate sample constraints differ")
    return {
        **root,
        "maximums": {
            metric: _number(raw_thresholds[metric], metric) for metric in sorted(required)
        },
    }


def evaluate_nba_player_holdout(
    batch: NBAPlayerHoldoutBatch,
    gate: dict[str, object] | None = None,
) -> dict[str, object]:
    minimum = 30 if gate is None else cast(int, gate["minimum_seasons"])
    if not batch.complete or len(batch.cells) < minimum:
        raise NbaPlayerHoldoutError("formal player holdout requires thirty complete seasons")
    if gate is not None and (
        batch.master_seed in cast(list[int], gate["forbidden_master_seeds"])
        or not batch.batch_id.startswith(cast(str, gate["batch_id_prefix"]))
        or batch.target_id != gate["target_id"]
        or batch.target_season != gate["target_season"]
    ):
        raise NbaPlayerHoldoutError("player holdout identity violates its frozen gate")
    pooled = aggregate_nba_player_evaluations(tuple(cell.evaluation for cell in batch.cells))
    metrics = {
        cast(str, item["metric"]): item for item in cast(list[dict[str, object]], pooled["metrics"])
    }
    thresholds = (
        cast(dict[str, float], gate["maximums"])
        if gate is not None
        else {
            "minutes_mae": 6.0,
            "usage_mae": 0.06,
            "true_shooting_mae": 0.08,
            "shot_structure_mae": 0.08,
            "zero_minute_rate": 0.10,
        }
    )
    observed = {
        "minutes_mae": _number(metrics["minutes_per_game"]["mean_mae"], "mean_mae"),
        "usage_mae": _number(metrics["usage_rate"]["mean_mae"], "mean_mae"),
        "true_shooting_mae": _number(metrics["true_shooting_percentage"]["mean_mae"], "mean_mae"),
        "shot_structure_mae": fmean(
            _number(metrics[f"shot_zone_share.{zone}"]["mean_mae"], "mean_mae")
            for zone in ("RIM", "MIDRANGE", "THREE")
        ),
        "zero_minute_rate": fmean(cell.zero_minute_rate for cell in batch.cells),
    }
    checks = [
        {
            "metric": metric,
            "observed": value,
            "maximum": thresholds[metric],
            "passed": value <= thresholds[metric],
        }
        for metric, value in observed.items()
    ]
    return {
        "schema_version": 1,
        "version": NBA_PLAYER_HOLDOUT_GATE_VERSION,
        "batch_id": batch.batch_id,
        "batch_sha256": batch.batch_sha256,
        "seasons": len(batch.cells),
        "target_id": batch.target_id,
        "target_season": batch.target_season,
        "pooled_evaluation": pooled,
        "mean_rotation_coverage": fmean(cell.mean_rotation_coverage for cell in batch.cells),
        "checks": checks,
        "passed": all(cast(bool, item["passed"]) for item in checks),
    }


def _cell_payload(cell: NBAPlayerHoldoutCell) -> dict[str, object]:
    return {
        "season_index": cell.season_index,
        "season_id": cell.season_id,
        "seed": cell.seed,
        "evaluation": cell.evaluation,
        "zero_minute_rate": cell.zero_minute_rate,
        "mean_rotation_coverage": cell.mean_rotation_coverage,
    }


def _batch_digest(
    identity: tuple[str, int, int, str, str], cells: tuple[NBAPlayerHoldoutCell, ...]
) -> str:
    return _digest(
        {
            "version": NBA_PLAYER_HOLDOUT_VERSION,
            "identity": list(identity),
            "cell_hashes": [cell.cell_sha256 for cell in cells],
        }
    )


def _digest(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _object(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise NbaPlayerHoldoutError(f"{label} must be an object")
    return cast(dict[str, Any], value)


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise NbaPlayerHoldoutError(f"{label} must be non-empty text")
    return value


def _integer(value: object, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise NbaPlayerHoldoutError(f"{label} must be a non-negative integer")
    return value


def _number(value: object, label: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
        raise NbaPlayerHoldoutError(f"{label} must be finite numeric data")
    return float(value)

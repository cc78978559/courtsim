"""Deterministic resumable orchestration for multi-season quick simulations."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass

from courtsim.analysis.quick_sim_comparison import QuickSimSeasonSummary
from courtsim.randomness import derive_seed

QUICK_SIM_BATCH_VERSION = "quick-sim-batch-v1"
QuickSimSeasonExecutor = Callable[[str, int], QuickSimSeasonSummary]


class QuickSimBatchError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class QuickSimBatchSpec:
    batch_id: str
    master_seed: int
    seasons: int
    team_count: int = 30
    version: str = QUICK_SIM_BATCH_VERSION

    def __post_init__(self) -> None:
        if not self.batch_id.strip():
            raise ValueError("quick-sim batch_id must not be blank")
        if (
            not isinstance(self.master_seed, int)
            or isinstance(self.master_seed, bool)
            or not 1 <= self.seasons <= 10_000
            or not 2 <= self.team_count <= 100
        ):
            raise ValueError("quick-sim batch dimensions are invalid")
        if self.version != QUICK_SIM_BATCH_VERSION:
            raise ValueError("unsupported quick-sim batch version")


@dataclass(frozen=True, slots=True)
class QuickSimBatchCell:
    season_index: int
    season_id: str
    seed: int
    summary: QuickSimSeasonSummary
    summary_sha256: str

    def __post_init__(self) -> None:
        if self.season_index < 0 or not self.season_id.strip():
            raise ValueError("quick-sim batch cell identity is invalid")
        if self.summary.season_id != self.season_id:
            raise ValueError("quick-sim batch cell summary identity differs")
        if self.summary_sha256 != _summary_digest(self.summary):
            raise ValueError("quick-sim batch cell summary hash differs")


@dataclass(frozen=True, slots=True)
class QuickSimBatchResult:
    spec: QuickSimBatchSpec
    cells: tuple[QuickSimBatchCell, ...]
    complete: bool
    batch_sha256: str

    def __post_init__(self) -> None:
        if tuple(item.season_index for item in self.cells) != tuple(range(len(self.cells))):
            raise ValueError("quick-sim batch cells must be contiguous")
        if len(self.cells) > self.spec.seasons:
            raise ValueError("quick-sim batch has too many cells")
        if any(item.summary.team_count != self.spec.team_count for item in self.cells):
            raise ValueError("quick-sim batch cell team count differs")
        if self.complete != (len(self.cells) == self.spec.seasons):
            raise ValueError("quick-sim batch completion flag differs")
        if self.batch_sha256 != _batch_digest(self.spec, self.cells):
            raise ValueError("quick-sim batch hash differs")


def run_quick_sim_batch(
    spec: QuickSimBatchSpec,
    executor: QuickSimSeasonExecutor,
    *,
    previous: QuickSimBatchResult | None = None,
    maximum_new_seasons: int | None = None,
) -> QuickSimBatchResult:
    if maximum_new_seasons is not None and (
        not isinstance(maximum_new_seasons, int)
        or isinstance(maximum_new_seasons, bool)
        or maximum_new_seasons < 1
    ):
        raise QuickSimBatchError("maximum_new_seasons must be a positive integer")
    if previous is not None and previous.spec != spec:
        raise QuickSimBatchError("previous quick-sim batch spec differs")
    cells = list(previous.cells if previous is not None else ())
    remaining = spec.seasons - len(cells)
    run_count = remaining if maximum_new_seasons is None else min(remaining, maximum_new_seasons)
    for season_index in range(len(cells), len(cells) + run_count):
        season_id = f"{spec.batch_id}:season-{season_index + 1:04d}"
        seed = derive_seed(
            spec.master_seed,
            QUICK_SIM_BATCH_VERSION,
            spec.batch_id,
            season_index,
        )
        summary = executor(season_id, seed)
        if summary.season_id != season_id or summary.team_count != spec.team_count:
            raise QuickSimBatchError("quick-sim executor returned a mismatched summary")
        cells.append(
            QuickSimBatchCell(
                season_index,
                season_id,
                seed,
                summary,
                _summary_digest(summary),
            )
        )
    canonical_cells = tuple(cells)
    return QuickSimBatchResult(
        spec,
        canonical_cells,
        len(canonical_cells) == spec.seasons,
        _batch_digest(spec, canonical_cells),
    )


def append_precomputed_quick_sim_summaries(
    spec: QuickSimBatchSpec,
    summaries: tuple[QuickSimSeasonSummary, ...],
    *,
    previous: QuickSimBatchResult | None = None,
) -> QuickSimBatchResult:
    """Canonically append independently computed contiguous season summaries."""
    if previous is not None and previous.spec != spec:
        raise QuickSimBatchError("precomputed quick-sim batch spec differs")
    cells = list(previous.cells if previous is not None else ())
    if len(cells) + len(summaries) > spec.seasons:
        raise QuickSimBatchError("precomputed quick-sim batch has too many summaries")
    for offset, summary in enumerate(summaries):
        season_index = len(cells)
        expected_id = f"{spec.batch_id}:season-{season_index + 1:04d}"
        seed = derive_seed(
            spec.master_seed,
            QUICK_SIM_BATCH_VERSION,
            spec.batch_id,
            season_index,
        )
        if summary.season_id != expected_id or summary.team_count != spec.team_count:
            raise QuickSimBatchError(
                f"precomputed quick-sim summary differs at wave offset {offset}"
            )
        cells.append(
            QuickSimBatchCell(
                season_index,
                expected_id,
                seed,
                summary,
                _summary_digest(summary),
            )
        )
    canonical_cells = tuple(cells)
    return QuickSimBatchResult(
        spec,
        canonical_cells,
        len(canonical_cells) == spec.seasons,
        _batch_digest(spec, canonical_cells),
    )


def quick_sim_batch_to_json(result: QuickSimBatchResult) -> str:
    return json.dumps(
        {
            "version": result.spec.version,
            "spec": {
                "batch_id": result.spec.batch_id,
                "master_seed": result.spec.master_seed,
                "seasons": result.spec.seasons,
                "team_count": result.spec.team_count,
            },
            "cells": [
                {
                    "season_index": item.season_index,
                    "season_id": item.season_id,
                    "seed": item.seed,
                    "summary": _summary_to_dict(item.summary),
                    "summary_sha256": item.summary_sha256,
                }
                for item in result.cells
            ],
            "complete": result.complete,
            "batch_sha256": result.batch_sha256,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def quick_sim_batch_from_json(payload: str) -> QuickSimBatchResult:
    try:
        raw = json.loads(payload)
    except json.JSONDecodeError as error:
        raise QuickSimBatchError("invalid quick-sim batch JSON") from error
    if not isinstance(raw, dict) or set(raw) != {
        "version",
        "spec",
        "cells",
        "complete",
        "batch_sha256",
    }:
        raise QuickSimBatchError("invalid quick-sim batch keys")
    spec_raw = raw["spec"]
    cells_raw = raw["cells"]
    if not isinstance(spec_raw, dict) or set(spec_raw) != {
        "batch_id",
        "master_seed",
        "seasons",
        "team_count",
    }:
        raise QuickSimBatchError("invalid quick-sim batch spec")
    if not isinstance(cells_raw, list):
        raise QuickSimBatchError("quick-sim batch cells must be a list")
    complete = raw["complete"]
    if not isinstance(complete, bool):
        raise QuickSimBatchError("quick-sim batch complete must be a boolean")
    spec = QuickSimBatchSpec(
        _require_string(spec_raw["batch_id"], "batch_id"),
        _require_int(spec_raw["master_seed"], "master_seed"),
        _require_int(spec_raw["seasons"], "seasons"),
        _require_int(spec_raw["team_count"], "team_count"),
        _require_string(raw["version"], "version"),
    )
    cells = []
    for item in cells_raw:
        if not isinstance(item, dict) or set(item) != {
            "season_index",
            "season_id",
            "seed",
            "summary",
            "summary_sha256",
        }:
            raise QuickSimBatchError("invalid quick-sim batch cell")
        summary_raw = item["summary"]
        if not isinstance(summary_raw, dict):
            raise QuickSimBatchError("invalid quick-sim batch summary")
        cells.append(
            QuickSimBatchCell(
                _require_int(item["season_index"], "season_index"),
                _require_string(item["season_id"], "season_id"),
                _require_int(item["seed"], "seed"),
                _summary_from_dict(summary_raw),
                _require_string(item["summary_sha256"], "summary_sha256"),
            )
        )
    return QuickSimBatchResult(
        spec,
        tuple(cells),
        complete,
        _require_string(raw["batch_sha256"], "batch_sha256"),
    )


def _summary_to_dict(summary: QuickSimSeasonSummary) -> dict[str, object]:
    return {
        "season_id": summary.season_id,
        "team_count": summary.team_count,
        "games": summary.games,
        "win_rate_stddev": summary.win_rate_stddev,
        "pace_possessions_per_team": summary.pace_possessions_per_team,
        "offensive_rating": summary.offensive_rating,
        "point_differential_stddev": summary.point_differential_stddev,
        "playoff_upset_rate": summary.playoff_upset_rate,
        "champion_seed": summary.champion_seed,
    }


def _summary_from_dict(raw: dict[object, object]) -> QuickSimSeasonSummary:
    if set(raw) != {
        "season_id",
        "team_count",
        "games",
        "win_rate_stddev",
        "pace_possessions_per_team",
        "offensive_rating",
        "point_differential_stddev",
        "playoff_upset_rate",
        "champion_seed",
    }:
        raise QuickSimBatchError("invalid quick-sim summary keys")
    upset = raw["playoff_upset_rate"]
    champion = raw["champion_seed"]
    return QuickSimSeasonSummary(
        _require_string(raw["season_id"], "season_id"),
        _require_int(raw["team_count"], "team_count"),
        _require_int(raw["games"], "games"),
        _require_number(raw["win_rate_stddev"], "win_rate_stddev"),
        _require_number(raw["pace_possessions_per_team"], "pace_possessions_per_team"),
        _require_number(raw["offensive_rating"], "offensive_rating"),
        _require_number(raw["point_differential_stddev"], "point_differential_stddev"),
        None if upset is None else _require_number(upset, "playoff_upset_rate"),
        None if champion is None else _require_int(champion, "champion_seed"),
    )


def _require_string(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise QuickSimBatchError(f"quick-sim batch {field} must be a string")
    return value


def _require_int(value: object, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise QuickSimBatchError(f"quick-sim batch {field} must be an integer")
    return value


def _require_number(value: object, field: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise QuickSimBatchError(f"quick-sim batch {field} must be numeric")
    return float(value)


def _summary_digest(summary: QuickSimSeasonSummary) -> str:
    payload = json.dumps(
        _summary_to_dict(summary),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _batch_digest(
    spec: QuickSimBatchSpec,
    cells: tuple[QuickSimBatchCell, ...],
) -> str:
    payload = json.dumps(
        {
            "version": spec.version,
            "batch_id": spec.batch_id,
            "master_seed": spec.master_seed,
            "seasons": spec.seasons,
            "team_count": spec.team_count,
            "cell_hashes": [item.summary_sha256 for item in cells],
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()

"""White-box aggregate NBA season simulation for fast distribution studies."""

from __future__ import annotations

import hashlib
import json
import math
import random
from dataclasses import dataclass, field
from pathlib import Path
from statistics import pstdev
from typing import Any, cast

from courtsim.analysis.nba_team_strength import (
    load_nba_team_strength_alignment,
    load_nba_team_strength_offsets,
)
from courtsim.analysis.quick_sim_artifacts import run_quick_sim_checkpoint
from courtsim.analysis.quick_sim_batch import QuickSimBatchSpec
from courtsim.analysis.quick_sim_comparison import QuickSimSeasonSummary
from courtsim.artifacts import sha256_file, write_json
from courtsim.nba_league import (
    NBAConferenceAlignment,
    NBAPostseasonResult,
    NBASeriesResult,
    PlayInGame,
    generate_nba_schedule,
    nba_series_home_court_order,
    resolve_nba_playoffs,
    resolve_play_in,
)
from courtsim.playoffs import PlayoffConfig, PlayoffSeed
from courtsim.randomness import derive_seed

NBA_AGGREGATE_QUICK_SIM_VERSION = "nba-aggregate-quick-sim-v1"
NBA_AGGREGATE_PARAMETERS_VERSION = "nba-aggregate-quick-sim-parameters-v1"
NBA_AGGREGATE_RUNNER_VERSION = "nba-aggregate-quick-sim-runner-v1"


class NbaAggregateQuickSimError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class NBAAggregateQuickSimParameters:
    base_pace: float
    base_offensive_rating: float
    team_score_standard_deviation: float
    pace_standard_deviation: float
    home_advantage_points: float
    rating_offset_margin_points: float
    version: str = NBA_AGGREGATE_PARAMETERS_VERSION

    def __post_init__(self) -> None:
        values = (
            self.base_pace,
            self.base_offensive_rating,
            self.team_score_standard_deviation,
            self.pace_standard_deviation,
            self.home_advantage_points,
            self.rating_offset_margin_points,
        )
        if any(not math.isfinite(value) or value < 0 for value in values):
            raise ValueError("aggregate quick-sim parameters must be finite and non-negative")
        if self.base_pace < 1 or self.base_offensive_rating < 1:
            raise ValueError("aggregate quick-sim base pace and rating must be positive")
        if self.version != NBA_AGGREGATE_PARAMETERS_VERSION:
            raise ValueError("unsupported aggregate quick-sim parameter version")


@dataclass(frozen=True, slots=True)
class NBAAggregateStanding:
    team_id: str
    wins: int
    losses: int
    point_differential: int


@dataclass(frozen=True, slots=True)
class NBAAggregateQuickSimExecution:
    season_id: str
    standings: tuple[NBAAggregateStanding, ...]
    postseason: NBAPostseasonResult
    summary: QuickSimSeasonSummary
    version: str = NBA_AGGREGATE_QUICK_SIM_VERSION


@dataclass(frozen=True, slots=True)
class NBAAggregateQuickSimExecutor:
    parameters: NBAAggregateQuickSimParameters
    alignment: NBAConferenceAlignment
    team_offsets: tuple[tuple[str, int], ...]
    playoff_config: PlayoffConfig = field(default_factory=PlayoffConfig)
    version: str = NBA_AGGREGATE_QUICK_SIM_VERSION

    def __post_init__(self) -> None:
        team_ids = tuple(team_id for team_id, _offset in self.team_offsets)
        if team_ids != tuple(sorted(set(team_ids))) or len(team_ids) != 30:
            raise ValueError("aggregate quick-sim requires 30 canonical team offsets")
        if set((*self.alignment.east_team_ids, *self.alignment.west_team_ids)) != set(team_ids):
            raise ValueError("aggregate quick-sim alignment differs from team offsets")
        if self.playoff_config.best_of != 7:
            raise ValueError("aggregate quick-sim requires best-of-seven playoffs")
        if self.version != NBA_AGGREGATE_QUICK_SIM_VERSION:
            raise ValueError("unsupported aggregate quick-sim executor version")

    def __call__(self, season_id: str, seed: int) -> QuickSimSeasonSummary:
        return self.execute(season_id, seed).summary

    def execute(self, season_id: str, seed: int) -> NBAAggregateQuickSimExecution:
        if not season_id.strip():
            raise NbaAggregateQuickSimError("aggregate quick-sim season id must not be blank")
        offsets = dict(self.team_offsets)
        schedule = generate_nba_schedule(tuple(offsets), alignment=self.alignment)
        records = {
            team_id: {"wins": 0, "losses": 0, "point_differential": 0} for team_id in offsets
        }
        total_points = 0
        total_team_possessions = 0.0
        home_wins = 0
        for game in schedule.games:
            home_score, away_score, pace = self._game(
                season_id,
                seed,
                ("regular", game.game_id),
                game.home_team_id,
                game.away_team_id,
                offsets,
            )
            total_points += home_score + away_score
            total_team_possessions += 2 * pace
            home_wins += int(home_score > away_score)
            home = records[game.home_team_id]
            away = records[game.away_team_id]
            home["wins" if home_score > away_score else "losses"] += 1
            away["wins" if away_score > home_score else "losses"] += 1
            home["point_differential"] += home_score - away_score
            away["point_differential"] += away_score - home_score
        standings = tuple(
            NBAAggregateStanding(
                team_id,
                item["wins"],
                item["losses"],
                item["point_differential"],
            )
            for team_id, item in sorted(records.items())
        )
        east_regular = self._conference_seeds(standings, self.alignment.east_team_ids, 10)
        west_regular = self._conference_seeds(standings, self.alignment.west_team_ids, 10)
        east = self._play_in("east", east_regular, season_id, seed, offsets)
        west = self._play_in("west", west_regular, season_id, seed, offsets)
        postseason = self._postseason(east, west, standings, season_id, seed, offsets)
        seed_by_team = {
            item.team_id: item.seed for item in (*postseason.east_seeds, *postseason.west_seeds)
        }
        upsets = sum(
            seed_by_team[item.winner_team_id]
            > min(seed_by_team[item.first_team_id], seed_by_team[item.second_team_id])
            for item in postseason.series
        )
        win_rates = tuple(item.wins / 82 for item in standings)
        differentials = tuple(item.point_differential / 82 for item in standings)
        rank_order = tuple(
            item.team_id
            for item in sorted(
                standings,
                key=lambda item: (-item.wins, -item.point_differential, item.team_id),
            )
        )
        summary = QuickSimSeasonSummary(
            season_id,
            30,
            len(schedule.games),
            pstdev(win_rates),
            total_team_possessions / (2 * len(schedule.games)),
            total_points * 100 / total_team_possessions,
            pstdev(differentials),
            upsets / len(postseason.series),
            seed_by_team[postseason.champion_team_id],
            rank_order,
            home_wins / len(schedule.games),
        )
        return NBAAggregateQuickSimExecution(season_id, standings, postseason, summary)

    def _game(
        self,
        season_id: str,
        seed: int,
        address: tuple[object, ...],
        home_team_id: str,
        away_team_id: str,
        offsets: dict[str, int],
    ) -> tuple[int, int, float]:
        frame = random.Random(
            derive_seed(seed, NBA_AGGREGATE_QUICK_SIM_VERSION, season_id, *address)
        )
        pace = max(
            1.0, frame.gauss(self.parameters.base_pace, self.parameters.pace_standard_deviation)
        )
        expected_total = 2 * pace * self.parameters.base_offensive_rating / 100
        paired_deviation = math.sqrt(2) * self.parameters.team_score_standard_deviation
        total = max(2.0, frame.gauss(expected_total, paired_deviation))
        expected_margin = (
            self.parameters.home_advantage_points
            + (offsets[home_team_id] - offsets[away_team_id])
            * self.parameters.rating_offset_margin_points
        )
        margin = frame.gauss(expected_margin, paired_deviation)
        home_score = max(1, round((total + margin) / 2))
        away_score = max(1, round((total - margin) / 2))
        if home_score == away_score:
            if frame.random() < 0.5:
                home_score += 1
            else:
                away_score += 1
        return home_score, away_score, pace

    def _conference_seeds(
        self,
        standings: tuple[NBAAggregateStanding, ...],
        conference_team_ids: tuple[str, ...],
        count: int,
    ) -> tuple[PlayoffSeed, ...]:
        by_team = {item.team_id: item for item in standings}
        ordered = sorted(
            conference_team_ids,
            key=lambda team_id: (
                -by_team[team_id].wins,
                -by_team[team_id].point_differential,
                team_id,
            ),
        )
        return tuple(PlayoffSeed(seed, team_id) for seed, team_id in enumerate(ordered[:count], 1))

    def _play_in(
        self,
        conference: str,
        seeds: tuple[PlayoffSeed, ...],
        season_id: str,
        seed: int,
        offsets: dict[str, int],
    ) -> tuple[PlayoffSeed, ...]:
        by_seed = {item.seed: item.team_id for item in seeds}

        def play(number: int, home: str, away: str) -> PlayInGame:
            home_score, away_score, _pace = self._game(
                season_id,
                seed,
                ("play-in", conference, number),
                home,
                away,
                offsets,
            )
            return PlayInGame(number, home, away, home_score, away_score)

        first = play(1, by_seed[7], by_seed[8])
        second = play(2, by_seed[9], by_seed[10])
        third = play(3, first.loser_team_id, second.winner_team_id)
        return resolve_play_in(
            conference=conference,
            seeds=seeds,
            games=(first, second, third),
        ).playoff_seeds

    def _postseason(
        self,
        east: tuple[PlayoffSeed, ...],
        west: tuple[PlayoffSeed, ...],
        standings: tuple[NBAAggregateStanding, ...],
        season_id: str,
        seed: int,
        offsets: dict[str, int],
    ) -> NBAPostseasonResult:
        seed_by_team = {item.team_id: item.seed for item in (*east, *west)}
        regular_season_records = {
            item.team_id: (item.wins, item.point_differential) for item in standings
        }
        ledger: list[NBASeriesResult] = []

        def series(
            conference: str,
            round_number: int,
            series_index: int,
            first: str,
            second: str,
        ) -> str:
            first_wins = 0
            second_wins = 0
            higher, lower = nba_series_home_court_order(
                first,
                second,
                conference=conference,
                seed_by_team=seed_by_team,
                regular_season_records=regular_season_records,
            )
            game_number = 0
            while max(first_wins, second_wins) < 4:
                game_number += 1
                home = higher if self.playoff_config.higher_seed_home[game_number - 1] else lower
                away = lower if home == higher else higher
                home_score, away_score, _pace = self._game(
                    season_id,
                    seed,
                    ("playoffs", conference, round_number, series_index, game_number),
                    home,
                    away,
                    offsets,
                )
                winner = home if home_score > away_score else away
                first_wins += int(winner == first)
                second_wins += int(winner == second)
            result = NBASeriesResult(
                round_number,
                series_index,
                conference,
                first,
                second,
                first_wins,
                second_wins,
            )
            ledger.append(result)
            return result.winner_team_id

        def round_one(conference: str, seeds: tuple[PlayoffSeed, ...], start: int) -> list[str]:
            teams = {item.seed: item.team_id for item in seeds}
            pairs = ((1, 8), (4, 5), (2, 7), (3, 6))
            return [
                series(conference, 1, start + index, teams[first], teams[second])
                for index, (first, second) in enumerate(pairs)
            ]

        east_first = round_one("east", east, 1)
        west_first = round_one("west", west, 5)
        east_second = [
            series("east", 2, 1, east_first[0], east_first[1]),
            series("east", 2, 2, east_first[2], east_first[3]),
        ]
        west_second = [
            series("west", 2, 1, west_first[0], west_first[1]),
            series("west", 2, 2, west_first[2], west_first[3]),
        ]
        east_champion = series("east", 3, 1, east_second[0], east_second[1])
        west_champion = series("west", 3, 1, west_second[0], west_second[1])
        series("nba", 4, 1, east_champion, west_champion)
        return resolve_nba_playoffs(
            east_seeds=east,
            west_seeds=west,
            series=tuple(ledger),
        )


def load_nba_aggregate_quick_sim_parameters(
    parameter_path: str | Path,
) -> NBAAggregateQuickSimParameters:
    path = Path(parameter_path).resolve()
    root = _load_object(path, "aggregate quick-sim parameters")
    expected = {
        "version",
        "source",
        "base_pace",
        "base_offensive_rating",
        "team_score_standard_deviation",
        "pace_standard_deviation",
        "home_advantage_points",
        "rating_offset_margin_points",
        "methodology",
    }
    if set(root) != expected or root.get("version") != NBA_AGGREGATE_PARAMETERS_VERSION:
        raise NbaAggregateQuickSimError("aggregate quick-sim parameter schema differs")
    source = root["source"]
    if not isinstance(source, dict):
        raise NbaAggregateQuickSimError("aggregate quick-sim source is invalid")
    source_path = (path.parent / _text(source.get("path"), "source.path")).resolve()
    expected_hash = _sha256(source.get("sha256"), "source.sha256")
    if not source_path.is_file() or sha256_file(source_path) != expected_hash:
        raise NbaAggregateQuickSimError("aggregate quick-sim source is unverified")
    baseline = _load_object(source_path, "aggregate quick-sim baseline")
    pinned = {
        "base_pace": baseline.get("mean_team_possessions"),
        "base_offensive_rating": baseline.get("points_per_100_possessions"),
        "team_score_standard_deviation": baseline.get("team_score_stddev"),
    }
    if any(root[field] != value for field, value in pinned.items()):
        raise NbaAggregateQuickSimError("aggregate quick-sim pinned baseline metrics differ")
    return NBAAggregateQuickSimParameters(
        _number(root["base_pace"], "base_pace"),
        _number(root["base_offensive_rating"], "base_offensive_rating"),
        _number(
            root["team_score_standard_deviation"],
            "team_score_standard_deviation",
        ),
        _number(root["pace_standard_deviation"], "pace_standard_deviation"),
        _number(root["home_advantage_points"], "home_advantage_points"),
        _number(root["rating_offset_margin_points"], "rating_offset_margin_points"),
    )


def build_nba_aggregate_quick_sim_executor(
    parameter_path: str | Path,
    strength_path: str | Path,
) -> NBAAggregateQuickSimExecutor:
    return NBAAggregateQuickSimExecutor(
        load_nba_aggregate_quick_sim_parameters(parameter_path),
        load_nba_team_strength_alignment(strength_path),
        load_nba_team_strength_offsets(strength_path),
    )


def run_nba_aggregate_quick_sim_batch(
    *,
    parameter_path: str | Path,
    strength_path: str | Path,
    checkpoint_path: str | Path,
    manifest_path: str | Path,
    batch_id: str,
    master_seed: int,
    seasons: int,
    maximum_new_seasons: int | None,
) -> dict[str, object]:
    """Run or resume a source-pinned aggregate batch with a full input receipt."""
    parameter_file = Path(parameter_path).resolve()
    strength_file = Path(strength_path).resolve()
    checkpoint_file = Path(checkpoint_path).resolve()
    manifest_file = Path(manifest_path).resolve()
    inputs = {
        "aggregate_parameters": _file_receipt(parameter_file),
        "team_strength": _file_receipt(strength_file),
    }
    configuration: dict[str, object] = {
        "runner_version": NBA_AGGREGATE_RUNNER_VERSION,
        "executor_version": NBA_AGGREGATE_QUICK_SIM_VERSION,
        "batch": {
            "batch_id": batch_id,
            "master_seed": master_seed,
            "seasons": seasons,
            "team_count": 30,
        },
        "game_config": {
            "mode": "aggregate",
            "parameters_version": NBA_AGGREGATE_PARAMETERS_VERSION,
        },
        "season_config": "aggregate-standings-play-in-playoffs-v1",
        "trace_mode": "summary-only",
        "inputs": inputs,
    }
    configuration_sha256 = _digest(configuration)
    _verify_run_resume(manifest_file, checkpoint_file, configuration_sha256)
    result, receipt = run_quick_sim_checkpoint(
        QuickSimBatchSpec(batch_id, master_seed, seasons),
        build_nba_aggregate_quick_sim_executor(parameter_file, strength_file),
        checkpoint_file,
        maximum_new_seasons=maximum_new_seasons,
    )
    payload: dict[str, object] = {
        "version": NBA_AGGREGATE_RUNNER_VERSION,
        "configuration_sha256": configuration_sha256,
        "configuration": configuration,
        "checkpoint": {
            "path": checkpoint_file.name,
            "sha256": receipt.file_sha256,
            "batch_sha256": result.batch_sha256,
            "completed_seasons": len(result.cells),
            "complete": result.complete,
        },
    }
    write_json(manifest_file, payload)
    return payload


def _file_receipt(path: Path) -> dict[str, object]:
    if not path.is_file():
        raise NbaAggregateQuickSimError(f"aggregate quick-sim input is missing: {path}")
    return {"filename": path.name, "sha256": sha256_file(path), "bytes": path.stat().st_size}


def _verify_run_resume(manifest: Path, checkpoint: Path, configuration_sha256: str) -> None:
    if not manifest.exists():
        if checkpoint.exists():
            raise NbaAggregateQuickSimError("aggregate checkpoint exists without its manifest")
        return
    root = _load_object(manifest, "aggregate quick-sim run manifest")
    checkpoint_record = root.get("checkpoint")
    if (
        root.get("version") != NBA_AGGREGATE_RUNNER_VERSION
        or root.get("configuration_sha256") != configuration_sha256
        or not isinstance(checkpoint_record, dict)
        or not checkpoint.is_file()
        or checkpoint_record.get("sha256") != sha256_file(checkpoint)
    ):
        raise NbaAggregateQuickSimError("aggregate quick-sim resume contract differs")


def _digest(value: object) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _load_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise NbaAggregateQuickSimError(f"cannot read {label}: {path}") from error
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise NbaAggregateQuickSimError(f"{label} must be an object")
    return cast(dict[str, Any], value)


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise NbaAggregateQuickSimError(f"{field} must be non-empty text")
    return value.strip()


def _sha256(value: object, field: str) -> str:
    text = _text(value, field)
    if len(text) != 64 or any(character not in "0123456789abcdef" for character in text):
        raise NbaAggregateQuickSimError(f"{field} is invalid")
    return text


def _number(value: object, field: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
        raise NbaAggregateQuickSimError(f"{field} must be finite numeric data")
    return float(value)

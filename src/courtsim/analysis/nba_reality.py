"""Source-pinned multi-season NBA standings and playoff reality import."""

from __future__ import annotations

import importlib
import json
import math
from pathlib import Path
from statistics import pstdev
from typing import Any, cast

from courtsim.analysis.quick_sim_comparison import (
    QuickSimSeasonSummary,
    build_quick_sim_reference,
    quick_sim_reference_to_json,
)
from courtsim.artifacts import sha256_file

NBA_REALITY_VERSION = "nba-reality-multiseason-v1"
_FORMAL_GUARDBANDS = {
    "win-rate-stddev": 0.02,
    "pace-possessions-per-team": 3.0,
    "offensive-rating": 5.0,
    "point-differential-stddev": 1.5,
    "playoff-upset-rate": 0.15,
    "champion-seed-mean": 2.0,
}
_EAST_TEAM_IDS = frozenset({1, 2, 4, 5, 8, 11, 14, 15, 17, 18, 19, 20, 27, 28, 30})
_TEAM_IDS = frozenset(range(1, 31))
_COLUMNS = (
    "game_id",
    "season",
    "season_type",
    "game_date",
    "team_id",
    "team_abbreviation",
    "team_score",
    "team_winner",
    "opponent_team_id",
    "opponent_team_score",
    "field_goals_attempted",
    "free_throws_attempted",
    "offensive_rebounds",
    "turnovers",
)


class NbaRealityError(ValueError):
    pass


def build_nba_reality_payload(
    manifest_path: str | Path,
    cache_directory: str | Path,
) -> tuple[dict[str, object], dict[str, object]]:
    """Read projected Parquet columns and build reality plus quick-sim reference artifacts."""
    manifest_file = Path(manifest_path).resolve()
    manifest = _load_object(manifest_file, "NBA reality manifest")
    _validate_manifest(manifest)
    try:
        parquet = importlib.import_module("pyarrow.parquet")
    except ImportError as error:
        raise NbaRealityError(
            "NBA reality Parquet import requires '.\\tools.cmd bootstrap-data'"
        ) from error
    cache = Path(cache_directory).resolve()
    season_rows: list[dict[str, object]] = []
    summaries: list[QuickSimSeasonSummary] = []
    source_receipts = []
    for raw_resource in cast(list[object], manifest["resources"]):
        resource = _object(raw_resource, "NBA reality resource")
        filename = _text(resource["filename"], "filename")
        source = cache / filename
        expected_hash = _sha256(resource["sha256"], "resource sha256")
        if not source.is_file() or sha256_file(source) != expected_hash:
            raise NbaRealityError(f"NBA reality source is missing or unverified: {filename}")
        rows = parquet.read_table(source, columns=list(_COLUMNS)).to_pylist()
        excluded = _integer_tuple(resource["excluded_non_standings_game_ids"], "excluded ids")
        season, summary = _build_season(rows, excluded)
        season_rows.append(season)
        summaries.append(summary)
        source_receipts.append(
            {
                "season": season["season_id"],
                "filename": filename,
                "url": _text(resource["url"], "url"),
                "bytes": source.stat().st_size,
                "sha256": expected_hash,
                "excluded_non_standings_game_ids": list(excluded),
            }
        )
    season_ids = tuple(_text(item["season_id"], "season_id") for item in season_rows)
    if season_ids != tuple(sorted(season_ids)):
        raise NbaRealityError("NBA reality resources must use season order")
    reference = build_quick_sim_reference(
        tuple(summaries),
        reference_id=_text(manifest["reference_id"], "reference_id"),
        source_label=(
            f"{_text(manifest['source_label'], 'source_label')}; "
            "formal ranges include frozen anti-overfit guardbands"
        ),
        game_version="real-nba-team-box-guardband-v1",
        roster_date=_text(manifest["frozen_at"], "frozen_at"),
    )
    payload = {
        "schema_version": 1,
        "version": NBA_REALITY_VERSION,
        "dataset_id": _text(manifest["dataset_id"], "dataset_id"),
        "frozen_at": _text(manifest["frozen_at"], "frozen_at"),
        "methodology": {
            "regular_season_type": 2,
            "playoff_season_type": 3,
            "team_ids": list(range(1, 31)),
            "standings_games_per_team": 82,
            "possessions_estimate": "FGA + 0.44*FTA - OREB + TOV",
            "series_grouping": "unordered team pair",
            "conference_seed_tiebreak": "wins, point differential, team id",
            "formal_reference_guardbands": _FORMAL_GUARDBANDS,
        },
        "sources": source_receipts,
        "seasons": season_rows,
    }
    reference_payload = cast(dict[str, object], json.loads(quick_sim_reference_to_json(reference)))
    _apply_formal_guardbands(reference_payload)
    return payload, reference_payload


def _apply_formal_guardbands(reference: dict[str, object]) -> None:
    metrics = cast(list[dict[str, object]], reference["metrics"])
    for target in metrics:
        metric = _text(target["metric"], "metric")
        margin = _FORMAL_GUARDBANDS[metric]
        minimum = _number(target["minimum"], "minimum")
        maximum = _number(target["maximum"], "maximum")
        target["minimum"] = max(0.0, minimum - margin)
        target["maximum"] = maximum + margin
        if metric == "playoff-upset-rate":
            target["maximum"] = min(1.0, cast(float, target["maximum"]))
        elif metric == "champion-seed-mean":
            target["minimum"] = max(1.0, cast(float, target["minimum"]))


def _build_season(
    rows: list[dict[str, object]], excluded_game_ids: tuple[int, ...]
) -> tuple[dict[str, object], QuickSimSeasonSummary]:
    seasons = {_integer(item.get("season"), "season") for item in rows}
    if len(seasons) != 1:
        raise NbaRealityError("NBA reality resource must contain one season")
    season_end = seasons.pop()
    season_id = f"{season_end - 1}-{str(season_end)[-2:]}"
    regular = [
        item
        for item in rows
        if _integer(item.get("season_type"), "season_type") == 2
        and _integer(item.get("team_id"), "team_id") in _TEAM_IDS
        and _integer(item.get("game_id"), "game_id") not in excluded_game_ids
    ]
    teams: dict[int, dict[str, object]] = {}
    for row in regular:
        team_id = _integer(row["team_id"], "team_id")
        team = teams.setdefault(
            team_id,
            {
                "team_id": team_id,
                "team_abbreviation": _text(row["team_abbreviation"], "team_abbreviation"),
                "wins": 0,
                "losses": 0,
                "points": 0,
                "point_differential": 0,
                "estimated_possessions": 0.0,
            },
        )
        regular_winner = _boolean(row["team_winner"], "team_winner")
        team["wins"] = cast(int, team["wins"]) + int(regular_winner)
        team["losses"] = cast(int, team["losses"]) + int(not regular_winner)
        score = _integer(row["team_score"], "team_score")
        opponent_score = _integer(row["opponent_team_score"], "opponent_team_score")
        team["points"] = cast(int, team["points"]) + score
        team["point_differential"] = cast(int, team["point_differential"]) + score - opponent_score
        possessions = (
            _number(row["field_goals_attempted"], "field_goals_attempted")
            + 0.44 * _number(row["free_throws_attempted"], "free_throws_attempted")
            - _number(row["offensive_rebounds"], "offensive_rebounds")
            + _number(row["turnovers"], "turnovers")
        )
        team["estimated_possessions"] = cast(float, team["estimated_possessions"]) + possessions
    if set(teams) != _TEAM_IDS or any(
        cast(int, item["wins"]) + cast(int, item["losses"]) != 82 for item in teams.values()
    ):
        raise NbaRealityError(f"NBA reality {season_id} standings are not 30 x 82")
    for conference in (_EAST_TEAM_IDS, _TEAM_IDS - _EAST_TEAM_IDS):
        ordered = sorted(
            conference,
            key=lambda team_id: (
                -cast(int, teams[team_id]["wins"]),
                -cast(int, teams[team_id]["point_differential"]),
                team_id,
            ),
        )
        for seed, team_id in enumerate(ordered, start=1):
            teams[team_id]["conference_seed"] = seed
    playoffs = [
        item
        for item in rows
        if _integer(item.get("season_type"), "season_type") == 3
        and _integer(item.get("team_id"), "team_id") in _TEAM_IDS
    ]
    series_by_pair: dict[tuple[int, int], dict[str, object]] = {}
    for row in playoffs:
        team_id = _integer(row["team_id"], "team_id")
        opponent_id = _integer(row["opponent_team_id"], "opponent_team_id")
        pair = (min(team_id, opponent_id), max(team_id, opponent_id))
        series = series_by_pair.setdefault(pair, {"wins": {}, "last_game_date": ""})
        wins = cast(dict[int, int], series["wins"])
        wins[team_id] = wins.get(team_id, 0) + int(_boolean(row["team_winner"], "team_winner"))
        game_date = str(row["game_date"])
        series["last_game_date"] = max(cast(str, series["last_game_date"]), game_date)
    if len(series_by_pair) != 15:
        raise NbaRealityError(f"NBA reality {season_id} must contain 15 playoff series")
    series_rows = []
    for pair, raw_series in series_by_pair.items():
        wins = cast(dict[int, int], raw_series["wins"])
        series_winner = max(wins, key=wins.__getitem__)
        loser = pair[0] if pair[1] == series_winner else pair[1]
        if wins[series_winner] != 4:
            raise NbaRealityError(f"NBA reality {season_id} series lacks four wins")
        series_rows.append(
            {
                "first_team_id": pair[0],
                "second_team_id": pair[1],
                "winner_team_id": series_winner,
                "winner_seed": teams[series_winner]["conference_seed"],
                "loser_seed": teams[loser]["conference_seed"],
                "winner_wins": wins[series_winner],
                "loser_wins": wins.get(loser, 0),
                "last_game_date": raw_series["last_game_date"],
                "upset": cast(int, teams[series_winner]["conference_seed"])
                > cast(int, teams[loser]["conference_seed"]),
            }
        )
    series_rows.sort(
        key=lambda item: (
            cast(str, item["last_game_date"]),
            cast(int, item["first_team_id"]),
        )
    )
    champion_id = cast(int, series_rows[-1]["winner_team_id"])
    total_points = sum(cast(int, item["points"]) for item in teams.values())
    total_possessions = math.fsum(
        cast(float, item["estimated_possessions"]) for item in teams.values()
    )
    win_rates = [cast(int, item["wins"]) / 82 for item in teams.values()]
    point_differentials = [cast(int, item["point_differential"]) / 82 for item in teams.values()]
    upset_rate = sum(cast(bool, item["upset"]) for item in series_rows) / 15
    summary = QuickSimSeasonSummary(
        season_id,
        30,
        1230,
        pstdev(win_rates),
        total_possessions / len(regular),
        total_points * 100 / total_possessions,
        pstdev(point_differentials),
        upset_rate,
        cast(int, teams[champion_id]["conference_seed"]),
    )
    standings = []
    for _team_id, item in sorted(teams.items()):
        standings.append(
            {
                **item,
                "estimated_possessions": round(cast(float, item["estimated_possessions"]), 6),
            }
        )
    return (
        {
            "season_id": season_id,
            "regular_season_games": 1230,
            "standings": standings,
            "playoff_games": len(playoffs) // 2,
            "playoff_series": series_rows,
            "champion_team_id": champion_id,
            "metrics": {
                "win-rate-stddev": summary.win_rate_stddev,
                "pace-possessions-per-team": summary.pace_possessions_per_team,
                "offensive-rating": summary.offensive_rating,
                "point-differential-stddev": summary.point_differential_stddev,
                "playoff-upset-rate": summary.playoff_upset_rate,
                "champion-seed": summary.champion_seed,
            },
        },
        summary,
    )


def _validate_manifest(raw: dict[str, Any]) -> None:
    if (
        set(raw)
        != {
            "schema_version",
            "dataset_id",
            "reference_id",
            "source_label",
            "frozen_at",
            "resources",
        }
        or raw.get("schema_version") != 1
    ):
        raise NbaRealityError("NBA reality manifest schema differs")
    resources = raw["resources"]
    if not isinstance(resources, list) or len(resources) < 3:
        raise NbaRealityError("NBA reality requires at least three seasons")
    expected = {
        "filename",
        "url",
        "sha256",
        "excluded_non_standings_game_ids",
    }
    for item in resources:
        resource = _object(item, "NBA reality resource")
        if set(resource) != expected:
            raise NbaRealityError("NBA reality resource schema differs")
        _sha256(resource["sha256"], "resource sha256")
        _integer_tuple(resource["excluded_non_standings_game_ids"], "excluded ids")


def _load_object(path: Path, label: str) -> dict[str, Any]:
    try:
        raw: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise NbaRealityError(f"cannot read {label}: {path}") from error
    return _object(raw, label)


def _object(value: object, field: str) -> dict[str, Any]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise NbaRealityError(f"{field} must be an object")
    return cast(dict[str, Any], value)


def _integer(value: object, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise NbaRealityError(f"{field} must be an integer")
    return value


def _number(value: object, field: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
        raise NbaRealityError(f"{field} must be finite numeric data")
    return float(value)


def _boolean(value: object, field: str) -> bool:
    if not isinstance(value, bool):
        raise NbaRealityError(f"{field} must be a boolean")
    return value


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise NbaRealityError(f"{field} must be non-empty text")
    return value.strip()


def _sha256(value: object, field: str) -> str:
    text = _text(value, field)
    if len(text) != 64 or any(item not in "0123456789abcdef" for item in text):
        raise NbaRealityError(f"{field} is invalid")
    return text


def _integer_tuple(value: object, field: str) -> tuple[int, ...]:
    if not isinstance(value, list):
        raise NbaRealityError(f"{field} must be a list")
    result = tuple(_integer(item, field) for item in value)
    if result != tuple(sorted(set(result))):
        raise NbaRealityError(f"{field} must be ordered and unique")
    return result

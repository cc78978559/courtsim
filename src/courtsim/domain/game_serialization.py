"""Strict JSON representation for canonical regulation game results."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, NoReturn, cast

from courtsim.domain.enums import GameEndReason
from courtsim.domain.game import (
    GameClockConfig,
    GamePossessionRecord,
    GameResult,
    validate_game_result,
)
from courtsim.domain.serialization import (
    SerializationError,
    possession_result_from_dict,
    possession_result_to_dict,
)
from courtsim.stats.attribution import PlayerStatDelta, StatCode

SCHEMA_VERSION = 1


def _fail(message: str) -> NoReturn:
    raise SerializationError(message)


def _object(value: object, field: str) -> Mapping[str, Any]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        _fail(f"{field} must be an object")
    return cast(Mapping[str, Any], value)


def _exact(value: Mapping[str, Any], keys: set[str], field: str) -> None:
    if set(value) != keys:
        _fail(f"{field} keys must be exactly {sorted(keys)}")


def _int(value: Mapping[str, Any], key: str) -> int:
    item = value[key]
    if not isinstance(item, int) or isinstance(item, bool):
        _fail(f"{key} must be an integer")
    return item


def _string(value: Mapping[str, Any], key: str) -> str:
    item = value[key]
    if not isinstance(item, str) or not item:
        _fail(f"{key} must be a non-empty string")
    return item


def game_result_to_dict(result: GameResult) -> dict[str, object]:
    return {
        "schema_version": SCHEMA_VERSION,
        "home_team_id": result.home_team_id,
        "away_team_id": result.away_team_id,
        "possessions": [
            {
                "possession_index": item.possession_index,
                "period": item.period,
                "clock_start_seconds": item.clock_start_seconds,
                "clock_end_seconds": item.clock_end_seconds,
                "offense_team_id": item.offense_team_id,
                "defense_team_id": item.defense_team_id,
                "result": possession_result_to_dict(item.result),
            }
            for item in result.possessions
        ],
        "home_score": result.home_score,
        "away_score": result.away_score,
        "player_stats": [
            {
                "player_id": item.player_id,
                "stat": int(item.stat),
                "amount": item.amount,
            }
            for item in result.player_stats
        ],
        "end_reason": int(result.end_reason),
    }


def game_result_from_dict(value: object, config: GameClockConfig) -> GameResult:
    obj = _object(value, "game result")
    _exact(
        obj,
        {
            "schema_version",
            "home_team_id",
            "away_team_id",
            "possessions",
            "home_score",
            "away_score",
            "player_stats",
            "end_reason",
        },
        "game result",
    )
    if _int(obj, "schema_version") != SCHEMA_VERSION:
        _fail("unsupported schema_version")
    raw_possessions = obj["possessions"]
    if not isinstance(raw_possessions, list):
        _fail("possessions must be a list")
    possessions: list[GamePossessionRecord] = []
    possession_keys = {
        "possession_index",
        "period",
        "clock_start_seconds",
        "clock_end_seconds",
        "offense_team_id",
        "defense_team_id",
        "result",
    }
    for raw_possession in raw_possessions:
        possession = _object(raw_possession, "possession")
        _exact(possession, possession_keys, "possession")
        possessions.append(
            GamePossessionRecord(
                _int(possession, "possession_index"),
                _int(possession, "period"),
                _int(possession, "clock_start_seconds"),
                _int(possession, "clock_end_seconds"),
                _string(possession, "offense_team_id"),
                _string(possession, "defense_team_id"),
                possession_result_from_dict(possession["result"]),
            )
        )
    raw_stats = obj["player_stats"]
    if not isinstance(raw_stats, list):
        _fail("player_stats must be a list")
    stats: list[PlayerStatDelta] = []
    for raw_stat in raw_stats:
        stat = _object(raw_stat, "player stat")
        _exact(stat, {"player_id", "stat", "amount"}, "player stat")
        try:
            stat_code = StatCode(_int(stat, "stat"))
        except ValueError as error:
            raise SerializationError("invalid stat") from error
        stats.append(
            PlayerStatDelta(
                _int(stat, "player_id"),
                stat_code,
                _int(stat, "amount"),
            )
        )
    try:
        end_reason = GameEndReason(_int(obj, "end_reason"))
    except ValueError as error:
        raise SerializationError("invalid end_reason") from error
    result = GameResult(
        _string(obj, "home_team_id"),
        _string(obj, "away_team_id"),
        tuple(possessions),
        _int(obj, "home_score"),
        _int(obj, "away_score"),
        tuple(stats),
        end_reason,
    )
    try:
        validate_game_result(result, config)
    except ValueError as error:
        raise SerializationError(str(error)) from error
    return result


def game_result_to_json(result: GameResult) -> str:
    return json.dumps(
        game_result_to_dict(result),
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def game_result_from_json(payload: str, config: GameClockConfig) -> GameResult:
    try:
        value = json.loads(payload)
    except json.JSONDecodeError as error:
        raise SerializationError("invalid JSON") from error
    return game_result_from_dict(value, config)

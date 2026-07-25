"""Strict JSON representation for canonical game results."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, NoReturn, cast

from courtsim.domain.enums import GameEndReason, SubstitutionReason
from courtsim.domain.game import (
    GameClockConfig,
    GamePossessionRecord,
    GameResult,
    PlayerFatigueSnapshot,
    PlayerPlayingTime,
    SubstitutionRecord,
    validate_game_result,
)
from courtsim.domain.plans import Lineup
from courtsim.domain.serialization import (
    SerializationError,
    possession_result_from_dict,
    possession_result_to_dict,
)
from courtsim.stats.attribution import PlayerStatDelta, StatCode

SCHEMA_VERSION = 2


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


def _nullable_string(value: Mapping[str, Any], key: str) -> str | None:
    item = value[key]
    return None if item is None else _string(value, key)


def _lineup(value: object, field: str) -> Lineup:
    if (
        not isinstance(value, list)
        or len(value) != 5
        or any(not isinstance(item, int) or isinstance(item, bool) for item in value)
    ):
        _fail(f"{field} must be a five-player integer list")
    return cast(Lineup, tuple(value))


def _fatigue_snapshots(value: object, field: str) -> tuple[PlayerFatigueSnapshot, ...]:
    if not isinstance(value, list):
        _fail(f"{field} must be a list")
    snapshots: list[PlayerFatigueSnapshot] = []
    for raw in value:
        item = _object(raw, field)
        _exact(item, {"player_id", "fatigue"}, field)
        snapshots.append(PlayerFatigueSnapshot(_int(item, "player_id"), _int(item, "fatigue")))
    return tuple(snapshots)


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
                "offense_lineup": (
                    list(item.offense_lineup) if item.offense_lineup is not None else None
                ),
                "defense_lineup": (
                    list(item.defense_lineup) if item.defense_lineup is not None else None
                ),
                "offense_fatigue": [
                    {"player_id": snapshot.player_id, "fatigue": snapshot.fatigue}
                    for snapshot in item.offense_fatigue
                ],
                "defense_fatigue": [
                    {"player_id": snapshot.player_id, "fatigue": snapshot.fatigue}
                    for snapshot in item.defense_fatigue
                ],
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
        "substitutions": [
            {
                "team_id": item.team_id,
                "period": item.period,
                "clock_seconds": item.clock_seconds,
                "reason": int(item.reason),
                "outgoing_player_id": item.outgoing_player_id,
                "incoming_player_id": item.incoming_player_id,
            }
            for item in result.substitutions
        ],
        "playing_time": [
            {
                "team_id": item.team_id,
                "player_id": item.player_id,
                "seconds": item.seconds,
            }
            for item in result.playing_time
        ],
        "final_fatigue": [
            {"player_id": item.player_id, "fatigue": item.fatigue} for item in result.final_fatigue
        ],
        "rotation_version": result.rotation_version,
        "fatigue_version": result.fatigue_version,
    }


def game_result_from_dict(value: object, config: GameClockConfig) -> GameResult:
    obj = _object(value, "game result")
    legacy_keys = {
        "schema_version",
        "home_team_id",
        "away_team_id",
        "possessions",
        "home_score",
        "away_score",
        "player_stats",
        "end_reason",
    }
    current_keys = legacy_keys | {
        "substitutions",
        "playing_time",
        "final_fatigue",
        "rotation_version",
        "fatigue_version",
    }
    schema_version = _int(obj, "schema_version")
    if schema_version not in {1, SCHEMA_VERSION}:
        _fail("unsupported schema_version")
    _exact(obj, legacy_keys if schema_version == 1 else current_keys, "game result")
    raw_possessions = obj["possessions"]
    if not isinstance(raw_possessions, list):
        _fail("possessions must be a list")
    possessions: list[GamePossessionRecord] = []
    legacy_possession_keys = {
        "possession_index",
        "period",
        "clock_start_seconds",
        "clock_end_seconds",
        "offense_team_id",
        "defense_team_id",
        "result",
    }
    current_possession_keys = legacy_possession_keys | {
        "offense_lineup",
        "defense_lineup",
        "offense_fatigue",
        "defense_fatigue",
    }
    for raw_possession in raw_possessions:
        possession = _object(raw_possession, "possession")
        _exact(
            possession,
            legacy_possession_keys if schema_version == 1 else current_possession_keys,
            "possession",
        )
        offense_lineup = (
            None
            if schema_version == 1 or possession["offense_lineup"] is None
            else _lineup(possession["offense_lineup"], "offense_lineup")
        )
        defense_lineup = (
            None
            if schema_version == 1 or possession["defense_lineup"] is None
            else _lineup(possession["defense_lineup"], "defense_lineup")
        )
        possessions.append(
            GamePossessionRecord(
                _int(possession, "possession_index"),
                _int(possession, "period"),
                _int(possession, "clock_start_seconds"),
                _int(possession, "clock_end_seconds"),
                _string(possession, "offense_team_id"),
                _string(possession, "defense_team_id"),
                possession_result_from_dict(possession["result"]),
                offense_lineup,
                defense_lineup,
                (
                    ()
                    if schema_version == 1
                    else _fatigue_snapshots(
                        possession["offense_fatigue"],
                        "offense_fatigue",
                    )
                ),
                (
                    ()
                    if schema_version == 1
                    else _fatigue_snapshots(
                        possession["defense_fatigue"],
                        "defense_fatigue",
                    )
                ),
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
    substitutions: list[SubstitutionRecord] = []
    playing_time: list[PlayerPlayingTime] = []
    final_fatigue: tuple[PlayerFatigueSnapshot, ...] = ()
    if schema_version == SCHEMA_VERSION:
        raw_substitutions = obj["substitutions"]
        if not isinstance(raw_substitutions, list):
            _fail("substitutions must be a list")
        substitution_keys = {
            "team_id",
            "period",
            "clock_seconds",
            "reason",
            "outgoing_player_id",
            "incoming_player_id",
        }
        for raw in raw_substitutions:
            item = _object(raw, "substitution")
            _exact(item, substitution_keys, "substitution")
            try:
                reason = SubstitutionReason(_int(item, "reason"))
            except ValueError as error:
                raise SerializationError("invalid substitution reason") from error
            substitutions.append(
                SubstitutionRecord(
                    _string(item, "team_id"),
                    _int(item, "period"),
                    _int(item, "clock_seconds"),
                    reason,
                    _int(item, "outgoing_player_id"),
                    _int(item, "incoming_player_id"),
                )
            )
        raw_playing_time = obj["playing_time"]
        if not isinstance(raw_playing_time, list):
            _fail("playing_time must be a list")
        for raw in raw_playing_time:
            item = _object(raw, "playing time")
            _exact(item, {"team_id", "player_id", "seconds"}, "playing time")
            playing_time.append(
                PlayerPlayingTime(
                    _string(item, "team_id"),
                    _int(item, "player_id"),
                    _int(item, "seconds"),
                )
            )
        final_fatigue = _fatigue_snapshots(obj["final_fatigue"], "final_fatigue")
    result = GameResult(
        _string(obj, "home_team_id"),
        _string(obj, "away_team_id"),
        tuple(possessions),
        _int(obj, "home_score"),
        _int(obj, "away_score"),
        tuple(stats),
        end_reason,
        tuple(substitutions),
        tuple(playing_time),
        final_fatigue,
        None if schema_version == 1 else _nullable_string(obj, "rotation_version"),
        None if schema_version == 1 else _nullable_string(obj, "fatigue_version"),
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

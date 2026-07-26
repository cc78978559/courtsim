"""Deterministic four-team playoff bracket resolution."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, NoReturn, cast

from courtsim.domain.serialization import SerializationError

PLAYOFF_VERSION = "playoff-v1"
PLAYOFF_SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class PlayoffConfig:
    best_of: int = 7
    higher_seed_home: tuple[bool, ...] = (True, True, False, False, True, False, True)
    version: str = PLAYOFF_VERSION

    def __post_init__(self) -> None:
        if self.version != PLAYOFF_VERSION:
            raise ValueError(f"unsupported playoff version: {self.version}")
        if (
            not isinstance(self.best_of, int)
            or isinstance(self.best_of, bool)
            or self.best_of not in {1, 3, 5, 7}
        ):
            raise ValueError("best_of must be one of 1, 3, 5, or 7")
        if len(self.higher_seed_home) != self.best_of or any(
            not isinstance(item, bool) for item in self.higher_seed_home
        ):
            raise ValueError("higher_seed_home must contain one boolean per possible game")

    @property
    def wins_required(self) -> int:
        return self.best_of // 2 + 1


@dataclass(frozen=True, slots=True)
class PlayoffSeed:
    seed: int
    team_id: str

    def __post_init__(self) -> None:
        if not isinstance(self.seed, int) or isinstance(self.seed, bool) or self.seed < 1:
            raise ValueError("playoff seed must be a positive integer")
        if not self.team_id.strip():
            raise ValueError("playoff team_id must not be blank")


@dataclass(frozen=True, slots=True)
class PlayoffGame:
    round_number: int
    series_index: int
    game_number: int
    home_team_id: str
    away_team_id: str
    home_score: int
    away_score: int

    def __post_init__(self) -> None:
        indexes = (self.round_number, self.series_index, self.game_number)
        if any(
            not isinstance(value, int) or isinstance(value, bool) or value < 1 for value in indexes
        ):
            raise ValueError("playoff game indexes must be positive integers")
        if not self.home_team_id.strip() or not self.away_team_id.strip():
            raise ValueError("playoff game team ids must not be blank")
        if self.home_team_id == self.away_team_id:
            raise ValueError("a playoff team cannot play itself")
        scores = (self.home_score, self.away_score)
        if any(
            not isinstance(score, int) or isinstance(score, bool) or score < 0 for score in scores
        ):
            raise ValueError("playoff scores must be non-negative integers")
        if self.home_score == self.away_score:
            raise ValueError("playoff games cannot end in a tie")

    @property
    def winner_team_id(self) -> str:
        return self.home_team_id if self.home_score > self.away_score else self.away_team_id


@dataclass(frozen=True, slots=True)
class PlayoffSeries:
    round_number: int
    series_index: int
    higher_seed: PlayoffSeed
    lower_seed: PlayoffSeed
    games: tuple[PlayoffGame, ...]
    higher_seed_wins: int
    lower_seed_wins: int
    winner_team_id: str


@dataclass(frozen=True, slots=True)
class PlayoffResult:
    seeds: tuple[PlayoffSeed, ...]
    games: tuple[PlayoffGame, ...]
    series: tuple[PlayoffSeries, ...]
    champion_team_id: str
    config: PlayoffConfig
    version: str = PLAYOFF_VERSION

    def __post_init__(self) -> None:
        if self.version != PLAYOFF_VERSION:
            raise ValueError("unsupported playoff result version")


@dataclass(frozen=True, slots=True)
class PlayoffAudit:
    teams: int
    series_completed: int
    games_played: int
    sweeps: int
    elimination_games: int
    champion_team_id: str


def _validate_seeds(seeds: tuple[PlayoffSeed, ...]) -> dict[str, PlayoffSeed]:
    if len(seeds) != 4:
        raise ValueError("playoff-v1 requires exactly four teams")
    if tuple(item.seed for item in seeds) != (1, 2, 3, 4):
        raise ValueError("playoff seeds must be ordered and contiguous from 1 through 4")
    if len({item.team_id for item in seeds}) != 4:
        raise ValueError("playoff team ids must be unique")
    return {item.team_id: item for item in seeds}


def _resolve_series(
    *,
    round_number: int,
    series_index: int,
    first: PlayoffSeed,
    second: PlayoffSeed,
    games: tuple[PlayoffGame, ...],
    start_index: int,
    config: PlayoffConfig,
) -> tuple[PlayoffSeries, int]:
    higher, lower = (first, second) if first.seed < second.seed else (second, first)
    higher_wins = 0
    lower_wins = 0
    consumed: list[PlayoffGame] = []
    index = start_index
    while higher_wins < config.wins_required and lower_wins < config.wins_required:
        if index >= len(games):
            raise ValueError("playoff game ledger ends before a series winner is decided")
        game = games[index]
        game_number = len(consumed) + 1
        expected_home = higher if config.higher_seed_home[game_number - 1] else lower
        expected_away = lower if expected_home is higher else higher
        if (
            game.round_number != round_number
            or game.series_index != series_index
            or game.game_number != game_number
        ):
            raise ValueError("playoff game address does not match bracket order")
        if game.home_team_id != expected_home.team_id or game.away_team_id != expected_away.team_id:
            raise ValueError("playoff game home/away teams do not match the series pattern")
        consumed.append(game)
        if game.winner_team_id == higher.team_id:
            higher_wins += 1
        else:
            lower_wins += 1
        index += 1
    winner = higher.team_id if higher_wins > lower_wins else lower.team_id
    return (
        PlayoffSeries(
            round_number,
            series_index,
            higher,
            lower,
            tuple(consumed),
            higher_wins,
            lower_wins,
            winner,
        ),
        index,
    )


def resolve_playoffs(
    *,
    seeds: tuple[PlayoffSeed, ...],
    games: tuple[PlayoffGame, ...],
    config: PlayoffConfig | None = None,
) -> PlayoffResult:
    config = config or PlayoffConfig()
    seed_by_team = _validate_seeds(seeds)
    series: list[PlayoffSeries] = []
    index = 0
    first, index = _resolve_series(
        round_number=1,
        series_index=1,
        first=seeds[0],
        second=seeds[3],
        games=games,
        start_index=index,
        config=config,
    )
    series.append(first)
    second, index = _resolve_series(
        round_number=1,
        series_index=2,
        first=seeds[1],
        second=seeds[2],
        games=games,
        start_index=index,
        config=config,
    )
    series.append(second)
    final, index = _resolve_series(
        round_number=2,
        series_index=1,
        first=seed_by_team[first.winner_team_id],
        second=seed_by_team[second.winner_team_id],
        games=games,
        start_index=index,
        config=config,
    )
    series.append(final)
    if index != len(games):
        raise ValueError("playoff ledger contains games after the championship is decided")
    return PlayoffResult(seeds, games, tuple(series), final.winner_team_id, config)


def audit_playoffs(result: PlayoffResult) -> PlayoffAudit:
    replayed = resolve_playoffs(seeds=result.seeds, games=result.games, config=result.config)
    if replayed != result:
        raise ValueError("playoff result does not derive from its game ledger")
    return PlayoffAudit(
        len(result.seeds),
        len(result.series),
        len(result.games),
        sum(min(series.higher_seed_wins, series.lower_seed_wins) == 0 for series in result.series),
        sum(len(series.games) == result.config.best_of for series in result.series),
        result.champion_team_id,
    )


def playoff_result_to_dict(result: PlayoffResult) -> dict[str, object]:
    return {
        "schema_version": PLAYOFF_SCHEMA_VERSION,
        "version": result.version,
        "config": {
            "version": result.config.version,
            "best_of": result.config.best_of,
            "higher_seed_home": list(result.config.higher_seed_home),
        },
        "seeds": [{"seed": item.seed, "team_id": item.team_id} for item in result.seeds],
        "games": [
            {
                "round_number": item.round_number,
                "series_index": item.series_index,
                "game_number": item.game_number,
                "home_team_id": item.home_team_id,
                "away_team_id": item.away_team_id,
                "home_score": item.home_score,
                "away_score": item.away_score,
            }
            for item in result.games
        ],
        "champion_team_id": result.champion_team_id,
    }


def _fail(message: str) -> NoReturn:
    raise SerializationError(message)


def _object(value: object, field: str) -> Mapping[str, Any]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        _fail(f"{field} must be an object")
    return cast(Mapping[str, Any], value)


def _exact(value: Mapping[str, Any], keys: set[str], field: str) -> None:
    if set(value) != keys:
        _fail(f"{field} keys must be exactly {sorted(keys)}")


def _integer(value: Mapping[str, Any], key: str) -> int:
    raw = value[key]
    if not isinstance(raw, int) or isinstance(raw, bool):
        _fail(f"{key} must be an integer")
    return raw


def _string(value: Mapping[str, Any], key: str) -> str:
    raw = value[key]
    if not isinstance(raw, str) or not raw:
        _fail(f"{key} must be a non-empty string")
    return raw


def playoff_result_from_dict(value: object) -> PlayoffResult:
    raw = _object(value, "playoff result")
    _exact(
        raw,
        {"schema_version", "version", "config", "seeds", "games", "champion_team_id"},
        "playoff result",
    )
    if _integer(raw, "schema_version") != PLAYOFF_SCHEMA_VERSION:
        _fail("unsupported playoff schema_version")
    config_raw = _object(raw["config"], "playoff config")
    _exact(config_raw, {"version", "best_of", "higher_seed_home"}, "playoff config")
    pattern_raw = config_raw["higher_seed_home"]
    if not isinstance(pattern_raw, list) or any(not isinstance(item, bool) for item in pattern_raw):
        _fail("higher_seed_home must be a boolean list")
    config = PlayoffConfig(
        _integer(config_raw, "best_of"),
        tuple(pattern_raw),
        _string(config_raw, "version"),
    )
    seeds_raw = raw["seeds"]
    if not isinstance(seeds_raw, list):
        _fail("seeds must be a list")
    seeds: list[PlayoffSeed] = []
    for seed_raw in seeds_raw:
        item = _object(seed_raw, "playoff seed")
        _exact(item, {"seed", "team_id"}, "playoff seed")
        seeds.append(PlayoffSeed(_integer(item, "seed"), _string(item, "team_id")))
    games_raw = raw["games"]
    if not isinstance(games_raw, list):
        _fail("games must be a list")
    games: list[PlayoffGame] = []
    for game_raw in games_raw:
        item = _object(game_raw, "playoff game")
        _exact(
            item,
            {
                "round_number",
                "series_index",
                "game_number",
                "home_team_id",
                "away_team_id",
                "home_score",
                "away_score",
            },
            "playoff game",
        )
        games.append(
            PlayoffGame(
                _integer(item, "round_number"),
                _integer(item, "series_index"),
                _integer(item, "game_number"),
                _string(item, "home_team_id"),
                _string(item, "away_team_id"),
                _integer(item, "home_score"),
                _integer(item, "away_score"),
            )
        )
    try:
        result = resolve_playoffs(seeds=tuple(seeds), games=tuple(games), config=config)
    except ValueError as error:
        raise SerializationError(str(error)) from error
    if result.champion_team_id != _string(raw, "champion_team_id"):
        _fail("champion_team_id does not derive from playoff games")
    if result.version != _string(raw, "version"):
        _fail("unsupported playoff result version")
    return result


def playoff_result_to_json(result: PlayoffResult) -> str:
    return json.dumps(
        playoff_result_to_dict(result),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )


def playoff_result_from_json(payload: str) -> PlayoffResult:
    try:
        value = json.loads(payload)
    except json.JSONDecodeError as error:
        raise SerializationError(f"invalid playoff JSON: {error.msg}") from error
    return playoff_result_from_dict(value)

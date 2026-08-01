"""Strict, source-pinned NBA player realism targets."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import cast

NBA_PLAYER_TARGET_VERSION = "nba-player-target-v1"
NBA_PLAYER_TARGET_SCHEMA_VERSION = 1
NBA_PLAYER_TARGET_ZONES = ("RIM", "MIDRANGE", "THREE")


class NbaPlayerTargetError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class NBAPlayerSourceReceipt:
    role: str
    path: str
    sha256: str

    def __post_init__(self) -> None:
        if not self.role.strip() or not self.path.strip():
            raise ValueError("NBA player target source identity must not be blank")
        if Path(self.path).is_absolute() or ".." in Path(self.path).parts:
            raise ValueError("NBA player target source path must be portable")
        if len(self.sha256) != 64 or any(
            character not in "0123456789abcdef" for character in self.sha256
        ):
            raise ValueError("NBA player target source sha256 is invalid")


@dataclass(frozen=True, slots=True)
class NBAPlayerTarget:
    nba_player_id: int
    player_name: str
    team_id: str
    games_played: int
    minutes_per_game: float
    usage_rate: float
    true_shooting_percentage: float
    field_goal_attempt_share: float
    shot_zone_shares: tuple[float, float, float]
    shot_zone_percentages: tuple[float, float, float]

    def __post_init__(self) -> None:
        if (
            not isinstance(self.nba_player_id, int)
            or isinstance(self.nba_player_id, bool)
            or self.nba_player_id < 1
            or not self.player_name.strip()
            or not self.team_id.strip()
            or not isinstance(self.games_played, int)
            or isinstance(self.games_played, bool)
            or self.games_played < 1
        ):
            raise ValueError("NBA player target identity is invalid")
        if not math.isfinite(self.minutes_per_game) or not 0 < self.minutes_per_game <= 60:
            raise ValueError("NBA player target minutes are invalid")
        for field, value, maximum in (
            ("usage_rate", self.usage_rate, 1.0),
            ("true_shooting_percentage", self.true_shooting_percentage, 1.5),
            ("field_goal_attempt_share", self.field_goal_attempt_share, 1.0),
        ):
            if not math.isfinite(value) or not 0 <= value <= maximum:
                raise ValueError(f"NBA player target {field} is invalid")
        if len(self.shot_zone_shares) != 3 or len(self.shot_zone_percentages) != 3:
            raise ValueError("NBA player target shot zones are incomplete")
        if any(not math.isfinite(value) or not 0 <= value <= 1 for value in self.shot_zone_shares):
            raise ValueError("NBA player target shot-zone shares are invalid")
        if not math.isclose(math.fsum(self.shot_zone_shares), 1.0, abs_tol=1e-9):
            raise ValueError("NBA player target shot-zone shares must sum to one")
        if any(
            not math.isfinite(value) or not 0 <= value <= 1 for value in self.shot_zone_percentages
        ):
            raise ValueError("NBA player target shot-zone percentages are invalid")


@dataclass(frozen=True, slots=True)
class NBAPlayerTargetSet:
    target_id: str
    season: str
    provider: str
    minimum_games: int
    minimum_minutes_per_game: float
    sources: tuple[NBAPlayerSourceReceipt, ...]
    players: tuple[NBAPlayerTarget, ...]
    version: str = NBA_PLAYER_TARGET_VERSION

    def __post_init__(self) -> None:
        if not self.target_id.strip() or not self.season.strip() or not self.provider.strip():
            raise ValueError("NBA player target-set identity must not be blank")
        if (
            not isinstance(self.minimum_games, int)
            or isinstance(self.minimum_games, bool)
            or self.minimum_games < 1
            or not math.isfinite(self.minimum_minutes_per_game)
            or self.minimum_minutes_per_game <= 0
        ):
            raise ValueError("NBA player target eligibility is invalid")
        if not self.sources or not self.players:
            raise ValueError("NBA player target set must contain sources and players")
        if len({item.role for item in self.sources}) != len(self.sources):
            raise ValueError("NBA player target source roles must be unique")
        identities = tuple(item.nba_player_id for item in self.players)
        if identities != tuple(sorted(set(identities))):
            raise ValueError("NBA player targets must use ordered unique player ids")
        if any(
            item.games_played < self.minimum_games
            or item.minutes_per_game < self.minimum_minutes_per_game
            for item in self.players
        ):
            raise ValueError("NBA player target does not satisfy eligibility")
        if self.version != NBA_PLAYER_TARGET_VERSION:
            raise ValueError("unsupported NBA player target version")


def nba_player_target_set_to_dict(targets: NBAPlayerTargetSet) -> dict[str, object]:
    return {
        "schema_version": NBA_PLAYER_TARGET_SCHEMA_VERSION,
        "version": targets.version,
        "target_id": targets.target_id,
        "season": targets.season,
        "provider": targets.provider,
        "eligibility": {
            "minimum_games": targets.minimum_games,
            "minimum_minutes_per_game": targets.minimum_minutes_per_game,
        },
        "sources": [
            {"role": item.role, "path": item.path, "sha256": item.sha256}
            for item in targets.sources
        ],
        "players": [
            {
                "nba_player_id": item.nba_player_id,
                "player_name": item.player_name,
                "team_id": item.team_id,
                "games_played": item.games_played,
                "minutes_per_game": item.minutes_per_game,
                "usage_rate": item.usage_rate,
                "true_shooting_percentage": item.true_shooting_percentage,
                "field_goal_attempt_share": item.field_goal_attempt_share,
                "shot_zone_shares": dict(
                    zip(NBA_PLAYER_TARGET_ZONES, item.shot_zone_shares, strict=True)
                ),
                "shot_zone_percentages": dict(
                    zip(NBA_PLAYER_TARGET_ZONES, item.shot_zone_percentages, strict=True)
                ),
            }
            for item in targets.players
        ],
    }


def load_nba_player_target_set(path: str | Path) -> NBAPlayerTargetSet:
    source = Path(path)
    try:
        raw: object = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise NbaPlayerTargetError(f"cannot read NBA player targets: {source}") from error
    if not isinstance(raw, dict) or set(raw) != {
        "schema_version",
        "version",
        "target_id",
        "season",
        "provider",
        "eligibility",
        "sources",
        "players",
    }:
        raise NbaPlayerTargetError("NBA player target root is invalid")
    if raw["schema_version"] != NBA_PLAYER_TARGET_SCHEMA_VERSION:
        raise NbaPlayerTargetError("NBA player target schema version differs")
    eligibility = _mapping(raw["eligibility"], "eligibility")
    if set(eligibility) != {"minimum_games", "minimum_minutes_per_game"}:
        raise NbaPlayerTargetError("NBA player target eligibility is invalid")
    raw_sources = raw["sources"]
    raw_players = raw["players"]
    if not isinstance(raw_sources, list) or not isinstance(raw_players, list):
        raise NbaPlayerTargetError("NBA player target collections are invalid")
    try:
        return NBAPlayerTargetSet(
            _text(raw["target_id"], "target_id"),
            _text(raw["season"], "season"),
            _text(raw["provider"], "provider"),
            _integer(eligibility["minimum_games"], "minimum_games"),
            _number(eligibility["minimum_minutes_per_game"], "minimum_minutes_per_game"),
            tuple(_source_receipt(item) for item in raw_sources),
            tuple(_player_target(item) for item in raw_players),
            _text(raw["version"], "version"),
        )
    except ValueError as error:
        raise NbaPlayerTargetError(str(error)) from error


def _source_receipt(value: object) -> NBAPlayerSourceReceipt:
    raw = _mapping(value, "source")
    if set(raw) != {"role", "path", "sha256"}:
        raise NbaPlayerTargetError("NBA player target source is invalid")
    return NBAPlayerSourceReceipt(
        _text(raw["role"], "source.role"),
        _text(raw["path"], "source.path"),
        _text(raw["sha256"], "source.sha256"),
    )


def _player_target(value: object) -> NBAPlayerTarget:
    raw = _mapping(value, "player")
    expected = {
        "nba_player_id",
        "player_name",
        "team_id",
        "games_played",
        "minutes_per_game",
        "usage_rate",
        "true_shooting_percentage",
        "field_goal_attempt_share",
        "shot_zone_shares",
        "shot_zone_percentages",
    }
    if set(raw) != expected:
        raise NbaPlayerTargetError("NBA player target row is invalid")
    return NBAPlayerTarget(
        _integer(raw["nba_player_id"], "nba_player_id"),
        _text(raw["player_name"], "player_name"),
        _text(raw["team_id"], "team_id"),
        _integer(raw["games_played"], "games_played"),
        _number(raw["minutes_per_game"], "minutes_per_game"),
        _number(raw["usage_rate"], "usage_rate"),
        _number(raw["true_shooting_percentage"], "true_shooting_percentage"),
        _number(raw["field_goal_attempt_share"], "field_goal_attempt_share"),
        _zones(raw["shot_zone_shares"], "shot_zone_shares"),
        _zones(raw["shot_zone_percentages"], "shot_zone_percentages"),
    )


def _zones(value: object, field: str) -> tuple[float, float, float]:
    raw = _mapping(value, field)
    if set(raw) != set(NBA_PLAYER_TARGET_ZONES):
        raise NbaPlayerTargetError(f"{field} zones are invalid")
    return cast(
        tuple[float, float, float],
        tuple(_number(raw[zone], field) for zone in NBA_PLAYER_TARGET_ZONES),
    )


def _mapping(value: object, field: str) -> dict[str, object]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise NbaPlayerTargetError(f"{field} must be an object")
    return cast(dict[str, object], value)


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise NbaPlayerTargetError(f"{field} must be non-empty text")
    return value.strip()


def _integer(value: object, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise NbaPlayerTargetError(f"{field} must be an integer")
    return value


def _number(value: object, field: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise NbaPlayerTargetError(f"{field} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise NbaPlayerTargetError(f"{field} must be finite")
    return result

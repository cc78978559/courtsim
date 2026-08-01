"""Source-pinned white-box team-strength offsets for quick simulation."""

from __future__ import annotations

import json
from dataclasses import fields, replace
from pathlib import Path
from typing import Any, cast

from courtsim.artifacts import sha256_file
from courtsim.domain.player import AbilityRatings, PlayerProfile
from courtsim.model.game_runtime import GameTeam
from courtsim.model.interaction_compiler import ProfileLineup

NBA_TEAM_STRENGTH_VERSION = "nba-team-strength-v1"


class NbaTeamStrengthError(ValueError):
    pass


def apply_nba_team_strengths(
    teams: tuple[GameTeam, ...], strength_path: str | Path
) -> tuple[GameTeam, ...]:
    """Apply one transparent additive ability offset to every player on each team."""
    path = Path(strength_path).resolve()
    try:
        raw: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise NbaTeamStrengthError(f"cannot read NBA team strength file: {path}") from error
    if not isinstance(raw, dict):
        raise NbaTeamStrengthError("NBA team strength payload must be an object")
    root = cast(dict[str, Any], raw)
    expected = {"version", "season_id", "source", "method", "teams"}
    if set(root) != expected or root.get("version") != NBA_TEAM_STRENGTH_VERSION:
        raise NbaTeamStrengthError("NBA team strength schema differs")
    source = root["source"]
    method = root["method"]
    if not isinstance(source, dict) or not isinstance(method, dict):
        raise NbaTeamStrengthError("NBA team strength provenance is invalid")
    source_path = (path.parent / _text(source.get("path"), "source.path")).resolve()
    source_hash = _sha256(source.get("sha256"), "source.sha256")
    if not source_path.is_file() or sha256_file(source_path) != source_hash:
        raise NbaTeamStrengthError("NBA team strength reality source is unverified")
    multiplier = _number(method.get("point_differential_multiplier"), "multiplier")
    rows = root["teams"]
    if not isinstance(rows, list) or len(rows) != 30:
        raise NbaTeamStrengthError("NBA team strength requires 30 teams")
    offsets: dict[str, int] = {}
    for value in rows:
        if not isinstance(value, dict) or set(value) != {
            "team_id",
            "point_differential",
            "games",
            "rating_offset",
        }:
            raise NbaTeamStrengthError("NBA team strength row schema differs")
        item = cast(dict[str, object], value)
        team_id = _text(item["team_id"], "team_id")
        games = _integer(item["games"], "games")
        differential = _integer(item["point_differential"], "point_differential")
        offset = _integer(item["rating_offset"], "rating_offset")
        if games != 82 or offset != round(differential / games * multiplier):
            raise NbaTeamStrengthError(f"NBA team strength derivation differs: {team_id}")
        if team_id in offsets:
            raise NbaTeamStrengthError("NBA team strength team ids must be unique")
        offsets[team_id] = offset
    if set(offsets) != {team.team_id for team in teams}:
        raise NbaTeamStrengthError("NBA team strength does not cover executor teams")
    return tuple(_apply_team_offset(team, offsets[team.team_id]) for team in teams)


def _apply_team_offset(team: GameTeam, offset: int) -> GameTeam:
    def apply(profile: PlayerProfile) -> PlayerProfile:
        abilities = AbilityRatings(
            **{
                item.name: max(0, min(100, getattr(profile.abilities, item.name) + offset))
                for item in fields(AbilityRatings)
            }
        )
        return replace(profile, abilities=abilities)

    starters = tuple(apply(profile) for profile in team.profiles)
    bench = tuple(apply(profile) for profile in team.bench_profiles)
    return replace(team, profiles=cast(ProfileLineup, starters), bench_profiles=bench)


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise NbaTeamStrengthError(f"{field} must be non-empty text")
    return value.strip()


def _integer(value: object, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise NbaTeamStrengthError(f"{field} must be an integer")
    return value


def _number(value: object, field: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise NbaTeamStrengthError(f"{field} must be numeric")
    return float(value)


def _sha256(value: object, field: str) -> str:
    text = _text(value, field)
    if len(text) != 64 or any(character not in "0123456789abcdef" for character in text):
        raise NbaTeamStrengthError(f"{field} is invalid")
    return text

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
from courtsim.nba_league import NBAConferenceAlignment

NBA_TEAM_STRENGTH_VERSION = "nba-team-strength-v1"


class NbaTeamStrengthError(ValueError):
    pass


def apply_nba_team_strengths(
    teams: tuple[GameTeam, ...], strength_path: str | Path
) -> tuple[GameTeam, ...]:
    """Apply one transparent additive ability offset to every player on each team."""
    offsets, _conferences, _divisions = _load_team_strengths(strength_path)
    if set(offsets) != {team.team_id for team in teams}:
        raise NbaTeamStrengthError("NBA team strength does not cover executor teams")
    return tuple(_apply_team_offset(team, offsets[team.team_id]) for team in teams)


def load_nba_team_strength_alignment(
    strength_path: str | Path,
) -> NBAConferenceAlignment:
    """Load an explicit, source-pinned real NBA conference alignment."""
    offsets, conferences, divisions = _load_team_strengths(strength_path)
    east = tuple(sorted(team_id for team_id in offsets if conferences[team_id] == "east"))
    west = tuple(sorted(team_id for team_id in offsets if conferences[team_id] == "west"))
    east_divisions = _division_groups(divisions, conferences, "east")
    west_divisions = _division_groups(divisions, conferences, "west")
    return NBAConferenceAlignment(
        east,
        west,
        east_divisions=east_divisions,
        west_divisions=west_divisions,
    )


def load_nba_team_strength_offsets(
    strength_path: str | Path,
) -> tuple[tuple[str, int], ...]:
    """Load canonical white-box team rating offsets."""
    offsets, _conferences, _divisions = _load_team_strengths(strength_path)
    return tuple(sorted(offsets.items()))


def _load_team_strengths(
    strength_path: str | Path,
) -> tuple[dict[str, int], dict[str, str], dict[str, str]]:
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
    conferences: dict[str, str] = {}
    divisions: dict[str, str] = {}
    for value in rows:
        if not isinstance(value, dict) or set(value) != {
            "team_id",
            "point_differential",
            "games",
            "rating_offset",
            "conference",
            "division",
        }:
            raise NbaTeamStrengthError("NBA team strength row schema differs")
        item = cast(dict[str, object], value)
        team_id = _text(item["team_id"], "team_id")
        games = _integer(item["games"], "games")
        differential = _integer(item["point_differential"], "point_differential")
        offset = _integer(item["rating_offset"], "rating_offset")
        conference = _text(item["conference"], "conference").lower()
        division = _text(item["division"], "division").lower()
        if games != 82 or offset != round(differential / games * multiplier):
            raise NbaTeamStrengthError(f"NBA team strength derivation differs: {team_id}")
        if team_id in offsets:
            raise NbaTeamStrengthError("NBA team strength team ids must be unique")
        if conference not in {"east", "west"}:
            raise NbaTeamStrengthError(f"NBA team strength conference differs: {team_id}")
        offsets[team_id] = offset
        conferences[team_id] = conference
        divisions[team_id] = division
    if tuple(conferences.values()).count("east") != 15:
        raise NbaTeamStrengthError("NBA team strength conferences must contain 15 teams each")
    if len(set(divisions.values())) != 6 or any(
        tuple(divisions.values()).count(division) != 5 for division in set(divisions.values())
    ):
        raise NbaTeamStrengthError("NBA team strength divisions must contain six groups of five")
    return offsets, conferences, divisions


def _division_groups(
    divisions: dict[str, str], conferences: dict[str, str], conference: str
) -> tuple[tuple[str, ...], ...]:
    names = sorted(
        {divisions[team_id] for team_id in divisions if conferences[team_id] == conference}
    )
    if len(names) != 3:
        raise NbaTeamStrengthError(f"NBA {conference} division count differs")
    return tuple(
        sorted(
            tuple(sorted(team_id for team_id in divisions if divisions[team_id] == name))
            for name in names
        )
    )


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

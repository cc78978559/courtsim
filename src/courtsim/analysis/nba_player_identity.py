"""Build an explicit, source-pinned ESPN-to-NBA player identity map."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, cast

from courtsim.artifacts import sha256_file

NBA_PLAYER_IDENTITY_VERSION = "nba-player-identity-v1"


class NbaPlayerIdentityError(ValueError):
    """Raised when player identities are ambiguous or source provenance is invalid."""


def build_nba_player_identity_payload(
    box_summary_path: str | Path,
    crosswalk_summary_path: str | Path,
    *,
    minimum_player_coverage: float = 0.9,
    minimum_minutes_coverage: float = 0.95,
    minimum_match_confidence: float = 0.9,
) -> dict[str, object]:
    """Join player-box ESPN ids to NBA ids without fallback name matching."""
    for field, value in (
        ("minimum_player_coverage", minimum_player_coverage),
        ("minimum_minutes_coverage", minimum_minutes_coverage),
        ("minimum_match_confidence", minimum_match_confidence),
    ):
        if not math.isfinite(value) or not 0.0 <= value <= 1.0:
            raise NbaPlayerIdentityError(f"{field} must be between zero and one")

    box_file = Path(box_summary_path).resolve()
    crosswalk_file = Path(crosswalk_summary_path).resolve()
    box = _load_summary(box_file, "player-box summary")
    crosswalk = _load_summary(crosswalk_file, "player crosswalk summary")
    if box.get("group_by") != ["team_id", "athlete_id", "athlete_display_name"]:
        raise NbaPlayerIdentityError("player-box summary has an unsupported group key")
    expected_crosswalk_key = [
        "espn_athlete_id",
        "nba_player_id",
        "espn_full_name",
        "nba_player_name",
        "match_method",
        "match_confidence",
    ]
    if crosswalk.get("group_by") != expected_crosswalk_key:
        raise NbaPlayerIdentityError("player crosswalk summary has an unsupported group key")

    box_players = _box_players(box)
    crosswalk_players = _crosswalk_players(crosswalk)
    mappings: list[dict[str, object]] = []
    unmatched: list[dict[str, object]] = []
    mapped_minutes = 0.0
    total_minutes = math.fsum(cast(float, item["minutes"]) for item in box_players.values())
    for espn_id in sorted(box_players, key=int):
        player = box_players[espn_id]
        match = crosswalk_players.get(espn_id)
        if match is None:
            unmatched.append(
                {
                    "espn_player_id": int(espn_id),
                    "player_name": player["player_name"],
                    "team_ids": player["team_ids"],
                    "minutes": player["minutes"],
                    "reason": "missing_from_pinned_crosswalk",
                }
            )
            continue
        confidence = cast(float, match["match_confidence"])
        if confidence < minimum_match_confidence:
            unmatched.append(
                {
                    "espn_player_id": int(espn_id),
                    "player_name": player["player_name"],
                    "team_ids": player["team_ids"],
                    "minutes": player["minutes"],
                    "reason": "below_match_confidence_threshold",
                    "candidate_nba_player_id": match["nba_player_id"],
                    "match_confidence": confidence,
                }
            )
            continue
        mapped_minutes += cast(float, player["minutes"])
        mappings.append(
            {
                "courtsim_player_id": None,
                "espn_player_id": int(espn_id),
                "nba_player_id": match["nba_player_id"],
                "player_name": player["player_name"],
                "espn_name": match["espn_name"],
                "nba_name": match["nba_name"],
                "team_ids": player["team_ids"],
                "games_played": player["games_played"],
                "minutes": player["minutes"],
                "match_method": match["match_method"],
                "match_confidence": confidence,
            }
        )

    player_coverage = len(mappings) / len(box_players) if box_players else 0.0
    minutes_coverage = mapped_minutes / total_minutes if total_minutes else 0.0
    ready = (
        player_coverage >= minimum_player_coverage and minutes_coverage >= minimum_minutes_coverage
    )
    return {
        "schema_version": 1,
        "version": NBA_PLAYER_IDENTITY_VERSION,
        "season": _text(box.get("season"), "player-box season"),
        "identity_authority": "NBA Stats player id",
        "policy": {
            "name_fallback": False,
            "minimum_match_confidence": minimum_match_confidence,
            "minimum_player_coverage": minimum_player_coverage,
            "minimum_minutes_coverage": minimum_minutes_coverage,
        },
        "sources": {
            "player_box": _source_receipt(box_file, box),
            "player_crosswalk": _source_receipt(crosswalk_file, crosswalk),
        },
        "coverage": {
            "box_players": len(box_players),
            "mapped_players": len(mappings),
            "unmapped_players": len(unmatched),
            "player_coverage": player_coverage,
            "total_minutes": total_minutes,
            "mapped_minutes": mapped_minutes,
            "minutes_coverage": minutes_coverage,
        },
        "promotion": {
            "ready": ready,
            "blocking_reasons": [
                reason
                for failed, reason in (
                    (
                        player_coverage < minimum_player_coverage,
                        "player_coverage_below_threshold",
                    ),
                    (
                        minutes_coverage < minimum_minutes_coverage,
                        "minutes_coverage_below_threshold",
                    ),
                )
                if failed
            ],
        },
        "mappings": mappings,
        "unmatched": unmatched,
    }


def _box_players(summary: dict[str, Any]) -> dict[str, dict[str, object]]:
    players: dict[str, dict[str, object]] = {}
    for raw_group in _groups(summary, "player-box"):
        group = _mapping(raw_group, "player-box group")
        key = _mapping(group.get("key"), "player-box group key")
        metrics = _mapping(group.get("metrics"), "player-box group metrics")
        espn_id = _positive_id(key.get("athlete_id"), "athlete_id")
        team_id = _text(key.get("team_id"), "team_id")
        name = _text(key.get("athlete_display_name"), "athlete_display_name")
        minutes = _nonnegative_number(metrics.get("minutes"), "minutes")
        games = _nonnegative_integer(metrics.get("games_played"), "games_played")
        player = players.setdefault(
            espn_id,
            {"player_name": name, "team_ids": [], "minutes": 0.0, "games_played": 0},
        )
        if player["player_name"] != name:
            raise NbaPlayerIdentityError(f"ESPN player id {espn_id} has conflicting names")
        cast(list[str], player["team_ids"]).append(team_id)
        player["minutes"] = cast(float, player["minutes"]) + minutes
        player["games_played"] = cast(int, player["games_played"]) + games
    for player in players.values():
        player["team_ids"] = sorted(set(cast(list[str], player["team_ids"])), key=int)
    if not players:
        raise NbaPlayerIdentityError("player-box summary contains no players")
    return players


def _crosswalk_players(summary: dict[str, Any]) -> dict[str, dict[str, object]]:
    players: dict[str, dict[str, object]] = {}
    nba_ids: dict[int, str] = {}
    for raw_group in _groups(summary, "player crosswalk"):
        group = _mapping(raw_group, "player crosswalk group")
        key = _mapping(group.get("key"), "player crosswalk group key")
        espn_id = _positive_id(key.get("espn_athlete_id"), "espn_athlete_id")
        nba_id = int(_positive_id(key.get("nba_player_id"), "nba_player_id"))
        match = {
            "nba_player_id": nba_id,
            "espn_name": _text(key.get("espn_full_name"), "espn_full_name"),
            "nba_name": _text(key.get("nba_player_name"), "nba_player_name"),
            "match_method": _text(key.get("match_method"), "match_method"),
            "match_confidence": _number(key.get("match_confidence"), "match_confidence"),
        }
        if espn_id in players and players[espn_id] != match:
            raise NbaPlayerIdentityError(f"ESPN player id {espn_id} is ambiguous")
        other_espn_id = nba_ids.get(nba_id)
        if other_espn_id is not None and other_espn_id != espn_id:
            raise NbaPlayerIdentityError(f"NBA player id {nba_id} maps to multiple ESPN ids")
        players[espn_id] = match
        nba_ids[nba_id] = espn_id
    return players


def _load_summary(path: Path, label: str) -> dict[str, Any]:
    try:
        raw: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise NbaPlayerIdentityError(f"cannot read {label}: {path}") from error
    summary = _mapping(raw, label)
    if summary.get("schema_version") != 1 or not isinstance(summary.get("groups"), list):
        raise NbaPlayerIdentityError(f"{label} must be a composite grouped schema v1 summary")
    return summary


def _groups(summary: dict[str, Any], label: str) -> list[object]:
    groups = summary.get("groups")
    if not isinstance(groups, list):
        raise NbaPlayerIdentityError(f"{label} groups must be a list")
    return cast(list[object], groups)


def _source_receipt(path: Path, summary: dict[str, Any]) -> dict[str, object]:
    source = _mapping(summary.get("source"), "summary source")
    return {
        "path": path.name,
        "sha256": sha256_file(path),
        "dataset_id": _text(summary.get("dataset_id"), "dataset_id"),
        "raw_sha256": _text(source.get("sha256"), "source.sha256"),
    }


def _mapping(value: object, field: str) -> dict[str, Any]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise NbaPlayerIdentityError(f"{field} must be an object")
    return cast(dict[str, Any], value)


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise NbaPlayerIdentityError(f"{field} must be non-empty text")
    return value.strip()


def _positive_id(value: object, field: str) -> str:
    text = _text(value, field)
    if not text.isdigit() or int(text) < 1:
        raise NbaPlayerIdentityError(f"{field} must be a positive integer id")
    return text


def _number(value: object, field: str) -> float:
    try:
        result = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as error:
        raise NbaPlayerIdentityError(f"{field} must be numeric") from error
    if not math.isfinite(result):
        raise NbaPlayerIdentityError(f"{field} must be finite")
    return result


def _nonnegative_number(value: object, field: str) -> float:
    result = _number(value, field)
    if result < 0:
        raise NbaPlayerIdentityError(f"{field} must be non-negative")
    return result


def _nonnegative_integer(value: object, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise NbaPlayerIdentityError(f"{field} must be a non-negative integer")
    return value

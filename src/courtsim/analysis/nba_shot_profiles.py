"""Convert audited local shot-detail groups into runtime team tendency offsets."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, cast

from courtsim.artifacts import sha256_file
from courtsim.domain.player import PlayerProfile, ShotZoneMix
from courtsim.model.game_runtime import GameTeam
from courtsim.model.interaction_compiler import ProfileLineup

NBA_SHOT_PROFILE_VERSION = 1
_ZONES = ("RIM", "MIDRANGE", "THREE")
_RECONCILED_METRICS = {
    "teams",
    "games",
    "field_goals_made",
    "field_goal_attempts",
    "three_points_made",
    "three_point_attempts",
    "field_goal_percentage",
    "three_point_percentage",
}


class NbaShotProfileError(ValueError):
    """Raised when a shot profile is not source-pinned or internally consistent."""


@dataclass(frozen=True, slots=True)
class NBATeamShotProfile:
    team_id: str
    shares: tuple[float, float, float]
    rating_offsets: tuple[int, int, int]


@dataclass(frozen=True, slots=True)
class NBAShotProfileSet:
    profile_id: str
    season: str
    zone_tendency_loading: float
    teams: tuple[NBATeamShotProfile, ...]


def build_nba_shot_profile_payload(
    summary_path: str | Path,
    audit_path: str | Path,
    *,
    zone_tendency_loading: float = 0.75,
) -> dict[str, object]:
    """Build team-relative rating offsets from an audited grouped shot summary."""
    if not math.isfinite(zone_tendency_loading) or zone_tendency_loading <= 0.0:
        raise NbaShotProfileError("zone_tendency_loading must be finite and positive")
    summary_file = Path(summary_path).resolve()
    audit_file = Path(audit_path).resolve()
    summary = _load_object(summary_file, "shot summary")
    audit = _load_object(audit_file, "shot audit")
    if summary.get("schema_version") != 1 or summary.get("group_by") != "TEAM_NAME":
        raise NbaShotProfileError("shot summary must be a grouped schema v1 TEAM_NAME summary")
    if audit.get("schema_version") != 1 or audit.get("status") != "passed":
        raise NbaShotProfileError("shot audit must be passed schema v1")
    promotion = _mapping(audit.get("promotion"), "audit.promotion")
    reconciled = promotion.get("reconciled_metrics")
    if (
        not isinstance(reconciled, list)
        or set(reconciled) != _RECONCILED_METRICS
        or promotion.get("warning_metrics") != []
        or promotion.get("rejected_metrics") != []
    ):
        raise NbaShotProfileError("shot audit does not reconcile every required total")
    audit_sources = _mapping(audit.get("sources"), "audit.sources")
    audited_summary = _mapping(audit_sources.get("shot_summary"), "audit.sources.shot_summary")
    if audited_summary.get("sha256") != sha256_file(summary_file):
        raise NbaShotProfileError("shot audit does not pin the supplied summary")
    metrics = _mapping(summary.get("metrics"), "summary.metrics")
    groups = _mapping(summary.get("groups"), "summary.groups")
    expected_teams = _positive_int(metrics.get("teams"), "summary.metrics.teams")
    if len(groups) != expected_teams:
        raise NbaShotProfileError("shot summary group count differs from teams metric")
    league_shares = _zone_shares(metrics)
    team_rows: list[dict[str, object]] = []
    for team_id in sorted(groups):
        team_metrics = _mapping(groups[team_id], f"summary.groups.{team_id}")
        shares = _zone_shares(team_metrics)
        log_ratios = tuple(
            math.log(value / baseline)
            for value, baseline in zip(shares, league_shares, strict=True)
        )
        mean_log_ratio = math.fsum(log_ratios) / len(log_ratios)
        offsets = tuple(
            round(15.0 * (value - mean_log_ratio) / zone_tendency_loading) for value in log_ratios
        )
        team_rows.append(
            {
                "team_id": team_id,
                "shot_zone_shares": dict(zip(_ZONES, shares, strict=True)),
                "rating_offsets": dict(zip(_ZONES, offsets, strict=True)),
            }
        )
    return {
        "schema_version": NBA_SHOT_PROFILE_VERSION,
        "profile_id": f"nba-{_text(summary.get('season'), 'summary.season')}-shot-zones-v1",
        "season": _text(summary.get("season"), "summary.season"),
        "zone_tendency_loading": zone_tendency_loading,
        "sources": {
            "summary_path": summary_file.name,
            "summary_sha256": sha256_file(summary_file),
            "audit_path": audit_file.name,
            "audit_sha256": sha256_file(audit_file),
            "raw_source_sha256": _text(
                _mapping(summary.get("source"), "summary.source").get("sha256"),
                "summary.source.sha256",
            ),
        },
        "teams": team_rows,
    }


def load_nba_shot_profile_set(path: str | Path) -> NBAShotProfileSet:
    """Load the compact runtime portion of a generated shot profile artifact."""
    raw = _load_object(Path(path), "shot profile")
    if (
        set(raw)
        != {
            "schema_version",
            "profile_id",
            "season",
            "zone_tendency_loading",
            "sources",
            "teams",
        }
        or raw.get("schema_version") != NBA_SHOT_PROFILE_VERSION
    ):
        raise NbaShotProfileError("shot profile does not match schema version 1")
    loading = _positive_number(raw.get("zone_tendency_loading"), "zone_tendency_loading")
    sources = _mapping(raw.get("sources"), "sources")
    if set(sources) != {
        "summary_path",
        "summary_sha256",
        "audit_path",
        "audit_sha256",
        "raw_source_sha256",
    }:
        raise NbaShotProfileError("shot profile sources are invalid")
    _text(sources.get("summary_path"), "sources.summary_path")
    _text(sources.get("audit_path"), "sources.audit_path")
    for field in ("summary_sha256", "audit_sha256", "raw_source_sha256"):
        _sha256(sources.get(field), f"sources.{field}")
    rows = raw.get("teams")
    if not isinstance(rows, list) or not rows:
        raise NbaShotProfileError("teams must be a non-empty list")
    teams: list[NBATeamShotProfile] = []
    for index, value in enumerate(rows):
        row = _mapping(value, f"teams[{index}]")
        if set(row) != {"team_id", "shot_zone_shares", "rating_offsets"}:
            raise NbaShotProfileError(f"teams[{index}] fields are invalid")
        shares = _zone_tuple(row.get("shot_zone_shares"), f"teams[{index}].shot_zone_shares")
        offsets_raw = _mapping(row.get("rating_offsets"), f"teams[{index}].rating_offsets")
        if set(offsets_raw) != set(_ZONES):
            raise NbaShotProfileError(f"teams[{index}].rating_offsets zones are invalid")
        offsets = tuple(offsets_raw[zone] for zone in _ZONES)
        if any(
            not isinstance(item, int) or isinstance(item, bool) or abs(item) > 100
            for item in offsets
        ):
            raise NbaShotProfileError(f"teams[{index}].rating_offsets are invalid")
        teams.append(
            NBATeamShotProfile(
                _text(row.get("team_id"), f"teams[{index}].team_id"),
                shares,
                cast(tuple[int, int, int], offsets),
            )
        )
    if tuple(item.team_id for item in teams) != tuple(sorted({item.team_id for item in teams})):
        raise NbaShotProfileError("shot profile teams must be ordered and unique")
    return NBAShotProfileSet(
        _text(raw.get("profile_id"), "profile_id"),
        _text(raw.get("season"), "season"),
        loading,
        tuple(teams),
    )


def apply_nba_shot_profiles(
    teams: tuple[GameTeam, ...],
    profiles: NBAShotProfileSet,
) -> tuple[GameTeam, ...]:
    """Apply team offsets to ephemeral quick-sim profiles while preserving player identity."""
    by_team = {item.team_id: item for item in profiles.teams}
    if set(by_team) != {team.team_id for team in teams}:
        raise NbaShotProfileError("shot profile team ids must exactly match simulation teams")
    return tuple(apply_nba_team_shot_profile(team, by_team[team.team_id]) for team in teams)


def apply_nba_team_shot_profile(
    team: GameTeam,
    profile: NBATeamShotProfile,
) -> GameTeam:
    """Apply one profile to a team copy without mutating its career snapshot."""
    if team.team_id != profile.team_id:
        raise NbaShotProfileError("shot profile team id differs from simulation team")

    def adjusted(player: PlayerProfile) -> PlayerProfile:
        mix = player.tendencies.shot_zone_mix
        ratings = (mix.rim, mix.midrange, mix.three)
        changed = tuple(
            max(0, min(100, value + offset))
            for value, offset in zip(ratings, profile.rating_offsets, strict=True)
        )
        return replace(
            player,
            tendencies=replace(
                player.tendencies,
                shot_zone_mix=ShotZoneMix(*changed),
            ),
        )

    return replace(
        team,
        profiles=cast(ProfileLineup, tuple(adjusted(item) for item in team.profiles)),
        bench_profiles=tuple(adjusted(item) for item in team.bench_profiles),
    )


def _zone_shares(metrics: dict[str, Any]) -> tuple[float, float, float]:
    attempts = _positive_number(metrics.get("field_goal_attempts"), "field_goal_attempts")
    shares = (
        (
            _positive_number(metrics.get("restricted_area_attempts"), "restricted_area_attempts")
            + _positive_number(metrics.get("paint_non_ra_attempts"), "paint_non_ra_attempts")
        )
        / attempts,
        _positive_number(metrics.get("mid_range_attempts"), "mid_range_attempts") / attempts,
        _positive_number(metrics.get("three_point_attempts"), "three_point_attempts") / attempts,
    )
    if not 0.999 <= math.fsum(shares) <= 1.001:
        raise NbaShotProfileError("shot zones do not reconcile with field-goal attempts")
    return shares


def _zone_tuple(value: object, field: str) -> tuple[float, float, float]:
    raw = _mapping(value, field)
    if set(raw) != set(_ZONES):
        raise NbaShotProfileError(f"{field} zones are invalid")
    shares = tuple(_positive_number(raw[zone], f"{field}.{zone}") for zone in _ZONES)
    if not 0.999 <= math.fsum(shares) <= 1.001:
        raise NbaShotProfileError(f"{field} must sum to one")
    return cast(tuple[float, float, float], shares)


def _load_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise NbaShotProfileError(f"cannot load {label}: {path}") from error
    return _mapping(value, label)


def _mapping(value: object, field: str) -> dict[str, Any]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise NbaShotProfileError(f"{field} must be an object")
    return cast(dict[str, Any], value)


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise NbaShotProfileError(f"{field} must be a non-empty string")
    return value.strip()


def _sha256(value: object, field: str) -> str:
    digest = _text(value, field).lower()
    if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
        raise NbaShotProfileError(f"{field} must be a SHA-256 digest")
    return digest


def _positive_number(value: object, field: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or float(value) <= 0.0
    ):
        raise NbaShotProfileError(f"{field} must be finite and positive")
    return float(value)


def _positive_int(value: object, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise NbaShotProfileError(f"{field} must be a positive integer")
    return value

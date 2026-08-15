"""Convert audited local shot-detail groups into runtime team tendency offsets."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, cast

from courtsim.analysis.audit_gates import load_distribution_audit
from courtsim.analysis.distribution import DistributionAudit, TeamDistributionMetrics
from courtsim.artifacts import sha256_file
from courtsim.domain.player import PlayerProfile, ShotZoneMix
from courtsim.model.game_runtime import GameTeam
from courtsim.model.interaction_compiler import ProfileLineup

NBA_SHOT_PROFILE_VERSION = 1
NBA_CALIBRATED_SHOT_PROFILE_VERSION = 2
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


def build_calibrated_nba_shot_profile_payload(
    profile_path: str | Path,
    baseline_audit_path: str | Path,
    *,
    calibration_strength: float = 0.75,
    contrast_calibration_strengths: tuple[float, float] = (1.0, 0.75),
    maximum_absolute_offset: int = 30,
) -> dict[str, object]:
    """Materialize a source-pinned v2 profile using identifiable log contrasts."""
    profile_file = Path(profile_path).resolve()
    baseline_file = Path(baseline_audit_path).resolve()
    raw = _load_object(profile_file, "shot profile")
    profiles = load_nba_shot_profile_set(profile_file)
    calibrated = calibrate_nba_shot_profiles(
        profiles,
        load_distribution_audit(baseline_file),
        calibration_strength=calibration_strength,
        contrast_calibration_strengths=contrast_calibration_strengths,
        maximum_absolute_offset=maximum_absolute_offset,
    )
    sources = _mapping(raw.get("sources"), "sources")
    return {
        "schema_version": NBA_CALIBRATED_SHOT_PROFILE_VERSION,
        "profile_id": calibrated.profile_id,
        "season": calibrated.season,
        "zone_tendency_loading": calibrated.zone_tendency_loading,
        "sources": dict(sources),
        "calibration": {
            "method": "three-anchor-log-contrasts-v1",
            "base_profile_id": profiles.profile_id,
            "base_profile_path": profile_file.name,
            "base_profile_sha256": sha256_file(profile_file),
            "baseline_audit_path": baseline_file.name,
            "baseline_audit_sha256": sha256_file(baseline_file),
            "calibration_strength": calibration_strength,
            "contrast_calibration_strengths": list(contrast_calibration_strengths),
            "maximum_absolute_offset": maximum_absolute_offset,
        },
        "teams": [
            {
                "team_id": team.team_id,
                "shot_zone_shares": dict(zip(_ZONES, team.shares, strict=True)),
                "rating_offsets": dict(zip(_ZONES, team.rating_offsets, strict=True)),
            }
            for team in calibrated.teams
        ],
    }


def load_nba_shot_profile_set(path: str | Path) -> NBAShotProfileSet:
    """Load the compact runtime portion of a generated shot profile artifact."""
    raw = _load_object(Path(path), "shot profile")
    schema_version = raw.get("schema_version")
    expected_keys = {
        "schema_version",
        "profile_id",
        "season",
        "zone_tendency_loading",
        "sources",
        "teams",
    }
    if schema_version == NBA_CALIBRATED_SHOT_PROFILE_VERSION:
        expected_keys.add("calibration")
    if set(raw) != expected_keys or schema_version not in {
        NBA_SHOT_PROFILE_VERSION,
        NBA_CALIBRATED_SHOT_PROFILE_VERSION,
    }:
        raise NbaShotProfileError("shot profile does not match a supported schema version")
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
    if schema_version == NBA_CALIBRATED_SHOT_PROFILE_VERSION:
        _validate_calibration(_mapping(raw.get("calibration"), "calibration"))
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


def _validate_calibration(value: dict[str, Any]) -> None:
    if (
        set(value)
        != {
            "method",
            "base_profile_id",
            "base_profile_path",
            "base_profile_sha256",
            "baseline_audit_path",
            "baseline_audit_sha256",
            "calibration_strength",
            "contrast_calibration_strengths",
            "maximum_absolute_offset",
        }
        or value.get("method") != "three-anchor-log-contrasts-v1"
    ):
        raise NbaShotProfileError("shot profile calibration metadata is invalid")
    for field in ("base_profile_id", "base_profile_path", "baseline_audit_path"):
        _text(value.get(field), f"calibration.{field}")
    for field in ("base_profile_sha256", "baseline_audit_sha256"):
        _sha256(value.get(field), f"calibration.{field}")
    strength = value.get("calibration_strength")
    contrasts = value.get("contrast_calibration_strengths")
    maximum = value.get("maximum_absolute_offset")
    if (
        not isinstance(strength, (int, float))
        or isinstance(strength, bool)
        or not math.isfinite(strength)
        or not 0.0 < strength <= 1.0
        or not isinstance(contrasts, list)
        or len(contrasts) != 2
        or any(
            not isinstance(item, (int, float))
            or isinstance(item, bool)
            or not math.isfinite(item)
            or not 0.0 <= item <= 1.0
            for item in contrasts
        )
        or not isinstance(maximum, int)
        or isinstance(maximum, bool)
        or not 1 <= maximum <= 100
    ):
        raise NbaShotProfileError("shot profile calibration values are invalid")


def apply_nba_shot_profiles(
    teams: tuple[GameTeam, ...],
    profiles: NBAShotProfileSet,
) -> tuple[GameTeam, ...]:
    """Apply team offsets to ephemeral quick-sim profiles while preserving player identity."""
    by_team = {item.team_id: item for item in profiles.teams}
    if set(by_team) != {team.team_id for team in teams}:
        raise NbaShotProfileError("shot profile team ids must exactly match simulation teams")
    return tuple(apply_nba_team_shot_profile(team, by_team[team.team_id]) for team in teams)


def calibrate_nba_shot_profiles(
    profiles: NBAShotProfileSet,
    baseline: DistributionAudit,
    *,
    maximum_absolute_offset: int = 30,
    calibration_strength: float = 1.0,
    zone_calibration_strengths: tuple[float, float, float] = (1.0, 1.0, 1.0),
    contrast_calibration_strengths: tuple[float, float] | None = None,
) -> NBAShotProfileSet:
    """Rebase target offsets onto measured simulated team distributions."""
    if (
        not isinstance(maximum_absolute_offset, int)
        or isinstance(maximum_absolute_offset, bool)
        or not 1 <= maximum_absolute_offset <= 100
    ):
        raise NbaShotProfileError("maximum absolute offset must be an integer from 1 through 100")
    if (
        not isinstance(calibration_strength, (int, float))
        or isinstance(calibration_strength, bool)
        or not math.isfinite(calibration_strength)
        or not 0.0 < calibration_strength <= 1.0
    ):
        raise NbaShotProfileError("calibration strength must be in (0, 1]")
    if len(zone_calibration_strengths) != len(_ZONES) or any(
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(value)
        or not 0.0 <= value <= 1.0
        for value in zone_calibration_strengths
    ):
        raise NbaShotProfileError("zone calibration strengths must be three values in [0, 1]")
    if contrast_calibration_strengths is not None and (
        len(contrast_calibration_strengths) != 2
        or any(
            not isinstance(value, (int, float))
            or isinstance(value, bool)
            or not math.isfinite(value)
            or not 0.0 <= value <= 1.0
            for value in contrast_calibration_strengths
        )
    ):
        raise NbaShotProfileError("contrast calibration strengths must be two values in [0, 1]")
    if contrast_calibration_strengths is not None and zone_calibration_strengths != (
        1.0,
        1.0,
        1.0,
    ):
        raise NbaShotProfileError("zone and contrast calibration strengths are mutually exclusive")
    if baseline.games < 1 or baseline.completed_games != baseline.games or baseline.aborted_games:
        raise NbaShotProfileError("shot profile baseline audit must contain complete games")
    baseline_teams = {item.team_id: item for item in baseline.team_metrics}
    if set(baseline_teams) != {item.team_id for item in profiles.teams}:
        raise NbaShotProfileError("shot profile baseline team ids differ")
    calibrated = []
    for profile in profiles.teams:
        if any(
            not math.isfinite(value) or value <= 0.0 for value in profile.shares
        ) or not math.isclose(math.fsum(profile.shares), 1.0, abs_tol=0.001):
            raise NbaShotProfileError(f"shot profile target shares are invalid: {profile.team_id}")
        baseline_shares = _audit_zone_shares(baseline_teams[profile.team_id])
        log_ratios = tuple(
            math.log(target / observed)
            for target, observed in zip(profile.shares, baseline_shares, strict=True)
        )
        mean_log_ratio = math.fsum(log_ratios) / len(log_ratios)
        if contrast_calibration_strengths is None:
            offset_values = tuple(
                calibration_strength
                * zone_strength
                * 15.0
                * (value - mean_log_ratio)
                / profiles.zone_tendency_loading
                for value, zone_strength in zip(
                    log_ratios,
                    zone_calibration_strengths,
                    strict=True,
                )
            )
        else:
            offset_values = (
                calibration_strength
                * contrast_calibration_strengths[0]
                * 15.0
                * (log_ratios[0] - log_ratios[2])
                / profiles.zone_tendency_loading,
                calibration_strength
                * contrast_calibration_strengths[1]
                * 15.0
                * (log_ratios[1] - log_ratios[2])
                / profiles.zone_tendency_loading,
                0.0,
            )
        offsets = tuple(
            max(-maximum_absolute_offset, min(maximum_absolute_offset, round(value)))
            for value in offset_values
        )
        calibrated.append(replace(profile, rating_offsets=cast(tuple[int, int, int], offsets)))
    return replace(
        profiles,
        profile_id=_calibrated_profile_id(
            profiles.profile_id,
            calibration_strength,
            zone_calibration_strengths,
            contrast_calibration_strengths,
        ),
        teams=tuple(calibrated),
    )


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


def _audit_zone_shares(team: TeamDistributionMetrics) -> tuple[float, float, float]:
    by_zone = {item.key: item.share for item in team.shot_zone_shares}
    if set(by_zone) != set(_ZONES):
        raise NbaShotProfileError(f"shot profile baseline zones are incomplete: {team.team_id}")
    shares = tuple(by_zone[zone] for zone in _ZONES)
    if any(not math.isfinite(value) or value <= 0.0 for value in shares):
        raise NbaShotProfileError(f"shot profile baseline shares are invalid: {team.team_id}")
    if not math.isclose(math.fsum(shares), 1.0, abs_tol=1e-9):
        raise NbaShotProfileError(f"shot profile baseline shares do not sum to one: {team.team_id}")
    return cast(tuple[float, float, float], shares)


def _calibrated_profile_id(
    profile_id: str,
    calibration_strength: float,
    zone_strengths: tuple[float, float, float],
    contrast_strengths: tuple[float, float] | None,
) -> str:
    value = f"{profile_id}-baseline-calibrated"
    if calibration_strength != 1.0:
        value += f"-{calibration_strength:g}x"
    if contrast_strengths is not None:
        value += "-contrasts-" + "-".join(f"{strength:g}" for strength in contrast_strengths)
    elif zone_strengths != (1.0, 1.0, 1.0):
        value += "-zones-" + "-".join(f"{strength:g}" for strength in zone_strengths)
    return value


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

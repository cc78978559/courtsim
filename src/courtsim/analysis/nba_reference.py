"""Deterministic conversion of a pinned NBA.com team snapshot into audit targets."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, cast

from courtsim.artifacts import sha256_file


class NbaReferenceError(ValueError):
    pass


TRADITIONAL_COLUMNS = (
    "Team",
    "GP",
    "PTS",
    "FGM",
    "FGA",
    "3PM",
    "3PA",
    "OREB",
    "DREB",
    "AST",
    "TOV",
    "STL",
    "BLK",
)
ADVANCED_COLUMNS = ("TEAM", "GP", "PACE", "POSS")
METRIC_ORDER = (
    "mean_team_possessions",
    "points_per_100_possessions",
    "field_goal_percentage",
    "three_point_percentage",
    "turnover_rate",
    "offensive_rebound_rate",
    "assist_per_field_goal",
    "block_rate",
    "steal_rate",
    "shot_zone_share.THREE",
)
TEAM_METRIC_ORDER = (
    "mean_team_possessions",
    "points_per_100_possessions",
    "field_goal_percentage",
    "three_point_percentage",
    "turnover_rate",
    "assist_per_field_goal",
    "block_rate",
    "steal_rate",
    "shot_zone_share.THREE",
)


def _load_object(path: Path) -> dict[str, Any]:
    try:
        value: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise NbaReferenceError(f"cannot load NBA reference snapshot: {path}") from error
    if not isinstance(value, dict):
        raise NbaReferenceError("NBA reference snapshot root must be an object")
    return cast(dict[str, Any], value)


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise NbaReferenceError(f"{field} must be a non-empty string")
    return value.strip()


def _number(value: object, field: str) -> float:
    text = _text(value, field).replace(",", "")
    try:
        number = float(text)
    except ValueError as error:
        raise NbaReferenceError(f"{field} must be numeric") from error
    if not math.isfinite(number) or number < 0.0:
        raise NbaReferenceError(f"{field} must be finite and non-negative")
    return number


def _table(
    raw: object,
    expected_columns: tuple[str, ...],
    table_name: str,
) -> dict[str, dict[str, float]]:
    if not isinstance(raw, dict) or set(raw) != {"columns", "rows"}:
        raise NbaReferenceError(f"{table_name} table does not match the snapshot contract")
    columns = raw["columns"]
    rows = raw["rows"]
    if columns != list(expected_columns) or not isinstance(rows, list):
        raise NbaReferenceError(f"{table_name} columns do not match the snapshot contract")
    result: dict[str, dict[str, float]] = {}
    for row_index, row in enumerate(rows):
        if not isinstance(row, list) or len(row) != len(expected_columns):
            raise NbaReferenceError(f"{table_name} row {row_index} is invalid")
        team = _text(row[0], f"{table_name}.rows[{row_index}][0]")
        if team in result:
            raise NbaReferenceError(f"{table_name} contains duplicate team: {team}")
        result[team] = {
            column: _number(row[index], f"{table_name}.{team}.{column}")
            for index, column in enumerate(expected_columns[1:], start=1)
        }
    if len(result) != 30:
        raise NbaReferenceError(f"{table_name} must contain exactly 30 NBA teams")
    return result


def _sum(table: dict[str, dict[str, float]], field: str) -> float:
    return math.fsum(row[field] for row in table.values())


def _ratio(numerator: float, denominator: float, metric: str) -> float:
    if denominator <= 0.0:
        raise NbaReferenceError(f"{metric} has a zero denominator")
    return numerator / denominator


def _validated_snapshot(
    snapshot_path: str | Path,
) -> tuple[dict[str, Any], dict[str, dict[str, float]], dict[str, dict[str, float]]]:
    source = Path(snapshot_path)
    raw = _load_object(source)
    expected_root = {
        "format_version",
        "provider",
        "population",
        "season",
        "season_type",
        "retrieved_on",
        "extraction",
        "origins",
        "traditional",
        "advanced",
    }
    if set(raw) != expected_root or raw["format_version"] != 1:
        raise NbaReferenceError("NBA reference snapshot does not match format version 1")
    for field in (
        "provider",
        "population",
        "season",
        "season_type",
        "retrieved_on",
        "extraction",
    ):
        _text(raw[field], field)
    origins = raw["origins"]
    if not isinstance(origins, dict) or set(origins) != {"traditional", "advanced"}:
        raise NbaReferenceError("origins must contain traditional and advanced URLs")
    _text(origins["traditional"], "origins.traditional")
    _text(origins["advanced"], "origins.advanced")

    traditional = _table(raw["traditional"], TRADITIONAL_COLUMNS, "traditional")
    advanced = _table(raw["advanced"], ADVANCED_COLUMNS, "advanced")
    if set(traditional) != set(advanced):
        raise NbaReferenceError("traditional and advanced team sets differ")
    for team in traditional:
        if traditional[team]["GP"] != 82 or advanced[team]["GP"] != 82:
            raise NbaReferenceError(f"{team} must have 82 games in both tables")
    return raw, traditional, advanced


def calculate_nba_core_metrics(snapshot_path: str | Path) -> dict[str, float]:
    """Calculate league metrics using the same event denominators as DistributionAudit."""
    _, traditional, advanced = _validated_snapshot(snapshot_path)

    team_games = _sum(advanced, "GP")
    possessions = _sum(advanced, "POSS")
    field_goals_made = _sum(traditional, "FGM")
    field_goal_attempts = _sum(traditional, "FGA")
    three_made = _sum(traditional, "3PM")
    three_attempts = _sum(traditional, "3PA")
    offensive_rebounds = _sum(traditional, "OREB")
    defensive_rebounds = _sum(traditional, "DREB")
    return {
        "mean_team_possessions": _ratio(
            math.fsum(row["PACE"] * row["GP"] for row in advanced.values()),
            team_games,
            "mean_team_possessions",
        ),
        "points_per_100_possessions": 100.0
        * _ratio(_sum(traditional, "PTS"), possessions, "points_per_100_possessions"),
        "field_goal_percentage": _ratio(
            field_goals_made,
            field_goal_attempts,
            "field_goal_percentage",
        ),
        "three_point_percentage": _ratio(
            three_made,
            three_attempts,
            "three_point_percentage",
        ),
        "turnover_rate": _ratio(_sum(traditional, "TOV"), possessions, "turnover_rate"),
        "offensive_rebound_rate": _ratio(
            offensive_rebounds,
            offensive_rebounds + defensive_rebounds,
            "offensive_rebound_rate",
        ),
        "assist_per_field_goal": _ratio(
            _sum(traditional, "AST"),
            field_goals_made,
            "assist_per_field_goal",
        ),
        "block_rate": _ratio(
            _sum(traditional, "BLK"),
            field_goal_attempts,
            "block_rate",
        ),
        "steal_rate": _ratio(_sum(traditional, "STL"), possessions, "steal_rate"),
        "shot_zone_share.THREE": _ratio(
            three_attempts,
            field_goal_attempts,
            "shot_zone_share.THREE",
        ),
    }


def calculate_nba_team_metrics(
    snapshot_path: str | Path,
    team: str,
) -> dict[str, float]:
    """Calculate a team's observable style vector from the pinned team snapshot."""
    _, traditional, advanced = _validated_snapshot(snapshot_path)
    if team not in traditional:
        raise NbaReferenceError(f"unknown NBA team: {team}")
    traditional_row = traditional[team]
    advanced_row = advanced[team]
    field_goals_made = traditional_row["FGM"]
    field_goal_attempts = traditional_row["FGA"]
    three_attempts = traditional_row["3PA"]
    possessions = advanced_row["POSS"]
    return {
        "mean_team_possessions": advanced_row["PACE"],
        "points_per_100_possessions": 100.0
        * _ratio(
            traditional_row["PTS"],
            possessions,
            "points_per_100_possessions",
        ),
        "field_goal_percentage": _ratio(
            field_goals_made,
            field_goal_attempts,
            "field_goal_percentage",
        ),
        "three_point_percentage": _ratio(
            traditional_row["3PM"],
            three_attempts,
            "three_point_percentage",
        ),
        "turnover_rate": _ratio(
            traditional_row["TOV"],
            possessions,
            "turnover_rate",
        ),
        "assist_per_field_goal": _ratio(
            traditional_row["AST"],
            field_goals_made,
            "assist_per_field_goal",
        ),
        "block_rate": _ratio(
            traditional_row["BLK"],
            field_goal_attempts,
            "block_rate",
        ),
        "steal_rate": _ratio(
            traditional_row["STL"],
            possessions,
            "steal_rate",
        ),
        "shot_zone_share.THREE": _ratio(
            three_attempts,
            field_goal_attempts,
            "shot_zone_share.THREE",
        ),
    }


def build_nba_core_target_payload(
    snapshot_path: str | Path,
    *,
    artifact_path: str,
    tolerance: float = 0.05,
) -> dict[str, object]:
    """Build an active target set with an explicit relative calibration envelope."""
    if not math.isfinite(tolerance) or not 0.0 < tolerance < 1.0:
        raise NbaReferenceError("tolerance must be between 0 and 1")
    portable_artifact = Path(artifact_path)
    if portable_artifact.is_absolute() or ".." in portable_artifact.parts:
        raise NbaReferenceError("artifact_path must be portable and cannot contain '..'")

    source = Path(snapshot_path)
    raw, _, _ = _validated_snapshot(source)
    metrics = calculate_nba_core_metrics(source)
    origins = cast(dict[str, object], raw["origins"])
    source_id = "nba-com-team-core-2024-25"
    return {
        "format_version": 1,
        "target_set_id": "nba-2024-25-regular-season-core-v1",
        "status": "active",
        "population": "NBA 2024-25 regular season, all 30 teams and 2,460 team-games",
        "season": "2024-25",
        "notes": (
            "Core event-denominator targets derived deterministically from the pinned "
            "NBA.com table projection. Bounds are an initial "
            f"+/-{tolerance:.2%} relative calibration "
            "envelope, not sampling confidence intervals. PACE is the official normalized "
            "pace field; all other ratios use totals matching DistributionAudit."
        ),
        "sources": [
            {
                "source_id": source_id,
                "label": "NBA.com 2024-25 team traditional and advanced table projection",
                "origin": (
                    f"{_text(origins['traditional'], 'origins.traditional')} | "
                    f"{_text(origins['advanced'], 'origins.advanced')}"
                ),
                "artifact_path": portable_artifact.as_posix(),
                "retrieved_on": _text(raw["retrieved_on"], "retrieved_on"),
                "content_sha256": sha256_file(source),
            }
        ],
        "metrics": [
            {
                "metric": metric,
                "lower": round(metrics[metric] * (1.0 - tolerance), 12),
                "target": round(metrics[metric], 12),
                "upper": round(metrics[metric] * (1.0 + tolerance), 12),
                "weight": 1.0,
                "required": True,
                "source_id": source_id,
            }
            for metric in METRIC_ORDER
        ],
        "planned_metrics": [],
    }


def build_nba_team_target_payload(
    snapshot_path: str | Path,
    *,
    team: str,
    artifact_path: str,
    metrics: tuple[str, ...] = TEAM_METRIC_ORDER,
    tolerance: float = 0.075,
    audit_team_id: str | None = None,
) -> dict[str, object]:
    """Build a source-pinned target subset for one team's observable style."""
    if not math.isfinite(tolerance) or not 0.0 < tolerance < 1.0:
        raise NbaReferenceError("tolerance must be between 0 and 1")
    portable_artifact = Path(artifact_path)
    if portable_artifact.is_absolute() or ".." in portable_artifact.parts:
        raise NbaReferenceError("artifact_path must be portable and cannot contain '..'")
    if not metrics or len(metrics) != len(set(metrics)):
        raise NbaReferenceError("team target metrics must be non-empty and unique")
    unknown_metrics = sorted(set(metrics) - set(TEAM_METRIC_ORDER))
    if unknown_metrics:
        raise NbaReferenceError(f"unsupported team target metrics: {unknown_metrics}")
    if audit_team_id is not None and (
        not audit_team_id or any(character in audit_team_id for character in ". ")
    ):
        raise NbaReferenceError("audit_team_id must be a compact metric path segment")

    source = Path(snapshot_path)
    raw, _, _ = _validated_snapshot(source)
    values = calculate_nba_team_metrics(source, team)
    origins = cast(dict[str, object], raw["origins"])
    slug = team.lower().replace(" ", "-")
    source_id = "nba-com-team-core-2024-25"
    return {
        "format_version": 1,
        "target_set_id": (
            f"nba-2024-25-{slug}-{audit_team_id}-style-v1"
            if audit_team_id is not None
            else f"nba-2024-25-{slug}-style-v1"
        ),
        "status": "active",
        "population": f"{team}, NBA 2024-25 regular season, 82 team-games",
        "season": "2024-25",
        "notes": (
            "Selected observable team-style targets derived deterministically from the "
            "pinned NBA.com team tables. Bounds are an initial "
            f"+/-{tolerance:.2%} relative representation envelope, not sampling "
            "confidence intervals. A symmetric self-play simulation is only a style "
            "proxy and is not a claim to reproduce this real team."
        ),
        "sources": [
            {
                "source_id": source_id,
                "label": "NBA.com 2024-25 team traditional and advanced table projection",
                "origin": (
                    f"{_text(origins['traditional'], 'origins.traditional')} | "
                    f"{_text(origins['advanced'], 'origins.advanced')}"
                ),
                "artifact_path": portable_artifact.as_posix(),
                "retrieved_on": _text(raw["retrieved_on"], "retrieved_on"),
                "content_sha256": sha256_file(source),
            }
        ],
        "metrics": [
            {
                "metric": (
                    f"team.{audit_team_id}.{metric}" if audit_team_id is not None else metric
                ),
                "lower": round(values[metric] * (1.0 - tolerance), 12),
                "target": round(values[metric], 12),
                "upper": round(values[metric] * (1.0 + tolerance), 12),
                "weight": 1.0,
                "required": True,
                "source_id": source_id,
            }
            for metric in metrics
        ],
        "planned_metrics": [],
    }

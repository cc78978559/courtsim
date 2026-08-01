"""Baseline differences and explicit scalar range gates."""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, cast

from courtsim.analysis.distribution import (
    DistributionAudit,
    PlayerFoulShare,
    PlayerUsageShare,
    ShareMetric,
    TeamDistributionMetrics,
)


class AuditGateError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class AuditMetricDifference:
    metric: str
    baseline: float
    current: float
    absolute_delta: float
    relative_delta: float | None


@dataclass(frozen=True, slots=True)
class AuditComparison:
    differences: tuple[AuditMetricDifference, ...]


@dataclass(frozen=True, slots=True)
class AuditGate:
    metric: str
    minimum: float
    maximum: float


@dataclass(frozen=True, slots=True)
class AuditGateFinding:
    metric: str
    value: float
    minimum: float
    maximum: float


@dataclass(frozen=True, slots=True)
class AuditGateReport:
    gate_kind: str
    checked: int
    findings: tuple[AuditGateFinding, ...]

    @property
    def passed(self) -> bool:
        return not self.findings


def _load_json(path: str | Path) -> dict[str, Any]:
    source = Path(path)
    try:
        value: object = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise AuditGateError(f"cannot load {source}") from error
    if not isinstance(value, dict):
        raise AuditGateError(f"{source} must contain an object")
    return cast(dict[str, Any], value)


def _number(value: object, field: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise AuditGateError(f"{field} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise AuditGateError(f"{field} must be finite")
    return result


def _share_metrics(value: object, field: str) -> tuple[ShareMetric, ...]:
    if not isinstance(value, list):
        raise AuditGateError(f"{field} must be a list")
    result: list[ShareMetric] = []
    for index, raw in enumerate(value):
        if not isinstance(raw, dict) or set(raw) != {"key", "count", "share"}:
            raise AuditGateError(f"{field}[{index}] is invalid")
        key, count = raw["key"], raw["count"]
        if (
            not isinstance(key, str)
            or not key
            or not isinstance(count, int)
            or isinstance(count, bool)
            or count < 0
        ):
            raise AuditGateError(f"{field}[{index}] is invalid")
        result.append(ShareMetric(key, count, _number(raw["share"], f"{field}.share")))
    return tuple(result)


def load_distribution_audit(path: str | Path) -> DistributionAudit:
    raw = _load_json(path)
    scalar_ints = {
        "games",
        "completed_games",
        "aborted_games",
        "completed_possessions",
    }
    scalar_floats = {
        "mean_team_score",
        "team_score_stddev",
        "mean_team_possessions",
        "points_per_100_possessions",
        "field_goal_percentage",
        "three_point_percentage",
        "turnover_rate",
        "offensive_rebound_rate",
        "assist_per_field_goal",
        "block_rate",
        "steal_rate",
    }
    foul_floats = {
        "free_throw_percentage",
        "free_throw_attempt_rate",
        "shooting_foul_rate",
        "free_throw_points_per_100_possessions",
        "field_goal_attempts_per_100_possessions",
    }
    common_foul_floats = {
        "non_shooting_foul_rate",
        "bonus_non_shooting_foul_rate",
        "defensive_foul_rate",
    }
    late_tempo_ints = {
        "late_game_trailing_possessions",
        "late_game_neutral_possessions",
        "late_game_leading_possessions",
    }
    strategy_ints = {
        "two_for_one_possessions",
        "intentional_foul_opportunities",
    }
    formal_strategy_ints = {
        "intentional_fouls_committed",
        "intentional_foul_continuations",
    }
    legacy_formal_strategy_ints = {"intentional_fouls_committed"}
    late_tempo_floats = {
        "late_game_trailing_mean_observed_seconds",
        "late_game_neutral_mean_observed_seconds",
        "late_game_leading_mean_observed_seconds",
    }
    strategy_floats = {
        "two_for_one_mean_observed_seconds",
    }
    formal_strategy_floats = {"intentional_foul_mean_observed_seconds"}
    tempo_ints = late_tempo_ints | strategy_ints
    tempo_floats = late_tempo_floats | strategy_floats
    share_fields = {
        "shot_zone_shares",
        "play_family_shares",
        "coverage_shares",
    }
    expanded_share_fields = {
        "route_shares",
        "creation_mode_shares",
        "tactical_action_shares",
    }
    expanded_present = set(raw) & expanded_share_fields
    if expanded_present and expanded_present != expanded_share_fields:
        raise AuditGateError("expanded tactical audit shares must be complete")
    expected = scalar_ints | scalar_floats | share_fields | {"player_usage_shares"}
    comparable_fields = frozenset(set(raw) - expanded_share_fields)
    if comparable_fields not in {
        frozenset(expected),
        frozenset(expected | foul_floats),
        frozenset(expected | foul_floats | common_foul_floats),
        frozenset(expected | foul_floats | common_foul_floats | {"player_foul_shares"}),
        frozenset(
            expected | foul_floats | common_foul_floats | {"player_foul_shares", "team_metrics"}
        ),
        frozenset(
            expected
            | foul_floats
            | common_foul_floats
            | {"player_foul_shares", "team_metrics"}
            | late_tempo_ints
            | late_tempo_floats
        ),
        frozenset(
            expected
            | foul_floats
            | common_foul_floats
            | {"player_foul_shares", "team_metrics"}
            | tempo_ints
            | tempo_floats
        ),
        frozenset(
            expected
            | foul_floats
            | common_foul_floats
            | {"player_foul_shares", "team_metrics"}
            | tempo_ints
            | tempo_floats
            | formal_strategy_ints
            | formal_strategy_floats
        ),
        frozenset(
            expected
            | foul_floats
            | common_foul_floats
            | {"player_foul_shares", "team_metrics"}
            | tempo_ints
            | tempo_floats
            | legacy_formal_strategy_ints
            | formal_strategy_floats
        ),
    }:
        raise AuditGateError("audit fields do not match the v1 contract")
    integers: dict[str, int] = {}
    for field in scalar_ints:
        value = raw[field]
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise AuditGateError(f"{field} must be a non-negative integer")
        integers[field] = value
    floats = {field: _number(raw[field], field) for field in scalar_floats}
    foul_metrics = {
        field: _number(raw[field], field) if field in raw else 0.0 for field in foul_floats
    }
    common_foul_metrics = {
        field: _number(raw[field], field) if field in raw else 0.0 for field in common_foul_floats
    }
    tempo_integer_metrics: dict[str, int] = {}
    for field in tempo_ints:
        value = raw.get(field, 0)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise AuditGateError(f"{field} must be a non-negative integer")
        tempo_integer_metrics[field] = value
    tempo_float_metrics = {
        field: _number(raw[field], field) if field in raw else 0.0 for field in tempo_floats
    }
    formal_strategy_integer_metrics: dict[str, int] = {}
    for field in formal_strategy_ints:
        value = raw.get(field, 0)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise AuditGateError(f"{field} must be a non-negative integer")
        formal_strategy_integer_metrics[field] = value
    formal_strategy_float_metrics = {
        field: _number(raw[field], field) if field in raw else 0.0
        for field in formal_strategy_floats
    }
    usage_raw = raw["player_usage_shares"]
    if not isinstance(usage_raw, list):
        raise AuditGateError("player_usage_shares must be a list")
    usage: list[PlayerUsageShare] = []
    for index, item in enumerate(usage_raw):
        if not isinstance(item, dict) or set(item) != {
            "team_id",
            "player_id",
            "usage_events",
            "share",
        }:
            raise AuditGateError(f"player_usage_shares[{index}] is invalid")
        if (
            not isinstance(item["team_id"], str)
            or not item["team_id"]
            or not isinstance(item["player_id"], int)
            or isinstance(item["player_id"], bool)
            or not isinstance(item["usage_events"], int)
            or isinstance(item["usage_events"], bool)
        ):
            raise AuditGateError(f"player_usage_shares[{index}] is invalid")
        usage.append(
            PlayerUsageShare(
                item["team_id"],
                item["player_id"],
                item["usage_events"],
                _number(item["share"], f"player_usage_shares[{index}].share"),
            )
        )
    foul_share_raw = raw.get("player_foul_shares", [])
    if not isinstance(foul_share_raw, list):
        raise AuditGateError("player_foul_shares must be a list")
    foul_shares: list[PlayerFoulShare] = []
    for index, item in enumerate(foul_share_raw):
        legacy_keys = {"team_id", "player_id", "foul_events", "share"}
        current_keys = legacy_keys | {"fouls_per_100_defensive_possessions"}
        if not isinstance(item, dict) or (set(item) != legacy_keys and set(item) != current_keys):
            raise AuditGateError(f"player_foul_shares[{index}] is invalid")
        if (
            not isinstance(item["team_id"], str)
            or not item["team_id"]
            or not isinstance(item["player_id"], int)
            or isinstance(item["player_id"], bool)
            or not isinstance(item["foul_events"], int)
            or isinstance(item["foul_events"], bool)
            or item["foul_events"] < 0
        ):
            raise AuditGateError(f"player_foul_shares[{index}] is invalid")
        foul_shares.append(
            PlayerFoulShare(
                item["team_id"],
                item["player_id"],
                item["foul_events"],
                _number(item["share"], f"player_foul_shares[{index}].share"),
                (
                    _number(
                        item["fouls_per_100_defensive_possessions"],
                        (f"player_foul_shares[{index}].fouls_per_100_defensive_possessions"),
                    )
                    if "fouls_per_100_defensive_possessions" in item
                    else 0.0
                ),
            )
        )
    team_metrics_raw = raw.get("team_metrics", [])
    if not isinstance(team_metrics_raw, list):
        raise AuditGateError("team_metrics must be a list")
    team_metrics: list[TeamDistributionMetrics] = []
    team_metric_fields = {
        "team_id",
        "possessions",
        "mean_team_possessions",
        "points_per_100_possessions",
        "field_goal_percentage",
        "three_point_percentage",
        "turnover_rate",
        "assist_per_field_goal",
        "block_rate",
        "steal_rate",
        "shot_zone_shares",
    }
    expanded_team_metric_fields = {
        "route_shares",
        "creation_mode_shares",
        "tactical_action_shares",
    }
    for index, item in enumerate(team_metrics_raw):
        if not isinstance(item, dict) or frozenset(item) not in {
            frozenset(team_metric_fields),
            frozenset(team_metric_fields | expanded_team_metric_fields),
        }:
            raise AuditGateError(f"team_metrics[{index}] is invalid")
        team_id = item["team_id"]
        possessions = item["possessions"]
        if (
            not isinstance(team_id, str)
            or not team_id
            or not isinstance(possessions, int)
            or isinstance(possessions, bool)
            or possessions < 0
        ):
            raise AuditGateError(f"team_metrics[{index}] is invalid")
        team_metrics.append(
            TeamDistributionMetrics(
                team_id=team_id,
                possessions=possessions,
                mean_team_possessions=_number(
                    item["mean_team_possessions"],
                    f"team_metrics[{index}].mean_team_possessions",
                ),
                points_per_100_possessions=_number(
                    item["points_per_100_possessions"],
                    f"team_metrics[{index}].points_per_100_possessions",
                ),
                field_goal_percentage=_number(
                    item["field_goal_percentage"],
                    f"team_metrics[{index}].field_goal_percentage",
                ),
                three_point_percentage=_number(
                    item["three_point_percentage"],
                    f"team_metrics[{index}].three_point_percentage",
                ),
                turnover_rate=_number(
                    item["turnover_rate"],
                    f"team_metrics[{index}].turnover_rate",
                ),
                assist_per_field_goal=_number(
                    item["assist_per_field_goal"],
                    f"team_metrics[{index}].assist_per_field_goal",
                ),
                block_rate=_number(
                    item["block_rate"],
                    f"team_metrics[{index}].block_rate",
                ),
                steal_rate=_number(
                    item["steal_rate"],
                    f"team_metrics[{index}].steal_rate",
                ),
                shot_zone_shares=_share_metrics(
                    item["shot_zone_shares"],
                    f"team_metrics[{index}].shot_zone_shares",
                ),
                route_shares=_share_metrics(
                    item.get("route_shares", []),
                    f"team_metrics[{index}].route_shares",
                ),
                creation_mode_shares=_share_metrics(
                    item.get("creation_mode_shares", []),
                    f"team_metrics[{index}].creation_mode_shares",
                ),
                tactical_action_shares=_share_metrics(
                    item.get("tactical_action_shares", []),
                    f"team_metrics[{index}].tactical_action_shares",
                ),
            )
        )
    return DistributionAudit(
        games=integers["games"],
        completed_games=integers["completed_games"],
        aborted_games=integers["aborted_games"],
        completed_possessions=integers["completed_possessions"],
        mean_team_score=floats["mean_team_score"],
        team_score_stddev=floats["team_score_stddev"],
        mean_team_possessions=floats["mean_team_possessions"],
        points_per_100_possessions=floats["points_per_100_possessions"],
        field_goal_percentage=floats["field_goal_percentage"],
        three_point_percentage=floats["three_point_percentage"],
        turnover_rate=floats["turnover_rate"],
        offensive_rebound_rate=floats["offensive_rebound_rate"],
        assist_per_field_goal=floats["assist_per_field_goal"],
        block_rate=floats["block_rate"],
        steal_rate=floats["steal_rate"],
        shot_zone_shares=_share_metrics(raw["shot_zone_shares"], "shot_zone_shares"),
        play_family_shares=_share_metrics(raw["play_family_shares"], "play_family_shares"),
        coverage_shares=_share_metrics(raw["coverage_shares"], "coverage_shares"),
        player_usage_shares=tuple(usage),
        free_throw_percentage=foul_metrics["free_throw_percentage"],
        free_throw_attempt_rate=foul_metrics["free_throw_attempt_rate"],
        shooting_foul_rate=foul_metrics["shooting_foul_rate"],
        free_throw_points_per_100_possessions=foul_metrics["free_throw_points_per_100_possessions"],
        field_goal_attempts_per_100_possessions=foul_metrics[
            "field_goal_attempts_per_100_possessions"
        ],
        non_shooting_foul_rate=common_foul_metrics["non_shooting_foul_rate"],
        bonus_non_shooting_foul_rate=common_foul_metrics["bonus_non_shooting_foul_rate"],
        defensive_foul_rate=common_foul_metrics["defensive_foul_rate"],
        player_foul_shares=tuple(foul_shares),
        team_metrics=tuple(team_metrics),
        late_game_trailing_possessions=tempo_integer_metrics["late_game_trailing_possessions"],
        late_game_neutral_possessions=tempo_integer_metrics["late_game_neutral_possessions"],
        late_game_leading_possessions=tempo_integer_metrics["late_game_leading_possessions"],
        late_game_trailing_mean_observed_seconds=tempo_float_metrics[
            "late_game_trailing_mean_observed_seconds"
        ],
        late_game_neutral_mean_observed_seconds=tempo_float_metrics[
            "late_game_neutral_mean_observed_seconds"
        ],
        late_game_leading_mean_observed_seconds=tempo_float_metrics[
            "late_game_leading_mean_observed_seconds"
        ],
        two_for_one_possessions=tempo_integer_metrics["two_for_one_possessions"],
        two_for_one_mean_observed_seconds=tempo_float_metrics["two_for_one_mean_observed_seconds"],
        intentional_foul_opportunities=tempo_integer_metrics["intentional_foul_opportunities"],
        intentional_fouls_committed=formal_strategy_integer_metrics["intentional_fouls_committed"],
        intentional_foul_continuations=formal_strategy_integer_metrics[
            "intentional_foul_continuations"
        ],
        intentional_foul_mean_observed_seconds=formal_strategy_float_metrics[
            "intentional_foul_mean_observed_seconds"
        ],
        route_shares=_share_metrics(raw.get("route_shares", []), "route_shares"),
        creation_mode_shares=_share_metrics(
            raw.get("creation_mode_shares", []), "creation_mode_shares"
        ),
        tactical_action_shares=_share_metrics(
            raw.get("tactical_action_shares", []), "tactical_action_shares"
        ),
    )


def audit_metric_map(audit: DistributionAudit) -> dict[str, float]:
    metrics = {
        "games": float(audit.games),
        "completed_games": float(audit.completed_games),
        "aborted_games": float(audit.aborted_games),
        "completed_possessions": float(audit.completed_possessions),
        "mean_team_score": audit.mean_team_score,
        "team_score_stddev": audit.team_score_stddev,
        "mean_team_possessions": audit.mean_team_possessions,
        "points_per_100_possessions": audit.points_per_100_possessions,
        "field_goal_percentage": audit.field_goal_percentage,
        "three_point_percentage": audit.three_point_percentage,
        "turnover_rate": audit.turnover_rate,
        "offensive_rebound_rate": audit.offensive_rebound_rate,
        "assist_per_field_goal": audit.assist_per_field_goal,
        "block_rate": audit.block_rate,
        "steal_rate": audit.steal_rate,
        "free_throw_percentage": audit.free_throw_percentage,
        "free_throw_attempt_rate": audit.free_throw_attempt_rate,
        "shooting_foul_rate": audit.shooting_foul_rate,
        "free_throw_points_per_100_possessions": (audit.free_throw_points_per_100_possessions),
        "field_goal_attempts_per_100_possessions": (audit.field_goal_attempts_per_100_possessions),
        "non_shooting_foul_rate": audit.non_shooting_foul_rate,
        "bonus_non_shooting_foul_rate": audit.bonus_non_shooting_foul_rate,
        "defensive_foul_rate": audit.defensive_foul_rate,
        "late_game_trailing_possessions": float(audit.late_game_trailing_possessions),
        "late_game_neutral_possessions": float(audit.late_game_neutral_possessions),
        "late_game_leading_possessions": float(audit.late_game_leading_possessions),
        "late_game_trailing_mean_observed_seconds": (
            audit.late_game_trailing_mean_observed_seconds
        ),
        "late_game_neutral_mean_observed_seconds": (audit.late_game_neutral_mean_observed_seconds),
        "late_game_leading_mean_observed_seconds": (audit.late_game_leading_mean_observed_seconds),
        "two_for_one_possessions": float(audit.two_for_one_possessions),
        "two_for_one_mean_observed_seconds": audit.two_for_one_mean_observed_seconds,
        "intentional_foul_opportunities": float(audit.intentional_foul_opportunities),
        "intentional_fouls_committed": float(audit.intentional_fouls_committed),
        "intentional_foul_continuations": float(audit.intentional_foul_continuations),
        "intentional_foul_mean_observed_seconds": (audit.intentional_foul_mean_observed_seconds),
    }
    for prefix, shares in (
        ("shot_zone_share", audit.shot_zone_shares),
        ("play_family_share", audit.play_family_shares),
        ("coverage_share", audit.coverage_shares),
        ("route_share", audit.route_shares),
        ("creation_mode_share", audit.creation_mode_shares),
        ("tactical_action_share", audit.tactical_action_shares),
    ):
        for item in shares:
            metrics[f"{prefix}.{item.key}"] = item.share
    for usage_item in audit.player_usage_shares:
        metrics[f"player_usage_share.{usage_item.team_id}.{usage_item.player_id}"] = (
            usage_item.share
        )
    for foul_item in audit.player_foul_shares:
        metrics[f"player_foul_share.{foul_item.team_id}.{foul_item.player_id}"] = foul_item.share
        metrics[
            (
                "player_fouls_per_100_defensive_possessions."
                f"{foul_item.team_id}.{foul_item.player_id}"
            )
        ] = foul_item.fouls_per_100_defensive_possessions
    for team in audit.team_metrics:
        prefix = f"team.{team.team_id}"
        metrics[f"{prefix}.mean_team_possessions"] = team.mean_team_possessions
        metrics[f"{prefix}.points_per_100_possessions"] = team.points_per_100_possessions
        metrics[f"{prefix}.field_goal_percentage"] = team.field_goal_percentage
        metrics[f"{prefix}.three_point_percentage"] = team.three_point_percentage
        metrics[f"{prefix}.turnover_rate"] = team.turnover_rate
        metrics[f"{prefix}.assist_per_field_goal"] = team.assist_per_field_goal
        metrics[f"{prefix}.block_rate"] = team.block_rate
        metrics[f"{prefix}.steal_rate"] = team.steal_rate
        for zone in team.shot_zone_shares:
            metrics[f"{prefix}.shot_zone_share.{zone.key}"] = zone.share
        for metric_prefix, shares in (
            ("route_share", team.route_shares),
            ("creation_mode_share", team.creation_mode_shares),
            ("tactical_action_share", team.tactical_action_shares),
        ):
            for item in shares:
                metrics[f"{prefix}.{metric_prefix}.{item.key}"] = item.share
    return metrics


def compare_distribution_audits(
    baseline: DistributionAudit,
    current: DistributionAudit,
) -> AuditComparison:
    baseline_metrics = audit_metric_map(baseline)
    current_metrics = audit_metric_map(current)
    metric_names = set(baseline_metrics) | set(current_metrics)
    missing = sorted(set(baseline_metrics) ^ set(current_metrics))
    dynamic_prefixes = (
        "player_foul_share.",
        "player_fouls_per_100_defensive_possessions.",
        "team.",
    )
    if any(not metric.startswith(dynamic_prefixes) for metric in missing):
        raise AuditGateError(f"audit metric sets differ: {missing}")
    return AuditComparison(
        tuple(
            AuditMetricDifference(
                metric,
                baseline_metrics.get(metric, 0.0),
                current_metrics.get(metric, 0.0),
                current_metrics.get(metric, 0.0) - baseline_metrics.get(metric, 0.0),
                (
                    (current_metrics.get(metric, 0.0) - baseline_metrics.get(metric, 0.0))
                    / abs(baseline_metrics.get(metric, 0.0))
                    if baseline_metrics.get(metric, 0.0) != 0.0
                    else None
                ),
            )
            for metric in sorted(metric_names)
        )
    )


def load_audit_gates(path: str | Path) -> tuple[str, tuple[AuditGate, ...]]:
    raw = _load_json(path)
    if set(raw) != {"format_version", "kind", "gates"} or raw["format_version"] != 1:
        raise AuditGateError("gate file does not match the v1 contract")
    kind = raw["kind"]
    gates_raw = raw["gates"]
    if not isinstance(kind, str) or not kind or not isinstance(gates_raw, list):
        raise AuditGateError("gate kind and gates are invalid")
    gates: list[AuditGate] = []
    for index, item in enumerate(gates_raw):
        if not isinstance(item, dict) or set(item) != {"metric", "minimum", "maximum"}:
            raise AuditGateError(f"gates[{index}] is invalid")
        metric = item["metric"]
        if not isinstance(metric, str) or not metric:
            raise AuditGateError(f"gates[{index}].metric is invalid")
        minimum = _number(item["minimum"], f"gates[{index}].minimum")
        maximum = _number(item["maximum"], f"gates[{index}].maximum")
        if minimum > maximum:
            raise AuditGateError(f"gates[{index}] has inverted bounds")
        gates.append(AuditGate(metric, minimum, maximum))
    if len({gate.metric for gate in gates}) != len(gates):
        raise AuditGateError("gate metrics must be unique")
    return kind, tuple(gates)


def evaluate_audit_gates(
    audit: DistributionAudit,
    gate_kind: str,
    gates: tuple[AuditGate, ...],
) -> AuditGateReport:
    metrics = audit_metric_map(audit)
    unknown = sorted(gate.metric for gate in gates if gate.metric not in metrics)
    if unknown:
        raise AuditGateError(f"unknown gate metrics: {unknown}")
    findings = tuple(
        AuditGateFinding(gate.metric, metrics[gate.metric], gate.minimum, gate.maximum)
        for gate in gates
        if not gate.minimum <= metrics[gate.metric] <= gate.maximum
    )
    return AuditGateReport(gate_kind, len(gates), findings)


def audit_comparison_to_json(comparison: AuditComparison) -> str:
    return json.dumps(
        asdict(comparison),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def audit_gate_report_to_json(report: AuditGateReport) -> str:
    return json.dumps(
        asdict(report),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )

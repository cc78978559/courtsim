"""Player-level simulation audit and multi-seed realism evaluation."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast

from courtsim.analysis.nba_player_aggregates import NBAPlayerSeasonAggregate
from courtsim.analysis.nba_player_targets import NBAPlayerTargetSet, load_nba_player_target_set
from courtsim.artifacts import sha256_file
from courtsim.domain.enums import ShotZone
from courtsim.domain.game import GameClockConfig, GameResult
from courtsim.domain.game_serialization import game_result_from_dict
from courtsim.domain.results import (
    BlockedShotSegmentResult,
    MadeShotSegmentResult,
    MissedShotSegmentResult,
    ShootingFoulSegmentResult,
)
from courtsim.stats.attribution import StatCode
from courtsim.verification import verify_manifest

NBA_PLAYER_AUDIT_VERSION = "nba-player-audit-v1"
NBA_PLAYER_EVALUATION_VERSION = "nba-player-evaluation-v1"
NBA_PLAYER_REALITY_GATE_VERSION = "nba-player-reality-gate-v1"
_ZONES = tuple(ShotZone)
_METRICS = (
    "minutes_per_game",
    "usage_rate",
    "true_shooting_percentage",
    "field_goal_attempt_share",
    "shot_zone_share.RIM",
    "shot_zone_share.MIDRANGE",
    "shot_zone_share.THREE",
    "shot_zone_percentage.RIM",
    "shot_zone_percentage.MIDRANGE",
    "shot_zone_percentage.THREE",
)


class NbaPlayerEvaluationError(ValueError):
    pass


def build_nba_player_audit_from_bundle(
    manifest_path: str | Path,
    target_path: str | Path,
    identity_path: str | Path,
) -> dict[str, object]:
    """Verify a full-trace model-audit bundle and build its player audit."""
    manifest_file = Path(manifest_path).resolve()
    targets_file = Path(target_path).resolve()
    identity_file = Path(identity_path).resolve()
    verification = verify_manifest(manifest_file)
    if not verification.ok:
        raise NbaPlayerEvaluationError("model-audit bundle verification failed")
    manifest = _load_object_file(manifest_file, "model-audit manifest")
    if manifest.get("kind") != "courtsim-model-distribution-audit":
        raise NbaPlayerEvaluationError("player audit requires a model-audit bundle")
    clock = _game_clock(manifest.get("clock"))
    games_path = _declared_games_path(manifest_file, manifest.get("outputs"))
    targets = load_nba_player_target_set(targets_file)
    identities = load_courtsim_identity_map(identity_file, targets)
    audit = audit_nba_player_results(_read_game_results(games_path, clock), targets, identities)
    audit["sources"] = {
        "manifest": {"path": manifest_file.name, "sha256": sha256_file(manifest_file)},
        "games": {"path": games_path.name, "sha256": sha256_file(games_path)},
        "targets": {"path": targets_file.name, "sha256": sha256_file(targets_file)},
        "identity": {"path": identity_file.name, "sha256": sha256_file(identity_file)},
    }
    return audit


def audit_nba_player_results(
    results: tuple[GameResult, ...],
    targets: NBAPlayerTargetSet,
    nba_to_courtsim_ids: Mapping[int, int],
) -> dict[str, object]:
    """Measure target players from canonical game results and playing-time ledgers."""
    completed = tuple(item for item in results if item.completed)
    if not completed or len(completed) != len(results):
        raise NbaPlayerEvaluationError("player audit requires only completed games")
    target_ids = {item.nba_player_id for item in targets.players}
    if set(nba_to_courtsim_ids) != target_ids:
        raise NbaPlayerEvaluationError("player audit identity map must exactly cover targets")
    courtsim_ids = tuple(nba_to_courtsim_ids[item] for item in sorted(target_ids))
    if len(courtsim_ids) != len(set(courtsim_ids)) or any(
        not isinstance(item, int) or isinstance(item, bool) or item < 0 for item in courtsim_ids
    ):
        raise NbaPlayerEvaluationError("player audit CourtSim ids must be unique non-negative ids")

    stats: dict[tuple[int, StatCode], int] = {}
    seconds: dict[int, int] = {}
    appearances: dict[int, int] = {}
    player_team: dict[int, str] = {}
    team_minutes: dict[str, float] = {}
    team_stats: dict[tuple[str, StatCode], int] = {}
    zone_attempts: dict[tuple[int, ShotZone], int] = {}
    zone_makes: dict[tuple[int, ShotZone], int] = {}
    for game in completed:
        teams_by_player: dict[int, str] = {}
        for playing_time in game.playing_time:
            teams_by_player[playing_time.player_id] = playing_time.team_id
            team_minutes[playing_time.team_id] = (
                team_minutes.get(playing_time.team_id, 0.0) + playing_time.seconds / 60.0
            )
            if playing_time.player_id in courtsim_ids and playing_time.seconds > 0:
                previous = player_team.setdefault(playing_time.player_id, playing_time.team_id)
                if previous != playing_time.team_id:
                    raise NbaPlayerEvaluationError("player audit does not support in-batch trades")
                seconds[playing_time.player_id] = (
                    seconds.get(playing_time.player_id, 0) + playing_time.seconds
                )
                appearances[playing_time.player_id] = appearances.get(playing_time.player_id, 0) + 1
        for delta in game.player_stats:
            stats[(delta.player_id, delta.stat)] = (
                stats.get((delta.player_id, delta.stat), 0) + delta.amount
            )
            team_id = teams_by_player.get(delta.player_id)
            if team_id is None:
                raise NbaPlayerEvaluationError("player stats lack a playing-time team identity")
            team_stats[(team_id, delta.stat)] = (
                team_stats.get((team_id, delta.stat), 0) + delta.amount
            )
        for aggregate in game.player_shot_zones:
            zone_attempts[(aggregate.player_id, aggregate.zone)] = (
                zone_attempts.get((aggregate.player_id, aggregate.zone), 0) + aggregate.attempts
            )
            zone_makes[(aggregate.player_id, aggregate.zone)] = (
                zone_makes.get((aggregate.player_id, aggregate.zone), 0) + aggregate.makes
            )
        for possession in () if game.player_shot_zones else game.possessions:
            for segment in possession.result.segments:
                if not isinstance(
                    segment,
                    (
                        MadeShotSegmentResult,
                        MissedShotSegmentResult,
                        BlockedShotSegmentResult,
                        ShootingFoulSegmentResult,
                    ),
                ):
                    continue
                if isinstance(segment, ShootingFoulSegmentResult) and not segment.field_goal_made:
                    continue
                shooter = segment.selection.finisher_id
                zone = segment.zone
                zone_attempts[(shooter, zone)] = zone_attempts.get((shooter, zone), 0) + 1
                made = isinstance(segment, MadeShotSegmentResult) or (
                    isinstance(segment, ShootingFoulSegmentResult) and segment.field_goal_made
                )
                if made:
                    zone_makes[(shooter, zone)] = zone_makes.get((shooter, zone), 0) + 1

    players: list[dict[str, object]] = []
    for target in targets.players:
        player_id = nba_to_courtsim_ids[target.nba_player_id]
        games = appearances.get(player_id, 0)
        minutes = seconds.get(player_id, 0) / 60.0
        team_id = player_team.get(player_id)
        fga = _stat(stats, player_id, StatCode.FGA)
        fta = _stat(stats, player_id, StatCode.FTA)
        turnovers = _stat(stats, player_id, StatCode.TOV)
        points = _stat(stats, player_id, StatCode.PTS)
        usage_numerator = fga + 0.44 * fta + turnovers
        if team_id is None or minutes == 0.0:
            usage_rate = 0.0
            fga_share = 0.0
        else:
            team_usage = (
                _team_stat(team_stats, team_id, StatCode.FGA)
                + 0.44 * _team_stat(team_stats, team_id, StatCode.FTA)
                + _team_stat(team_stats, team_id, StatCode.TOV)
            )
            usage_rate = _ratio(
                usage_numerator * (team_minutes.get(team_id, 0.0) / 5.0),
                minutes * team_usage,
            )
            fga_share = _ratio(fga, _team_stat(team_stats, team_id, StatCode.FGA))
        attempts = tuple(zone_attempts.get((player_id, zone), 0) for zone in _ZONES)
        makes = tuple(zone_makes.get((player_id, zone), 0) for zone in _ZONES)
        total_attempts = sum(attempts)
        players.append(
            {
                "nba_player_id": target.nba_player_id,
                "courtsim_player_id": player_id,
                "player_name": target.player_name,
                "team_id": team_id,
                "games_played": games,
                "minutes": round(minutes, 12),
                "minutes_per_game": round(_ratio(minutes, games), 12),
                "usage_rate": round(usage_rate, 12),
                "true_shooting_percentage": round(_ratio(points, 2.0 * (fga + 0.44 * fta)), 12),
                "field_goal_attempt_share": round(fga_share, 12),
                "shot_zone_attempts": dict(
                    zip((zone.name for zone in _ZONES), attempts, strict=True)
                ),
                "shot_zone_shares": {
                    zone.name: round(_ratio(attempt, total_attempts), 12)
                    for zone, attempt in zip(_ZONES, attempts, strict=True)
                },
                "shot_zone_percentages": {
                    zone.name: round(_ratio(made, attempt), 12)
                    for zone, made, attempt in zip(_ZONES, makes, attempts, strict=True)
                },
            }
        )
    return {
        "schema_version": 1,
        "version": NBA_PLAYER_AUDIT_VERSION,
        "target_id": targets.target_id,
        "season": targets.season,
        "games": len(completed),
        "players": players,
    }


def audit_nba_player_aggregates(
    aggregates: tuple[NBAPlayerSeasonAggregate, ...], targets: NBAPlayerTargetSet
) -> dict[str, object]:
    """Convert compact season aggregates into the canonical player-audit schema.

    Target players omitted from a capped roster remain explicit zero-minute rows, so
    coverage failures cannot disappear from the formal gate.
    """
    by_player = {item.player_id: item for item in aggregates}
    if len(by_player) != len(aggregates):
        raise NbaPlayerEvaluationError("player aggregates contain duplicate player ids")
    rows: list[dict[str, object]] = []
    games = max((item.games_available for item in aggregates), default=0)
    for target in targets.players:
        observed = by_player.get(target.nba_player_id)
        shares = observed.shot_zone_shares if observed is not None else (0.0, 0.0, 0.0)
        percentages = observed.shot_zone_percentages if observed is not None else (0.0, 0.0, 0.0)
        rows.append(
            {
                "nba_player_id": target.nba_player_id,
                "courtsim_player_id": target.nba_player_id,
                "player_name": target.player_name,
                "team_id": observed.team_id if observed is not None else None,
                "games_played": observed.games_played if observed is not None else 0,
                "minutes": round(observed.minutes, 12) if observed is not None else 0.0,
                "minutes_per_game": (
                    round(observed.minutes_per_game, 12) if observed is not None else 0.0
                ),
                "usage_rate": round(observed.usage_rate, 12) if observed is not None else 0.0,
                "true_shooting_percentage": (
                    round(observed.true_shooting_percentage, 12) if observed is not None else 0.0
                ),
                "field_goal_attempt_share": (
                    round(observed.field_goal_attempt_share, 12) if observed is not None else 0.0
                ),
                "shot_zone_attempts": {},
                "shot_zone_shares": dict(zip((zone.name for zone in _ZONES), shares, strict=True)),
                "shot_zone_percentages": dict(
                    zip((zone.name for zone in _ZONES), percentages, strict=True)
                ),
            }
        )
    return {
        "schema_version": 1,
        "version": NBA_PLAYER_AUDIT_VERSION,
        "target_id": targets.target_id,
        "season": targets.season,
        "games": games,
        "players": rows,
    }


def evaluate_nba_player_audit(
    audit: Mapping[str, object], targets: NBAPlayerTargetSet
) -> dict[str, object]:
    """Compute per-metric absolute error without combining unlike units."""
    if (
        audit.get("schema_version") != 1
        or audit.get("version") != NBA_PLAYER_AUDIT_VERSION
        or audit.get("target_id") != targets.target_id
        or audit.get("season") != targets.season
    ):
        raise NbaPlayerEvaluationError("player audit identity differs from targets")
    raw_players = audit.get("players")
    if not isinstance(raw_players, list):
        raise NbaPlayerEvaluationError("player audit rows are invalid")
    audited = {_row_id(item): _object(item, "player audit row") for item in raw_players}
    expected = {item.nba_player_id for item in targets.players}
    if set(audited) != expected or len(audited) != len(raw_players):
        raise NbaPlayerEvaluationError("player audit coverage differs from targets")
    squared: dict[str, list[float]] = {metric: [] for metric in _METRICS}
    absolute: dict[str, list[float]] = {metric: [] for metric in _METRICS}
    rows: list[dict[str, object]] = []
    for target in targets.players:
        observed = audited[target.nba_player_id]
        target_values = _target_values(target)
        observed_values = _observed_values(observed)
        errors = {}
        for metric in _METRICS:
            error = observed_values[metric] - target_values[metric]
            squared[metric].append(error * error)
            absolute[metric].append(abs(error))
            errors[metric] = round(error, 12)
        rows.append({"nba_player_id": target.nba_player_id, "errors": errors})
    metrics = [
        {
            "metric": metric,
            "rmse": round(math.sqrt(math.fsum(squared[metric]) / len(rows)), 12),
            "mae": round(math.fsum(absolute[metric]) / len(rows), 12),
        }
        for metric in _METRICS
    ]
    return {
        "schema_version": 1,
        "version": NBA_PLAYER_EVALUATION_VERSION,
        "target_id": targets.target_id,
        "season": targets.season,
        "players": len(rows),
        "metrics": metrics,
        "player_errors": rows,
    }


def evaluate_nba_player_audit_files(
    audit_path: str | Path, target_path: str | Path
) -> dict[str, object]:
    return evaluate_nba_player_audit(
        _load_object_file(Path(audit_path).resolve(), "player audit"),
        load_nba_player_target_set(target_path),
    )


def evaluate_nba_player_reality_gate(
    evaluation: Mapping[str, object], audit: Mapping[str, object]
) -> dict[str, object]:
    """Apply frozen, unit-specific player realism thresholds."""
    raw_metrics = evaluation.get("metrics")
    raw_players = audit.get("players")
    if evaluation.get("version") != NBA_PLAYER_EVALUATION_VERSION or not isinstance(
        raw_metrics, list
    ):
        raise NbaPlayerEvaluationError("player gate evaluation is invalid")
    if audit.get("version") != NBA_PLAYER_AUDIT_VERSION or not isinstance(raw_players, list):
        raise NbaPlayerEvaluationError("player gate audit is invalid")
    if tuple(evaluation.get(key) for key in ("target_id", "season")) != tuple(
        audit.get(key) for key in ("target_id", "season")
    ):
        raise NbaPlayerEvaluationError("player gate inputs differ")
    metrics = {_metric_name(item): _object(item, "player metric") for item in raw_metrics}
    thresholds = {
        "minutes_mae": 6.0,
        "usage_mae": 0.06,
        "true_shooting_mae": 0.08,
        "shot_structure_mae": 0.08,
        "zero_minute_rate": 0.10,
    }
    shot_structure = (
        math.fsum(
            _number(metrics[f"shot_zone_share.{zone}"].get("mae"), "mae")
            for zone in ("RIM", "MIDRANGE", "THREE")
        )
        / 3.0
    )
    zero_minutes = sum(
        _number(_object(row, "player audit row").get("minutes"), "minutes") == 0.0
        for row in raw_players
    )
    observed = {
        "minutes_mae": _number(metrics["minutes_per_game"].get("mae"), "mae"),
        "usage_mae": _number(metrics["usage_rate"].get("mae"), "mae"),
        "true_shooting_mae": _number(metrics["true_shooting_percentage"].get("mae"), "mae"),
        "shot_structure_mae": shot_structure,
        "zero_minute_rate": _ratio(zero_minutes, len(raw_players)),
    }
    checks = [
        {
            "metric": metric,
            "observed": round(value, 12),
            "maximum": thresholds[metric],
            "passed": value <= thresholds[metric],
        }
        for metric, value in observed.items()
    ]
    return {
        "schema_version": 1,
        "version": NBA_PLAYER_REALITY_GATE_VERSION,
        "target_id": evaluation.get("target_id"),
        "season": evaluation.get("season"),
        "passed": all(item["passed"] is True for item in checks),
        "checks": checks,
    }


def evaluate_nba_player_reality_gate_files(
    evaluation_path: str | Path, audit_path: str | Path
) -> dict[str, object]:
    return evaluate_nba_player_reality_gate(
        _load_object_file(Path(evaluation_path).resolve(), "player evaluation"),
        _load_object_file(Path(audit_path).resolve(), "player audit"),
    )


def aggregate_nba_player_evaluation_files(
    paths: tuple[str | Path, ...],
) -> dict[str, object]:
    return aggregate_nba_player_evaluations(
        tuple(_load_object_file(Path(path).resolve(), "player evaluation") for path in paths)
    )


def aggregate_nba_player_evaluations(
    reports: tuple[Mapping[str, object], ...],
) -> dict[str, object]:
    """Pool compatible seed-level RMSE values in squared-error space."""
    if not reports:
        raise NbaPlayerEvaluationError("player evaluation batch must not be empty")
    first = reports[0]
    identity = tuple(first.get(key) for key in ("target_id", "season", "players"))
    metric_runs: dict[str, list[tuple[float, float]]] = {metric: [] for metric in _METRICS}
    for report in reports:
        if (
            report.get("version") != NBA_PLAYER_EVALUATION_VERSION
            or tuple(report.get(key) for key in ("target_id", "season", "players")) != identity
        ):
            raise NbaPlayerEvaluationError("player evaluation batch identity differs")
        raw_metrics = report.get("metrics")
        if not isinstance(raw_metrics, list):
            raise NbaPlayerEvaluationError("player evaluation batch metrics are invalid")
        metrics = {_metric_name(item): _object(item, "player metric") for item in raw_metrics}
        if set(metrics) != set(_METRICS):
            raise NbaPlayerEvaluationError("player evaluation batch metrics differ")
        for metric in _METRICS:
            metric_runs[metric].append(
                (
                    _number(metrics[metric].get("rmse"), "rmse"),
                    _number(metrics[metric].get("mae"), "mae"),
                )
            )
    return {
        "schema_version": 1,
        "version": "nba-player-evaluation-batch-v1",
        "target_id": identity[0],
        "season": identity[1],
        "players": identity[2],
        "runs": len(reports),
        "metrics": [
            {
                "metric": metric,
                "pooled_rmse": round(
                    math.sqrt(
                        math.fsum(rmse * rmse for rmse, _ in metric_runs[metric]) / len(reports)
                    ),
                    12,
                ),
                "mean_mae": round(
                    math.fsum(mae for _, mae in metric_runs[metric]) / len(reports), 12
                ),
            }
            for metric in _METRICS
        ],
    }


def load_courtsim_identity_map(path: str | Path, targets: NBAPlayerTargetSet) -> dict[int, int]:
    """Load only explicitly assigned CourtSim ids from an identity artifact."""
    try:
        raw: object = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise NbaPlayerEvaluationError(f"cannot read player identity artifact: {path}") from error
    root = _object(raw, "player identity artifact")
    if root.get("version") != "nba-player-identity-v1":
        raise NbaPlayerEvaluationError("player identity artifact version differs")
    mappings = root.get("mappings")
    if not isinstance(mappings, list):
        raise NbaPlayerEvaluationError("player identity mappings are invalid")
    result: dict[int, int] = {}
    for raw_mapping in mappings:
        mapping = _object(raw_mapping, "player identity mapping")
        nba_id = _integer(mapping.get("nba_player_id"), "nba_player_id")
        courtsim_id = _integer(mapping.get("courtsim_player_id"), "courtsim_player_id")
        if nba_id in result:
            raise NbaPlayerEvaluationError("player identity contains duplicate NBA ids")
        result[nba_id] = courtsim_id
    target_ids = {item.nba_player_id for item in targets.players}
    if set(result) != target_ids:
        raise NbaPlayerEvaluationError("assigned player identities do not exactly cover targets")
    return result


def _target_values(target: Any) -> dict[str, float]:
    values = {
        "minutes_per_game": target.minutes_per_game,
        "usage_rate": target.usage_rate,
        "true_shooting_percentage": target.true_shooting_percentage,
        "field_goal_attempt_share": target.field_goal_attempt_share,
    }
    for index, zone in enumerate(("RIM", "MIDRANGE", "THREE")):
        values[f"shot_zone_share.{zone}"] = target.shot_zone_shares[index]
        values[f"shot_zone_percentage.{zone}"] = target.shot_zone_percentages[index]
    return values


def _observed_values(row: Mapping[str, Any]) -> dict[str, float]:
    values = {metric: _number(row.get(metric), metric) for metric in _METRICS[:4]}
    shares = _object(row.get("shot_zone_shares"), "shot_zone_shares")
    percentages = _object(row.get("shot_zone_percentages"), "shot_zone_percentages")
    for zone in ("RIM", "MIDRANGE", "THREE"):
        values[f"shot_zone_share.{zone}"] = _number(shares.get(zone), zone)
        values[f"shot_zone_percentage.{zone}"] = _number(percentages.get(zone), zone)
    return values


def _stat(stats: Mapping[tuple[int, StatCode], int], player_id: int, stat: StatCode) -> int:
    return stats.get((player_id, stat), 0)


def _team_stat(stats: Mapping[tuple[str, StatCode], int], team_id: str, stat: StatCode) -> int:
    return stats.get((team_id, stat), 0)


def _ratio(numerator: float | int, denominator: float | int) -> float:
    return float(numerator) / float(denominator) if denominator else 0.0


def _object(value: object, field: str) -> dict[str, Any]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise NbaPlayerEvaluationError(f"{field} must be an object")
    return cast(dict[str, Any], value)


def _integer(value: object, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise NbaPlayerEvaluationError(f"{field} must be a non-negative integer")
    return value


def _number(value: object, field: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
        raise NbaPlayerEvaluationError(f"{field} must be finite numeric data")
    return float(value)


def _row_id(value: object) -> int:
    return _integer(_object(value, "player audit row").get("nba_player_id"), "nba_player_id")


def _metric_name(value: object) -> str:
    metric = _object(value, "player metric").get("metric")
    if not isinstance(metric, str) or not metric:
        raise NbaPlayerEvaluationError("player metric identity is invalid")
    return metric


def _load_object_file(path: Path, label: str) -> dict[str, Any]:
    try:
        raw: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise NbaPlayerEvaluationError(f"cannot read {label}: {path}") from error
    return _object(raw, label)


def _game_clock(value: object) -> GameClockConfig:
    raw = _object(value, "model-audit clock")
    try:
        return GameClockConfig(
            _integer(raw.get("regulation_periods"), "regulation_periods"),
            _integer(raw.get("period_seconds"), "period_seconds"),
            _integer(raw.get("possession_seconds"), "possession_seconds"),
            _integer(raw.get("overtime_seconds", 300), "overtime_seconds"),
            _integer(raw.get("max_overtimes", 8), "max_overtimes"),
            _boolean(raw.get("overtime_enabled", False), "overtime_enabled"),
        )
    except ValueError as error:
        raise NbaPlayerEvaluationError("model-audit clock is invalid") from error


def _declared_games_path(manifest_path: Path, value: object) -> Path:
    if not isinstance(value, list):
        raise NbaPlayerEvaluationError("model-audit outputs are invalid")
    for raw_output in value:
        output = _object(raw_output, "model-audit output")
        if output.get("path") == "games.jsonl":
            path = manifest_path.parent / "games.jsonl"
            if not path.is_file():
                raise NbaPlayerEvaluationError("model-audit games.jsonl is missing")
            return path
    raise NbaPlayerEvaluationError("player audit requires full-trace games.jsonl")


def _read_game_results(path: Path, clock: GameClockConfig) -> tuple[GameResult, ...]:
    games: list[GameResult] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise NbaPlayerEvaluationError(f"cannot read model-audit games: {path}") from error
    for line_number, line in enumerate(lines, start=1):
        try:
            raw: object = json.loads(line)
            row = _object(raw, "model-audit game row")
            if set(row) != {"game_index", "seed", "result"}:
                raise NbaPlayerEvaluationError("model-audit game row keys are invalid")
            games.append(game_result_from_dict(row["result"], clock))
        except (json.JSONDecodeError, ValueError) as error:
            raise NbaPlayerEvaluationError(
                f"model-audit games line {line_number} is invalid"
            ) from error
    if not games:
        raise NbaPlayerEvaluationError("model-audit games are empty")
    return tuple(games)


def _boolean(value: object, field: str) -> bool:
    if not isinstance(value, bool):
        raise NbaPlayerEvaluationError(f"{field} must be a boolean")
    return value

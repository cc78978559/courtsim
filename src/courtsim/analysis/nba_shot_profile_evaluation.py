"""Evaluate whether team shot profiles improve simulated zone distributions."""

from __future__ import annotations

import math
from typing import cast

from courtsim.analysis.distribution import DistributionAudit, TeamDistributionMetrics
from courtsim.analysis.nba_shot_profiles import NBAShotProfileSet

NBA_SHOT_PROFILE_EVALUATION_VERSION = 1
_ZONES = ("RIM", "MIDRANGE", "THREE")


class NbaShotProfileEvaluationError(ValueError):
    """Raised when baseline, candidate, and targets cannot be compared."""


def evaluate_nba_shot_profile_audits(
    baseline: DistributionAudit,
    candidate: DistributionAudit,
    profiles: NBAShotProfileSet,
) -> dict[str, object]:
    """Compute paired team/zone errors against the observed profile targets."""
    for label, audit in (("baseline", baseline), ("candidate", candidate)):
        if audit.games < 1 or audit.completed_games != audit.games or audit.aborted_games:
            raise NbaShotProfileEvaluationError(f"{label} audit must contain complete games")
    if baseline.games != candidate.games:
        raise NbaShotProfileEvaluationError("baseline and candidate game counts differ")
    baseline_teams = {item.team_id: item for item in baseline.team_metrics}
    candidate_teams = {item.team_id: item for item in candidate.team_metrics}
    target_teams = {item.team_id: item for item in profiles.teams}
    if not target_teams or set(baseline_teams) != set(target_teams):
        raise NbaShotProfileEvaluationError("baseline team ids differ from shot profiles")
    if set(candidate_teams) != set(target_teams):
        raise NbaShotProfileEvaluationError("candidate team ids differ from shot profiles")
    rows: list[dict[str, object]] = []
    baseline_squared: list[float] = []
    candidate_squared: list[float] = []
    baseline_absolute: list[float] = []
    candidate_absolute: list[float] = []
    improved = 0
    worsened = 0
    unchanged = 0
    zone_errors: dict[str, tuple[list[float], list[float]]] = {zone: ([], []) for zone in _ZONES}
    for team_id in sorted(target_teams):
        target = target_teams[team_id]
        baseline_shares = _shares(baseline_teams[team_id])
        candidate_shares = _shares(candidate_teams[team_id])
        baseline_team_squared: list[float] = []
        candidate_team_squared: list[float] = []
        for index, zone in enumerate(_ZONES):
            baseline_error = baseline_shares[index] - target.shares[index]
            candidate_error = candidate_shares[index] - target.shares[index]
            baseline_squared.append(baseline_error * baseline_error)
            candidate_squared.append(candidate_error * candidate_error)
            baseline_team_squared.append(baseline_error * baseline_error)
            candidate_team_squared.append(candidate_error * candidate_error)
            baseline_absolute.append(abs(baseline_error))
            candidate_absolute.append(abs(candidate_error))
            zone_errors[zone][0].append(baseline_error * baseline_error)
            zone_errors[zone][1].append(candidate_error * candidate_error)
            if abs(candidate_error) < abs(baseline_error):
                improved += 1
            elif abs(candidate_error) > abs(baseline_error):
                worsened += 1
            else:
                unchanged += 1
        baseline_rmse = _rmse(baseline_team_squared)
        candidate_rmse = _rmse(candidate_team_squared)
        rows.append(
            {
                "team_id": team_id,
                "baseline_rmse": round(baseline_rmse, 12),
                "candidate_rmse": round(candidate_rmse, 12),
                "rmse_improvement": round(baseline_rmse - candidate_rmse, 12),
            }
        )
    baseline_rmse = _rmse(baseline_squared)
    candidate_rmse = _rmse(candidate_squared)
    rmse_improvement = baseline_rmse - candidate_rmse
    baseline_mae = math.fsum(baseline_absolute) / len(baseline_absolute)
    candidate_mae = math.fsum(candidate_absolute) / len(candidate_absolute)
    return {
        "schema_version": NBA_SHOT_PROFILE_EVALUATION_VERSION,
        "evaluation_id": f"{profiles.profile_id}-evaluation-v1",
        "status": (
            "improved"
            if rmse_improvement > 0.0
            else "regressed"
            if rmse_improvement < 0.0
            else "unchanged"
        ),
        "profile_id": profiles.profile_id,
        "season": profiles.season,
        "teams": len(target_teams),
        "team_zone_comparisons": len(baseline_squared),
        "baseline_rmse": round(baseline_rmse, 12),
        "candidate_rmse": round(candidate_rmse, 12),
        "rmse_improvement": round(rmse_improvement, 12),
        "relative_rmse_improvement": (
            None if baseline_rmse == 0.0 else round(rmse_improvement / baseline_rmse, 12)
        ),
        "baseline_mae": round(baseline_mae, 12),
        "candidate_mae": round(candidate_mae, 12),
        "mae_improvement": round(baseline_mae - candidate_mae, 12),
        "improved_team_zones": improved,
        "worsened_team_zones": worsened,
        "unchanged_team_zones": unchanged,
        "zone_rmse": [
            {
                "zone": zone,
                "baseline": round(_rmse(zone_errors[zone][0]), 12),
                "candidate": round(_rmse(zone_errors[zone][1]), 12),
                "improvement": round(
                    _rmse(zone_errors[zone][0]) - _rmse(zone_errors[zone][1]),
                    12,
                ),
            }
            for zone in _ZONES
        ],
        "team_results": rows,
    }


def aggregate_nba_shot_profile_evaluations(
    reports: tuple[dict[str, object], ...],
) -> dict[str, object]:
    """Pool compatible per-seed evaluations without averaging away squared error."""
    if not reports:
        raise NbaShotProfileEvaluationError("shot profile evaluation batch must not be empty")
    first = reports[0]
    identity = tuple(first.get(key) for key in ("profile_id", "season", "teams"))
    if any(value is None for value in identity):
        raise NbaShotProfileEvaluationError("shot profile evaluation identity is incomplete")
    for report in reports:
        if report.get("schema_version") != NBA_SHOT_PROFILE_EVALUATION_VERSION:
            raise NbaShotProfileEvaluationError("shot profile evaluation version differs")
        if tuple(report.get(key) for key in ("profile_id", "season", "teams")) != identity:
            raise NbaShotProfileEvaluationError("shot profile evaluation identity differs")

    baseline_rmse = _pooled_rmse(reports, "baseline_rmse")
    candidate_rmse = _pooled_rmse(reports, "candidate_rmse")
    zone_rows = _pool_group_rows(reports, "zone_rmse", "zone")
    team_rows = _pool_group_rows(reports, "team_results", "team_id")
    improvement = baseline_rmse - candidate_rmse
    statuses = [report.get("status") for report in reports]
    profile_id, season, teams = identity
    return {
        "schema_version": NBA_SHOT_PROFILE_EVALUATION_VERSION,
        "evaluation_id": f"{profile_id}-batch-v1",
        "profile_id": profile_id,
        "season": season,
        "teams": teams,
        "runs": len(reports),
        "status": "improved"
        if improvement > 0
        else "regressed"
        if improvement < 0
        else "unchanged",
        "baseline_rmse": round(baseline_rmse, 12),
        "candidate_rmse": round(candidate_rmse, 12),
        "rmse_improvement": round(improvement, 12),
        "relative_rmse_improvement": (
            None if baseline_rmse == 0.0 else round(improvement / baseline_rmse, 12)
        ),
        "improved_runs": statuses.count("improved"),
        "regressed_runs": statuses.count("regressed"),
        "unchanged_runs": statuses.count("unchanged"),
        "zone_rmse": zone_rows,
        "team_results": team_rows,
    }


def _shares(team: TeamDistributionMetrics) -> tuple[float, float, float]:
    by_zone = {item.key: item.share for item in team.shot_zone_shares}
    if set(by_zone) != set(_ZONES):
        raise NbaShotProfileEvaluationError(f"team shot zones are incomplete: {team.team_id}")
    shares = tuple(by_zone[zone] for zone in _ZONES)
    if any(not math.isfinite(value) or value < 0.0 for value in shares):
        raise NbaShotProfileEvaluationError(f"team shot shares are invalid: {team.team_id}")
    if not math.isclose(math.fsum(shares), 1.0, abs_tol=1e-9):
        raise NbaShotProfileEvaluationError(f"team shot shares do not sum to one: {team.team_id}")
    return cast(tuple[float, float, float], shares)


def _rmse(squared_errors: list[float]) -> float:
    return math.sqrt(math.fsum(squared_errors) / len(squared_errors))


def _number(value: object, field: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
        raise NbaShotProfileEvaluationError(f"shot profile evaluation {field} is invalid")
    return float(value)


def _pooled_rmse(reports: tuple[dict[str, object], ...], field: str) -> float:
    values = [_number(report.get(field), field) for report in reports]
    return math.sqrt(math.fsum(value * value for value in values) / len(values))


def _pool_group_rows(
    reports: tuple[dict[str, object], ...],
    field: str,
    identity_field: str,
) -> list[dict[str, object]]:
    groups: list[dict[str, dict[str, object]]] = []
    for report in reports:
        raw_rows = report.get(field)
        if not isinstance(raw_rows, list):
            raise NbaShotProfileEvaluationError(f"shot profile evaluation {field} is invalid")
        rows: dict[str, dict[str, object]] = {}
        for raw in raw_rows:
            if not isinstance(raw, dict) or not isinstance(raw.get(identity_field), str):
                raise NbaShotProfileEvaluationError(
                    f"shot profile evaluation {field} identity is invalid"
                )
            rows[cast(str, raw[identity_field])] = raw
        if len(rows) != len(raw_rows):
            raise NbaShotProfileEvaluationError(
                f"shot profile evaluation {field} identities are duplicated"
            )
        groups.append(rows)
    identities = set(groups[0])
    if any(set(group) != identities for group in groups[1:]):
        raise NbaShotProfileEvaluationError(f"shot profile evaluation {field} differs")
    pooled = []
    ordered_identities = _ZONES if field == "zone_rmse" else tuple(sorted(identities))
    if set(ordered_identities) != identities:
        raise NbaShotProfileEvaluationError(f"shot profile evaluation {field} differs")
    for item_id in ordered_identities:
        baseline = _pooled_rmse(
            tuple(
                {
                    "value": group[item_id].get(
                        "baseline" if field == "zone_rmse" else "baseline_rmse"
                    )
                }
                for group in groups
            ),
            "value",
        )
        candidate = _pooled_rmse(
            tuple(
                {
                    "value": group[item_id].get(
                        "candidate" if field == "zone_rmse" else "candidate_rmse"
                    )
                }
                for group in groups
            ),
            "value",
        )
        if field == "zone_rmse":
            pooled.append(
                {
                    identity_field: item_id,
                    "baseline": round(baseline, 12),
                    "candidate": round(candidate, 12),
                    "improvement": round(baseline - candidate, 12),
                }
            )
        else:
            pooled.append(
                {
                    identity_field: item_id,
                    "baseline_rmse": round(baseline, 12),
                    "candidate_rmse": round(candidate, 12),
                    "rmse_improvement": round(baseline - candidate, 12),
                }
            )
    return pooled

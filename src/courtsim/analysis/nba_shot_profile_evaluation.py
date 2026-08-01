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

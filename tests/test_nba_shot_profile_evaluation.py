from dataclasses import replace

import pytest

from courtsim.analysis.distribution import (
    DistributionAudit,
    ShareMetric,
    TeamDistributionMetrics,
)
from courtsim.analysis.nba_shot_profile_evaluation import (
    NbaShotProfileEvaluationError,
    evaluate_nba_shot_profile_audits,
)
from courtsim.analysis.nba_shot_profiles import NBAShotProfileSet, NBATeamShotProfile


def _team(team_id: str, shares: tuple[float, float, float]) -> TeamDistributionMetrics:
    return TeamDistributionMetrics(
        team_id,
        100,
        100.0,
        110.0,
        0.46,
        0.36,
        0.14,
        0.6,
        0.05,
        0.08,
        tuple(
            ShareMetric(zone, round(100 * share), share)
            for zone, share in zip(("RIM", "MIDRANGE", "THREE"), shares, strict=True)
        ),
    )


def _audit(*teams: TeamDistributionMetrics) -> DistributionAudit:
    return DistributionAudit(
        games=1,
        completed_games=1,
        aborted_games=0,
        completed_possessions=200,
        mean_team_score=110.0,
        team_score_stddev=1.0,
        mean_team_possessions=100.0,
        points_per_100_possessions=110.0,
        field_goal_percentage=0.46,
        three_point_percentage=0.36,
        turnover_rate=0.14,
        offensive_rebound_rate=0.25,
        assist_per_field_goal=0.6,
        block_rate=0.05,
        steal_rate=0.08,
        shot_zone_shares=(),
        play_family_shares=(),
        coverage_shares=(),
        player_usage_shares=(),
        team_metrics=tuple(teams),
    )


def test_team_zone_evaluation_detects_paired_improvement() -> None:
    profiles = NBAShotProfileSet(
        "profiles",
        "2024-25",
        0.75,
        (
            NBATeamShotProfile("A", (0.5, 0.1, 0.4), (0, 0, 0)),
            NBATeamShotProfile("B", (0.4, 0.2, 0.4), (0, 0, 0)),
        ),
    )
    baseline = _audit(_team("A", (0.4, 0.2, 0.4)), _team("B", (0.5, 0.1, 0.4)))
    candidate = _audit(_team("A", (0.48, 0.12, 0.4)), _team("B", (0.42, 0.18, 0.4)))
    report = evaluate_nba_shot_profile_audits(baseline, candidate, profiles)
    assert report["status"] == "improved"
    assert report["rmse_improvement"] == pytest.approx(0.065319726474)
    assert report["relative_rmse_improvement"] == pytest.approx(0.8)
    assert report["mae_improvement"] == pytest.approx(0.053333333333)
    assert report["improved_team_zones"] == 4
    assert report["unchanged_team_zones"] == 2


def test_team_zone_evaluation_rejects_mismatched_teams() -> None:
    profiles = NBAShotProfileSet(
        "profiles",
        "2024-25",
        0.75,
        (NBATeamShotProfile("A", (0.5, 0.1, 0.4), (0, 0, 0)),),
    )
    baseline = _audit(_team("A", (0.5, 0.1, 0.4)))
    with pytest.raises(NbaShotProfileEvaluationError, match="candidate"):
        evaluate_nba_shot_profile_audits(
            baseline,
            replace(baseline, team_metrics=(_team("B", (0.5, 0.1, 0.4)),)),
            profiles,
        )


def test_team_zone_evaluation_requires_complete_equal_batches() -> None:
    profiles = NBAShotProfileSet(
        "profiles",
        "2024-25",
        0.75,
        (NBATeamShotProfile("A", (0.5, 0.1, 0.4), (0, 0, 0)),),
    )
    audit = _audit(_team("A", (0.5, 0.1, 0.4)))
    with pytest.raises(NbaShotProfileEvaluationError, match="baseline audit"):
        evaluate_nba_shot_profile_audits(
            replace(audit, completed_games=0, aborted_games=1),
            audit,
            profiles,
        )
    with pytest.raises(NbaShotProfileEvaluationError, match="game counts"):
        evaluate_nba_shot_profile_audits(
            audit, replace(audit, games=2, completed_games=2), profiles
        )


def test_team_zone_evaluation_handles_perfect_baseline() -> None:
    profiles = NBAShotProfileSet(
        "profiles",
        "2024-25",
        0.75,
        (NBATeamShotProfile("A", (0.5, 0.1, 0.4), (0, 0, 0)),),
    )
    audit = _audit(_team("A", (0.5, 0.1, 0.4)))
    report = evaluate_nba_shot_profile_audits(audit, audit, profiles)
    assert report["status"] == "unchanged"
    assert report["relative_rmse_improvement"] is None

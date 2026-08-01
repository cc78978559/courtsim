from dataclasses import replace

import pytest

from courtsim.analysis.distribution import (
    DistributionAudit,
    ShareMetric,
    TeamDistributionMetrics,
)
from courtsim.analysis.nba_shot_profile_evaluation import (
    NbaShotProfileEvaluationError,
    aggregate_nba_shot_profile_evaluations,
    evaluate_nba_shot_profile_audits,
)
from courtsim.analysis.nba_shot_profiles import (
    NbaShotProfileError,
    NBAShotProfileSet,
    NBATeamShotProfile,
    calibrate_nba_shot_profiles,
)


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


def test_team_zone_evaluation_batch_pools_squared_errors() -> None:
    profiles = NBAShotProfileSet(
        "profiles",
        "2024-25",
        0.75,
        (NBATeamShotProfile("A", (0.5, 0.1, 0.4), (0, 0, 0)),),
    )
    baseline = _audit(_team("A", (0.4, 0.2, 0.4)))
    first = evaluate_nba_shot_profile_audits(
        baseline,
        _audit(_team("A", (0.48, 0.12, 0.4))),
        profiles,
    )
    second = evaluate_nba_shot_profile_audits(
        baseline,
        _audit(_team("A", (0.46, 0.14, 0.4))),
        profiles,
    )
    batch = aggregate_nba_shot_profile_evaluations((first, second))
    assert batch["runs"] == 2
    assert batch["improved_runs"] == 2
    assert batch["status"] == "improved"
    assert batch["baseline_rmse"] == pytest.approx(first["baseline_rmse"])
    first_candidate = first["candidate_rmse"]
    second_candidate = second["candidate_rmse"]
    zone_rows = batch["zone_rmse"]
    team_rows = batch["team_results"]
    assert isinstance(first_candidate, float)
    assert isinstance(second_candidate, float)
    assert isinstance(zone_rows, list)
    assert isinstance(team_rows, list)
    expected = ((first_candidate**2 + second_candidate**2) / 2) ** 0.5
    assert batch["candidate_rmse"] == pytest.approx(expected)
    assert len(zone_rows) == 3
    assert [row["zone"] for row in zone_rows] == ["RIM", "MIDRANGE", "THREE"]
    assert len(team_rows) == 1


def test_team_zone_evaluation_batch_rejects_mixed_profiles() -> None:
    report = {
        "schema_version": 1,
        "profile_id": "A",
        "season": "2024-25",
        "teams": 30,
    }
    with pytest.raises(NbaShotProfileEvaluationError, match="identity differs"):
        aggregate_nba_shot_profile_evaluations((report, {**report, "profile_id": "B"}))


def test_shot_profiles_can_rebase_offsets_onto_simulated_baseline() -> None:
    profiles = NBAShotProfileSet(
        "profiles",
        "2024-25",
        0.75,
        (NBATeamShotProfile("A", (0.5, 0.1, 0.4), (-4, 8, -4)),),
    )
    baseline = _audit(_team("A", (0.36, 0.21, 0.43)))
    calibrated = calibrate_nba_shot_profiles(profiles, baseline)
    assert calibrated.profile_id == "profiles-baseline-calibrated"
    rim, midrange, three = calibrated.teams[0].rating_offsets
    assert rim > 0
    assert midrange < 0
    assert abs(three) < abs(midrange)
    regularized = calibrate_nba_shot_profiles(profiles, baseline, calibration_strength=0.5)
    assert regularized.profile_id == "profiles-baseline-calibrated-0.5x"
    assert all(
        abs(value) <= abs(full)
        for value, full in zip(
            regularized.teams[0].rating_offsets,
            calibrated.teams[0].rating_offsets,
            strict=True,
        )
    )
    zone_regularized = calibrate_nba_shot_profiles(
        profiles,
        baseline,
        calibration_strength=0.75,
        zone_calibration_strengths=(1.0, 1.0, 0.5),
    )
    assert zone_regularized.profile_id == ("profiles-baseline-calibrated-0.75x-zones-1-1-0.5")
    contrasted = calibrate_nba_shot_profiles(
        profiles,
        baseline,
        calibration_strength=0.75,
        contrast_calibration_strengths=(1.0, 0.5),
    )
    assert contrasted.profile_id == ("profiles-baseline-calibrated-0.75x-contrasts-1-0.5")
    assert contrasted.teams[0].rating_offsets[2] == 0
    with pytest.raises(NbaShotProfileError, match="complete games"):
        calibrate_nba_shot_profiles(
            profiles,
            replace(baseline, completed_games=0, aborted_games=1),
        )
    with pytest.raises(NbaShotProfileError, match="strength"):
        calibrate_nba_shot_profiles(profiles, baseline, calibration_strength=0.0)
    with pytest.raises(NbaShotProfileError, match="zone calibration"):
        calibrate_nba_shot_profiles(
            profiles,
            baseline,
            zone_calibration_strengths=(1.0, 1.0, 1.1),
        )
    with pytest.raises(NbaShotProfileError, match="mutually exclusive"):
        calibrate_nba_shot_profiles(
            profiles,
            baseline,
            zone_calibration_strengths=(1.0, 1.0, 0.5),
            contrast_calibration_strengths=(1.0, 1.0),
        )

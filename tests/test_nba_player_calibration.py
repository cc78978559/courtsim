from test_nba_player_targets import _targets

from courtsim.analysis.nba_player_calibration import (
    build_player_calibration_plan,
    classify_player_role,
)


def test_player_calibration_plan_gates_identity_before_metric_tuning() -> None:
    targets = _targets()
    identity = {"coverage": {"player_coverage": 0.95, "minutes_coverage": 0.98}}
    report = build_player_calibration_plan(targets, identity)
    assert report["promotion_ready"] is True
    role_distribution = report["role_distribution"]
    assert isinstance(role_distribution, dict)
    assert sum(role_distribution.values()) == 1
    assert classify_player_role(targets.players[0]) == "SECONDARY_CREATOR"

from pathlib import Path
from typing import Any, cast

import pytest

from courtsim.analysis.nba_player_evaluation import (
    NbaPlayerEvaluationError,
    aggregate_nba_player_evaluations,
    audit_nba_player_results,
    evaluate_nba_player_audit,
    load_courtsim_identity_map,
)
from courtsim.analysis.nba_player_targets import (
    NBAPlayerSourceReceipt,
    NBAPlayerTarget,
    NBAPlayerTargetSet,
)
from courtsim.artifacts import write_json
from courtsim.domain.enums import GameEndReason
from courtsim.domain.game import GameResult, PlayerPlayingTime
from courtsim.stats.attribution import PlayerStatDelta, StatCode


def _targets() -> NBAPlayerTargetSet:
    return NBAPlayerTargetSet(
        "players-v1",
        "2024-25",
        "fixture",
        1,
        1.0,
        (NBAPlayerSourceReceipt("box", "box.json", "a" * 64),),
        (
            NBAPlayerTarget(
                100,
                "Player",
                "A",
                1,
                48.0,
                0.2,
                0.6,
                0.25,
                (0.4, 0.2, 0.4),
                (0.7, 0.4, 0.38),
            ),
        ),
    )


def _result() -> GameResult:
    stats = [
        PlayerStatDelta(1, StatCode.FGA, 10),
        PlayerStatDelta(1, StatCode.FTA, 2),
        PlayerStatDelta(1, StatCode.TOV, 1),
        PlayerStatDelta(1, StatCode.PTS, 15),
        PlayerStatDelta(2, StatCode.FGA, 30),
        PlayerStatDelta(2, StatCode.FTA, 8),
        PlayerStatDelta(2, StatCode.TOV, 9),
    ]
    playing_time = [
        *(PlayerPlayingTime("A", player_id, 2880) for player_id in range(1, 6)),
        *(PlayerPlayingTime("B", player_id, 2880) for player_id in range(11, 16)),
    ]
    return GameResult(
        "A",
        "B",
        (),
        100,
        90,
        tuple(stats),
        GameEndReason.REGULATION,
        playing_time=tuple(playing_time),
    )


def test_player_audit_computes_minutes_usage_efficiency_and_share() -> None:
    audit = audit_nba_player_results((_result(),), _targets(), {100: 1})
    rows = cast(list[dict[str, Any]], audit["players"])
    row = rows[0]
    assert row["minutes_per_game"] == 48.0
    assert row["field_goal_attempt_share"] == 0.25
    assert row["true_shooting_percentage"] == pytest.approx(15 / (2 * 10.88))
    assert row["usage_rate"] == pytest.approx((10 + 0.44 * 2 + 1) / (40 + 0.44 * 10 + 10))
    assert row["shot_zone_shares"] == {"RIM": 0.0, "MIDRANGE": 0.0, "THREE": 0.0}


def test_player_evaluation_and_batch_pool_metric_errors() -> None:
    targets = _targets()
    audit = audit_nba_player_results((_result(),), targets, {100: 1})
    evaluation = evaluate_nba_player_audit(audit, targets)
    metrics = cast(list[dict[str, Any]], evaluation["metrics"])
    by_name = {item["metric"]: item for item in metrics}
    assert by_name["minutes_per_game"]["rmse"] == 0.0
    assert by_name["field_goal_attempt_share"]["rmse"] == 0.0
    batch = aggregate_nba_player_evaluations((evaluation, evaluation))
    assert batch["runs"] == 2
    pooled = cast(list[dict[str, Any]], batch["metrics"])
    assert {item["metric"] for item in pooled} == set(by_name)


def test_identity_loader_requires_explicit_courtsim_assignment(tmp_path: Path) -> None:
    identity = tmp_path / "identity.json"
    write_json(
        identity,
        {
            "version": "nba-player-identity-v1",
            "mappings": [{"nba_player_id": 100, "courtsim_player_id": None}],
        },
    )
    with pytest.raises(NbaPlayerEvaluationError, match="courtsim_player_id"):
        load_courtsim_identity_map(identity, _targets())

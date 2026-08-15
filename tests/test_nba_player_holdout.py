from typing import cast

from courtsim.analysis.nba_player_aggregates import NBAPlayerSeasonAggregate
from courtsim.analysis.nba_player_holdout import (
    append_nba_player_holdout_cells,
    build_nba_player_holdout_cell,
    evaluate_nba_player_holdout,
    load_nba_player_holdout_gate,
    nba_player_holdout_from_dict,
    nba_player_holdout_to_dict,
)
from courtsim.analysis.nba_player_targets import (
    NBAPlayerSourceReceipt,
    NBAPlayerTarget,
    NBAPlayerTargetSet,
)


def test_player_holdout_gate_is_external_and_strict() -> None:
    thresholds = load_nba_player_holdout_gate(
        {
            "version": "nba-player-holdout-gate-v1",
            "gate_id": "player-test",
            "frozen_at": "2026-08-15",
            "minimum_seasons": 30,
            "forbidden_master_seeds": [1, 2],
            "batch_id_prefix": "holdout-",
            "target_id": "players-v1",
            "target_season": "2024-25",
            "maximums": {
                "minutes_mae": 6.0,
                "usage_mae": 0.06,
                "true_shooting_mae": 0.08,
                "shot_structure_mae": 0.08,
                "zero_minute_rate": 0.10,
            },
        }
    )
    maximums = cast(dict[str, float], thresholds["maximums"])
    assert maximums["minutes_mae"] == 6.0


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
                "1",
                82,
                24.0,
                0.2,
                0.6,
                0.1,
                (0.4, 0.2, 0.4),
                (0.7, 0.4, 0.38),
            ),
        ),
    )


def _aggregate() -> NBAPlayerSeasonAggregate:
    return NBAPlayerSeasonAggregate(
        "Atlanta Hawks",
        100,
        82,
        82,
        82 * 24 * 60,
        0.2,
        0.6,
        0.1,
        (0.4, 0.2, 0.4),
        (0.7, 0.4, 0.38),
        1,
        1,
        1,
        1,
        1,
        1.0,
        1.0,
    )


def test_player_holdout_round_trips_and_gates_thirty_seasons() -> None:
    targets = _targets()
    batch = None
    for index in range(30):
        cell = build_nba_player_holdout_cell(
            index,
            f"holdout:season-{index + 1:04d}",
            index + 100,
            (_aggregate(),),
            targets,
        )
        batch = append_nba_player_holdout_cells(
            batch_id="holdout",
            master_seed=99,
            seasons=30,
            targets=targets,
            cells=(cell,),
            previous=batch,
        )
    assert batch is not None and batch.complete
    restored = nba_player_holdout_from_dict(nba_player_holdout_to_dict(batch))
    assert restored == batch
    report = evaluate_nba_player_holdout(restored)
    assert report["passed"] is True
    assert report["seasons"] == 30

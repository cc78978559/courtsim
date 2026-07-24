from courtsim.domain.enums import ContestLevel, Coverage, FinisherRoute, ShotZone
from courtsim.domain.interaction import FinisherSelection
from courtsim.domain.plans import BallScreenPlan, IsolationPlan
from courtsim.domain.results import (
    BlockedShotSegmentResult,
    DefensiveRebound,
    MadeShotSegmentResult,
    MissedShotSegmentResult,
    OffensiveRebound,
    ShootingFoulSegmentResult,
)
from courtsim.stats import StatCode, attribute_segment


def as_map(result: object) -> dict[tuple[int, StatCode], int]:
    attribution = attribute_segment(result)  # type: ignore[arg-type]
    return {(item.player_id, item.stat): item.amount for item in attribution.player_deltas}


def test_made_roll_attribution_derives_assist() -> None:
    result = MadeShotSegmentResult(
        BallScreenPlan(1, 5),
        Coverage.DROP,
        FinisherSelection(FinisherRoute.SCREENER_ROLL, 5),
        ShotZone.RIM,
        ContestLevel.NORMAL,
        1,
    )
    attribution = attribute_segment(result)
    assert attribution.score_delta == 2
    assert attribution.possession_delta == 1
    assert as_map(result) == {
        (1, StatCode.AST): 1,
        (5, StatCode.PTS): 2,
        (5, StatCode.FGM): 1,
        (5, StatCode.FGA): 1,
        (5, StatCode.TWO_PM): 1,
        (5, StatCode.TWO_PA): 1,
    }


def test_miss_oreb_retains_possession() -> None:
    result = MissedShotSegmentResult(
        IsolationPlan(1),
        Coverage.BASE,
        FinisherSelection(FinisherRoute.INITIATOR_SELF, 1),
        ShotZone.THREE,
        ContestLevel.HEAVY,
        OffensiveRebound(4),
    )
    attribution = attribute_segment(result)
    assert attribution.score_delta == 0
    assert attribution.possession_delta == 0
    assert as_map(result)[(4, StatCode.OREB)] == 1
    assert as_map(result)[(4, StatCode.REB)] == 1


def test_block_books_attempt_block_and_defensive_rebound() -> None:
    result = BlockedShotSegmentResult(
        IsolationPlan(1),
        Coverage.BLITZ,
        FinisherSelection(FinisherRoute.INITIATOR_SELF, 1),
        ShotZone.RIM,
        11,
        DefensiveRebound(12),
    )
    attribution = attribute_segment(result)
    assert attribution.possession_delta == 1
    stats = as_map(result)
    assert stats[(1, StatCode.FGA)] == 1
    assert stats[(11, StatCode.BLK)] == 1
    assert stats[(12, StatCode.DREB)] == 1


def test_missed_shooting_foul_books_free_throws_but_not_field_goal_attempt() -> None:
    result = ShootingFoulSegmentResult(
        IsolationPlan(1),
        Coverage.BASE,
        FinisherSelection(FinisherRoute.INITIATOR_SELF, 1),
        ShotZone.THREE,
        ContestLevel.HEAVY,
        11,
        False,
        (True, False, True),
        None,
    )
    attribution = attribute_segment(result)
    assert attribution.score_delta == 2
    stats = as_map(result)
    assert stats[(1, StatCode.FTA)] == 3
    assert stats[(1, StatCode.FTM)] == 2
    assert stats[(1, StatCode.PTS)] == 2
    assert stats[(11, StatCode.PF)] == 1
    assert (1, StatCode.FGA) not in stats


def test_and_one_books_field_goal_assist_and_bonus_free_throw() -> None:
    result = ShootingFoulSegmentResult(
        BallScreenPlan(1, 5),
        Coverage.DROP,
        FinisherSelection(FinisherRoute.SCREENER_ROLL, 5),
        ShotZone.RIM,
        ContestLevel.NORMAL,
        11,
        True,
        (True,),
        None,
        1,
    )
    attribution = attribute_segment(result)
    assert attribution.score_delta == 3
    stats = as_map(result)
    assert stats[(1, StatCode.AST)] == 1
    assert stats[(5, StatCode.FGM)] == 1
    assert stats[(5, StatCode.FTA)] == 1
    assert stats[(5, StatCode.PTS)] == 3

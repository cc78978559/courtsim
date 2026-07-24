import json

import pytest

from courtsim.domain.enums import ContestLevel, Coverage, FinisherRoute, ShotZone
from courtsim.domain.interaction import FinisherSelection
from courtsim.domain.plans import BallScreenPlan, IsolationPlan, OffBallActionPlan
from courtsim.domain.results import (
    BlockedShotSegmentResult,
    DefensiveRebound,
    MadeShotSegmentResult,
    MissedShotSegmentResult,
    OffensiveRebound,
    ShootingFoulSegmentResult,
    TurnoverSegmentResult,
    ViolationTurnover,
)
from courtsim.domain.serialization import (
    SerializationError,
    segment_result_from_dict,
    segment_result_from_json,
    segment_result_to_json,
)

RESULTS = (
    TurnoverSegmentResult(IsolationPlan(1), Coverage.BASE, ViolationTurnover(1)),
    MadeShotSegmentResult(
        BallScreenPlan(1, 5),
        Coverage.DROP,
        FinisherSelection(FinisherRoute.SCREENER_POP, 5),
        ShotZone.THREE,
        ContestLevel.NORMAL,
    ),
    MissedShotSegmentResult(
        OffBallActionPlan(1, 3, 4),
        Coverage.SWITCH,
        FinisherSelection(FinisherRoute.DESIGNED_OFF_BALL_TARGET, 3),
        ShotZone.MIDRANGE,
        ContestLevel.HEAVY,
        OffensiveRebound(2),
    ),
    BlockedShotSegmentResult(
        IsolationPlan(1),
        Coverage.BLITZ,
        FinisherSelection(FinisherRoute.INITIATOR_SELF, 1),
        ShotZone.RIM,
        11,
        DefensiveRebound(12),
    ),
    ShootingFoulSegmentResult(
        IsolationPlan(1),
        Coverage.BASE,
        FinisherSelection(FinisherRoute.INITIATOR_SELF, 1),
        ShotZone.RIM,
        ContestLevel.HEAVY,
        11,
        False,
        (True, False),
        OffensiveRebound(4),
    ),
)


@pytest.mark.parametrize("result", RESULTS)
def test_stable_json_round_trip(result: object) -> None:
    assert segment_result_from_json(segment_result_to_json(result)) == result  # type: ignore[arg-type]


def test_representative_json_is_a_golden_contract() -> None:
    assert segment_result_to_json(RESULTS[1]) == (
        '{"assister_id":null,"contest_level":0,"coverage":1,"kind":"made_shot",'
        '"plan":{"family":0,"handler_id":1,"screener_id":5},'
        '"schema_version":4,"selection":{"finisher_id":5,"route":2},"zone":2}'
    )


def test_decoder_rejects_unknown_keys_invalid_enum_and_version() -> None:
    raw = json.loads(segment_result_to_json(RESULTS[1]))
    raw["invented"] = True
    with pytest.raises(SerializationError):
        segment_result_from_dict(raw)

    raw = json.loads(segment_result_to_json(RESULTS[1]))
    raw["coverage"] = 99
    with pytest.raises(SerializationError):
        segment_result_from_dict(raw)

    raw = json.loads(segment_result_to_json(RESULTS[1]))
    raw["schema_version"] = 5
    with pytest.raises(SerializationError):
        segment_result_from_dict(raw)


def test_v1_made_shot_derives_legacy_assister() -> None:
    raw = {
        "schema_version": 1,
        "kind": "made_shot",
        "plan": {"family": 0, "handler_id": 1, "screener_id": 5},
        "coverage": 1,
        "selection": {"route": 1, "finisher_id": 5},
        "zone": 0,
        "contest_level": 0,
    }
    result = segment_result_from_dict(raw)
    assert isinstance(result, MadeShotSegmentResult)
    assert result.assister_id == 1


def test_shooting_foul_rejects_pre_v3_serialization() -> None:
    raw = json.loads(segment_result_to_json(RESULTS[-1]))
    raw["schema_version"] = 2
    with pytest.raises(SerializationError, match="requires schema_version 3"):
        segment_result_from_dict(raw)

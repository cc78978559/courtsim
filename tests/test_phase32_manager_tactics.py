from courtsim.domain.enums import Coverage, PlayFamily
from courtsim.manager_learning import (
    ManagerLearningState,
    OpponentObservation,
    opponent_tactical_adjustment,
    update_manager_learning,
)


def _learned_state(games: int) -> ManagerLearningState:
    return update_manager_learning(
        ManagerLearningState("manager-A", "A", 2027),
        (OpponentObservation("B", games, 90, 85, 75, 95, 20),),
        completed_season=2028,
    )


def test_opponent_tactics_are_bounded_canonical_and_explainable() -> None:
    adjustment = opponent_tactical_adjustment(_learned_state(8), "B")
    assert adjustment is not None
    assert tuple(key for key, _ in adjustment.play_family_logit_biases) == tuple(PlayFamily)
    assert tuple(key for key, _ in adjustment.coverage_logit_biases) == tuple(Coverage)
    assert all(
        abs(value) <= 0.75
        for _, value in (adjustment.play_family_logit_biases + adjustment.coverage_logit_biases)
    )
    assert dict(adjustment.play_family_logit_biases)[PlayFamily.ISOLATION] < 0
    assert dict(adjustment.coverage_logit_biases)[Coverage.SWITCH] > 0
    assert adjustment.tempo_delta < 0
    assert adjustment.confidence_bps == 10_000


def test_opponent_tactics_scale_with_evidence_and_ignore_unknown_teams() -> None:
    early = opponent_tactical_adjustment(_learned_state(1), "B")
    mature = opponent_tactical_adjustment(_learned_state(8), "B")
    assert early is not None
    assert mature is not None
    assert early.confidence_bps == 1_250
    assert abs(dict(early.coverage_logit_biases)[Coverage.SWITCH]) < abs(
        dict(mature.coverage_logit_biases)[Coverage.SWITCH]
    )
    assert opponent_tactical_adjustment(_learned_state(8), "C") is None

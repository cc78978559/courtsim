from courtsim.domain.enums import Coverage
from courtsim.manager_learning import (
    ManagerLearningState,
    OpponentObservation,
    OpponentTacticalAdjustment,
    opponent_tactical_adjustment,
    update_manager_learning,
)


def _adjustment(
    offense_strength: int,
    defense_strength: int,
) -> OpponentTacticalAdjustment:
    state = update_manager_learning(
        ManagerLearningState("manager-A", "A", 2028),
        (
            OpponentObservation(
                "B",
                8,
                offense_strength,
                defense_strength,
                50,
                80,
                20,
            ),
        ),
        completed_season=2029,
    )
    adjustment = opponent_tactical_adjustment(state, "B")
    assert adjustment is not None
    return adjustment


def test_matchup_outcomes_change_intensity_without_changing_style_direction() -> None:
    poor = _adjustment(80, 70)
    good = _adjustment(20, 30)
    assert poor.matchup_net_rating == -50
    assert poor.response_multiplier_bps == 12_500
    assert good.matchup_net_rating == 50
    assert good.response_multiplier_bps == 7_500
    poor_switch = dict(poor.coverage_logit_biases)[Coverage.SWITCH]
    good_switch = dict(good.coverage_logit_biases)[Coverage.SWITCH]
    assert poor_switch > good_switch > 0


def test_neutral_matchup_keeps_the_unmodified_tactical_weight() -> None:
    neutral = _adjustment(50, 50)
    assert neutral.matchup_net_rating == 0
    assert neutral.response_multiplier_bps == 10_000
    assert all(
        abs(value) <= 0.75
        for _, value in neutral.play_family_logit_biases + neutral.coverage_logit_biases
    )

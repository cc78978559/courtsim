import math

import pytest

from courtsim.probability import (
    ProbabilityOption,
    sample_probability_node,
    sample_probability_value,
)
from courtsim.randomness import RandomFrame, RandomFrameAddress, RandomSlot


def frame() -> RandomFrame:
    return RandomFrame(42, RandomFrameAddress("fixture", 0, 1, 2, 3))


def test_random_frame_is_stable_and_slots_are_distinct() -> None:
    current = frame()
    assert current.seed_for(RandomSlot.TERMINAL) == 101631527650604959702970348563263520740
    assert current.uniform(RandomSlot.TERMINAL) == current.uniform(RandomSlot.TERMINAL)
    assert current.uniform(RandomSlot.TERMINAL) != current.uniform(RandomSlot.SHOT_MAKE)
    assert [(slot.name, slot.value) for slot in RandomSlot] == [
        ("TERMINAL", 0),
        ("STEALER", 1),
        ("FINISHER_ROUTE", 2),
        ("FINISHER_PLAYER", 3),
        ("SHOT_ZONE", 4),
        ("CONTEST", 5),
        ("SHOT_MAKE", 6),
        ("REBOUND_SIDE", 7),
        ("REBOUNDER", 8),
        ("PLAY_FAMILY", 9),
        ("PLAN_INITIATOR", 10),
        ("PLAN_PARTNER", 11),
        ("OFFBALL_TARGET", 12),
        ("OFFBALL_SCREEN_SETTER", 13),
        ("COVERAGE", 14),
        ("ASSIST_DECISION", 15),
        ("ASSISTER", 16),
        ("SHOOTING_FOUL", 17),
        ("FOULER", 18),
        ("FREE_THROW_1", 19),
        ("FREE_THROW_2", 20),
        ("FREE_THROW_3", 21),
        ("NON_SHOOTING_FOUL", 22),
        ("NON_SHOOTING_FOULER", 23),
        ("POSSESSION_DURATION", 24),
    ]


def test_random_frame_address_rejects_unstable_coordinates() -> None:
    with pytest.raises(ValueError):
        RandomFrameAddress("", 0, 0, 0, 0)
    with pytest.raises(ValueError):
        RandomFrameAddress("fixture", -1, 0, 0, 0)


def test_probability_node_uses_stable_inverse_cdf() -> None:
    result = sample_probability_node(
        frame(),
        RandomSlot.TERMINAL,
        (
            ProbabilityOption("first", "a", 1.0),
            ProbabilityOption("second", "b", 3.0),
        ),
    )
    assert result.selected_id == "second"
    assert result.selected == "b"
    assert result.probabilities == (0.25, 0.75)
    assert math.isclose(sum(result.probabilities), 1.0)


def test_probability_node_rejects_duplicate_ids() -> None:
    with pytest.raises(ValueError):
        sample_probability_node(
            frame(),
            RandomSlot.TERMINAL,
            (
                ProbabilityOption("same", "a", 1.0),
                ProbabilityOption("same", "b", 1.0),
            ),
        )


def test_probability_value_matches_traced_inverse_cdf() -> None:
    options = (
        ProbabilityOption("first", "a", 1.0),
        ProbabilityOption("second", "b", 3.0),
    )
    assert sample_probability_value(frame(), RandomSlot.TERMINAL, options) == (
        sample_probability_node(frame(), RandomSlot.TERMINAL, options).selected
    )

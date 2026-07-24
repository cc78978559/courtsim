import math
import random

import pytest
from hypothesis import given
from hypothesis import strategies as st

from courtsim.decisions import WeightError, normalize_weights, sample_weighted


@given(st.lists(st.floats(min_value=0, max_value=1e6), min_size=1, max_size=30))
def test_normalized_probabilities_are_finite_and_sum_to_one(weights: list[float]) -> None:
    choices = tuple((index, weight) for index, weight in enumerate((*weights, 1.0)))
    normalized = normalize_weights(choices)
    assert all(math.isfinite(choice.probability) for choice in normalized)
    assert math.isclose(math.fsum(choice.probability for choice in normalized), 1.0)


def test_invalid_weights_are_rejected() -> None:
    with pytest.raises(WeightError):
        normalize_weights(())
    with pytest.raises(WeightError):
        normalize_weights((("a", 0.0), ("b", 0.0)))
    with pytest.raises(WeightError):
        normalize_weights((("a", float("nan")),))
    with pytest.raises(WeightError):
        normalize_weights((("a", -1.0),))


def test_weighted_sampling_is_reproducible() -> None:
    choices = (("pass", 2.0), ("shoot", 1.0))
    left = random.Random(123)
    right = random.Random(123)
    assert [sample_weighted(left, choices) for _ in range(20)] == [
        sample_weighted(right, choices) for _ in range(20)
    ]

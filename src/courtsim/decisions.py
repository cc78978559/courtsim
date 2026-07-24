"""Validated probability utilities shared by future offense and defense policies."""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Generic, TypeVar

T = TypeVar("T")


class WeightError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class WeightedChoice(Generic[T]):
    value: T
    weight: float
    probability: float


def normalize_weights(choices: tuple[tuple[T, float], ...]) -> tuple[WeightedChoice[T], ...]:
    if not choices:
        raise WeightError("at least one weighted choice is required")
    if any(not math.isfinite(weight) or weight < 0 for _, weight in choices):
        raise WeightError("weights must be finite and non-negative")
    total = math.fsum(weight for _, weight in choices)
    if total <= 0:
        raise WeightError("at least one weight must be positive")
    return tuple(
        WeightedChoice(value=value, weight=weight, probability=weight / total)
        for value, weight in choices
    )


def sample_weighted(rng: random.Random, choices: tuple[tuple[T, float], ...]) -> T:
    normalized = normalize_weights(choices)
    threshold = rng.random()
    cumulative = 0.0
    for choice in normalized:
        cumulative += choice.probability
        if threshold < cumulative:
            return choice.value
    return normalized[-1].value

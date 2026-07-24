"""Probability-node primitives driven by addressable random slots."""

from dataclasses import dataclass
from typing import Generic, TypeVar

from courtsim.decisions import WeightedChoice, normalize_weights
from courtsim.randomness import RandomFrame, RandomSlot

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class ProbabilityOption(Generic[T]):
    id: str
    value: T
    weight: float


@dataclass(frozen=True, slots=True)
class ProbabilityNodeResult(Generic[T]):
    slot: RandomSlot
    selected_id: str
    selected: T
    options: tuple[ProbabilityOption[T], ...]
    probabilities: tuple[float, ...]
    uniform: float


def sample_probability_node(
    frame: RandomFrame,
    slot: RandomSlot,
    options: tuple[ProbabilityOption[T], ...],
) -> ProbabilityNodeResult[T]:
    ids = tuple(option.id for option in options)
    if len(ids) != len(set(ids)):
        raise ValueError("probability option ids must be unique")
    normalized: tuple[WeightedChoice[ProbabilityOption[T]], ...] = normalize_weights(
        tuple((option, option.weight) for option in options)
    )
    uniform = frame.uniform(slot)
    cumulative = 0.0
    selected = normalized[-1].value
    for choice in normalized:
        cumulative += choice.probability
        if uniform < cumulative:
            selected = choice.value
            break
    return ProbabilityNodeResult(
        slot=slot,
        selected_id=selected.id,
        selected=selected.value,
        options=options,
        probabilities=tuple(choice.probability for choice in normalized),
        uniform=uniform,
    )


def sample_probability_value(
    frame: RandomFrame,
    slot: RandomSlot,
    options: tuple[ProbabilityOption[T], ...],
) -> T:
    """Select identically to ``sample_probability_node`` without retaining trace data."""
    ids = tuple(option.id for option in options)
    if len(ids) != len(set(ids)):
        raise ValueError("probability option ids must be unique")
    normalized: tuple[WeightedChoice[ProbabilityOption[T]], ...] = normalize_weights(
        tuple((option, option.weight) for option in options)
    )
    uniform = frame.uniform(slot)
    cumulative = 0.0
    selected = normalized[-1].value.value
    for choice in normalized:
        cumulative += choice.probability
        if uniform < cumulative:
            selected = choice.value.value
            break
    return selected

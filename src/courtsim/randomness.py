"""Stable, named random streams.

Python's built-in hash is intentionally randomized between processes, so it
must never be used to derive simulation seeds.
"""

from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass
from enum import IntEnum


def derive_seed(master_seed: int, *labels: object) -> int:
    """Derive a stable 128-bit seed from a master seed and semantic labels."""
    digest = hashlib.blake2b(digest_size=16, person=b"courtsim-rng-v1")
    digest.update(str(master_seed).encode("utf-8"))
    for label in labels:
        encoded = str(label).encode("utf-8")
        digest.update(len(encoded).to_bytes(4, "big"))
        digest.update(encoded)
    return int.from_bytes(digest.digest(), "big")


@dataclass(frozen=True, slots=True)
class RandomStreams:
    """Factory for isolated deterministic random streams."""

    master_seed: int

    def seed_for(self, *labels: object) -> int:
        return derive_seed(self.master_seed, *labels)

    def stream(self, *labels: object) -> random.Random:
        return random.Random(self.seed_for(*labels))


class RandomSlot(IntEnum):
    """Append-only meanings within RNG schema v1."""

    TERMINAL = 0
    STEALER = 1
    FINISHER_ROUTE = 2
    FINISHER_PLAYER = 3
    SHOT_ZONE = 4
    CONTEST = 5
    SHOT_MAKE = 6
    REBOUND_SIDE = 7
    REBOUNDER = 8
    PLAY_FAMILY = 9
    PLAN_INITIATOR = 10
    PLAN_PARTNER = 11
    OFFBALL_TARGET = 12
    OFFBALL_SCREEN_SETTER = 13
    COVERAGE = 14
    ASSIST_DECISION = 15
    ASSISTER = 16
    SHOOTING_FOUL = 17
    FOULER = 18
    FREE_THROW_1 = 19
    FREE_THROW_2 = 20
    FREE_THROW_3 = 21
    NON_SHOOTING_FOUL = 22
    NON_SHOOTING_FOULER = 23
    POSSESSION_DURATION = 24


@dataclass(frozen=True, slots=True)
class RandomFrameAddress:
    scenario_id: str
    replicate_id: int
    game_id: int
    possession_index: int
    segment_index: int

    def __post_init__(self) -> None:
        if not self.scenario_id:
            raise ValueError("scenario_id must not be empty")
        values = (
            self.replicate_id,
            self.game_id,
            self.possession_index,
            self.segment_index,
        )
        if any(value < 0 for value in values):
            raise ValueError("random-frame indexes must be non-negative")


@dataclass(frozen=True, slots=True)
class RandomFrame:
    """Addressable uniforms that do not depend on branch draw counts."""

    master_seed: int
    address: RandomFrameAddress

    def seed_for(self, slot: RandomSlot) -> int:
        return derive_seed(
            self.master_seed,
            "random-frame-v1",
            self.address.scenario_id,
            self.address.replicate_id,
            self.address.game_id,
            self.address.possession_index,
            self.address.segment_index,
            int(slot),
        )

    def uniform(self, slot: RandomSlot) -> float:
        return random.Random(self.seed_for(slot)).random()

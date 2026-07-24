"""Deterministic five-player role scores, rankings and natural shares."""

import math
from dataclasses import dataclass
from functools import lru_cache

from courtsim.domain.player import AbilityRatings, PlayerProfile
from courtsim.player_features import (
    ability_rating_to_z,
    centered_mix_bias,
    scalar_tendency_bias,
)

ROLE_TEMPERATURE = 0.75


@dataclass(frozen=True, slots=True)
class RoleEntry:
    player_id: int
    score: float
    share: float
    rank: int


@dataclass(frozen=True, slots=True)
class RoleAllocation:
    role: str
    entries: tuple[RoleEntry, ...]


@dataclass(frozen=True, slots=True)
class LineupDynamicRoles:
    handler: RoleAllocation
    screener: RoleAllocation
    spacer: RoleAllocation
    rim_protector: RoleAllocation
    defensive_rebounder: RoleAllocation
    offensive_rebounder: RoleAllocation
    point_of_attack_defender: RoleAllocation
    primary_handler_id: int
    secondary_handler_id: int | None
    secondary_creator_deficient: bool
    eligible_spacer_ids: tuple[int, ...]
    primary_rim_protector_id: int | None
    primary_defensive_rebounder_id: int


def _allocation(role: str, scores: tuple[tuple[int, float], ...]) -> RoleAllocation:
    maximum = max(score / ROLE_TEMPERATURE for _, score in scores)
    weights = tuple(
        (player_id, math.exp(score / ROLE_TEMPERATURE - maximum), score)
        for player_id, score in scores
    )
    total = math.fsum(weight for _, weight, _ in weights)
    shares = {player_id: weight / total for player_id, weight, _ in weights}
    ranked = sorted(scores, key=lambda item: (-item[1], item[0]))
    return RoleAllocation(
        role,
        tuple(
            RoleEntry(player_id, score, shares[player_id], rank)
            for rank, (player_id, score) in enumerate(ranked, start=1)
        ),
    )


def _role_biases(profile: PlayerProfile) -> dict[str, float]:
    names = ("handler", "post", "spot_up", "cutter", "screener")
    values = tuple(getattr(profile.tendencies.play_role_mix, name) for name in names)
    return dict(zip(names, centered_mix_bias(values), strict=True))


@lru_cache(maxsize=256)
def derive_lineup_dynamic_roles(
    profiles: tuple[
        PlayerProfile,
        PlayerProfile,
        PlayerProfile,
        PlayerProfile,
        PlayerProfile,
    ],
) -> LineupDynamicRoles:
    player_ids = tuple(profile.player_id for profile in profiles)
    if len(set(player_ids)) != 5:
        raise ValueError("dynamic roles require five distinct players")

    score_rows: dict[str, list[tuple[int, float]]] = {
        "handler": [],
        "screener": [],
        "spacer": [],
        "rim_protector": [],
        "defensive_rebounder": [],
        "offensive_rebounder": [],
        "point_of_attack_defender": [],
    }
    profile_by_id = {profile.player_id: profile for profile in profiles}
    for profile in profiles:
        ability = profile.abilities

        def z(name: str, current: AbilityRatings = ability) -> float:
            return ability_rating_to_z(getattr(current, name))

        role = _role_biases(profile)
        tendency = profile.tendencies
        scores = {
            "handler": (
                0.28 * z("perimeter_creation")
                + 0.22 * z("playmaking")
                + 0.18 * z("ball_security")
                + 0.17 * z("offensive_decision")
                + 0.15 * role["handler"]
            ),
            "screener": (
                0.5294117647058824 * z("screen_setting")
                + 0.23529411764705882 * z("rim_finishing")
                + 0.11764705882352941 * z("offensive_rebounding")
                + 0.11764705882352941 * role["screener"]
            ),
            "spacer": (
                0.50 * z("three_point_shooting")
                + 0.25 * z("off_ball_movement")
                + 0.15 * role["spot_up"]
                + 0.10 * z("offensive_decision")
            ),
            "rim_protector": (
                0.7058823529411765 * z("rim_protection")
                + 0.29411764705882354 * z("defensive_awareness")
            ),
            "defensive_rebounder": (
                0.6842105263157895 * z("defensive_rebounding")
                + 0.21052631578947367 * scalar_tendency_bias(tendency.defensive_rebound_commitment)
                + 0.10526315789473684 * z("defensive_awareness")
            ),
            "offensive_rebounder": (
                0.65 * z("offensive_rebounding")
                + 0.25 * scalar_tendency_bias(tendency.offensive_rebound_commitment)
                + 0.10 * z("screen_setting")
            ),
            "point_of_attack_defender": (
                0.7058823529411765 * z("point_of_attack_defense")
                + 0.23529411764705882 * z("defensive_awareness")
                + 0.058823529411764705 * z("steal_skill")
            ),
        }
        for role_name, score in scores.items():
            score_rows[role_name].append((profile.player_id, score))

    allocations = {
        role_name: _allocation(role_name, tuple(rows)) for role_name, rows in score_rows.items()
    }
    handler = allocations["handler"]
    primary_handler = handler.entries[0]
    second_handler = handler.entries[1]
    secondary_ok = second_handler.share >= 0.18 and second_handler.score >= -0.25
    spacer = allocations["spacer"]
    eligible_spacers = tuple(
        entry.player_id
        for entry in spacer.entries
        if profile_by_id[entry.player_id].abilities.three_point_shooting >= 50
        and entry.score >= 0.0
    )[:2]
    rim = allocations["rim_protector"].entries[0]
    dreb = allocations["defensive_rebounder"].entries[0]
    return LineupDynamicRoles(
        handler=handler,
        screener=allocations["screener"],
        spacer=spacer,
        rim_protector=allocations["rim_protector"],
        defensive_rebounder=allocations["defensive_rebounder"],
        offensive_rebounder=allocations["offensive_rebounder"],
        point_of_attack_defender=allocations["point_of_attack_defender"],
        primary_handler_id=primary_handler.player_id,
        secondary_handler_id=second_handler.player_id if secondary_ok else None,
        secondary_creator_deficient=not secondary_ok,
        eligible_spacer_ids=eligible_spacers,
        primary_rim_protector_id=rim.player_id if rim.score >= 0.0 else None,
        primary_defensive_rebounder_id=dreb.player_id,
    )

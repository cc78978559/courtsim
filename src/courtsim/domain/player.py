"""Immutable demo-v1 player profile with no simulation overall rating."""

from dataclasses import dataclass, fields
from enum import IntEnum
from typing import Any


class SizeClass(IntEnum):
    SMALL = 0
    MEDIUM = 1
    LARGE = 2


def _validate_rating(value: int, field_name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= 100:
        raise ValueError(f"{field_name} must be an integer from 0 through 100")


def _validate_rating_dataclass(value: Any) -> None:
    for item in fields(value):
        _validate_rating(getattr(value, item.name), item.name)


@dataclass(frozen=True, slots=True)
class AbilityRatings:
    perimeter_creation: int
    post_creation: int
    ball_security: int
    playmaking: int
    off_ball_movement: int
    screen_setting: int
    rim_finishing: int
    midrange_shooting: int
    three_point_shooting: int
    free_throw_shooting: int
    foul_drawing: int
    point_of_attack_defense: int
    post_defense: int
    rim_protection: int
    steal_skill: int
    foul_discipline: int
    offensive_rebounding: int
    defensive_rebounding: int
    offensive_decision: int
    defensive_awareness: int

    def __post_init__(self) -> None:
        _validate_rating_dataclass(self)


@dataclass(frozen=True, slots=True)
class PlayRoleMix:
    handler: int
    post: int
    spot_up: int
    cutter: int
    screener: int

    def __post_init__(self) -> None:
        _validate_rating_dataclass(self)


@dataclass(frozen=True, slots=True)
class ShotZoneMix:
    rim: int
    midrange: int
    three: int

    def __post_init__(self) -> None:
        _validate_rating_dataclass(self)


@dataclass(frozen=True, slots=True)
class TendencyRatings:
    offensive_involvement: int
    play_role_mix: PlayRoleMix
    shoot_vs_pass: int
    shot_zone_mix: ShotZoneMix
    pass_risk: int
    contact_seek: int
    offensive_rebound_commitment: int
    defensive_rebound_commitment: int
    steal_gamble: int
    help_aggression: int
    block_chase: int

    def __post_init__(self) -> None:
        if not isinstance(self.play_role_mix, PlayRoleMix):
            raise ValueError("play_role_mix must be PlayRoleMix")
        if not isinstance(self.shot_zone_mix, ShotZoneMix):
            raise ValueError("shot_zone_mix must be ShotZoneMix")
        for field_name in (
            "offensive_involvement",
            "shoot_vs_pass",
            "pass_risk",
            "contact_seek",
            "offensive_rebound_commitment",
            "defensive_rebound_commitment",
            "steal_gamble",
            "help_aggression",
            "block_chase",
        ):
            _validate_rating(getattr(self, field_name), field_name)


@dataclass(frozen=True, slots=True)
class PlayerProfile:
    player_id: int
    name: str
    size_class: SizeClass
    abilities: AbilityRatings
    tendencies: TendencyRatings
    nominal_role_tags: tuple[str, ...] = ()
    schema_version: int = 1

    def __post_init__(self) -> None:
        if (
            not isinstance(self.schema_version, int)
            or isinstance(self.schema_version, bool)
            or self.schema_version != 1
        ):
            raise ValueError("unsupported player profile schema_version")
        if (
            not isinstance(self.player_id, int)
            or isinstance(self.player_id, bool)
            or self.player_id < 0
        ):
            raise ValueError("player_id must be non-negative")
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("player name must not be blank")
        if not isinstance(self.size_class, SizeClass):
            raise ValueError("size_class must be SizeClass")
        if not isinstance(self.abilities, AbilityRatings):
            raise ValueError("abilities must be AbilityRatings")
        if not isinstance(self.tendencies, TendencyRatings):
            raise ValueError("tendencies must be TendencyRatings")
        if not isinstance(self.nominal_role_tags, tuple) or any(
            not isinstance(tag, str) for tag in self.nominal_role_tags
        ):
            raise ValueError("nominal role tags must be a tuple of strings")
        if len(self.nominal_role_tags) != len(set(self.nominal_role_tags)):
            raise ValueError("nominal role tags must be unique")
        if any(
            not tag
            or not tag.isascii()
            or not tag[0].isalpha()
            or tag != tag.upper()
            or not tag.replace("_", "").isalnum()
            for tag in self.nominal_role_tags
        ):
            raise ValueError("nominal role tags must be uppercase ASCII identifiers")

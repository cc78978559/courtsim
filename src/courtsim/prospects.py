"""Deterministic annual prospect classes with field-level ability and potential."""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields, replace

from courtsim.career import (
    CareerPlayer,
    CareerStatus,
    DevelopmentTraits,
)
from courtsim.domain.player import AbilityRatings, PlayerProfile, SizeClass
from courtsim.domain.player_serialization import player_profile_to_dict
from courtsim.randomness import derive_seed

PROSPECT_GENERATION_VERSION = "prospect-generation-v1"

_CREATION = {
    "perimeter_creation",
    "post_creation",
    "ball_security",
    "playmaking",
    "offensive_decision",
}
_SHOOTING = {
    "midrange_shooting",
    "three_point_shooting",
    "free_throw_shooting",
    "off_ball_movement",
}
_DEFENSE = {
    "point_of_attack_defense",
    "post_defense",
    "rim_protection",
    "steal_skill",
    "foul_discipline",
    "defensive_awareness",
}
_INTERIOR = {
    "post_creation",
    "screen_setting",
    "rim_finishing",
    "rim_protection",
    "offensive_rebounding",
    "defensive_rebounding",
}
_ARCHETYPES = ("creator", "shooter", "defender", "interior", "balanced")


@dataclass(frozen=True, slots=True)
class ProspectGenerationRules:
    class_size: int = 4
    minimum_age: int = 18
    maximum_age: int = 21
    minimum_ability: int = 42
    maximum_ability: int = 74
    minimum_potential_gain: int = 6
    maximum_potential_gain: int = 24
    player_id_base: int = 10_000_000
    version: str = PROSPECT_GENERATION_VERSION

    def __post_init__(self) -> None:
        integer_values = (
            self.class_size,
            self.minimum_age,
            self.maximum_age,
            self.minimum_ability,
            self.maximum_ability,
            self.minimum_potential_gain,
            self.maximum_potential_gain,
            self.player_id_base,
        )
        if any(not isinstance(value, int) or isinstance(value, bool) for value in integer_values):
            raise ValueError("prospect generation rules must be integers")
        if not 1 <= self.class_size <= 60:
            raise ValueError("prospect class_size must be from one through sixty")
        if not 18 <= self.minimum_age <= self.maximum_age <= 23:
            raise ValueError("prospect age bounds are invalid")
        if not 0 <= self.minimum_ability <= self.maximum_ability <= 100:
            raise ValueError("prospect ability bounds are invalid")
        if not 0 <= self.minimum_potential_gain <= self.maximum_potential_gain <= 100:
            raise ValueError("prospect potential-gain bounds are invalid")
        if self.player_id_base < 1_000_000:
            raise ValueError("prospect player_id_base must reserve a high identity namespace")
        if self.version != PROSPECT_GENERATION_VERSION:
            raise ValueError("unsupported prospect generation version")


@dataclass(frozen=True, slots=True)
class ProspectClass:
    draft_year: int
    master_seed: int
    rules: ProspectGenerationRules
    players: tuple[CareerPlayer, ...]
    archetypes: tuple[str, ...]
    version: str = PROSPECT_GENERATION_VERSION

    def __post_init__(self) -> None:
        if (
            not isinstance(self.draft_year, int)
            or isinstance(self.draft_year, bool)
            or self.draft_year < 1
            or not isinstance(self.master_seed, int)
            or isinstance(self.master_seed, bool)
            or self.master_seed < 0
        ):
            raise ValueError("prospect class year and seed are invalid")
        if self.version != PROSPECT_GENERATION_VERSION:
            raise ValueError("unsupported prospect class version")
        if len(self.players) != self.rules.class_size or len(self.archetypes) != len(self.players):
            raise ValueError("prospect class does not match configured size")
        if self.players != tuple(sorted(self.players, key=lambda item: item.player_id)):
            raise ValueError("prospect class players must be ordered by player_id")
        if any(player.status is not CareerStatus.PROSPECT for player in self.players):
            raise ValueError("prospect class can contain only undrafted prospects")
        if any(archetype not in _ARCHETYPES for archetype in self.archetypes):
            raise ValueError("prospect class contains an unknown archetype")


def generate_prospect_class(
    *,
    draft_year: int,
    master_seed: int,
    templates: tuple[PlayerProfile, ...],
    existing_player_ids: frozenset[int] = frozenset(),
    rules: ProspectGenerationRules | None = None,
) -> ProspectClass:
    """Generate an address-stable class; template order cannot change its output."""
    active_rules = rules or ProspectGenerationRules()
    if not isinstance(draft_year, int) or isinstance(draft_year, bool) or draft_year < 1:
        raise ValueError("draft_year must be a positive integer")
    if not isinstance(master_seed, int) or isinstance(master_seed, bool) or master_seed < 0:
        raise ValueError("master_seed must be a non-negative integer")
    ordered_templates = tuple(sorted(templates, key=lambda item: item.player_id))
    if not ordered_templates:
        raise ValueError("prospect generation requires at least one profile template")
    if len({template.player_id for template in ordered_templates}) != len(ordered_templates):
        raise ValueError("prospect profile template ids must be unique")

    generated: list[CareerPlayer] = []
    archetypes: list[str] = []
    for slot in range(active_rules.class_size):
        player_id = active_rules.player_id_base + draft_year * 100 + slot
        if player_id in existing_player_ids:
            raise ValueError(
                f"generated prospect player id collides with league state: {player_id}"
            )
        template = ordered_templates[slot % len(ordered_templates)]
        archetype = _ARCHETYPES[
            derive_seed(
                master_seed,
                active_rules.version,
                draft_year,
                slot,
                "archetype",
            )
            % len(_ARCHETYPES)
        ]
        abilities: dict[str, int] = {}
        potential: dict[str, int] = {}
        for item in fields(AbilityRatings):
            ability = _ability(
                item.name,
                archetype,
                draft_year,
                slot,
                master_seed,
                active_rules,
            )
            gain_span = (
                active_rules.maximum_potential_gain - active_rules.minimum_potential_gain + 1
            )
            gain = active_rules.minimum_potential_gain + (
                derive_seed(
                    master_seed,
                    active_rules.version,
                    draft_year,
                    slot,
                    item.name,
                    "potential",
                )
                % gain_span
            )
            abilities[item.name] = ability
            potential[item.name] = min(100, ability + gain)
        age_span = active_rules.maximum_age - active_rules.minimum_age + 1
        age = active_rules.minimum_age + (
            derive_seed(
                master_seed,
                active_rules.version,
                draft_year,
                slot,
                "age",
            )
            % age_span
        )
        size = SizeClass(
            derive_seed(
                master_seed,
                active_rules.version,
                draft_year,
                slot,
                "size",
            )
            % len(SizeClass)
        )
        profile = replace(
            template,
            player_id=player_id,
            name=f"Prospect {draft_year}-{slot + 1:02d}",
            size_class=size,
            abilities=AbilityRatings(**abilities),
            nominal_role_tags=(),
        )
        peak_start = 25 + (
            derive_seed(
                master_seed,
                active_rules.version,
                draft_year,
                slot,
                "peak-start",
            )
            % 4
        )
        peak_span = 3 + (
            derive_seed(
                master_seed,
                active_rules.version,
                draft_year,
                slot,
                "peak-span",
            )
            % 3
        )
        development = DevelopmentTraits(
            growth_rate=_range_value(master_seed, draft_year, slot, "growth", 55, 95),
            peak_start_age=peak_start,
            peak_end_age=peak_start + peak_span,
            decline_resistance=_range_value(
                master_seed,
                draft_year,
                slot,
                "decline-resistance",
                35,
                85,
            ),
            consistency=_range_value(
                master_seed,
                draft_year,
                slot,
                "consistency",
                60,
                95,
            ),
        )
        generated.append(
            CareerPlayer(
                profile,
                age,
                0,
                development,
                AbilityRatings(**potential),
                CareerStatus.PROSPECT,
            )
        )
        archetypes.append(archetype)
    return ProspectClass(
        draft_year,
        master_seed,
        active_rules,
        tuple(generated),
        tuple(archetypes),
    )


def prospect_class_to_dict(value: ProspectClass) -> dict[str, object]:
    return {
        "version": value.version,
        "draft_year": value.draft_year,
        "master_seed": value.master_seed,
        "rules": asdict(value.rules),
        "players": [
            {
                "profile": player_profile_to_dict(player.profile),
                "age": player.age,
                "development": asdict(player.development),
                "potential": {
                    item.name: getattr(player.potential, item.name)
                    for item in fields(AbilityRatings)
                },
                "status": player.status.name,
                "archetype": archetype,
            }
            for player, archetype in zip(value.players, value.archetypes, strict=True)
        ],
    }


def _ability(
    ability: str,
    archetype: str,
    draft_year: int,
    slot: int,
    master_seed: int,
    rules: ProspectGenerationRules,
) -> int:
    span = rules.maximum_ability - rules.minimum_ability + 1
    value = rules.minimum_ability + (
        derive_seed(
            master_seed,
            rules.version,
            draft_year,
            slot,
            ability,
            "ability",
        )
        % span
    )
    if archetype == "creator":
        value += 8 if ability in _CREATION else -2
    elif archetype == "shooter":
        value += 8 if ability in _SHOOTING else -2
    elif archetype == "defender":
        value += 8 if ability in _DEFENSE else -2
    elif archetype == "interior":
        value += 8 if ability in _INTERIOR else -2
    return max(rules.minimum_ability, min(rules.maximum_ability, value))


def _range_value(
    master_seed: int,
    draft_year: int,
    slot: int,
    label: str,
    minimum: int,
    maximum: int,
) -> int:
    return minimum + (
        derive_seed(
            master_seed,
            PROSPECT_GENERATION_VERSION,
            draft_year,
            slot,
            label,
        )
        % (maximum - minimum + 1)
    )

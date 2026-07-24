"""Fixed rating transforms and audited node-specific feature compilation."""

from dataclasses import dataclass
from math import isfinite

from courtsim.domain.player import PlayerProfile

ABILITY_RATING_ANCHORS = (0, 20, 35, 50, 65, 80, 95, 100)
ABILITY_Z_ANCHORS = (-3.0, -1.8, -0.9, 0.0, 0.9, 1.8, 2.6, 3.0)


def ability_rating_to_z(rating: int) -> float:
    if not isinstance(rating, int) or isinstance(rating, bool) or not 0 <= rating <= 100:
        raise ValueError("ability rating must be an integer from 0 through 100")
    for index in range(1, len(ABILITY_RATING_ANCHORS)):
        upper_rating = ABILITY_RATING_ANCHORS[index]
        if rating <= upper_rating:
            lower_rating = ABILITY_RATING_ANCHORS[index - 1]
            lower_z = ABILITY_Z_ANCHORS[index - 1]
            upper_z = ABILITY_Z_ANCHORS[index]
            fraction = (rating - lower_rating) / (upper_rating - lower_rating)
            return lower_z + fraction * (upper_z - lower_z)
    raise AssertionError("rating anchors must include 100")


def scalar_tendency_bias(rating: int) -> float:
    if not isinstance(rating, int) or isinstance(rating, bool) or not 0 <= rating <= 100:
        raise ValueError("tendency rating must be an integer from 0 through 100")
    return max(-2.75, min(2.75, (rating - 50) / 18.0))


def centered_mix_bias(ratings: tuple[int, ...]) -> tuple[float, ...]:
    if not ratings:
        raise ValueError("mix requires at least one rating")
    for rating in ratings:
        if not isinstance(rating, int) or isinstance(rating, bool) or not 0 <= rating <= 100:
            raise ValueError("mix ratings must be integers from 0 through 100")
    mean = sum(ratings) / len(ratings)
    return tuple(max(-3.0, min(3.0, (rating - mean) / 15.0)) for rating in ratings)


@dataclass(frozen=True, slots=True)
class AttributeEffectSpec:
    primary_node: str
    allowed_secondary_nodes: tuple[str, ...] = ()
    forbidden_nodes: tuple[str, ...] = ()
    max_secondary_logit: float = 0.40
    dormant: bool = False

    def __post_init__(self) -> None:
        if not isfinite(self.max_secondary_logit) or self.max_secondary_logit < 0:
            raise ValueError("max_secondary_logit must be finite and non-negative")


ATTRIBUTE_EFFECT_LEDGER: dict[str, AttributeEffectSpec] = {
    "perimeter_creation": AttributeEffectSpec(
        "interaction.on_ball", ("role.handler",), ("shot.make",)
    ),
    "post_creation": AttributeEffectSpec("interaction.post", dormant=True),
    "ball_security": AttributeEffectSpec("terminal.turnover.lost_ball", ("role.handler",)),
    "playmaking": AttributeEffectSpec(
        "interaction.pass_creation", ("role.handler",), ("assist.resolve",)
    ),
    "off_ball_movement": AttributeEffectSpec("interaction.target_availability", ("role.spacer",)),
    "screen_setting": AttributeEffectSpec("interaction.screen", ("role.screener",)),
    "rim_finishing": AttributeEffectSpec("shot.make.rim", ("role.screener",)),
    "midrange_shooting": AttributeEffectSpec("shot.make.midrange"),
    "three_point_shooting": AttributeEffectSpec(
        "shot.make.three",
        ("role.spacer", "scouting.three_point_threat"),
        ("shot.zone.select",),
    ),
    "free_throw_shooting": AttributeEffectSpec("free_throw.make"),
    "foul_drawing": AttributeEffectSpec("foul.draw"),
    "point_of_attack_defense": AttributeEffectSpec(
        "interaction.on_ball_defense", ("role.point_of_attack_defender",)
    ),
    "post_defense": AttributeEffectSpec(
        "interaction.post_defense", ("role.rim_protector",), dormant=True
    ),
    "rim_protection": AttributeEffectSpec(
        "shot.block_contest",
        ("role.rim_protector", "scouting.rim_deterrence"),
        ("shot.make", "rebound.resolve"),
    ),
    "steal_skill": AttributeEffectSpec(
        "terminal.turnover.steal_pressure", ("role.point_of_attack_defender",)
    ),
    "foul_discipline": AttributeEffectSpec("foul.commit"),
    "offensive_rebounding": AttributeEffectSpec(
        "rebound.hazard.offense", ("role.offensive_rebounder",)
    ),
    "defensive_rebounding": AttributeEffectSpec(
        "rebound.hazard.defense", ("role.defensive_rebounder",)
    ),
    "offensive_decision": AttributeEffectSpec(
        "terminal.turnover.decision", ("role.handler", "role.spacer")
    ),
    "defensive_awareness": AttributeEffectSpec(
        "interaction.rotation",
        (
            "role.rim_protector",
            "role.defensive_rebounder",
            "role.point_of_attack_defender",
        ),
    ),
}

TENDENCY_NODE_REGISTRY: dict[str, str] = {
    "offensive_involvement": "participant.select",
    "play_role_mix.handler": "role.handler",
    "play_role_mix.post": "role.post",
    "play_role_mix.spot_up": "role.spacer",
    "play_role_mix.cutter": "role.cutter",
    "play_role_mix.screener": "role.screener",
    "shoot_vs_pass": "finisher.select",
    "shot_zone_mix.rim": "shot.zone.select",
    "shot_zone_mix.midrange": "shot.zone.select",
    "shot_zone_mix.three": "shot.zone.select",
    "pass_risk": "pass_risk.tradeoff",
    "contact_seek": "foul.draw",
    "offensive_rebound_commitment": "rebound.hazard.offense",
    "defensive_rebound_commitment": "rebound.hazard.defense",
    "steal_gamble": "terminal.turnover.steal_pressure",
    "help_aggression": "defense.response",
    "block_chase": "shot.block_contest",
}

DORMANT_TENDENCIES = frozenset({"play_role_mix.post"})


@dataclass(frozen=True, slots=True)
class NodePlayerFeatures:
    node: str
    player_id: int
    values: tuple[tuple[str, float], ...]


def validate_attribute_effect_ledger() -> None:
    expected = {
        "perimeter_creation",
        "post_creation",
        "ball_security",
        "playmaking",
        "off_ball_movement",
        "screen_setting",
        "rim_finishing",
        "midrange_shooting",
        "three_point_shooting",
        "free_throw_shooting",
        "foul_drawing",
        "point_of_attack_defense",
        "post_defense",
        "rim_protection",
        "steal_skill",
        "foul_discipline",
        "offensive_rebounding",
        "defensive_rebounding",
        "offensive_decision",
        "defensive_awareness",
    }
    if set(ATTRIBUTE_EFFECT_LEDGER) != expected:
        raise ValueError("attribute ledger must cover every ability exactly once")
    for name, spec in ATTRIBUTE_EFFECT_LEDGER.items():
        if spec.primary_node in spec.allowed_secondary_nodes:
            raise ValueError(f"{name} repeats its primary node as a secondary")
        if set(spec.allowed_secondary_nodes) & set(spec.forbidden_nodes):
            raise ValueError(f"{name} has overlapping allowed and forbidden nodes")


validate_attribute_effect_ledger()


def compile_player_features_for_node(profile: PlayerProfile, node: str) -> NodePlayerFeatures:
    values: list[tuple[str, float]] = []
    for ability_name, spec in ATTRIBUTE_EFFECT_LEDGER.items():
        if spec.dormant:
            continue
        if node == spec.primary_node or node in spec.allowed_secondary_nodes:
            values.append(
                (
                    ability_name,
                    ability_rating_to_z(getattr(profile.abilities, ability_name)),
                )
            )

    scalar_tendencies = {
        "offensive_involvement": profile.tendencies.offensive_involvement,
        "shoot_vs_pass": profile.tendencies.shoot_vs_pass,
        "pass_risk": profile.tendencies.pass_risk,
        "contact_seek": profile.tendencies.contact_seek,
        "offensive_rebound_commitment": (profile.tendencies.offensive_rebound_commitment),
        "defensive_rebound_commitment": (profile.tendencies.defensive_rebound_commitment),
        "steal_gamble": profile.tendencies.steal_gamble,
        "help_aggression": profile.tendencies.help_aggression,
        "block_chase": profile.tendencies.block_chase,
    }
    for tendency_name, rating in scalar_tendencies.items():
        if tendency_name in DORMANT_TENDENCIES:
            continue
        if TENDENCY_NODE_REGISTRY[tendency_name] == node:
            values.append((tendency_name, scalar_tendency_bias(rating)))

    role_names = ("handler", "post", "spot_up", "cutter", "screener")
    role_biases = centered_mix_bias(
        tuple(getattr(profile.tendencies.play_role_mix, name) for name in role_names)
    )
    for name, bias in zip(role_names, role_biases, strict=True):
        key = f"play_role_mix.{name}"
        if key not in DORMANT_TENDENCIES and TENDENCY_NODE_REGISTRY[key] == node:
            values.append((key, bias))

    zone_names = ("rim", "midrange", "three")
    zone_biases = centered_mix_bias(
        tuple(getattr(profile.tendencies.shot_zone_mix, name) for name in zone_names)
    )
    for name, bias in zip(zone_names, zone_biases, strict=True):
        key = f"shot_zone_mix.{name}"
        if TENDENCY_NODE_REGISTRY[key] == node:
            values.append((key, bias))

    return NodePlayerFeatures(node, profile.player_id, tuple(sorted(values)))

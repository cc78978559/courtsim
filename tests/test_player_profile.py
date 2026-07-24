import hashlib
import json
from dataclasses import fields, replace
from pathlib import Path

import pytest

from courtsim.domain.player import (
    AbilityRatings,
    PlayerProfile,
    PlayRoleMix,
    ShotZoneMix,
    SizeClass,
    TendencyRatings,
)
from courtsim.domain.player_serialization import (
    PlayerSerializationError,
    player_lineup_from_json,
    player_profile_from_json,
    player_profile_to_json,
)
from courtsim.dynamic_roles import derive_lineup_dynamic_roles
from courtsim.player_features import (
    ATTRIBUTE_EFFECT_LEDGER,
    ability_rating_to_z,
    centered_mix_bias,
    compile_player_features_for_node,
    scalar_tendency_bias,
)


def neutral_abilities() -> AbilityRatings:
    return AbilityRatings(
        perimeter_creation=50,
        post_creation=50,
        ball_security=50,
        playmaking=50,
        off_ball_movement=50,
        screen_setting=50,
        rim_finishing=50,
        midrange_shooting=50,
        three_point_shooting=50,
        free_throw_shooting=50,
        foul_drawing=50,
        point_of_attack_defense=50,
        post_defense=50,
        rim_protection=50,
        steal_skill=50,
        foul_discipline=50,
        offensive_rebounding=50,
        defensive_rebounding=50,
        offensive_decision=50,
        defensive_awareness=50,
    )


def neutral_tendencies() -> TendencyRatings:
    return TendencyRatings(
        offensive_involvement=50,
        play_role_mix=PlayRoleMix(50, 50, 50, 50, 50),
        shoot_vs_pass=50,
        shot_zone_mix=ShotZoneMix(50, 50, 50),
        pass_risk=50,
        contact_seek=50,
        offensive_rebound_commitment=50,
        defensive_rebound_commitment=50,
        steal_gamble=50,
        help_aggression=50,
        block_chase=50,
    )


def profile(player_id: int, name: str | None = None) -> PlayerProfile:
    return PlayerProfile(
        player_id,
        name or f"Player {player_id}",
        SizeClass.MEDIUM,
        neutral_abilities(),
        neutral_tendencies(),
    )


def test_profile_contract_has_exactly_20_abilities_and_17_tendency_values() -> None:
    assert len(fields(AbilityRatings)) == 20
    assert 1 + 5 + 1 + 3 + 7 == 17
    assert set(ATTRIBUTE_EFFECT_LEDGER) == {item.name for item in fields(AbilityRatings)}
    assert not hasattr(profile(1), "overall_rating")
    assert [(item.name, item.value) for item in SizeClass] == [
        ("SMALL", 0),
        ("MEDIUM", 1),
        ("LARGE", 2),
    ]


def test_profile_json_round_trip_and_golden_hash() -> None:
    original = replace(
        profile(7, "示例球员"),
        nominal_role_tags=("MOVEMENT_SHOOTER",),
    )
    payload = player_profile_to_json(original)
    assert player_profile_from_json(payload) == original
    assert hashlib.sha256(payload.encode("utf-8")).hexdigest() == (
        "e75ee9b06cebf122c939216b3c36858eadfb8322a46f41b2f6344c9721a060f6"
    )


def test_checked_in_example_profile_loads() -> None:
    path = Path(__file__).parents[1] / "examples" / "player_profile_v1.json"
    loaded = player_profile_from_json(path.read_text(encoding="utf-8"))
    assert loaded.player_id == 7
    assert loaded.abilities.three_point_shooting == 90
    assert loaded.nominal_role_tags == ("MOVEMENT_SHOOTER",)


def test_profile_rejects_out_of_range_bool_and_duplicate_tags() -> None:
    with pytest.raises(ValueError):
        replace(neutral_abilities(), rim_finishing=101)
    with pytest.raises(ValueError):
        replace(neutral_abilities(), rim_finishing=True)
    with pytest.raises(ValueError):
        replace(profile(1), nominal_role_tags=("A", "A"))
    with pytest.raises(ValueError):
        replace(profile(1), nominal_role_tags=("not valid",))


def test_profile_decoder_rejects_unknown_fields() -> None:
    payload = player_profile_to_json(profile(1))
    with pytest.raises(PlayerSerializationError):
        player_profile_from_json(payload[:-1] + ',"overall_rating":99}')


@pytest.mark.parametrize(
    ("rating", "expected"),
    [(0, -3.0), (20, -1.8), (35, -0.9), (50, 0.0), (65, 0.9), (80, 1.8), (95, 2.6), (100, 3.0)],
)
def test_ability_anchor_mapping(rating: int, expected: float) -> None:
    assert ability_rating_to_z(rating) == expected


def test_tendency_mappings_are_centered_and_shift_invariant() -> None:
    assert scalar_tendency_bias(50) == 0.0
    assert scalar_tendency_bias(0) == -2.75
    assert scalar_tendency_bias(100) == 2.75
    assert centered_mix_bias((80, 80, 80)) == (0.0, 0.0, 0.0)
    assert centered_mix_bias((40, 40, 40)) == (0.0, 0.0, 0.0)
    assert centered_mix_bias((80, 50, 20)) == (2.0, 0.0, -2.0)


def test_node_compiler_exposes_only_owned_features() -> None:
    shooter = replace(
        profile(1),
        abilities=replace(
            neutral_abilities(),
            three_point_shooting=80,
            perimeter_creation=95,
        ),
        tendencies=replace(
            neutral_tendencies(),
            shot_zone_mix=ShotZoneMix(20, 30, 90),
        ),
        nominal_role_tags=("ELITE_SCORER",),
    )
    make_features = compile_player_features_for_node(shooter, "shot.make.three")
    assert make_features.values == (("three_point_shooting", 1.8),)

    zone_features = compile_player_features_for_node(shooter, "shot.zone.select")
    assert {name for name, _ in zone_features.values} == {
        "shot_zone_mix.midrange",
        "shot_zone_mix.rim",
        "shot_zone_mix.three",
    }
    assert "three_point_shooting" not in dict(zone_features.values)
    assert compile_player_features_for_node(shooter, "free_throw.make").values == (
        ("free_throw_shooting", 0.0),
    )
    assert {name for name, _ in compile_player_features_for_node(shooter, "foul.draw").values} == {
        "contact_seek",
        "foul_drawing",
    }


def test_nominal_tags_never_change_compiled_features() -> None:
    plain = profile(1)
    tagged = replace(plain, nominal_role_tags=("ELITE_SCORER", "STRETCH_BIG"))
    assert compile_player_features_for_node(plain, "shot.make.three") == (
        compile_player_features_for_node(tagged, "shot.make.three")
    )


def test_dynamic_roles_are_deterministic_and_ties_use_player_id() -> None:
    lineup = (profile(5), profile(3), profile(1), profile(4), profile(2))
    roles = derive_lineup_dynamic_roles(lineup)
    assert [entry.player_id for entry in roles.handler.entries] == [1, 2, 3, 4, 5]
    assert sum(entry.share for entry in roles.handler.entries) == pytest.approx(1.0)
    assert roles.primary_handler_id == 1


def test_dynamic_role_specialists_rank_first() -> None:
    handler = replace(
        profile(1),
        abilities=replace(
            neutral_abilities(),
            perimeter_creation=90,
            playmaking=85,
            ball_security=80,
            offensive_decision=80,
        ),
        tendencies=replace(
            neutral_tendencies(),
            play_role_mix=PlayRoleMix(90, 20, 20, 20, 20),
        ),
    )
    spacer = replace(
        profile(2),
        abilities=replace(
            neutral_abilities(),
            three_point_shooting=90,
            off_ball_movement=90,
        ),
        tendencies=replace(
            neutral_tendencies(),
            play_role_mix=PlayRoleMix(20, 20, 90, 20, 20),
        ),
    )
    rim_protector = replace(
        profile(3),
        abilities=replace(
            neutral_abilities(),
            rim_protection=90,
            defensive_awareness=85,
            post_defense=80,
        ),
    )
    rebounder = replace(
        profile(4),
        abilities=replace(
            neutral_abilities(),
            defensive_rebounding=95,
            offensive_rebounding=90,
        ),
        tendencies=replace(
            neutral_tendencies(),
            offensive_rebound_commitment=85,
            defensive_rebound_commitment=90,
        ),
    )
    roles = derive_lineup_dynamic_roles((handler, spacer, rim_protector, rebounder, profile(5)))
    assert roles.primary_handler_id == 1
    assert roles.eligible_spacer_ids[0] == 2
    assert roles.primary_rim_protector_id == 3
    assert roles.primary_defensive_rebounder_id == 4


def test_lineup_without_positive_rim_protector_is_explicit() -> None:
    weak = tuple(
        replace(
            profile(player_id),
            abilities=replace(
                neutral_abilities(),
                rim_protection=35,
                defensive_awareness=35,
                post_defense=35,
            ),
        )
        for player_id in range(1, 6)
    )
    assert len(weak) == 5
    roles = derive_lineup_dynamic_roles(weak)
    assert roles.primary_rim_protector_id is None


def test_dormant_abilities_do_not_change_dynamic_roles() -> None:
    baseline = (profile(1), profile(2), profile(3), profile(4), profile(5))
    changed_first = replace(
        baseline[0],
        abilities=replace(
            baseline[0].abilities,
            post_creation=100,
            post_defense=100,
            foul_discipline=100,
        ),
    )
    changed = (changed_first, *baseline[1:])
    assert derive_lineup_dynamic_roles(changed) == derive_lineup_dynamic_roles(baseline)


def test_dynamic_roles_cache_immutable_lineups() -> None:
    lineup = tuple(profile(player_id) for player_id in range(1, 6))
    derive_lineup_dynamic_roles.cache_clear()
    try:
        first = derive_lineup_dynamic_roles(lineup)
        second = derive_lineup_dynamic_roles(lineup)
        info = derive_lineup_dynamic_roles.cache_info()
        assert first is second
        assert info.misses == 1
        assert info.hits == 1
    finally:
        derive_lineup_dynamic_roles.cache_clear()


def test_five_player_lineup_json_is_strict_and_ordered() -> None:
    payload = {
        "schema_version": 1,
        "lineup_id": "synthetic-test-lineup",
        "players": [
            json.loads(player_profile_to_json(profile(player_id))) for player_id in range(1, 6)
        ],
    }
    lineup = player_lineup_from_json(json.dumps(payload))
    assert tuple(player.player_id for player in lineup) == (1, 2, 3, 4, 5)

    players = payload["players"]
    assert isinstance(players, list)
    payload["players"] = players[:4]
    with pytest.raises(PlayerSerializationError, match="exactly five"):
        player_lineup_from_json(json.dumps(payload))

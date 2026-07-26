from dataclasses import fields

import pytest
from test_game_runtime import player

from courtsim.career import CareerStatus
from courtsim.domain.player import AbilityRatings
from courtsim.prospects import (
    ProspectGenerationRules,
    generate_prospect_class,
    prospect_class_to_dict,
)


def test_prospect_class_is_deterministic_and_template_order_independent() -> None:
    templates = (player(1), player(2), player(3))
    first = generate_prospect_class(
        draft_year=2029,
        master_seed=991,
        templates=templates,
    )
    second = generate_prospect_class(
        draft_year=2029,
        master_seed=991,
        templates=tuple(reversed(templates)),
    )
    assert first == second
    assert len(first.players) == 4
    assert len(set(first.archetypes)) >= 2


def test_prospect_identity_is_stable_while_seed_changes_talent() -> None:
    first = generate_prospect_class(
        draft_year=2029,
        master_seed=1,
        templates=(player(1),),
    )
    second = generate_prospect_class(
        draft_year=2029,
        master_seed=2,
        templates=(player(1),),
    )
    assert tuple(item.player_id for item in first.players) == tuple(
        item.player_id for item in second.players
    )
    assert first.players != second.players


def test_generated_players_have_field_level_ceiling_and_development() -> None:
    rules = ProspectGenerationRules(
        class_size=8,
        minimum_ability=45,
        maximum_ability=70,
        minimum_potential_gain=10,
        maximum_potential_gain=20,
    )
    result = generate_prospect_class(
        draft_year=2030,
        master_seed=44,
        templates=(player(1), player(2)),
        rules=rules,
    )
    for prospect in result.players:
        assert prospect.status is CareerStatus.PROSPECT
        assert 18 <= prospect.age <= 21
        assert prospect.seasons_pro == 0
        assert prospect.draft_year == prospect.draft_round == prospect.draft_pick == 0
        for item in fields(AbilityRatings):
            current = getattr(prospect.profile.abilities, item.name)
            ceiling = getattr(prospect.potential, item.name)
            assert 45 <= current <= 70
            assert current + 10 <= ceiling <= min(100, current + 20)
        assert 55 <= prospect.development.growth_rate <= 95
        assert prospect.development.peak_start_age < prospect.development.peak_end_age


def test_prospect_audit_payload_is_complete_and_json_ready() -> None:
    result = generate_prospect_class(
        draft_year=2029,
        master_seed=9,
        templates=(player(1),),
    )
    payload = prospect_class_to_dict(result)
    assert payload["version"] == "prospect-generation-v1"
    assert payload["draft_year"] == 2029
    players = payload["players"]
    assert isinstance(players, list)
    assert len(players) == 4
    assert all(item["status"] == "PROSPECT" for item in players)


def test_prospect_generation_rejects_collision_or_invalid_contract() -> None:
    rules = ProspectGenerationRules()
    collision = rules.player_id_base + 2029 * 100
    with pytest.raises(ValueError, match="collides"):
        generate_prospect_class(
            draft_year=2029,
            master_seed=1,
            templates=(player(1),),
            existing_player_ids=frozenset({collision}),
            rules=rules,
        )
    with pytest.raises(ValueError, match="class_size"):
        ProspectGenerationRules(class_size=0)
    with pytest.raises(ValueError, match="template"):
        generate_prospect_class(
            draft_year=2029,
            master_seed=1,
            templates=(),
        )

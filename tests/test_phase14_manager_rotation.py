from dataclasses import fields, replace

import pytest
from test_game_runtime import player

from courtsim.career import CareerPlayer, CareerStatus, DevelopmentTraits
from courtsim.domain.game import GameClockConfig
from courtsim.domain.player import AbilityRatings
from courtsim.manager_ai import ManagerProfile
from courtsim.manager_rotation import (
    ManagerRotationRules,
    generate_manager_rotation,
)


def ratings(value: int) -> AbilityRatings:
    return AbilityRatings(**{item.name: value for item in fields(AbilityRatings)})


def rotation_player(
    player_id: int,
    *,
    value: int = 60,
    ceiling: int | None = None,
    injury_burden: int = 0,
) -> CareerPlayer:
    profile = replace(player(player_id), abilities=ratings(value))
    return CareerPlayer(
        profile,
        22,
        2,
        DevelopmentTraits(),
        ratings(ceiling if ceiling is not None else value),
        CareerStatus.ACTIVE,
        injury_burden=injury_burden,
    )


def test_rotation_is_deterministic_auditable_and_clock_complete() -> None:
    roster = tuple(rotation_player(player_id, value=75 - player_id) for player_id in range(1, 9))
    config = GameClockConfig(4, 720, 15)
    first = generate_manager_rotation(
        team_id="home",
        roster=roster,
        profile=ManagerProfile("manager-home", "home"),
        game_config=config,
    )
    second = generate_manager_rotation(
        team_id="home",
        roster=tuple(reversed(roster)),
        profile=ManagerProfile("manager-home", "home"),
        game_config=config,
    )
    assert first == second
    assert len(first.lineup) == 5
    assert len(first.rotation_order) == 8
    assert len(first.decisions) == 8
    assert len(first.plan.stints) == 16
    assert sum(seconds for _, seconds in first.target_seconds) == 5 * 4 * 720
    assert all(decision.selected is not None for decision in first.decisions)


def test_development_manager_can_prefer_upside_inside_reasonable_band() -> None:
    old_tie_break = rotation_player(1, value=65, ceiling=65)
    young_upside = rotation_player(2, value=65, ceiling=95)
    fillers = tuple(rotation_player(player_id, value=55) for player_id in range(3, 7))
    neutral = generate_manager_rotation(
        team_id="home",
        roster=(old_tie_break, young_upside, *fillers),
        profile=ManagerProfile("neutral", "home"),
        game_config=GameClockConfig(1, 120, 15),
    )
    developer = generate_manager_rotation(
        team_id="home",
        roster=(old_tie_break, young_upside, *fillers),
        profile=ManagerProfile("developer", "home", development_bias=100),
        game_config=GameClockConfig(1, 120, 15),
    )
    assert neutral.rotation_order[0] == 1
    assert developer.rotation_order[0] == 2


def test_rotation_limits_active_group_but_keeps_emergency_substitutes() -> None:
    roster = tuple(
        rotation_player(
            player_id,
            value=80 - player_id,
            injury_burden=100 if player_id == 12 else 0,
        )
        for player_id in range(1, 13)
    )
    result = generate_manager_rotation(
        team_id="home",
        roster=roster,
        profile=ManagerProfile("manager-home", "home"),
        game_config=GameClockConfig(1, 120, 15),
        rules=ManagerRotationRules(maximum_rotation_players=8),
    )
    assert len(result.rotation_order) == 8
    assert len(result.substitution_order) == 12
    assert 12 not in result.rotation_order
    assert dict(result.target_seconds)[12] == 0


def test_rotation_contracts_reject_invalid_rosters_and_rules() -> None:
    with pytest.raises(ValueError, match="at least five"):
        generate_manager_rotation(
            team_id="home",
            roster=tuple(rotation_player(player_id) for player_id in range(1, 5)),
            profile=ManagerProfile("manager-home", "home"),
            game_config=GameClockConfig(1, 120, 15),
        )
    with pytest.raises(ValueError, match="maximum_rotation_players"):
        ManagerRotationRules(maximum_rotation_players=4)

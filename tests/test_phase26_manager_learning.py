from dataclasses import replace

import pytest
from test_phase14_manager_rotation import ratings, rotation_player

from courtsim.domain.game import GameClockConfig
from courtsim.manager_ai import ManagerProfile
from courtsim.manager_learning import (
    ManagerLearningState,
    OpponentObservation,
    advance_manager_learning_from_season,
    opponent_rotation_adjustment,
    update_manager_learning,
)
from courtsim.manager_rotation import generate_manager_rotation
from courtsim.season import SeasonResult, SeasonSchedule


def test_manager_learning_accumulates_weighted_cross_season_memory() -> None:
    initial = ManagerLearningState("manager-A", "A", 2028)
    first = update_manager_learning(
        initial,
        (OpponentObservation("B", 2, 80, 60, 70, 75, 40),),
        completed_season=2029,
    )
    second = update_manager_learning(
        first,
        (OpponentObservation("B", 1, 50, 90, 40, 30, 80),),
        completed_season=2030,
    )
    memory = second.opponents[0]
    assert second.seasons_observed == 2
    assert second.tenure_start_season == 2029
    assert memory.games_observed == 3
    assert memory.offense_strength == 70
    assert memory.defense_strength == 70
    assert memory.pace == 60


def test_manager_replacement_starts_a_new_tenure_without_breaking_team_history() -> None:
    season = SeasonResult(SeasonSchedule(("A", "B"), ()), (), (), (), ())
    prior = (
        ManagerLearningState("old-A", "A", 2030, 2),
        ManagerLearningState("manager-B", "B", 2030, 2),
    )
    advanced = advance_manager_learning_from_season(
        season,
        prior,
        {
            "A": ManagerProfile("new-A", "A"),
            "B": ManagerProfile("manager-B", "B"),
        },
        GameClockConfig(1, 120, 15),
        completed_season=2031,
    )
    by_team = {item.team_id: item for item in advanced}
    assert by_team["A"].seasons_observed == 1
    assert by_team["A"].tenure_start_season == 2031
    assert by_team["B"].seasons_observed == 3
    assert by_team["B"].tenure_start_season == 2029


def test_opponent_model_produces_bounded_white_box_rotation_emphasis() -> None:
    learned = update_manager_learning(
        ManagerLearningState("manager-A", "A", 2028),
        (OpponentObservation("B", 4, 90, 80, 75, 85, 20),),
        completed_season=2029,
    )
    adjustment = opponent_rotation_adjustment(learned, "B")
    assert adjustment is not None
    assert adjustment.defense_emphasis_bps > 0
    assert adjustment.offense_emphasis_bps > 0
    assert adjustment.perimeter_defense_emphasis_bps > 0
    assert adjustment.interior_defense_emphasis_bps < 0
    assert opponent_rotation_adjustment(learned, "C") is None


def test_manager_learning_rejects_non_monotonic_seasons() -> None:
    with pytest.raises(ValueError, match="monotonically"):
        update_manager_learning(
            ManagerLearningState("manager-A", "A", 2029),
            (),
            completed_season=2029,
        )


def test_learned_shot_profile_changes_rotation_priority() -> None:
    perimeter = rotation_player(1)
    perimeter = replace(
        perimeter,
        profile=replace(
            perimeter.profile,
            abilities=replace(
                ratings(60),
                point_of_attack_defense=100,
                steal_skill=100,
                post_defense=20,
                rim_protection=20,
            ),
        ),
        potential=ratings(100),
    )
    interior = rotation_player(2)
    interior = replace(
        interior,
        profile=replace(
            interior.profile,
            abilities=replace(
                ratings(60),
                point_of_attack_defense=20,
                steal_skill=20,
                post_defense=100,
                rim_protection=100,
            ),
        ),
        potential=ratings(100),
    )
    fillers = tuple(rotation_player(player_id, value=40) for player_id in range(3, 7))
    learned = update_manager_learning(
        ManagerLearningState("manager-home", "home", 2028),
        (OpponentObservation("B", 8, 60, 60, 60, 100, 0),),
        completed_season=2029,
    )
    result = generate_manager_rotation(
        team_id="home",
        roster=(perimeter, interior, *fillers),
        profile=ManagerProfile("manager-home", "home"),
        game_config=GameClockConfig(1, 120, 15),
        opponent_adjustment=opponent_rotation_adjustment(learned, "B"),
    )
    assert result.rotation_order[0] == perimeter.player_id
    opponent_contributions = [
        contribution
        for contribution in result.decisions[0].candidates[0].contributions
        if contribution.source == "opponent-model"
    ]
    assert opponent_contributions

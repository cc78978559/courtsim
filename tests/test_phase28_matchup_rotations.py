import json
from collections.abc import Mapping
from dataclasses import replace

import pytest
from test_game_runtime import PARAMETERS, player
from test_phase4_season import CONFIG, FRAME, schedule, season_teams
from test_phase12_manager_league_adapter import adapter, league_state, request

from courtsim.manager_experiment import ManagerExperimentArm
from courtsim.manager_league_adapter import league_state_to_json
from courtsim.manager_learning import (
    ManagerLearningState,
    OpponentObservation,
    update_manager_learning,
)
from courtsim.model.game_runtime import GameTeam
from courtsim.season import ScheduledGame, SeasonConfig, sample_season


def test_season_resolves_teams_for_every_scheduled_matchup() -> None:
    calls: list[tuple[int, str, str]] = []

    def resolver(
        scheduled: ScheduledGame,
        teams: Mapping[str, GameTeam],
    ) -> tuple[GameTeam, GameTeam]:
        calls.append(
            (
                scheduled.game_id,
                scheduled.home_team_id,
                scheduled.away_team_id,
            )
        )
        return teams[scheduled.home_team_id], teams[scheduled.away_team_id]

    result = sample_season(
        parameters=PARAMETERS,
        game_config=CONFIG,
        schedule=schedule(1, 2, 3),
        teams=season_teams(),
        frame=FRAME,
        season_config=SeasonConfig(injury_probability_bps=0),
        team_resolver=resolver,
    )
    assert calls == [
        (
            game.game_id,
            game.home_team_id,
            game.away_team_id,
        )
        for game in result.schedule.games
    ]


def test_season_rejects_resolver_that_changes_roster_identity() -> None:
    home, away = season_teams()

    def resolver(
        scheduled: ScheduledGame,
        teams: Mapping[str, GameTeam],
    ) -> tuple[GameTeam, GameTeam]:
        changed = replace(
            home,
            bench_profiles=(player(7),),
            substitution_order=(1, 2, 3, 4, 5, 7),
        )
        return changed, away

    with pytest.raises(ValueError, match="preserve"):
        sample_season(
            parameters=PARAMETERS,
            game_config=CONFIG,
            schedule=schedule(1),
            teams=(home, away),
            frame=FRAME,
            season_config=SeasonConfig(injury_probability_bps=0),
            team_resolver=resolver,
        )


def test_adapter_uses_persisted_opponent_memory_for_game_and_playoff_rotations() -> None:
    learned_a = update_manager_learning(
        ManagerLearningState("manager-A", "A", 2027),
        (OpponentObservation("B", 8, 90, 85, 75, 95, 20),),
        completed_season=2028,
    )
    initial = replace(league_state(), manager_learning=(learned_a,))
    execution = adapter()(
        replace(
            request(ManagerExperimentArm.INCUMBENT),
            season_year=2029,
            state_payload=league_state_to_json(
                replace(
                    initial,
                    management=replace(initial.management, season_year=2029),
                )
            ),
        )
    )
    audit = json.loads(execution.audit_payload)
    matchup = audit["rotations"]["A"]["opponents"]["B"]
    assert matchup["adjustment"] is not None
    assert matchup["adjustment"]["games_observed"] == 8
    assert matchup["tactics"]["confidence_bps"] == 10_000
    assert matchup["tactics"]["play_family_logit_biases"]["ISOLATION"] < 0
    assert matchup["tactics"]["coverage_logit_biases"]["SWITCH"] > 0
    assert matchup["tactics"]["effective_tempo"] < 50
    assert any(
        contribution["source"] == "opponent-model" and contribution["value"] != 0
        for decision in matchup["rotation"]["decisions"]
        for candidate in decision["candidates"]
        for contribution in candidate["contributions"]
    )

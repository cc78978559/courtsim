import json
from dataclasses import replace

import pytest
from test_game_runtime import (
    AWAY,
    HOME,
    MATCHUPS,
    NON_BONUS_INTENTIONAL_FOUL_PARAMETERS,
    PARAMETERS,
    player,
)

from courtsim.domain.game import GameClockConfig
from courtsim.domain.serialization import SerializationError
from courtsim.model import (
    FatigueConfig,
    GameTeam,
    sample_game,
)
from courtsim.model.game_runtime import possession_duration_options
from courtsim.randomness import RandomFrame, RandomFrameAddress
from courtsim.rotations import RotationPlan, RotationStint
from courtsim.season import (
    ScheduledGame,
    SeasonConfig,
    SeasonResult,
    SeasonSchedule,
    audit_season,
    sample_season,
    season_result_from_json,
    season_result_to_json,
)

CONFIG = GameClockConfig(1, 20, 10)
FRAME = RandomFrame(404, RandomFrameAddress("season", 0, 0, 0, 0))


def season_teams() -> tuple[GameTeam, GameTeam]:
    return (
        replace(HOME, bench_profiles=(player(6),), substitution_order=(1, 2, 3, 4, 5, 6)),
        replace(
            AWAY,
            bench_profiles=(player(16),),
            substitution_order=(11, 12, 13, 14, 15, 16),
        ),
    )


def schedule(*days: int) -> SeasonSchedule:
    return SeasonSchedule(
        ("home", "away"),
        tuple(
            ScheduledGame(
                index,
                day,
                "home" if index % 2 == 0 else "away",
                "away" if index % 2 == 0 else "home",
            )
            for index, day in enumerate(days)
        ),
    )


def run_season(
    *days: int,
    season_config: SeasonConfig | None = None,
) -> SeasonResult:
    return sample_season(
        parameters=PARAMETERS,
        game_config=CONFIG,
        schedule=schedule(*days),
        teams=season_teams(),
        frame=FRAME,
        fatigue_config=FatigueConfig(maximum_fatigue=1_000),
        season_config=season_config or SeasonConfig(injury_probability_bps=0),
    )


def test_season_validation_accepts_parameter_owned_possession_durations() -> None:
    config = GameClockConfig(1, 180, 15)
    allowed = possession_duration_options(NON_BONUS_INTENTIONAL_FOUL_PARAMETERS)
    result = sample_season(
        parameters=NON_BONUS_INTENTIONAL_FOUL_PARAMETERS,
        game_config=config,
        schedule=schedule(1),
        teams=season_teams(),
        frame=FRAME,
        fatigue_config=FatigueConfig(maximum_fatigue=1_000),
        season_config=SeasonConfig(injury_probability_bps=0),
    )
    assert audit_season(result, config, allowed).games_completed == 1
    assert season_result_from_json(season_result_to_json(result), config, allowed) == result


def test_schedule_contract_is_strict_and_chronological() -> None:
    with pytest.raises(ValueError, match="ordered"):
        SeasonSchedule(
            ("home", "away"),
            (
                ScheduledGame(1, 2, "home", "away"),
                ScheduledGame(0, 1, "away", "home"),
            ),
        )
    with pytest.raises(ValueError, match="known"):
        SeasonSchedule(("home", "away"), (ScheduledGame(0, 1, "home", "other"),))
    with pytest.raises(ValueError, match="unique"):
        SeasonSchedule(
            ("home", "away"),
            (
                ScheduledGame(0, 1, "home", "away"),
                ScheduledGame(0, 2, "away", "home"),
            ),
        )


def test_season_is_reproducible_and_input_teams_remain_immutable() -> None:
    teams = season_teams()
    first = sample_season(
        parameters=PARAMETERS,
        game_config=CONFIG,
        schedule=schedule(1, 2, 4),
        teams=teams,
        frame=FRAME,
        season_config=SeasonConfig(injury_probability_bps=0),
    )
    second = sample_season(
        parameters=PARAMETERS,
        game_config=CONFIG,
        schedule=schedule(1, 2, 4),
        teams=teams,
        frame=FRAME,
        season_config=SeasonConfig(injury_probability_bps=0),
    )
    assert first == second
    assert teams == season_teams()


def test_cross_game_fatigue_and_off_day_recovery_are_canonical() -> None:
    result = run_season(
        1,
        2,
        4,
        season_config=SeasonConfig(
            injury_probability_bps=0,
            daily_fatigue_recovery=1_000,
        ),
    )
    first, second, third = (record.result for record in result.games)
    assert first is not None and second is not None and third is not None
    first_final = {item.player_id: item.fatigue for item in first.final_fatigue}
    second_start = {
        item.player_id: item.fatigue
        for item in second.possessions[0].offense_fatigue + second.possessions[0].defense_fatigue
    }
    third_start = {
        item.player_id: item.fatigue
        for item in third.possessions[0].offense_fatigue + third.possessions[0].defense_fatigue
    }
    assert second_start == {
        player_id: fatigue for player_id, fatigue in first_final.items() if player_id not in {6, 16}
    }
    assert set(third_start.values()) == {0}


def test_injuries_are_isolated_deterministic_and_recover_on_return_day() -> None:
    injured = run_season(
        1,
        2,
        3,
        season_config=SeasonConfig(
            injury_probability_bps=10_000,
            minimum_days_out=1,
            maximum_days_out=1,
        ),
    )
    healthy = run_season(1, season_config=SeasonConfig(injury_probability_bps=0))
    assert injured.games[0].result == healthy.games[0].result
    assert len([item for item in injured.injuries if item.game_id == 0]) == 10
    assert {item.return_day for item in injured.injuries if item.game_id == 0} == {3}
    assert injured.games[1].result is None
    assert len(injured.games[1].home_unavailable) == 5
    assert injured.games[2].result is not None


def test_unavailable_player_is_removed_from_lineup_and_rotation() -> None:
    home, away = season_teams()
    home = replace(
        home,
        rotation_plan=RotationPlan((RotationStint(1, 10, (1, 2, 3, 4, 6)),)),
    )
    result = sample_season(
        parameters=PARAMETERS,
        game_config=CONFIG,
        schedule=schedule(1, 2),
        teams=(home, away),
        frame=FRAME,
        season_config=SeasonConfig(
            injury_probability_bps=200,
            minimum_days_out=2,
            maximum_days_out=2,
        ),
    )
    assert [item.player_id for item in result.injuries if item.game_id == 0] == [1]
    second = result.games[1]
    assert second.result is not None
    assert second.away_unavailable == (1,)
    assert all(
        1 not in lineup
        for record in second.result.possessions
        for lineup in (record.offense_lineup, record.defense_lineup)
        if lineup is not None
    )
    assert all(substitution.incoming_player_id != 1 for substitution in second.result.substitutions)


def test_forfeit_and_standings_are_derived_from_availability() -> None:
    result = run_season(
        1,
        2,
        season_config=SeasonConfig(
            injury_probability_bps=10_000,
            minimum_days_out=2,
            maximum_days_out=2,
            forfeit_score=2,
        ),
    )
    assert result.games[1].result is None
    assert result.games[1].home_score == result.games[1].away_score == 0
    assert sum(row.wins + row.losses + row.ties for row in result.standings) == 4
    assert tuple(row.rank for row in result.standings) == (1, 2)


def test_season_json_round_trip_and_strict_tamper_rejection() -> None:
    result = run_season(1, 3)
    payload = season_result_to_json(result)
    assert season_result_from_json(payload, CONFIG) == result
    raw = json.loads(payload)
    raw["standings"][0]["wins"] += 1
    with pytest.raises(SerializationError, match="standings"):
        season_result_from_json(json.dumps(raw), CONFIG)
    raw = json.loads(payload)
    raw["extra"] = True
    with pytest.raises(SerializationError, match="keys"):
        season_result_from_json(json.dumps(raw), CONFIG)


def test_season_audit_counts_games_injuries_and_missed_appearances() -> None:
    result = run_season(
        1,
        2,
        season_config=SeasonConfig(
            injury_probability_bps=10_000,
            minimum_days_out=1,
            maximum_days_out=1,
        ),
    )
    audit = audit_season(result, CONFIG)
    assert audit.games_scheduled == 2
    assert audit.games_completed == 1
    assert audit.forfeits == 1
    assert audit.injuries == 10
    assert audit.player_games_missed == 10
    assert audit.standings_wins == audit.standings_losses


def test_initial_fatigue_contract_rejects_partial_or_disabled_state() -> None:
    home, away = season_teams()
    with pytest.raises(ValueError, match="requires"):
        sample_game(
            parameters=PARAMETERS,
            config=CONFIG,
            home=home,
            away=away,
            matchups=MATCHUPS,
            frame=FRAME,
            initial_fatigue={},
        )
    with pytest.raises(ValueError, match="exactly"):
        sample_game(
            parameters=PARAMETERS,
            config=CONFIG,
            home=home,
            away=away,
            matchups=MATCHUPS,
            frame=FRAME,
            fatigue_config=FatigueConfig(),
            initial_fatigue={1: 0},
        )

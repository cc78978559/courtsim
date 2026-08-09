import json
from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest

from courtsim.analysis.distribution import audit_game_results
from courtsim.domain.enums import GameEndReason, PossessionEndReason
from courtsim.domain.game import GameClockConfig, validate_game_result
from courtsim.domain.game_serialization import game_result_from_json, game_result_to_json
from courtsim.domain.plans import Lineup
from courtsim.domain.player import PlayerProfile
from courtsim.domain.player_serialization import player_profile_from_json
from courtsim.domain.results import NonShootingFoulSegmentResult
from courtsim.domain.serialization import SerializationError
from courtsim.model import (
    DefensiveMatchups,
    GameMatchups,
    GameSample,
    GameTeam,
    Matchup,
    TeamTempoStrategy,
    TraceMode,
    effective_tempo_rating,
    late_game_strategy_config,
    possession_duration_weights,
    sample_game,
)
from courtsim.model.interaction_compiler import ProfileLineup
from courtsim.parameters import load_model_parameters
from courtsim.randomness import RandomFrame, RandomFrameAddress
from courtsim.stats import StatCode, attribute_possession

ROOT = Path(__file__).parents[1]
PARAMETERS = load_model_parameters(
    ROOT / "data" / "model_schema_demo_v1_3.json",
    ROOT / "data" / "model_parameters_demo_0.4.0.json",
)
TEMPO_PARAMETERS = load_model_parameters(
    ROOT / "data" / "model_schema_demo_v1_8.json",
    ROOT / "data" / "model_parameters_demo_1.0.0.json",
)
LATE_TEMPO_PARAMETERS = load_model_parameters(
    ROOT / "data" / "model_schema_demo_v1_9.json",
    ROOT / "data" / "model_parameters_demo_1.1.0.json",
)
LATE_STRATEGY_PARAMETERS = load_model_parameters(
    ROOT / "data" / "model_schema_demo_v1_10.json",
    ROOT / "data" / "model_parameters_demo_1.2.0.json",
)
FORMAL_INTENTIONAL_FOUL_PARAMETERS = load_model_parameters(
    ROOT / "data" / "model_schema_demo_v1_11.json",
    ROOT / "data" / "model_parameters_demo_1.3.0.json",
)
NON_BONUS_INTENTIONAL_FOUL_PARAMETERS = load_model_parameters(
    ROOT / "data" / "model_schema_demo_v1_12.json",
    ROOT / "data" / "model_parameters_demo_1.4.0.json",
)
HOME_LINEUP: Lineup = (1, 2, 3, 4, 5)
AWAY_LINEUP: Lineup = (11, 12, 13, 14, 15)


def player(player_id: int) -> PlayerProfile:
    template = player_profile_from_json(
        (ROOT / "examples" / "player_profile_v1.json").read_text(encoding="utf-8")
    )
    return replace(template, player_id=player_id, name=f"Player {player_id}")


def profiles(lineup: Lineup) -> ProfileLineup:
    return cast(ProfileLineup, tuple(player(player_id) for player_id in lineup))


HOME = GameTeam("home", HOME_LINEUP, profiles(HOME_LINEUP))
AWAY = GameTeam("away", AWAY_LINEUP, profiles(AWAY_LINEUP))
MATCHUPS = GameMatchups(
    DefensiveMatchups(
        (
            Matchup(1, 11),
            Matchup(2, 12),
            Matchup(3, 13),
            Matchup(4, 14),
            Matchup(5, 15),
        )
    ),
    DefensiveMatchups(
        (
            Matchup(11, 1),
            Matchup(12, 2),
            Matchup(13, 3),
            Matchup(14, 4),
            Matchup(15, 5),
        )
    ),
)
SHORT_GAME = GameClockConfig(regulation_periods=2, period_seconds=25, possession_seconds=10)


def game(
    seed: int,
    *,
    config: GameClockConfig = SHORT_GAME,
    max_segments: int | None = None,
    trace_mode: TraceMode = TraceMode.FULL,
) -> GameSample:
    return sample_game(
        parameters=PARAMETERS,
        config=config,
        home=HOME,
        away=AWAY,
        matchups=MATCHUPS,
        frame=RandomFrame(seed, RandomFrameAddress("game", 0, 0, 0, 0)),
        max_segments_per_possession=max_segments,
        trace_mode=trace_mode,
    )


def test_regulation_game_replays_with_contiguous_clock_and_alternating_offense() -> None:
    sampled = game(7)
    assert sampled == game(7)
    assert sampled.result.completed
    assert sampled.result.end_reason is GameEndReason.REGULATION
    assert len(sampled.result.possessions) == 6
    assert [
        (
            item.period,
            item.clock_start_seconds,
            item.clock_end_seconds,
            item.offense_team_id,
        )
        for item in sampled.result.possessions
    ] == [
        (1, 25, 15, "home"),
        (1, 15, 5, "away"),
        (1, 5, 0, "home"),
        (2, 25, 15, "away"),
        (2, 15, 5, "home"),
        (2, 5, 0, "away"),
    ]
    validate_game_result(sampled.result, SHORT_GAME)


def test_aggregate_only_retains_canonical_game_but_not_decision_samples() -> None:
    full = game(7)
    aggregate = game(7, trace_mode=TraceMode.AGGREGATE_ONLY)
    assert aggregate.result == full.result
    assert full.possession_samples
    assert aggregate.possession_samples == ()


def test_player_aggregate_mode_omits_possessions_but_retains_box_and_zone_totals() -> None:
    full = game(7)
    aggregate = game(7, trace_mode=TraceMode.PLAYER_AGGREGATES)
    assert aggregate.result.possessions == ()
    assert aggregate.result.possessions_omitted
    assert aggregate.result.player_stats == full.result.player_stats
    assert aggregate.result.playing_time == full.result.playing_time
    assert aggregate.result.player_shot_zones == full.result.player_shot_zones
    assert aggregate.result.home_possessions + aggregate.result.away_possessions == len(
        full.result.possessions
    )
    assert aggregate.possession_samples == ()
    validate_game_result(aggregate.result, SHORT_GAME)
    assert (
        game_result_from_json(game_result_to_json(aggregate.result), SHORT_GAME) == aggregate.result
    )


def test_score_and_player_ledger_equal_the_possession_event_source() -> None:
    result = game(7).result
    expected_score = {"home": 0, "away": 0}
    expected_stats: dict[tuple[int, StatCode], int] = {}
    for record in result.possessions:
        offense = HOME if record.offense_team_id == HOME.team_id else AWAY
        defense = AWAY if offense is HOME else HOME
        attribution = attribute_possession(record.result, offense.lineup, defense.lineup)
        expected_score[offense.team_id] += attribution.score_delta
        for delta in attribution.player_deltas:
            key = (delta.player_id, delta.stat)
            expected_stats[key] = expected_stats.get(key, 0) + delta.amount
    assert (result.home_score, result.away_score) == (
        expected_score["home"],
        expected_score["away"],
    )
    assert {
        (delta.player_id, delta.stat): delta.amount for delta in result.player_stats
    } == expected_stats


def test_truncated_possession_aborts_game_without_switching_offense() -> None:
    sampled = game(
        25,
        config=GameClockConfig(1, 10, 10),
        max_segments=1,
    )
    assert not sampled.result.completed
    assert sampled.result.end_reason is GameEndReason.POSSESSION_TRUNCATED
    assert len(sampled.result.possessions) == 1
    final = sampled.result.possessions[0]
    assert final.offense_team_id == "home"
    assert final.result.end_reason is PossessionEndReason.SEGMENT_LIMIT


def test_game_contract_rejects_invalid_clock_and_team_identity() -> None:
    with pytest.raises(ValueError):
        GameClockConfig(0, 10, 5)
    with pytest.raises(ValueError):
        GameClockConfig(1, 10, 11)
    with pytest.raises(ValueError):
        replace(HOME, team_id=" ")
    with pytest.raises(ValueError):
        sample_game(
            parameters=PARAMETERS,
            config=GameClockConfig(1, 10, 10),
            home=HOME,
            away=replace(AWAY, team_id="home"),
            matchups=MATCHUPS,
            frame=RandomFrame(1, RandomFrameAddress("game", 0, 0, 0, 0)),
        )


def test_game_json_round_trip_rejects_tampered_score_and_clock() -> None:
    result = game(7).result
    payload = game_result_to_json(result)
    assert game_result_from_json(payload, SHORT_GAME) == result

    wrong_score = json.loads(payload)
    wrong_score["home_score"] += 1
    with pytest.raises(SerializationError):
        game_result_from_json(json.dumps(wrong_score), SHORT_GAME)

    wrong_clock = json.loads(payload)
    wrong_clock["possessions"][1]["clock_start_seconds"] += 1
    with pytest.raises(SerializationError):
        game_result_from_json(json.dumps(wrong_clock), SHORT_GAME)


def test_team_tempo_changes_pace_without_invalid_clock_durations() -> None:
    config = GameClockConfig(regulation_periods=1, period_seconds=720, possession_seconds=15)

    def total_possessions(tempo: int) -> int:
        strategy = TeamTempoStrategy(tempo)
        return sum(
            len(
                sample_game(
                    parameters=TEMPO_PARAMETERS,
                    config=config,
                    home=replace(HOME, tempo_strategy=strategy),
                    away=replace(AWAY, tempo_strategy=strategy),
                    matchups=MATCHUPS,
                    frame=RandomFrame(
                        seed,
                        RandomFrameAddress("tempo-test", 0, seed, 0, 0),
                    ),
                    trace_mode=TraceMode.AGGREGATE_ONLY,
                ).result.possessions
            )
            for seed in range(20)
        )

    assert total_possessions(90) > total_possessions(50) > total_possessions(10)


def test_tempo_version_preserves_possession_outcomes_for_shared_indices() -> None:
    config = GameClockConfig(regulation_periods=1, period_seconds=720, possession_seconds=15)
    frame = RandomFrame(37, RandomFrameAddress("tempo-compatibility", 0, 0, 0, 0))
    previous = sample_game(
        parameters=load_model_parameters(
            ROOT / "data" / "model_schema_demo_v1_7.json",
            ROOT / "data" / "model_parameters_demo_0.9.0.json",
        ),
        config=config,
        home=HOME,
        away=AWAY,
        matchups=MATCHUPS,
        frame=frame,
        trace_mode=TraceMode.AGGREGATE_ONLY,
    )
    current = sample_game(
        parameters=TEMPO_PARAMETERS,
        config=config,
        home=HOME,
        away=AWAY,
        matchups=MATCHUPS,
        frame=frame,
        trace_mode=TraceMode.AGGREGATE_ONLY,
    )
    shared = min(len(previous.result.possessions), len(current.result.possessions))
    assert tuple(item.result for item in previous.result.possessions[:shared]) == tuple(
        item.result for item in current.result.possessions[:shared]
    )


def test_late_game_tempo_adjustment_is_bounded_and_context_specific() -> None:
    assert (
        effective_tempo_rating(
            LATE_TEMPO_PARAMETERS,
            HOME.tempo_strategy,
            period=4,
            clock_seconds=90,
            regulation_periods=4,
            offense_score=90,
            defense_score=96,
        )
        == 70
    )
    assert (
        effective_tempo_rating(
            LATE_TEMPO_PARAMETERS,
            HOME.tempo_strategy,
            period=4,
            clock_seconds=90,
            regulation_periods=4,
            offense_score=96,
            defense_score=90,
        )
        == 35
    )
    assert (
        effective_tempo_rating(
            LATE_TEMPO_PARAMETERS,
            HOME.tempo_strategy,
            period=4,
            clock_seconds=90,
            regulation_periods=4,
            offense_score=94,
            defense_score=94,
        )
        == 50
    )
    assert (
        effective_tempo_rating(
            LATE_TEMPO_PARAMETERS,
            HOME.tempo_strategy,
            period=3,
            clock_seconds=90,
            regulation_periods=4,
            offense_score=90,
            defense_score=110,
        )
        == 50
    )

    trailing = possession_duration_weights(
        LATE_TEMPO_PARAMETERS,
        HOME.tempo_strategy,
        period=4,
        clock_seconds=90,
        regulation_periods=4,
        offense_score=90,
        defense_score=96,
    )
    leading = possession_duration_weights(
        LATE_TEMPO_PARAMETERS,
        HOME.tempo_strategy,
        period=4,
        clock_seconds=90,
        regulation_periods=4,
        offense_score=96,
        defense_score=90,
    )
    assert trailing[0].weight > leading[0].weight
    assert trailing[2].weight < leading[2].weight


def test_late_game_version_preserves_the_first_three_periods() -> None:
    config = GameClockConfig()
    frame = RandomFrame(91, RandomFrameAddress("late-tempo-compatibility", 0, 0, 0, 0))
    previous = sample_game(
        parameters=TEMPO_PARAMETERS,
        config=config,
        home=HOME,
        away=AWAY,
        matchups=MATCHUPS,
        frame=frame,
        trace_mode=TraceMode.AGGREGATE_ONLY,
    )
    current = sample_game(
        parameters=LATE_TEMPO_PARAMETERS,
        config=config,
        home=HOME,
        away=AWAY,
        matchups=MATCHUPS,
        frame=frame,
        trace_mode=TraceMode.AGGREGATE_ONLY,
    )
    previous_first_three = tuple(item for item in previous.result.possessions if item.period <= 3)
    current_first_three = tuple(item for item in current.result.possessions if item.period <= 3)
    assert previous_first_three == current_first_three


def test_formal_intentional_foul_is_bonus_gated_and_uses_three_seconds() -> None:
    frame = RandomFrame(28, RandomFrameAddress("find", 0, 28, 0, 0))
    current = sample_game(
        parameters=FORMAL_INTENTIONAL_FOUL_PARAMETERS,
        config=GameClockConfig(),
        home=HOME,
        away=AWAY,
        matchups=MATCHUPS,
        frame=frame,
        trace_mode=TraceMode.FULL,
    )
    committed = [
        (record, sample)
        for record, sample in zip(
            current.result.possessions,
            current.possession_samples,
            strict=True,
        )
        if sample.intentional_foul_committed
    ]
    assert len(committed) == 2
    for record, sample in committed:
        assert record.clock_start_seconds - record.clock_end_seconds == 3
        first = sample.result.segments[0]
        assert isinstance(first, NonShootingFoulSegmentResult)
        assert first.in_bonus
        assert sample.defensive_fouls_committed >= 1

    shadow = sample_game(
        parameters=LATE_STRATEGY_PARAMETERS,
        config=GameClockConfig(),
        home=HOME,
        away=AWAY,
        matchups=MATCHUPS,
        frame=frame,
        trace_mode=TraceMode.FULL,
    )
    assert not any(sample.intentional_foul_committed for sample in shadow.possession_samples)


def test_non_bonus_intentional_foul_adds_timed_inbound_continuation() -> None:
    sampled = sample_game(
        parameters=NON_BONUS_INTENTIONAL_FOUL_PARAMETERS,
        config=GameClockConfig(),
        home=HOME,
        away=AWAY,
        matchups=MATCHUPS,
        frame=RandomFrame(6, RandomFrameAddress("find-nonbonus", 0, 6, 0, 0)),
        trace_mode=TraceMode.FULL,
    )
    continuations = [
        (record, sample)
        for record, sample in zip(
            sampled.result.possessions,
            sampled.possession_samples,
            strict=True,
        )
        if sample.intentional_foul_committed
        and not cast(NonShootingFoulSegmentResult, sample.result.segments[0]).in_bonus
    ]
    assert continuations
    for record, sample in continuations:
        assert len(sample.result.segments) >= 2
        assert record.clock_start_seconds - record.clock_end_seconds in {15, 18, 21}
    strategy = late_game_strategy_config(NON_BONUS_INTENTIONAL_FOUL_PARAMETERS)
    assert strategy is not None
    audit = audit_game_results((sampled.result,), strategy)
    assert audit.intentional_fouls_committed == audit.intentional_foul_opportunities
    assert audit.intentional_foul_continuations == len(continuations)

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

from courtsim.domain.enums import (
    Coverage,
    FoulTeamSide,
    GameEndReason,
    PossessionEndReason,
    TechnicalFoulType,
)
from courtsim.domain.game import GameClockConfig, validate_game_result
from courtsim.domain.plans import IsolationPlan, plan_participants
from courtsim.domain.player import PlayerProfile
from courtsim.domain.results import (
    OffensiveFoulSegmentResult,
    PossessionResult,
    TechnicalFoulSegmentResult,
    offense_retains_ball,
    validate_action_segment_result,
)
from courtsim.domain.serialization import (
    SerializationError,
    segment_result_from_dict,
    segment_result_from_json,
    segment_result_to_dict,
    segment_result_to_json,
)
from courtsim.model import GameSample, TraceMode, sample_game
from courtsim.model.game_runtime import possession_duration_options
from courtsim.randomness import RandomFrame, RandomFrameAddress
from courtsim.rules import (
    GameRules,
    audit_rule_events,
    non_shooting_foul_free_throws,
    replace_ineligible_players,
    select_technical_free_throw_shooter,
)
from courtsim.stats import StatCode, attribute_segment


def test_tied_regulation_continues_into_deterministic_overtime() -> None:
    config = GameClockConfig(
        regulation_periods=1,
        period_seconds=10,
        possession_seconds=10,
        overtime_seconds=10,
        max_overtimes=4,
        overtime_enabled=True,
    )
    sampled = sample_game(
        parameters=PARAMETERS,
        config=config,
        home=HOME,
        away=AWAY,
        matchups=MATCHUPS,
        frame=RandomFrame(0, RandomFrameAddress("game", 0, 0, 0, 0)),
    )
    assert (
        sampled.result
        == sample_game(
            parameters=PARAMETERS,
            config=config,
            home=HOME,
            away=AWAY,
            matchups=MATCHUPS,
            frame=RandomFrame(0, RandomFrameAddress("game", 0, 0, 0, 0)),
        ).result
    )
    assert sampled.result.end_reason is GameEndReason.OVERTIME
    assert [record.period for record in sampled.result.possessions] == [1, 2]
    assert sampled.result.home_score != sampled.result.away_score
    validate_game_result(sampled.result, config)


def test_overtime_clock_and_limit_are_explicit() -> None:
    with pytest.raises(ValueError, match="overtime_seconds"):
        GameClockConfig(overtime_seconds=0)
    with pytest.raises(ValueError, match="max_overtimes"):
        GameClockConfig(max_overtimes=0)


def test_foul_out_replacement_is_roster_ordered_and_has_explicit_failure() -> None:
    rules = GameRules(player_foul_limit=2)
    assert replace_ineligible_players(
        active_lineup=(1, 2, 3, 4, 5),
        roster_order=(1, 2, 3, 4, 5, 6, 7),
        ineligible=frozenset({2, 4}),
    ) == (1, 6, 3, 7, 5)
    assert (
        replace_ineligible_players(
            active_lineup=(1, 2, 3, 4, 5),
            roster_order=(1, 2, 3, 4, 5, 6),
            ineligible=frozenset({2, 4, 6}),
        )
        is None
    )
    assert rules.version == "nba-v1"


def test_game_team_materializes_a_legal_active_lineup_from_bench() -> None:
    template: PlayerProfile = HOME.profiles[0]
    bench = replace(template, player_id=6, name="Player 6")
    roster_team = replace(HOME, bench_profiles=(bench,))
    active = roster_team.with_lineup((1, 6, 3, 4, 5))
    assert active.lineup == (1, 6, 3, 4, 5)
    assert tuple(profile.player_id for profile in active.profiles) == active.lineup
    assert tuple(profile.player_id for profile in active.bench_profiles) == (2,)
    assert active.roster_order == (1, 2, 3, 4, 5, 6)


def test_foul_out_replacement_is_used_by_the_runtime() -> None:
    home = replace(HOME, bench_profiles=tuple(player(player_id) for player_id in range(6, 11)))
    away = replace(AWAY, bench_profiles=tuple(player(player_id) for player_id in range(16, 21)))

    def run() -> GameSample:
        return sample_game(
            parameters=NON_BONUS_INTENTIONAL_FOUL_PARAMETERS,
            config=GameClockConfig(1, 180, 15),
            home=home,
            away=away,
            matchups=MATCHUPS,
            frame=RandomFrame(1, RandomFrameAddress("foulout", 0, 0, 0, 0)),
            trace_mode=TraceMode.FULL,
            rules=GameRules(player_foul_limit=1),
        )

    sampled = run()
    participant_ids = {
        player_id
        for possession in sampled.possession_samples
        for segment in possession.result.segments
        for player_id in plan_participants(segment.plan)
    }
    assert 6 in participant_ids
    assert sampled.result.end_reason is GameEndReason.REGULATION
    assert sampled.result == run().result


def test_no_legal_replacement_ends_with_an_explicit_reason() -> None:
    sampled = sample_game(
        parameters=NON_BONUS_INTENTIONAL_FOUL_PARAMETERS,
        config=GameClockConfig(1, 180, 15),
        home=HOME,
        away=AWAY,
        matchups=MATCHUPS,
        frame=RandomFrame(1, RandomFrameAddress("foulout", 0, 0, 0, 0)),
        rules=GameRules(player_foul_limit=1),
    )
    assert sampled.result.end_reason is GameEndReason.NO_LEGAL_LINEUP
    assert sampled.result.possessions[-1].result.completed
    validate_game_result(
        sampled.result,
        GameClockConfig(1, 180, 15),
        possession_duration_options(NON_BONUS_INTENTIONAL_FOUL_PARAMETERS),
    )


@pytest.mark.parametrize(
    ("period", "clock", "period_fouls", "late_fouls", "expected"),
    (
        (4, 121, 3, 1, 0),
        (4, 120, 3, 1, 2),
        (4, 121, 4, 0, 2),
        (5, 300, 3, 0, 2),
    ),
)
def test_team_foul_penalty_handles_final_two_minutes_and_overtime(
    period: int,
    clock: int,
    period_fouls: int,
    late_fouls: int,
    expected: int,
) -> None:
    assert (
        non_shooting_foul_free_throws(
            GameRules(),
            period=period,
            regulation_periods=4,
            clock_seconds=clock,
            period_team_fouls_before=period_fouls,
            final_two_minute_team_fouls_before=late_fouls,
        )
        == expected
    )


def test_offensive_foul_is_canonical_and_not_an_ordinary_turnover() -> None:
    result = OffensiveFoulSegmentResult(IsolationPlan(1), Coverage.BASE, 1, 11)
    validate_action_segment_result(result, HOME.lineup, AWAY.lineup)
    assert segment_result_from_json(segment_result_to_json(result)) == result
    possession = PossessionResult((result,), PossessionEndReason.OFFENSIVE_FOUL)
    assert possession.completed
    attribution = attribute_segment(result)
    totals = {(delta.player_id, delta.stat): delta.amount for delta in attribution.player_deltas}
    assert totals == {(1, StatCode.TOV): 1, (1, StatCode.PF): 1}
    assert attribution.possession_delta == 1
    assert audit_rule_events((result,)).offensive_fouls == 1


def test_technical_free_throw_has_explicit_party_shooter_and_continuation() -> None:
    assert (
        select_technical_free_throw_shooter(HOME.profiles)
        == min(
            (
                profile
                for profile in HOME.profiles
                if profile.abilities.free_throw_shooting
                == max(item.abilities.free_throw_shooting for item in HOME.profiles)
            ),
            key=lambda profile: profile.player_id,
        ).player_id
    )
    result = TechnicalFoulSegmentResult(
        IsolationPlan(1),
        Coverage.BASE,
        TechnicalFoulType.PLAYER,
        FoulTeamSide.DEFENSE,
        11,
        1,
        (True,),
        True,
    )
    validate_action_segment_result(result, HOME.lineup, AWAY.lineup)
    assert offense_retains_ball(result)
    assert segment_result_from_json(segment_result_to_json(result)) == result
    attribution = attribute_segment(result)
    totals = {(delta.player_id, delta.stat): delta.amount for delta in attribution.player_deltas}
    assert totals == {
        (1, StatCode.PTS): 1,
        (1, StatCode.FTM): 1,
        (1, StatCode.FTA): 1,
        (11, StatCode.TF): 1,
    }
    assert attribution.score_delta == 1
    assert attribution.possession_delta == 0
    assert audit_rule_events((result,)).technical_fouls == 1

    legacy_shape = segment_result_to_dict(result)
    legacy_shape["schema_version"] = 4
    with pytest.raises(SerializationError, match="requires schema_version 5"):
        segment_result_from_dict(legacy_shape)


def test_offensive_team_technical_credits_only_the_opponent_free_throw() -> None:
    result = TechnicalFoulSegmentResult(
        IsolationPlan(1),
        Coverage.BASE,
        TechnicalFoulType.PLAYER,
        FoulTeamSide.OFFENSE,
        1,
        11,
        (True,),
        False,
    )
    validate_action_segment_result(result, HOME.lineup, AWAY.lineup)
    attribution = attribute_segment(result)
    assert attribution.score_delta == 0
    assert attribution.opponent_score_delta == 1
    assert attribution.possession_delta == 1
    stats = {delta.stat for delta in attribution.player_deltas}
    assert stats == {StatCode.PTS, StatCode.FTM, StatCode.FTA, StatCode.TF}
    assert not stats & {
        StatCode.FGA,
        StatCode.FGM,
        StatCode.OREB,
        StatCode.DREB,
        StatCode.REB,
    }

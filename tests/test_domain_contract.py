import itertools

import pytest

from courtsim.domain.contest import (
    BlockedAttempt,
    LiveAttempt,
    ShotContestContext,
    validate_contest_resolution,
    validate_shot_contest_context,
)
from courtsim.domain.enums import (
    ContestLevel,
    Coverage,
    CreationMode,
    FinisherRoute,
    GameEndReason,
    PlayFamily,
    PossessionEndReason,
    ReboundSide,
    ShotZone,
    TacticalAction,
    TerminalChannel,
    TurnoverKind,
)
from courtsim.domain.interaction import (
    FinisherCandidateProfile,
    FinisherSelection,
    InteractionState,
    select_candidate,
    validate_interaction_state,
)
from courtsim.domain.plans import (
    LEGAL_ROUTES_BY_PLAY,
    LEGAL_ZONES_BY_ROUTE,
    BallScreenPlan,
    IsolationPlan,
    OffBallActionPlan,
    creation_mode_for,
    last_passer_for,
    legal_coverages_for,
    tactical_action_for,
    validate_coverage,
)
from courtsim.domain.results import (
    BlockedShotSegmentResult,
    DefensiveRebound,
    MadeShotSegmentResult,
    MissedShotSegmentResult,
    NonShootingFoulSegmentResult,
    OffensiveRebound,
    ShootingFoulSegmentResult,
    StolenTurnover,
    TurnoverSegmentResult,
    offense_retains_ball,
    possession_end_reason,
    validate_action_segment_result,
)
from courtsim.domain.serialization import segment_result_from_json, segment_result_to_json
from courtsim.stats.attribution import StatCode, attribute_segment

OFFENSE = (1, 2, 3, 4, 5)
DEFENSE = (11, 12, 13, 14, 15)
BALL_SCREEN = BallScreenPlan(1, 5)
ISOLATION = IsolationPlan(1)
OFF_BALL = OffBallActionPlan(1, 3, 4)
OFF_BALL_NO_SCREEN = OffBallActionPlan(1, 3)


def candidate(route: FinisherRoute, finisher_id: int) -> FinisherCandidateProfile:
    return FinisherCandidateProfile(route, finisher_id, 0.5, 0.1, 0.2, 0.3, 11, 12)


def test_append_only_enum_ids_are_a_golden_contract() -> None:
    assert [(item.name, item.value) for item in PlayFamily] == [
        ("BALL_SCREEN", 0),
        ("ISOLATION", 1),
        ("OFF_BALL_ACTION", 2),
    ]
    assert [(item.name, item.value) for item in Coverage] == [
        ("BASE", 0),
        ("DROP", 1),
        ("SWITCH", 2),
        ("BLITZ", 3),
    ]
    assert [(item.name, item.value) for item in PossessionEndReason] == [
        ("MADE_SHOT", 0),
        ("TURNOVER", 1),
        ("DEFENSIVE_REBOUND", 2),
        ("SEGMENT_LIMIT", 3),
        ("FREE_THROW_SEQUENCE", 4),
        ("OFFENSIVE_FOUL", 5),
        ("TECHNICAL_FREE_THROW", 6),
    ]
    assert [(item.name, item.value) for item in GameEndReason] == [
        ("REGULATION", 0),
        ("POSSESSION_TRUNCATED", 1),
        ("OVERTIME", 2),
        ("OVERTIME_LIMIT", 3),
        ("NO_LEGAL_LINEUP", 4),
    ]
    assert [(item.name, item.value) for item in FinisherRoute] == [
        ("INITIATOR_SELF", 0),
        ("SCREENER_ROLL", 1),
        ("SCREENER_POP", 2),
        ("HELP_RELEASE", 3),
        ("DESIGNED_OFF_BALL_TARGET", 4),
        ("INITIATOR_BAILOUT", 5),
    ]
    assert [(item.name, item.value) for item in CreationMode] == [
        ("SELF_CREATED", 0),
        ("SCREEN_PARTNER_FEED", 1),
        ("SPOT_UP_FEED", 2),
        ("OFF_BALL_MOVEMENT_FEED", 3),
    ]
    assert [(item.name, item.value) for item in TacticalAction] == [
        ("BALL_SCREEN_KEEP", 0),
        ("BALL_SCREEN_ROLL", 1),
        ("BALL_SCREEN_POP", 2),
        ("BALL_SCREEN_KICKOUT", 3),
        ("ISOLATION_ATTACK", 4),
        ("ISOLATION_KICKOUT", 5),
        ("PINDOWN", 6),
        ("BACKDOOR_CUT", 7),
        ("OFF_BALL_BAILOUT", 8),
    ]


def test_tactical_vocabulary_is_derived_from_causal_plan_shape() -> None:
    assert (
        tactical_action_for(BALL_SCREEN, FinisherRoute.SCREENER_ROLL)
        is TacticalAction.BALL_SCREEN_ROLL
    )
    assert (
        tactical_action_for(ISOLATION, FinisherRoute.HELP_RELEASE)
        is TacticalAction.ISOLATION_KICKOUT
    )
    assert (
        tactical_action_for(OFF_BALL, FinisherRoute.DESIGNED_OFF_BALL_TARGET)
        is TacticalAction.PINDOWN
    )
    assert (
        tactical_action_for(OFF_BALL_NO_SCREEN, FinisherRoute.DESIGNED_OFF_BALL_TARGET)
        is TacticalAction.BACKDOOR_CUT
    )
    assert [(item.name, item.value) for item in ShotZone] == [
        ("RIM", 0),
        ("MIDRANGE", 1),
        ("THREE", 2),
    ]
    assert [(item.name, item.value) for item in TerminalChannel] == [
        ("SHOT_OPPORTUNITY", 0),
        ("TURNOVER", 1),
    ]
    assert [(item.name, item.value) for item in ReboundSide] == [
        ("OFFENSE", 0),
        ("DEFENSE", 1),
    ]
    assert [(item.name, item.value) for item in TurnoverKind] == [
        ("LOST_BALL_STEAL", 0),
        ("LOST_BALL_UNFORCED", 1),
        ("BAD_PASS_STEAL", 2),
        ("BAD_PASS_UNFORCED", 3),
        ("VIOLATION", 4),
    ]


def test_plan_shape_guards_participants() -> None:
    with pytest.raises(ValueError):
        BallScreenPlan(1, 1)
    with pytest.raises(ValueError):
        OffBallActionPlan(1, 2, 2)
    with pytest.raises(ValueError):
        IsolationPlan(-1)


def test_offball_switch_requires_a_screen_setter() -> None:
    assert Coverage.SWITCH in legal_coverages_for(OFF_BALL)
    assert legal_coverages_for(OFF_BALL_NO_SCREEN) == frozenset({Coverage.BASE})
    with pytest.raises(ValueError):
        validate_coverage(OFF_BALL_NO_SCREEN, Coverage.SWITCH)


@pytest.mark.parametrize("plan", [BALL_SCREEN, ISOLATION, OFF_BALL, OFF_BALL_NO_SCREEN])
def test_every_legal_coverage_route_zone_combination_validates(plan: object) -> None:
    assert isinstance(plan, (BallScreenPlan, IsolationPlan, OffBallActionPlan))
    for coverage, route in itertools.product(
        legal_coverages_for(plan), LEGAL_ROUTES_BY_PLAY[plan.family]
    ):
        if route is FinisherRoute.HELP_RELEASE:
            finisher_id = 2
        elif route is FinisherRoute.INITIATOR_SELF:
            finisher_id = 1
        elif route in {FinisherRoute.SCREENER_ROLL, FinisherRoute.SCREENER_POP}:
            finisher_id = 5
        elif route is FinisherRoute.DESIGNED_OFF_BALL_TARGET:
            finisher_id = 3
        else:
            finisher_id = 1
        for zone in LEGAL_ZONES_BY_ROUTE[route]:
            result = MadeShotSegmentResult(
                plan,
                coverage,
                FinisherSelection(route, finisher_id),
                zone,
                ContestLevel.NORMAL,
            )
            validate_action_segment_result(result, OFFENSE, DEFENSE)
            assert segment_result_from_json(segment_result_to_json(result)) == result


def test_interaction_is_keyed_by_route_and_finisher() -> None:
    state = InteractionState(
        0.2,
        0.4,
        (
            candidate(FinisherRoute.INITIATOR_SELF, 1),
            candidate(FinisherRoute.SCREENER_ROLL, 5),
            candidate(FinisherRoute.SCREENER_POP, 5),
            candidate(FinisherRoute.HELP_RELEASE, 2),
            candidate(FinisherRoute.HELP_RELEASE, 3),
        ),
    )
    validate_interaction_state(BALL_SCREEN, state, OFFENSE, DEFENSE)
    chosen = select_candidate(state, FinisherSelection(FinisherRoute.HELP_RELEASE, 3))
    assert chosen.finisher_id == 3


def test_interaction_rejects_missing_route_and_participant_as_help_release() -> None:
    missing = InteractionState(
        0.2,
        0.4,
        (
            candidate(FinisherRoute.INITIATOR_SELF, 1),
            candidate(FinisherRoute.SCREENER_ROLL, 5),
            candidate(FinisherRoute.HELP_RELEASE, 2),
        ),
    )
    with pytest.raises(ValueError):
        validate_interaction_state(BALL_SCREEN, missing, OFFENSE, DEFENSE)

    bad_help = InteractionState(
        0.2,
        0.4,
        (
            candidate(FinisherRoute.INITIATOR_SELF, 1),
            candidate(FinisherRoute.SCREENER_ROLL, 5),
            candidate(FinisherRoute.SCREENER_POP, 5),
            candidate(FinisherRoute.HELP_RELEASE, 5),
        ),
    )
    with pytest.raises(ValueError):
        validate_interaction_state(BALL_SCREEN, bad_help, OFFENSE, DEFENSE)


def test_block_candidates_exist_only_in_post_zone_context() -> None:
    selection = FinisherSelection(FinisherRoute.SCREENER_ROLL, 5)
    context = ShotContestContext(0.2, 0.3, 11, 12, (11, 12))
    validate_shot_contest_context(context, selection, ShotZone.RIM, OFFENSE, DEFENSE)
    validate_contest_resolution(context, BlockedAttempt(12))
    validate_contest_resolution(context, LiveAttempt(ContestLevel.HEAVY))
    with pytest.raises(ValueError):
        validate_contest_resolution(context, BlockedAttempt(13))
    with pytest.raises(ValueError):
        validate_shot_contest_context(context, selection, ShotZone.THREE, OFFENSE, DEFENSE)


def test_creation_and_passer_are_derived() -> None:
    made = MadeShotSegmentResult(
        BALL_SCREEN,
        Coverage.DROP,
        FinisherSelection(FinisherRoute.SCREENER_ROLL, 5),
        ShotZone.RIM,
        ContestLevel.NORMAL,
    )
    assert made.creation_mode is CreationMode.SCREEN_PARTNER_FEED
    assert made.last_passer_id == 1
    assert made.assist_eligible
    assert creation_mode_for(FinisherRoute.INITIATOR_SELF) is CreationMode.SELF_CREATED
    assert last_passer_for(BALL_SCREEN, FinisherRoute.INITIATOR_SELF) is None


def test_result_union_enforces_rebound_and_turnover_identity() -> None:
    miss = MissedShotSegmentResult(
        ISOLATION,
        Coverage.BASE,
        FinisherSelection(FinisherRoute.INITIATOR_SELF, 1),
        ShotZone.MIDRANGE,
        ContestLevel.HEAVY,
        OffensiveRebound(4),
    )
    block = BlockedShotSegmentResult(
        ISOLATION,
        Coverage.BLITZ,
        FinisherSelection(FinisherRoute.INITIATOR_SELF, 1),
        ShotZone.RIM,
        11,
        DefensiveRebound(12),
    )
    turnover = TurnoverSegmentResult(
        ISOLATION,
        Coverage.BLITZ,
        StolenTurnover(
            kind=TurnoverKind.LOST_BALL_STEAL,
            responsible_offender_id=1,
            stealer_id=11,
        ),
    )
    for result in (miss, block, turnover):
        validate_action_segment_result(result, OFFENSE, DEFENSE)

    invalid = TurnoverSegmentResult(
        ISOLATION,
        Coverage.BASE,
        StolenTurnover(
            kind=TurnoverKind.BAD_PASS_STEAL,
            responsible_offender_id=2,
            stealer_id=11,
        ),
    )
    with pytest.raises(ValueError):
        validate_action_segment_result(invalid, OFFENSE, DEFENSE)


def test_shooting_foul_contract_enforces_attempt_count_and_final_rebound() -> None:
    valid = ShootingFoulSegmentResult(
        ISOLATION,
        Coverage.BASE,
        FinisherSelection(FinisherRoute.INITIATOR_SELF, 1),
        ShotZone.RIM,
        ContestLevel.HEAVY,
        11,
        False,
        (True, False),
        OffensiveRebound(4),
    )
    validate_action_segment_result(valid, OFFENSE, DEFENSE)

    with pytest.raises(ValueError, match="free throw count"):
        ShootingFoulSegmentResult(
            ISOLATION,
            Coverage.BASE,
            FinisherSelection(FinisherRoute.INITIATOR_SELF, 1),
            ShotZone.THREE,
            ContestLevel.NORMAL,
            11,
            False,
            (True, False),
            OffensiveRebound(4),
        )
    with pytest.raises(ValueError, match="requires a rebound"):
        ShootingFoulSegmentResult(
            ISOLATION,
            Coverage.BASE,
            FinisherSelection(FinisherRoute.INITIATOR_SELF, 1),
            ShotZone.RIM,
            ContestLevel.NORMAL,
            11,
            False,
            (True, False),
            None,
        )


def test_non_shooting_foul_contract_models_retention_bonus_and_attribution() -> None:
    non_bonus = NonShootingFoulSegmentResult(
        ISOLATION,
        Coverage.BASE,
        1,
        11,
    )
    bonus_made = NonShootingFoulSegmentResult(
        ISOLATION,
        Coverage.BASE,
        1,
        11,
        (True, False),
        DefensiveRebound(12),
    )
    bonus_oreb = NonShootingFoulSegmentResult(
        ISOLATION,
        Coverage.BASE,
        1,
        11,
        (True, False),
        OffensiveRebound(4),
    )
    for result in (non_bonus, bonus_made, bonus_oreb):
        validate_action_segment_result(result, OFFENSE, DEFENSE)
        assert segment_result_from_json(segment_result_to_json(result)) == result

    assert offense_retains_ball(non_bonus)
    assert possession_end_reason(non_bonus) is None
    assert not offense_retains_ball(bonus_made)
    assert possession_end_reason(bonus_made) is PossessionEndReason.FREE_THROW_SEQUENCE
    assert offense_retains_ball(bonus_oreb)
    assert possession_end_reason(bonus_oreb) is None

    non_bonus_stats = attribute_segment(non_bonus)
    assert non_bonus_stats.possession_delta == 0
    assert non_bonus_stats.score_delta == 0
    assert non_bonus_stats.player_deltas == (non_bonus_stats.player_deltas[0],)
    assert non_bonus_stats.player_deltas[0].player_id == 11
    assert non_bonus_stats.player_deltas[0].stat is StatCode.PF

    bonus_stats = attribute_segment(bonus_made)
    totals = {(delta.player_id, delta.stat): delta.amount for delta in bonus_stats.player_deltas}
    assert bonus_stats.score_delta == 1
    assert bonus_stats.possession_delta == 1
    assert totals[(1, StatCode.FTA)] == 2
    assert totals[(1, StatCode.FTM)] == 1
    assert totals[(11, StatCode.PF)] == 1
    assert totals[(12, StatCode.DREB)] == 1


def test_non_shooting_foul_rejects_wrong_attempt_and_rebound_shapes() -> None:
    with pytest.raises(ValueError, match="zero or two"):
        NonShootingFoulSegmentResult(
            ISOLATION,
            Coverage.BASE,
            1,
            11,
            (True,),
        )
    with pytest.raises(ValueError, match="non-bonus"):
        NonShootingFoulSegmentResult(
            ISOLATION,
            Coverage.BASE,
            1,
            11,
            (),
            DefensiveRebound(12),
        )
    invalid_player = NonShootingFoulSegmentResult(
        ISOLATION,
        Coverage.BASE,
        2,
        11,
    )
    with pytest.raises(ValueError, match="plan ball handler"):
        validate_action_segment_result(invalid_player, OFFENSE, DEFENSE)

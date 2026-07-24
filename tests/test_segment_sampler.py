from dataclasses import dataclass, field
from typing import Self, TypeVar

import pytest

from courtsim.domain.contest import (
    BlockedAttempt,
    ContestResolution,
    LiveAttempt,
    ShotContestContext,
)
from courtsim.domain.enums import (
    ContestLevel,
    Coverage,
    FinisherRoute,
    ShotZone,
    TurnoverKind,
)
from courtsim.domain.interaction import (
    FinisherCandidateProfile,
    FinisherSelection,
    InteractionState,
)
from courtsim.domain.plans import IsolationPlan, Lineup, OffensivePlan, PlayerId
from courtsim.domain.results import (
    BlockedShotSegmentResult,
    DefensiveRebound,
    MadeShotSegmentResult,
    MissedShotSegmentResult,
    NonShootingFoulSegmentResult,
    OffensiveRebound,
    ReboundOutcome,
    ShootingFoulSegmentResult,
    StolenTurnover,
    TurnoverSegmentResult,
    offense_retains_ball,
)
from courtsim.model import (
    ShotOpportunity,
    TurnoverOpportunity,
    sample_action_segment,
)
from courtsim.model.hazards import PlayerHazard, ReboundHazards
from courtsim.model.segment_sampler import SegmentSample, TerminalOpportunity
from courtsim.probability import ProbabilityOption
from courtsim.randomness import RandomFrame, RandomFrameAddress, RandomSlot

OFFENSE: Lineup = (1, 2, 3, 4, 5)
DEFENSE: Lineup = (11, 12, 13, 14, 15)
PLAN = IsolationPlan(1)
INTERACTION = InteractionState(
    ball_pressure=0.2,
    pass_release=0.3,
    finisher_candidates=(
        FinisherCandidateProfile(FinisherRoute.INITIATOR_SELF, 1, 0.8, 0.2, 0.1, 0.5, 11, 12),
        FinisherCandidateProfile(FinisherRoute.HELP_RELEASE, 2, 0.2, 0.3, 0.2, 0.1, 12, 13),
    ),
)


T = TypeVar("T")


def one(option_id: str, value: T) -> tuple[ProbabilityOption[T], ...]:
    return (ProbabilityOption(option_id, value, 1.0),)


@dataclass(frozen=True)
class ScriptedPolicy:
    terminal: TerminalOpportunity
    contest: ContestResolution = field(default_factory=lambda: LiveAttempt(ContestLevel.NORMAL))
    made: bool = True
    rebound: ReboundOutcome = field(default_factory=lambda: DefensiveRebound(12))
    assisted: bool = False
    shooting_foul: bool = False
    non_shooting_foul: bool | None = None
    free_throws: tuple[bool, bool, bool] = (True, True, True)

    def prepare_segment(
        self,
        plan: OffensivePlan,
        coverage: Coverage,
        interaction: InteractionState,
        offense_lineup: Lineup,
        defense_lineup: Lineup,
    ) -> Self:
        return self

    def terminal_options(
        self,
        plan: OffensivePlan,
        coverage: Coverage,
        interaction: InteractionState,
    ) -> tuple[ProbabilityOption[TerminalOpportunity], ...]:
        return one("terminal", self.terminal)

    def non_shooting_foul_options(
        self,
        plan: OffensivePlan,
        coverage: Coverage,
        interaction: InteractionState,
    ) -> tuple[ProbabilityOption[bool], ...] | None:
        if self.non_shooting_foul is None:
            return None
        return one(
            ("non-shooting-foul" if self.non_shooting_foul else "no-non-shooting-foul"),
            self.non_shooting_foul,
        )

    def non_shooting_fouler_options(
        self,
        plan: OffensivePlan,
        interaction: InteractionState,
        defense_lineup: Lineup,
    ) -> tuple[ProbabilityOption[PlayerId], ...]:
        return one("non-shooting-fouler:11", 11)

    def stealer_options(
        self,
        kind: TurnoverKind,
        interaction: InteractionState,
        defense_lineup: Lineup,
    ) -> tuple[ProbabilityOption[PlayerId], ...]:
        return one("stealer:11", 11)

    def route_options(
        self,
        plan: OffensivePlan,
        coverage: Coverage,
        interaction: InteractionState,
    ) -> tuple[ProbabilityOption[FinisherRoute], ...]:
        return one("route:self", FinisherRoute.INITIATOR_SELF)

    def finisher_options(
        self,
        route: FinisherRoute,
        interaction: InteractionState,
    ) -> tuple[ProbabilityOption[PlayerId], ...]:
        return one("finisher:1", 1)

    def zone_options(
        self,
        plan: OffensivePlan,
        selection: FinisherSelection,
        interaction: InteractionState,
    ) -> tuple[ProbabilityOption[ShotZone], ...]:
        return one("zone:rim", ShotZone.RIM)

    def contest_context(
        self,
        plan: OffensivePlan,
        coverage: Coverage,
        selection: FinisherSelection,
        zone: ShotZone,
        interaction: InteractionState,
    ) -> ShotContestContext:
        return ShotContestContext(0.2, 0.1, 11, 12, (11,))

    def contest_options(
        self,
        context: ShotContestContext,
        zone: ShotZone,
    ) -> tuple[ProbabilityOption[ContestResolution], ...]:
        return one("contest", self.contest)

    def make_options(
        self,
        plan: OffensivePlan,
        selection: FinisherSelection,
        zone: ShotZone,
        live_attempt: LiveAttempt,
    ) -> tuple[ProbabilityOption[bool], ...]:
        return one("made" if self.made else "missed", self.made)

    def shooting_foul_options(
        self,
        context: ShotContestContext,
        selection: FinisherSelection,
        zone: ShotZone,
        live_attempt: LiveAttempt,
    ) -> tuple[ProbabilityOption[bool], ...]:
        return one(
            "shooting-foul" if self.shooting_foul else "no-foul",
            self.shooting_foul,
        )

    def fouler_options(
        self,
        context: ShotContestContext,
        defense_lineup: Lineup,
    ) -> tuple[ProbabilityOption[PlayerId], ...]:
        return one("fouler:11", 11)

    def free_throw_make_options(
        self,
        shooter_id: PlayerId,
        attempt_number: int,
    ) -> tuple[ProbabilityOption[bool], ...]:
        made = self.free_throws[attempt_number - 1]
        return one(f"free-throw:{attempt_number}:{made}", made)

    def assist_options(
        self,
        plan: OffensivePlan,
        selection: FinisherSelection,
    ) -> tuple[ProbabilityOption[bool], ...]:
        return one("assisted" if self.assisted else "unassisted", self.assisted)

    def assister_options(
        self,
        plan: OffensivePlan,
        selection: FinisherSelection,
        offense_lineup: Lineup,
    ) -> tuple[ProbabilityOption[PlayerId], ...]:
        return one("assister:2", 2)

    def rebound_hazards(
        self,
        plan: OffensivePlan,
        selection: FinisherSelection,
        zone: ShotZone,
        blocker_id: PlayerId | None,
        offense_lineup: Lineup,
        defense_lineup: Lineup,
    ) -> ReboundHazards:
        offense = tuple(
            PlayerHazard(
                player_id,
                1.0
                if isinstance(self.rebound, OffensiveRebound)
                and player_id == self.rebound.rebounder_id
                else 0.0,
            )
            for player_id in offense_lineup
        )
        defense = tuple(
            PlayerHazard(
                player_id,
                1.0
                if isinstance(self.rebound, DefensiveRebound)
                and player_id == self.rebound.rebounder_id
                else 0.0,
            )
            for player_id in defense_lineup
        )
        return ReboundHazards(offense, defense)


class InvalidRoutePolicy(ScriptedPolicy):
    def route_options(
        self,
        plan: OffensivePlan,
        coverage: Coverage,
        interaction: InteractionState,
    ) -> tuple[ProbabilityOption[FinisherRoute], ...]:
        return (
            ProbabilityOption("route:self", FinisherRoute.INITIATOR_SELF, 1.0),
            ProbabilityOption("route:illegal", FinisherRoute.SCREENER_ROLL, 0.0),
        )


def sample(
    policy: ScriptedPolicy,
    segment_index: int = 0,
    *,
    bonus_free_throws: bool = False,
) -> SegmentSample:
    return sample_action_segment(
        plan=PLAN,
        coverage=Coverage.BASE,
        interaction=INTERACTION,
        offense_lineup=OFFENSE,
        defense_lineup=DEFENSE,
        policy=policy,
        frame=RandomFrame(77, RandomFrameAddress("segment-fixture", 0, 0, 3, segment_index)),
        bonus_free_throws=bonus_free_throws,
    )


def test_shot_make_vertical_slice() -> None:
    sampled = sample(ScriptedPolicy(ShotOpportunity()))
    assert isinstance(sampled.result, MadeShotSegmentResult)
    assert [item.slot for item in sampled.node_results] == [
        RandomSlot.TERMINAL,
        RandomSlot.FINISHER_ROUTE,
        RandomSlot.FINISHER_PLAYER,
        RandomSlot.SHOT_ZONE,
        RandomSlot.CONTEST,
        RandomSlot.SHOOTING_FOUL,
        RandomSlot.SHOT_MAKE,
        RandomSlot.ASSIST_DECISION,
    ]


def test_non_shooting_foul_retains_ball_before_bonus_and_shoots_in_bonus() -> None:
    non_bonus = sample(
        ScriptedPolicy(
            ShotOpportunity(),
            non_shooting_foul=True,
        )
    )
    assert isinstance(non_bonus.result, NonShootingFoulSegmentResult)
    assert non_bonus.result.free_throws == ()
    assert offense_retains_ball(non_bonus.result)
    assert [item.slot for item in non_bonus.node_results] == [
        RandomSlot.NON_SHOOTING_FOUL,
        RandomSlot.NON_SHOOTING_FOULER,
    ]

    bonus = sample(
        ScriptedPolicy(
            ShotOpportunity(),
            rebound=DefensiveRebound(12),
            non_shooting_foul=True,
            free_throws=(True, False, True),
        ),
        bonus_free_throws=True,
    )
    assert isinstance(bonus.result, NonShootingFoulSegmentResult)
    assert bonus.result.free_throws == (True, False)
    assert bonus.result.rebound == DefensiveRebound(12)
    assert not offense_retains_ball(bonus.result)
    assert [item.slot for item in bonus.node_results] == [
        RandomSlot.NON_SHOOTING_FOUL,
        RandomSlot.NON_SHOOTING_FOULER,
        RandomSlot.FREE_THROW_1,
        RandomSlot.FREE_THROW_2,
        RandomSlot.REBOUND_SIDE,
        RandomSlot.REBOUNDER,
    ]


def test_missed_shooting_foul_samples_two_throws_and_last_miss_rebound() -> None:
    sampled = sample(
        ScriptedPolicy(
            ShotOpportunity(),
            made=False,
            rebound=OffensiveRebound(4),
            shooting_foul=True,
            free_throws=(True, False, True),
        )
    )
    assert isinstance(sampled.result, ShootingFoulSegmentResult)
    assert sampled.result.free_throws == (True, False)
    assert sampled.result.rebound == OffensiveRebound(4)
    assert offense_retains_ball(sampled.result)
    assert [item.slot for item in sampled.node_results][-7:] == [
        RandomSlot.SHOOTING_FOUL,
        RandomSlot.FOULER,
        RandomSlot.SHOT_MAKE,
        RandomSlot.FREE_THROW_1,
        RandomSlot.FREE_THROW_2,
        RandomSlot.REBOUND_SIDE,
        RandomSlot.REBOUNDER,
    ]


def test_and_one_samples_assist_and_one_free_throw() -> None:
    sampled = sample(
        ScriptedPolicy(
            ShotOpportunity(),
            made=True,
            assisted=True,
            shooting_foul=True,
            free_throws=(True, True, True),
        )
    )
    assert isinstance(sampled.result, ShootingFoulSegmentResult)
    assert sampled.result.field_goal_made
    assert sampled.result.assister_id == 2
    assert sampled.result.free_throws == (True,)
    assert sampled.result.rebound is None


def test_live_miss_requires_rebound_and_can_retain_possession() -> None:
    sampled = sample(
        ScriptedPolicy(
            ShotOpportunity(),
            LiveAttempt(ContestLevel.HEAVY),
            False,
            OffensiveRebound(4),
        )
    )
    assert isinstance(sampled.result, MissedShotSegmentResult)
    assert isinstance(sampled.result.rebound, OffensiveRebound)
    assert sampled.node_results[-2].slot is RandomSlot.REBOUND_SIDE
    assert sampled.node_results[-1].slot is RandomSlot.REBOUNDER


def test_block_bypasses_make_node_and_requires_rebound() -> None:
    sampled = sample(
        ScriptedPolicy(
            ShotOpportunity(),
            BlockedAttempt(11),
            rebound=DefensiveRebound(12),
        )
    )
    assert isinstance(sampled.result, BlockedShotSegmentResult)
    slots = [item.slot for item in sampled.node_results]
    assert RandomSlot.SHOT_MAKE not in slots
    assert slots[-2:] == [RandomSlot.REBOUND_SIDE, RandomSlot.REBOUNDER]


@pytest.mark.parametrize(
    "kind",
    [
        TurnoverKind.LOST_BALL_UNFORCED,
        TurnoverKind.BAD_PASS_UNFORCED,
        TurnoverKind.VIOLATION,
    ],
)
def test_non_steal_turnovers_do_not_consume_stealer_slot(kind: TurnoverKind) -> None:
    sampled = sample(ScriptedPolicy(TurnoverOpportunity(kind)))
    assert isinstance(sampled.result, TurnoverSegmentResult)
    assert [item.slot for item in sampled.node_results] == [RandomSlot.TERMINAL]


def test_stolen_turnover_assigns_defender_from_same_branch() -> None:
    sampled = sample(ScriptedPolicy(TurnoverOpportunity(TurnoverKind.LOST_BALL_STEAL)))
    assert isinstance(sampled.result, TurnoverSegmentResult)
    assert isinstance(sampled.result.outcome, StolenTurnover)
    assert sampled.result.outcome.stealer_id == 11
    assert sampled.node_results[-1].slot is RandomSlot.STEALER


def test_same_frame_replays_and_new_segment_changes_random_frame() -> None:
    policy = ScriptedPolicy(ShotOpportunity())
    left = sample(policy)
    right = sample(policy)
    later = sample(policy, segment_index=1)
    assert left == right
    assert left.node_results[0].uniform != later.node_results[0].uniform


def test_policy_cannot_hide_illegal_candidates_behind_zero_weight() -> None:
    with pytest.raises(ValueError):
        sample(InvalidRoutePolicy(ShotOpportunity()))

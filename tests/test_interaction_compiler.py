from dataclasses import replace
from pathlib import Path

import pytest

from courtsim.domain.enums import Coverage, FinisherRoute
from courtsim.domain.interaction import InteractionState, validate_interaction_state
from courtsim.domain.plans import (
    BallScreenPlan,
    IsolationPlan,
    Lineup,
    OffBallActionPlan,
)
from courtsim.domain.player import PlayerProfile, SizeClass
from courtsim.domain.player_serialization import player_profile_from_json
from courtsim.model import (
    DefensiveMatchups,
    Matchup,
    PlayerAwareCompiledPolicy,
    compile_interaction_state,
    sample_action_segment,
)
from courtsim.model.interaction_compiler import ProfileLineup
from courtsim.parameters import load_model_parameters
from courtsim.randomness import RandomFrame, RandomFrameAddress

ROOT = Path(__file__).parents[1]
PARAMETERS = load_model_parameters(
    ROOT / "data" / "model_schema_demo_v1_3.json",
    ROOT / "data" / "model_parameters_demo_0.4.0.json",
)
OFFENSE: Lineup = (1, 2, 3, 4, 5)
DEFENSE: Lineup = (11, 12, 13, 14, 15)
MATCHUPS = DefensiveMatchups(
    (
        Matchup(1, 11),
        Matchup(2, 12),
        Matchup(3, 13),
        Matchup(4, 14),
        Matchup(5, 15),
    )
)


def template() -> PlayerProfile:
    path = ROOT / "examples" / "player_profile_v1.json"
    return player_profile_from_json(path.read_text(encoding="utf-8"))


def player(player_id: int) -> PlayerProfile:
    return replace(
        template(),
        player_id=player_id,
        name=f"Player {player_id}",
        nominal_role_tags=(),
    )


def offense_profiles(first: PlayerProfile | None = None) -> ProfileLineup:
    return (first or player(1), player(2), player(3), player(4), player(5))


def defense_profiles(first: PlayerProfile | None = None) -> ProfileLineup:
    return (first or player(11), player(12), player(13), player(14), player(15))


def compile_state(
    plan: BallScreenPlan | IsolationPlan | OffBallActionPlan,
    coverage: Coverage,
    offense: ProfileLineup | None = None,
    defense: ProfileLineup | None = None,
) -> InteractionState:
    return compile_interaction_state(
        parameters=PARAMETERS,
        plan=plan,
        coverage=coverage,
        offense_lineup=OFFENSE,
        defense_lineup=DEFENSE,
        offense_profiles=offense or offense_profiles(),
        defense_profiles=defense or defense_profiles(),
        matchups=MATCHUPS,
    )


@pytest.mark.parametrize(
    ("plan", "coverage"),
    [
        (BallScreenPlan(1, 5), Coverage.BASE),
        (BallScreenPlan(1, 5), Coverage.DROP),
        (BallScreenPlan(1, 5), Coverage.SWITCH),
        (BallScreenPlan(1, 5), Coverage.BLITZ),
        (IsolationPlan(1), Coverage.BASE),
        (IsolationPlan(1), Coverage.BLITZ),
        (OffBallActionPlan(1, 3), Coverage.BASE),
        (OffBallActionPlan(1, 3, 4), Coverage.SWITCH),
    ],
)
def test_every_legal_interaction_shape_validates(
    plan: BallScreenPlan | IsolationPlan | OffBallActionPlan,
    coverage: Coverage,
) -> None:
    state = compile_state(plan, coverage)
    validate_interaction_state(plan, state, OFFENSE, DEFENSE)


def test_help_release_creates_one_candidate_per_weakside_player() -> None:
    ball_screen = compile_state(BallScreenPlan(1, 5), Coverage.BLITZ)
    help_ids = {
        item.finisher_id
        for item in ball_screen.finisher_candidates
        if item.route is FinisherRoute.HELP_RELEASE
    }
    assert help_ids == {2, 3, 4}

    isolation = compile_state(IsolationPlan(1), Coverage.BLITZ)
    isolation_help = {
        item.finisher_id
        for item in isolation.finisher_candidates
        if item.route is FinisherRoute.HELP_RELEASE
    }
    assert isolation_help == {2, 3, 4, 5}


def test_blitz_applies_exact_play_coverage_pressure_delta() -> None:
    base = compile_state(BallScreenPlan(1, 5), Coverage.BASE)
    blitz = compile_state(BallScreenPlan(1, 5), Coverage.BLITZ)
    assert blitz.ball_pressure - base.ball_pressure == pytest.approx(0.35)
    assert blitz.pass_release - base.pass_release == pytest.approx(0.30)


def test_creator_and_primary_defender_have_opposite_directions() -> None:
    low_creator = replace(
        player(1),
        abilities=replace(player(1).abilities, perimeter_creation=25),
    )
    high_creator = replace(
        player(1),
        abilities=replace(player(1).abilities, perimeter_creation=90),
    )
    low_state = compile_state(IsolationPlan(1), Coverage.BASE, offense_profiles(low_creator))
    high_state = compile_state(IsolationPlan(1), Coverage.BASE, offense_profiles(high_creator))
    low_self = next(
        item for item in low_state.finisher_candidates if item.route is FinisherRoute.INITIATOR_SELF
    )
    high_self = next(
        item
        for item in high_state.finisher_candidates
        if item.route is FinisherRoute.INITIATOR_SELF
    )
    assert high_self.availability > low_self.availability
    assert high_self.rim_access > low_self.rim_access

    weak_defender = replace(
        player(11),
        abilities=replace(player(11).abilities, point_of_attack_defense=25),
    )
    elite_defender = replace(
        player(11),
        abilities=replace(player(11).abilities, point_of_attack_defense=90),
    )
    weak_state = compile_state(
        IsolationPlan(1), Coverage.BASE, defense=defense_profiles(weak_defender)
    )
    elite_state = compile_state(
        IsolationPlan(1), Coverage.BASE, defense=defense_profiles(elite_defender)
    )
    weak_self = next(
        item
        for item in weak_state.finisher_candidates
        if item.route is FinisherRoute.INITIATOR_SELF
    )
    elite_self = next(
        item
        for item in elite_state.finisher_candidates
        if item.route is FinisherRoute.INITIATOR_SELF
    )
    assert elite_state.ball_pressure > weak_state.ball_pressure
    assert elite_self.availability < weak_self.availability
    assert elite_self.primary_contest > weak_self.primary_contest


def test_switch_changes_assignment_and_size_context_not_raw_success_rate() -> None:
    large_handler = replace(player(1), size_class=SizeClass.LARGE)
    small_screener_defender = replace(player(15), size_class=SizeClass.SMALL)
    defense: ProfileLineup = (
        player(11),
        player(12),
        player(13),
        player(14),
        small_screener_defender,
    )
    state = compile_state(
        BallScreenPlan(1, 5),
        Coverage.SWITCH,
        offense_profiles(large_handler),
        defense,
    )
    self_candidate = next(
        item for item in state.finisher_candidates if item.route is FinisherRoute.INITIATOR_SELF
    )
    assert self_candidate.primary_defender_id == 15


def test_nominal_tags_never_change_interaction() -> None:
    plain = player(1)
    tagged = replace(plain, nominal_role_tags=("ELITE_SCORER",))
    assert compile_state(IsolationPlan(1), Coverage.BASE, offense_profiles(plain)) == compile_state(
        IsolationPlan(1), Coverage.BASE, offense_profiles(tagged)
    )


def test_matchups_must_be_a_complete_bijection() -> None:
    invalid = DefensiveMatchups(
        (
            Matchup(1, 11),
            Matchup(2, 11),
            Matchup(3, 13),
            Matchup(4, 14),
            Matchup(5, 15),
        )
    )
    with pytest.raises(ValueError):
        invalid.as_map(OFFENSE, DEFENSE)


def test_compiled_interaction_runs_through_player_aware_segment() -> None:
    offense = offense_profiles()
    defense = defense_profiles()
    interaction = compile_state(BallScreenPlan(1, 5), Coverage.BLITZ, offense, defense)
    policy = PlayerAwareCompiledPolicy(PARAMETERS, offense, defense)
    frame = RandomFrame(
        20260723,
        RandomFrameAddress("interaction-e2e", 0, 0, 0, 0),
    )

    def run() -> object:
        return sample_action_segment(
            plan=BallScreenPlan(1, 5),
            coverage=Coverage.BLITZ,
            interaction=interaction,
            offense_lineup=OFFENSE,
            defense_lineup=DEFENSE,
            policy=policy,
            frame=frame,
        )

    assert run() == run()

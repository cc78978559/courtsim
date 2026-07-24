from dataclasses import replace
from pathlib import Path

from courtsim.domain.contest import LiveAttempt, ShotContestContext
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
from courtsim.domain.plans import IsolationPlan, Lineup
from courtsim.domain.player import PlayerProfile, ShotZoneMix
from courtsim.domain.player_serialization import player_profile_from_json
from courtsim.model import PlayerAwareCompiledPolicy, sample_action_segment
from courtsim.model.player_aware_policy import ProfileLineup
from courtsim.parameters import load_model_parameters
from courtsim.randomness import RandomFrame, RandomFrameAddress

ROOT = Path(__file__).parents[1]
PARAMETERS = load_model_parameters(
    ROOT / "data" / "model_schema_demo_v1_3.json",
    ROOT / "data" / "model_parameters_demo_0.4.0.json",
)
ASSIST_PARAMETERS = load_model_parameters(
    ROOT / "data" / "model_schema_demo_v1_4.json",
    ROOT / "data" / "model_parameters_demo_0.6.0.json",
)
FOUL_PARAMETERS = load_model_parameters(
    ROOT / "data" / "model_schema_demo_v1_5.json",
    ROOT / "data" / "model_parameters_demo_0.7.0.json",
)
COMMON_FOUL_PARAMETERS = load_model_parameters(
    ROOT / "data" / "model_schema_demo_v1_6.json",
    ROOT / "data" / "model_parameters_demo_0.8.0.json",
)
ASSIST_OCCURRENCE_PARAMETERS = load_model_parameters(
    ROOT / "data" / "model_schema_demo_v1_7.json",
    ROOT / "data" / "model_parameters_demo_0.9.0.json",
)
OFFENSE: Lineup = (1, 2, 3, 4, 5)
DEFENSE: Lineup = (11, 12, 13, 14, 15)
PLAN = IsolationPlan(1)
INTERACTION = InteractionState(
    0.2,
    0.3,
    (
        FinisherCandidateProfile(FinisherRoute.INITIATOR_SELF, 1, 0.8, 0.2, 0.1, 0.4, 11, 12),
        FinisherCandidateProfile(FinisherRoute.HELP_RELEASE, 2, 0.2, 0.3, 0.2, 0.1, 12, 13),
    ),
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


def prepared(
    offense: ProfileLineup | None = None,
    defense: ProfileLineup | None = None,
) -> PlayerAwareCompiledPolicy:
    policy = PlayerAwareCompiledPolicy(
        PARAMETERS,
        offense or offense_profiles(),
        defense or defense_profiles(),
    )
    result = policy.prepare_segment(PLAN, Coverage.BASE, INTERACTION, OFFENSE, DEFENSE)
    assert isinstance(result, PlayerAwareCompiledPolicy)
    assert result.steal_hazards is not None
    return result


def test_ball_security_reduces_lost_ball_competing_risk() -> None:
    low = replace(
        player(1),
        abilities=replace(player(1).abilities, ball_security=20),
    )
    high = replace(
        player(1),
        abilities=replace(player(1).abilities, ball_security=80),
    )

    def lost_share(handler: PlayerProfile) -> float:
        policy = prepared(offense_profiles(handler))
        options = policy.terminal_options(PLAN, Coverage.BASE, INTERACTION)
        total = sum(option.weight for option in options)
        return sum(option.weight for option in options if "LOST_BALL" in option.id) / total

    assert lost_share(high) < lost_share(low)


def test_zone_tendency_changes_zone_but_not_make_skill() -> None:
    rim_pref = replace(
        player(1),
        tendencies=replace(
            player(1).tendencies,
            shot_zone_mix=ShotZoneMix(95, 20, 10),
        ),
    )
    three_pref = replace(
        player(1),
        tendencies=replace(
            player(1).tendencies,
            shot_zone_mix=ShotZoneMix(10, 20, 95),
        ),
    )
    selection = FinisherSelection(FinisherRoute.INITIATOR_SELF, 1)

    def three_share(finisher: PlayerProfile) -> float:
        policy = prepared(offense_profiles(finisher))
        options = policy.zone_options(PLAN, selection, INTERACTION)
        total = sum(option.weight for option in options)
        return next(option.weight / total for option in options if option.value is ShotZone.THREE)

    assert three_share(three_pref) > three_share(rim_pref)


def test_three_point_skill_changes_make_but_not_zone_options() -> None:
    low = replace(
        player(1),
        abilities=replace(player(1).abilities, three_point_shooting=35),
    )
    high = replace(
        player(1),
        abilities=replace(player(1).abilities, three_point_shooting=90),
    )
    selection = FinisherSelection(FinisherRoute.INITIATOR_SELF, 1)

    def make_probability(finisher: PlayerProfile) -> float:
        policy = prepared(offense_profiles(finisher))
        options = policy.make_options(
            PLAN,
            selection,
            ShotZone.THREE,
            LiveAttempt(ContestLevel.NORMAL),
        )
        return next(option.weight for option in options if option.value)

    assert make_probability(high) > make_probability(low)
    low_zones = prepared(offense_profiles(low)).zone_options(PLAN, selection, INTERACTION)
    high_zones = prepared(offense_profiles(high)).zone_options(PLAN, selection, INTERACTION)
    assert low_zones == high_zones


def test_rim_protection_and_chase_raise_block_share() -> None:
    low = replace(
        player(11),
        abilities=replace(player(11).abilities, rim_protection=25),
        tendencies=replace(player(11).tendencies, block_chase=20),
    )
    high = replace(
        player(11),
        abilities=replace(player(11).abilities, rim_protection=90),
        tendencies=replace(player(11).tendencies, block_chase=90),
    )
    context = ShotContestContext(0.2, 0.1, 11, None, (11,))

    def block_share(defender: PlayerProfile) -> float:
        options = prepared(defense=defense_profiles(defender)).contest_options(
            context, ShotZone.RIM
        )
        total = sum(option.weight for option in options)
        return (
            sum(option.weight for option in options if option.id.startswith("contest:BLOCK"))
            / total
        )

    assert block_share(high) > block_share(low)


def test_steal_hazard_is_shared_with_stealer_assignment() -> None:
    elite = replace(
        player(11),
        abilities=replace(player(11).abilities, steal_skill=95),
        tendencies=replace(player(11).tendencies, steal_gamble=85),
    )
    policy = prepared(defense=defense_profiles(elite))
    assert policy.steal_hazards is not None
    options = policy.stealer_options(
        TurnoverKind.LOST_BALL_STEAL,
        INTERACTION,
        DEFENSE,
    )
    weight_by_id = {option.value: option.weight for option in options}
    assert weight_by_id[11] > weight_by_id[12]
    assert tuple(
        (entry.player_id, entry.weight) for entry in policy.steal_hazards.entries
    ) == tuple((option.value, option.weight) for option in options)


def test_rebound_hazards_drive_both_side_and_player() -> None:
    elite = replace(
        player(4),
        abilities=replace(player(4).abilities, offensive_rebounding=95),
        tendencies=replace(player(4).tendencies, offensive_rebound_commitment=90),
    )
    policy = prepared((player(1), player(2), player(3), elite, player(5)))
    hazards = policy.rebound_hazards(
        PLAN,
        FinisherSelection(FinisherRoute.INITIATOR_SELF, 1),
        ShotZone.RIM,
        None,
        OFFENSE,
        DEFENSE,
    )
    offense_weights = {entry.player_id: entry.weight for entry in hazards.offense}
    assert offense_weights[4] == max(offense_weights.values())
    assert (
        sum(offense_weights.values())
        / (sum(offense_weights.values()) + sum(entry.weight for entry in hazards.defense))
        > 0.25
    )


def test_assister_hazard_rewards_playmaking_and_excludes_finisher() -> None:
    weak = replace(
        player(2),
        abilities=replace(
            player(2).abilities,
            playmaking=20,
            offensive_decision=20,
        ),
    )
    elite = replace(
        player(3),
        abilities=replace(
            player(3).abilities,
            playmaking=95,
            offensive_decision=95,
        ),
    )
    policy = PlayerAwareCompiledPolicy(
        ASSIST_PARAMETERS,
        (player(1), weak, elite, player(4), player(5)),
        defense_profiles(),
    )
    selection = FinisherSelection(FinisherRoute.INITIATOR_SELF, 1)
    assist_weights = {
        option.value: option.weight for option in policy.assister_options(PLAN, selection, OFFENSE)
    }
    assert 1 not in assist_weights
    assert assist_weights[3] > assist_weights[2]
    assist_probability = {
        option.value: option.weight for option in policy.assist_options(PLAN, selection)
    }
    assert assist_probability == {False: 0.6, True: 0.4}


def test_fixed_passer_skill_changes_assist_occurrence_only_in_v17() -> None:
    low = replace(
        player(1),
        abilities=replace(
            player(1).abilities,
            playmaking=20,
            offensive_decision=20,
        ),
    )
    high = replace(
        player(1),
        abilities=replace(
            player(1).abilities,
            playmaking=95,
            offensive_decision=95,
        ),
    )
    selection = FinisherSelection(FinisherRoute.HELP_RELEASE, 2)

    def probability(passer: PlayerProfile) -> float:
        policy = PlayerAwareCompiledPolicy(
            ASSIST_OCCURRENCE_PARAMETERS,
            offense_profiles(passer),
            defense_profiles(),
        )
        return next(
            option.weight for option in policy.assist_options(PLAN, selection) if option.value
        )

    assert probability(high) > probability(low)

    self_created = FinisherSelection(FinisherRoute.INITIATOR_SELF, 1)
    low_policy = PlayerAwareCompiledPolicy(
        ASSIST_OCCURRENCE_PARAMETERS,
        offense_profiles(low),
        defense_profiles(),
    )
    high_policy = PlayerAwareCompiledPolicy(
        ASSIST_OCCURRENCE_PARAMETERS,
        offense_profiles(high),
        defense_profiles(),
    )
    assert low_policy.assist_options(PLAN, self_created) == high_policy.assist_options(
        PLAN,
        self_created,
    )


def test_foul_drawing_and_contact_seek_raise_shooting_foul_probability() -> None:
    low = replace(
        player(1),
        abilities=replace(player(1).abilities, foul_drawing=20),
        tendencies=replace(player(1).tendencies, contact_seek=20),
    )
    high = replace(
        player(1),
        abilities=replace(player(1).abilities, foul_drawing=95),
        tendencies=replace(player(1).tendencies, contact_seek=95),
    )
    context = ShotContestContext(0.2, 0.1, 11, 12, (11, 12))
    selection = FinisherSelection(FinisherRoute.INITIATOR_SELF, 1)

    def foul_probability(shooter: PlayerProfile) -> float:
        policy = PlayerAwareCompiledPolicy(
            FOUL_PARAMETERS,
            offense_profiles(shooter),
            defense_profiles(),
        )
        return next(
            option.weight
            for option in policy.shooting_foul_options(
                context,
                selection,
                ShotZone.RIM,
                LiveAttempt(ContestLevel.NORMAL),
            )
            if option.value
        )

    assert foul_probability(high) > foul_probability(low)


def test_common_foul_uses_handler_traits_and_related_defender_hazard() -> None:
    low = replace(
        player(1),
        abilities=replace(player(1).abilities, foul_drawing=20),
        tendencies=replace(player(1).tendencies, contact_seek=20),
    )
    high = replace(
        player(1),
        abilities=replace(player(1).abilities, foul_drawing=95),
        tendencies=replace(player(1).tendencies, contact_seek=95),
    )

    def foul_probability(handler: PlayerProfile) -> float:
        policy = PlayerAwareCompiledPolicy(
            COMMON_FOUL_PARAMETERS,
            offense_profiles(handler),
            defense_profiles(),
        )
        options = policy.non_shooting_foul_options(
            PLAN,
            Coverage.BASE,
            INTERACTION,
        )
        assert options is not None
        return next(option.weight for option in options if option.value)

    assert foul_probability(high) > foul_probability(low)

    disciplined = replace(
        player(11),
        abilities=replace(player(11).abilities, foul_discipline=95),
    )
    reckless = replace(
        player(12),
        abilities=replace(player(12).abilities, foul_discipline=20),
    )
    policy = PlayerAwareCompiledPolicy(
        COMMON_FOUL_PARAMETERS,
        offense_profiles(),
        (disciplined, reckless, player(13), player(14), player(15)),
    )
    weights = {
        option.value: option.weight
        for option in policy.non_shooting_fouler_options(
            PLAN,
            INTERACTION,
            DEFENSE,
        )
    }
    assert set(weights) == {11, 12}
    assert weights[11] < weights[12]


def test_free_throw_skill_raises_make_probability() -> None:
    low = replace(
        player(1),
        abilities=replace(player(1).abilities, free_throw_shooting=20),
    )
    high = replace(
        player(1),
        abilities=replace(player(1).abilities, free_throw_shooting=95),
    )

    def make_probability(shooter: PlayerProfile) -> float:
        policy = PlayerAwareCompiledPolicy(
            FOUL_PARAMETERS,
            offense_profiles(shooter),
            defense_profiles(),
        )
        return next(
            option.weight for option in policy.free_throw_make_options(1, 1) if option.value
        )

    assert make_probability(high) > make_probability(low)


def test_player_aware_segment_is_reproducible() -> None:
    policy = PlayerAwareCompiledPolicy(PARAMETERS, offense_profiles(), defense_profiles())
    frame = RandomFrame(88, RandomFrameAddress("player-aware", 0, 0, 0, 0))

    def run() -> object:
        return sample_action_segment(
            plan=PLAN,
            coverage=Coverage.BASE,
            interaction=INTERACTION,
            offense_lineup=OFFENSE,
            defense_lineup=DEFENSE,
            policy=policy,
            frame=frame,
        )

    assert run() == run()


def test_prepared_policy_reuses_immutable_compiled_context() -> None:
    policy = PlayerAwareCompiledPolicy(PARAMETERS, offense_profiles(), defense_profiles())
    result = policy.prepare_segment(PLAN, Coverage.BASE, INTERACTION, OFFENSE, DEFENSE)
    assert isinstance(result, PlayerAwareCompiledPolicy)
    assert result._base is policy._base
    assert result._offense is policy._offense
    assert result._defense is policy._defense

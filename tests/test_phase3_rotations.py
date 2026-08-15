import json
from dataclasses import replace

import pytest
from test_game_runtime import AWAY, HOME, MATCHUPS, PARAMETERS, player

from courtsim.domain.contest import LiveAttempt
from courtsim.domain.enums import (
    ContestLevel,
    Coverage,
    FinisherRoute,
    GameEndReason,
    ShotZone,
    SubstitutionReason,
)
from courtsim.domain.game import GameClockConfig, PlayerPlayingTime, validate_game_result
from courtsim.domain.game_serialization import (
    game_result_from_dict,
    game_result_from_json,
    game_result_to_dict,
    game_result_to_json,
)
from courtsim.domain.interaction import FinisherSelection
from courtsim.domain.plans import IsolationPlan
from courtsim.domain.player import PlayerProfile
from courtsim.model import (
    FatigueConfig,
    GameSample,
    GameTeam,
    PlayerAwareCompiledPolicy,
    RotationPlan,
    RotationStint,
    compile_interaction_state,
    sample_game,
    sample_game_batch,
)
from courtsim.randomness import RandomFrame, RandomFrameAddress
from courtsim.rotations import audit_rotations, fatigue_adjusted_profile, update_fatigue


def rotating_teams() -> tuple[GameTeam, GameTeam]:
    home = replace(
        HOME,
        bench_profiles=(player(6), player(7)),
        rotation_plan=RotationPlan(
            (
                RotationStint(1, 20, (1, 6, 3, 4, 5)),
                RotationStint(1, 10, HOME.lineup),
            )
        ),
    )
    away = replace(AWAY, bench_profiles=(player(16),))
    return home, away


def rotation_game(*, fatigue_config: FatigueConfig | None = None) -> GameSample:
    home, away = rotating_teams()
    return sample_game(
        parameters=PARAMETERS,
        config=GameClockConfig(1, 30, 10),
        home=home,
        away=away,
        matchups=MATCHUPS,
        frame=RandomFrame(41, RandomFrameAddress("rotation", 0, 0, 0, 0)),
        fatigue_config=fatigue_config,
    )


def test_rotation_contract_rejects_bad_order_and_unknown_players() -> None:
    with pytest.raises(ValueError, match="ordered"):
        RotationPlan(
            (
                RotationStint(1, 10, HOME.lineup),
                RotationStint(1, 20, HOME.lineup),
            )
        )
    with pytest.raises(ValueError, match="outside the roster"):
        replace(
            HOME,
            rotation_plan=RotationPlan((RotationStint(1, 20, (1, 2, 3, 4, 99)),)),
        )
    with pytest.raises(ValueError, match="disjoint"):
        sample_game(
            parameters=PARAMETERS,
            config=GameClockConfig(1, 10, 10),
            home=replace(HOME, bench_profiles=(player(11),)),
            away=AWAY,
            matchups=MATCHUPS,
            frame=RandomFrame(1, RandomFrameAddress("bad-roster", 0, 0, 0, 0)),
        )


def test_scheduled_rotation_is_canonical_and_clock_addressed() -> None:
    sampled = rotation_game()
    records = sampled.result.possessions
    assert records[0].offense_lineup == HOME.lineup
    assert records[1].defense_lineup == (1, 6, 3, 4, 5)
    assert records[2].offense_lineup == HOME.lineup
    assert [
        (
            item.team_id,
            item.period,
            item.clock_seconds,
            item.reason,
            item.outgoing_player_id,
            item.incoming_player_id,
        )
        for item in sampled.result.substitutions
    ] == [
        ("home", 1, 20, SubstitutionReason.ROTATION, 2, 6),
        ("home", 1, 10, SubstitutionReason.ROTATION, 6, 2),
    ]
    tampered = replace(
        sampled.result,
        substitutions=(
            replace(sampled.result.substitutions[0], incoming_player_id=99),
            *sampled.result.substitutions[1:],
        ),
    )
    with pytest.raises(ValueError, match="game roster"):
        validate_game_result(tampered, GameClockConfig(1, 30, 10))


def test_playing_time_derives_only_from_possession_lineups() -> None:
    sampled = rotation_game()
    times = {(item.team_id, item.player_id): item.seconds for item in sampled.result.playing_time}
    assert times[("home", 2)] == 20
    assert times[("home", 6)] == 10
    assert times[("home", 1)] == 30
    assert sum(value for (team, _), value in times.items() if team == "home") == 5 * 30
    validate_game_result(sampled.result, GameClockConfig(1, 30, 10))

    tampered = replace(
        sampled.result,
        playing_time=tuple(
            PlayerPlayingTime(item.team_id, item.player_id, item.seconds - 1)
            if item.team_id == "home" and item.player_id == 1
            else item
            for item in sampled.result.playing_time
        ),
    )
    with pytest.raises(ValueError, match="playing time"):
        validate_game_result(tampered, GameClockConfig(1, 30, 10))


def test_game_schema_v4_round_trips_and_v1_remains_readable() -> None:
    result = rotation_game().result
    assert game_result_from_json(game_result_to_json(result), GameClockConfig(1, 30, 10)) == result
    raw = game_result_to_dict(result)
    raw["schema_version"] = 1
    raw.pop("substitutions")
    raw.pop("playing_time")
    raw.pop("final_fatigue")
    raw.pop("rotation_version")
    raw.pop("fatigue_version")
    raw.pop("player_shot_zones")
    raw.pop("possessions_omitted")
    raw.pop("home_possessions")
    raw.pop("away_possessions")
    raw_possessions = raw["possessions"]
    assert isinstance(raw_possessions, list)
    for possession in raw_possessions:
        assert isinstance(possession, dict)
        for key in (
            "offense_lineup",
            "defense_lineup",
            "offense_fatigue",
            "defense_fatigue",
        ):
            possession.pop(key)
    legacy = game_result_from_dict(json.loads(json.dumps(raw)), GameClockConfig(1, 30, 10))
    assert legacy.substitutions == ()
    assert legacy.playing_time == ()
    assert all(item.offense_lineup is None for item in legacy.possessions)
    assert legacy.rotation_version is None
    assert legacy.fatigue_version is None


def test_fatigue_load_recovery_and_bounds_are_deterministic() -> None:
    config = FatigueConfig(
        active_load_per_second=5,
        bench_recovery_per_second=3,
        maximum_fatigue=100,
    )
    state = {player_id: 20 for player_id in range(1, 7)}
    updated = update_fatigue(
        state,
        active_lineup=HOME.lineup,
        roster_order=(1, 2, 3, 4, 5, 6),
        elapsed_seconds=10,
        config=config,
    )
    assert updated == {1: 70, 2: 70, 3: 70, 4: 70, 5: 70, 6: 0}
    assert (
        update_fatigue(
            updated,
            active_lineup=HOME.lineup,
            roster_order=(1, 2, 3, 4, 5, 6),
            elapsed_seconds=10,
            config=config,
        )[1]
        == 100
    )


def test_zero_fatigue_preserves_the_v02_event_stream() -> None:
    baseline = rotation_game()
    zero = rotation_game(
        fatigue_config=FatigueConfig(
            active_load_per_second=0,
            bench_recovery_per_second=0,
        )
    )
    assert tuple(item.result for item in zero.result.possessions) == tuple(
        item.result for item in baseline.result.possessions
    )
    assert (zero.result.home_score, zero.result.away_score, zero.result.player_stats) == (
        baseline.result.home_score,
        baseline.result.away_score,
        baseline.result.player_stats,
    )
    assert all(item.fatigue == 0 for item in zero.result.final_fatigue)


def test_high_workload_penalizes_only_explicit_abilities() -> None:
    config = FatigueConfig(maximum_ability_penalty=12)
    profile = HOME.profiles[0]
    adjusted = fatigue_adjusted_profile(profile, config.maximum_fatigue, config)
    assert adjusted.abilities.three_point_shooting == max(
        0,
        profile.abilities.three_point_shooting - 12,
    )
    assert adjusted.abilities.perimeter_creation == max(
        0,
        profile.abilities.perimeter_creation - 12,
    )
    assert adjusted.abilities.post_creation == profile.abilities.post_creation
    assert adjusted.tendencies == profile.tendencies


def test_high_fatigue_lowers_three_point_execution_counterfactually() -> None:
    config = FatigueConfig(maximum_ability_penalty=30)
    plan = IsolationPlan(1)
    selection = FinisherSelection(FinisherRoute.INITIATOR_SELF, 1)

    def make_weight(profile: PlayerProfile) -> float:
        active_profiles = (profile, *HOME.profiles[1:])
        interaction = compile_interaction_state(
            parameters=PARAMETERS,
            plan=plan,
            coverage=Coverage.BASE,
            offense_lineup=HOME.lineup,
            defense_lineup=AWAY.lineup,
            offense_profiles=active_profiles,
            defense_profiles=AWAY.profiles,
            matchups=MATCHUPS.home_offense,
        )
        policy = PlayerAwareCompiledPolicy(
            PARAMETERS,
            active_profiles,
            AWAY.profiles,
        ).prepare_segment(
            plan,
            Coverage.BASE,
            interaction,
            HOME.lineup,
            AWAY.lineup,
        )
        assert isinstance(policy, PlayerAwareCompiledPolicy)
        return next(
            option.weight
            for option in policy.make_options(
                plan,
                selection,
                ShotZone.THREE,
                LiveAttempt(ContestLevel.NORMAL),
            )
            if option.value
        )

    rested = HOME.profiles[0]
    fatigued = fatigue_adjusted_profile(rested, config.maximum_fatigue, config)
    assert make_weight(fatigued) < make_weight(rested)


def test_runtime_fatigue_snapshots_are_replayable_and_bounded() -> None:
    config = FatigueConfig(
        active_load_per_second=4,
        bench_recovery_per_second=2,
        maximum_fatigue=1000,
    )
    sampled = rotation_game(fatigue_config=config)
    assert sampled.result.end_reason is GameEndReason.REGULATION
    assert sampled.result.possessions[0].offense_fatigue
    assert sampled.result.rotation_version == "rotation-v1"
    assert sampled.result.fatigue_version == "fatigue-v1"
    assert all(0 <= item.fatigue <= config.maximum_fatigue for item in sampled.result.final_fatigue)
    assert (
        game_result_from_json(
            game_result_to_json(sampled.result),
            GameClockConfig(1, 30, 10),
        )
        == sampled.result
    )
    audit = audit_rotations(sampled.result)
    assert audit.scheduled_substitutions == 2
    assert audit.players_used == 11
    assert audit.total_player_seconds == 10 * 30
    assert audit.maximum_final_fatigue > 0


def test_rotation_and_fatigue_batch_is_index_deterministic() -> None:
    home, away = rotating_teams()
    arguments = {
        "parameters": PARAMETERS,
        "config": GameClockConfig(1, 30, 10),
        "home": home,
        "away": away,
        "matchups": MATCHUPS,
        "frame": RandomFrame(52, RandomFrameAddress("rotation-batch", 0, 0, 0, 0)),
        "games": 2,
        "fatigue_config": FatigueConfig(),
    }
    first = sample_game_batch(**arguments)  # type: ignore[arg-type]
    second = sample_game_batch(**arguments)  # type: ignore[arg-type]
    assert first == second
    assert all(game.result.playing_time for game in first.games)
    assert all(game.result.final_fatigue for game in first.games)

"""Deterministic two-team regulation game runtime."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from math import exp
from typing import Any, cast

from courtsim.domain.enums import GameEndReason, LateGameDefenseMode, LateGameOffenseMode
from courtsim.domain.game import (
    GameClockConfig,
    GamePossessionRecord,
    GameResult,
    validate_game_result,
)
from courtsim.domain.plans import Lineup
from courtsim.domain.player import PlayerProfile
from courtsim.domain.results import offense_retains_ball
from courtsim.model.action_setup import TeamDefenseStrategy, TeamOffenseStrategy
from courtsim.model.interaction_compiler import (
    DefensiveMatchups,
    Matchup,
    ProfileLineup,
)
from courtsim.model.late_game_strategy import (
    LateGameStrategyConfig,
    late_game_strategy_config,
    resolve_late_game_strategy,
)
from courtsim.model.possession_runtime import PossessionSample, sample_possession
from courtsim.model.trace_mode import TraceMode
from courtsim.parameters import ModelParameters
from courtsim.player_features import scalar_tendency_bias
from courtsim.probability import ProbabilityOption, sample_probability_value
from courtsim.randomness import RandomFrame, RandomSlot
from courtsim.rules import GameRules, ineligible_players, replace_ineligible_players
from courtsim.stats.attribution import PlayerStatDelta, StatCode, attribute_possession


@dataclass(frozen=True, slots=True)
class TeamTempoStrategy:
    tempo: int = 50

    def __post_init__(self) -> None:
        if (
            not isinstance(self.tempo, int)
            or isinstance(self.tempo, bool)
            or not 0 <= self.tempo <= 100
        ):
            raise ValueError("tempo must be an integer from 0 through 100")


@dataclass(frozen=True, slots=True)
class GameTeam:
    team_id: str
    lineup: Lineup
    profiles: ProfileLineup
    offense_strategy: TeamOffenseStrategy = field(default_factory=TeamOffenseStrategy)
    defense_strategy: TeamDefenseStrategy = field(default_factory=TeamDefenseStrategy)
    tempo_strategy: TeamTempoStrategy = field(default_factory=TeamTempoStrategy)
    bench_profiles: tuple[PlayerProfile, ...] = ()
    substitution_order: tuple[int, ...] = ()

    def __post_init__(self) -> None:
        if not self.team_id.strip():
            raise ValueError("team_id must not be blank")
        if {profile.player_id for profile in self.profiles} != set(self.lineup):
            raise ValueError("team profiles must match its lineup")
        roster_ids = tuple(profile.player_id for profile in self.profiles + self.bench_profiles)
        if len(roster_ids) != len(set(roster_ids)):
            raise ValueError("team roster player ids must be unique")
        if self.substitution_order and (
            len(self.substitution_order) != len(set(self.substitution_order))
            or set(self.substitution_order) != set(roster_ids)
        ):
            raise ValueError("substitution_order must cover the complete roster exactly once")

    @property
    def roster_order(self) -> tuple[int, ...]:
        return self.substitution_order or tuple(
            profile.player_id for profile in self.profiles + self.bench_profiles
        )

    def with_lineup(self, lineup: Lineup) -> GameTeam:
        roster = {profile.player_id: profile for profile in self.profiles + self.bench_profiles}
        active = cast(ProfileLineup, tuple(roster[player_id] for player_id in lineup))
        bench = tuple(
            roster[player_id] for player_id in self.roster_order if player_id not in lineup
        )
        return replace(
            self,
            lineup=lineup,
            profiles=active,
            bench_profiles=bench,
            substitution_order=self.roster_order,
        )


@dataclass(frozen=True, slots=True)
class GameMatchups:
    home_offense: DefensiveMatchups
    away_offense: DefensiveMatchups


@dataclass(frozen=True, slots=True)
class GameSample:
    result: GameResult
    possession_samples: tuple[PossessionSample, ...]


def _bonus_foul_threshold(parameters: ModelParameters) -> int | None:
    rules = cast(Mapping[str, Any], parameters.payload["rules"])
    raw = rules.get("bonus_foul_threshold")
    if raw is None:
        return None
    if not isinstance(raw, int) or isinstance(raw, bool) or raw < 1:
        raise ValueError("bonus_foul_threshold must be a positive integer")
    return raw


def possession_duration_options(parameters: ModelParameters) -> tuple[int, ...] | None:
    if parameters.schema.schema_version not in {
        "demo-v1.8",
        "demo-v1.9",
        "demo-v1.10",
        "demo-v1.11",
        "demo-v1.12",
    }:
        return None
    nodes = cast(Mapping[str, Any], parameters.payload["nodes"])
    node = cast(Mapping[str, Any], nodes["possession_duration"])
    durations = cast(Mapping[str, Any], node["durations_seconds"])
    values = {cast(int, value) for value in durations.values()}
    strategy = late_game_strategy_config(parameters)
    if strategy is not None and strategy.intentional_foul_formal_enabled:
        values.add(strategy.intentional_foul_clock_seconds)
        if strategy.intentional_foul_non_bonus_enabled:
            values.update(
                strategy.intentional_foul_clock_seconds + duration
                for duration in tuple(values)
                if duration != strategy.intentional_foul_clock_seconds
            )
    return tuple(sorted(values))


def effective_tempo_rating(
    parameters: ModelParameters,
    strategy: TeamTempoStrategy,
    *,
    period: int,
    clock_seconds: int,
    regulation_periods: int,
    offense_score: int,
    defense_score: int,
    late_game_config: LateGameStrategyConfig | None = None,
) -> int:
    tempo = strategy.tempo
    if parameters.schema.schema_version not in {
        "demo-v1.9",
        "demo-v1.10",
        "demo-v1.11",
        "demo-v1.12",
    }:
        return tempo
    nodes = cast(Mapping[str, Any], parameters.payload["nodes"])
    node = cast(Mapping[str, Any], nodes["possession_duration"])
    late_game = cast(Mapping[str, Any], node["late_game_adjustments"])
    strategy_config = (
        late_game_config if late_game_config is not None else late_game_strategy_config(parameters)
    )
    if strategy_config is not None:
        state = resolve_late_game_strategy(
            strategy_config,
            period=period,
            clock_seconds=clock_seconds,
            regulation_periods=regulation_periods,
            offense_score=offense_score,
            defense_score=defense_score,
        )
        if state.offense_mode is LateGameOffenseMode.TWO_FOR_ONE:
            tempo += strategy_config.two_for_one_tempo_delta
        elif state.offense_mode is LateGameOffenseMode.COMEBACK:
            tempo += cast(int, late_game["trailing_tempo_delta"])
        elif state.offense_mode is LateGameOffenseMode.PROTECT_LEAD:
            tempo += cast(int, late_game["leading_tempo_delta"])
    elif period == regulation_periods and clock_seconds <= cast(int, late_game["window_seconds"]):
        margin = offense_score - defense_score
        threshold = cast(int, late_game["margin_threshold"])
        if margin <= -threshold:
            tempo += cast(int, late_game["trailing_tempo_delta"])
        elif margin >= threshold:
            tempo += cast(int, late_game["leading_tempo_delta"])
    return max(0, min(100, tempo))


def possession_duration_weights(
    parameters: ModelParameters,
    strategy: TeamTempoStrategy,
    *,
    period: int,
    clock_seconds: int,
    regulation_periods: int,
    offense_score: int,
    defense_score: int,
    late_game_config: LateGameStrategyConfig | None = None,
) -> tuple[ProbabilityOption[int], ...]:
    nodes = cast(Mapping[str, Any], parameters.payload["nodes"])
    node = cast(Mapping[str, Any], nodes["possession_duration"])
    durations = cast(Mapping[str, Any], node["durations_seconds"])
    bases = cast(Mapping[str, Any], node["base_probabilities"])
    coefficient = float(node["tempo_coefficient"])
    effective_tempo = effective_tempo_rating(
        parameters,
        strategy,
        period=period,
        clock_seconds=clock_seconds,
        regulation_periods=regulation_periods,
        offense_score=offense_score,
        defense_score=defense_score,
        late_game_config=late_game_config,
    )
    tempo_bias = coefficient * scalar_tendency_bias(effective_tempo)
    return tuple(
        ProbabilityOption(
            class_name,
            cast(int, durations[class_name]),
            float(bases[class_name])
            * exp(
                tempo_bias
                * (1.0 if class_name == "SHORT" else -1.0 if class_name == "LONG" else 0.0)
            ),
        )
        for class_name in ("SHORT", "STANDARD", "LONG")
    )


def _sample_possession_duration(
    parameters: ModelParameters,
    team: GameTeam,
    frame: RandomFrame,
    fixed_seconds: int,
    *,
    period: int,
    clock_seconds: int,
    regulation_periods: int,
    offense_score: int,
    defense_score: int,
    late_game_config: LateGameStrategyConfig | None,
) -> int:
    if parameters.schema.schema_version not in {
        "demo-v1.8",
        "demo-v1.9",
        "demo-v1.10",
        "demo-v1.11",
        "demo-v1.12",
    }:
        return fixed_seconds
    return sample_probability_value(
        frame,
        RandomSlot.POSSESSION_DURATION,
        possession_duration_weights(
            parameters,
            team.tempo_strategy,
            period=period,
            clock_seconds=clock_seconds,
            regulation_periods=regulation_periods,
            offense_score=offense_score,
            defense_score=defense_score,
            late_game_config=late_game_config,
        ),
    )


def sample_game(
    *,
    parameters: ModelParameters,
    config: GameClockConfig,
    home: GameTeam,
    away: GameTeam,
    matchups: GameMatchups,
    frame: RandomFrame,
    max_segments_per_possession: int | None = None,
    trace_mode: TraceMode = TraceMode.FULL,
    rules: GameRules | None = None,
) -> GameSample:
    if home.team_id == away.team_id:
        raise ValueError("home and away team ids must be distinct")
    if set(home.lineup) & set(away.lineup):
        raise ValueError("home and away player ids must be disjoint")

    score = {home.team_id: 0, away.team_id: 0}
    starting_home_lineup = home.lineup
    starting_away_lineup = away.lineup
    stat_totals: dict[tuple[int, StatCode], int] = {}
    records: list[GamePossessionRecord] = []
    samples: list[PossessionSample] = []
    offense, defense = home, away
    period = 1
    clock = config.period_seconds
    possession_index = 0
    end_reason = GameEndReason.REGULATION
    team_fouls = {home.team_id: 0, away.team_id: 0}
    final_two_minute_fouls = {home.team_id: 0, away.team_id: 0}
    player_fouls = {player_id: 0 for player_id in home.roster_order + away.roster_order}
    bonus_foul_threshold = _bonus_foul_threshold(parameters)
    game_strategy_config = late_game_strategy_config(parameters)

    last_scheduled_period = config.regulation_periods + (
        config.max_overtimes if config.overtime_enabled else 0
    )
    while period <= last_scheduled_period:
        possession_frame = RandomFrame(
            frame.master_seed,
            replace(
                frame.address,
                possession_index=frame.address.possession_index + possession_index,
                segment_index=0,
            ),
        )
        home_on_offense = offense.team_id == home.team_id
        original_matchups = matchups.home_offense if home_on_offense else matchups.away_offense
        original_offense = starting_home_lineup if home_on_offense else starting_away_lineup
        original_defense = starting_away_lineup if home_on_offense else starting_home_lineup
        directional_matchups = (
            original_matchups
            if offense.lineup == original_offense and defense.lineup == original_defense
            else DefensiveMatchups(
                cast(
                    tuple[Matchup, Matchup, Matchup, Matchup, Matchup],
                    tuple(
                        Matchup(offender_id, defender_id)
                        for offender_id, defender_id in zip(
                            offense.lineup,
                            defense.lineup,
                            strict=True,
                        )
                    ),
                )
            )
        )
        strategy_state = (
            resolve_late_game_strategy(
                game_strategy_config,
                period=period,
                clock_seconds=clock,
                regulation_periods=config.regulation_periods,
                offense_score=score[offense.team_id],
                defense_score=score[defense.team_id],
            )
            if game_strategy_config is not None
            else None
        )
        possession_bonus_threshold = bonus_foul_threshold
        if rules is not None:
            possession_bonus_threshold = (
                rules.overtime_bonus_threshold
                if period > config.regulation_periods
                else rules.regulation_bonus_threshold
            )
            if clock <= rules.final_two_minute_seconds:
                fouls_needed = max(
                    1,
                    rules.final_two_minute_threshold - final_two_minute_fouls[defense.team_id],
                )
                possession_bonus_threshold = min(
                    possession_bonus_threshold,
                    team_fouls[defense.team_id] + fouls_needed,
                )
        intentional_foul = (
            game_strategy_config is not None
            and game_strategy_config.intentional_foul_formal_enabled
            and strategy_state is not None
            and strategy_state.defense_mode is LateGameDefenseMode.INTENTIONAL_FOUL
            and (
                game_strategy_config.intentional_foul_non_bonus_enabled
                or (
                    possession_bonus_threshold is not None
                    and team_fouls[defense.team_id] + 1 >= possession_bonus_threshold
                )
            )
        )
        sampled = sample_possession(
            parameters=parameters,
            offense_lineup=offense.lineup,
            defense_lineup=defense.lineup,
            offense_profiles=offense.profiles,
            defense_profiles=defense.profiles,
            matchups=directional_matchups,
            frame=possession_frame,
            offense_strategy=offense.offense_strategy,
            defense_strategy=defense.defense_strategy,
            max_segments=max_segments_per_possession,
            defense_team_fouls=team_fouls[defense.team_id],
            bonus_foul_threshold=possession_bonus_threshold,
            force_intentional_foul=intentional_foul,
            trace_mode=trace_mode,
        )
        team_fouls[defense.team_id] += sampled.defensive_fouls_committed
        if rules is not None and clock <= rules.final_two_minute_seconds:
            final_two_minute_fouls[defense.team_id] += sampled.defensive_fouls_committed
        normal_possession_seconds = _sample_possession_duration(
            parameters,
            offense,
            possession_frame,
            config.possession_seconds,
            period=period,
            clock_seconds=clock,
            regulation_periods=config.regulation_periods,
            offense_score=score[offense.team_id],
            defense_score=score[defense.team_id],
            late_game_config=game_strategy_config,
        )
        if sampled.intentional_foul_committed and game_strategy_config is not None:
            possession_seconds = game_strategy_config.intentional_foul_clock_seconds
            if offense_retains_ball(sampled.result.segments[0]):
                possession_seconds += normal_possession_seconds
        else:
            possession_seconds = normal_possession_seconds
        clock_end = max(0, clock - possession_seconds)
        records.append(
            GamePossessionRecord(
                possession_index,
                period,
                clock,
                clock_end,
                offense.team_id,
                defense.team_id,
                sampled.result,
            )
        )
        if trace_mode is TraceMode.FULL:
            samples.append(sampled)
        attribution = attribute_possession(
            sampled.result,
            offense.lineup,
            defense.lineup,
        )
        score[offense.team_id] += attribution.score_delta
        score[defense.team_id] += attribution.opponent_score_delta
        for delta in attribution.player_deltas:
            key = (delta.player_id, delta.stat)
            stat_totals[key] = stat_totals.get(key, 0) + delta.amount
            if delta.stat is StatCode.PF:
                player_fouls[delta.player_id] = player_fouls.get(delta.player_id, 0) + delta.amount
        if not sampled.result.completed:
            end_reason = GameEndReason.POSSESSION_TRUNCATED
            break

        if rules is not None:
            ineligible = ineligible_players(player_fouls, rules)
            home_lineup = replace_ineligible_players(
                active_lineup=home.lineup,
                roster_order=home.roster_order,
                ineligible=ineligible,
            )
            away_lineup = replace_ineligible_players(
                active_lineup=away.lineup,
                roster_order=away.roster_order,
                ineligible=ineligible,
            )
            if home_lineup is None or away_lineup is None:
                end_reason = GameEndReason.NO_LEGAL_LINEUP
                break
            home = home.with_lineup(home_lineup)
            away = away.with_lineup(away_lineup)

        possession_index += 1
        next_offense_id = defense.team_id
        offense = home if home.team_id == next_offense_id else away
        defense = away if offense is home else home
        clock = clock_end
        if clock == 0:
            if period >= config.regulation_periods:
                if score[home.team_id] != score[away.team_id]:
                    end_reason = (
                        GameEndReason.REGULATION
                        if period == config.regulation_periods
                        else GameEndReason.OVERTIME
                    )
                    break
                if not config.overtime_enabled:
                    break
                if period == last_scheduled_period:
                    end_reason = GameEndReason.OVERTIME_LIMIT
                    break
            period += 1
            clock = config.seconds_for_period(period)
            team_fouls = {home.team_id: 0, away.team_id: 0}
            final_two_minute_fouls = {home.team_id: 0, away.team_id: 0}

    player_stats = tuple(
        PlayerStatDelta(player_id, stat, amount)
        for (player_id, stat), amount in sorted(
            stat_totals.items(), key=lambda item: (item[0][0], int(item[0][1]))
        )
    )
    result = GameResult(
        home.team_id,
        away.team_id,
        tuple(records),
        score[home.team_id],
        score[away.team_id],
        player_stats,
        end_reason,
    )
    validate_game_result(result, config, possession_duration_options(parameters))
    return GameSample(result, tuple(samples))

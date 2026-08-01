"""Event-sourced aggregate metrics for calibration baselines."""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from typing import TypeVar

from courtsim.domain.enums import (
    Coverage,
    CreationMode,
    FinisherRoute,
    LateGameDefenseMode,
    LateGameOffenseMode,
    PlayFamily,
    ShotZone,
    TacticalAction,
)
from courtsim.domain.game import GameResult
from courtsim.domain.plans import creation_mode_for, tactical_action_for
from courtsim.domain.results import (
    BlockedShotSegmentResult,
    MadeShotSegmentResult,
    MissedShotSegmentResult,
    NonShootingFoulSegmentResult,
    OffensiveFoulSegmentResult,
    OffensiveRebound,
    ShootingFoulSegmentResult,
    TechnicalFoulSegmentResult,
    TurnoverSegmentResult,
    offense_retains_ball,
)
from courtsim.model.late_game_strategy import (
    LateGameStrategyConfig,
    resolve_late_game_strategy,
)

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class ShareMetric:
    key: str
    count: int
    share: float


@dataclass(frozen=True, slots=True)
class PlayerUsageShare:
    team_id: str
    player_id: int
    usage_events: int
    share: float


@dataclass(frozen=True, slots=True)
class PlayerFoulShare:
    team_id: str
    player_id: int
    foul_events: int
    share: float
    fouls_per_100_defensive_possessions: float


@dataclass(frozen=True, slots=True)
class TeamDistributionMetrics:
    team_id: str
    possessions: int
    mean_team_possessions: float
    points_per_100_possessions: float
    field_goal_percentage: float
    three_point_percentage: float
    turnover_rate: float
    assist_per_field_goal: float
    block_rate: float
    steal_rate: float
    shot_zone_shares: tuple[ShareMetric, ...]
    route_shares: tuple[ShareMetric, ...] = ()
    creation_mode_shares: tuple[ShareMetric, ...] = ()
    tactical_action_shares: tuple[ShareMetric, ...] = ()


@dataclass(frozen=True, slots=True)
class DistributionAudit:
    games: int
    completed_games: int
    aborted_games: int
    completed_possessions: int
    mean_team_score: float
    team_score_stddev: float
    mean_team_possessions: float
    points_per_100_possessions: float
    field_goal_percentage: float
    three_point_percentage: float
    turnover_rate: float
    offensive_rebound_rate: float
    assist_per_field_goal: float
    block_rate: float
    steal_rate: float
    shot_zone_shares: tuple[ShareMetric, ...]
    play_family_shares: tuple[ShareMetric, ...]
    coverage_shares: tuple[ShareMetric, ...]
    player_usage_shares: tuple[PlayerUsageShare, ...]
    free_throw_percentage: float = 0.0
    free_throw_attempt_rate: float = 0.0
    shooting_foul_rate: float = 0.0
    free_throw_points_per_100_possessions: float = 0.0
    field_goal_attempts_per_100_possessions: float = 0.0
    non_shooting_foul_rate: float = 0.0
    bonus_non_shooting_foul_rate: float = 0.0
    defensive_foul_rate: float = 0.0
    player_foul_shares: tuple[PlayerFoulShare, ...] = ()
    team_metrics: tuple[TeamDistributionMetrics, ...] = ()
    late_game_trailing_possessions: int = 0
    late_game_neutral_possessions: int = 0
    late_game_leading_possessions: int = 0
    late_game_trailing_mean_observed_seconds: float = 0.0
    late_game_neutral_mean_observed_seconds: float = 0.0
    late_game_leading_mean_observed_seconds: float = 0.0
    two_for_one_possessions: int = 0
    two_for_one_mean_observed_seconds: float = 0.0
    intentional_foul_opportunities: int = 0
    intentional_fouls_committed: int = 0
    intentional_foul_continuations: int = 0
    intentional_foul_mean_observed_seconds: float = 0.0
    route_shares: tuple[ShareMetric, ...] = ()
    creation_mode_shares: tuple[ShareMetric, ...] = ()
    tactical_action_shares: tuple[ShareMetric, ...] = ()


def _ratio(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def _shares(counts: dict[T, int], ordered: tuple[T, ...]) -> tuple[ShareMetric, ...]:
    total = sum(counts.values())
    return tuple(
        ShareMetric(
            getattr(key, "name", str(key)),
            counts.get(key, 0),
            _ratio(counts.get(key, 0), total),
        )
        for key in ordered
    )


def audit_game_results(
    results: tuple[GameResult, ...],
    late_game_config: LateGameStrategyConfig | None = None,
) -> DistributionAudit:
    if not results:
        raise ValueError("distribution audit requires at least one game")
    completed = tuple(result for result in results if result.completed)
    if not completed:
        raise ValueError("distribution audit requires at least one completed game")

    scores: list[int] = []
    completed_possessions = 0
    field_goal_attempts = 0
    field_goals_made = 0
    three_attempts = 0
    three_made = 0
    turnovers = 0
    steals = 0
    offensive_rebounds = 0
    defensive_rebounds = 0
    assists = 0
    blocks = 0
    free_throws_attempted = 0
    free_throws_made = 0
    shooting_fouls = 0
    non_shooting_fouls = 0
    bonus_non_shooting_fouls = 0
    zone_counts: dict[ShotZone, int] = {}
    play_counts: dict[PlayFamily, int] = {}
    coverage_counts: dict[Coverage, int] = {}
    route_counts: dict[FinisherRoute, int] = {}
    creation_mode_counts: dict[CreationMode, int] = {}
    tactical_action_counts: dict[TacticalAction, int] = {}
    usage_counts: dict[tuple[str, int], int] = {}
    team_usage_totals: dict[str, int] = {}
    foul_counts: dict[tuple[str, int], int] = {}
    team_foul_totals: dict[str, int] = {}
    team_defensive_possessions: dict[str, int] = {}
    team_points: dict[str, int] = {}
    team_possessions: dict[str, int] = {}
    team_field_goal_attempts: dict[str, int] = {}
    team_field_goals_made: dict[str, int] = {}
    team_three_attempts: dict[str, int] = {}
    team_three_made: dict[str, int] = {}
    team_turnovers: dict[str, int] = {}
    team_assists: dict[str, int] = {}
    team_blocks: dict[str, int] = {}
    team_steals: dict[str, int] = {}
    team_zone_counts: dict[str, dict[ShotZone, int]] = {}
    team_route_counts: dict[str, dict[FinisherRoute, int]] = {}
    team_creation_mode_counts: dict[str, dict[CreationMode, int]] = {}
    team_tactical_action_counts: dict[str, dict[TacticalAction, int]] = {}
    late_game_duration_counts = {"trailing": 0, "neutral": 0, "leading": 0}
    late_game_duration_totals = {"trailing": 0, "neutral": 0, "leading": 0}
    two_for_one_possessions = 0
    two_for_one_duration_total = 0
    intentional_foul_opportunities = 0
    intentional_fouls_committed = 0
    intentional_foul_continuations = 0
    intentional_foul_duration_total = 0

    for game in completed:
        scores.extend((game.home_score, game.away_score))
        team_points[game.home_team_id] = team_points.get(game.home_team_id, 0) + game.home_score
        team_points[game.away_team_id] = team_points.get(game.away_team_id, 0) + game.away_score
        completed_possessions += len(game.possessions)
        live_score = {game.home_team_id: 0, game.away_team_id: 0}
        final_period = max(possession.period for possession in game.possessions)
        for possession in game.possessions:
            offense_team = possession.offense_team_id
            defense_team = possession.defense_team_id
            if late_game_config is not None:
                strategy_state = resolve_late_game_strategy(
                    late_game_config,
                    period=possession.period,
                    clock_seconds=possession.clock_start_seconds,
                    regulation_periods=final_period,
                    offense_score=live_score[offense_team],
                    defense_score=live_score[defense_team],
                )
                if (
                    strategy_state.offense_mode is LateGameOffenseMode.TWO_FOR_ONE
                    and possession.clock_end_seconds > 0
                ):
                    two_for_one_possessions += 1
                    two_for_one_duration_total += (
                        possession.clock_start_seconds - possession.clock_end_seconds
                    )
                if strategy_state.defense_mode is LateGameDefenseMode.INTENTIONAL_FOUL:
                    intentional_foul_opportunities += 1
                    first_segment = possession.result.segments[0]
                    if late_game_config.intentional_foul_formal_enabled and isinstance(
                        first_segment, NonShootingFoulSegmentResult
                    ):
                        intentional_fouls_committed += 1
                        if offense_retains_ball(first_segment):
                            intentional_foul_continuations += 1
                        intentional_foul_duration_total += (
                            possession.clock_start_seconds - possession.clock_end_seconds
                        )
            if (
                possession.period == final_period
                and possession.clock_start_seconds <= 120
                and possession.clock_end_seconds > 0
            ):
                margin = live_score[offense_team] - live_score[defense_team]
                context = "trailing" if margin <= -6 else "leading" if margin >= 6 else "neutral"
                late_game_duration_counts[context] += 1
                late_game_duration_totals[context] += (
                    possession.clock_start_seconds - possession.clock_end_seconds
                )
            team_possessions[offense_team] = team_possessions.get(offense_team, 0) + 1
            team_defensive_possessions[defense_team] = (
                team_defensive_possessions.get(defense_team, 0) + 1
            )
            for segment in possession.result.segments:
                play_counts[segment.plan.family] = play_counts.get(segment.plan.family, 0) + 1
                coverage_counts[segment.coverage] = coverage_counts.get(segment.coverage, 0) + 1
                if isinstance(
                    segment,
                    (
                        MadeShotSegmentResult,
                        MissedShotSegmentResult,
                        BlockedShotSegmentResult,
                        ShootingFoulSegmentResult,
                    ),
                ):
                    route = segment.selection.route
                    creation_mode = creation_mode_for(route)
                    tactical_action = tactical_action_for(segment.plan, route)
                    route_counts[route] = route_counts.get(route, 0) + 1
                    creation_mode_counts[creation_mode] = (
                        creation_mode_counts.get(creation_mode, 0) + 1
                    )
                    tactical_action_counts[tactical_action] = (
                        tactical_action_counts.get(tactical_action, 0) + 1
                    )
                    team_routes = team_route_counts.setdefault(offense_team, {})
                    team_routes[route] = team_routes.get(route, 0) + 1
                    team_creation = team_creation_mode_counts.setdefault(offense_team, {})
                    team_creation[creation_mode] = team_creation.get(creation_mode, 0) + 1
                    team_actions = team_tactical_action_counts.setdefault(offense_team, {})
                    team_actions[tactical_action] = team_actions.get(tactical_action, 0) + 1
                if isinstance(segment, TurnoverSegmentResult):
                    turnovers += 1
                    team_turnovers[offense_team] = team_turnovers.get(offense_team, 0) + 1
                    usage_player = segment.outcome.responsible_offender_id
                    if hasattr(segment.outcome, "stealer_id"):
                        steals += 1
                        team_steals[defense_team] = team_steals.get(defense_team, 0) + 1
                elif isinstance(segment, NonShootingFoulSegmentResult):
                    non_shooting_fouls += 1
                    foul_key = (defense_team, segment.fouler_id)
                    foul_counts[foul_key] = foul_counts.get(foul_key, 0) + 1
                    team_foul_totals[defense_team] = team_foul_totals.get(defense_team, 0) + 1
                    if segment.in_bonus:
                        bonus_non_shooting_fouls += 1
                    usage_player = segment.offended_player_id
                    free_throws_attempted += len(segment.free_throws)
                    free_throws_made += sum(segment.free_throws)
                    live_score[offense_team] += sum(segment.free_throws)
                    if segment.rebound is not None:
                        if isinstance(segment.rebound, OffensiveRebound):
                            offensive_rebounds += 1
                        else:
                            defensive_rebounds += 1
                elif isinstance(segment, OffensiveFoulSegmentResult):
                    turnovers += 1
                    team_turnovers[offense_team] = team_turnovers.get(offense_team, 0) + 1
                    foul_key = (offense_team, segment.responsible_offender_id)
                    foul_counts[foul_key] = foul_counts.get(foul_key, 0) + 1
                    team_foul_totals[offense_team] = team_foul_totals.get(offense_team, 0) + 1
                    usage_player = segment.responsible_offender_id
                elif isinstance(segment, TechnicalFoulSegmentResult):
                    usage_player = segment.shooter_id
                    free_throws_attempted += 1
                    free_throws_made += sum(segment.free_throws)
                    scoring_team = (
                        defense_team if segment.responsible_side.value == 0 else offense_team
                    )
                    live_score[scoring_team] += sum(segment.free_throws)
                else:
                    usage_player = segment.selection.finisher_id
                    if isinstance(segment, ShootingFoulSegmentResult):
                        shooting_fouls += 1
                        foul_key = (defense_team, segment.fouler_id)
                        foul_counts[foul_key] = foul_counts.get(foul_key, 0) + 1
                        team_foul_totals[defense_team] = team_foul_totals.get(defense_team, 0) + 1
                        free_throws_attempted += len(segment.free_throws)
                        free_throws_made += sum(segment.free_throws)
                        live_score[offense_team] += sum(segment.free_throws)
                        if segment.field_goal_made:
                            live_score[offense_team] += 3 if segment.zone is ShotZone.THREE else 2
                        if segment.field_goal_made:
                            field_goal_attempts += 1
                            field_goals_made += 1
                            team_field_goal_attempts[offense_team] = (
                                team_field_goal_attempts.get(offense_team, 0) + 1
                            )
                            team_field_goals_made[offense_team] = (
                                team_field_goals_made.get(offense_team, 0) + 1
                            )
                            zone_counts[segment.zone] = zone_counts.get(segment.zone, 0) + 1
                            offense_zones = team_zone_counts.setdefault(offense_team, {})
                            offense_zones[segment.zone] = offense_zones.get(segment.zone, 0) + 1
                            if segment.zone is ShotZone.THREE:
                                three_attempts += 1
                                three_made += 1
                                team_three_attempts[offense_team] = (
                                    team_three_attempts.get(offense_team, 0) + 1
                                )
                                team_three_made[offense_team] = (
                                    team_three_made.get(offense_team, 0) + 1
                                )
                            if segment.assisted:
                                assists += 1
                                team_assists[offense_team] = team_assists.get(offense_team, 0) + 1
                        if segment.rebound is not None:
                            if isinstance(segment.rebound, OffensiveRebound):
                                offensive_rebounds += 1
                            else:
                                defensive_rebounds += 1
                    else:
                        field_goal_attempts += 1
                        team_field_goal_attempts[offense_team] = (
                            team_field_goal_attempts.get(offense_team, 0) + 1
                        )
                        zone_counts[segment.zone] = zone_counts.get(segment.zone, 0) + 1
                        offense_zones = team_zone_counts.setdefault(offense_team, {})
                        offense_zones[segment.zone] = offense_zones.get(segment.zone, 0) + 1
                        if segment.zone is ShotZone.THREE:
                            three_attempts += 1
                            team_three_attempts[offense_team] = (
                                team_three_attempts.get(offense_team, 0) + 1
                            )
                    if isinstance(segment, MadeShotSegmentResult):
                        live_score[offense_team] += 3 if segment.zone is ShotZone.THREE else 2
                        field_goals_made += 1
                        team_field_goals_made[offense_team] = (
                            team_field_goals_made.get(offense_team, 0) + 1
                        )
                        if segment.zone is ShotZone.THREE:
                            three_made += 1
                            team_three_made[offense_team] = team_three_made.get(offense_team, 0) + 1
                        if segment.assisted:
                            assists += 1
                            team_assists[offense_team] = team_assists.get(offense_team, 0) + 1
                    elif not isinstance(segment, ShootingFoulSegmentResult):
                        if isinstance(segment, BlockedShotSegmentResult):
                            blocks += 1
                            team_blocks[defense_team] = team_blocks.get(defense_team, 0) + 1
                        rebound = segment.rebound
                        if isinstance(rebound, OffensiveRebound):
                            offensive_rebounds += 1
                        else:
                            defensive_rebounds += 1
                usage_key = (offense_team, usage_player)
                usage_counts[usage_key] = usage_counts.get(usage_key, 0) + 1
                team_usage_totals[offense_team] = team_usage_totals.get(offense_team, 0) + 1

    mean_score = math.fsum(scores) / len(scores)
    score_variance = math.fsum((score - mean_score) ** 2 for score in scores) / len(scores)
    player_usage = tuple(
        PlayerUsageShare(
            team_id,
            player_id,
            count,
            _ratio(count, team_usage_totals[team_id]),
        )
        for (team_id, player_id), count in sorted(usage_counts.items())
    )
    player_fouls = tuple(
        PlayerFoulShare(
            team_id,
            player_id,
            count,
            _ratio(count, team_foul_totals[team_id]),
            100.0 * _ratio(count, team_defensive_possessions[team_id]),
        )
        for (team_id, player_id), count in sorted(foul_counts.items())
    )
    team_distributions = tuple(
        TeamDistributionMetrics(
            team_id=team_id,
            possessions=team_possessions.get(team_id, 0),
            mean_team_possessions=team_possessions.get(team_id, 0) / len(completed),
            points_per_100_possessions=(
                100.0
                * _ratio(
                    team_points.get(team_id, 0),
                    team_possessions.get(team_id, 0),
                )
            ),
            field_goal_percentage=_ratio(
                team_field_goals_made.get(team_id, 0),
                team_field_goal_attempts.get(team_id, 0),
            ),
            three_point_percentage=_ratio(
                team_three_made.get(team_id, 0),
                team_three_attempts.get(team_id, 0),
            ),
            turnover_rate=_ratio(
                team_turnovers.get(team_id, 0),
                team_possessions.get(team_id, 0),
            ),
            assist_per_field_goal=_ratio(
                team_assists.get(team_id, 0),
                team_field_goals_made.get(team_id, 0),
            ),
            block_rate=_ratio(
                team_blocks.get(team_id, 0),
                sum(
                    attempts
                    for opponent_id, attempts in team_field_goal_attempts.items()
                    if opponent_id != team_id
                ),
            ),
            steal_rate=_ratio(
                team_steals.get(team_id, 0),
                team_defensive_possessions.get(team_id, 0),
            ),
            shot_zone_shares=_shares(
                team_zone_counts.get(team_id, {}),
                tuple(ShotZone),
            ),
            route_shares=_shares(team_route_counts.get(team_id, {}), tuple(FinisherRoute)),
            creation_mode_shares=_shares(
                team_creation_mode_counts.get(team_id, {}), tuple(CreationMode)
            ),
            tactical_action_shares=_shares(
                team_tactical_action_counts.get(team_id, {}), tuple(TacticalAction)
            ),
        )
        for team_id in sorted(team_points)
    )
    return DistributionAudit(
        games=len(results),
        completed_games=len(completed),
        aborted_games=len(results) - len(completed),
        completed_possessions=completed_possessions,
        mean_team_score=mean_score,
        team_score_stddev=math.sqrt(score_variance),
        mean_team_possessions=completed_possessions / (2 * len(completed)),
        points_per_100_possessions=100.0 * math.fsum(scores) / completed_possessions,
        field_goal_percentage=_ratio(field_goals_made, field_goal_attempts),
        three_point_percentage=_ratio(three_made, three_attempts),
        turnover_rate=_ratio(turnovers, completed_possessions),
        offensive_rebound_rate=_ratio(
            offensive_rebounds,
            offensive_rebounds + defensive_rebounds,
        ),
        assist_per_field_goal=_ratio(assists, field_goals_made),
        block_rate=_ratio(blocks, field_goal_attempts),
        steal_rate=_ratio(steals, completed_possessions),
        shot_zone_shares=_shares(zone_counts, tuple(ShotZone)),
        play_family_shares=_shares(play_counts, tuple(PlayFamily)),
        coverage_shares=_shares(coverage_counts, tuple(Coverage)),
        player_usage_shares=player_usage,
        free_throw_percentage=_ratio(free_throws_made, free_throws_attempted),
        free_throw_attempt_rate=_ratio(free_throws_attempted, field_goal_attempts),
        shooting_foul_rate=_ratio(shooting_fouls, completed_possessions),
        free_throw_points_per_100_possessions=(100.0 * free_throws_made / completed_possessions),
        field_goal_attempts_per_100_possessions=(
            100.0 * field_goal_attempts / completed_possessions
        ),
        non_shooting_foul_rate=_ratio(non_shooting_fouls, completed_possessions),
        bonus_non_shooting_foul_rate=_ratio(
            bonus_non_shooting_fouls,
            completed_possessions,
        ),
        defensive_foul_rate=_ratio(
            shooting_fouls + non_shooting_fouls,
            completed_possessions,
        ),
        player_foul_shares=player_fouls,
        team_metrics=team_distributions,
        late_game_trailing_possessions=late_game_duration_counts["trailing"],
        late_game_neutral_possessions=late_game_duration_counts["neutral"],
        late_game_leading_possessions=late_game_duration_counts["leading"],
        late_game_trailing_mean_observed_seconds=_ratio(
            late_game_duration_totals["trailing"],
            late_game_duration_counts["trailing"],
        ),
        late_game_neutral_mean_observed_seconds=_ratio(
            late_game_duration_totals["neutral"],
            late_game_duration_counts["neutral"],
        ),
        late_game_leading_mean_observed_seconds=_ratio(
            late_game_duration_totals["leading"],
            late_game_duration_counts["leading"],
        ),
        two_for_one_possessions=two_for_one_possessions,
        two_for_one_mean_observed_seconds=_ratio(
            two_for_one_duration_total,
            two_for_one_possessions,
        ),
        intentional_foul_opportunities=intentional_foul_opportunities,
        intentional_fouls_committed=intentional_fouls_committed,
        intentional_foul_continuations=intentional_foul_continuations,
        intentional_foul_mean_observed_seconds=_ratio(
            intentional_foul_duration_total,
            intentional_fouls_committed,
        ),
        route_shares=_shares(route_counts, tuple(FinisherRoute)),
        creation_mode_shares=_shares(creation_mode_counts, tuple(CreationMode)),
        tactical_action_shares=_shares(tactical_action_counts, tuple(TacticalAction)),
    )


def distribution_audit_to_json(audit: DistributionAudit) -> str:
    return json.dumps(
        asdict(audit),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )

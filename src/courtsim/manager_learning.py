"""Persistent opponent models and white-box matchup adjustments."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace

from courtsim.domain.enums import Coverage, PlayFamily, ShotZone
from courtsim.domain.game import GameClockConfig
from courtsim.domain.results import (
    BlockedShotSegmentResult,
    MadeShotSegmentResult,
    MissedShotSegmentResult,
    ShootingFoulSegmentResult,
)
from courtsim.manager_ai import ManagerProfile
from courtsim.season import SeasonResult

MANAGER_LEARNING_VERSION = "manager-learning-v1"


@dataclass(frozen=True, slots=True)
class OpponentObservation:
    opponent_team_id: str
    games_observed: int
    offense_strength: int
    defense_strength: int
    pace: int
    three_point_rate: int
    rim_rate: int

    def __post_init__(self) -> None:
        if not self.opponent_team_id.strip() or self.games_observed < 1:
            raise ValueError("opponent observation identity and games are invalid")
        ratings = (
            self.offense_strength,
            self.defense_strength,
            self.pace,
            self.three_point_rate,
            self.rim_rate,
        )
        if any(
            not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= 100
            for value in ratings
        ):
            raise ValueError("opponent observation ratings must be from zero through one hundred")


@dataclass(frozen=True, slots=True)
class OpponentMemory:
    opponent_team_id: str
    games_observed: int
    offense_strength: int
    defense_strength: int
    pace: int
    three_point_rate: int
    rim_rate: int

    def __post_init__(self) -> None:
        OpponentObservation(
            self.opponent_team_id,
            self.games_observed,
            self.offense_strength,
            self.defense_strength,
            self.pace,
            self.three_point_rate,
            self.rim_rate,
        )


@dataclass(frozen=True, slots=True)
class ManagerLearningState:
    manager_id: str
    team_id: str
    last_completed_season: int
    seasons_observed: int = 0
    opponents: tuple[OpponentMemory, ...] = ()
    version: str = MANAGER_LEARNING_VERSION

    def __post_init__(self) -> None:
        if not self.manager_id.strip() or not self.team_id.strip():
            raise ValueError("manager learning identity must not be blank")
        if self.last_completed_season < 0 or self.seasons_observed < 0:
            raise ValueError("manager learning season values must be non-negative")
        if self.opponents != tuple(sorted(self.opponents, key=lambda item: item.opponent_team_id)):
            raise ValueError("opponent memories must use canonical order")
        if len({item.opponent_team_id for item in self.opponents}) != len(self.opponents):
            raise ValueError("opponent memories must be unique")
        if self.version != MANAGER_LEARNING_VERSION:
            raise ValueError("unsupported manager learning version")


@dataclass(frozen=True, slots=True)
class OpponentRotationAdjustment:
    opponent_team_id: str
    offense_emphasis_bps: int
    defense_emphasis_bps: int
    perimeter_defense_emphasis_bps: int
    interior_defense_emphasis_bps: int
    pace_emphasis_bps: int
    games_observed: int
    version: str = MANAGER_LEARNING_VERSION

    def __post_init__(self) -> None:
        if not self.opponent_team_id.strip() or self.games_observed < 1:
            raise ValueError("opponent rotation adjustment is invalid")
        values = (
            self.offense_emphasis_bps,
            self.defense_emphasis_bps,
            self.perimeter_defense_emphasis_bps,
            self.interior_defense_emphasis_bps,
            self.pace_emphasis_bps,
        )
        if any(not -2_500 <= value <= 2_500 for value in values):
            raise ValueError("opponent rotation emphasis exceeds its bounded range")
        if self.version != MANAGER_LEARNING_VERSION:
            raise ValueError("unsupported opponent adjustment version")


@dataclass(frozen=True, slots=True)
class OpponentTacticalAdjustment:
    opponent_team_id: str
    play_family_logit_biases: tuple[tuple[PlayFamily, float], ...]
    coverage_logit_biases: tuple[tuple[Coverage, float], ...]
    tempo_delta: int
    confidence_bps: int
    matchup_net_rating: int
    response_multiplier_bps: int
    games_observed: int
    version: str = MANAGER_LEARNING_VERSION

    def __post_init__(self) -> None:
        if not self.opponent_team_id.strip() or self.games_observed < 1:
            raise ValueError("opponent tactical adjustment is invalid")
        if tuple(item[0] for item in self.play_family_logit_biases) != tuple(PlayFamily):
            raise ValueError("play-family tactical biases must use canonical order")
        if tuple(item[0] for item in self.coverage_logit_biases) != tuple(Coverage):
            raise ValueError("coverage tactical biases must use canonical order")
        biases = tuple(item[1] for item in self.play_family_logit_biases) + tuple(
            item[1] for item in self.coverage_logit_biases
        )
        if any(abs(value) > 0.75 for value in biases):
            raise ValueError("opponent tactical bias exceeds its bounded range")
        if not -15 <= self.tempo_delta <= 15:
            raise ValueError("opponent tempo adjustment exceeds its bounded range")
        if not 0 <= self.confidence_bps <= 10_000:
            raise ValueError("opponent tactical confidence is invalid")
        if not -100 <= self.matchup_net_rating <= 100:
            raise ValueError("opponent matchup net rating is invalid")
        if not 7_500 <= self.response_multiplier_bps <= 12_500:
            raise ValueError("opponent tactical response multiplier is invalid")
        if self.version != MANAGER_LEARNING_VERSION:
            raise ValueError("unsupported opponent adjustment version")


def update_manager_learning(
    state: ManagerLearningState,
    observations: Sequence[OpponentObservation],
    *,
    completed_season: int,
) -> ManagerLearningState:
    if completed_season <= state.last_completed_season:
        raise ValueError("manager learning seasons must advance monotonically")
    memories = {item.opponent_team_id: item for item in state.opponents}
    for observation in sorted(
        observations,
        key=lambda item: item.opponent_team_id,
    ):
        previous = memories.get(observation.opponent_team_id)
        if previous is None:
            memories[observation.opponent_team_id] = OpponentMemory(
                observation.opponent_team_id,
                observation.games_observed,
                observation.offense_strength,
                observation.defense_strength,
                observation.pace,
                observation.three_point_rate,
                observation.rim_rate,
            )
            continue
        games = previous.games_observed + observation.games_observed
        memories[observation.opponent_team_id] = OpponentMemory(
            observation.opponent_team_id,
            games,
            _weighted(
                previous.offense_strength,
                previous.games_observed,
                observation.offense_strength,
                observation.games_observed,
            ),
            _weighted(
                previous.defense_strength,
                previous.games_observed,
                observation.defense_strength,
                observation.games_observed,
            ),
            _weighted(
                previous.pace,
                previous.games_observed,
                observation.pace,
                observation.games_observed,
            ),
            _weighted(
                previous.three_point_rate,
                previous.games_observed,
                observation.three_point_rate,
                observation.games_observed,
            ),
            _weighted(
                previous.rim_rate,
                previous.games_observed,
                observation.rim_rate,
                observation.games_observed,
            ),
        )
    return replace(
        state,
        last_completed_season=completed_season,
        seasons_observed=state.seasons_observed + 1,
        opponents=tuple(sorted(memories.values(), key=lambda item: item.opponent_team_id)),
    )


def advance_manager_learning_from_season(
    season: SeasonResult,
    existing: Sequence[ManagerLearningState],
    profiles: Mapping[str, ManagerProfile],
    game_config: GameClockConfig,
    *,
    completed_season: int,
) -> tuple[ManagerLearningState, ...]:
    """Update every manager from the canonical regular-season event ledger."""
    existing_by_team = {item.team_id: item for item in existing}
    result = []
    for team_id in sorted(profiles):
        totals: dict[str, list[int]] = defaultdict(lambda: [0] * 8)
        for record in season.games:
            scheduled = record.scheduled_game
            if scheduled.home_team_id == team_id:
                opponent = scheduled.away_team_id
                team_points, opponent_points = record.home_score, record.away_score
            elif scheduled.away_team_id == team_id:
                opponent = scheduled.home_team_id
                team_points, opponent_points = record.away_score, record.home_score
            else:
                continue
            totals[opponent][0] += 1
            totals[opponent][1] += opponent_points
            totals[opponent][2] += team_points
            if record.result is None:
                continue
            for possession in record.result.possessions:
                offense_index = 3 if possession.offense_team_id == opponent else 4
                totals[opponent][offense_index] += 1
                if possession.offense_team_id != opponent:
                    continue
                for segment in possession.result.segments:
                    if not isinstance(
                        segment,
                        (
                            MadeShotSegmentResult,
                            MissedShotSegmentResult,
                            BlockedShotSegmentResult,
                            ShootingFoulSegmentResult,
                        ),
                    ):
                        continue
                    totals[opponent][5] += 1
                    totals[opponent][6] += segment.zone is ShotZone.THREE
                    totals[opponent][7] += segment.zone is ShotZone.RIM
        observations = tuple(
            opponent_observation_from_totals(opponent, values, game_config)
            for opponent, values in sorted(totals.items())
        )
        profile = profiles[team_id]
        prior = existing_by_team.get(
            team_id,
            ManagerLearningState(
                profile.manager_id,
                team_id,
                completed_season - 1,
            ),
        )
        if prior.manager_id != profile.manager_id:
            prior = ManagerLearningState(
                profile.manager_id,
                team_id,
                completed_season - 1,
            )
        result.append(
            update_manager_learning(
                prior,
                observations,
                completed_season=completed_season,
            )
        )
    return tuple(result)


def opponent_rotation_adjustment(
    state: ManagerLearningState,
    opponent_team_id: str,
) -> OpponentRotationAdjustment | None:
    memory = next(
        (item for item in state.opponents if item.opponent_team_id == opponent_team_id),
        None,
    )
    if memory is None:
        return None
    return OpponentRotationAdjustment(
        opponent_team_id,
        _bounded((memory.defense_strength - 50) * 40),
        _bounded((memory.offense_strength - 50) * 40),
        _bounded((memory.three_point_rate - 50) * 35),
        _bounded((memory.rim_rate - 50) * 35),
        _bounded((memory.pace - 50) * 25),
        memory.games_observed,
    )


def opponent_tactical_adjustment(
    state: ManagerLearningState,
    opponent_team_id: str,
) -> OpponentTacticalAdjustment | None:
    memory = next(
        (item for item in state.opponents if item.opponent_team_id == opponent_team_id),
        None,
    )
    if memory is None:
        return None
    confidence_bps = min(10_000, memory.games_observed * 1_250)
    confidence = confidence_bps / 10_000
    matchup_net_rating = (100 - memory.defense_strength) - memory.offense_strength
    response_multiplier_bps = max(
        7_500,
        min(12_500, 10_000 - matchup_net_rating * 100),
    )
    response_multiplier = response_multiplier_bps / 10_000
    tactical_weight = confidence * response_multiplier
    defense_delta = memory.defense_strength - 50
    offense_delta = memory.offense_strength - 50
    three_delta = memory.three_point_rate - 50
    rim_delta = memory.rim_rate - 50

    offense_biases = (
        (PlayFamily.BALL_SCREEN, _bounded_bias(defense_delta * 0.006 * tactical_weight)),
        (PlayFamily.ISOLATION, _bounded_bias(-defense_delta * 0.010 * tactical_weight)),
        (
            PlayFamily.OFF_BALL_ACTION,
            _bounded_bias(defense_delta * 0.008 * tactical_weight),
        ),
    )
    coverage_biases = (
        (
            Coverage.BASE,
            _bounded_bias(-abs(three_delta - rim_delta) * 0.002 * tactical_weight),
        ),
        (
            Coverage.DROP,
            _bounded_bias((rim_delta * 0.009 - three_delta * 0.007) * tactical_weight),
        ),
        (
            Coverage.SWITCH,
            _bounded_bias((three_delta * 0.009 - rim_delta * 0.004) * tactical_weight),
        ),
        (
            Coverage.BLITZ,
            _bounded_bias((offense_delta * 0.006 + three_delta * 0.004) * tactical_weight),
        ),
    )
    tempo_delta = round(((50 - memory.pace) * 0.20 + defense_delta * 0.10) * tactical_weight)
    return OpponentTacticalAdjustment(
        opponent_team_id,
        offense_biases,
        coverage_biases,
        max(-15, min(15, tempo_delta)),
        confidence_bps,
        matchup_net_rating,
        response_multiplier_bps,
        memory.games_observed,
    )


def _weighted(
    previous: int,
    previous_games: int,
    observed: int,
    observed_games: int,
) -> int:
    return (previous * previous_games + observed * observed_games) // (
        previous_games + observed_games
    )


def _bounded(value: int) -> int:
    return max(-2_500, min(2_500, value))


def _bounded_bias(value: float) -> float:
    return round(max(-0.75, min(0.75, value)), 4)


def opponent_observation_from_totals(
    opponent_team_id: str,
    totals: list[int],
    game_config: GameClockConfig,
) -> OpponentObservation:
    (
        games,
        opponent_points,
        team_points,
        opponent_possessions,
        team_possessions,
        opponent_shots,
        opponent_threes,
        opponent_rim_shots,
    ) = totals
    reference_possessions = (
        game_config.regulation_periods
        * game_config.period_seconds
        / (2 * game_config.possession_seconds)
    )
    possessions_per_game = opponent_possessions / max(1, games)
    return OpponentObservation(
        opponent_team_id,
        games,
        _bounded_rating(round(opponent_points * 50 / max(1, opponent_possessions))),
        _bounded_rating(100 - round(team_points * 50 / max(1, team_possessions))),
        _bounded_rating(round(50 * possessions_per_game / reference_possessions)),
        _percentage(opponent_threes, opponent_shots),
        _percentage(opponent_rim_shots, opponent_shots),
    )


def _percentage(part: int, whole: int) -> int:
    return 50 if whole == 0 else _bounded_rating(round(part * 100 / whole))


def _bounded_rating(value: int) -> int:
    return max(0, min(100, value))


def manager_learning_to_dict(state: ManagerLearningState) -> dict[str, object]:
    return {
        "version": state.version,
        "manager_id": state.manager_id,
        "team_id": state.team_id,
        "last_completed_season": state.last_completed_season,
        "seasons_observed": state.seasons_observed,
        "opponents": [
            {
                "opponent_team_id": item.opponent_team_id,
                "games_observed": item.games_observed,
                "offense_strength": item.offense_strength,
                "defense_strength": item.defense_strength,
                "pace": item.pace,
                "three_point_rate": item.three_point_rate,
                "rim_rate": item.rim_rate,
            }
            for item in state.opponents
        ],
    }


def manager_learning_from_dict(value: object) -> ManagerLearningState:
    if not isinstance(value, dict) or set(value) != {
        "version",
        "manager_id",
        "team_id",
        "last_completed_season",
        "seasons_observed",
        "opponents",
    }:
        raise ValueError("invalid manager learning object")
    opponents_raw = value["opponents"]
    if not isinstance(opponents_raw, list):
        raise ValueError("manager learning opponents must be a list")
    opponents = tuple(
        OpponentMemory(
            str(item["opponent_team_id"]),
            int(item["games_observed"]),
            int(item["offense_strength"]),
            int(item["defense_strength"]),
            int(item["pace"]),
            int(item["three_point_rate"]),
            int(item["rim_rate"]),
        )
        for item in opponents_raw
        if isinstance(item, dict)
    )
    if len(opponents) != len(opponents_raw):
        raise ValueError("manager learning opponents must be objects")
    return ManagerLearningState(
        str(value["manager_id"]),
        str(value["team_id"]),
        int(value["last_completed_season"]),
        int(value["seasons_observed"]),
        opponents,
        str(value["version"]),
    )

"""Persistent opponent models and white-box matchup adjustments."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace

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

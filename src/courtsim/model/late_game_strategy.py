"""Deterministic late-game strategy state resolution."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, cast

from courtsim.domain.enums import LateGameDefenseMode, LateGameOffenseMode
from courtsim.parameters import ModelParameters


@dataclass(frozen=True, slots=True)
class LateGameStrategyConfig:
    final_window_seconds: int
    score_margin_threshold: int
    two_for_one_window_start_seconds: int
    two_for_one_window_end_seconds: int
    two_for_one_max_abs_margin: int
    two_for_one_tempo_delta: int
    intentional_foul_window_seconds: int
    intentional_foul_min_trailing_margin: int
    intentional_foul_max_trailing_margin: int
    intentional_foul_formal_enabled: bool = False
    intentional_foul_non_bonus_enabled: bool = False
    intentional_foul_clock_seconds: int = 3


@dataclass(frozen=True, slots=True)
class LateGameStrategyState:
    offense_mode: LateGameOffenseMode
    defense_mode: LateGameDefenseMode


DEFAULT_LATE_GAME_STRATEGY_CONFIG = LateGameStrategyConfig(
    final_window_seconds=120,
    score_margin_threshold=6,
    two_for_one_window_start_seconds=32,
    two_for_one_window_end_seconds=40,
    two_for_one_max_abs_margin=5,
    two_for_one_tempo_delta=15,
    intentional_foul_window_seconds=30,
    intentional_foul_min_trailing_margin=3,
    intentional_foul_max_trailing_margin=8,
)


def late_game_strategy_config(
    parameters: ModelParameters,
    *,
    shadow_legacy: bool = False,
) -> LateGameStrategyConfig | None:
    if parameters.schema.schema_version not in {
        "demo-v1.10",
        "demo-v1.11",
        "demo-v1.12",
    }:
        return (
            DEFAULT_LATE_GAME_STRATEGY_CONFIG
            if shadow_legacy and parameters.schema.schema_version == "demo-v1.9"
            else None
        )
    nodes = cast(Mapping[str, Any], parameters.payload["nodes"])
    strategy = cast(Mapping[str, Any], nodes["late_game_strategy"])
    duration = cast(Mapping[str, Any], nodes["possession_duration"])
    adjustments = cast(Mapping[str, Any], duration["late_game_adjustments"])
    return LateGameStrategyConfig(
        final_window_seconds=cast(int, adjustments["window_seconds"]),
        score_margin_threshold=cast(int, adjustments["margin_threshold"]),
        two_for_one_window_start_seconds=cast(int, strategy["two_for_one_window_start_seconds"]),
        two_for_one_window_end_seconds=cast(int, strategy["two_for_one_window_end_seconds"]),
        two_for_one_max_abs_margin=cast(int, strategy["two_for_one_max_abs_margin"]),
        two_for_one_tempo_delta=cast(int, strategy["two_for_one_tempo_delta"]),
        intentional_foul_window_seconds=cast(int, strategy["intentional_foul_window_seconds"]),
        intentional_foul_min_trailing_margin=cast(
            int, strategy["intentional_foul_min_trailing_margin"]
        ),
        intentional_foul_max_trailing_margin=cast(
            int, strategy["intentional_foul_max_trailing_margin"]
        ),
        intentional_foul_formal_enabled=parameters.schema.schema_version
        in {"demo-v1.11", "demo-v1.12"},
        intentional_foul_non_bonus_enabled=parameters.schema.schema_version == "demo-v1.12",
        intentional_foul_clock_seconds=cast(int, strategy.get("intentional_foul_clock_seconds", 3)),
    )


def resolve_late_game_strategy(
    config: LateGameStrategyConfig,
    *,
    period: int,
    clock_seconds: int,
    regulation_periods: int,
    offense_score: int,
    defense_score: int,
) -> LateGameStrategyState:
    if period != regulation_periods:
        return LateGameStrategyState(
            LateGameOffenseMode.STANDARD,
            LateGameDefenseMode.STANDARD,
        )
    margin = offense_score - defense_score
    offense_mode = LateGameOffenseMode.STANDARD
    if (
        config.two_for_one_window_start_seconds
        <= clock_seconds
        <= config.two_for_one_window_end_seconds
        and abs(margin) <= config.two_for_one_max_abs_margin
    ):
        offense_mode = LateGameOffenseMode.TWO_FOR_ONE
    elif clock_seconds <= config.final_window_seconds:
        if margin <= -config.score_margin_threshold:
            offense_mode = LateGameOffenseMode.COMEBACK
        elif margin >= config.score_margin_threshold:
            offense_mode = LateGameOffenseMode.PROTECT_LEAD

    defense_trailing_margin = margin
    defense_mode = LateGameDefenseMode.STANDARD
    if (
        clock_seconds <= config.intentional_foul_window_seconds
        and config.intentional_foul_min_trailing_margin
        <= defense_trailing_margin
        <= config.intentional_foul_max_trailing_margin
    ):
        defense_mode = LateGameDefenseMode.INTENTIONAL_FOUL
    return LateGameStrategyState(offense_mode, defense_mode)

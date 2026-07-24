from pathlib import Path

from courtsim.domain.enums import LateGameDefenseMode, LateGameOffenseMode
from courtsim.model.late_game_strategy import (
    LateGameStrategyConfig,
    LateGameStrategyState,
    late_game_strategy_config,
    resolve_late_game_strategy,
)
from courtsim.parameters import load_model_parameters

ROOT = Path(__file__).parents[1]
PARAMETERS = load_model_parameters(
    ROOT / "data" / "model_schema_demo_v1_10.json",
    ROOT / "data" / "model_parameters_demo_1.2.0.json",
)
_CONFIG = late_game_strategy_config(PARAMETERS)
assert _CONFIG is not None
CONFIG: LateGameStrategyConfig = _CONFIG


def state(clock: int, margin: int, *, period: int = 4) -> LateGameStrategyState:
    return resolve_late_game_strategy(
        CONFIG,
        period=period,
        clock_seconds=clock,
        regulation_periods=4,
        offense_score=100 + margin,
        defense_score=100,
    )


def test_two_for_one_has_priority_for_close_games() -> None:
    assert state(40, 5).offense_mode is LateGameOffenseMode.TWO_FOR_ONE
    assert state(32, -5).offense_mode is LateGameOffenseMode.TWO_FOR_ONE
    assert state(41, 0).offense_mode is LateGameOffenseMode.STANDARD


def test_comeback_and_lead_protection_apply_outside_two_for_one() -> None:
    assert state(90, -6).offense_mode is LateGameOffenseMode.COMEBACK
    assert state(90, 6).offense_mode is LateGameOffenseMode.PROTECT_LEAD
    assert state(90, 0).offense_mode is LateGameOffenseMode.STANDARD


def test_intentional_foul_is_a_defense_shadow_state() -> None:
    assert state(30, 3).defense_mode is LateGameDefenseMode.INTENTIONAL_FOUL
    assert state(10, 8).defense_mode is LateGameDefenseMode.INTENTIONAL_FOUL
    assert state(30, 9).defense_mode is LateGameDefenseMode.STANDARD
    assert state(31, 5).defense_mode is LateGameDefenseMode.STANDARD
    assert state(20, 5, period=3).defense_mode is LateGameDefenseMode.STANDARD

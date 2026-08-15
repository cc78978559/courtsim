from pathlib import Path

import pytest

from courtsim.analysis.nba_shot_profile_runner import (
    NbaShotProfileRunnerError,
    _build_teams,
    run_nba_shot_profile_experiment,
)
from courtsim.domain.game import GameClockConfig
from courtsim.domain.player_serialization import player_lineup_from_json

ROOT = Path(__file__).parents[1]


def test_runner_builds_unique_fifteen_player_rosters() -> None:
    templates = player_lineup_from_json(
        (ROOT / "examples" / "calibration_lineup_v1.json").read_text(encoding="utf-8")
    )
    teams = _build_teams(tuple(f"team-{index:02d}" for index in range(30)), templates)
    assert len(teams) == 30
    assert all(len(team.roster_order) == 15 for team in teams)
    assert len({player_id for team in teams for player_id in team.roster_order}) == 450


def test_runner_rejects_invalid_seed_before_loading_inputs(tmp_path: Path) -> None:
    with pytest.raises(NbaShotProfileRunnerError, match="seed"):
        run_nba_shot_profile_experiment(
            profile_path=tmp_path / "missing-profile.json",
            schema_path=tmp_path / "missing-schema.json",
            parameters_path=tmp_path / "missing-parameters.json",
            lineup_path=tmp_path / "missing-lineup.json",
            output_directory=tmp_path / "output",
            seed=True,
            game_config=GameClockConfig(overtime_enabled=True),
        )

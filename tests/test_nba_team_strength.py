from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import cast

from courtsim.analysis.nba_team_strength import (
    apply_nba_team_strengths,
    load_nba_team_strength_alignment,
)
from courtsim.domain.plans import Lineup
from courtsim.model.game_runtime import GameTeam
from courtsim.model.interaction_compiler import ProfileLineup

ROOT = Path(__file__).resolve().parents[1]


def test_team_strength_applies_source_derived_offsets() -> None:
    # Reuse the valid role objects from the tracked lineup instead of manufacturing invalid mixes.
    from courtsim.domain.player_serialization import player_lineup_from_json

    templates = player_lineup_from_json(
        (ROOT / "examples" / "calibration_lineup_v1.json").read_text(encoding="utf-8")
    )
    names = [
        "Atlanta Hawks",
        "Boston Celtics",
        "Brooklyn Nets",
        "Charlotte Hornets",
        "Chicago Bulls",
        "Cleveland Cavaliers",
        "Dallas Mavericks",
        "Denver Nuggets",
        "Detroit Pistons",
        "Golden State Warriors",
        "Houston Rockets",
        "Indiana Pacers",
        "LA Clippers",
        "Los Angeles Lakers",
        "Memphis Grizzlies",
        "Miami Heat",
        "Milwaukee Bucks",
        "Minnesota Timberwolves",
        "New Orleans Pelicans",
        "New York Knicks",
        "Oklahoma City Thunder",
        "Orlando Magic",
        "Philadelphia 76ers",
        "Phoenix Suns",
        "Portland Trail Blazers",
        "Sacramento Kings",
        "San Antonio Spurs",
        "Toronto Raptors",
        "Utah Jazz",
        "Washington Wizards",
    ]
    teams = []
    for index, name in enumerate(names):
        profiles = tuple(
            replace(item, player_id=index * 5 + slot) for slot, item in enumerate(templates)
        )
        teams.append(
            GameTeam(
                name,
                cast(Lineup, tuple(item.player_id for item in profiles)),
                cast(ProfileLineup, profiles),
            )
        )
    result = apply_nba_team_strengths(
        tuple(teams), ROOT / "experiments" / "sources" / "nba-2024-25-team-strength-v1.json"
    )
    by_id = {team.team_id: team for team in result}
    assert (
        by_id["Oklahoma City Thunder"].profiles[0].abilities.playmaking
        == templates[0].abilities.playmaking + 10
    )
    assert (
        by_id["Washington Wizards"].profiles[0].abilities.playmaking
        == templates[0].abilities.playmaking - 9
    )
    alignment = load_nba_team_strength_alignment(
        ROOT / "experiments" / "sources" / "nba-2024-25-team-strength-v1.json"
    )
    assert "Boston Celtics" in alignment.east_team_ids
    assert "Los Angeles Lakers" in alignment.west_team_ids
    assert len(alignment.east_team_ids) == len(alignment.west_team_ids) == 15

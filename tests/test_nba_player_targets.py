import json
from pathlib import Path

import pytest

from courtsim.analysis.nba_player_targets import (
    NBAPlayerSourceReceipt,
    NBAPlayerTarget,
    NbaPlayerTargetError,
    NBAPlayerTargetSet,
    load_nba_player_target_set,
    nba_player_target_set_to_dict,
)
from courtsim.artifacts import write_json


def _targets() -> NBAPlayerTargetSet:
    return NBAPlayerTargetSet(
        "nba-2024-25-player-realism-v1",
        "2024-25",
        "local-fixture",
        10,
        8.0,
        (NBAPlayerSourceReceipt("box_scores", "sources/box.json", "a" * 64),),
        (
            NBAPlayerTarget(
                10,
                "Player A",
                "A",
                70,
                32.5,
                0.25,
                0.61,
                0.22,
                (0.4, 0.2, 0.4),
                (0.7, 0.45, 0.38),
            ),
        ),
    )


def test_nba_player_targets_round_trip(tmp_path: Path) -> None:
    targets = _targets()
    path = tmp_path / "targets.json"
    write_json(path, nba_player_target_set_to_dict(targets))
    assert load_nba_player_target_set(path) == targets


def test_nba_player_targets_reject_incomplete_zones(tmp_path: Path) -> None:
    payload = nba_player_target_set_to_dict(_targets())
    players = payload["players"]
    assert isinstance(players, list)
    players[0]["shot_zone_shares"].pop("THREE")
    path = tmp_path / "targets.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(NbaPlayerTargetError, match="zones are invalid"):
        load_nba_player_target_set(path)

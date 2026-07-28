import json
from pathlib import Path

import pytest
from test_phase48_nba_franchise import _state

from courtsim.nba_franchise_artifacts import (
    NBAFranchiseArtifactError,
    load_nba_franchise_checkpoint,
    nba_franchise_state_from_json,
    nba_franchise_state_to_json,
    write_nba_franchise_checkpoint,
)


def test_franchise_state_json_is_canonical_and_strict() -> None:
    state, _, contract_rules = _state()
    payload = nba_franchise_state_to_json(state, contract_rules)

    restored, restored_rules = nba_franchise_state_from_json(payload)
    assert restored == state
    assert restored_rules == contract_rules
    assert nba_franchise_state_to_json(restored, restored_rules) == payload

    raw = json.loads(payload)
    raw["unexpected"] = True
    with pytest.raises(NBAFranchiseArtifactError, match="keys must be exactly"):
        nba_franchise_state_from_json(json.dumps(raw))


def test_franchise_checkpoint_rejects_corruption(tmp_path: Path) -> None:
    state, _, contract_rules = _state()
    path = tmp_path / "franchise.json"
    receipt = write_nba_franchise_checkpoint(state, contract_rules, path)
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["state"]["league_id"] = "tampered"
    path.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(NBAFranchiseArtifactError, match="state hash differs"):
        load_nba_franchise_checkpoint(path)
    with pytest.raises(NBAFranchiseArtifactError, match="file hash differs"):
        load_nba_franchise_checkpoint(path, expected_file_sha256=receipt.file_sha256)

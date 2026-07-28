import json
from dataclasses import replace
from pathlib import Path

import pytest
from test_phase48_nba_franchise import _state

from courtsim.cap_mechanics import BirdRights, CapLedger, TradeException
from courtsim.cli import main
from courtsim.nba_franchise_artifacts import (
    NBAFranchiseArtifactError,
    load_nba_franchise_checkpoint,
    nba_franchise_state_from_json,
    nba_franchise_state_to_json,
    write_nba_franchise_checkpoint,
)


def test_franchise_state_json_is_canonical_and_strict() -> None:
    state, _, contract_rules = _state()
    state = replace(
        state,
        cap_ledger=CapLedger(
            bird_rights=(BirdRights("T01", 1, 3, 1_000_000),),
            trade_exceptions=(TradeException(1, "T02", 250_000, 2030),),
            next_exception_id=2,
        ),
    )
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


def test_compressed_checkpoint_is_deterministic_and_migrates_v2_state(
    tmp_path: Path,
) -> None:
    state, _, contract_rules = _state()
    first = tmp_path / "first.json.gz"
    second = tmp_path / "second.json.gz"
    first_receipt = write_nba_franchise_checkpoint(
        state,
        contract_rules,
        first,
        compress=True,
    )
    second_receipt = write_nba_franchise_checkpoint(
        state,
        contract_rules,
        second,
        compress=True,
    )
    assert first.read_bytes() == second.read_bytes()
    assert first_receipt.compression == "gzip"
    assert second_receipt.file_sha256 == first_receipt.file_sha256
    restored, restored_rules, loaded = load_nba_franchise_checkpoint(first)
    assert restored == state
    assert restored_rules == contract_rules
    assert loaded.compression == "gzip"

    legacy = json.loads(nba_franchise_state_to_json(state, contract_rules))
    legacy["schema_version"] = 1
    legacy["version"] = "nba-franchise-v4"
    migrated, _ = nba_franchise_state_from_json(json.dumps(legacy))
    assert migrated == state


def test_franchise_checkpoint_verification_cli(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    state, _, contract_rules = _state()
    checkpoint = tmp_path / "franchise.json.gz"
    receipt = write_nba_franchise_checkpoint(
        state,
        contract_rules,
        checkpoint,
        compress=True,
    )

    assert (
        main(
            [
                "nba-franchise-checkpoint-verify",
                str(checkpoint),
                "--expected-file-sha256",
                receipt.file_sha256,
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["compression"] == "gzip"
    assert payload["completed_seasons"] == state.completed_seasons

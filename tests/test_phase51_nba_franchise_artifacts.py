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
from courtsim.nba_franchise_runner import (
    NBA_FRANCHISE_RUNNER_VERSION,
    NBAFranchiseRetentionPolicy,
    _checkpoint_to_dict,
    _migrate_manifest,
    _remove_retention_garbage,
    _stage_retention,
    nba_franchise_execution_config_sha256,
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
    legacy["version"] = "nba-franchise-v5"
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


def test_runner_v3_manifest_migration_preserves_checkpoint_seed_versions() -> None:
    legacy = {
        "schema_version": 2,
        "version": "nba-franchise-runner-v3",
        "spec": {
            "run_id": "legacy-run",
            "master_seed": 77,
            "seasons": 2,
            "version": "nba-franchise-runner-v3",
        },
        "checkpoints": [
            {
                "completed_seasons": 1,
                "seed_version": "nba-franchise-runner-v3",
            }
        ],
    }

    migrated = _migrate_manifest(legacy)

    assert migrated["version"] == NBA_FRANCHISE_RUNNER_VERSION
    migrated_spec = migrated["spec"]
    assert isinstance(migrated_spec, dict)
    assert migrated_spec["version"] == NBA_FRANCHISE_RUNNER_VERSION
    assert migrated_spec["execution_config_sha256"] == "0" * 64
    assert migrated["schema_version"] == 3
    assert migrated["checkpoints"] == legacy["checkpoints"]


@pytest.mark.parametrize("schema_version", [2, 3])
def test_runner_v4_manifest_migrates_to_distinct_v5_identity(schema_version: int) -> None:
    spec: dict[str, object] = {
        "run_id": "legacy-v4-run",
        "master_seed": 88,
        "seasons": 2,
        "version": "nba-franchise-runner-v4",
    }
    if schema_version == 3:
        spec["execution_config_sha256"] = "a" * 64
    legacy = {
        "schema_version": schema_version,
        "version": "nba-franchise-runner-v4",
        "spec": spec,
        "checkpoints": [
            {
                "completed_seasons": 1,
                "seed_version": "nba-franchise-runner-v4",
            }
        ],
    }

    migrated = _migrate_manifest(legacy)

    assert migrated["schema_version"] == 3
    assert migrated["version"] == NBA_FRANCHISE_RUNNER_VERSION
    migrated_spec = migrated["spec"]
    assert isinstance(migrated_spec, dict)
    assert migrated_spec["version"] == NBA_FRANCHISE_RUNNER_VERSION
    expected_hash = "a" * 64 if schema_version == 3 else "0" * 64
    assert migrated_spec["execution_config_sha256"] == expected_hash
    assert migrated["checkpoints"] == legacy["checkpoints"]


def test_execution_config_hash_is_canonical_and_rejects_non_json_values() -> None:
    first = nba_franchise_execution_config_sha256({"b": [2, 3], "a": 1})
    second = nba_franchise_execution_config_sha256({"a": 1, "b": [2, 3]})
    assert first == second
    assert len(first) == 64
    with pytest.raises(ValueError, match="JSON-compatible"):
        nba_franchise_execution_config_sha256({"invalid": object()})


def test_retention_keeps_old_checkpoint_until_new_manifest_can_be_published(
    tmp_path: Path,
) -> None:
    state, _, contract_rules = _state()
    original = tmp_path / "season-00000.json"
    receipt = write_nba_franchise_checkpoint(state, contract_rules, original)
    checkpoints: list[object] = [
        _checkpoint_to_dict(
            0,
            None,
            receipt.state_sha256,
            receipt.file_sha256,
            seed_version=NBA_FRANCHISE_RUNNER_VERSION,
        )
    ]
    garbage = _stage_retention(
        tmp_path,
        checkpoints,
        initial_completed_seasons=0,
        latest_completed_seasons=2,
        policy=NBAFranchiseRetentionPolicy(keep_last=1, keep_every=5, compress_after=1),
    )
    assert original.is_file()
    assert (tmp_path / "season-00000.json.gz").is_file()
    assert garbage == (original,)
    _remove_retention_garbage(garbage)
    assert not original.exists()

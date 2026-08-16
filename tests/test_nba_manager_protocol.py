from dataclasses import replace
from pathlib import Path

import pytest

from courtsim.artifacts import sha256_file
from courtsim.nba_manager_protocol import (
    NBA_MANAGER_CANONICAL_TEAM_IDS,
    NBA_MANAGER_FORMAL_MASTER_SEEDS,
    NBA_MANAGER_HOLDOUT_ID,
    NBA_MANAGER_PROTOCOL_ID,
    NBAManagerProtocolError,
    canonical_nba_manager_protocol_path,
    load_nba_manager_promotion_protocol,
    verify_nba_manager_protocol_file,
)


def test_canonical_nba_manager_protocol_is_frozen_and_hash_verifiable() -> None:
    path = canonical_nba_manager_protocol_path()
    protocol = load_nba_manager_promotion_protocol(path)

    assert protocol.experiment_id == NBA_MANAGER_PROTOCOL_ID
    assert protocol.holdout_id == NBA_MANAGER_HOLDOUT_ID
    assert protocol.team_ids == NBA_MANAGER_CANONICAL_TEAM_IDS
    assert protocol.focal_team_ids == NBA_MANAGER_CANONICAL_TEAM_IDS
    assert protocol.master_seeds == NBA_MANAGER_FORMAL_MASTER_SEEDS
    assert protocol.seasons == 5
    verify_nba_manager_protocol_file(path, sha256_file(path))

    with pytest.raises(NBAManagerProtocolError, match="file differs"):
        verify_nba_manager_protocol_file(path, "0" * 64)


def test_formal_protocol_rejects_noncanonical_path(tmp_path: Path) -> None:
    copied = tmp_path / "protocol.json"
    copied.write_bytes(canonical_nba_manager_protocol_path().read_bytes())

    with pytest.raises(NBAManagerProtocolError, match="canonical path"):
        load_nba_manager_promotion_protocol(copied)


def test_protocol_rejects_identity_digest_and_schema_tampering(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = canonical_nba_manager_protocol_path()
    protocol = load_nba_manager_promotion_protocol(path)
    with pytest.raises(ValueError, match="identity"):
        replace(protocol, status="open")
    with pytest.raises(ValueError, match="digest"):
        replace(protocol, initial_state_sha256="invalid")

    with monkeypatch.context() as context:
        context.setattr(Path, "read_text", lambda *_args, **_kwargs: "{}")
        with pytest.raises(NBAManagerProtocolError, match="schema differs"):
            load_nba_manager_promotion_protocol(path)
    with monkeypatch.context() as context:
        context.setattr(Path, "read_text", lambda *_args, **_kwargs: "not-json")
        with pytest.raises(NBAManagerProtocolError, match="cannot load"):
            load_nba_manager_promotion_protocol(path)

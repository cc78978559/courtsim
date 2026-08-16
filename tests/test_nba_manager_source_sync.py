from pathlib import Path

import pytest
from test_nba_player_targets import _targets

import courtsim.analysis.nba_manager_source_sync as source_sync
from courtsim.analysis.nba_manager_source_sync import sync_nba_manager_state_source
from courtsim.analysis.nba_manager_state import load_nba_manager_state_source
from courtsim.analysis.nba_player_targets import nba_player_target_set_to_dict
from courtsim.artifacts import write_json


def test_keyless_manager_source_sync_caches_raw_and_computes_season_age(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    targets = tmp_path / "targets.json"
    identity = tmp_path / "identity.json"
    output = tmp_path / "manager-source.json"
    cache = tmp_path / "cache"
    write_json(targets, nba_player_target_set_to_dict(_targets()))
    write_json(
        identity,
        {"mappings": [{"nba_player_id": 10, "espn_player_id": 99}]},
    )

    def fetch(url: str) -> dict[str, object]:
        if "/contracts/" in url:
            return {"salary": 12_000_000, "yearsRemaining": 3, "active": True}
        return {"dateOfBirth": "2000-02-02T00:00Z", "debutYear": 2020}

    monkeypatch.setattr(source_sync, "_fetch_json", fetch)
    report = sync_nba_manager_state_source(
        player_targets_path=targets,
        identity_path=identity,
        output_path=output,
        cache_directory=cache,
        season_year=2025,
        workers=2,
    )
    loaded = load_nba_manager_state_source(output)
    assert report["age_rows"] == 1
    assert report["salary_rows"] == 1
    assert loaded.players[0].age == 24
    assert loaded.players[0].annual_salary == 12_000_000
    assert loaded.players[0].contract_years_remaining == 3
    assert loaded.players[0].team_tenure_seasons is None
    assert dict(loaded.sources).keys() == {"identity", "player_targets", "raw_manifest"}

    monkeypatch.setattr(
        source_sync,
        "_fetch_json",
        lambda _url: (_ for _ in ()).throw(AssertionError("offline run fetched network")),
    )
    offline = sync_nba_manager_state_source(
        player_targets_path=targets,
        identity_path=identity,
        output_path=output,
        cache_directory=cache,
        season_year=2025,
        offline=True,
    )
    assert offline["failures"] == {}

"""Keyless ESPN age and contract ingestion for local NBA manager studies."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, cast

from courtsim.analysis.nba_manager_state import (
    NBA_MANAGER_STATE_SOURCE_SCHEMA_VERSION,
    NBA_MANAGER_STATE_SOURCE_VERSION,
    load_nba_manager_state_source,
)
from courtsim.analysis.nba_player_targets import load_nba_player_target_set
from courtsim.artifacts import sha256_file, write_json

NBA_MANAGER_SOURCE_SYNC_VERSION = "nba-manager-source-sync-v1"
ESPN_ATHLETE_URL = (
    "https://sports.core.api.espn.com/v2/sports/basketball/leagues/nba/athletes/{espn_id}"
)
ESPN_CONTRACT_URL = ESPN_ATHLETE_URL + "/contracts/{season_year}?lang=en&region=us"


class NBAManagerSourceSyncError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class _Identity:
    nba_player_id: int
    espn_player_id: int


def sync_nba_manager_state_source(
    *,
    player_targets_path: str | Path,
    identity_path: str | Path,
    output_path: str | Path,
    cache_directory: str | Path,
    season_year: int,
    workers: int = 8,
    offline: bool = False,
    force: bool = False,
) -> dict[str, object]:
    """Fetch once, cache raw JSON locally, and emit a compact source-pinned table."""
    if season_year < 2000 or workers < 1:
        raise NBAManagerSourceSyncError("NBA manager source season or worker count is invalid")
    targets_file = Path(player_targets_path).resolve()
    identity_file = Path(identity_path).resolve()
    output_file = Path(output_path).resolve()
    cache = Path(cache_directory).resolve()
    cache.mkdir(parents=True, exist_ok=True)
    targets = load_nba_player_target_set(targets_file)
    target_by_id = {item.nba_player_id: item for item in targets.players}
    identities = _load_identities(identity_file)
    identity_by_nba = {item.nba_player_id: item.espn_player_id for item in identities}

    def load(player_id: int) -> tuple[int, dict[str, object] | None, str | None]:
        espn_id = identity_by_nba.get(player_id)
        if espn_id is None:
            return player_id, None, "missing-identity"
        cache_file = cache / f"espn-{espn_id}-season-{season_year}.json"
        if cache_file.is_file() and not force:
            try:
                value = _object(json.loads(cache_file.read_text(encoding="utf-8")), "ESPN cache")
                return player_id, value, None
            except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError):
                if offline:
                    return player_id, None, "invalid-cache"
        if offline:
            return player_id, None, "missing-cache"
        try:
            athlete = _fetch_json(ESPN_ATHLETE_URL.format(espn_id=espn_id))
            contract = _fetch_json(
                ESPN_CONTRACT_URL.format(espn_id=espn_id, season_year=season_year)
            )
            value = {
                "version": NBA_MANAGER_SOURCE_SYNC_VERSION,
                "nba_player_id": player_id,
                "espn_player_id": espn_id,
                "season_year": season_year,
                "athlete": athlete,
                "contract": contract,
            }
            write_json(cache_file, value)
            return player_id, value, None
        except (OSError, ValueError, urllib.error.URLError):
            return player_id, None, "fetch-failed"

    target_ids = tuple(item.nba_player_id for item in targets.players)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        loaded = tuple(pool.map(load, target_ids))
    rows = []
    failures: dict[str, int] = {}
    cached_files = []
    for player_id, value, failure in loaded:
        row: dict[str, object] = {"nba_player_id": player_id}
        if failure is not None:
            failures[failure] = failures.get(failure, 0) + 1
        elif value is not None:
            athlete = _object(value["athlete"], "ESPN athlete")
            contract = _object(value["contract"], "ESPN contract")
            age = _age_at_season(athlete.get("dateOfBirth"), season_year)
            salary = _positive_integer(contract.get("salary"))
            term = _positive_integer(contract.get("yearsRemaining"))
            debut = _positive_integer(athlete.get("debutYear"))
            if age is not None:
                row["age"] = age
            contract_team_id = _contract_team_id(contract.get("team"))
            team_matches = contract_team_id in {None, target_by_id[player_id].team_id}
            if salary is not None:
                row["annual_salary"] = salary
            if term is not None:
                row["contract_years_remaining"] = term
            if not team_matches:
                failures["contract-team-mismatch"] = failures.get("contract-team-mismatch", 0) + 1
            # Debut proves league service, not same-team continuity, so it cannot grant Bird rights.
            if debut is not None and debut > season_year:
                raise NBAManagerSourceSyncError("ESPN debut year is after the requested season")
            espn_id = identity_by_nba[player_id]
            cache_file = cache / f"espn-{espn_id}-season-{season_year}.json"
            cached_files.append({"path": cache_file.name, "sha256": sha256_file(cache_file)})
        rows.append(row)
    raw_manifest = cache / "raw-manifest.json"
    write_json(
        raw_manifest,
        {
            "version": NBA_MANAGER_SOURCE_SYNC_VERSION,
            "season_year": season_year,
            "files": sorted(cached_files, key=lambda item: cast(str, item["path"])),
            "failures": dict(sorted(failures.items())),
        },
    )
    payload = {
        "schema_version": NBA_MANAGER_STATE_SOURCE_SCHEMA_VERSION,
        "version": NBA_MANAGER_STATE_SOURCE_VERSION,
        "dataset_id": f"espn-nba-manager-state-{season_year}",
        "season": targets.season,
        "sources": [
            {"role": "identity", "sha256": sha256_file(identity_file)},
            {"role": "player_targets", "sha256": sha256_file(targets_file)},
            {"role": "raw_manifest", "sha256": sha256_file(raw_manifest)},
        ],
        "players": rows,
    }
    write_json(output_file, payload)
    loaded_source = load_nba_manager_state_source(output_file)
    age_rows = sum(item.age is not None for item in loaded_source.players)
    salary_rows = sum(item.annual_salary is not None for item in loaded_source.players)
    return {
        "version": NBA_MANAGER_SOURCE_SYNC_VERSION,
        "dataset_id": loaded_source.dataset_id,
        "players": len(loaded_source.players),
        "age_rows": age_rows,
        "salary_rows": salary_rows,
        "failures": dict(sorted(failures.items())),
        "output": str(output_file),
        "output_sha256": sha256_file(output_file),
        "raw_manifest": str(raw_manifest),
        "raw_manifest_sha256": sha256_file(raw_manifest),
    }


def _load_identities(path: Path) -> tuple[_Identity, ...]:
    try:
        root = _object(json.loads(path.read_text(encoding="utf-8")), "NBA identity")
        raw = root["mappings"]
        if not isinstance(raw, list):
            raise NBAManagerSourceSyncError("NBA identity mappings must be a list")
        identities = tuple(
            sorted(
                (
                    _Identity(
                        _required_integer(_object(item, "NBA identity row")["nba_player_id"]),
                        _required_integer(_object(item, "NBA identity row")["espn_player_id"]),
                    )
                    for item in raw
                ),
                key=lambda item: item.nba_player_id,
            )
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError) as error:
        raise NBAManagerSourceSyncError("cannot load NBA player identity") from error
    if len({item.nba_player_id for item in identities}) != len(identities):
        raise NBAManagerSourceSyncError("NBA player identity contains duplicate mappings")
    return identities


def _fetch_json(url: str) -> dict[str, object]:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "courtsim-personal-research/1.0", "Accept": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return cast(dict[str, object], _object(json.loads(response.read()), "ESPN response"))


def _age_at_season(value: object, season_year: int) -> int | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        born = datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
        return None
    as_of = date(season_year, 2, 1)
    return as_of.year - born.year - ((as_of.month, as_of.day) < (born.month, born.day))


def _positive_integer(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    integer = round(value)
    return integer if integer > 0 else None


def _contract_team_id(value: object) -> str | None:
    if not isinstance(value, dict):
        return None
    reference = value.get("$ref")
    if not isinstance(reference, str) or "/teams/" not in reference:
        return None
    return reference.split("/teams/", maxsplit=1)[1].split("?", maxsplit=1)[0].strip("/") or None


def _required_integer(value: object) -> int:
    result = _positive_integer(value)
    if result is None:
        raise NBAManagerSourceSyncError("NBA identity value must be a positive integer")
    return result


def _object(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise NBAManagerSourceSyncError(f"{label} must be an object")
    return cast(dict[str, Any], value)

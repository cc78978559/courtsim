"""Atomic, hash-verified persistence for complete NBA franchise state."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from courtsim.artifacts import sha256_file, write_json
from courtsim.cap_mechanics import CapLedger
from courtsim.domain.enums import Coverage, PlayFamily
from courtsim.domain.plans import Lineup
from courtsim.domain.player import PlayerProfile
from courtsim.domain.player_serialization import (
    player_profile_from_dict,
    player_profile_to_dict,
)
from courtsim.management import ContractRules
from courtsim.manager_league_adapter import (
    CourtSimLeagueState,
    league_state_from_json,
    league_state_to_json,
)
from courtsim.model.action_setup import TeamDefenseStrategy, TeamOffenseStrategy
from courtsim.model.game_runtime import GameTeam, TeamTempoStrategy
from courtsim.model.interaction_compiler import ProfileLineup
from courtsim.nba_franchise import NBAFranchiseState
from courtsim.rotations import RotationPlan, RotationStint

NBA_FRANCHISE_ARTIFACT_VERSION = "nba-franchise-artifact-v1"


class NBAFranchiseArtifactError(ValueError):
    """Raised when a franchise checkpoint is invalid or corrupted."""


@dataclass(frozen=True, slots=True)
class NBAFranchiseCheckpointReceipt:
    checkpoint_path: str
    league_id: str
    completed_seasons: int
    state_sha256: str
    file_sha256: str
    version: str = NBA_FRANCHISE_ARTIFACT_VERSION


def nba_franchise_state_to_json(
    state: NBAFranchiseState,
    contract_rules: ContractRules,
) -> str:
    payload = _state_to_dict(state, contract_rules)
    return _canonical_json(payload)


def nba_franchise_state_from_json(
    payload: str,
) -> tuple[NBAFranchiseState, ContractRules]:
    try:
        raw = _object(json.loads(payload), "NBA franchise state")
        _exact(
            raw,
            {
                "schema_version",
                "version",
                "league_id",
                "completed_seasons",
                "league_state",
                "teams",
            },
            "NBA franchise state",
        )
        if _integer(raw, "schema_version") != 1:
            raise NBAFranchiseArtifactError("unsupported NBA franchise state schema")
        league_state = league_state_from_json(_canonical_json(raw["league_state"]))
        if league_state.nba_alignment is None:
            raise NBAFranchiseArtifactError("NBA franchise checkpoint lacks alignment")
        players = {player.player_id: player.profile for player in league_state.players}
        teams_raw = _list(raw["teams"], "NBA franchise teams")
        teams = tuple(_team_from_dict(item, players) for item in teams_raw)
        state = NBAFranchiseState(
            league_id=_string(raw, "league_id"),
            management=league_state.management,
            players=league_state.players,
            draft_assets=league_state.draft_assets,
            teams=teams,
            alignment=league_state.nba_alignment,
            completed_seasons=_integer(raw, "completed_seasons"),
            manager_learning=league_state.manager_learning,
            version=_string(raw, "version"),
        )
        return state, league_state.contract_rules
    except (
        json.JSONDecodeError,
        KeyError,
        TypeError,
        ValueError,
    ) as error:
        if isinstance(error, NBAFranchiseArtifactError):
            raise
        raise NBAFranchiseArtifactError(f"invalid NBA franchise state: {error}") from error


def write_nba_franchise_checkpoint(
    state: NBAFranchiseState,
    contract_rules: ContractRules,
    checkpoint_path: str | Path,
) -> NBAFranchiseCheckpointReceipt:
    path = Path(checkpoint_path)
    state_payload = _state_to_dict(state, contract_rules)
    state_sha256 = _sha256_value(state_payload)
    envelope = {
        "schema_version": 1,
        "version": NBA_FRANCHISE_ARTIFACT_VERSION,
        "state_sha256": state_sha256,
        "state": state_payload,
    }
    write_json(path, envelope)
    return NBAFranchiseCheckpointReceipt(
        str(path.resolve()),
        state.league_id,
        state.completed_seasons,
        state_sha256,
        sha256_file(path),
    )


def load_nba_franchise_checkpoint(
    checkpoint_path: str | Path,
    *,
    expected_file_sha256: str | None = None,
) -> tuple[NBAFranchiseState, ContractRules, NBAFranchiseCheckpointReceipt]:
    path = Path(checkpoint_path)
    if not path.is_file():
        raise NBAFranchiseArtifactError("NBA franchise checkpoint path must be a file")
    file_sha256 = sha256_file(path)
    if expected_file_sha256 is not None and file_sha256 != expected_file_sha256:
        raise NBAFranchiseArtifactError("NBA franchise checkpoint file hash differs")
    try:
        envelope = _object(
            json.loads(path.read_text(encoding="utf-8")),
            "NBA franchise checkpoint",
        )
        _exact(
            envelope,
            {"schema_version", "version", "state_sha256", "state"},
            "NBA franchise checkpoint",
        )
        if (
            _integer(envelope, "schema_version") != 1
            or _string(envelope, "version") != NBA_FRANCHISE_ARTIFACT_VERSION
        ):
            raise NBAFranchiseArtifactError("unsupported NBA franchise checkpoint")
        expected_state_sha256 = _string(envelope, "state_sha256")
        if _sha256_value(envelope["state"]) != expected_state_sha256:
            raise NBAFranchiseArtifactError("NBA franchise checkpoint state hash differs")
        state, contract_rules = nba_franchise_state_from_json(_canonical_json(envelope["state"]))
        return (
            state,
            contract_rules,
            NBAFranchiseCheckpointReceipt(
                str(path.resolve()),
                state.league_id,
                state.completed_seasons,
                expected_state_sha256,
                file_sha256,
            ),
        )
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
        if isinstance(error, NBAFranchiseArtifactError):
            raise
        raise NBAFranchiseArtifactError(f"invalid NBA franchise checkpoint: {error}") from error


def _state_to_dict(
    state: NBAFranchiseState,
    contract_rules: ContractRules,
) -> dict[str, object]:
    league_state = CourtSimLeagueState(
        contract_rules,
        state.management,
        state.players,
        state.draft_assets,
        CapLedger(),
        state.manager_learning,
        state.alignment,
    )
    return {
        "schema_version": 1,
        "version": state.version,
        "league_id": state.league_id,
        "completed_seasons": state.completed_seasons,
        "league_state": json.loads(league_state_to_json(league_state)),
        "teams": [_team_to_dict(team) for team in state.teams],
    }


def _team_to_dict(team: GameTeam) -> dict[str, object]:
    return {
        "team_id": team.team_id,
        "lineup": list(team.lineup),
        "profiles": [player_profile_to_dict(profile) for profile in team.profiles],
        "bench_profiles": [player_profile_to_dict(profile) for profile in team.bench_profiles],
        "substitution_order": list(team.substitution_order),
        "offense_strategy": [
            [family.name, value] for family, value in team.offense_strategy.play_family_logit_biases
        ],
        "defense_strategy": [
            [coverage.name, value]
            for coverage, value in team.defense_strategy.coverage_logit_biases
        ],
        "tempo": team.tempo_strategy.tempo,
        "rotation_plan": (
            {
                "version": team.rotation_plan.version,
                "stints": [
                    {
                        "period": stint.period,
                        "start_clock_seconds": stint.start_clock_seconds,
                        "lineup": list(stint.lineup),
                    }
                    for stint in team.rotation_plan.stints
                ],
            }
            if team.rotation_plan is not None
            else None
        ),
    }


def _team_from_dict(
    value: object,
    player_profiles: Mapping[int, PlayerProfile],
) -> GameTeam:
    raw = _object(value, "NBA franchise team")
    _exact(
        raw,
        {
            "team_id",
            "lineup",
            "profiles",
            "bench_profiles",
            "substitution_order",
            "offense_strategy",
            "defense_strategy",
            "tempo",
            "rotation_plan",
        },
        "NBA franchise team",
    )
    lineup = cast(Lineup, _integer_tuple(raw["lineup"], "lineup"))
    substitution_order = _integer_tuple(
        raw["substitution_order"],
        "substitution_order",
    )
    try:
        profiles = cast(
            ProfileLineup,
            tuple(player_profile_from_dict(item) for item in _list(raw["profiles"], "profiles")),
        )
        bench = tuple(
            player_profile_from_dict(item)
            for item in _list(raw["bench_profiles"], "bench_profiles")
        )
        if any(profile.player_id not in player_profiles for profile in (*profiles, *bench)):
            raise NBAFranchiseArtifactError("NBA franchise team references an unknown player")
        offense = TeamOffenseStrategy(
            tuple(
                (PlayFamily[name], number)
                for name, number in _biases(
                    raw["offense_strategy"],
                    "offense_strategy",
                )
            )
        )
        defense = TeamDefenseStrategy(
            tuple(
                (Coverage[name], number)
                for name, number in _biases(
                    raw["defense_strategy"],
                    "defense_strategy",
                )
            )
        )
        rotation_raw = raw["rotation_plan"]
        rotation = None
        if rotation_raw is not None:
            rotation_object = _object(rotation_raw, "rotation_plan")
            _exact(rotation_object, {"version", "stints"}, "rotation_plan")
            rotation = RotationPlan(
                tuple(
                    _rotation_stint(item)
                    for item in _list(rotation_object["stints"], "rotation stints")
                ),
                _string(rotation_object, "version"),
            )
        return GameTeam(
            _string(raw, "team_id"),
            lineup,
            profiles,
            offense,
            defense,
            TeamTempoStrategy(_integer(raw, "tempo")),
            bench,
            substitution_order,
            rotation,
        )
    except (KeyError, TypeError, ValueError) as error:
        raise NBAFranchiseArtifactError(f"invalid NBA franchise team: {error}") from error


def _rotation_stint(value: object) -> RotationStint:
    raw = _object(value, "rotation stint")
    _exact(raw, {"period", "start_clock_seconds", "lineup"}, "rotation stint")
    return RotationStint(
        _integer(raw, "period"),
        _integer(raw, "start_clock_seconds"),
        cast(Lineup, _integer_tuple(raw["lineup"], "rotation lineup")),
    )


def _biases(value: object, field: str) -> tuple[tuple[str, float], ...]:
    items = _list(value, field)
    result = []
    for item in items:
        if (
            not isinstance(item, list)
            or len(item) != 2
            or not isinstance(item[0], str)
            or not isinstance(item[1], (int, float))
            or isinstance(item[1], bool)
        ):
            raise NBAFranchiseArtifactError(f"{field} entries are invalid")
        result.append((item[0], float(item[1])))
    return tuple(result)


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _sha256_value(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _object(value: object, field: str) -> dict[str, Any]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise NBAFranchiseArtifactError(f"{field} must be an object")
    return cast(dict[str, Any], value)


def _list(value: object, field: str) -> list[object]:
    if not isinstance(value, list):
        raise NBAFranchiseArtifactError(f"{field} must be a list")
    return cast(list[object], value)


def _exact(value: dict[str, Any], keys: set[str], field: str) -> None:
    if set(value) != keys:
        raise NBAFranchiseArtifactError(f"{field} keys must be exactly {sorted(keys)}")


def _integer(value: dict[str, Any], key: str) -> int:
    item = value[key]
    if not isinstance(item, int) or isinstance(item, bool):
        raise NBAFranchiseArtifactError(f"{key} must be an integer")
    return item


def _string(value: dict[str, Any], key: str) -> str:
    item = value[key]
    if not isinstance(item, str) or not item:
        raise NBAFranchiseArtifactError(f"{key} must be a non-empty string")
    return item


def _integer_tuple(value: object, field: str) -> tuple[int, ...]:
    items = _list(value, field)
    if any(not isinstance(item, int) or isinstance(item, bool) for item in items):
        raise NBAFranchiseArtifactError(f"{field} must contain integers")
    return tuple(cast(list[int], items))

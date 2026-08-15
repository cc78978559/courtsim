"""Frozen configuration assembly for governed NBA manager experiments."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, cast

from courtsim.analysis.nba_shot_profiles import load_nba_shot_profile_set
from courtsim.artifacts import sha256_file
from courtsim.career import CareerRules, DraftRules
from courtsim.domain.game import GameClockConfig
from courtsim.manager_ai import (
    REALITY_BASELINE_POLICY_ID,
    WHITE_BOX_CANDIDATE_POLICY_ID,
    ManagerProfile,
)
from courtsim.manager_rotation import ManagerRotationRules
from courtsim.manager_trade import ManagerTradeRules
from courtsim.model.trace_mode import TraceMode
from courtsim.nba_franchise_artifacts import (
    load_nba_franchise_checkpoint,
    nba_franchise_state_to_json,
)
from courtsim.nba_manager_adapter import (
    NBAFrontOfficeExperimentAdapter,
    load_macro_metric_ranges,
)
from courtsim.nba_manager_experiment import (
    NBAManagerExperimentSpec,
    nba_manager_execution_config_sha256,
)
from courtsim.parameters import load_model_parameters
from courtsim.scouting import ScoutingRules
from courtsim.season import SeasonConfig
from courtsim.three_team_market import ThreeTeamMarketRules
from courtsim.trade_market import TradeMarketRules
from courtsim.trades import TradeRules

NBA_MANAGER_PROFILE_SET_VERSION = "nba-manager-profile-set-v1"
NBA_MANAGER_STUDY_CONFIG_VERSION = "nba-manager-study-config-v1"


class NBAManagerStudyError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class NBAManagerStudyBundle:
    spec: NBAManagerExperimentSpec
    initial_state_payload: str
    adapter: NBAFrontOfficeExperimentAdapter
    execution_configuration: dict[str, object]
    source_hashes: tuple[tuple[str, str], ...]
    version: str = NBA_MANAGER_STUDY_CONFIG_VERSION


def load_nba_manager_profiles(
    path: str | Path,
    team_ids: tuple[str, ...],
) -> dict[str, ManagerProfile]:
    try:
        value: object = json.loads(Path(path).read_text(encoding="utf-8"))
        root = _object(value, "NBA manager profiles")
        if set(root) != {"version", "profile_set_id", "profiles"}:
            raise NBAManagerStudyError("NBA manager profile root is invalid")
        if root["version"] != NBA_MANAGER_PROFILE_SET_VERSION:
            raise NBAManagerStudyError("unsupported NBA manager profile set")
        raw_profiles = root["profiles"]
        if not isinstance(raw_profiles, list):
            raise NBAManagerStudyError("NBA manager profiles must be a list")
        profiles = tuple(
            ManagerProfile(**_object(item, "NBA manager profile")) for item in raw_profiles
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError) as error:
        raise NBAManagerStudyError("cannot load NBA manager profiles") from error
    result = {item.team_id: item for item in profiles}
    if len(result) != len(profiles) or set(result) != set(team_ids):
        raise NBAManagerStudyError("NBA manager profiles differ from franchise teams")
    return result


def build_nba_manager_study_bundle(
    *,
    experiment_id: str,
    initial_checkpoint: str | Path,
    state_build_receipt_path: str | Path,
    schema_path: str | Path,
    parameters_path: str | Path,
    shot_profiles_path: str | Path,
    macro_reference_path: str | Path,
    manager_profiles_path: str | Path,
    master_seeds: tuple[int, ...],
    focal_team_ids: tuple[str, ...] | None = None,
    seasons: int = 5,
    formal_run: bool = True,
    game_config: GameClockConfig | None = None,
) -> NBAManagerStudyBundle:
    checkpoint = Path(initial_checkpoint).resolve()
    state_receipt = Path(state_build_receipt_path).resolve()
    schema = Path(schema_path).resolve()
    parameters_file = Path(parameters_path).resolve()
    shots = Path(shot_profiles_path).resolve()
    macro = Path(macro_reference_path).resolve()
    managers = Path(manager_profiles_path).resolve()
    state, contract_rules, _ = load_nba_franchise_checkpoint(checkpoint)
    try:
        receipt_root = _object(
            json.loads(state_receipt.read_text(encoding="utf-8")),
            "NBA manager state-build receipt",
        )
        build_receipt = _object(receipt_root["build"], "NBA manager state-build result")
        if formal_run and build_receipt.get("formal_source_eligible") is not True:
            raise NBAManagerStudyError("formal NBA manager study requires eligible source coverage")
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, KeyError) as error:
        raise NBAManagerStudyError("cannot load NBA manager state-build receipt") from error
    team_ids = tuple(roster.team_id for roster in state.management.rosters)
    profiles = load_nba_manager_profiles(managers, team_ids)
    active_game_config = game_config or GameClockConfig(4, 720, 24, 300, 8, True)
    draft_rules = DraftRules(rounds=2, rookie_salary=contract_rules.minimum_salary)
    career_rules = CareerRules()
    scouting_rules = ScoutingRules()
    season_config = SeasonConfig()
    rotation_rules = ManagerRotationRules()
    trade_rules = TradeRules()
    manager_trade_rules = ManagerTradeRules()
    trade_market_rules = TradeMarketRules(
        maximum_candidates_per_pair=4,
        maximum_round_three_candidates=2,
        maximum_contract_condition_candidates=2,
    )
    three_team_market_rules = ThreeTeamMarketRules(
        maximum_candidates_per_trio=2,
        maximum_trios=128,
        maximum_cyclic_candidates_per_trio=1,
        maximum_hub_candidates_per_trio=1,
        maximum_compensation_picks=1,
    )
    shot_profiles = load_nba_shot_profile_set(shots)
    model_parameters = load_model_parameters(schema, parameters_file)
    source_hashes = tuple(
        sorted(
            (
                ("initial_checkpoint", sha256_file(checkpoint)),
                ("macro_reference", sha256_file(macro)),
                ("manager_profiles", sha256_file(managers)),
                ("model_parameters", sha256_file(parameters_file)),
                ("model_schema", sha256_file(schema)),
                ("shot_profiles", sha256_file(shots)),
                ("state_build_receipt", sha256_file(state_receipt)),
            )
        )
    )
    configuration: dict[str, object] = {
        "version": NBA_MANAGER_STUDY_CONFIG_VERSION,
        "model_parameter_hash": model_parameters.parameter_hash,
        "game_config": asdict(active_game_config),
        "career_rules": asdict(career_rules),
        "contract_rules": asdict(contract_rules),
        "draft_rules": asdict(draft_rules),
        "scouting_rules": asdict(scouting_rules),
        "season_config": asdict(season_config),
        "rotation_rules": asdict(rotation_rules),
        "trade_rules": asdict(trade_rules),
        "manager_trade_rules": asdict(manager_trade_rules),
        "trade_market_rules": asdict(trade_market_rules),
        "three_team_market_rules": asdict(three_team_market_rules),
        "manager_profiles": {team_id: asdict(profile) for team_id, profile in profiles.items()},
        "trace_mode": TraceMode.AGGREGATE_ONLY.name,
        "minimum_roster_players": 12,
        "source_hashes": dict(source_hashes),
    }
    initial_payload = nba_franchise_state_to_json(state, contract_rules)
    selected_focal_teams = focal_team_ids or team_ids[: len(master_seeds)]
    spec = NBAManagerExperimentSpec(
        experiment_id,
        REALITY_BASELINE_POLICY_ID,
        WHITE_BOX_CANDIDATE_POLICY_ID,
        master_seeds,
        selected_focal_teams,
        state.management.season_year,
        seasons,
        team_ids,
        hashlib.sha256(initial_payload.encode("utf-8")).hexdigest(),
        source_hashes,
        nba_manager_execution_config_sha256(configuration),
        formal_run=formal_run,
    )
    adapter = NBAFrontOfficeExperimentAdapter(
        model_parameters,
        active_game_config,
        profiles,
        contract_rules,
        draft_rules,
        career_rules,
        scouting_rules,
        season_config,
        rotation_rules,
        trade_rules=trade_rules,
        manager_trade_rules=manager_trade_rules,
        trade_market_rules=trade_market_rules,
        three_team_market_rules=three_team_market_rules,
        shot_zone_profiles=shot_profiles,
        macro_ranges=load_macro_metric_ranges(macro),
    )
    return NBAManagerStudyBundle(
        spec,
        initial_payload,
        adapter,
        configuration,
        source_hashes,
    )


def _object(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise NBAManagerStudyError(f"{label} must be an object")
    return cast(dict[str, Any], value)

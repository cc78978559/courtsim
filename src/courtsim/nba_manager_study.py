"""Frozen configuration assembly for governed NBA manager experiments."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, fields, replace
from pathlib import Path
from typing import Any, cast

from courtsim.analysis.nba_manager_state import (
    NBA_MANAGER_STATE_BUILD_VERSION,
    NBAManagerStateBuildReceipt,
)
from courtsim.analysis.nba_player_targets import (
    NBAPlayerTargetSet,
    load_nba_player_target_set,
)
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
    NBAFranchiseCheckpointReceipt,
    load_nba_franchise_checkpoint,
    nba_franchise_state_to_json,
)
from courtsim.nba_manager_adapter import (
    NBA_MANAGER_ADAPTER_VERSION,
    MacroMetricRange,
    NBAFrontOfficeExperimentAdapter,
    load_macro_metric_ranges,
)
from courtsim.nba_manager_experiment import (
    NBAManagerExperimentSpec,
    nba_manager_code_identity,
    nba_manager_execution_config_sha256,
)
from courtsim.nba_manager_protocol import (
    NBA_MANAGER_PROTOCOL_SOURCE_ROLE,
    load_nba_manager_promotion_protocol,
)
from courtsim.parameters import load_model_parameters
from courtsim.scouting import ScoutingRules
from courtsim.season import SeasonConfig
from courtsim.three_team_market import ThreeTeamMarketRules
from courtsim.trade_market import TradeMarketRules
from courtsim.trades import TradeRules

NBA_MANAGER_PROFILE_SET_VERSION = "nba-manager-profile-set-v1"
NBA_MANAGER_STUDY_CONFIG_VERSION = "nba-manager-study-config-v1"
NBA_MANAGER_STATE_BUILD_RECEIPT_VERSION = "nba-manager-state-build-receipt-v1"
NBA_MANAGER_FORMAL_GAME_CONFIG = GameClockConfig(4, 720, 24, 300, 8, True)


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


def _parse_state_build_receipt(
    root: dict[str, Any],
    *,
    initial_payload: str,
    checkpoint_receipt: NBAFranchiseCheckpointReceipt,
    season_year: int,
    rostered_players: int,
) -> NBAManagerStateBuildReceipt:
    if (
        set(root) != {"version", "build", "checkpoint"}
        or root.get("version") != NBA_MANAGER_STATE_BUILD_RECEIPT_VERSION
    ):
        raise NBAManagerStudyError("NBA manager state-build receipt root is invalid")
    build_raw = _object(root["build"], "NBA manager state-build result")
    build_fields = {item.name for item in fields(NBAManagerStateBuildReceipt)}
    if set(build_raw) != build_fields:
        raise NBAManagerStudyError("NBA manager state-build result schema differs")
    for name in (
        "proxy_age_player_ids",
        "proxy_salary_player_ids",
        "default_contract_player_ids",
        "non_bird_fallback_player_ids",
    ):
        value = build_raw[name]
        if not isinstance(value, list):
            raise NBAManagerStudyError("NBA manager state-build fallback identities are invalid")
        build_raw[name] = tuple(value)
    build = NBAManagerStateBuildReceipt(**build_raw)
    checkpoint_raw = _object(root["checkpoint"], "NBA manager checkpoint receipt")
    checkpoint_fields = {item.name for item in fields(NBAFranchiseCheckpointReceipt)}
    if set(checkpoint_raw) != checkpoint_fields:
        raise NBAManagerStudyError("NBA manager checkpoint receipt schema differs")
    stored_checkpoint = NBAFranchiseCheckpointReceipt(**checkpoint_raw)
    payload_sha256 = hashlib.sha256(initial_payload.encode("utf-8")).hexdigest()
    if (
        build.version != NBA_MANAGER_STATE_BUILD_VERSION
        or build.initial_state_sha256 != payload_sha256
        or build.initial_state_sha256 != checkpoint_receipt.state_sha256
        or build.league_id != checkpoint_receipt.league_id
        or build.season_year != season_year
        or build.rostered_players != rostered_players
        or not stored_checkpoint.checkpoint_path.strip()
        or stored_checkpoint.league_id != checkpoint_receipt.league_id
        or stored_checkpoint.completed_seasons != checkpoint_receipt.completed_seasons
        or stored_checkpoint.state_sha256 != checkpoint_receipt.state_sha256
        or stored_checkpoint.file_sha256 != checkpoint_receipt.file_sha256
        or stored_checkpoint.compression != checkpoint_receipt.compression
        or stored_checkpoint.version != checkpoint_receipt.version
    ):
        raise NBAManagerStudyError("NBA manager state-build receipt is not bound to checkpoint")
    return build


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
    player_targets_path: str | Path | None = None,
    promotion_protocol_path: str | Path | None = None,
) -> NBAManagerStudyBundle:
    checkpoint = Path(initial_checkpoint).resolve()
    state_receipt = Path(state_build_receipt_path).resolve()
    schema = Path(schema_path).resolve()
    parameters_file = Path(parameters_path).resolve()
    shots = Path(shot_profiles_path).resolve()
    macro = Path(macro_reference_path).resolve()
    managers = Path(manager_profiles_path).resolve()
    player_targets_file = (
        None if player_targets_path is None else Path(player_targets_path).resolve()
    )
    state, contract_rules, checkpoint_receipt = load_nba_franchise_checkpoint(checkpoint)
    initial_payload = nba_franchise_state_to_json(state, contract_rules)
    try:
        receipt_root = _object(
            json.loads(state_receipt.read_text(encoding="utf-8")),
            "NBA manager state-build receipt",
        )
        build_receipt = _parse_state_build_receipt(
            receipt_root,
            initial_payload=initial_payload,
            checkpoint_receipt=checkpoint_receipt,
            season_year=state.management.season_year,
            rostered_players=sum(len(roster.player_ids) for roster in state.management.rosters),
        )
        if formal_run and not build_receipt.formal_source_eligible:
            raise NBAManagerStudyError("formal NBA manager study requires eligible source coverage")
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError) as error:
        raise NBAManagerStudyError("cannot load NBA manager state-build receipt") from error
    team_ids = tuple(roster.team_id for roster in state.management.rosters)
    if formal_run and player_targets_file is None:
        raise NBAManagerStudyError("formal NBA manager study requires frozen player targets")
    player_targets: NBAPlayerTargetSet | None = None
    if player_targets_file is not None:
        loaded_targets = load_nba_player_target_set(player_targets_file)
        if loaded_targets.target_id != build_receipt.player_target_id:
            raise NBAManagerStudyError("NBA manager player targets differ from state receipt")
        roster_ids = {
            player_id for roster in state.management.rosters for player_id in roster.player_ids
        }
        target_by_id = {item.nba_player_id: item for item in loaded_targets.players}
        if not roster_ids <= set(target_by_id):
            raise NBAManagerStudyError("NBA manager player targets do not cover initial rosters")
        player_targets = replace(
            loaded_targets,
            target_id=f"{loaded_targets.target_id}:initial-roster",
            players=tuple(target_by_id[player_id] for player_id in sorted(roster_ids)),
        )
    profiles = load_nba_manager_profiles(managers, team_ids)
    active_game_config = game_config or GameClockConfig(4, 720, 24, 300, 8, True)
    if formal_run and active_game_config != NBA_MANAGER_FORMAL_GAME_CONFIG:
        raise NBAManagerStudyError("formal NBA manager study requires the frozen full-game clock")
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
    macro_ranges = tuple(
        sorted(
            (
                *load_macro_metric_ranges(macro),
                MacroMetricRange("home-win-rate", 0.47, 0.57),
                MacroMetricRange("injury-rate", 0.001, 0.008),
            ),
            key=lambda item: item.metric,
        )
    )
    optional_sources = (
        ()
        if player_targets_file is None
        else (("player_targets", sha256_file(player_targets_file)),)
    )
    input_source_hashes = tuple(
        sorted(
            (
                ("initial_checkpoint", sha256_file(checkpoint)),
                ("macro_reference", sha256_file(macro)),
                ("manager_profiles", sha256_file(managers)),
                ("model_parameters", sha256_file(parameters_file)),
                ("model_schema", sha256_file(schema)),
                ("shot_profiles", sha256_file(shots)),
                ("state_build_receipt", sha256_file(state_receipt)),
                *optional_sources,
            )
        )
    )
    configuration: dict[str, object] = {
        "version": NBA_MANAGER_STUDY_CONFIG_VERSION,
        "adapter_version": NBA_MANAGER_ADAPTER_VERSION,
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
        "player_target_id": None if player_targets is None else player_targets.target_id,
        "partial_player_target_fallback": player_targets is not None,
        "macro_ranges": [asdict(item) for item in macro_ranges],
        "source_hashes": dict(input_source_hashes),
    }
    execution_config_sha256 = nba_manager_execution_config_sha256(configuration)
    source_hashes = input_source_hashes
    if formal_run:
        if promotion_protocol_path is None:
            raise NBAManagerStudyError("formal NBA manager study requires the frozen protocol")
        protocol_path = Path(promotion_protocol_path).resolve()
        protocol = load_nba_manager_promotion_protocol(protocol_path)
        proposed_macro_ranges = tuple(
            (item.metric, item.minimum, item.maximum) for item in macro_ranges
        )
        if (
            protocol.experiment_id != experiment_id
            or protocol.start_season != state.management.season_year
            or protocol.initial_state_sha256
            != hashlib.sha256(initial_payload.encode("utf-8")).hexdigest()
            or protocol.source_hashes != input_source_hashes
            or protocol.execution_config_sha256 != execution_config_sha256
            or protocol.macro_ranges != proposed_macro_ranges
            or protocol.team_ids != team_ids
            or protocol.master_seeds != master_seeds
            or protocol.focal_team_ids != (focal_team_ids or team_ids)
            or protocol.seasons != seasons
        ):
            raise NBAManagerStudyError("formal NBA manager study differs from frozen protocol")
        source_hashes = tuple(
            sorted(
                (
                    *input_source_hashes,
                    (NBA_MANAGER_PROTOCOL_SOURCE_ROLE, sha256_file(protocol_path)),
                )
            )
        )
    code_commit, code_tree_sha256 = nba_manager_code_identity(require_clean=formal_run)
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
        execution_config_sha256,
        tuple((item.metric, item.minimum, item.maximum) for item in macro_ranges),
        code_commit,
        code_tree_sha256,
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
        player_targets=player_targets,
        macro_ranges=macro_ranges,
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

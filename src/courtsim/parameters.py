"""Strict stdlib-only loading for the demo-v1 model contract and numbers."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, NoReturn, cast

from courtsim.domain.enums import (
    Coverage,
    CreationMode,
    FinisherRoute,
    PlayFamily,
    ShotZone,
    TurnoverKind,
)
from courtsim.domain.plans import (
    LEGAL_COVERAGES_BY_PLAY,
    LEGAL_ROUTES_BY_PLAY,
    LEGAL_ZONES_BY_ROUTE,
)

TERMINAL_CLASSES = (
    "SHOT_OPPORTUNITY",
    *(f"TO_{kind.name}" for kind in TurnoverKind),
)
CONTEST_CLASSES = ("BLOCK", "HEAVY_CONTEST", "NORMAL")

EXPECTED_NODE_CONTRACTS: dict[
    str, tuple[str, tuple[str, ...], frozenset[str], dict[str, float]]
] = {
    "play_selection": (
        "centered_softmax",
        tuple(play.name for play in PlayFamily),
        frozenset(),
        {},
    ),
    "participant_selection": (
        "player_hazard",
        ("PLAYER_HAZARD",),
        frozenset(),
        {},
    ),
    "defense_response": (
        "conditional_softmax",
        tuple(coverage.name for coverage in Coverage),
        frozenset(),
        {},
    ),
    "terminal_competing_risk": (
        "centered_softmax",
        TERMINAL_CLASSES,
        frozenset(
            {
                "interaction.ball_pressure",
                "interaction.pass_release",
                "handler.ball_security",
                "handler.offensive_decision",
                "handler.pass_risk",
                "team.steal_pressure",
            }
        ),
        {},
    ),
    "finisher_route": (
        "centered_softmax",
        tuple(route.name for route in FinisherRoute),
        frozenset({"candidate.availability"}),
        {"candidate.availability": 1.0},
    ),
    "shot_zone": (
        "centered_softmax",
        tuple(zone.name for zone in ShotZone),
        frozenset({"finisher.zone_tendency"}),
        {"finisher.zone_tendency": 0.75},
    ),
    "contest_gate": (
        "centered_softmax",
        CONTEST_CLASSES,
        frozenset({"block_candidate.rim_protection", "block_candidate.block_chase"}),
        {},
    ),
    "shot_make": (
        "binary_logit",
        ("MISS", "MAKE"),
        frozenset({"shooter.zone_skill"}),
        {},
    ),
    "assist_resolution": (
        "conditional_binary_with_player_hazard",
        ("NO_ASSIST", "ASSIST"),
        frozenset(
            {
                "candidate.playmaking",
                "candidate.offensive_decision",
            }
        ),
        {},
    ),
    "shooting_foul": (
        "conditional_binary_with_player_hazard",
        ("NO_FOUL", "FOUL"),
        frozenset(
            {
                "shooter.foul_drawing",
                "shooter.contact_seek",
                "defender.foul_discipline",
            }
        ),
        {},
    ),
    "non_shooting_foul": (
        "conditional_binary_with_player_hazard",
        ("NO_FOUL", "FOUL"),
        frozenset(
            {
                "handler.foul_drawing",
                "handler.contact_seek",
                "interaction.ball_pressure",
                "defender.foul_discipline",
            }
        ),
        {},
    ),
    "free_throw_make": (
        "binary_logit",
        ("MISS", "MAKE"),
        frozenset({"shooter.free_throw_shooting"}),
        {},
    ),
    "rebound_side": (
        "binary_logit",
        ("DEFENSE", "OFFENSE"),
        frozenset(),
        {},
    ),
    "steal_hazard": (
        "player_hazard",
        ("PLAYER_HAZARD",),
        frozenset({"defender.steal_skill", "defender.steal_gamble"}),
        {},
    ),
    "rebound_hazard": (
        "player_hazard",
        ("PLAYER_HAZARD",),
        frozenset(
            {
                "player.rebound_ability",
                "player.rebound_commitment",
                "event.rebound_context",
            }
        ),
        {},
    ),
    "interaction": (
        "deterministic_interaction",
        (
            "creator_edge",
            "ball_pressure",
            "pass_release",
            "rim_access",
            "rim_help",
        ),
        frozenset(
            {
                "initiator.perimeter_creation",
                "initiator.playmaking",
                "screener.screen_setting",
                "target.off_ball_movement",
                "primary.point_of_attack_defense",
                "target_defender.defensive_awareness",
                "helper.defensive_awareness",
                "size.switch_context",
            }
        ),
        {},
    ),
}
ASSIST_V17_CONTRACT: tuple[
    str,
    tuple[str, ...],
    frozenset[str],
    dict[str, float],
] = (
    "conditional_binary_with_player_hazard",
    ("NO_ASSIST", "ASSIST"),
    frozenset(
        {
            "candidate.playmaking",
            "candidate.offensive_decision",
            "passer.playmaking",
            "passer.offensive_decision",
        }
    ),
    {},
)
POSSESSION_DURATION_V18_CONTRACT: tuple[
    str,
    tuple[str, ...],
    frozenset[str],
    dict[str, float],
] = (
    "tempo_duration_softmax",
    ("SHORT", "STANDARD", "LONG"),
    frozenset({"team.tempo"}),
    {},
)
POSSESSION_DURATION_V19_CONTRACT: tuple[
    str,
    tuple[str, ...],
    frozenset[str],
    dict[str, float],
] = (
    "contextual_tempo_duration_softmax",
    ("SHORT", "STANDARD", "LONG"),
    frozenset(
        {
            "team.tempo",
            "game.period",
            "game.clock_seconds",
            "game.score_margin",
        }
    ),
    {},
)
LATE_GAME_STRATEGY_V110_CONTRACT: tuple[
    str,
    tuple[str, ...],
    frozenset[str],
    dict[str, float],
] = (
    "deterministic_state_machine",
    (
        "OFFENSE_STANDARD",
        "OFFENSE_COMEBACK",
        "OFFENSE_PROTECT_LEAD",
        "OFFENSE_TWO_FOR_ONE",
        "DEFENSE_STANDARD",
        "DEFENSE_INTENTIONAL_FOUL",
    ),
    frozenset(
        {
            "game.period",
            "game.clock_seconds",
            "game.score_margin",
            "game.possession_side",
        }
    ),
    {},
)


class ParameterError(ValueError):
    pass


def _fail(message: str) -> NoReturn:
    raise ParameterError(message)


def _node_contracts(
    schema_version: str,
) -> dict[str, tuple[str, tuple[str, ...], frozenset[str], dict[str, float]]]:
    if schema_version == "demo-v1.3":
        return {
            name: contract
            for name, contract in EXPECTED_NODE_CONTRACTS.items()
            if name
            not in {
                "assist_resolution",
                "shooting_foul",
                "non_shooting_foul",
                "free_throw_make",
            }
        }
    if schema_version == "demo-v1.4":
        return {
            name: contract
            for name, contract in EXPECTED_NODE_CONTRACTS.items()
            if name not in {"shooting_foul", "non_shooting_foul", "free_throw_make"}
        }
    if schema_version == "demo-v1.5":
        return {
            name: contract
            for name, contract in EXPECTED_NODE_CONTRACTS.items()
            if name != "non_shooting_foul"
        }
    if schema_version == "demo-v1.6":
        return EXPECTED_NODE_CONTRACTS
    if schema_version == "demo-v1.7":
        return {
            **EXPECTED_NODE_CONTRACTS,
            "assist_resolution": ASSIST_V17_CONTRACT,
        }
    if schema_version == "demo-v1.8":
        return {
            **EXPECTED_NODE_CONTRACTS,
            "assist_resolution": ASSIST_V17_CONTRACT,
            "possession_duration": POSSESSION_DURATION_V18_CONTRACT,
        }
    if schema_version == "demo-v1.9":
        return {
            **EXPECTED_NODE_CONTRACTS,
            "assist_resolution": ASSIST_V17_CONTRACT,
            "possession_duration": POSSESSION_DURATION_V19_CONTRACT,
        }
    if schema_version == "demo-v1.10":
        return {
            **EXPECTED_NODE_CONTRACTS,
            "assist_resolution": ASSIST_V17_CONTRACT,
            "possession_duration": POSSESSION_DURATION_V19_CONTRACT,
            "late_game_strategy": LATE_GAME_STRATEGY_V110_CONTRACT,
        }
    if schema_version == "demo-v1.11":
        return {
            **EXPECTED_NODE_CONTRACTS,
            "assist_resolution": ASSIST_V17_CONTRACT,
            "possession_duration": POSSESSION_DURATION_V19_CONTRACT,
            "late_game_strategy": LATE_GAME_STRATEGY_V110_CONTRACT,
        }
    if schema_version == "demo-v1.12":
        return {
            **EXPECTED_NODE_CONTRACTS,
            "assist_resolution": ASSIST_V17_CONTRACT,
            "possession_duration": POSSESSION_DURATION_V19_CONTRACT,
            "late_game_strategy": LATE_GAME_STRATEGY_V110_CONTRACT,
        }
    _fail(f"unsupported schema_version: {schema_version}")


def _object(value: object, field: str) -> dict[str, Any]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        _fail(f"{field} must be an object")
    return cast(dict[str, Any], value)


def _exact(obj: dict[str, Any], keys: set[str], field: str) -> None:
    if set(obj) != keys:
        _fail(f"{field} keys must be exactly {sorted(keys)}")


def _string(obj: dict[str, Any], key: str) -> str:
    value = obj[key]
    if not isinstance(value, str):
        _fail(f"{key} must be a string")
    return value


def _number(value: object, field: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        _fail(f"{field} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        _fail(f"{field} must be finite")
    return result


def _probability_vector(value: object, expected: frozenset[str], field: str) -> dict[str, float]:
    obj = _object(value, field)
    if set(obj) != set(expected):
        _fail(f"{field} classes do not match the structural contract")
    probabilities = {key: _number(item, f"{field}.{key}") for key, item in obj.items()}
    if len(probabilities) == 1:
        if next(iter(probabilities.values())) != 1.0:
            _fail(f"{field} deterministic probability must equal one")
    elif any(probability <= 0.0 or probability >= 1.0 for probability in probabilities.values()):
        _fail(f"{field} probabilities must be strictly between zero and one")
    if not math.isclose(math.fsum(probabilities.values()), 1.0, abs_tol=1e-12):
        _fail(f"{field} probabilities must sum to one")
    return probabilities


@dataclass(frozen=True, slots=True)
class ParameterValue:
    value: float
    lower: float
    upper: float
    trainable: bool


def _parameter_value(value: object, field: str) -> ParameterValue:
    obj = _object(value, field)
    _exact(obj, {"value", "lower", "upper", "trainable"}, field)
    parameter = ParameterValue(
        _number(obj["value"], f"{field}.value"),
        _number(obj["lower"], f"{field}.lower"),
        _number(obj["upper"], f"{field}.upper"),
        bool(obj["trainable"]) if isinstance(obj["trainable"], bool) else _fail("trainable"),
    )
    if parameter.lower > parameter.upper:
        _fail(f"{field} lower must not exceed upper")
    if not parameter.lower <= parameter.value <= parameter.upper:
        _fail(f"{field} value is outside its bounds")
    if max(abs(parameter.lower), abs(parameter.upper)) > 2.0:
        _fail(f"{field} exceeds the absolute coefficient safety bound")
    return parameter


@dataclass(frozen=True, slots=True)
class ModelSchema:
    schema_version: str
    rng_schema_version: int
    schema_hash: str
    finisher_availability_loading: float
    zone_tendency_loading: float
    has_assist_resolution: bool
    has_shooting_fouls: bool
    has_non_shooting_fouls: bool


@dataclass(frozen=True, slots=True)
class ModelParameters:
    schema: ModelSchema
    payload: Mapping[str, Any]
    parameter_hash: str


def _canonical_hash(payload: object) -> str:
    def clean(value: object) -> object:
        if isinstance(value, float):
            return round(value, 9)
        if isinstance(value, dict):
            return {
                key: clean(item)
                for key, item in value.items()
                if key not in {"parameter_hash", "created_at_utc", "notes"}
            }
        if isinstance(value, list):
            return [clean(item) for item in value]
        return value

    encoded = json.dumps(
        clean(payload),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _freeze(value: object) -> object:
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return value


def _read_json(path: str | Path) -> dict[str, Any]:
    try:
        value: object = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ParameterError(f"cannot load {path}") from error
    return _object(value, str(path))


def load_model_schema(path: str | Path) -> ModelSchema:
    payload = _read_json(path)
    _exact(
        payload,
        {"schema_version", "rng_schema_version", "nodes", "dormant_features"},
        "model schema",
    )
    schema_version = _string(payload, "schema_version")
    contracts = _node_contracts(schema_version)
    if payload["rng_schema_version"] != 1:
        _fail("unsupported rng_schema_version")
    nodes = _object(payload["nodes"], "nodes")
    if set(nodes) != set(contracts):
        _fail("schema nodes do not match engine contract")
    for name, (
        expected_type,
        expected_classes,
        allowed_features,
        fixed_loadings,
    ) in contracts.items():
        node = _object(nodes[name], f"nodes.{name}")
        _exact(
            node,
            {
                "model_type",
                "classes",
                "allowed_features",
                "fixed_feature_loadings",
            },
            f"nodes.{name}",
        )
        if node["model_type"] != expected_type:
            _fail(f"{name} model_type does not match engine contract")
        if node["classes"] != list(expected_classes):
            _fail(f"{name} classes do not match engine contract")
        if set(cast(list[object], node["allowed_features"])) != set(allowed_features):
            _fail(f"{name} allowed_features do not match engine contract")
        actual_loadings = _object(
            node["fixed_feature_loadings"], f"nodes.{name}.fixed_feature_loadings"
        )
        parsed_loadings = {
            feature: _number(value, f"nodes.{name}.fixed_feature_loadings.{feature}")
            for feature, value in actual_loadings.items()
        }
        if parsed_loadings != fixed_loadings:
            _fail(f"{name} fixed feature loadings do not match engine contract")
    dormant = payload["dormant_features"]
    if not isinstance(dormant, list) or not all(isinstance(item, str) for item in dormant):
        _fail("dormant_features must be a string list")
    return ModelSchema(
        schema_version,
        cast(int, payload["rng_schema_version"]),
        _canonical_hash(payload),
        1.0,
        0.75,
        "assist_resolution" in contracts,
        "shooting_foul" in contracts,
        "non_shooting_foul" in contracts,
    )


def _validate_base_tables(nodes: dict[str, Any], schema_version: str) -> None:
    play_selection = _object(nodes["play_selection"], "play_selection")
    participant_selection = _object(nodes["participant_selection"], "participant_selection")
    defense_response = _object(nodes["defense_response"], "defense_response")
    terminal = _object(nodes["terminal_competing_risk"], "terminal_competing_risk")
    route = _object(nodes["finisher_route"], "finisher_route")
    zone = _object(nodes["shot_zone"], "shot_zone")
    contest = _object(nodes["contest_gate"], "contest_gate")
    make = _object(nodes["shot_make"], "shot_make")
    assist = (
        _object(nodes["assist_resolution"], "assist_resolution")
        if "assist_resolution" in nodes
        else None
    )
    shooting_foul = (
        _object(nodes["shooting_foul"], "shooting_foul") if "shooting_foul" in nodes else None
    )
    non_shooting_foul = (
        _object(nodes["non_shooting_foul"], "non_shooting_foul")
        if "non_shooting_foul" in nodes
        else None
    )
    free_throw_make = (
        _object(nodes["free_throw_make"], "free_throw_make") if "free_throw_make" in nodes else None
    )
    rebound = _object(nodes["rebound_side"], "rebound_side")
    steal_hazard = _object(nodes["steal_hazard"], "steal_hazard")
    rebound_hazard = _object(nodes["rebound_hazard"], "rebound_hazard")
    interaction = _object(nodes["interaction"], "interaction")
    possession_duration = (
        _object(nodes["possession_duration"], "possession_duration")
        if "possession_duration" in nodes
        else None
    )
    late_game_strategy = (
        _object(nodes["late_game_strategy"], "late_game_strategy")
        if "late_game_strategy" in nodes
        else None
    )

    _exact(play_selection, {"base_probabilities"}, "play_selection")
    _probability_vector(
        play_selection["base_probabilities"],
        frozenset(play.name for play in PlayFamily),
        "play_selection.base_probabilities",
    )
    _exact(
        participant_selection,
        {
            "involvement_coefficient",
            "role_preference_coefficient",
            "offball_no_screen_probability",
        },
        "participant_selection",
    )
    for field in ("involvement_coefficient", "role_preference_coefficient"):
        value = _number(participant_selection[field], f"participant_selection.{field}")
        if not 0.0 <= value <= 1.0:
            _fail(f"participant_selection.{field} must be between zero and one")
    no_screen = _number(
        participant_selection["offball_no_screen_probability"],
        "participant_selection.offball_no_screen_probability",
    )
    if not 0.0 < no_screen < 1.0:
        _fail("offball_no_screen_probability must be strictly between zero and one")
    _exact(
        defense_response,
        {"base_probabilities", "help_aggression_effect"},
        "defense_response",
    )
    response_bases = _object(
        defense_response["base_probabilities"], "defense_response.base_probabilities"
    )
    expected_response_contexts = {
        PlayFamily.BALL_SCREEN.name,
        PlayFamily.ISOLATION.name,
        PlayFamily.OFF_BALL_ACTION.name,
        f"{PlayFamily.OFF_BALL_ACTION.name}|WITH_SCREEN",
    }
    if set(response_bases) != expected_response_contexts:
        _fail("defense response contexts do not match the structural contract")
    response_classes = {
        PlayFamily.BALL_SCREEN.name: LEGAL_COVERAGES_BY_PLAY[PlayFamily.BALL_SCREEN],
        PlayFamily.ISOLATION.name: LEGAL_COVERAGES_BY_PLAY[PlayFamily.ISOLATION],
        PlayFamily.OFF_BALL_ACTION.name: frozenset({Coverage.BASE}),
        f"{PlayFamily.OFF_BALL_ACTION.name}|WITH_SCREEN": LEGAL_COVERAGES_BY_PLAY[
            PlayFamily.OFF_BALL_ACTION
        ],
    }
    for context, coverages in response_classes.items():
        _probability_vector(
            response_bases[context],
            frozenset(coverage.name for coverage in coverages),
            f"defense_response.{context}",
        )
    help_effect = _object(
        defense_response["help_aggression_effect"],
        "defense_response.help_aggression_effect",
    )
    if set(help_effect) != {coverage.name for coverage in Coverage}:
        _fail("help aggression effects must cover every coverage")
    for coverage, raw_value in help_effect.items():
        if abs(_number(raw_value, f"help_aggression_effect.{coverage}")) > 0.8:
            _fail(f"help aggression effect {coverage} exceeds 0.8")

    for node, name in (
        (terminal, "terminal_competing_risk"),
        (route, "finisher_route"),
        (zone, "shot_zone"),
        (contest, "contest_gate"),
    ):
        _exact(node, {"base_probabilities", "feature_weights"}, name)

    terminal_base = _object(terminal["base_probabilities"], "terminal base")
    route_base = _object(route["base_probabilities"], "route base")
    if set(terminal_base) != {play.name for play in PlayFamily}:
        _fail("terminal base contexts must cover every play")
    if set(route_base) != {play.name for play in PlayFamily}:
        _fail("route base contexts must cover every play")
    for play in PlayFamily:
        _probability_vector(
            terminal_base[play.name], frozenset(TERMINAL_CLASSES), f"terminal.{play.name}"
        )
        _probability_vector(
            route_base[play.name],
            frozenset(route.name for route in LEGAL_ROUTES_BY_PLAY[play]),
            f"route.{play.name}",
        )

    zone_base = _object(zone["base_probabilities"], "zone base")
    expected_zone_contexts = {
        f"{play.name}|{route.name}" for play in PlayFamily for route in LEGAL_ROUTES_BY_PLAY[play]
    }
    if set(zone_base) != expected_zone_contexts:
        _fail("zone base contexts do not match legal play-route combinations")
    for context, vector in zone_base.items():
        route_name = context.split("|", maxsplit=1)[1]
        route_id = FinisherRoute[route_name]
        _probability_vector(
            vector,
            frozenset(zone.name for zone in LEGAL_ZONES_BY_ROUTE[route_id]),
            f"zone.{context}",
        )

    contest_base = _object(contest["base_probabilities"], "contest base")
    if set(contest_base) != {zone.name for zone in ShotZone}:
        _fail("contest base must cover every zone")
    for shot_zone in ShotZone:
        _probability_vector(
            contest_base[shot_zone.name],
            frozenset(CONTEST_CLASSES),
            f"contest.{shot_zone.name}",
        )

    _exact(
        make,
        {
            "base_make_probability",
            "heavy_contest_offset",
            "zone_skill_coefficient",
        },
        "shot_make",
    )
    for field in (
        "base_make_probability",
        "heavy_contest_offset",
        "zone_skill_coefficient",
    ):
        table = _object(make[field], f"shot_make.{field}")
        if set(table) != {zone.name for zone in ShotZone}:
            _fail(f"shot_make.{field} must cover every zone")
        for key, value in table.items():
            numeric = _number(value, f"shot_make.{field}.{key}")
            if field == "base_make_probability" and not 0.0 < numeric < 1.0:
                _fail("base make probabilities must be strictly between zero and one")
            if field == "zone_skill_coefficient" and not 0.0 <= numeric <= 0.8:
                _fail("zone skill coefficients must be between zero and 0.8")
    if assist is not None:
        assist_fields = {
            "base_probability_by_creation_mode",
            "assister_playmaking_coefficient",
            "assister_decision_coefficient",
        }
        if schema_version in {
            "demo-v1.7",
            "demo-v1.8",
            "demo-v1.9",
            "demo-v1.10",
            "demo-v1.11",
            "demo-v1.12",
        }:
            assist_fields |= {
                "occurrence_logit_intercept",
                "occurrence_playmaking_coefficient",
                "occurrence_decision_coefficient",
            }
        _exact(
            assist,
            assist_fields,
            "assist_resolution",
        )
        assist_bases = _object(
            assist["base_probability_by_creation_mode"],
            "assist_resolution.base_probability_by_creation_mode",
        )
        if set(assist_bases) != {mode.name for mode in CreationMode}:
            _fail("assist base probabilities must cover every creation mode")
        for mode, raw_probability in assist_bases.items():
            probability = _number(raw_probability, f"assist_resolution.{mode}")
            if not 0.0 < probability < 1.0:
                _fail("assist base probabilities must be strictly between zero and one")
        for field in (
            "assister_playmaking_coefficient",
            "assister_decision_coefficient",
        ):
            coefficient = _number(assist[field], f"assist_resolution.{field}")
            if not 0.0 <= coefficient <= 0.8:
                _fail(f"assist_resolution.{field} must be between zero and 0.8")
        if schema_version in {
            "demo-v1.7",
            "demo-v1.8",
            "demo-v1.9",
            "demo-v1.10",
            "demo-v1.11",
            "demo-v1.12",
        }:
            intercept = _number(
                assist["occurrence_logit_intercept"],
                "assist_resolution.occurrence_logit_intercept",
            )
            if abs(intercept) > 0.8:
                _fail("assist_resolution.occurrence_logit_intercept must be between -0.8 and 0.8")
            for field in (
                "occurrence_playmaking_coefficient",
                "occurrence_decision_coefficient",
            ):
                coefficient = _number(assist[field], f"assist_resolution.{field}")
                if not 0.0 <= coefficient <= 0.8:
                    _fail(f"assist_resolution.{field} must be between zero and 0.8")
    if possession_duration is not None:
        duration_fields = {
            "durations_seconds",
            "base_probabilities",
            "tempo_coefficient",
        }
        if schema_version in {
            "demo-v1.9",
            "demo-v1.10",
            "demo-v1.11",
            "demo-v1.12",
        }:
            duration_fields.add("late_game_adjustments")
        _exact(
            possession_duration,
            duration_fields,
            "possession_duration",
        )
        durations = _object(
            possession_duration["durations_seconds"],
            "possession_duration.durations_seconds",
        )
        expected_duration_classes = frozenset({"SHORT", "STANDARD", "LONG"})
        if set(durations) != expected_duration_classes:
            _fail("possession durations must cover SHORT, STANDARD, and LONG")
        parsed_durations: dict[str, int] = {}
        for class_name, raw_duration in durations.items():
            if (
                not isinstance(raw_duration, int)
                or isinstance(raw_duration, bool)
                or raw_duration < 1
            ):
                _fail(f"possession_duration.{class_name} must be a positive integer")
            parsed_durations[class_name] = raw_duration
        if not (
            parsed_durations["SHORT"] < parsed_durations["STANDARD"] < parsed_durations["LONG"]
        ):
            _fail("possession durations must be strictly ordered")
        _probability_vector(
            possession_duration["base_probabilities"],
            expected_duration_classes,
            "possession_duration.base_probabilities",
        )
        tempo_coefficient = _number(
            possession_duration["tempo_coefficient"],
            "possession_duration.tempo_coefficient",
        )
        if not 0.0 <= tempo_coefficient <= 0.8:
            _fail("possession_duration.tempo_coefficient must be between zero and 0.8")
        if schema_version in {
            "demo-v1.9",
            "demo-v1.10",
            "demo-v1.11",
            "demo-v1.12",
        }:
            late_game = _object(
                possession_duration["late_game_adjustments"],
                "possession_duration.late_game_adjustments",
            )
            _exact(
                late_game,
                {
                    "window_seconds",
                    "margin_threshold",
                    "trailing_tempo_delta",
                    "leading_tempo_delta",
                },
                "possession_duration.late_game_adjustments",
            )
            for field in ("window_seconds", "margin_threshold"):
                value = late_game[field]
                if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                    _fail(f"late_game_adjustments.{field} must be a positive integer")
            if late_game["window_seconds"] > 300:
                _fail("late-game tempo window must not exceed 300 seconds")
            if late_game["margin_threshold"] > 30:
                _fail("late-game tempo margin threshold must not exceed 30")
            trailing_delta = late_game["trailing_tempo_delta"]
            leading_delta = late_game["leading_tempo_delta"]
            for field, value in (
                ("trailing_tempo_delta", trailing_delta),
                ("leading_tempo_delta", leading_delta),
            ):
                if not isinstance(value, int) or isinstance(value, bool) or not -30 <= value <= 30:
                    _fail(f"late_game_adjustments.{field} must be within [-30, 30]")
            if trailing_delta <= 0 or leading_delta >= 0:
                _fail("late-game trailing delta must be positive and leading delta negative")
    if late_game_strategy is not None:
        strategy_fields = {
            "two_for_one_window_start_seconds",
            "two_for_one_window_end_seconds",
            "two_for_one_max_abs_margin",
            "two_for_one_tempo_delta",
            "intentional_foul_window_seconds",
            "intentional_foul_min_trailing_margin",
            "intentional_foul_max_trailing_margin",
        }
        if schema_version in {"demo-v1.11", "demo-v1.12"}:
            strategy_fields.add("intentional_foul_clock_seconds")
        if schema_version == "demo-v1.12":
            strategy_fields.add("intentional_foul_non_bonus_enabled")
        _exact(late_game_strategy, strategy_fields, "late_game_strategy")
        parsed_strategy: dict[str, int] = {}
        integer_strategy_fields = strategy_fields - {"intentional_foul_non_bonus_enabled"}
        for field in integer_strategy_fields:
            value = late_game_strategy[field]
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                _fail(f"late_game_strategy.{field} must be a non-negative integer")
            parsed_strategy[field] = value
        if not (
            0
            < parsed_strategy["two_for_one_window_start_seconds"]
            < parsed_strategy["two_for_one_window_end_seconds"]
            <= 60
        ):
            _fail("two-for-one window must be ordered within the final 60 seconds")
        if not 1 <= parsed_strategy["two_for_one_tempo_delta"] <= 30:
            _fail("two-for-one tempo delta must be within [1, 30]")
        if parsed_strategy["two_for_one_max_abs_margin"] > 10:
            _fail("two-for-one maximum margin must not exceed 10")
        if not 1 <= parsed_strategy["intentional_foul_window_seconds"] <= 60:
            _fail("intentional foul window must be within the final 60 seconds")
        if not (
            1
            <= parsed_strategy["intentional_foul_min_trailing_margin"]
            <= parsed_strategy["intentional_foul_max_trailing_margin"]
            <= 15
        ):
            _fail("intentional foul margin range is invalid")
        if schema_version in {"demo-v1.11", "demo-v1.12"} and not (
            1 <= parsed_strategy["intentional_foul_clock_seconds"] <= 10
        ):
            _fail("intentional foul clock seconds must be within [1, 10]")
        if (
            schema_version == "demo-v1.12"
            and late_game_strategy["intentional_foul_non_bonus_enabled"] is not True
        ):
            _fail("intentional_foul_non_bonus_enabled must be true")
    if shooting_foul is not None:
        _exact(
            shooting_foul,
            {
                "base_probability_by_zone",
                "heavy_contest_logit_offset",
                "foul_drawing_coefficient",
                "contact_seek_coefficient",
                "fouler_discipline_coefficient",
            },
            "shooting_foul",
        )
        foul_bases = _object(
            shooting_foul["base_probability_by_zone"],
            "shooting_foul.base_probability_by_zone",
        )
        if set(foul_bases) != {zone.name for zone in ShotZone}:
            _fail("shooting foul base probabilities must cover every zone")
        for zone_name, raw_probability in foul_bases.items():
            probability = _number(
                raw_probability,
                f"shooting_foul.base_probability_by_zone.{zone_name}",
            )
            if not 0.0 < probability < 1.0:
                _fail("shooting foul base probabilities must be strictly between zero and one")
        for field in (
            "heavy_contest_logit_offset",
            "foul_drawing_coefficient",
            "contact_seek_coefficient",
            "fouler_discipline_coefficient",
        ):
            coefficient = _number(shooting_foul[field], f"shooting_foul.{field}")
            if abs(coefficient) > 0.8:
                _fail(f"shooting_foul.{field} exceeds 0.8")
    if non_shooting_foul is not None:
        _exact(
            non_shooting_foul,
            {
                "base_probability_by_play_family",
                "ball_pressure_coefficient",
                "foul_drawing_coefficient",
                "contact_seek_coefficient",
                "fouler_discipline_coefficient",
            },
            "non_shooting_foul",
        )
        foul_bases = _object(
            non_shooting_foul["base_probability_by_play_family"],
            "non_shooting_foul.base_probability_by_play_family",
        )
        if set(foul_bases) != {play.name for play in PlayFamily}:
            _fail("non-shooting foul base probabilities must cover every play family")
        for play_name, raw_probability in foul_bases.items():
            probability = _number(
                raw_probability,
                f"non_shooting_foul.base_probability_by_play_family.{play_name}",
            )
            if not 0.0 < probability < 1.0:
                _fail("non-shooting foul base probabilities must be strictly between zero and one")
        for field in (
            "ball_pressure_coefficient",
            "foul_drawing_coefficient",
            "contact_seek_coefficient",
            "fouler_discipline_coefficient",
        ):
            coefficient = _number(
                non_shooting_foul[field],
                f"non_shooting_foul.{field}",
            )
            if abs(coefficient) > 0.8:
                _fail(f"non_shooting_foul.{field} exceeds 0.8")
    if free_throw_make is not None:
        _exact(
            free_throw_make,
            {"base_make_probability", "shooting_coefficient"},
            "free_throw_make",
        )
        free_throw_base = _number(
            free_throw_make["base_make_probability"],
            "free_throw_make.base_make_probability",
        )
        if not 0.0 < free_throw_base < 1.0:
            _fail("free throw base make probability must be strictly between zero and one")
        free_throw_coefficient = _number(
            free_throw_make["shooting_coefficient"],
            "free_throw_make.shooting_coefficient",
        )
        if not 0.0 <= free_throw_coefficient <= 0.8:
            _fail("free throw shooting coefficient must be between zero and 0.8")
    _exact(rebound, {"neutral_oreb_probability"}, "rebound_side")
    oreb = _number(rebound["neutral_oreb_probability"], "neutral_oreb_probability")
    if not 0.0 < oreb < 1.0:
        _fail("neutral_oreb_probability must be strictly between zero and one")
    _exact(
        steal_hazard,
        {"skill_coefficient", "gamble_coefficient"},
        "steal_hazard",
    )
    _exact(
        rebound_hazard,
        {
            "ability_coefficient",
            "commitment_coefficient",
            "defense_context_factor",
            "shooter_context_offset",
            "blocker_context_offset",
            "blocked_oreb_offset",
        },
        "rebound_hazard",
    )
    for node_name, node in (
        ("steal_hazard", steal_hazard),
        ("rebound_hazard", rebound_hazard),
    ):
        for key, value in node.items():
            numeric = _number(value, f"{node_name}.{key}")
            if abs(numeric) > 3.0:
                _fail(f"{node_name}.{key} exceeds the structural safety bound")
    _exact(
        interaction,
        {
            "dimensions",
            "coefficients",
            "coverage_deltas",
            "favorable_switch_creator_delta",
            "unfavorable_switch_creator_delta",
        },
        "interaction",
    )
    dimensions = (
        "creator_edge",
        "ball_pressure",
        "pass_release",
        "rim_access",
        "rim_help",
    )
    if interaction["dimensions"] != list(dimensions):
        _fail("interaction dimensions do not match the structural contract")
    coefficients = _object(interaction["coefficients"], "interaction.coefficients")
    expected_coefficients = {
        "ball_screen_creator",
        "ball_screen_screen",
        "ball_screen_primary_defense",
        "isolation_creator",
        "isolation_primary_defense",
        "offball_playmaking",
        "offball_target_movement",
        "offball_target_awareness",
        "ball_pressure_primary_defense",
        "pass_release_playmaking",
        "pass_release_target_movement",
        "pass_release_help_awareness",
        "rim_access_creator",
        "rim_access_screen",
        "rim_access_primary_defense",
        "rim_access_help_awareness",
        "rim_help_awareness",
        "help_candidate_movement",
        "help_candidate_awareness",
        "primary_contest_defense",
        "primary_contest_creator_edge",
    }
    if set(coefficients) != expected_coefficients:
        _fail("interaction coefficients do not match the structural contract")
    for key, value in coefficients.items():
        if abs(_number(value, f"interaction.coefficients.{key}")) > 0.8:
            _fail(f"interaction coefficient {key} exceeds 0.8")
    deltas = _object(interaction["coverage_deltas"], "interaction.coverage_deltas")
    expected_contexts = {
        f"{play.name}|{coverage.name}"
        for play in PlayFamily
        for coverage in LEGAL_COVERAGES_BY_PLAY[play]
    }
    if set(deltas) != expected_contexts:
        _fail("interaction coverage deltas must cover every legal family combination")
    for context, value in deltas.items():
        vector = _object(value, f"interaction.coverage_deltas.{context}")
        if set(vector) != set(dimensions):
            _fail(f"interaction delta {context} has invalid dimensions")
        for dimension, raw_delta in vector.items():
            delta = _number(raw_delta, f"{context}.{dimension}")
            if abs(delta) > 0.75:
                _fail(f"interaction delta {context}.{dimension} exceeds 0.75")
        if context.endswith("|BASE") and any(
            _number(raw_delta, f"{context}.{dimension}") != 0.0
            for dimension, raw_delta in vector.items()
        ):
            _fail("all BASE interaction deltas must be zero")
    for field in (
        "favorable_switch_creator_delta",
        "unfavorable_switch_creator_delta",
    ):
        if abs(_number(interaction[field], f"interaction.{field}")) > 0.4:
            _fail(f"interaction.{field} exceeds the size-context bound")


def _validate_feature_weights(
    schema_payload: dict[str, Any],
    nodes: dict[str, Any],
    contracts: dict[str, tuple[str, tuple[str, ...], frozenset[str], dict[str, float]]],
) -> None:
    dormant = set(cast(list[str], schema_payload["dormant_features"]))
    trainable_count = 0
    for node_name, (_, classes, allowed, _) in contracts.items():
        node = _object(nodes[node_name], node_name)
        raw_weights = node.get("feature_weights", {})
        weights = _object(raw_weights, f"{node_name}.feature_weights")
        if not set(weights) <= set(allowed):
            _fail(f"{node_name} contains an unregistered feature")
        if set(weights) & dormant:
            _fail(f"{node_name} activates a dormant feature")
        for feature, raw_class_weights in weights.items():
            class_weights = _object(raw_class_weights, f"{node_name}.{feature}")
            if set(class_weights) != set(classes):
                _fail(f"{node_name}.{feature} must cover all node classes")
            values = [
                _parameter_value(value, f"{node_name}.{feature}.{class_name}")
                for class_name, value in class_weights.items()
            ]
            if not math.isclose(math.fsum(item.value for item in values), 0.0, abs_tol=1e-12):
                _fail(f"{node_name}.{feature} softmax weights must be centered")
            trainable_count += sum(item.trainable for item in values)
    if trainable_count > 30:
        _fail("demo-v1 permits at most 30 trainable scalar parameters")


def load_model_parameters(schema_path: str | Path, parameters_path: str | Path) -> ModelParameters:
    schema_payload = _read_json(schema_path)
    schema = load_model_schema(schema_path)
    contracts = _node_contracts(schema.schema_version)
    payload = _read_json(parameters_path)
    _exact(payload, {"metadata", "nodes", "rules"}, "model parameters")
    metadata = _object(payload["metadata"], "metadata")
    _exact(
        metadata,
        {
            "schema_version",
            "parameter_version",
            "rng_schema_version",
            "engine_compatibility",
            "parameter_hash",
            "created_at_utc",
            "notes",
        },
        "metadata",
    )
    if metadata["schema_version"] != schema.schema_version:
        _fail("parameter schema_version does not match schema")
    if metadata["rng_schema_version"] != schema.rng_schema_version:
        _fail("parameter rng_schema_version does not match schema")
    nodes = _object(payload["nodes"], "nodes")
    if set(nodes) != set(contracts):
        _fail("parameter nodes do not match schema")
    _validate_base_tables(nodes, schema.schema_version)
    _validate_feature_weights(schema_payload, nodes, contracts)
    rules = _object(payload["rules"], "rules")
    expected_rules = {
        "offensive_rebound_continues_possession",
        "max_action_segments_per_possession",
    }
    if schema.has_non_shooting_fouls:
        expected_rules.add("bonus_foul_threshold")
    _exact(rules, expected_rules, "rules")
    if rules["offensive_rebound_continues_possession"] is not True:
        _fail("demo-v1 requires offensive rebounds to continue the possession")
    max_segments = rules["max_action_segments_per_possession"]
    if not isinstance(max_segments, int) or isinstance(max_segments, bool) or max_segments < 1:
        _fail("max_action_segments_per_possession must be a positive integer")
    if schema.has_non_shooting_fouls:
        bonus_threshold = rules["bonus_foul_threshold"]
        if (
            not isinstance(bonus_threshold, int)
            or isinstance(bonus_threshold, bool)
            or bonus_threshold < 1
        ):
            _fail("bonus_foul_threshold must be a positive integer")

    parameter_hash = _canonical_hash(payload)
    declared_hash = metadata["parameter_hash"]
    if declared_hash is not None and declared_hash != parameter_hash:
        _fail("declared parameter_hash does not match canonical content")
    return ModelParameters(
        schema,
        cast(Mapping[str, Any], _freeze(payload)),
        parameter_hash,
    )

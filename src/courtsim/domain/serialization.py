"""Strict, stable JSON representation for canonical action-segment facts."""

import json
from collections.abc import Mapping
from typing import Any, NoReturn, cast

from courtsim.domain.enums import (
    ContestLevel,
    Coverage,
    FinisherRoute,
    FoulTeamSide,
    PlayFamily,
    PossessionEndReason,
    ShotZone,
    TechnicalFoulType,
    TurnoverKind,
)
from courtsim.domain.interaction import FinisherSelection
from courtsim.domain.plans import (
    BallScreenPlan,
    IsolationPlan,
    OffBallActionPlan,
    OffensivePlan,
    last_passer_for,
)
from courtsim.domain.results import (
    ActionSegmentResult,
    BlockedShotSegmentResult,
    DefensiveRebound,
    MadeShotSegmentResult,
    MissedShotSegmentResult,
    NonShootingFoulSegmentResult,
    OffensiveFoulSegmentResult,
    OffensiveRebound,
    PossessionResult,
    ReboundOutcome,
    ShootingFoulSegmentResult,
    StolenTurnover,
    TechnicalFoulSegmentResult,
    TurnoverOutcome,
    TurnoverSegmentResult,
    UnforcedTurnover,
    ViolationTurnover,
    offense_retains_ball,
    possession_end_reason,
)

SCHEMA_VERSION = 5


class SerializationError(ValueError):
    """The serialized structure does not match the frozen schema."""


def _fail(message: str) -> NoReturn:
    raise SerializationError(message)


def _object(value: object, field: str) -> Mapping[str, Any]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        _fail(f"{field} must be an object")
    return cast(Mapping[str, Any], value)


def _exact(obj: Mapping[str, Any], required: set[str], field: str) -> None:
    if set(obj) != required:
        _fail(f"{field} keys must be exactly {sorted(required)}")


def _int(obj: Mapping[str, Any], key: str) -> int:
    value = obj[key]
    if not isinstance(value, int) or isinstance(value, bool):
        _fail(f"{key} must be an integer")
    return value


def _nullable_int(obj: Mapping[str, Any], key: str) -> int | None:
    value = obj[key]
    if value is None:
        return None
    return _int(obj, key)


def _enum(enum_type: type[Any], obj: Mapping[str, Any], key: str) -> Any:
    try:
        return enum_type(_int(obj, key))
    except ValueError as error:
        raise SerializationError(f"invalid {key}") from error


def _plan_to_dict(plan: OffensivePlan) -> dict[str, object]:
    if isinstance(plan, BallScreenPlan):
        return {
            "family": int(PlayFamily.BALL_SCREEN),
            "handler_id": plan.handler_id,
            "screener_id": plan.screener_id,
        }
    if isinstance(plan, IsolationPlan):
        return {"family": int(PlayFamily.ISOLATION), "initiator_id": plan.initiator_id}
    return {
        "family": int(PlayFamily.OFF_BALL_ACTION),
        "passer_id": plan.passer_id,
        "target_id": plan.target_id,
        "screen_setter_id": plan.screen_setter_id,
    }


def _plan_from_dict(value: object) -> OffensivePlan:
    obj = _object(value, "plan")
    family = cast(PlayFamily, _enum(PlayFamily, obj, "family"))
    if family is PlayFamily.BALL_SCREEN:
        _exact(obj, {"family", "handler_id", "screener_id"}, "plan")
        return BallScreenPlan(_int(obj, "handler_id"), _int(obj, "screener_id"))
    if family is PlayFamily.ISOLATION:
        _exact(obj, {"family", "initiator_id"}, "plan")
        return IsolationPlan(_int(obj, "initiator_id"))
    _exact(
        obj,
        {"family", "passer_id", "target_id", "screen_setter_id"},
        "plan",
    )
    return OffBallActionPlan(
        _int(obj, "passer_id"),
        _int(obj, "target_id"),
        _nullable_int(obj, "screen_setter_id"),
    )


def _selection_to_dict(selection: FinisherSelection) -> dict[str, int]:
    return {"route": int(selection.route), "finisher_id": selection.finisher_id}


def _selection_from_dict(value: object) -> FinisherSelection:
    obj = _object(value, "selection")
    _exact(obj, {"route", "finisher_id"}, "selection")
    return FinisherSelection(
        cast(FinisherRoute, _enum(FinisherRoute, obj, "route")),
        _int(obj, "finisher_id"),
    )


def _rebound_to_dict(rebound: ReboundOutcome) -> dict[str, object]:
    return {
        "kind": "offensive" if isinstance(rebound, OffensiveRebound) else "defensive",
        "rebounder_id": rebound.rebounder_id,
    }


def _rebound_from_dict(value: object) -> ReboundOutcome:
    obj = _object(value, "rebound")
    _exact(obj, {"kind", "rebounder_id"}, "rebound")
    kind = obj["kind"]
    rebounder_id = _int(obj, "rebounder_id")
    if kind == "offensive":
        return OffensiveRebound(rebounder_id)
    if kind == "defensive":
        return DefensiveRebound(rebounder_id)
    _fail("invalid rebound kind")


def _turnover_to_dict(outcome: TurnoverOutcome) -> dict[str, object]:
    if isinstance(outcome, StolenTurnover):
        return {
            "kind": int(outcome.kind),
            "responsible_offender_id": outcome.responsible_offender_id,
            "stealer_id": outcome.stealer_id,
        }
    if isinstance(outcome, UnforcedTurnover):
        return {
            "kind": int(outcome.kind),
            "responsible_offender_id": outcome.responsible_offender_id,
        }
    return {
        "kind": int(TurnoverKind.VIOLATION),
        "responsible_offender_id": outcome.responsible_offender_id,
    }


def _turnover_from_dict(value: object) -> TurnoverOutcome:
    obj = _object(value, "outcome")
    kind = cast(TurnoverKind, _enum(TurnoverKind, obj, "kind"))
    if kind in {TurnoverKind.LOST_BALL_STEAL, TurnoverKind.BAD_PASS_STEAL}:
        _exact(obj, {"kind", "responsible_offender_id", "stealer_id"}, "outcome")
        return StolenTurnover(kind, _int(obj, "responsible_offender_id"), _int(obj, "stealer_id"))
    _exact(obj, {"kind", "responsible_offender_id"}, "outcome")
    if kind is TurnoverKind.VIOLATION:
        return ViolationTurnover(_int(obj, "responsible_offender_id"))
    return UnforcedTurnover(kind, _int(obj, "responsible_offender_id"))


def segment_result_to_dict(result: ActionSegmentResult) -> dict[str, object]:
    base: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "plan": _plan_to_dict(result.plan),
        "coverage": int(result.coverage),
    }
    if isinstance(result, TurnoverSegmentResult):
        return {**base, "kind": "turnover", "outcome": _turnover_to_dict(result.outcome)}
    if isinstance(result, NonShootingFoulSegmentResult):
        return {
            **base,
            "kind": "non_shooting_foul",
            "offended_player_id": result.offended_player_id,
            "fouler_id": result.fouler_id,
            "free_throws": list(result.free_throws),
            "rebound": (_rebound_to_dict(result.rebound) if result.rebound is not None else None),
        }
    if isinstance(result, OffensiveFoulSegmentResult):
        return {
            **base,
            "kind": "offensive_foul",
            "responsible_offender_id": result.responsible_offender_id,
            "defender_id": result.defender_id,
        }
    if isinstance(result, TechnicalFoulSegmentResult):
        return {
            **base,
            "kind": "technical_foul",
            "foul_type": int(result.foul_type),
            "responsible_side": int(result.responsible_side),
            "responsible_player_id": result.responsible_player_id,
            "shooter_id": result.shooter_id,
            "free_throws": list(result.free_throws),
            "offense_retains_possession": result.offense_retains_possession,
        }

    shot: dict[str, object] = {
        **base,
        "selection": _selection_to_dict(result.selection),
        "zone": int(result.zone),
    }
    if isinstance(result, MadeShotSegmentResult):
        return {
            **shot,
            "kind": "made_shot",
            "contest_level": int(result.contest_level),
            "assister_id": result.assister_id,
        }
    if isinstance(result, MissedShotSegmentResult):
        return {
            **shot,
            "kind": "missed_shot",
            "contest_level": int(result.contest_level),
            "rebound": _rebound_to_dict(result.rebound),
        }
    if isinstance(result, ShootingFoulSegmentResult):
        return {
            **shot,
            "kind": "shooting_foul",
            "contest_level": int(result.contest_level),
            "fouler_id": result.fouler_id,
            "field_goal_made": result.field_goal_made,
            "free_throws": list(result.free_throws),
            "rebound": (_rebound_to_dict(result.rebound) if result.rebound is not None else None),
            "assister_id": result.assister_id,
        }
    return {
        **shot,
        "kind": "blocked_shot",
        "blocker_id": result.blocker_id,
        "rebound": _rebound_to_dict(result.rebound),
    }


def segment_result_from_dict(value: object) -> ActionSegmentResult:
    obj = _object(value, "segment result")
    common = {"schema_version", "kind", "plan", "coverage"}
    schema_version = _int(obj, "schema_version")
    if schema_version not in {1, 2, 3, 4, SCHEMA_VERSION}:
        _fail("unsupported schema_version")
    kind = obj.get("kind")
    plan = _plan_from_dict(obj.get("plan"))
    coverage = cast(Coverage, _enum(Coverage, obj, "coverage"))
    if kind == "turnover":
        _exact(obj, common | {"outcome"}, "segment result")
        return TurnoverSegmentResult(plan, coverage, _turnover_from_dict(obj["outcome"]))
    if kind == "non_shooting_foul":
        if schema_version not in {4, SCHEMA_VERSION}:
            _fail("non_shooting_foul requires schema_version 4 or 5")
        _exact(
            obj,
            common
            | {
                "offended_player_id",
                "fouler_id",
                "free_throws",
                "rebound",
            },
            "segment result",
        )
        raw_free_throws = obj["free_throws"]
        if not isinstance(raw_free_throws, list) or any(
            not isinstance(made, bool) for made in raw_free_throws
        ):
            _fail("free_throws must be a boolean list")
        raw_rebound = obj["rebound"]
        rebound = None if raw_rebound is None else _rebound_from_dict(raw_rebound)
        return NonShootingFoulSegmentResult(
            plan,
            coverage,
            _int(obj, "offended_player_id"),
            _int(obj, "fouler_id"),
            tuple(raw_free_throws),
            rebound,
        )
    if kind == "offensive_foul":
        if schema_version != SCHEMA_VERSION:
            _fail("offensive_foul requires schema_version 5")
        _exact(
            obj,
            common | {"responsible_offender_id", "defender_id"},
            "segment result",
        )
        return OffensiveFoulSegmentResult(
            plan,
            coverage,
            _int(obj, "responsible_offender_id"),
            _int(obj, "defender_id"),
        )
    if kind == "technical_foul":
        if schema_version != SCHEMA_VERSION:
            _fail("technical_foul requires schema_version 5")
        _exact(
            obj,
            common
            | {
                "foul_type",
                "responsible_side",
                "responsible_player_id",
                "shooter_id",
                "free_throws",
                "offense_retains_possession",
            },
            "segment result",
        )
        raw_free_throws = obj["free_throws"]
        if not isinstance(raw_free_throws, list) or any(
            not isinstance(made, bool) for made in raw_free_throws
        ):
            _fail("free_throws must be a boolean list")
        retained = obj["offense_retains_possession"]
        if not isinstance(retained, bool):
            _fail("offense_retains_possession must be a boolean")
        return TechnicalFoulSegmentResult(
            plan,
            coverage,
            cast(TechnicalFoulType, _enum(TechnicalFoulType, obj, "foul_type")),
            cast(FoulTeamSide, _enum(FoulTeamSide, obj, "responsible_side")),
            _nullable_int(obj, "responsible_player_id"),
            _int(obj, "shooter_id"),
            tuple(raw_free_throws),
            retained,
        )

    selection = _selection_from_dict(obj.get("selection"))
    zone = cast(ShotZone, _enum(ShotZone, obj, "zone"))
    shot = common | {"selection", "zone"}
    if kind == "made_shot":
        if schema_version == 1:
            _exact(obj, shot | {"contest_level"}, "segment result")
            assister_id = last_passer_for(plan, selection.route)
        else:
            _exact(obj, shot | {"contest_level", "assister_id"}, "segment result")
            raw_assister = obj["assister_id"]
            assister_id = None if raw_assister is None else _int(obj, "assister_id")
        return MadeShotSegmentResult(
            plan,
            coverage,
            selection,
            zone,
            cast(ContestLevel, _enum(ContestLevel, obj, "contest_level")),
            assister_id,
        )
    if kind == "missed_shot":
        _exact(obj, shot | {"contest_level", "rebound"}, "segment result")
        return MissedShotSegmentResult(
            plan,
            coverage,
            selection,
            zone,
            cast(ContestLevel, _enum(ContestLevel, obj, "contest_level")),
            _rebound_from_dict(obj["rebound"]),
        )
    if kind == "shooting_foul":
        if schema_version not in {3, 4, SCHEMA_VERSION}:
            _fail("shooting_foul requires schema_version 3, 4, or 5")
        _exact(
            obj,
            shot
            | {
                "contest_level",
                "fouler_id",
                "field_goal_made",
                "free_throws",
                "rebound",
                "assister_id",
            },
            "segment result",
        )
        field_goal_made = obj["field_goal_made"]
        if not isinstance(field_goal_made, bool):
            _fail("field_goal_made must be a boolean")
        raw_free_throws = obj["free_throws"]
        if not isinstance(raw_free_throws, list) or any(
            not isinstance(made, bool) for made in raw_free_throws
        ):
            _fail("free_throws must be a boolean list")
        raw_rebound = obj["rebound"]
        rebound = None if raw_rebound is None else _rebound_from_dict(raw_rebound)
        return ShootingFoulSegmentResult(
            plan,
            coverage,
            selection,
            zone,
            cast(ContestLevel, _enum(ContestLevel, obj, "contest_level")),
            _int(obj, "fouler_id"),
            field_goal_made,
            tuple(raw_free_throws),
            rebound,
            _nullable_int(obj, "assister_id"),
        )
    if kind == "blocked_shot":
        _exact(obj, shot | {"blocker_id", "rebound"}, "segment result")
        return BlockedShotSegmentResult(
            plan,
            coverage,
            selection,
            zone,
            _int(obj, "blocker_id"),
            _rebound_from_dict(obj["rebound"]),
        )
    _fail("invalid segment result kind")


def segment_result_to_json(result: ActionSegmentResult) -> str:
    return json.dumps(
        segment_result_to_dict(result),
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def segment_result_from_json(payload: str) -> ActionSegmentResult:
    try:
        value = json.loads(payload)
    except json.JSONDecodeError as error:
        raise SerializationError("invalid JSON") from error
    return segment_result_from_dict(value)


def possession_result_to_dict(result: PossessionResult) -> dict[str, object]:
    return {
        "schema_version": SCHEMA_VERSION,
        "segments": [segment_result_to_dict(segment) for segment in result.segments],
        "end_reason": int(result.end_reason),
    }


def possession_result_from_dict(value: object) -> PossessionResult:
    obj = _object(value, "possession result")
    _exact(obj, {"schema_version", "segments", "end_reason"}, "possession result")
    if _int(obj, "schema_version") not in {1, 2, 3, 4, SCHEMA_VERSION}:
        _fail("unsupported schema_version")
    raw_segments = obj["segments"]
    if not isinstance(raw_segments, list) or not raw_segments:
        _fail("segments must be a non-empty list")
    segments = tuple(segment_result_from_dict(segment) for segment in raw_segments)
    end_reason = cast(
        PossessionEndReason,
        _enum(PossessionEndReason, obj, "end_reason"),
    )
    if any(not offense_retains_ball(segment) for segment in segments[:-1]):
        _fail("only an offense-retaining event may continue a possession")
    natural_end = possession_end_reason(segments[-1])
    if end_reason is PossessionEndReason.SEGMENT_LIMIT:
        if natural_end is not None:
            _fail("segment limit requires offense to retain the final event")
    elif natural_end is not end_reason:
        _fail("end_reason does not match the final segment")
    return PossessionResult(segments, end_reason)


def possession_result_to_json(result: PossessionResult) -> str:
    return json.dumps(
        possession_result_to_dict(result),
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def possession_result_from_json(payload: str) -> PossessionResult:
    try:
        value = json.loads(payload)
    except json.JSONDecodeError as error:
        raise SerializationError("invalid JSON") from error
    return possession_result_from_dict(value)

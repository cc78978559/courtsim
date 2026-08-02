"""Interpretable player-role targets and calibration readiness."""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Mapping
from typing import Any, cast

from courtsim.analysis.nba_player_targets import NBAPlayerTarget, NBAPlayerTargetSet

NBA_PLAYER_CALIBRATION_VERSION = "nba-player-calibration-v1"


def classify_player_role(player: NBAPlayerTarget) -> str:
    if player.usage_rate >= 0.28 and player.field_goal_attempt_share >= 0.20:
        return "PRIMARY_CREATOR"
    if player.usage_rate >= 0.22:
        return "SECONDARY_CREATOR"
    rim, _midrange, three = player.shot_zone_shares
    if rim >= 0.55:
        return "RIM_FINISHER"
    if three >= 0.55:
        return "SPACER"
    if player.minutes_per_game >= 24:
        return "CONNECTOR"
    return "BENCH_SPECIALIST"


def build_player_calibration_plan(
    targets: NBAPlayerTargetSet,
    identity: Mapping[str, object],
    *,
    minimum_identity_player_coverage: float = 0.9,
    minimum_identity_minutes_coverage: float = 0.95,
) -> dict[str, object]:
    coverage = _object(identity.get("coverage"), "identity.coverage")
    player_coverage = _number(coverage.get("player_coverage"), "player_coverage")
    minutes_coverage = _number(coverage.get("minutes_coverage"), "minutes_coverage")
    roles = Counter(classify_player_role(player) for player in targets.players)
    ready = (
        player_coverage >= minimum_identity_player_coverage
        and minutes_coverage >= minimum_identity_minutes_coverage
    )
    return {
        "schema_version": 1,
        "version": NBA_PLAYER_CALIBRATION_VERSION,
        "target_id": targets.target_id,
        "players": len(targets.players),
        "identity": {
            "player_coverage": player_coverage,
            "minutes_coverage": minutes_coverage,
            "minimum_player_coverage": minimum_identity_player_coverage,
            "minimum_minutes_coverage": minimum_identity_minutes_coverage,
        },
        "role_distribution": dict(sorted(roles.items())),
        "calibration_order": [
            "minutes_per_game",
            "usage_rate",
            "field_goal_attempt_share",
            "shot_zone_shares",
            "true_shooting_percentage",
            "shot_zone_percentages",
            "role_distribution",
        ],
        "promotion_ready": ready,
        "blocking_reasons": [
            reason
            for failed, reason in (
                (player_coverage < minimum_identity_player_coverage, "player_identity_coverage"),
                (minutes_coverage < minimum_identity_minutes_coverage, "minutes_identity_coverage"),
            )
            if failed
        ],
    }


def _object(value: object, field: str) -> dict[str, Any]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise ValueError(f"{field} must be an object")
    return cast(dict[str, Any], value)


def _number(value: object, field: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
        raise ValueError(f"{field} must be finite numeric data")
    return float(value)

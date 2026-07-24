"""Deterministic audit table for contextual team-tempo policy."""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any, cast

from courtsim.model.game_runtime import (
    TeamTempoStrategy,
    effective_tempo_rating,
    possession_duration_weights,
)
from courtsim.parameters import ModelParameters


def _context_row(
    parameters: ModelParameters,
    strategy: TeamTempoStrategy,
    *,
    context_id: str,
    period: int,
    clock_seconds: int,
    offense_score: int,
    defense_score: int,
) -> dict[str, Any]:
    options = possession_duration_weights(
        parameters,
        strategy,
        period=period,
        clock_seconds=clock_seconds,
        regulation_periods=4,
        offense_score=offense_score,
        defense_score=defense_score,
    )
    total = math.fsum(option.weight for option in options)
    probabilities = tuple(option.weight / total for option in options)
    return {
        "context_id": context_id,
        "period": period,
        "clock_seconds": clock_seconds,
        "score_margin": offense_score - defense_score,
        "effective_tempo": effective_tempo_rating(
            parameters,
            strategy,
            period=period,
            clock_seconds=clock_seconds,
            regulation_periods=4,
            offense_score=offense_score,
            defense_score=defense_score,
        ),
        "expected_duration_seconds": math.fsum(
            option.value * probability
            for option, probability in zip(options, probabilities, strict=True)
        ),
        "options": [
            {
                "class": option.id,
                "duration_seconds": option.value,
                "probability": probability,
            }
            for option, probability in zip(options, probabilities, strict=True)
        ],
    }


def build_tempo_policy_audit(
    parameters: ModelParameters,
    *,
    tempo: int = 50,
) -> dict[str, Any]:
    if parameters.schema.schema_version != "demo-v1.9":
        raise ValueError("tempo policy audit requires demo-v1.9 parameters")
    strategy = TeamTempoStrategy(tempo)
    nodes = cast(Mapping[str, Any], parameters.payload["nodes"])
    duration = cast(Mapping[str, Any], nodes["possession_duration"])
    late_game = cast(Mapping[str, Any], duration["late_game_adjustments"])
    threshold = cast(int, late_game["margin_threshold"])
    window = cast(int, late_game["window_seconds"])
    contexts = (
        _context_row(
            parameters,
            strategy,
            context_id="early-trailing",
            period=4,
            clock_seconds=window + 1,
            offense_score=100,
            defense_score=100 + threshold,
        ),
        _context_row(
            parameters,
            strategy,
            context_id="late-below-threshold",
            period=4,
            clock_seconds=window,
            offense_score=100,
            defense_score=100 + threshold - 1,
        ),
        _context_row(
            parameters,
            strategy,
            context_id="late-tied",
            period=4,
            clock_seconds=window,
            offense_score=100,
            defense_score=100,
        ),
        _context_row(
            parameters,
            strategy,
            context_id="late-trailing",
            period=4,
            clock_seconds=window,
            offense_score=100,
            defense_score=100 + threshold,
        ),
        _context_row(
            parameters,
            strategy,
            context_id="late-leading",
            period=4,
            clock_seconds=window,
            offense_score=100 + threshold,
            defense_score=100,
        ),
    )
    by_id = {cast(str, row["context_id"]): row for row in contexts}
    tied_duration = cast(float, by_id["late-tied"]["expected_duration_seconds"])
    gates = (
        {
            "gate": "early-context-is-inactive",
            "passed": by_id["early-trailing"]["effective_tempo"] == tempo,
        },
        {
            "gate": "below-margin-threshold-is-inactive",
            "passed": by_id["late-below-threshold"]["effective_tempo"] == tempo,
        },
        {
            "gate": "trailing-team-plays-faster",
            "passed": (
                cast(float, by_id["late-trailing"]["expected_duration_seconds"]) < tied_duration
            ),
        },
        {
            "gate": "leading-team-plays-slower",
            "passed": (
                cast(float, by_id["late-leading"]["expected_duration_seconds"]) > tied_duration
            ),
        },
    )
    return {
        "format_version": 1,
        "kind": "courtsim-tempo-policy-audit",
        "schema_version": parameters.schema.schema_version,
        "schema_hash": parameters.schema.schema_hash,
        "parameter_hash": parameters.parameter_hash,
        "base_tempo": tempo,
        "contexts": list(contexts),
        "gates": list(gates),
        "summary": {
            "checked": len(gates),
            "failed": sum(not cast(bool, gate["passed"]) for gate in gates),
            "passed": all(cast(bool, gate["passed"]) for gate in gates),
        },
    }

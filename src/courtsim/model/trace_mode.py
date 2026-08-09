"""Explicit control over retained simulation detail."""

from enum import StrEnum


class TraceMode(StrEnum):
    FULL = "full"
    AGGREGATE_ONLY = "aggregate-only"
    PLAYER_AGGREGATES = "player-aggregates"

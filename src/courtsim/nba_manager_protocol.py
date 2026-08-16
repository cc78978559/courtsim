"""Frozen external protocol for the one-shot NBA manager holdout."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from courtsim.analysis.nba_real_rosters import ESPN_TEAM_NAMES
from courtsim.artifacts import sha256_file

NBA_MANAGER_PROTOCOL_VERSION = "nba-manager-promotion-protocol-v1"
NBA_MANAGER_PROTOCOL_ID = "nba-manager-policy-v1"
NBA_MANAGER_HOLDOUT_ID = "nba-manager-policy-v1-holdout-202704"
NBA_MANAGER_FORMAL_MASTER_SEEDS = tuple(range(20270401, 20270431))
NBA_MANAGER_CANONICAL_TEAM_IDS = tuple(sorted(ESPN_TEAM_NAMES.values()))
NBA_MANAGER_PROTOCOL_INPUT_ROLES = frozenset(
    {
        "initial_checkpoint",
        "macro_reference",
        "manager_profiles",
        "model_parameters",
        "model_schema",
        "player_targets",
        "shot_profiles",
        "state_build_source",
        "state_build_receipt",
    }
)
NBA_MANAGER_PROTOCOL_SOURCE_ROLE = "promotion_protocol"


class NBAManagerProtocolError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class NBAManagerPromotionProtocol:
    experiment_id: str
    holdout_id: str
    start_season: int
    initial_state_sha256: str
    source_hashes: tuple[tuple[str, str], ...]
    execution_config_sha256: str
    macro_ranges: tuple[tuple[str, float, float], ...]
    team_ids: tuple[str, ...] = NBA_MANAGER_CANONICAL_TEAM_IDS
    master_seeds: tuple[int, ...] = NBA_MANAGER_FORMAL_MASTER_SEEDS
    focal_team_ids: tuple[str, ...] = NBA_MANAGER_CANONICAL_TEAM_IDS
    seasons: int = 5
    status: str = "frozen"
    version: str = NBA_MANAGER_PROTOCOL_VERSION

    def __post_init__(self) -> None:
        names = tuple(name for name, _ in self.source_hashes)
        macro_names = tuple(name for name, _, _ in self.macro_ranges)
        if (
            self.experiment_id != NBA_MANAGER_PROTOCOL_ID
            or self.holdout_id != NBA_MANAGER_HOLDOUT_ID
            or self.start_season < 1
            or self.team_ids != NBA_MANAGER_CANONICAL_TEAM_IDS
            or self.master_seeds != NBA_MANAGER_FORMAL_MASTER_SEEDS
            or self.focal_team_ids != NBA_MANAGER_CANONICAL_TEAM_IDS
            or self.seasons != 5
            or self.status != "frozen"
            or self.version != NBA_MANAGER_PROTOCOL_VERSION
            or set(names) != NBA_MANAGER_PROTOCOL_INPUT_ROLES
            or names != tuple(sorted(names))
            or macro_names != tuple(sorted(set(macro_names)))
            or not self.macro_ranges
        ):
            raise ValueError("NBA manager promotion protocol identity is invalid")
        for digest in (
            self.initial_state_sha256,
            self.execution_config_sha256,
            *(digest for _, digest in self.source_hashes),
        ):
            _validate_digest(digest)
        if any(
            not name.strip()
            or not math.isfinite(minimum)
            or not math.isfinite(maximum)
            or minimum > maximum
            for name, minimum, maximum in self.macro_ranges
        ):
            raise ValueError("NBA manager promotion protocol macro ranges are invalid")


def canonical_nba_manager_protocol_path() -> Path:
    return (
        Path(__file__).resolve().parents[2]
        / "experiments/promotion/nba-manager-policy-v1-protocol.json"
    )


def load_nba_manager_promotion_protocol(path: str | Path) -> NBAManagerPromotionProtocol:
    candidate = Path(path).resolve()
    if candidate != canonical_nba_manager_protocol_path().resolve():
        raise NBAManagerProtocolError("formal NBA manager protocol must use the canonical path")
    try:
        root = _object(json.loads(candidate.read_text(encoding="utf-8")))
        expected = {
            "schema_version",
            "version",
            "status",
            "experiment_id",
            "holdout_id",
            "start_season",
            "seasons",
            "team_ids",
            "master_seeds",
            "focal_team_ids",
            "initial_state_sha256",
            "source_hashes",
            "execution_config_sha256",
            "macro_ranges",
        }
        if set(root) != expected or root["schema_version"] != 1:
            raise NBAManagerProtocolError("NBA manager promotion protocol schema differs")
        return NBAManagerPromotionProtocol(
            experiment_id=str(root["experiment_id"]),
            holdout_id=str(root["holdout_id"]),
            start_season=int(root["start_season"]),
            initial_state_sha256=str(root["initial_state_sha256"]),
            source_hashes=tuple(
                (str(item[0]), str(item[1]))
                for item in cast(list[list[object]], root["source_hashes"])
            ),
            execution_config_sha256=str(root["execution_config_sha256"]),
            macro_ranges=tuple(
                (str(item[0]), float(cast(float, item[1])), float(cast(float, item[2])))
                for item in cast(list[list[object]], root["macro_ranges"])
            ),
            team_ids=tuple(str(item) for item in cast(list[object], root["team_ids"])),
            master_seeds=tuple(
                int(cast(int, item)) for item in cast(list[object], root["master_seeds"])
            ),
            focal_team_ids=tuple(str(item) for item in cast(list[object], root["focal_team_ids"])),
            seasons=int(root["seasons"]),
            status=str(root["status"]),
            version=str(root["version"]),
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError) as error:
        raise NBAManagerProtocolError("cannot load NBA manager promotion protocol") from error


def verify_nba_manager_protocol_file(path: str | Path, expected_sha256: str) -> None:
    protocol = load_nba_manager_promotion_protocol(path)
    if not protocol.status == "frozen" or sha256_file(path) != expected_sha256:
        raise NBAManagerProtocolError("NBA manager promotion protocol file differs")


def _validate_digest(value: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError("NBA manager promotion protocol digest is invalid")


def _object(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise NBAManagerProtocolError("NBA manager promotion protocol must be an object")
    return cast(dict[str, Any], value)

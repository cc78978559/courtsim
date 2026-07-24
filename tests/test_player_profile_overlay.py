import json
from pathlib import Path

import pytest

from courtsim.artifacts import sha256_file
from courtsim.cli import main
from courtsim.domain.player_serialization import player_lineup_from_dict
from courtsim.player_profile_overlay import (
    PlayerProfileOverlayError,
    apply_player_lineup_overlay,
)
from courtsim.verification import verify_manifest

ROOT = Path(__file__).parents[1]
BASE = ROOT / "examples" / "calibration_lineup_v1.json"


def overlay(*overrides: dict[str, object]) -> dict[str, object]:
    return {
        "format_version": 1,
        "kind": "courtsim-player-lineup-overlay",
        "overlay_id": "test-profile-overlay",
        "lineup_id": "test-profile-overlay-lineup",
        "notes": "Controlled player profile overlay test.",
        "overrides": list(overrides),
    }


def write(path: Path, value: object) -> Path:
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def test_profile_overlay_materializes_valid_lineup_and_manifest(tmp_path: Path) -> None:
    source = write(
        tmp_path / "overlay.json",
        overlay(
            {
                "player_id": 2,
                "path": ["abilities", "three_point_shooting"],
                "value": 20,
            },
            {
                "player_id": 2,
                "path": ["tendencies", "shot_zone_mix", "three"],
                "value": 10,
            },
        ),
    )
    output = tmp_path / "candidate.json"
    assert main(["profile-overlay", str(BASE), str(source), str(output)]) == 0
    candidate = json.loads(output.read_text(encoding="utf-8"))
    lineup = player_lineup_from_dict(candidate)
    player = next(item for item in lineup if item.player_id == 2)
    assert player.abilities.three_point_shooting == 20
    assert player.tendencies.shot_zone_mix.three == 10
    assert candidate["lineup_id"] == "test-profile-overlay-lineup"

    manifest_path = output.with_suffix(".json.manifest.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["inputs"][0]["sha256"] == sha256_file(BASE)
    assert manifest["inputs"][1]["sha256"] == sha256_file(source)
    assert manifest["outputs"][0]["sha256"] == sha256_file(output)
    assert verify_manifest(manifest_path).ok


def test_profile_overlay_rejects_identity_paths_duplicates_and_invalid_ratings(
    tmp_path: Path,
) -> None:
    identity = write(
        tmp_path / "identity.json",
        overlay({"player_id": 2, "path": ["name", "value"], "value": 10}),
    )
    with pytest.raises(PlayerProfileOverlayError, match="path is invalid"):
        apply_player_lineup_overlay(BASE, identity)

    item = {
        "player_id": 2,
        "path": ["abilities", "three_point_shooting"],
        "value": 20,
    }
    duplicates = write(tmp_path / "duplicates.json", overlay(item, item))
    with pytest.raises(PlayerProfileOverlayError, match="duplicate"):
        apply_player_lineup_overlay(BASE, duplicates)

    invalid = write(
        tmp_path / "invalid.json",
        overlay(
            {
                "player_id": 2,
                "path": ["abilities", "three_point_shooting"],
                "value": 101,
            }
        ),
    )
    with pytest.raises(PlayerProfileOverlayError, match="0 through 100"):
        apply_player_lineup_overlay(BASE, invalid)


def test_profile_overlay_requires_a_five_player_lineup(tmp_path: Path) -> None:
    source = write(
        tmp_path / "overlay.json",
        overlay(
            {
                "player_id": 2,
                "path": ["abilities", "three_point_shooting"],
                "value": 20,
            }
        ),
    )
    with pytest.raises(PlayerProfileOverlayError, match="base player lineup is invalid"):
        apply_player_lineup_overlay(ROOT / "examples" / "player_profile_v1.json", source)

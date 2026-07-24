import json
from pathlib import Path

import pytest

from courtsim.cli import main
from courtsim.parameter_overlay import (
    ParameterOverlayError,
    add_assist_occurrence_effects,
    add_assist_resolution_node,
    add_foul_free_throw_nodes,
    add_late_game_tempo_adjustments,
    add_non_shooting_foul_node,
    add_possession_duration_node,
    apply_parameter_overlay,
    enable_non_bonus_intentional_fouls,
    promote_intentional_foul_execution,
)
from courtsim.parameters import load_model_parameters

ROOT = Path(__file__).parents[1]
SCHEMA = ROOT / "data" / "model_schema_demo_v1_3.json"
BASE = ROOT / "data" / "model_parameters_demo_0.4.0.json"
STRUCTURE_BASE = ROOT / "data" / "model_parameters_demo_0.5.0.json"
ASSIST_SCHEMA = ROOT / "data" / "model_schema_demo_v1_4.json"
ASSIST_MIGRATION = ROOT / "experiments" / "calibration" / "assist-node-v1.json"
FOUL_SCHEMA = ROOT / "data" / "model_schema_demo_v1_5.json"
FOUL_MIGRATION = ROOT / "experiments" / "calibration" / "foul-free-throw-node-v1.json"
COMMON_FOUL_SCHEMA = ROOT / "data" / "model_schema_demo_v1_6.json"
COMMON_FOUL_MIGRATION = ROOT / "experiments" / "calibration" / "common-foul-node-v1.json"
ASSIST_OCCURRENCE_SCHEMA = ROOT / "data" / "model_schema_demo_v1_7.json"
ASSIST_OCCURRENCE_MIGRATION = ROOT / "experiments" / "calibration" / "assist-occurrence-v1.json"
TEMPO_SCHEMA = ROOT / "data" / "model_schema_demo_v1_8.json"
TEMPO_MIGRATION = ROOT / "experiments" / "calibration" / "possession-duration-v1.json"
LATE_TEMPO_SCHEMA = ROOT / "data" / "model_schema_demo_v1_9.json"
LATE_TEMPO_MIGRATION = ROOT / "experiments" / "calibration" / "late-game-tempo-v1.json"
FORMAL_FOUL_SCHEMA = ROOT / "data" / "model_schema_demo_v1_11.json"
FORMAL_FOUL_MIGRATION = ROOT / "experiments" / "calibration" / "intentional-foul-execution-v1.json"
NON_BONUS_FOUL_SCHEMA = ROOT / "data" / "model_schema_demo_v1_12.json"
NON_BONUS_FOUL_MIGRATION = (
    ROOT / "experiments" / "calibration" / "intentional-foul-non-bonus-v1.json"
)


def overlay(*overrides: dict[str, object]) -> dict[str, object]:
    return {
        "format_version": 1,
        "overlay_id": "test-overlay",
        "parameter_version": "test-overlay-1",
        "notes": "Synthetic overlay test.",
        "overrides": list(overrides),
    }


def write(path: Path, value: object) -> Path:
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def test_overlay_materializes_existing_numeric_leaves_and_validates(tmp_path: Path) -> None:
    source = write(
        tmp_path / "overlay.json",
        overlay(
            {
                "path": [
                    "nodes",
                    "rebound_hazard",
                    "defense_context_factor",
                ],
                "value": 2.2,
            }
        ),
    )
    output = tmp_path / "candidate.json"
    assert main(["parameters-overlay", str(SCHEMA), str(BASE), str(source), str(output)]) == 0
    loaded = load_model_parameters(SCHEMA, output)
    assert loaded.payload["metadata"]["parameter_version"] == "test-overlay-1"
    assert loaded.payload["nodes"]["rebound_hazard"]["defense_context_factor"] == 2.2


def test_overlay_rejects_missing_and_duplicate_paths(tmp_path: Path) -> None:
    missing = write(
        tmp_path / "missing.json",
        overlay({"path": ["nodes", "not-a-node", "value"], "value": 1.0}),
    )
    with pytest.raises(ParameterOverlayError, match="does not exist"):
        apply_parameter_overlay(BASE, missing)

    duplicate = {
        "path": ["nodes", "rebound_hazard", "defense_context_factor"],
        "value": 2.2,
    }
    duplicates = write(tmp_path / "duplicates.json", overlay(duplicate, duplicate))
    with pytest.raises(ParameterOverlayError, match="duplicate"):
        apply_parameter_overlay(BASE, duplicates)


def test_overlay_cannot_mutate_metadata_or_replace_objects(tmp_path: Path) -> None:
    metadata = write(
        tmp_path / "metadata.json",
        overlay({"path": ["metadata", "parameter_version"], "value": 1.0}),
    )
    with pytest.raises(ParameterOverlayError, match="path is invalid"):
        apply_parameter_overlay(BASE, metadata)

    object_leaf = write(
        tmp_path / "object.json",
        overlay({"path": ["nodes", "shot_zone", "base_probabilities"], "value": 1.0}),
    )
    with pytest.raises(ParameterOverlayError, match="leaf is not numeric"):
        apply_parameter_overlay(BASE, object_leaf)


def test_assist_migration_materializes_v14_parameters_and_validates(
    tmp_path: Path,
) -> None:
    output = tmp_path / "candidate.json"
    assert (
        main(
            [
                "parameters-add-assist",
                str(ASSIST_SCHEMA),
                str(STRUCTURE_BASE),
                str(ASSIST_MIGRATION),
                str(output),
            ]
        )
        == 0
    )
    loaded = load_model_parameters(ASSIST_SCHEMA, output)
    assert loaded.schema.has_assist_resolution
    assert loaded.payload["metadata"]["schema_version"] == "demo-v1.4"
    assert (
        loaded.payload["nodes"]["assist_resolution"]["base_probability_by_creation_mode"][
            "SELF_CREATED"
        ]
        == 0.4
    )


def test_assist_migration_rejects_an_already_migrated_base() -> None:
    with pytest.raises(ParameterOverlayError, match=r"requires demo-v1\.3"):
        add_assist_resolution_node(
            ROOT / "data" / "model_parameters_demo_0.6.0.json",
            ASSIST_MIGRATION,
        )


def test_foul_migration_materializes_v15_parameters_and_validates(
    tmp_path: Path,
) -> None:
    output = tmp_path / "candidate.json"
    assert (
        main(
            [
                "parameters-add-fouls",
                str(FOUL_SCHEMA),
                str(ROOT / "data" / "model_parameters_demo_0.6.0.json"),
                str(FOUL_MIGRATION),
                str(output),
            ]
        )
        == 0
    )
    loaded = load_model_parameters(FOUL_SCHEMA, output)
    assert loaded.schema.has_shooting_fouls
    assert loaded.payload["metadata"]["schema_version"] == "demo-v1.5"
    assert loaded.payload["nodes"]["shooting_foul"]["base_probability_by_zone"]["RIM"] == 0.14


def test_foul_migration_rejects_an_already_migrated_base(tmp_path: Path) -> None:
    migrated = tmp_path / "migrated.json"
    migrated.write_text(
        json.dumps(
            add_foul_free_throw_nodes(
                ROOT / "data" / "model_parameters_demo_0.6.0.json",
                FOUL_MIGRATION,
            )
        ),
        encoding="utf-8",
    )
    with pytest.raises(ParameterOverlayError, match=r"requires demo-v1\.4"):
        add_foul_free_throw_nodes(migrated, FOUL_MIGRATION)


def test_common_foul_migration_materializes_v16_parameters_and_validates(
    tmp_path: Path,
) -> None:
    output = tmp_path / "candidate.json"
    assert (
        main(
            [
                "parameters-add-common-fouls",
                str(COMMON_FOUL_SCHEMA),
                str(ROOT / "data" / "model_parameters_demo_0.7.0.json"),
                str(COMMON_FOUL_MIGRATION),
                str(output),
            ]
        )
        == 0
    )
    loaded = load_model_parameters(COMMON_FOUL_SCHEMA, output)
    assert loaded.schema.has_non_shooting_fouls
    assert loaded.payload["metadata"]["schema_version"] == "demo-v1.6"
    assert loaded.payload["rules"]["bonus_foul_threshold"] == 5


def test_common_foul_migration_rejects_an_already_migrated_base() -> None:
    with pytest.raises(ParameterOverlayError, match=r"requires demo-v1\.5"):
        add_non_shooting_foul_node(
            ROOT / "data" / "model_parameters_demo_0.8.0.json",
            COMMON_FOUL_MIGRATION,
        )


def test_assist_occurrence_migration_materializes_v17_parameters(
    tmp_path: Path,
) -> None:
    output = tmp_path / "candidate.json"
    assert (
        main(
            [
                "parameters-add-assist-occurrence",
                str(ASSIST_OCCURRENCE_SCHEMA),
                str(ROOT / "data" / "model_parameters_demo_0.8.0.json"),
                str(ASSIST_OCCURRENCE_MIGRATION),
                str(output),
            ]
        )
        == 0
    )
    loaded = load_model_parameters(ASSIST_OCCURRENCE_SCHEMA, output)
    assert loaded.payload["metadata"]["schema_version"] == "demo-v1.7"
    assert loaded.payload["nodes"]["assist_resolution"]["occurrence_playmaking_coefficient"] == 0.3


def test_assist_occurrence_migration_rejects_v17_base() -> None:
    with pytest.raises(ParameterOverlayError, match=r"requires demo-v1\.6"):
        add_assist_occurrence_effects(
            ROOT / "data" / "model_parameters_demo_0.9.0.json",
            ASSIST_OCCURRENCE_MIGRATION,
        )


def test_tempo_migration_materializes_v18_parameters(tmp_path: Path) -> None:
    output = tmp_path / "candidate.json"
    assert (
        main(
            [
                "parameters-add-tempo",
                str(TEMPO_SCHEMA),
                str(ROOT / "data" / "model_parameters_demo_0.9.0.json"),
                str(TEMPO_MIGRATION),
                str(output),
            ]
        )
        == 0
    )
    loaded = load_model_parameters(TEMPO_SCHEMA, output)
    assert (
        loaded.parameter_hash
        == load_model_parameters(
            TEMPO_SCHEMA,
            ROOT / "data" / "model_parameters_demo_1.0.0.json",
        ).parameter_hash
    )


def test_tempo_migration_rejects_v18_base() -> None:
    with pytest.raises(ParameterOverlayError, match=r"requires demo-v1\.7"):
        add_possession_duration_node(
            ROOT / "data" / "model_parameters_demo_1.0.0.json",
            TEMPO_MIGRATION,
        )


def test_late_game_tempo_migration_materializes_v19_parameters(tmp_path: Path) -> None:
    output = tmp_path / "candidate.json"
    assert (
        main(
            [
                "parameters-add-late-game-tempo",
                str(LATE_TEMPO_SCHEMA),
                str(ROOT / "data" / "model_parameters_demo_1.0.0.json"),
                str(LATE_TEMPO_MIGRATION),
                str(output),
            ]
        )
        == 0
    )
    loaded = load_model_parameters(LATE_TEMPO_SCHEMA, output)
    assert (
        loaded.parameter_hash
        == load_model_parameters(
            LATE_TEMPO_SCHEMA,
            ROOT / "data" / "model_parameters_demo_1.1.0.json",
        ).parameter_hash
    )


def test_late_game_tempo_migration_rejects_v19_base() -> None:
    with pytest.raises(ParameterOverlayError, match=r"requires demo-v1\.8"):
        add_late_game_tempo_adjustments(
            ROOT / "data" / "model_parameters_demo_1.1.0.json",
            LATE_TEMPO_MIGRATION,
        )


def test_intentional_foul_migration_materializes_v111_parameters(tmp_path: Path) -> None:
    output = tmp_path / "candidate.json"
    assert (
        main(
            [
                "parameters-promote-intentional-foul",
                str(FORMAL_FOUL_SCHEMA),
                str(ROOT / "data" / "model_parameters_demo_1.2.0.json"),
                str(FORMAL_FOUL_MIGRATION),
                str(output),
            ]
        )
        == 0
    )
    loaded = load_model_parameters(FORMAL_FOUL_SCHEMA, output)
    assert (
        loaded.parameter_hash
        == load_model_parameters(
            FORMAL_FOUL_SCHEMA,
            ROOT / "data" / "model_parameters_demo_1.3.0.json",
        ).parameter_hash
    )


def test_intentional_foul_migration_rejects_v111_base() -> None:
    with pytest.raises(ParameterOverlayError, match=r"requires demo-v1\.10"):
        promote_intentional_foul_execution(
            ROOT / "data" / "model_parameters_demo_1.3.0.json",
            FORMAL_FOUL_MIGRATION,
        )


def test_non_bonus_foul_migration_materializes_v112_parameters(tmp_path: Path) -> None:
    output = tmp_path / "candidate.json"
    assert (
        main(
            [
                "parameters-enable-non-bonus-intentional-foul",
                str(NON_BONUS_FOUL_SCHEMA),
                str(ROOT / "data" / "model_parameters_demo_1.3.0.json"),
                str(NON_BONUS_FOUL_MIGRATION),
                str(output),
            ]
        )
        == 0
    )
    loaded = load_model_parameters(NON_BONUS_FOUL_SCHEMA, output)
    assert (
        loaded.parameter_hash
        == load_model_parameters(
            NON_BONUS_FOUL_SCHEMA,
            ROOT / "data" / "model_parameters_demo_1.4.0.json",
        ).parameter_hash
    )


def test_non_bonus_foul_migration_rejects_v112_base() -> None:
    with pytest.raises(ParameterOverlayError, match=r"requires demo-v1\.11"):
        enable_non_bonus_intentional_fouls(
            ROOT / "data" / "model_parameters_demo_1.4.0.json",
            NON_BONUS_FOUL_MIGRATION,
        )

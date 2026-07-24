import json
from copy import deepcopy
from pathlib import Path
from types import MappingProxyType

import pytest

from courtsim.domain.enums import Coverage, FinisherRoute
from courtsim.domain.interaction import FinisherCandidateProfile, InteractionState
from courtsim.domain.plans import IsolationPlan, Lineup
from courtsim.model import CompiledParameterPolicy, sample_action_segment
from courtsim.parameters import ParameterError, load_model_parameters
from courtsim.randomness import RandomFrame, RandomFrameAddress

ROOT = Path(__file__).parents[1]
SCHEMA = ROOT / "data" / "model_schema_demo_v1_3.json"
PARAMETERS = ROOT / "data" / "model_parameters_demo_0.4.0.json"
ASSIST_SCHEMA = ROOT / "data" / "model_schema_demo_v1_4.json"
ASSIST_PARAMETERS = ROOT / "data" / "model_parameters_demo_0.6.0.json"
FOUL_SCHEMA = ROOT / "data" / "model_schema_demo_v1_5.json"
FOUL_PARAMETERS = ROOT / "data" / "model_parameters_demo_0.7.0.json"
COMMON_FOUL_SCHEMA = ROOT / "data" / "model_schema_demo_v1_6.json"
COMMON_FOUL_PARAMETERS = ROOT / "data" / "model_parameters_demo_0.8.0.json"
ASSIST_OCCURRENCE_SCHEMA = ROOT / "data" / "model_schema_demo_v1_7.json"
ASSIST_OCCURRENCE_PARAMETERS = ROOT / "data" / "model_parameters_demo_0.9.0.json"
TEMPO_SCHEMA = ROOT / "data" / "model_schema_demo_v1_8.json"
TEMPO_PARAMETERS = ROOT / "data" / "model_parameters_demo_1.0.0.json"
LATE_TEMPO_SCHEMA = ROOT / "data" / "model_schema_demo_v1_9.json"
LATE_TEMPO_PARAMETERS = ROOT / "data" / "model_parameters_demo_1.1.0.json"
LATE_STRATEGY_SCHEMA = ROOT / "data" / "model_schema_demo_v1_10.json"
LATE_STRATEGY_PARAMETERS = ROOT / "data" / "model_parameters_demo_1.2.0.json"
FORMAL_INTENTIONAL_FOUL_SCHEMA = ROOT / "data" / "model_schema_demo_v1_11.json"
FORMAL_INTENTIONAL_FOUL_PARAMETERS = ROOT / "data" / "model_parameters_demo_1.3.0.json"
NON_BONUS_INTENTIONAL_FOUL_SCHEMA = ROOT / "data" / "model_schema_demo_v1_12.json"
NON_BONUS_INTENTIONAL_FOUL_PARAMETERS = ROOT / "data" / "model_parameters_demo_1.4.0.json"
OFFENSE: Lineup = (1, 2, 3, 4, 5)
DEFENSE: Lineup = (11, 12, 13, 14, 15)


def write_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False),
        encoding="utf-8",
    )


def load_json(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def test_demo_parameters_load_with_stable_hashes() -> None:
    parameters = load_model_parameters(SCHEMA, PARAMETERS)
    assert not parameters.schema.has_assist_resolution
    assert isinstance(parameters.payload, MappingProxyType)
    assert (
        parameters.parameter_hash
        == "c3592432913e940005ff69449c31e2e30a23355f1986e1d5a18a214daff22d38"
    )
    assert (
        parameters.schema.schema_hash
        == "8fc2f9243e7f83711549ad67cc51435b8d078524d7221a0ec41e2d8f3c675ff0"
    )


def test_assist_parameters_load_with_stable_hashes() -> None:
    parameters = load_model_parameters(ASSIST_SCHEMA, ASSIST_PARAMETERS)
    assert parameters.schema.has_assist_resolution
    assert not parameters.schema.has_shooting_fouls
    assert (
        parameters.parameter_hash
        == "b6081415add0b1598bd86088bebddf5f2e835a677a8ed4230229153cee5dc362"
    )
    assert (
        parameters.schema.schema_hash
        == "b43bac066c70dfc9aead2c281cabdd2358a3fad8aa6f99615834b1221c81e80e"
    )


def test_foul_parameters_load_with_stable_hashes() -> None:
    parameters = load_model_parameters(FOUL_SCHEMA, FOUL_PARAMETERS)
    assert parameters.schema.has_assist_resolution
    assert parameters.schema.has_shooting_fouls
    assert (
        parameters.parameter_hash
        == "2c7887dd9519a6ecfa5f93c6226b1ef68c01d6d6c407cffa94cc1289c641e755"
    )
    assert (
        parameters.schema.schema_hash
        == "d73e0642cc4568e3bbef8bebb37219138971f86155a20c45196eb63028d0e72f"
    )


def test_common_foul_parameters_load_with_stable_hashes() -> None:
    parameters = load_model_parameters(COMMON_FOUL_SCHEMA, COMMON_FOUL_PARAMETERS)
    assert parameters.schema.has_non_shooting_fouls
    assert parameters.payload["rules"]["bonus_foul_threshold"] == 5
    assert (
        parameters.parameter_hash
        == "1596e9cc6da73967585e945caa52476ea61babffaa1e87b9738387b88dea2658"
    )
    assert (
        parameters.schema.schema_hash
        == "f9f372503715519e1cc7c808e46f3237000b2b3640a3d00c387ae3179acb731a"
    )


def test_assist_occurrence_parameters_load_with_stable_hash() -> None:
    parameters = load_model_parameters(
        ASSIST_OCCURRENCE_SCHEMA,
        ASSIST_OCCURRENCE_PARAMETERS,
    )
    assert parameters.schema.schema_version == "demo-v1.7"
    assert (
        parameters.parameter_hash
        == "fd2dc6abc8fb0e99639fe7b9e1362ca0f8ce86a43b108fd0750d7ec29c2e788e"
    )


def test_tempo_parameters_load_with_stable_hashes() -> None:
    parameters = load_model_parameters(TEMPO_SCHEMA, TEMPO_PARAMETERS)
    assert parameters.schema.schema_version == "demo-v1.8"
    assert (
        parameters.parameter_hash
        == "625a535bded781f08cfe45accd70d2581cab32bdae24ee1e0cf4a49fe6bebe4e"
    )
    assert (
        parameters.schema.schema_hash
        == "4c1470f3c53b9efcb43d1d3441ff82842140a7ebda51e899a243adbd88422ddb"
    )


def test_late_game_tempo_parameters_load_with_stable_hashes() -> None:
    parameters = load_model_parameters(LATE_TEMPO_SCHEMA, LATE_TEMPO_PARAMETERS)
    assert parameters.schema.schema_version == "demo-v1.9"
    assert (
        parameters.parameter_hash
        == "0e3ed1d24e4b4a705e13a7e93153814ef223660bf59227e4b75f1b31a0c633b5"
    )
    assert (
        parameters.schema.schema_hash
        == "8bbde2a54258631170a981fbaf654b52468dd0f4a3afeca582cabd2353aa7cb0"
    )


def test_late_game_strategy_parameters_load_with_stable_hashes() -> None:
    parameters = load_model_parameters(LATE_STRATEGY_SCHEMA, LATE_STRATEGY_PARAMETERS)
    assert parameters.schema.schema_version == "demo-v1.10"
    assert (
        parameters.parameter_hash
        == "f6277ffadb034fd17e9369efd104eb767259dab71f9f2acc356e9c99c5400e89"
    )
    assert (
        parameters.schema.schema_hash
        == "ad945566b77dbdcb0084a720e655aa6e92ad7832c9ca40e1d6da7bc5eb887b9b"
    )


def test_formal_intentional_foul_parameters_load_with_stable_hashes() -> None:
    parameters = load_model_parameters(
        FORMAL_INTENTIONAL_FOUL_SCHEMA,
        FORMAL_INTENTIONAL_FOUL_PARAMETERS,
    )
    assert parameters.schema.schema_version == "demo-v1.11"
    assert (
        parameters.parameter_hash
        == "e3ba033d59a189d6926a8b47cdfb0eb4c7d8b24b68c37e1ba14d5d591692a804"
    )
    assert (
        parameters.schema.schema_hash
        == "e67160d0292cc37056f99f4726201e29b8058f5a3377de95b16d55b514f57946"
    )


def test_non_bonus_intentional_foul_parameters_load_with_stable_hashes() -> None:
    parameters = load_model_parameters(
        NON_BONUS_INTENTIONAL_FOUL_SCHEMA,
        NON_BONUS_INTENTIONAL_FOUL_PARAMETERS,
    )
    assert parameters.schema.schema_version == "demo-v1.12"
    assert (
        parameters.parameter_hash
        == "3d935b77ec1239127aef824fc06f8a84cb11cb4c7ac8de30a997a37d32809950"
    )
    assert (
        parameters.schema.schema_hash
        == "e32e210bfe6c672d2f214759603420d475342876491f400753452c9262950374"
    )


def test_notes_and_timestamp_do_not_change_parameter_hash(tmp_path: Path) -> None:
    payload = load_json(PARAMETERS)
    metadata = payload["metadata"]
    assert isinstance(metadata, dict)
    metadata["notes"] = "different presentation note"
    metadata["created_at_utc"] = "2099-01-01T00:00:00Z"
    changed = tmp_path / "parameters.json"
    write_json(changed, payload)
    assert (
        load_model_parameters(SCHEMA, changed).parameter_hash
        == load_model_parameters(SCHEMA, PARAMETERS).parameter_hash
    )


def test_schema_cannot_enable_an_engine_forbidden_feature(tmp_path: Path) -> None:
    schema = load_json(SCHEMA)
    nodes = schema["nodes"]
    assert isinstance(nodes, dict)
    terminal = nodes["terminal_competing_risk"]
    assert isinstance(terminal, dict)
    allowed = terminal["allowed_features"]
    assert isinstance(allowed, list)
    allowed.append("overall_rating")
    changed = tmp_path / "schema.json"
    write_json(changed, schema)
    with pytest.raises(ParameterError):
        load_model_parameters(changed, PARAMETERS)


def test_parameters_reject_unknown_feature_even_at_zero_weight(tmp_path: Path) -> None:
    payload = deepcopy(load_json(PARAMETERS))
    nodes = payload["nodes"]
    assert isinstance(nodes, dict)
    terminal = nodes["terminal_competing_risk"]
    assert isinstance(terminal, dict)
    features = terminal["feature_weights"]
    assert isinstance(features, dict)
    features["overall_rating"] = {}
    changed = tmp_path / "parameters.json"
    write_json(changed, payload)
    with pytest.raises(ParameterError):
        load_model_parameters(SCHEMA, changed)


def test_parameters_reject_non_centered_softmax_weights(tmp_path: Path) -> None:
    payload = deepcopy(load_json(PARAMETERS))
    nodes = payload["nodes"]
    assert isinstance(nodes, dict)
    terminal = nodes["terminal_competing_risk"]
    assert isinstance(terminal, dict)
    features = terminal["feature_weights"]
    assert isinstance(features, dict)
    ball_pressure = features["interaction.ball_pressure"]
    assert isinstance(ball_pressure, dict)
    shot = ball_pressure["SHOT_OPPORTUNITY"]
    assert isinstance(shot, dict)
    shot["value"] = -0.1
    changed = tmp_path / "parameters.json"
    write_json(changed, payload)
    with pytest.raises(ParameterError):
        load_model_parameters(SCHEMA, changed)


def test_compiled_terminal_pressure_has_expected_direction() -> None:
    policy = CompiledParameterPolicy(load_model_parameters(SCHEMA, PARAMETERS))
    plan = IsolationPlan(1)
    low = InteractionState(
        0.0,
        0.0,
        (
            FinisherCandidateProfile(FinisherRoute.INITIATOR_SELF, 1, 0.5, 0.2, 0.1, 0.3, 11, 12),
            FinisherCandidateProfile(FinisherRoute.HELP_RELEASE, 2, 0.5, 0.2, 0.1, 0.3, 12, 13),
        ),
    )
    high = InteractionState(1.0, 0.0, low.finisher_candidates)

    def lost_ball_share(interaction: InteractionState) -> float:
        options = policy.terminal_options(plan, Coverage.BASE, interaction)
        total = sum(option.weight for option in options)
        return sum(option.weight for option in options if "LOST_BALL" in option.id) / total

    assert lost_ball_share(high) > lost_ball_share(low)


def test_compiled_policy_runs_a_reproducible_valid_segment() -> None:
    policy = CompiledParameterPolicy(load_model_parameters(SCHEMA, PARAMETERS))
    interaction = InteractionState(
        0.2,
        0.3,
        (
            FinisherCandidateProfile(FinisherRoute.INITIATOR_SELF, 1, 0.8, 0.2, 0.1, 0.4, 11, 12),
            FinisherCandidateProfile(FinisherRoute.HELP_RELEASE, 2, 0.2, 0.3, 0.2, 0.1, 12, 13),
        ),
    )
    frame = RandomFrame(20260723, RandomFrameAddress("compiled", 0, 0, 0, 0))

    def run() -> object:
        return sample_action_segment(
            plan=IsolationPlan(1),
            coverage=Coverage.BASE,
            interaction=interaction,
            offense_lineup=OFFENSE,
            defense_lineup=DEFENSE,
            policy=policy,
            frame=frame,
        )

    assert run() == run()

from __future__ import annotations

from collections.abc import Mapping

import numpy as np
import pytest

from reflect.types import (
    ActionChunk,
    ActionRepresentation,
    Constraint,
    ContractValidationError,
    ControlReference,
    ObjectBelief,
    Observation,
    Pose,
    Predicate,
    RecoveryDecision,
    RobotState,
    SceneRelation,
    SemanticGoal,
    SkillSpec,
    SkillState,
    WorldModelPrediction,
    validate_contract,
)


def valid_pose(**change: object) -> Pose:
    values: dict[str, object] = {
        "position": np.array([0.1, 0.2, 0.3]),
        "quaternion_wxyz": np.array([1.0, 0.0, 0.0, 0.0]),
    }
    values.update(change)
    return Pose(**values)  # type: ignore[arg-type]


def valid_robot_state(**change: object) -> RobotState:
    values: dict[str, object] = {"q": np.array([0.1, 0.2]), "dq": np.array([0.0, 0.0])}
    values.update(change)
    return RobotState(**values)  # type: ignore[arg-type]


def valid_constraint(**change: object) -> Constraint:
    values: dict[str, object] = {"kind": "keep_upright", "parameters": {"limit": 0.1}}
    values.update(change)
    return Constraint(**values)  # type: ignore[arg-type]


def valid_predicate(**change: object) -> Predicate:
    values: dict[str, object] = {"kind": "at_target", "parameters": {"distance_m": 0.02}}
    values.update(change)
    return Predicate(**values)  # type: ignore[arg-type]


def valid_goal(**change: object) -> SemanticGoal:
    values: dict[str, object] = {
        "goal_id": "goal-1",
        "entity_ids": ["cube-1"],
        "objective": "place cube",
        "constraints": [valid_constraint()],
        "success_predicate": valid_predicate(),
    }
    values.update(change)
    return SemanticGoal(**values)  # type: ignore[arg-type]


def valid_skill_spec(**change: object) -> SkillSpec:
    values: dict[str, object] = {
        "skill_id": "pick-1",
        "skill_type": "pick",
        "target_entities": ["cube-1"],
        "target_pose": valid_pose(),
        "constraints": [valid_constraint()],
        "success_predicate": valid_predicate(),
        "timeout_s": 1.0,
        "retry_budget": 0,
    }
    values.update(change)
    return SkillSpec(**values)  # type: ignore[arg-type]


def valid_object_belief(**change: object) -> ObjectBelief:
    values: dict[str, object] = {
        "entity_id": "cube-1",
        "label": "cube",
        "pose": np.array([0.1, 0.2, 0.3]),
        "pose_confidence": 0.9,
        "state": {"held": False},
        "state_confidence": 0.8,
        "last_seen_ns": 4,
        "provenance": ["perception"],
    }
    values.update(change)
    return ObjectBelief(**values)  # type: ignore[arg-type]


def valid_observation(**change: object) -> Observation:
    values: dict[str, object] = {
        "sequence_id": 1,
        "source_time_ns": 2,
        "received_time_ns": 3,
        "robot_state": valid_robot_state(),
        "object_beliefs": [valid_object_belief()],
        "current_skill_id": "pick-1",
        "current_phase": "approach",
    }
    values.update(change)
    return Observation(**values)  # type: ignore[arg-type]


def valid_action_chunk(**change: object) -> ActionChunk:
    values: dict[str, object] = {
        "chunk_id": "chunk-1",
        "skill_id": "pick-1",
        "source_observation_id": 1,
        "source_observation_time_ns": 2,
        "generated_time_ns": 3,
        "valid_from_ns": 4,
        "expires_at_ns": 5,
        "dt_s": 0.1,
        "actions": np.array([[0.1, 0.2], [0.3, 0.4]]),
        "representation": "JOINT_POSITION",
        "expected_phase": "approach",
        "metadata": {"policy": "baseline"},
    }
    values.update(change)
    return ActionChunk(**values)  # type: ignore[arg-type]


def valid_control_reference(**change: object) -> ControlReference:
    values: dict[str, object] = {
        "source_chunk_id": "chunk-1",
        "time_ns": 6,
        "q_ref": np.array([0.1, 0.2]),
        "dq_ref": np.array([0.0, 0.0]),
        "eef_ref": np.array([0.1, 0.2, 0.3]),
        "feedforward": np.array([0.0, 0.0]),
        "controller_mode": "joint_position",
    }
    values.update(change)
    return ControlReference(**values)  # type: ignore[arg-type]


def valid_scene_relation(**change: object) -> SceneRelation:
    values: dict[str, object] = {
        "subject_id": "cube-1",
        "predicate": "on",
        "object_id": "table-1",
        "confidence": 0.8,
        "observed_at_ns": 7,
        "provenance": ["perception"],
    }
    values.update(change)
    return SceneRelation(**values)  # type: ignore[arg-type]


def valid_world_model_prediction(**change: object) -> WorldModelPrediction:
    values: dict[str, object] = {
        "observation_id": 1,
        "candidate_id": "candidate-1",
        "horizon_s": 1.0,
        "predicted_progress": 0.2,
        "predicted_success_probability": 0.8,
        "predicted_failure_probabilities": {"collision": 0.1},
        "predicted_state": np.array([0.1, 0.2]),
        "predicted_latent": np.array([0.3, 0.4]),
        "uncertainty": 0.2,
        "inference_ms": 5.0,
    }
    values.update(change)
    return WorldModelPrediction(**values)  # type: ignore[arg-type]


def test_constructors_cover_every_shared_contract() -> None:
    contracts = [
        valid_pose(),
        valid_robot_state(),
        valid_constraint(),
        valid_predicate(),
        valid_goal(),
        valid_skill_spec(),
        valid_observation(),
        valid_action_chunk(),
        valid_control_reference(),
        valid_object_belief(),
        valid_scene_relation(),
        valid_world_model_prediction(),
    ]
    for contract in contracts:
        validate_contract(contract)

    assert SkillState.SUCCEEDED.value == "succeeded"
    assert RecoveryDecision.RETRIGGER.value == "retrigger"
    assert ActionRepresentation.JOINT_POSITION.value == "JOINT_POSITION"


def test_action_chunk_copies_and_freezes_actions() -> None:
    source = np.array([[0.1, 0.2], [0.3, 0.4]])
    chunk = valid_action_chunk(actions=source)
    source[0, 0] = 99.0
    assert chunk.actions[0, 0] == pytest.approx(0.1)
    assert chunk.actions.flags.c_contiguous
    assert not chunk.actions.flags.writeable


@pytest.mark.parametrize(
    "change, message",
    [
        ({"source_observation_id": -1}, "source_observation_id"),
        ({"expires_at_ns": 9, "valid_from_ns": 10}, "expires_at_ns"),
        ({"dt_s": 0.0}, "dt_s"),
        ({"actions": np.array([[np.nan]])}, "finite"),
        ({"representation": "NOT_A_REPRESENTATION"}, "representation"),
    ],
)
def test_action_chunk_rejects_invalid_boundaries(change: dict[str, object], message: str) -> None:
    with pytest.raises(ContractValidationError, match=message):
        valid_action_chunk(**change)


@pytest.mark.parametrize("confidence", [-0.1, 1.1])
def test_confidence_values_are_bounded(confidence: float) -> None:
    with pytest.raises(ContractValidationError, match="confidence"):
        valid_object_belief(pose_confidence=confidence)
    with pytest.raises(ContractValidationError, match="confidence"):
        valid_scene_relation(confidence=confidence)


@pytest.mark.parametrize("change", [{"sequence_id": -1}, {"source_time_ns": -1}, {"received_time_ns": -1}])
def test_observation_rejects_negative_timestamp_or_sequence(change: dict[str, object]) -> None:
    with pytest.raises(ContractValidationError):
        valid_observation(**change)


@pytest.mark.parametrize(
    "change, message",
    [
        ({"predicted_progress": np.nan}, "predicted_progress"),
        ({"predicted_success_probability": np.inf}, "predicted_success_probability"),
        ({"predicted_failure_probabilities": {"collision": np.nan}}, "finite"),
        ({"inference_ms": np.inf}, "inference_ms"),
    ],
)
def test_world_model_scores_and_latency_must_be_finite(change: dict[str, object], message: str) -> None:
    with pytest.raises(ContractValidationError, match=message):
        valid_world_model_prediction(**change)


@pytest.mark.parametrize(
    "factory, change, message",
    [
        (valid_goal, {"goal_id": ""}, "goal_id"),
        (valid_skill_spec, {"skill_id": ""}, "skill_id"),
        (valid_action_chunk, {"chunk_id": ""}, "chunk_id"),
        (valid_control_reference, {"source_chunk_id": ""}, "source_chunk_id"),
        (valid_object_belief, {"entity_id": ""}, "entity_id"),
        (valid_scene_relation, {"subject_id": ""}, "subject_id"),
        (valid_world_model_prediction, {"candidate_id": ""}, "candidate_id"),
    ],
)
def test_identifiers_must_not_be_empty(factory: object, change: dict[str, object], message: str) -> None:
    with pytest.raises(ContractValidationError, match=message):
        factory(**change)  # type: ignore[operator]


@pytest.mark.parametrize("change, message", [({"timeout_s": 0.0}, "timeout_s"), ({"retry_budget": -1}, "retry_budget")])
def test_skill_spec_requires_positive_timeout_and_non_negative_retry_budget(change: dict[str, object], message: str) -> None:
    with pytest.raises(ContractValidationError, match=message):
        valid_skill_spec(**change)


@pytest.mark.parametrize(
    "factory, field",
    [
        (valid_control_reference, "q_ref"),
        (valid_control_reference, "dq_ref"),
        (valid_control_reference, "eef_ref"),
        (valid_control_reference, "feedforward"),
        (valid_object_belief, "pose"),
        (valid_world_model_prediction, "predicted_state"),
        (valid_world_model_prediction, "predicted_latent"),
    ],
)
def test_optional_arrays_are_copied_and_frozen(factory: object, field: str) -> None:
    source = np.array([0.1, 0.2])
    contract = factory(**{field: source})  # type: ignore[operator]
    source[0] = 99.0
    copied = getattr(contract, field)
    assert copied[0] == pytest.approx(0.1)
    assert copied.flags.c_contiguous
    assert not copied.flags.writeable


def test_mappings_and_tuples_are_normalized() -> None:
    goal = valid_goal(entity_ids=["cube-1"], constraints=[valid_constraint()])
    assert goal.entity_ids == ("cube-1",)
    assert isinstance(valid_constraint().parameters, Mapping)
    with pytest.raises(TypeError):
        valid_constraint().parameters["other"] = 1  # type: ignore[index]


def test_validate_contract_rejects_unsupported_values() -> None:
    with pytest.raises(ContractValidationError, match="unsupported"):
        validate_contract("not a contract")

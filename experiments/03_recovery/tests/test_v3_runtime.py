from __future__ import annotations

import importlib

import numpy as np
import pytest


contracts = importlib.import_module("experiments.03_recovery.src.v3_contracts")
runtime = importlib.import_module("experiments.03_recovery.src.v3_runtime")


Architecture = contracts.Architecture
DecisionLevel = contracts.DecisionLevel
PRIMARY = contracts.PRIMARY_CONTROLLER_ID
P4 = contracts.SENSITIVITY_CONTROLLER_ID
EpisodeSpec = runtime.V3EpisodeSpec


def spec(scenario: str, architecture: Architecture = Architecture.R3, *, seed: int = 20261891, controller: str = PRIMARY) -> EpisodeSpec:
    return EpisodeSpec(architecture, scenario, seed, controller)


def test_realization_pairs_share_physics_and_precheck_can_retain_not_run() -> None:
    anchor = contracts.make_realization("anchor-nominal", 20261891)
    disturbed = contracts.make_realization("control-impulse", 20261891)
    assert anchor.q0 == disturbed.q0
    assert anchor.target_a_xy == disturbed.target_a_xy
    assert runtime.precheck(spec("anchor-nominal")).disposition == "READY"
    not_run = runtime.precheck(spec("motion-path-infeasible"), force_not_run=True)
    assert not_run.disposition == "NOT_RUN"
    assert not_run.architecture_independent is True


@pytest.fixture(scope="module")
def anchor_episode() -> object:
    return runtime.run_episode(spec("anchor-nominal"))


@pytest.fixture(scope="module")
def impulse_episode() -> object:
    return runtime.run_episode(spec("control-impulse"))


def test_sampled_tick_is_reached_and_torque_impulse_changes_physical_bytes(anchor_episode: object, impulse_episode: object) -> None:
    tick = impulse_episode.realization.injection_tick
    assert impulse_episode.injection_rows == (tick,)
    assert int(impulse_episode.trace["tick"][tick]) == tick
    assert np.linalg.norm(impulse_episode.trace["applied_force_nm"][tick]) > 0.0
    assert np.array_equal(anchor_episode.trace["applied_force_nm"][tick], np.zeros(3))
    assert impulse_episode.trace["q"].tobytes() != anchor_episode.trace["q"].tobytes()
    assert impulse_episode.parameter_use_receipt["injection_tick"] == tick
    assert impulse_episode.parameter_use_receipt["impulse_nm"] == impulse_episode.realization.impulse_nm


def test_full_500hz_state_reference_action_torque_contact_and_envelopes(anchor_episode: object) -> None:
    required = {
        "tick", "q", "dq", "eef_xy", "q_ref", "dq_ref", "actuator_cmd_nm",
        "applied_force_nm", "contact_count", "obstacle_contact", "target_xy",
        "contact_force_norm_n", "contact_torque_norm_nm", "target_error_m", "safe_hold", "action_valid",
        "world_authorized",
    }
    assert required <= set(anchor_episode.trace)
    assert all(len(anchor_episode.trace[name]) == contracts.EPISODE_TICKS for name in required)
    assert len(anchor_episode.action_envelopes) == contracts.EPISODE_TICKS
    assert len(anchor_episode.contact_envelopes) == contracts.EPISODE_TICKS
    assert set(anchor_episode.contact_envelopes[0]) == {"tick", "contacts"}
    assert anchor_episode.executor_debug["aborted"] is False
    assert np.all(anchor_episode.trace["target_error_m"][-50:] <= 0.025)
    envelope = next(item for item in anchor_episode.action_envelopes if item["mode"] == "EXECUTE")
    assert set(envelope) == {
        "tick", "controller_id", "stack_id", "mode", "object_id", "affordance",
        "command_content_sha256", "generation_tick", "action_age_ticks",
        "cartesian_reference", "joint_reference", "executed_actuator_nm",
        "external_force_nm", "hold_reason",
    }


def test_all_realized_disturbances_change_intended_retained_bytes() -> None:
    seed = 20261892
    anchor = runtime.run_episode(spec("anchor-nominal", seed=seed))
    episodes = {name: runtime.run_episode(spec(name, seed=seed)) for name in contracts.SCENARIO_IDS[2:]}
    assert episodes["control-impulse"].trace["applied_force_nm"].tobytes() != anchor.trace["applied_force_nm"].tobytes()
    assert any(item["hold_reason"] == "COMMAND_WITHHELD" for item in episodes["control-dropout"].action_envelopes)
    assert episodes["motion-target-shift"].world_ledger[-1]["target_xy"] != anchor.world_ledger[-1]["target_xy"]
    obstacle = episodes["motion-path-infeasible"]
    assert obstacle.precheck.straight_path_blocked and obstacle.precheck.waypoint_path_clear
    assert any(item["obstacle_active"] for item in obstacle.world_ledger)
    assert np.all(obstacle.trace["action_valid"])
    for name in ("semantic-object-unavailable", "semantic-restriction-change"):
        episode = episodes[name]
        delivery = episode.realization.injection_tick + episode.realization.semantic_delay_ticks
        assert all(item["version"] == 1 for item in episode.memory_ledger if item["tick"] < delivery)
        assert any(item["version"] == 2 and item["tick"] == delivery for item in episode.memory_ledger)
        assert episode.action_envelopes[delivery]["mode"] == "HOLD"
        assert episode.action_envelopes[delivery]["object_id"] is None
        assert any(item["object_id"] == "object-b" for item in episode.commands)


def test_architectures_execute_distinct_observable_driven_sequences_and_advance_time() -> None:
    episodes = {arch: runtime.run_episode(spec("semantic-object-unavailable", arch, seed=20261893)) for arch in Architecture}
    sequences = {arch: tuple(item.level for item in episode.decisions if item.level is not DecisionLevel.NONE) for arch, episode in episodes.items()}
    assert sequences[Architecture.R0] == (DecisionLevel.CONTROL, DecisionLevel.CONTROL, DecisionLevel.SAFE_ABORT)
    assert sequences[Architecture.R1] == (DecisionLevel.SEMANTIC,)
    assert sequences[Architecture.R2] == (DecisionLevel.MOTION, DecisionLevel.MOTION, DecisionLevel.SEMANTIC)
    assert sequences[Architecture.R3] == (DecisionLevel.SEMANTIC,)
    for episode in episodes.values():
        intervention_ticks = [item.observed_tick for item in episode.decisions if item.level not in {DecisionLevel.NONE, DecisionLevel.SAFE_ABORT}]
        assert all(later - earlier >= contracts.REOBSERVE_TICKS for earlier, later in zip(intervention_ticks, intervention_ticks[1:]))
    r3 = episodes[Architecture.R3]
    assert r3.budget_resets
    assert all(item["old_content_sha256"] != item["new_content_sha256"] for item in r3.budget_resets)
    assert all(item["successful_execution_receipt_sha256"] == item["new_content_sha256"] for item in r3.budget_resets)


def test_existing_p6_and_repaired_p4_paths_have_distinct_bound_bytes() -> None:
    p6 = runtime.run_episode(spec("anchor-nominal", seed=20261894, controller=PRIMARY))
    p4 = runtime.run_episode(spec("anchor-nominal", seed=20261894, controller=P4))
    assert p6.controller_binding["call_path"] == "representations.emit_chunk:P6->reference_for_tick:P6->arm.bounded_pd"
    assert p4.controller_binding["call_path"] == "representations.emit_chunk:P4->with_p4_executor_tuning:1:dqon->reference_for_tick:P4->arm.bounded_pd"
    assert p6.controller_binding["controller_id"] != p4.controller_binding["controller_id"]
    assert p6.trajectory_bytes != p4.trajectory_bytes
    assert p6.trace["q_ref"].tobytes() != p4.trace["q_ref"].tobytes()
    assert p6.trace["actuator_cmd_nm"].tobytes() != p4.trace["actuator_cmd_nm"].tobytes()

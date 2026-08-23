from __future__ import annotations

import importlib
import hashlib

import numpy as np

world = importlib.import_module("experiments.06_world_model.world")


def _action_preimage(commands: np.ndarray) -> bytes:
    metadata = world.canonical([commands.dtype.str, list(commands.shape), world.COMMAND_DT])
    return metadata + b"\0" + commands.tobytes(order="C")


def test_split_domain_is_exact_and_disjoint() -> None:
    rows = world.scene_rows()
    assert len(rows) == 144
    assert [sum(row.partition == name for row in rows) for name in ("train", "tuning", "evaluation")] == [72, 24, 48]
    evaluation = [row for row in rows if row.partition == "evaluation"]
    assert {name: sum(row.stratum == name for row in evaluation) for name in world.STRATA} == {
        "ID": 16,
        "MASS_OOD": 8,
        "FRICTION_OOD": 8,
        "GEOMETRY_OOD": 8,
        "OBSTACLE_OOD": 8,
    }
    assert len({row.seed for row in rows}) == 144
    assert len({row.scene_id for row in rows}) == 144


def test_candidate_compiler_is_deterministic_distinct_and_has_hold() -> None:
    scene = world.generate_scene(world.scene_rows()[0])
    anchor = world.probe_anchors(scene)[0]
    first = world.compile_candidates(scene, anchor)
    second = world.compile_candidates(scene, anchor)
    assert tuple(item.strategy_id for item in first) == world.STRATEGIES
    preimages = [_action_preimage(item.commands) for item in first]
    assert len(set(preimages)) == 8
    assert len({item.action_sha256 for item in first}) == 8
    assert all(item.commands.shape == (50, 2) and item.commands.dtype == np.dtype("<f8") for item in first)
    assert all(item.action_sha256 == hashlib.sha256(preimage).hexdigest() for item, preimage in zip(first, preimages))
    assert np.array_equal(first[-1].commands, np.zeros((50, 2), dtype="<f8"))
    assert [item.action_sha256 for item in first] == [item.action_sha256 for item in second]
    assert [item.generation_counter for item in first] == [item.generation_counter for item in second]
    assert [item.perturbation_magnitude for item in first] == [item.perturbation_magnitude for item in second]
    assert all(item.pre_perturbation_sha256 == hashlib.sha256(_action_preimage(item.commands)).hexdigest() for item in first if item.generation_counter == 0)


def test_candidate_compiler_resolves_label_independent_action_collisions_without_moving_hold(monkeypatch: object) -> None:
    scene = world.generate_scene(world.scene_rows()[0])
    anchor = world.probe_anchors(scene)[0]
    zero = np.zeros((50, 2), dtype="<f8")
    monkeypatch.setattr(world, "_commands", lambda *args, **kwargs: zero.copy())

    candidates = world.compile_candidates(scene, anchor)

    assert len({_action_preimage(item.commands) for item in candidates}) == 8
    assert np.array_equal(candidates[-1].commands, zero)
    assert candidates[-1].generation_counter == 0
    assert candidates[-1].perturbation_magnitude == 0.0
    assert all(0 <= item.generation_counter <= 8 for item in candidates)
    assert all(0.0 <= item.perturbation_magnitude <= 8e-9 for item in candidates)
    assert all(np.max(np.abs(item.commands)) <= world.CONFIG["command_limit_m_s"] for item in candidates)
    assert all(item.pre_perturbation_sha256 == hashlib.sha256(_action_preimage(zero)).hexdigest() for item in candidates)


def test_branch_truth_restores_anchor_and_reproduces_exact_cost() -> None:
    scene = world.generate_scene(world.scene_rows()[0])
    anchor = world.probe_anchors(scene)[0]
    candidate = world.compile_candidates(scene, anchor)[0]
    first = world.run_candidate(scene, anchor, candidate)
    second = world.run_candidate(scene, anchor, candidate)
    assert first.anchor_restore_sha256 == anchor.restore_sha256
    assert first == second
    assert np.isfinite(first.actual_cost)
    assert first.actual_cost == world.actual_cost(
        first.position_error_m,
        first.orientation_error_rad,
        first.collision,
        first.action_energy,
        first.terminal_failure,
        first.success,
    )


def test_anchor_captures_and_restores_complete_mujoco_integration_state() -> None:
    scene = world.generate_scene(world.scene_rows()[0])
    anchor = world.probe_anchors(scene)[1]
    model, data = world._new_data(scene)
    data.time = 123.0
    data.qpos[:] = -0.25
    data.qvel[:] = 0.75
    data.qacc_warmstart[:] = 0.125
    data.mocap_pos[:] = 0.33
    data.mocap_quat[:] = (0.5, 0.5, 0.5, 0.5)

    world._apply_anchor(model, data, anchor)

    state = np.empty(anchor.state_size, dtype=np.float64)
    world.mujoco.mj_getState(model, data, state, anchor.state_spec)
    assert anchor.state_spec == int(world.mujoco.mjtState.mjSTATE_INTEGRATION)
    assert anchor.state_size == world.mujoco.mj_stateSize(model, anchor.state_spec)
    assert np.array_equal(state, np.asarray(anchor.integration_state))
    assert np.array_equal(data.mocap_pos.ravel(), np.asarray(anchor.mocap_pos))
    assert np.array_equal(data.mocap_quat.ravel(), np.asarray(anchor.mocap_quat))
    assert data.time != 123.0


def test_each_candidate_branch_begins_from_the_same_complete_anchor_state() -> None:
    scene = world.generate_scene(world.scene_rows()[0])
    anchor = world.probe_anchors(scene)[1]
    candidates = world.compile_candidates(scene, anchor)

    direct = world.run_candidate(scene, anchor, candidates[0])
    hold = world.run_candidate(scene, anchor, candidates[-1])

    assert direct.anchor_restore_sha256 == anchor.restore_sha256
    assert hold.anchor_restore_sha256 == anchor.restore_sha256

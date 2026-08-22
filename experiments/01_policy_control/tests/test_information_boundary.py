from __future__ import annotations

import importlib
import inspect
import numpy as np
from dataclasses import replace

from reflect.types import ObjectBelief, Pose

from .helpers import config, policy_input


rep = importlib.import_module("experiments.01_policy_control.src.representations")
contracts = importlib.import_module("experiments.01_policy_control.src.contracts")


def test_all_stacks_emit_from_one_immutable_snapshot_without_live_target_argument() -> None:
    cfg = config()
    value = policy_input()
    before = value.skill.target_pose.position.tobytes()
    first = {stack: rep.emit_chunk(stack, value, cfg).actions.tobytes() for stack in contracts.CommandStack}
    second = {stack: rep.emit_chunk(stack, value, cfg).actions.tobytes() for stack in contracts.CommandStack}
    assert first == second and value.skill.target_pose.position.tobytes() == before
    assert "target" not in inspect.signature(rep.emit_chunk).parameters
    assert "scenario" not in inspect.signature(rep.reference_for_tick).parameters


def test_retained_external_mutation_cannot_change_full_valid_and_safehold_sequences() -> None:
    cfg = config()
    base = policy_input()
    external_target = np.array([0.62, 0.08])
    scenario_current_target = external_target.copy()
    observation = replace(base.observation, object_beliefs=(ObjectBelief("target", "target", external_target, 1.0, {}, 1.0, 0, ("synthetic",)),))
    skill = replace(base.skill, target_pose=Pose(np.array([external_target[0], external_target[1], 0.0]), np.array([1.0, 0.0, 0.0, 0.0])))
    value = contracts.PolicyInput(observation, skill, base.response_time_ns, base.policy_period_ns, base.q_initial, base.q_initial_target)
    def sequence(stack, retained):
        chunk = rep.emit_chunk(stack, retained, cfg)
        state = rep.initial_executor_state(retained.q_initial)
        rows = []
        for tick in range(cfg.timing.episode_ticks):
            now_ns = tick * 2_000_000
            if chunk.valid_from_ns <= now_ns < chunk.expires_at_ns:
                reference, state, _ = rep.reference_for_tick(stack, chunk, retained.q_initial, np.zeros(3), now_ns, state, cfg)
                rows.append(reference.q_ref.tobytes())
            else:
                if stack is contracts.CommandStack.P5 and state.p5_planner_enabled:
                    state = rep.p5_transition(state, "SAFE_HOLD")
                rows.append(b"SAFE_HOLD")
        return chunk.actions.tobytes(), tuple(rows), state
    for stack in contracts.CommandStack:
        before = sequence(stack, value)
        external_target[:] = [-9.0, 9.0]
        scenario_current_target[:] = [9.0, -9.0]
        after = sequence(stack, value)
        assert before[:2] == after[:2]
        if stack is contracts.CommandStack.P5:
            assert not after[2].p5_planner_enabled
    assert "target" not in inspect.signature(rep.emit_chunk).parameters
    assert "scenario" not in inspect.signature(rep.reference_for_tick).parameters

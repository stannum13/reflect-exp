from __future__ import annotations

import importlib
import inspect
import numpy as np
from dataclasses import replace

from reflect.types import ObjectBelief, Pose

from .helpers import config, policy_input


rep = importlib.import_module("experiments.01_policy_control.src.representations")
contracts = importlib.import_module("experiments.01_policy_control.src.contracts")
evaluate = importlib.import_module("experiments.01_policy_control.src.evaluate")
timing = importlib.import_module("experiments.01_policy_control.src.timing")


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
    scenario = evaluate.generate_scenario(17, cfg)
    target_owner = evaluate.EpisodeTargetOwner.from_scenario(scenario)
    external_target = np.array([0.62, 0.08])
    target_owner.set_target(external_target)
    captured_target = target_owner.snapshot()
    observation = replace(
        base.observation,
        object_beliefs=(ObjectBelief("target", "target", captured_target, 1.0, {}, 1.0, 0, ("synthetic",)),),
    )
    skill = replace(
        base.skill,
        target_pose=Pose(
            np.array([captured_target[0], captured_target[1], 0.0]),
            np.array([1.0, 0.0, 0.0, 0.0]),
        ),
    )
    value = contracts.PolicyInput(observation, skill, 0, base.policy_period_ns, base.q_initial, base.q_initial_target)

    def sequence(stack, retained):
        chunk = rep.emit_chunk(stack, retained, cfg)
        state = timing.SchedulerState.initial(retained.q_initial, cfg, rollout_id=f"barrier-{stack.value}")
        references = []
        safe_holds = []
        for tick in range(cfg.timing.episode_ticks):
            request = None
            if tick == 0:
                request = timing.PolicyRequest(
                    retained.observation,
                    tick,
                    retained.policy_period_ns // 2_000_000,
                    chunk,
                )
            transition = timing.transition_tick(state, cfg, request=request, latency_ticks=0)
            state = transition.state
            if transition.control_reference is not None:
                references.append(
                    (
                        transition.control_reference.q_ref.tobytes(),
                        transition.control_reference.dq_ref.tobytes(),
                    )
                )
            if transition.safe_hold:
                assert transition.safe_hold_command is not None
                assert np.array_equal(transition.safe_hold_command.q_ref, transition.state.q)
                assert np.array_equal(transition.safe_hold_command.dq_ref, np.zeros_like(transition.state.dq))
                safe_holds.append(
                    (
                        transition.safe_hold_command.disposition,
                        transition.safe_hold_command.q_ref.tobytes(),
                        transition.safe_hold_command.dq_ref.tobytes(),
                    )
                )
        return chunk.actions.tobytes(), tuple(references), tuple(safe_holds), state

    for stack in contracts.CommandStack:
        before = sequence(stack, value)
        external_target[:] = [-9.0, 9.0]
        target_owner.set_target(np.array([9.0, -9.0]))
        after = sequence(stack, value)
        assert before[:3] == after[:3]
        assert before[1]
        assert before[2]
        if stack is contracts.CommandStack.P5:
            assert not after[3].executor_state.p5_planner_enabled
    forbidden = {"target", "scenario", "target_owner", "live_target"}
    emit_parameters = set(inspect.signature(rep.emit_chunk).parameters)
    reference_parameters = set(inspect.signature(rep.reference_for_tick).parameters)
    assert emit_parameters == {"stack", "policy_input", "config"}
    assert reference_parameters == {"stack", "chunk", "q", "dq", "time_ns", "state", "config"}
    assert forbidden.isdisjoint(emit_parameters)
    assert forbidden.isdisjoint(reference_parameters)

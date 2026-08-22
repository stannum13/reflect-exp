from __future__ import annotations

import importlib
import inspect
import numpy as np

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


def test_full_500hz_reference_sequences_repeat_for_all_stacks() -> None:
    cfg = config()
    value = policy_input()
    def sequence(stack):
        chunk = rep.emit_chunk(stack, value, cfg)
        state = rep.initial_executor_state(value.q_initial)
        rows = []
        for tick in range(cfg.timing.episode_ticks):
            reference, state, _ = rep.reference_for_tick(stack, chunk, value.q_initial, np.zeros(3), tick * 2_000_000, state, cfg)
            rows.append(reference.q_ref.tobytes())
        return tuple(rows)
    for stack in contracts.CommandStack:
        assert sequence(stack) == sequence(stack)

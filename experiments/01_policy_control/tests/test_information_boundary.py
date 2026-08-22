from __future__ import annotations

import importlib
import inspect

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

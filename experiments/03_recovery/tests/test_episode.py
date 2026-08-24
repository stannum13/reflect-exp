from __future__ import annotations

import importlib

import numpy as np
import pytest


c = importlib.import_module("experiments.03_recovery.src.contracts")
cell = importlib.import_module("experiments.03_recovery.src.cell")
episode = importlib.import_module("experiments.03_recovery.src.episode")


@pytest.fixture(scope="module")
def representative() -> dict[tuple[c.Architecture, str], object]:
    selected = {item.scenario_id: item for item in cell.scenario_specs() if item.scenario_id in {"anchor-none", "control-impulse", "motion-target-shift", "semantic-object-unavailable"}}
    result = {}
    for architecture in c.Architecture:
        for scenario_id, scenario in selected.items():
            spec = c.EpisodeSpec(
                f"representative-{architecture.value}-{scenario_id}-20261601",
                architecture,
                scenario_id,
                scenario.domain,
                20261601,
                "P6-res0p5-slew48",
                False,
            )
            result[(architecture, scenario_id)] = episode.run_episode(spec)
    return result


def test_representative_success_pattern(representative: dict[tuple[c.Architecture, str], object]) -> None:
    for architecture in c.Architecture:
        assert representative[(architecture, "anchor-none")].terminal is c.TerminalDisposition.SUCCESS
        assert representative[(architecture, "control-impulse")].terminal is c.TerminalDisposition.SUCCESS
    assert representative[(c.Architecture.LOCAL_ONLY, "motion-target-shift")].terminal is c.TerminalDisposition.SAFE_ABORT
    assert representative[(c.Architecture.LOCAL_ONLY, "semantic-object-unavailable")].terminal is c.TerminalDisposition.SAFE_ABORT
    for architecture in (c.Architecture.SEMANTIC_ALWAYS, c.Architecture.MOTION_THEN_SEMANTIC, c.Architecture.LAYER_MATCHED):
        assert representative[(architecture, "motion-target-shift")].terminal is c.TerminalDisposition.SUCCESS
        assert representative[(architecture, "semantic-object-unavailable")].terminal is c.TerminalDisposition.SUCCESS


def test_layer_matched_selects_lowest_sufficient_level(representative: dict[tuple[c.Architecture, str], object]) -> None:
    expected = {
        "control-impulse": c.RecoveryLevel.CONTROL,
        "motion-target-shift": c.RecoveryLevel.MOTION,
        "semantic-object-unavailable": c.RecoveryLevel.SEMANTIC,
    }
    for scenario_id, level in expected.items():
        evidence = representative[(c.Architecture.LAYER_MATCHED, scenario_id)]
        assert evidence.recovery_decisions[0].level is level
        assert evidence.metrics["lowest_sufficient_correct"]


def test_trace_is_full_500hz_finite_and_read_only(representative: dict[tuple[c.Architecture, str], object]) -> None:
    evidence = representative[(c.Architecture.LAYER_MATCHED, "motion-target-shift")]
    assert evidence.trace["tick"].shape == (3125,)
    for name in ("q", "dq", "q_ref", "dq_ref", "action", "torque"):
        assert evidence.trace[name].shape == (3125, 3)
        assert np.isfinite(evidence.trace[name]).all()
        assert not evidence.trace[name].flags.writeable
    for name in ("target_error_m", "action_age_s", "safe_hold", "saturation", "clamp", "discontinuity"):
        assert evidence.trace[name].shape == (3125,)
        assert not evidence.trace[name].flags.writeable


def test_cause_is_scorer_only_and_decisions_use_observables(representative: dict[tuple[c.Architecture, str], object]) -> None:
    evidence = representative[(c.Architecture.LAYER_MATCHED, "semantic-object-unavailable")]
    assert evidence.scorer["hidden_cause"] == "SEMANTIC_OBJECT_UNAVAILABLE"
    assert all("cause" not in c.canonical_bytes(item).decode("ascii").lower() for item in evidence.recovery_decisions)
    assert all("scenario" not in c.canonical_bytes(item).decode("ascii").lower() for item in evidence.recovery_decisions)
    assert evidence.semantic_plans[0].target_object_id == "object-a"
    assert evidence.semantic_plans[-1].target_object_id == "object-b"


def test_every_episode_has_complete_semantic_memory_motion_and_terminal_evidence(representative: dict[tuple[c.Architecture, str], object]) -> None:
    for evidence in representative.values():
        assert evidence.semantic_plans
        assert evidence.memory_snapshots
        assert evidence.motion_commands
        assert evidence.scorer
        assert evidence.metrics["terminal_disposition"] == evidence.terminal.value
        assert evidence.metrics["unsafe_count"] == 0
        assert evidence.metrics["forbidden_action_count"] == 0


def test_repaired_p4_adapter_executes_without_retuning() -> None:
    scenario = cell.scenario_specs()[4]
    spec = c.EpisodeSpec("sensitivity-R3-motion-target-shift-20261601", c.Architecture.LAYER_MATCHED, scenario.scenario_id, scenario.domain, 20261601, "P4-lookahead1-dqon", True)
    evidence = episode.run_episode(spec)
    assert evidence.controller_fingerprint["lookahead_ticks"] == 1
    assert evidence.controller_fingerprint["dq_feedforward"] is True
    assert evidence.terminal is c.TerminalDisposition.SUCCESS

from __future__ import annotations

import importlib

import pytest


c = importlib.import_module("experiments.03_recovery.src.contracts")
cell = importlib.import_module("experiments.03_recovery.src.cell")


def test_exact_eight_frozen_scenarios_and_schedule() -> None:
    rows = cell.scenario_specs()
    assert tuple(item.scenario_id for item in rows) == (
        "anchor-none",
        "anchor-slow-policy",
        "control-impulse",
        "control-dropout",
        "motion-target-shift",
        "motion-path-infeasible",
        "semantic-object-unavailable",
        "semantic-restriction-change",
    )
    assert tuple(item.domain for item in rows) == (
        c.ScenarioDomain.ANCHOR,
        c.ScenarioDomain.ANCHOR,
        c.ScenarioDomain.CONTROL,
        c.ScenarioDomain.CONTROL,
        c.ScenarioDomain.MOTION,
        c.ScenarioDomain.MOTION,
        c.ScenarioDomain.SEMANTIC,
        c.ScenarioDomain.SEMANTIC,
    )
    assert all(item.injection_tick is None for item in rows[:2])
    assert all(item.injection_tick == 750 for item in rows[2:])
    assert len({item.sha256 for item in rows}) == 8


def test_magnitudes_are_frozen_and_not_mutable() -> None:
    by_id = {item.scenario_id: item for item in cell.scenario_specs()}
    assert by_id["anchor-slow-policy"].parameters == (("policy_delay_ticks", 25.0),)
    assert by_id["control-impulse"].parameters == (("impulse_dq_rad_s", 0.06),)
    assert by_id["control-dropout"].parameters == (("dropout_ticks", 25.0),)
    assert by_id["motion-target-shift"].parameters == (("target_shift_m", 0.06),)
    with pytest.raises(Exception):
        by_id["control-impulse"].parameters += (("adaptive", 1.0),)


def test_precheck_is_architecture_independent_and_fails_closed() -> None:
    for scenario in cell.scenario_specs():
        receipt = cell.precheck(scenario, "P6-res0p5-slew48")
        assert receipt.feasible
        assert receipt.architecture_domain_sha256 == receipt.geometry_sha256
        assert receipt.scenario_sha256 == scenario.sha256
    with pytest.raises(ValueError):
        cell.precheck(cell.scenario_specs()[0], "unfrozen-controller")


def test_full_identity_domain_is_exact_and_nonoverlapping() -> None:
    specs = cell.episode_specs()
    assert len(specs) == 288
    assert len({item.episode_id for item in specs}) == 288
    primary = [item for item in specs if not item.sensitivity]
    sensitivity = [item for item in specs if item.sensitivity]
    assert len(primary) == 256 and len(sensitivity) == 32
    assert {item.seed for item in primary} == set(range(20261601, 20261609))
    assert {item.seed for item in sensitivity} == set(range(20261601, 20261605))
    assert {item.architecture for item in sensitivity} == {c.Architecture.LAYER_MATCHED}


def test_semantic_cell_fails_closed_on_stale_or_unauthorized_fact() -> None:
    state = cell.SemanticCell.initial()
    stale = cell.replace_fact(state.memory, "object-a", stale=True)
    with pytest.raises(cell.SemanticPlanningError):
        cell.plan_skill(stale, preferred_object_id="object-a")
    forbidden = cell.replace_fact(state.memory, "object-a", restrictions=("FORBIDDEN",))
    with pytest.raises(cell.SemanticPlanningError):
        cell.plan_skill(forbidden, preferred_object_id="object-a")


def test_semantic_replan_selects_the_authorized_alternative() -> None:
    memory = cell.replace_fact(cell.SemanticCell.initial().memory, "object-a", available=False, observed_tick=750)
    assert cell.plan_skill(memory).target_object_id == "object-b"

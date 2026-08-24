from __future__ import annotations

import copy
import importlib

import pytest


c = importlib.import_module("experiments.03_recovery.src.contracts")
cell = importlib.import_module("experiments.03_recovery.src.cell")
a = importlib.import_module("experiments.03_recovery.src.analyze")


def supporting_rows() -> list[dict[str, object]]:
    rows = []
    scenarios = [item for item in cell.scenario_specs() if item.domain is not c.ScenarioDomain.ANCHOR]
    for architecture in c.Architecture:
        for scenario in scenarios:
            for seed in (20261601, 20261602):
                success = architecture is not c.Architecture.LOCAL_ONLY or scenario.domain is c.ScenarioDomain.CONTROL
                semantic = int(architecture is c.Architecture.SEMANTIC_ALWAYS or scenario.domain is c.ScenarioDomain.SEMANTIC and architecture in {c.Architecture.MOTION_THEN_SEMANTIC, c.Architecture.LAYER_MATCHED})
                motion = int(architecture is c.Architecture.MOTION_THEN_SEMANTIC or scenario.domain is c.ScenarioDomain.MOTION and architecture is c.Architecture.LAYER_MATCHED)
                local = int(architecture is c.Architecture.LOCAL_ONLY or scenario.domain is c.ScenarioDomain.CONTROL and architecture is c.Architecture.LAYER_MATCHED)
                rows.append({
                    "episode_id": f"{architecture.value}-{scenario.scenario_id}-{seed}",
                    "architecture": architecture.value,
                    "scenario_id": scenario.scenario_id,
                    "scenario_domain": scenario.domain.value,
                    "seed": seed,
                    "controller_id": cell.PRIMARY_CONTROLLER,
                    "sensitivity": False,
                    "eventual_success": success,
                    "unsafe_count": 0,
                    "forbidden_action_count": 0,
                    "semantic_replans": semantic,
                    "motion_replans": motion,
                    "bounded_local_recoveries": local,
                    "lowest_sufficient_correct": architecture is c.Architecture.LAYER_MATCHED,
                    "repeated_state_retry_loop": False,
                    "first_recovery_level": scenario.intended_level.value if architecture is c.Architecture.LAYER_MATCHED else "CONTROL",
                    "lowest_sufficient_level": scenario.intended_level.value,
                    "terminal_disposition": "SUCCESS" if success else "SAFE_ABORT",
                    "attempt_outcome": "VALID",
                })
    return rows


def test_all_six_support_gates_pass_on_declared_pattern() -> None:
    result = a.evaluate_gates(supporting_rows(), expected_primary_count=48)
    assert result["outcome"] == "SUPPORTS_LAYER_MATCHED_HIERARCHY"
    assert [item["passed"] for item in result["gates"]] == [True] * 6


@pytest.mark.parametrize("gate_index", range(6))
def test_each_support_gate_can_fail_without_threshold_adaptation(gate_index: int) -> None:
    rows = supporting_rows()
    r3 = [item for item in rows if item["architecture"] == "R3"]
    if gate_index == 0:
        r3[0]["unsafe_count"] = 1
    elif gate_index == 1:
        for item in rows:
            if item["architecture"] == "R0" and item["scenario_domain"] in {"MOTION", "SEMANTIC"}:
                item["eventual_success"] = True
    elif gate_index == 2:
        for item in r3:
            item["semantic_replans"] = 1
    elif gate_index == 3:
        for item in r3:
            if item["scenario_domain"] == "CONTROL":
                item["motion_replans"] = 1
    elif gate_index == 4:
        for item in r3[:4]:
            item["lowest_sufficient_correct"] = False
    else:
        for item in r3:
            if item["scenario_domain"] == "CONTROL":
                item["eventual_success"] = False
    result = a.evaluate_gates(rows, expected_primary_count=48)
    assert result["gates"][gate_index]["passed"] is False
    assert result["outcome"] in {"NOT_SUPPORTED", "INCONCLUSIVE"}


def test_paired_contrasts_are_domain_stratified_and_bootstrap_is_deterministic() -> None:
    rows = supporting_rows()
    paired = a.paired_case_rows(rows)
    assert len(paired) == 36
    assert {(item["comparator"], item["scenario_domain"]) for item in paired} == {
        (architecture, domain) for architecture in ("R0", "R1", "R2") for domain in ("CONTROL", "MOTION", "SEMANTIC")
    }
    first_results, first_draws = a.bootstrap_contrasts(paired, draws=10_000)
    second_results, second_draws = a.bootstrap_contrasts(paired, draws=10_000)
    assert first_results == second_results and first_draws == second_draws
    assert len(first_draws) == 90_000
    assert len({item["draw_seed"] for item in first_draws}) == 90_000


def test_confusion_and_class_absent_annotations_are_explicit() -> None:
    rows = supporting_rows()
    confusion = a.lowest_sufficient_confusion(rows)
    assert sum(item["count"] for item in confusion) == 12
    samples = a.sample_index(rows)
    r0_motion_working = next(item for item in samples if item["architecture"] == "R0" and item["scenario_domain"] == "MOTION" and item["requested_class"] == "WORKING")
    assert r0_motion_working["observed_class"] == "CLASS_NOT_OBSERVED"
    assert r0_motion_working["denominator"] == 4

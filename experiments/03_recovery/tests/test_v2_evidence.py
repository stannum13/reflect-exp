import importlib


evidence = importlib.import_module("experiments.03_recovery.run_v2")


def test_analysis_gates_are_paired_and_include_realization_gate():
    assert evidence.GATE_NAMES == (
        "safety", "r3_vs_r0", "r3_vs_r1", "control_efficiency",
        "assignment_and_audit", "paired_domains", "realization_variation",
    )


def test_raw_episode_file_set_retains_exact_execution_bytes():
    assert {"action.bin", "trajectory.bin", "memory-events.jsonl", "trace.npz", "scorer.json", "terminal.json"} <= set(evidence.EPISODE_FILES)

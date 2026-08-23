from __future__ import annotations

import importlib
import hashlib
import json
from pathlib import Path


probe = importlib.import_module("experiments.01_policy_control.engineering_p2_rescue")


def test_domains_are_exact_disjoint_and_bounded() -> None:
    assert probe.HORIZONS == (.05, .075, .1)
    assert probe.SLEWS == (24.0, 32.0, 48.0)
    assert probe.TUNING_CONDITIONS == ("core-20-000-1", "core-10-300-2", "core-05-700-2")
    assert len(probe.CORE_CONDITIONS) == 24
    assert probe.FAULT_CONDITIONS == ("probe-drop", "probe-out-of-order")
    assert len(probe.TUNING_SEEDS) == len(probe.EVALUATION_SEEDS) == len(probe.FAULT_SEEDS) == 4
    assert not (set(probe.TUNING_SEEDS) & set(probe.EVALUATION_SEEDS) or set(probe.TUNING_SEEDS) & set(probe.FAULT_SEEDS) or set(probe.EVALUATION_SEEDS) & set(probe.FAULT_SEEDS))
    assert probe.DECLARED_ROLLOUTS == {"tuning": 108, "evaluation": 288, "fault": 16, "total": 412}


def test_selection_is_mechanical_and_tie_broken_by_variant_id() -> None:
    rows=[]
    for variant,working,recovered,clamp,disc in (("z",10,20,.02,.03),("a",10,20,.01,.04),("b",10,20,.01,.04),("c",9,30,0.,0.)):
        rows.append({"variant_id":variant,"absolute_working":working,"metrics":{"recovered_events":recovered,"clamp_fraction":clamp,"discontinuity_mean":disc}})
    assert probe.select_top_two(rows) == ("a","b")


def test_paired_interval_is_deterministic_and_uses_complete_pairs() -> None:
    cells=[{"seed":seed,"condition_id":condition,"difference":float(seed-index)} for seed in range(4) for index,condition in enumerate(("a","b"))]
    first=probe.paired_interval(cells,seed=71)
    assert first==probe.paired_interval(cells,seed=71)
    assert first["n_pairs"]==8
    bad=cells[:-1]
    try:probe.paired_interval(bad,seed=71)
    except ValueError as exc:assert "rectangular" in str(exc)
    else:raise AssertionError("incomplete paired domain accepted")


def test_committed_evidence_receipt_binds_reconstructable_raw_when_present() -> None:
    root=Path(probe.__file__).resolve().parent
    receipt=json.loads((root/"ENGINEERING_P2_RESCUE_EVIDENCE.json").read_text())
    evidence=Path(probe.ROOT)/receipt["evidence"]["relative_path"]
    assert receipt["disposition"].endswith("NOT_READY_FOR_FORMAL_P4_PILOT")
    if evidence.is_dir():
        rows=[]
        for path in sorted(x for x in evidence.rglob("*") if x.is_file()):
            payload=path.read_bytes();rows.append({"path":path.relative_to(evidence).as_posix(),"bytes":len(payload),"sha256":hashlib.sha256(payload).hexdigest()})
        assert len(rows)==receipt["evidence"]["files"]
        assert sum(row["bytes"] for row in rows)==receipt["evidence"]["bytes"]
        assert hashlib.sha256(probe.canonical(rows)).hexdigest()==receipt["evidence"]["inventory_sha256"]

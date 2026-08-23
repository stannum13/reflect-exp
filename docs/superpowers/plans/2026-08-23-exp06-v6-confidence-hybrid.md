# Experiment 06 v6 Confidence Hybrid Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement and run the frozen W5 confidence-gated hybrid on a wholly new Exp06 namespace.

**Architecture:** Extend the existing experiment-local world/model/run modules. W5 calibration is a small immutable artifact derived from training-normalized truth-free scores and tuning outcomes; evaluation consumes it without fitting or tuning.

**Tech Stack:** Python 3.11, NumPy 2.4.6, MuJoCo 3.12.0, pytest.

## Global Constraints

- Preserve Exp06 v1-v5 byte-for-byte.
- Freeze `exp06-v6`, `scene-v6-cycle`, q=.25/.50/.75, coverage, tie, and gate before outcomes.
- Fit on train, calibrate/select on tune, evaluate once on untouched evaluation.
- No dependencies or generalized publication framework.

---

### Task 1: Freeze v6 domains

**Files:** Modify `experiments/06_world_model/world.py`; test `experiments/06_world_model/tests/test_world.py`.

**Produces:** `scene_rows()` with exact v6 identities and split.

- [ ] Add a failing test that asserts 72/24/48, 16+8x4 evaluation strata, `exp06-v6/` IDs, and zero ID/seed overlap with v3-v5.
- [ ] Run `pytest experiments/06_world_model/tests/test_world.py -q`; expect the namespace test to fail.
- [ ] Change only the scene namespace and seed salt to the frozen v6 values.
- [ ] Rerun the test; expect pass.
- [ ] Commit world and test.

### Task 2: Implement W5 calibration and selection

**Files:** Modify `experiments/06_world_model/model.py`; test `experiments/06_world_model/tests/test_model.py`.

**Produces:** `HybridCalibration`, `calibrate_w5(training, tuning, fitted)`, truth-free `w5_confidence`, and W5 selections.

- [ ] Add failing leakage, ancestry, fixed-quantile, coverage, tie-order, and truth-mutation tests.
- [ ] Run focused model tests; expect missing W5 APIs/failures.
- [ ] Implement the four-component score, fixed threshold selection, immutable hashes/parents, W5 prediction/selection, metrics, and exact gate.
- [ ] Rerun focused model tests; expect pass.
- [ ] Commit model and tests.

### Task 3: Bind run, reconstruction, latency, and evidence

**Files:** Modify `experiments/06_world_model/run.py`; test `experiments/06_world_model/tests/test_run.py`.

**Produces:** raw `calibration.json`, derived W5 artifacts, measured K=8 latency, and authenticated reconstruction.

- [ ] Add failing tests that monkeypatch fitting/calibration during evaluation reconstruction, reject calibration/source tamper, require exact raw files, and reproduce W5 outputs.
- [ ] Run focused run tests; expect failures.
- [ ] Fit/calibrate before evaluation, retain calibration ancestry/hash, make derivation consume frozen models/calibration, measure full-anchor W5 latency, and extend gate/annotations/recipe.
- [ ] Rerun all Exp06 tests and `git diff --check`; expect pass.
- [ ] Commit run and tests.

### Task 4: Execute and seal v6

**Files:** Create `experiments/06_world_model/results/model-quality-v6/` and `experiments/06_world_model/MODEL_QUALITY_V6.md`.

**Produces:** one immutable engineering result and report.

- [ ] Commit Tasks 1-3 before running any v6 outcome.
- [ ] Run the exact full matrix once; do not alter candidates or thresholds afterward.
- [ ] Reconstruct into an absent clean directory and require byte-equal derived output.
- [ ] Independently recompute counts, overlap, hashes, metrics, strata, latency, coverage, annotations, and gate.
- [ ] Write the honest report, including every failed gate and limitation.
- [ ] Run all Exp06 tests and final reconstruction, then commit only v6 evidence/report.

# V3 Event-Continuation Authentication Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace self-attested analytic Gate 5 candidates with exact-state MuJoCo continuations independently scored and recomputed by Gate 8.

**Architecture:** `v3_runtime.py` owns closed event snapshots and deterministic restoration/continuation. `v3_scorer.py` owns candidate validation and sufficiency. `v3_outcome.py` orchestrates exactly three candidates per event, while `v3_outcome_analysis.py` recomputes their integrity for Gate 8.

**Tech Stack:** Python 3.11, MuJoCo, NumPy, canonical JSON, SHA-256, pytest.

## Global Constraints

- Never execute held-out outcome seeds `20261801..20261810`.
- Never create `results/hierarchical-recovery-v3`.
- Use calibration seeds only for source verification and evidence resealing.
- Preserve create-only, recursive, symlink-rejecting evidence semantics.

---

### Task 1: Runtime snapshot and continuation contract

**Files:**
- Modify: `experiments/03_recovery/tests/test_v3_runtime.py`
- Modify: `experiments/03_recovery/src/v3_runtime.py`

**Interfaces:**
- Produces: authenticated complete failure-event snapshots and `run_counterfactual_continuation(raw, event_state, level, window_ticks=25)`.

- [ ] Add tests asserting complete simulator/logical state fields, exact restoration identity, three forced levels, fixed window, and distinct raw traces.
- [ ] Run the tests and verify RED because restoration/continuation evidence is absent.
- [ ] Implement canonical snapshot serialization, restoration, and fixed-window continuation.
- [ ] Run the focused runtime tests GREEN.
- [ ] Commit runtime and tests atomically.

### Task 2: Independent candidate scorer and per-event orchestration

**Files:**
- Modify: `experiments/03_recovery/tests/test_v3_scorer.py`
- Modify: `experiments/03_recovery/tests/test_v3_outcome.py`
- Modify: `experiments/03_recovery/src/v3_scorer.py`
- Modify: `experiments/03_recovery/src/v3_outcome.py`

**Interfaces:**
- Consumes: runtime continuation raw evidence.
- Produces: `score_counterfactual_candidate(event_state, candidate)` and exactly three independently scored candidates per retained event.

- [ ] Add tests for exactly three runtime/scorer calls per event, dropout `2 -> 6`, independent sufficiency, and raw/terminal/member tamper rejection.
- [ ] Run tests and verify RED on current analytic/self-attested candidates.
- [ ] Implement scorer-owned receipts and replace analytic candidate construction.
- [ ] Run scorer/outcome tests GREEN.
- [ ] Commit source/tests atomically.

### Task 3: Gate 8 recomputation

**Files:**
- Modify: `experiments/03_recovery/tests/test_v3_outcome.py`
- Modify: `experiments/03_recovery/src/v3_outcome_analysis.py`

**Interfaces:**
- Consumes: retained event snapshots, candidate raw evidence, and score receipts.
- Produces: internally recomputed `cause` construct-integrity status.

- [ ] Add tests that forge labels, booleans, trace/member hashes, terminal data, and scorer receipts.
- [ ] Run tests and verify RED because Gate 8 trusts self-attestation.
- [ ] Recompute candidate hashes and independent scores inside Gate 8.
- [ ] Run focused tests GREEN and commit atomically.

### Task 4: Verification and calibration-only reseal

**Files:**
- Update: ignored `results/hierarchical-recovery-v3-qualification`
- Replace: tracked qualification archive/manifest/report authentication artifacts.

**Interfaces:**
- Produces: source commit, byte-exact reconstructed qualification, content-addressed archive, canonical report, and clean verification receipts.

- [ ] Run focused regression tests, V3 selection, and full Experiment 03 suite with bytecode caching disabled.
- [ ] Commit source/tests and record the exact source commit.
- [ ] Regenerate calibration qualification only, reconstruct it byte-exactly, publish the deterministic archive, and regenerate the canonical report/authentication.
- [ ] Run archive extraction, report authentication, recursive inventory, source/config/environment, and no-outcome checks.
- [ ] Commit evidence artifacts and report exact hashes without self-reviewing outcome readiness.

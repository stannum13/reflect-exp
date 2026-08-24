# Exp13 Direct Hierarchy Outcome Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Freeze, execute, reconstruct, and publish the 540-cell Exp13 direct hierarchy outcome without any causal-lowest claim.

**Architecture:** Add one backward-compatible realization/precheck injection seam to the production V3 MuJoCo kernel. A compact Exp13 module owns the frozen matrix, fresh realization namespace, independent raw scorer, paired bootstrap analysis, create-only evidence lifecycle, reconstruction, archive, and report.

**Tech Stack:** Python 3.11, MuJoCo, NumPy, pytest, Ruff, deterministic canonical JSON/CSV/SVG/PNG/tar evidence.

## Global Constraints

- V3 remains `REJECTED_CAUSAL_AUTH`; do not execute V3 outcome seeds or create its outcome root.
- Exp13 matrix is exactly 480 P6 primary cells plus 60 R3/P4 sensitivity cells.
- Primary seeds are exactly `20261901..20261910`; sensitivity uses the first five.
- No counterfactual continuation, causal-minimality, or lowest-level value enters Exp13 evidence or gates.
- Outcome execution begins only after the source commit and atomic freeze commit.

---

### Task 1: Production-kernel injection seam and frozen matrix

**Files:**
- Modify: `experiments/03_recovery/src/v3_runtime.py`
- Create: `experiments/13_direct_hierarchy/__init__.py`
- Create: `experiments/13_direct_hierarchy/src/__init__.py`
- Create: `experiments/13_direct_hierarchy/src/experiment.py`
- Test: `experiments/13_direct_hierarchy/tests/test_experiment.py`

**Interfaces:**
- `run_episode(spec, realization_override=None, precheck_override=None)` preserves default V3 behavior.
- `matrix_specs() -> tuple[DirectSpec, ...]` returns exactly 540 unique cells.
- `make_realization(spec: DirectSpec) -> DirectRealization` is architecture-blind.

- [ ] Write tests for exact 540 identity, 480/60 split, seed pairing, severity doses, hidden-cause exclusion from policy signatures, and default V3 behavior.
- [ ] Run the focused tests and confirm failure because Exp13 and the injection seam do not exist.
- [ ] Implement the minimal typed contracts, realization sampler, precheck adapter, and V3 injection seam.
- [ ] Run focused tests to green and commit.

### Task 2: Independent direct scorer and paired analysis

**Files:**
- Modify: `experiments/13_direct_hierarchy/src/experiment.py`
- Test: `experiments/13_direct_hierarchy/tests/test_experiment.py`

**Interfaces:**
- `score_raw(raw) -> DirectScore` reconstructs success, safety, progress, and secondary metrics from retained raw members.
- `analyze_rows(rows) -> dict[str, object]` emits paired comparisons, 10,000 seed-cluster draws, heterogeneity, P4 sensitivity, and the frozen direct-outcome decision.

- [ ] Write adversarial scorer tests that alter executor terminal labels, physical traces, contacts, commands, memory, and decision rows.
- [ ] Verify the tests fail before scorer implementation.
- [ ] Implement scorer reconstruction and paired seed-cluster analysis with fixed R2.
- [ ] Run tests to green and commit.

### Task 3: Freeze and resumable evidence lifecycle

**Files:**
- Modify: `experiments/13_direct_hierarchy/src/experiment.py`
- Create: `experiments/13_direct_hierarchy/run.py`
- Create: `experiments/13_direct_hierarchy/tests/__init__.py`
- Modify: `experiments/13_direct_hierarchy/tests/test_experiment.py`

**Interfaces:**
- `freeze(output, source_commit)`, `execute(output)`, `reconstruct(output, clean)`, and `archive(output, destination)` are create-only.
- `run.py` exposes `freeze`, `execute`, `reconstruct`, and `archive` commands.

- [ ] Write tests for freeze-before-run, exact disposition identity, interrupted-cell retention/resume, recursive inventory, raw replay, graph-table fidelity, and deterministic archive extraction.
- [ ] Verify RED.
- [ ] Implement the minimal lifecycle by reusing V3 canonical serialization, episode payload, inventory, tree, graph, and archive helpers.
- [ ] Run focused tests, full Experiment 13 tests, and Ruff; commit the source/tests.

### Task 4: Atomic freeze, actual matrix, reconstruction, and evidence commit

**Files:**
- Create: `results/exp13-direct-hierarchy-v1/freeze.json` and ignored working evidence.
- Create: `experiments/13_direct_hierarchy/DIRECT_HIERARCHY_RESULT.md`
- Create: `reports/evidence/exp13-direct-hierarchy-v1/manifest.json`
- Create: `reports/evidence/exp13-direct-hierarchy-v1/<sha256>.tar.gz`

- [ ] Generate the freeze against the exact source commit without executing a cell; commit it atomically.
- [ ] Execute the resumable 540-cell matrix and seal all dispositions/raw inventory.
- [ ] Reconstruct every executable cell into a clean destination and require byte-exact raw and derived equality.
- [ ] Publish paired rows, 10,000-draw inputs/draws, heterogeneity, sensitivity, CSV/SVG/PNG graphs, examples, hashes, and direct-outcome report.
- [ ] Run focused tests, full Experiment 13 tests, Ruff, archive extraction, recursive inventory, `git diff --check`, cleanliness, and V3-outcome absence checks.
- [ ] Commit the tracked report/archive/manifest atomically; do not self-review or self-authorize.


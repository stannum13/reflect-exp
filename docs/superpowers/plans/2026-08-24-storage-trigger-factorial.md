# Storage x Triggering Factorial Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Measure how semantic-memory storage and wake-up triggering interact in a paired synthetic task, without attributing any result to pi0.5.

**Architecture:** Experiment 10 imports Experiment 04's deterministic initial semantic task generator, then applies a frozen mission/disturbance schedule. `ORACLE_TYPED_SEMANTIC_V1` consumes only each storage variant's projection; independent trigger logic decides when it may replan. Raw step traces are scored and aggregated only after publication, with byte-exact reconstruction.

**Tech Stack:** Python 3.11, NumPy PCG64, standard-library CSV/JSON/SVG/PNG, pytest, Ruff.

## Global Constraints

- Planner identity is `ORACLE_TYPED_SEMANTIC_V1`; it is deterministic synthetic logic, not a VLA or pi0.5 substitute.
- Frozen matrix is 5 storage variants x 5 trigger variants x 4 disturbance families x 2 severities x 3 horizons x 20 paired seeds = 12,000 episodes.
- Seeds are exactly 20264101 through 20264120; bootstrap resamples seed clusters in 10,000 deterministic draws.
- Every episode retains complete step-level world, plan, trigger, storage, retry, escalation, progress, cost, and terminal observations.
- Source/config/seed identities are committed before the outcome run. Raw and derived evidence is create-only and hash-bound.

---

### Task 1: Freeze typed dynamics and integrity boundaries

**Files:**
- Create: `experiments/10_storage_trigger/configs/storage-trigger-factorial-v1.json`
- Create: `experiments/10_storage_trigger/configs/seeds-v1.json`
- Create: `experiments/10_storage_trigger/src/factorial.py`
- Create: `experiments/10_storage_trigger/tests/test_factorial.py`

**Interfaces:**
- Consumes: `experiments.04_memory.src.unfixed_ablation.generate_seed(seed)` initial observation only.
- Produces: `frozen_matrix()`, `run_episode(cell)`, `run_frozen(output, implementation_git_sha)`, and `reconstruct(raw, destination)`.

- [ ] Write failing tests for exact 12,000 identities, trigger cooldown/hysteresis, storage separation, explicit planner labeling, raw tamper rejection, and byte-identical reconstruction.
- [ ] Run the focused test file and retain the missing-module RED.
- [ ] Implement deterministic typed storage, trigger, mission, scorer, bootstrap, graph, manifest, and replay paths.
- [ ] Run pytest and Ruff; commit source, config, seeds, tests, and this plan before outcomes.

### Task 2: Execute, analyze, and publish the frozen matrix

**Files:**
- Create: `experiments/10_storage_trigger/results/storage-trigger-factorial-v1/raw/**`
- Create: `experiments/10_storage_trigger/results/storage-trigger-factorial-v1/derived/**`
- Create: `experiments/10_storage_trigger/STORAGE_TRIGGER_FACTORIAL_RESULT.md`

**Interfaces:**
- Consumes: the Task 1 commit without source/config changes.
- Produces: raw CSV/JSONL, tidy tables, paired seed-cluster intervals, working/nonworking samples, deterministic SVG/PNG, manifests, and report.

- [ ] Run exactly the frozen 12,000 episodes from the committed runner.
- [ ] Validate all hashes, counts, paired identities, planner labels, and plot/style tables.
- [ ] Reconstruct derived evidence into a clean directory and require byte equality.
- [ ] Report only storage/trigger engineering signals for this synthetic task; commit evidence/report separately.

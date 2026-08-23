# Storage x Trigger Factorial V2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish a superseding 12,000-cell white-box factorial whose raw ledger supports independent scoring and whose source, matrix, and recursive inventories fail closed.

**Architecture:** A standalone V2 executor publishes low-level world/storage/trigger/action receipts, while a scorer that does not import the executor independently derives every episode metric. Canonical freeze and recursive manifests bind the exact source/config/seeds/matrix before deterministic derived reconstruction.

**Tech Stack:** Python 3.11, NumPy PCG64, standard-library CSV/JSON/SVG/zlib PNG, pytest, Ruff.

## Global Constraints

- Preserve every V1 tracked byte.
- V2 seeds are exactly `20265101..20265120`; bootstrap seed is `20265999`.
- V2 matrix is exactly 5 x 5 x 4 x 2 x 3 x 20 = 12,000 unique episodes.
- The V2 result is synthetic white-box engineering evidence only.
- No V2 outcome runs before the source/config/seeds/tests commit.
- Raw/derived publication is create-only, canonical, recursively closed, and symlink-free.

---

### Task 1: Adversarial RED contract

**Files:**
- Create: `experiments/10_storage_trigger/tests/test_factorial_v2.py`
- Create: `experiments/10_storage_trigger/configs/storage-trigger-factorial-v2.json`
- Create: `experiments/10_storage_trigger/configs/seeds-v2.json`

**Interfaces:**
- Consumes: approved V2 design and immutable V1 evidence.
- Produces: wished-for `factorial_v2` and `factorial_v2_scorer` APIs.

- [ ] Write tests importing `experiments.10_storage_trigger.src.factorial_v2` and asserting `frozen_matrix()` has exactly 12,000 held-back identities.
- [ ] Write an independent-score attack that mutates executor diagnostic completion fields plus manifest hashes and requires `reconstruct()` to reject or reproduce unchanged derived completion.
- [ ] Write exact-freeze attacks for an out-of-range seed, config drift, seed drift, implementation/source/import closure drift, duplicate/missing/extra matrix cells, and a forged 40-character commit.
- [ ] Write recursive-closure attacks for nested files, symlinks, traversal, missing members, and extra derived/archive members.
- [ ] Write graph/annotation assertions requiring visible PNG labels and explicit `requested_class`/`disposition` fields.
- [ ] Run `uv run pytest experiments/10_storage_trigger/tests/test_factorial_v2.py -q`; expect collection/behavior failures because V2 does not exist.

### Task 2: Authoritative executor ledger and independent scorer

**Files:**
- Create: `experiments/10_storage_trigger/src/factorial_v2.py`
- Create: `experiments/10_storage_trigger/src/factorial_v2_scorer.py`
- Modify: `experiments/10_storage_trigger/tests/test_factorial_v2.py`

**Interfaces:**
- Consumes: canonical V2 config/seeds and Experiment 04 `generate_seed(seed)`.
- Produces: `frozen_matrix()`, `run_episode(cell)`, `score_episode(start, ticks)`, `run_fixture(output, implementation_git_sha)`, and `run_frozen(output, implementation_git_sha)`.

- [ ] Implement `factorial_v2_scorer.py` without importing `factorial_v2`; define canonical world transition, eligibility, plan validity, trigger replay, storage replay, action success, progress, completion, retry/wake/latency/storage/cost derivation.
- [ ] Implement V2 executor constants and exact matrix from V2 config/seeds.
- [ ] Publish per-episode canonical start records and per-tick world-before/after, event, storage, trigger, plan, action, and control-fault receipts; exclude score-authoritative progress/completion/valid/stale booleans.
- [ ] Make executor summaries call the independent scorer over the completed ledger.
- [ ] Run focused matrix/storage/trigger/scorer tests and require GREEN.

### Task 3: Freeze, recursive closure, and reconstruction

**Files:**
- Modify: `experiments/10_storage_trigger/src/factorial_v2.py`
- Modify: `experiments/10_storage_trigger/tests/test_factorial_v2.py`

**Interfaces:**
- Consumes: `source_closure()`, V2 raw start/tick ledgers, exact V2 matrix.
- Produces: `validate_raw(raw)`, `reconstruct(raw, destination)`, recursively closed manifests.

- [ ] Implement normalized relative-path validation rejecting absolute paths, `..`, duplicates, symlinks, special files, undeclared directories/files, missing members, and nested extras.
- [ ] Bind source closure for executor, scorer, V2 config/seeds, and Experiment 04 generator with exact bytes/hashes plus current HEAD; reject an arbitrary caller-provided commit.
- [ ] Require retained config/seeds byte equality and independently recompute the exact Cartesian identity set and canonical matrix SHA.
- [ ] Validate every start/tick cell identity and independently rescore all episode summaries before derivation.
- [ ] Regenerate derived tables/bootstrap/annotations/plots from validated independently scored rows only.
- [ ] Run every adversarial test and require GREEN.

### Task 4: Deterministic annotated graphics and scoped reporting

**Files:**
- Modify: `experiments/10_storage_trigger/src/factorial_v2.py`
- Create: `experiments/10_storage_trigger/V1_RECONSTRUCTION_DISPOSITION.md`
- Create: `experiments/10_storage_trigger/STORAGE_TRIGGER_FACTORIAL_V2_RESULT.md`
- Modify: `experiments/10_storage_trigger/tests/test_factorial_v2.py`

**Interfaces:**
- Consumes: tidy storage-trigger and heterogeneity tables.
- Produces: labeled SVG/PNG, plot style, explicit annotations, V1 insufficiency notice, V2 result template.

- [ ] Implement a deterministic bitmap glyph renderer for PNG title, axes, storage/trigger labels, and exact cell values; bind font/palette/order in `plot-style.json`.
- [ ] Emit annotations with `requested_class`, `disposition`, and authenticated episode identity or null.
- [ ] Emit family/horizon/severity heterogeneity tables and report the aggregate contrasts only with their decompositions.
- [ ] Record that V1 remains byte-identical but is insufficient for independent reconstruction.
- [ ] Run focused graph/report tests, full Experiment 10 tests, Ruff, and `git diff --check`.

### Task 5: Freeze source before outcomes

**Files:**
- Commit all V2 source/config/seeds/tests/design/plan/disposition changes.

**Interfaces:**
- Consumes: fully GREEN pre-outcome implementation.
- Produces: immutable V2 implementation commit used by the raw freeze.

- [ ] Hash and compare every V1 path against commit `6a94954`; require no difference.
- [ ] Run `uv run pytest experiments/10_storage_trigger/tests -q` and `uv run ruff check experiments/10_storage_trigger`.
- [ ] Commit with `feat(exp10): freeze reconstructible storage trigger V2` and record the exact 40-character SHA.

### Task 6: Execute and publish V2 evidence

**Files:**
- Create: `experiments/10_storage_trigger/results/storage-trigger-factorial-v2/raw/**`
- Create: `experiments/10_storage_trigger/results/storage-trigger-factorial-v2/derived/**`
- Modify: `experiments/10_storage_trigger/STORAGE_TRIGGER_FACTORIAL_V2_RESULT.md`

**Interfaces:**
- Consumes: the frozen implementation commit and absent V2 result root.
- Produces: exact 12,000-cell evidence, clean reconstruction, final scoped report.

- [ ] Run `run_frozen()` exactly once with the frozen implementation SHA into the absent V2 root.
- [ ] Reconstruct to a new temporary directory and compare every derived byte plus recursively closed inventory.
- [ ] Independently recompute completion/cost/latency contrasts, all 50 bootstrap rows, and family/horizon/severity decompositions from raw ledgers.
- [ ] Update the V2 report with exact counts, hashes, contrast intervals, heterogeneity, 100%/zero-width limitations, and verification receipts.
- [ ] Run focused tests, complete Experiment 10 tests, Ruff, reconstruction, manifest closure, V1 immutability, and `git diff --check`.
- [ ] Commit result/report atomically with `exp(exp10): publish reconstructible storage trigger V2`.


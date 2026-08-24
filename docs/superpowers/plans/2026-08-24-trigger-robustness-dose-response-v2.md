# Experiment 11 V2 Integrity Repair Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish a new 46,080-episode Experiment 11 namespace whose independent replay, exact provenance, recursive inventories, paired inference, and store-separated graphs close every fresh-review finding without changing V1.

**Architecture:** V2 has a generator kernel and a separately implemented ledger replay scorer with no generator import. A source commit freezes the complete Python/config/seed/package-init closure; the later evidence commit contains create-only raw and derived trees plus a root manifest and tracked V1 rejection registry, while reconstruction validates the frozen Git blobs and recomputes every derived byte from raw.

**Tech Stack:** Python 3.11 standard library, pytest, Ruff, Git blob authentication.

## Global Constraints

- Preserve every V1 byte and classify V1 as `INVALID_REJECTED` with no claim authority.
- Use the wholly new twelve-seed namespace `20266301..20266312` and exactly 46,080 paired episodes.
- Use exactly 10,000 seed-cluster bootstrap draws; every accepted effect has effective seed n=12.
- Do not run physical or remote execution.
- Commit source/config/tests before executing outcomes; commit evidence/report separately.

---

### Task 1: V2 preregistration and independent replay

**Files:**
- Create: `experiments/11_trigger_robustness/configs/trigger-robustness-v2.json`
- Create: `experiments/11_trigger_robustness/configs/seeds-v2.json`
- Create: `experiments/11_trigger_robustness/src/kernel_v2.py`
- Create: `experiments/11_trigger_robustness/src/replay_v2.py`
- Test: `experiments/11_trigger_robustness/tests/test_trigger_robustness_v2.py`

**Interfaces:** `simulate(cell, config, quality)` emits start/ticks/terminal; `score_episode(start,ticks,terminal,config)` independently reconstructs the same state and rejects altered ledger facts.

- [ ] Write tests that assert the scorer source does not import/call the generator, compare both implementations over positive-control fixture cells, and prove a generator-only injected bug is rejected.
- [ ] Run the focused test and observe failure because V2 modules do not exist.
- [ ] Implement the generator and an algorithmically independent replay scorer, then rerun focused tests to green.

### Task 2: Authenticated closure and recursive evidence

**Files:**
- Create: `experiments/11_trigger_robustness/src/experiment_v2.py`
- Modify: `experiments/11_trigger_robustness/tests/test_trigger_robustness_v2.py`

**Interfaces:** `freeze_receipt(cells, implementation_git_sha, fixture)`, `publish`, `validate_raw`, `derive`, `validate_derived`, and `reconstruct` authenticate canonical bytes, Git blobs, exact recursive inventories (including subordinate manifests), and forbid symlinks.

- [ ] Write coherent-tamper tests for source/config/seed/matrix/freeze drift, manifest replacement, nested extras, sibling extras, and file/directory symlinks.
- [ ] Run tests and observe the missing validation failures.
- [ ] Implement exact root/raw/derived inventories, canonical schemas, source-commit ancestry/blob verification, and recomputation-based derived validation.
- [ ] Rerun tests to green.

### Task 3: Paired inference, store-separated graphs, and retirement

**Files:**
- Create: `experiments/11_trigger_robustness/configs/retired-attempts-v2.json`
- Create: `experiments/11_trigger_robustness/V1_RECONSTRUCTION_DISPOSITION.md`
- Modify: `experiments/11_trigger_robustness/src/experiment_v2.py`
- Modify: `experiments/11_trigger_robustness/tests/test_trigger_robustness_v2.py`

**Interfaces:** preregistered `effect_id` definitions produce paired contrasts and heterogeneity with 10,000 seed-cluster draws, slopes/cliffs, gates, graph-table rows, and SVG/PNG panels that never pool storage variants.

- [ ] Write tests for the exact retirement schema and hashes, 12-cluster contrast pairing, effect IDs, gates, graph table-to-render equality, explicit transformations, and raw-to-derived recomputation rejecting coherently resealed forgeries.
- [ ] Run tests and observe failures.
- [ ] Implement minimal derivation, plotting, registry parsing, and report generation; rerun focused tests.

### Task 4: Source commit, full execution, and evidence commit

**Files:**
- Create: `experiments/11_trigger_robustness/results/v2/**`
- Create: `experiments/11_trigger_robustness/TRIGGER_ROBUSTNESS_V2_RESULT.md`

**Interfaces:** CLI `full OUTPUT --implementation-git-sha SHA` executes the frozen matrix; `reconstruct SOURCE TARGET --expected-root-manifest-sha256 SHA` validates and independently rebuilds it.

- [ ] Run focused Experiment 11 tests, the full repository suite, Ruff, and `git diff --check`; commit source/config/tests/disposition atomically.
- [ ] Execute the 46,080-cell matrix under that exact source commit.
- [ ] Validate and reconstruct into a fresh ignored directory; require byte-identical derived artifacts and exact inventories.
- [ ] Record counts, manifest/tree hashes, contrast/gate summaries, graph hashes, and V1 preservation hashes in the tracked report.
- [ ] Run fresh full verification and commit evidence/report atomically.

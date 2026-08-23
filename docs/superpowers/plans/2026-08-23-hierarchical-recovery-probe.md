# Hierarchical Recovery Probe Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement, execute, reconstruct, and analyze the approved 288-episode Reflect-style control/motion/semantic recovery experiment without adding a robotics framework or retuning a controller.

**Architecture:** Add an experiment-local typed semantic cell and deterministic bounded recovery state machine under `experiments/03_recovery`. Reuse the existing MuJoCo planar-arm, frozen P6 controller for the 256-episode primary matrix, and repaired P4 only for the declared 32-episode sensitivity slice. Seal raw semantic, memory, motion, controller, recovery, scorer, and terminal evidence before deriving paired contrasts and figures.

**Tech Stack:** Python 3.11, NumPy, MuJoCo, existing Experiment 01 controllers/evidence helpers, pytest, JSON/JSONL/NPZ or Parquet already available in the lockfile, Matplotlib only if already locked.

## Global Constraints

- Binding design: `docs/superpowers/specs/2026-08-23-hierarchical-recovery-microexperiment-design.md`; implement every stated architecture, scenario, seed, measure, safety rule, evidence member, and decision gate.
- Fixed memory is exactly `T3_LIVE_BELIEF_V1`; memory is never treated as a fourth recovery level.
- Architectures are exactly `R0 LOCAL_ONLY`, `R1 SEMANTIC_ALWAYS`, `R2 MOTION_THEN_SEMANTIC`, and `R3 LAYER_MATCHED`.
- Recovery budgets are exactly two control recoveries, two motion refresh/replans, and one semantic replan; no budget resets without a successful new command with a new command hash.
- R3 may inspect observable contract state but never injected cause/scorer truth.
- Scenarios are exactly two anchors, two control disturbances, two motion disturbances, and two semantic disturbances, injected at controller tick 750 where applicable.
- Primary seeds are `20261601..20261608`, P6 fixed residual `0.5` / slew `48`, 4×8×8 = 256 episodes.
- Sensitivity seeds are `20261601..20261604`, repaired P4 R3 only, 8×4 = 32 episodes. Total is exactly 288 started episodes unless the frozen pre-outcome feasibility gate declares the entire configuration `NOT_RUN`.
- No parameter selection, controller retuning, learned classifier, hidden-cause access, adaptive magnitude, ROS/MJPC/new robotics framework, database, or LLM.
- Every started episode has one terminal disposition; invalid/aborted attempts are inventoried and excluded from analysis, never deleted.
- Raw evidence is sufficient to replay semantic/recovery decisions without scorer truth, replay motion/controller execution, recompute every metric and figure, and reproduce deterministic derived files byte-for-byte.
- Graphs always ship with canonical graph-data tables, source hashes, a reconstruction script, working/nonworking examples, and explicit `CLASS_NOT_OBSERVED` rows.

---

### Task 1: Typed domain, fixed memory, and bounded recovery state machine

**Files:**
- Create: `experiments/03_recovery/__init__.py`
- Create: `experiments/03_recovery/src/__init__.py`
- Create: `experiments/03_recovery/src/contracts.py`
- Create: `experiments/03_recovery/src/recovery.py`
- Create: `experiments/03_recovery/tests/test_contracts.py`
- Create: `experiments/03_recovery/tests/test_recovery.py`

**Interfaces:**
- `Architecture`, `RecoveryLevel`, `ScenarioDomain`, and `TerminalDisposition` are closed enums.
- Immutable rows: `MemoryFact`, `MemorySnapshot`, `SkillRequest`, `MotionCommand`, `ObservableFailure`, `RecoveryBudget`, `RecoveryDecision`, and `EpisodeSpec`.
- `decide_recovery(architecture, observable_failure, budget, previous_command_sha256) -> RecoveryDecision` is pure and cannot receive a cause label.

- [ ] Write RED contract tests for closed enums, finite/ASCII/hash validation, fixed `T3_LIVE_BELIEF_V1` canonical bytes, and rejection of hidden scorer fields.
- [ ] Run `uv run pytest experiments/03_recovery/tests/test_contracts.py -q`; verify expected RED.
- [ ] Implement the immutable typed rows and canonical SHA-256 serialization; rerun to GREEN.
- [ ] Write RED table tests spanning every architecture × observable failure class, monotonic escalation, exact budgets, safe abort, and command-hash reset rule.
- [ ] Run `uv run pytest experiments/03_recovery/tests/test_recovery.py -q`; verify expected RED.
- [ ] Implement the smallest deterministic recovery state machine satisfying the frozen table; rerun both files to GREEN.
- [ ] Commit `feat(exp03): define bounded hierarchical recovery contracts`.

### Task 2: MuJoCo cell, scenario injection, and full-fidelity episode traces

**Files:**
- Create: `experiments/03_recovery/src/cell.py`
- Create: `experiments/03_recovery/src/episode.py`
- Create: `experiments/03_recovery/tests/test_cell.py`
- Create: `experiments/03_recovery/tests/test_episode.py`
- Modify only through imports: existing Experiment 01 modules remain byte-unchanged.

**Interfaces:**
- `scenario_specs()` returns the exact eight frozen scenarios and no others.
- `precheck(spec, controller) -> FeasibilityReceipt` is architecture-independent and runs before outcomes.
- `run_episode(EpisodeSpec) -> EpisodeEvidence` consumes only observable state in planners and writes scorer cause separately.
- Controller adapters call the existing fixed P6 path and repaired P4 path without changing their tuning.

- [ ] Write RED tests for the exact eight scenarios, tick-750 schedule, architecture-independent precheck, fixed magnitudes, and non-overlapping identities.
- [ ] Implement the minimal tabletop semantic cell and injectors using existing safe Experiment 01/05 magnitudes.
- [ ] Write RED episode tests for a representative anchor plus one control, motion, and semantic disturbance under all four architectures; assert correct trace separation and no hidden-cause access.
- [ ] Implement semantic skill selection, motion target/constraint resolution, existing controller execution, bounded retries/replans, safe holds, and a terminal disposition for every path.
- [ ] Retain 500 Hz numeric trace arrays plus canonical semantic/memory/motion/recovery/scorer JSONL. Include exact metric inputs rather than rounded summaries.
- [ ] Run `uv run pytest experiments/03_recovery/tests/test_cell.py experiments/03_recovery/tests/test_episode.py -q` to GREEN and commit `feat(exp03): execute hierarchical recovery episodes`.

### Task 3: Sealed matrix runner, reconstruction, analysis, and figures

**Files:**
- Create: `experiments/03_recovery/run.py`
- Create: `experiments/03_recovery/src/evidence.py`
- Create: `experiments/03_recovery/src/analyze.py`
- Create: `experiments/03_recovery/tests/test_evidence.py`
- Create: `experiments/03_recovery/tests/test_analysis.py`

**Interfaces:**
- `run_shard(output, shard_id)` accepts only `anchors-control`, `motion`, or `semantic` and writes disjoint identities.
- `merge_shards(output, shard_roots)` validates exact source/config/manifests and the full 288 identity set before analysis.
- `reconstruct(raw_root, clean_output)` authenticates every member and reproduces every deterministic derived table/report/figure input byte-for-byte.
- `analyze(raw_root, derived_root)` emits decision gates, paired case rows, 10,000-draw deterministic bootstrap results, confusion tables, samples, graph data, SVG/PNG figures, and `RESULTS.md`.

- [ ] Write RED tests for create-only publication, exact manifest/hash inventory, missing/duplicate/extra identity rejection, invalid-attempt exclusion, and source/config drift.
- [ ] Implement sealed bundle and root manifests with canonical hashes and append-only invalid-attempt inventory.
- [ ] Write RED analysis tests for all six support gates, domain-stratified paired contrasts, deterministic bootstrap seeds, lowest-sufficient-level confusion, loop detection, and class-absent annotations.
- [ ] Implement analysis and graph-data generation. PNG may carry a separately recorded renderer/version hash; SVG and tables must be deterministic.
- [ ] Add a small 1-seed test matrix and verify raw→clean reconstruction including replayed decisions and controller traces.
- [ ] Run `uv run pytest experiments/03_recovery/tests -q` and `git diff --check`; commit `feat(exp03): seal and analyze hierarchy matrix`.

### Task 4: Execute the actual 288 episodes and audit the outcome

**Files:**
- Create under ignored results root: `results/hierarchical-recovery-v1/**`
- Create: `experiments/03_recovery/HIERARCHICAL_RECOVERY_V1.md`

**Interfaces:**
- Three shards write to `results/hierarchical-recovery-v1/shards/{anchors-control,motion,semantic}`.
- Merged raw/derived roots live at `results/hierarchical-recovery-v1/{raw,derived}`.

- [ ] Freeze and record source SHA, config SHA, controller fingerprints, dependency versions, platform, and exact episode identity manifest before launching any shard.
- [ ] Run the three shards concurrently. Do not adapt code/config/scenarios after the first outcome exists.
- [ ] Merge only after all shards validate; verify exactly 256 P6 primary plus 32 P4 sensitivity terminal episodes.
- [ ] Reconstruct into a fresh temporary directory and byte-compare deterministic derived files and graph data.
- [ ] Independently audit that recovery decisions never consume cause labels and all 10,000 bootstrap inputs/draw seeds are retained.
- [ ] Write `HIERARCHICAL_RECOVERY_V1.md` with situation, methodology, objective, outcome, inference, conclusion, limits, working/nonworking samples, graph links, and raw evidence hashes.
- [ ] Run full Experiment 03 tests plus repository safety/source audits and `git diff --check`.
- [ ] Commit the tracked report and implementation as `docs(exp03): report hierarchical recovery experiment` while leaving bulky raw evidence ignored but fully inventoried.

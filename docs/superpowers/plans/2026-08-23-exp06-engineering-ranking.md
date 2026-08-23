# Experiment 06 Engineering Ranking Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and run one isolated, reconstructable MuJoCo engineering experiment comparing two learned candidate rankers with DIRECT, random, heuristic, and exact-rollout controls.

**Architecture:** `world.py` deterministically generates split scenes, two anchors, eight one-second action chunks, and independently restored MuJoCo truth branches. `model.py` fits pure-NumPy ridge progress and dynamics models using training rows only and ranks untouched evaluation candidates. `run.py` creates one lossless evidence tree and can reconstruct every derived byte from raw scene/action/truth inputs.

**Tech Stack:** Python 3.11.13, NumPy 2.4.6, MuJoCo 3.12.0, PyArrow 21, pytest 9.

## Global Constraints

- Touch only `experiments/06_world_model/` and this plan.
- Use 48 ID training, 16 ID tuning, and 24 untouched evaluation scenes: 8 ID and 4 each MASS_OOD, FRICTION_OOD, GEOMETRY_OOD, OBSTACLE_OOD.
- Use two anchors and exactly eight distinct 50x2 action chunks per scene, totaling 1,408 independently restored candidate branches.
- W2 is an oracle/upper bound and never a deployable selector.
- No downloaded models, new dependency, online learning, action routing, bootstrap framework, or generalized publication layer.
- Evidence status is `PRELIMINARY_NONCONFIRMATORY_ENGINEERING_ONLY` and cannot promote authority.

---

### Task 1: Deterministic MuJoCo world and candidate truth

**Files:**
- Create: `experiments/06_world_model/__init__.py`
- Create: `experiments/06_world_model/world.py`
- Create: `experiments/06_world_model/config.json`
- Create: `experiments/06_world_model/tests/test_world.py`

**Interfaces:**
- Produces: `scene_rows()`, `compile_candidates(anchor)`, `generate_scene(scene_row)`, `run_scene(scene_row)`, and canonical dataclasses for scenes, anchors, candidates, and outcomes.
- Guarantees: split IDs are disjoint; commands are deterministic/distinct; each branch restores one byte-identical anchor; truth exposes terminal state, success, collision, unsafe, energy, and exact cost.

- [ ] **Step 1: Write failing tests** for exact 48/16/24 split counts and strata, no shared seed, deterministic eight-strategy compilation, HOLD zeros, distinct action hashes, anchor restore equality, and finite cost identity.
- [ ] **Step 2: Run RED:** `.venv/bin/python -m pytest experiments/06_world_model/tests/test_world.py -q`; expect import failure because `world.py` is absent.
- [ ] **Step 3: Implement minimal world:** dataclasses plus canonical JSON/hash helpers; checked config loader; domain-separated PCG64 scene generation; canonical MJCF builder; two-anchor probe; eight waypoint controllers; independent MuJoCo branch restore; frozen actual-cost formula.
- [ ] **Step 4: Run GREEN:** the focused world suite passes twice with identical hashes.
- [ ] **Step 5: Commit exact Task 1 paths** with `feat(exp06): add deterministic pushing truth world`.

### Task 2: Leakage-safe learned and control selectors

**Files:**
- Create: `experiments/06_world_model/model.py`
- Create: `experiments/06_world_model/tests/test_model.py`

**Interfaces:**
- Consumes: immutable truth rows returned by `world.run_scene`.
- Produces: `fit_models(training_rows, tuning_rows)`, `predict_all(models, rows)`, `rank_selectors(predictions, rows)`, and `aggregate_metrics(selections, rows)`.
- Models: W3 ridge predicts actual cost from scene/anchor/action summaries; W4 ridge predicts terminal object pose plus collision/unsafe/success heads from scene/anchor and all 100 command scalars, then recomputes frozen cost.

- [ ] **Step 1: Write failing tests** proving fit rejects non-training rows, evaluation IDs cannot enter fit hashes, ridge reconstruction is byte-stable, W4 cost is derived from its outputs, each selector emits exactly one of eight candidates, W2 equals minimum actual cost, regret is nonnegative, and Spearman tie rules are total.
- [ ] **Step 2: Run RED:** `.venv/bin/python -m pytest experiments/06_world_model/tests/test_model.py -q`; expect import failure because `model.py` is absent.
- [ ] **Step 3: Implement minimal selectors:** DIRECT; domain-separated W0; frozen W1 nominal progress/collision/action heuristic; W2 truth oracle; centered standardized primal ridge for W3/W4 with three fixed ridge candidates selected on tuning regret; no sklearn/scipy.
- [ ] **Step 4: Run GREEN:** model and world suites pass; repeat fit bytes match.
- [ ] **Step 5: Commit exact Task 2 paths** with `feat(exp06): add leakage-safe ranking models`.

### Task 3: Create-only evidence, reconstruction, and real matrix

**Files:**
- Create: `experiments/06_world_model/run.py`
- Create: `experiments/06_world_model/tests/test_run.py`
- Create after execution: `experiments/06_world_model/ENGINEERING_RANKING.md`

**Interfaces:**
- CLI: `python -m experiments.06_world_model.run --output PATH` and `--reconstruct-from RAW --output PATH`.
- Raw members: config/source ledger, scenes JSONL, anchors JSONL, actions NPZ/index, truth JSONL, fitted models NPZ/index, predictions JSONL, selections JSONL, metrics JSON, recipe JSON, and exact file manifest.

- [ ] **Step 1: Write failing tests** for create-only output, exact 88 scenes/176 anchors/1,408 candidates, full invalid-attempt retention, immutable train/tune/eval ancestry, manifest byte/hash agreement, and fresh-directory reconstruction of models/predictions/selections/metrics byte-for-byte.
- [ ] **Step 2: Run RED:** `.venv/bin/python -m pytest experiments/06_world_model/tests/test_run.py -q`; expect import failure because `run.py` is absent.
- [ ] **Step 3: Implement minimal runner:** freeze source/config before simulation; write raw members with create-exclusive operations; fit only after all train/tune truth seals; predict untouched evaluation rows; validate exact counts and hashes; write manifest last; reconstruction consumes only raw sealed inputs.
- [ ] **Step 4: Run GREEN:** all Experiment 06 tests pass; run `git diff --check`.
- [ ] **Step 5: Execute 1,408 branches** under `experiments/06_world_model/results/engineering-ranking-v1/`, reconstruct derived evidence in a sibling ignored root, and require byte-identical derived outputs.
- [ ] **Step 6: Validate and report:** independently reopen every file, recompute all hashes/counts/costs/rankings, summarize W3/W4 versus DIRECT/W1 and W2 overall and per stratum, retain first canonical working/nonworking examples, and write only `ENGINEERING_RANKING.md` as tracked outcome evidence.
- [ ] **Step 7: Commit Task 3 implementation/tests, then commit the outcome report separately** so empirical identity is unambiguous.


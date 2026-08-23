# π0.5 Semantic Hierarchy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run a checkpoint-backed π0.5 semantic-planning experiment above separate motion-replanning and MPC/PID retry layers, crossed with fixed/live semantic and episodic memory.

**Architecture:** An OpenPI adapter receives images, instruction, and a deterministic task-relevant memory projection, but exposes only a validated `SemanticPlan`. The motion planner consumes that plan and the existing P6/P4 executors remain the only fine-manipulation controllers. Raw model, memory, planning, motion, and control evidence are retained separately and joined by immutable IDs.

**Tech Stack:** official OpenPI/π0.5 checkpoint, Python, NumPy, MuJoCo, existing Experiment 03/04/05 contracts, deterministic JSON/CSV/SVG/PNG evidence.

## Global Constraints

- π0.5 may emit semantic plans only; raw VLA actions never enter motion or control.
- Semantic memory, episodic history, metric world state, and controller state remain separate stores.
- Exact official checkpoint/OpenPI identities and a real forward pass are mandatory for a π0.5 outcome.
- Motion replanning and MPC/PID retry/retrigger remain separately manipulated and counted.
- No held-out outcome runs before source/config/checkpoint freeze and construct review.

---

### Task 1: Freeze the real π0.5 backend feasibility probe

**Files:**
- Create: `experiments/09_mini_reflect/configs/pi05-semantic-probe.json`
- Create: `experiments/09_mini_reflect/src/pi05_backend.py`
- Test: `experiments/09_mini_reflect/tests/test_pi05_backend.py`

**Interfaces:**
- Consumes: official OpenPI checkout and `pi05_droid` or `pi05_base` checkpoint.
- Produces: `Pi05BackendIdentity`, raw checkpoint-backed response bytes, latency/memory receipts, and typed `NOT_RUN` reasons.

- [ ] Write failing tests proving checkpoint identity is mandatory, a real forward-pass receipt is required, action arrays are discarded, and unavailable local/remote backends yield `NOT_RUN_NO_CHECKPOINT_BACKEND`.
- [ ] Run `.venv/bin/pytest experiments/09_mini_reflect/tests/test_pi05_backend.py -q` and observe the missing-interface failures.
- [ ] Implement the minimal official OpenPI local/client adapter and fail-closed identity/receipt validation.
- [ ] Run the focused tests and one checkpoint-backed feasibility invocation; retain raw device, latency, memory, request, response, and error evidence.
- [ ] Commit source/config before any semantic outcome prompt.

### Task 2: Bind semantic memory and typed plans

**Files:**
- Create: `experiments/09_mini_reflect/src/semantic_context.py`
- Create: `experiments/09_mini_reflect/src/semantic_plan.py`
- Test: `experiments/09_mini_reflect/tests/test_semantic_plan.py`

**Interfaces:**
- Consumes: metric world, `T3_LIVE_BELIEF_V1`, episodic events, current images/instruction.
- Produces: bounded canonical context bytes and validated `SemanticPlan` objects.

- [ ] Write failing tests for stable object/room/region IDs, affordances, restrictions, confidence/provenance/staleness, bounded episodic retrieval, hidden-cause exclusion, unauthorized/stale references, and prompt-order determinism.
- [ ] Run the focused tests and retain RED output.
- [ ] Implement deterministic context projection plus strict plan parsing/grounding/refusal.
- [ ] Add adversarial model responses containing raw actions, unknown objects, forbidden affordances, and future facts; require rejection.
- [ ] Run tests and commit the memory/plan boundary.

### Task 3: Keep the three manipulation levels independent

**Files:**
- Create: `experiments/09_mini_reflect/src/hierarchy.py`
- Test: `experiments/09_mini_reflect/tests/test_hierarchy.py`

**Interfaces:**
- Consumes: `SemanticPlan`, existing motion planner, P6/P4 controller adapters.
- Produces: separate semantic-replan, motion-replan, and control retry/retrigger event streams.

- [ ] Write failing tests proving semantic replans cannot write trajectories, motion replans cannot rewrite semantic facts, and MPC/PID retry/retrigger cannot change task/object selection.
- [ ] Run focused RED tests.
- [ ] Implement typed queues, independent 1/2/2 budgets, causal receipts, and guarded content-changing resets.
- [ ] Verify each injected semantic, motion, and control fault changes only the intended layer before any escalation.
- [ ] Run tests and commit.

### Task 4: Preregister and run the comparison zoo

**Files:**
- Create: `experiments/09_mini_reflect/configs/pi05-zoo-v1.json`
- Create: `experiments/09_mini_reflect/run_pi05_zoo.py`
- Test: `experiments/09_mini_reflect/tests/test_pi05_zoo.py`

**Interfaces:**
- Consumes: Z0-Z9 cells from the approved design, frozen scene/seed schedule, checkpoint-backed adapter.
- Produces: complete or typed `NOT_RUN` matched dispositions and raw multi-layer evidence.

- [ ] Write failing tests for exact zoo identities, matched seeds, severity/delay gradients, same lower controller across semantic cells, P4 sensitivity subset, and no outcome execution without checkpoint/construct approval.
- [ ] Freeze source/config/checkpoint/import closure and obtain read-only approval.
- [ ] Execute feasibility cells immediately; if checkpoint-backed, run the frozen outcome matrix, otherwise seal `NOT_RUN_NO_CHECKPOINT_BACKEND` without simulated π0.5 rows.
- [ ] Retain every valid, failed, interrupted, refused, and NOT_RUN attempt.
- [ ] Commit only immutable evidence/report artifacts after the run.

### Task 5: Analyze rich paired measures and reconstruct

**Files:**
- Create: `experiments/09_mini_reflect/src/pi05_analysis.py`
- Create: `experiments/09_mini_reflect/tests/test_pi05_analysis.py`
- Create: `experiments/09_mini_reflect/PI05_SEMANTIC_HIERARCHY_RESULT.md`

**Interfaces:**
- Consumes: raw model/memory/semantic/motion/control evidence and matched dispositions.
- Produces: paired effects, clustered intervals, strata tables, graphs, examples, manifests, archive, and decision label.

- [ ] Write failing tests that independently recompute semantic grounding, memory use/staleness, layer-specific interventions, controller/trajectory measures, latency, safety, and outcome labels from raw evidence.
- [ ] Implement realization-cluster bootstrap and retain its exact 10,000 draws, inputs, effective sample sizes, and template sensitivity.
- [ ] Generate canonical graph CSVs plus deterministic SVG/PNG figures for success, semantic quality, intervention profile, latency, trajectory quality, and failure taxonomy.
- [ ] Reconstruct in a clean directory and require byte equality for raw-derived joins, analysis, graphs, report, manifests, and archive.
- [ ] Obtain independent scientific/evidence review and commit the approved result or annotated negative/NOT_RUN evidence.

# Hierarchical Recovery V3 Review Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the four construct-review findings without executing held-out outcomes, while leaving a frozen approval-gated outcome path that requires no later source edit.

**Architecture:** Separate injected causes from a retained-history observation builder, make the scorer reconstruct physical and reset authorities from raw rows, tag episode specifications with a closed qualification/outcome stage, and replace the forced NOT_RUN switch with an unreachable geometric input. Qualification remains the only executable stage used before approval.

**Tech Stack:** Python 3.11, NumPy, MuJoCo, pytest, canonical JSON/JSONL/NPZ evidence, deterministic SHA-256 manifests.

## Global Constraints

- Never execute seeds `20261801..20261810` before reviewer approval.
- Never create `results/hierarchical-recovery-v3` during qualification or tests.
- Calibration execution uses only `20261891..20261894`.
- V1/V2 raw, derived, source, and reports remain immutable; Experiment 01 remains import-only and byte-identical.
- Every production change starts with an observed failing test.
- Do not regenerate qualification evidence or make the final consolidation commit until the reviewer findings are complete.

---

### Task 1: Cause-closed observation construction

**Files:**
- Modify: `experiments/03_recovery/src/v3_runtime.py`
- Modify: `experiments/03_recovery/src/v3_evidence.py`
- Test: `experiments/03_recovery/tests/test_v3_runtime.py`
- Test: `experiments/03_recovery/tests/test_v3_evidence.py`

**Interfaces:**
- Consumes: retained `trace_rows`, delivered memory, current command validity, and geometry state.
- Produces: `_observable(...) -> ObservableState` with no injector argument; `cause_boundary_audit() -> Mapping[str, object]` authenticated into Gate 6.

- [ ] **Step 1: Write failing adversarial tests**

```python
def test_impulse_decision_occurs_only_after_retained_physical_effect():
    raw = runtime.run_episode(spec("control-impulse"))
    assert raw.observations[0].tick > raw.realization.injection_tick
    assert raw.observations[0].external_load_mean_nm == runtime.retained_load_estimate(raw.trace, raw.observations[0].tick)

def test_observable_builder_rejects_hidden_taint_and_static_audit_closes_calls():
    assert "current_external_force_nm" not in inspect.signature(runtime._observable).parameters
    audit = evidence.cause_boundary_audit()
    assert audit["passed"] is True
    assert audit["forbidden_call_keywords"] == []
```

- [ ] **Step 2: Run the two tests and observe failures caused by the existing direct injector argument and token-only audit.**

- [ ] **Step 3: Remove `current_external_force_nm` from `_observable`; compute the load estimate from retained q/dq/action history only; ensure policy evaluation follows the first retained post-step effect.**

- [ ] **Step 4: Implement an AST/signature/call-site closure audit that authenticates allowed `_observable` inputs and verifies every `decide` call receives only architecture, typed observable, and budget. Bind its receipt into Gate 6 and episode evidence.**

- [ ] **Step 5: Run runtime/evidence tests and commit the isolated cause-boundary fix after GREEN.**

### Task 2: Independent physical terminal and reset scoring

**Files:**
- Modify: `experiments/03_recovery/src/v3_runtime.py`
- Modify: `experiments/03_recovery/src/v3_scorer.py`
- Modify: `experiments/03_recovery/src/v3_evidence.py`
- Test: `experiments/03_recovery/tests/test_v3_scorer.py`

**Interfaces:**
- Consumes: qpos/eef rows, world and memory ledgers, action/contact envelopes, commands, and receipt time/content bindings.
- Produces: scorer rows containing independently reconstructed target error and reset validity.

- [ ] **Step 1: Write failing tamper tests**

```python
def test_target_error_trace_and_executor_count_are_non_authoritative():
    raw = episode("semantic-object-unavailable")
    trace = {name: value.copy() for name, value in raw.trace.items()}
    trace["target_error_m"][:] = 0.0
    receipts = [dict(item) for item in raw.execution_receipts]
    receipts[0]["executed_valid_ticks"] = 999999
    tampered = replace(raw, trace=trace, execution_receipts=tuple(receipts))
    assert scorer.score_episode(tampered) == scorer.score_episode(raw)

def test_action_window_tamper_invalidates_reset_even_with_positive_executor_count():
    raw = episode("semantic-object-unavailable")
    # Change matching EXECUTE rows to HOLD while leaving receipt count positive.
    assert scorer.score_episode(tampered).violation_counts["reset"] > 0
```

- [ ] **Step 2: Run the tamper tests and observe target/dwell and reset outcomes change under executor-authored fields.**

- [ ] **Step 3: Align qpos and eef sampling to one tick; recompute planar FK and target error in the scorer from qpos plus the latest world/memory target, treating trace target error as debug only.**

- [ ] **Step 4: Change execution receipts to bind content/start/end and a receipt SHA. Reconstruct successful execution from matching valid EXECUTE action rows, trace torque/reference, authorization, and contact rows; ignore the executor-reported count.**

- [ ] **Step 5: Run scorer/runtime tests and commit after all tamper controls are GREEN.**

### Task 3: Frozen approval-gated outcome path

**Files:**
- Modify: `experiments/03_recovery/src/v3_contracts.py`
- Modify: `experiments/03_recovery/src/v3_runtime.py`
- Create: `experiments/03_recovery/src/v3_outcome.py`
- Create: `experiments/03_recovery/run_v3_outcome.py`
- Test: `experiments/03_recovery/tests/test_v3_outcome.py`

**Interfaces:**
- Produces: `RunStage`, `OUTCOME_SEEDS`, `outcome_specs()`, `verify_outcome_approval(...)`, and an executable CLI guarded by immutable qualification/report hashes.

- [ ] **Step 1: Write failing tests that construct but never execute the exact 360-cell outcome plan, reject held-out seeds through qualification APIs, reject missing/mutable approval reports before creating output, and assert the CLI source contains no qualification-time execution side effect.**

- [ ] **Step 2: Run tests and observe missing stage/outcome interfaces.**

- [ ] **Step 3: Add closed stage-tagged sampling with distinct canonical RNG namespaces. Preserve qualification-only defaults; permit `20261801..20261810` only when an explicit immutable OUTCOME stage is present.**

- [ ] **Step 4: Implement the 320 P6 plus 40 P4 plan and approval verifier binding the qualification freeze, raw/derived manifests, source closure, qualified source commit, and reviewer approval report hash.**

- [ ] **Step 5: Add the create-only outcome CLI. Ensure all refusal paths validate approval before output creation or episode execution. Run outcome tests and confirm the prohibited root is absent.**

### Task 4: Authentic geometric NOT_RUN and evidence regeneration

**Files:**
- Modify: `experiments/03_recovery/src/v3_runtime.py`
- Modify: `experiments/03_recovery/src/v3_evidence.py`
- Modify: `experiments/03_recovery/tests/test_v3_runtime.py`
- Modify: `experiments/03_recovery/tests/test_v3_evidence.py`
- Modify: `.superpowers/sdd/hierarchy-v3-qualification-report.md`

**Interfaces:**
- Produces: `PrecheckControlSpec` and `unreachable_precheck_control()` whose target is outside the 0.75 m arm reach; full retained input and independently derived receipt.

- [ ] **Step 1: Replace forced-NOT_RUN tests with a failing test that uses an unreachable target and proves the disposition follows IK/workspace geometry without an override parameter.**

- [ ] **Step 2: Remove `force_not_run`; implement and retain the canonical unreachable input, IK errors, workspace reach, geometry hash, and architecture-independent NOT_RUN receipt.**

- [ ] **Step 3: After consolidated review approval, run all V3 and repository tests, verify frozen files, and commit implementation stages.**

- [ ] **Step 4: Preserve the stale evidence bundle under `/private/tmp`, regenerate the create-only qualification root from the final source commit, reconstruct it cleanly, and verify raw/derived hashes byte-for-byte.**

- [ ] **Step 5: Update and commit the tracked report with new RED/GREEN logs, outcome-path non-execution proof, structural closure receipt, scorer tamper controls, authentic NOT_RUN input, hashes, tests, and remaining concerns.**

### Task 5: Exact T3 memory and fully independent action/mission scoring

**Files:**
- Modify: `experiments/03_recovery/src/v3_contracts.py`
- Modify: `experiments/03_recovery/src/v3_runtime.py`
- Modify: `experiments/03_recovery/src/v3_scorer.py`
- Test: `experiments/03_recovery/tests/test_v3_contracts_policy.py`
- Test: `experiments/03_recovery/tests/test_v3_scorer.py`

**Interfaces:**
- Consumes: the existing immutable `MemoryFact`/`MemorySnapshot` contract from `experiments/03_recovery/src/contracts.py`.
- Produces: exact `T3_LIVE_BELIEF_V1` snapshots with schema ID, semantic label, affordance, restrictions, pose, availability, timestamp, confidence, provenance, stale/unknown dispositions, and evidence-ledger SHA-256.

- [ ] **Step 1: Write RED tests requiring exact T3 canonical snapshots and fail-closed stale/unknown/provenance behavior.**
- [ ] **Step 2: Replace ad-hoc memory dictionaries with typed snapshots plus an append-only evidence ledger; retain both ledger events and authenticated snapshots.**
- [ ] **Step 3: Add RED tamper tests for trace `action_valid`, last-object-only terminal logic, joint/cartesian reference semantics, command trajectory membership, command object/affordance/restriction/target mismatch, and stale/unknown T3 facts.**
- [ ] **Step 4: Reconstruct those authorities from action envelopes, commands, trajectory members, q/eef/contact rows, world truth, and typed memory. Ignore executor trace booleans and require final mission dwell on the currently authorized target.**
- [ ] **Step 5: Run contract/runtime/scorer tests to GREEN and commit the isolated memory/scorer stage.**

### Task 6: Independent gates, complete freeze, authenticated PNG, durable evidence

**Files:**
- Modify: `experiments/03_recovery/src/v3_evidence.py`
- Modify: `experiments/03_recovery/tests/test_v3_evidence.py`
- Create: tracked qualification archive/manifest under `reports/evidence/hierarchical-recovery-v3-qualification/`
- Modify: `.superpowers/sdd/hierarchy-v3-qualification-report.md`

**Interfaces:**
- Produces: gate-specific audit receipts recomputed from raw authorities; complete source/environment closure; deterministic SVG/PNG companions; durable content-addressed evidence inventory.

- [ ] **Step 1: Write RED tests proving Gate 2 checks each disturbance's intended raw channel/units/timing; Gate 5 independently reconstructs elapsed attempts, budgets, content, and execution; Gate 6 consumes the structural closure receipt; Gate 10 recomputes infeasibility from retained geometry rather than receipt Booleans.**
- [ ] **Step 2: Replace self-referential predicates with independent audit functions and retain their full inputs/results as authenticated gate receipts.**
- [ ] **Step 3: Write RED closure tests requiring the preregistration, pyproject, uv.lock, qualification/outcome source/config, Python/MuJoCo/NumPy versions, executable/platform identity, and renderer identity/hash. Expand freeze and reconstruction validation accordingly.**
- [ ] **Step 4: Add a tracked deterministic rasterizer (or already-locked deterministic renderer with frozen version) and emit authenticated PNG companions for every SVG from the same canonical graph table. Test PNG signatures, dimensions, hashes, and replay equality.**
- [ ] **Step 5: Publish a tracked content-addressed archive or complete tracked evidence tree that authenticates every ignored raw/derived member, then prove a fresh checkout can reconstruct/verify without the local ignored root.**
- [ ] **Step 6: Regenerate only after all consolidated tests are GREEN; update exact hashes/counts/report and commit the durable evidence/report.**

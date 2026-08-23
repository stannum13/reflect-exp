# Experiment 06 Validity Repair Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce a distinct Experiment 06 v3 run whose eight candidates are action-byte unique, whose branches restore the complete MuJoCo integration state, and whose reconstruction authenticates and replays every branch.

**Architecture:** Keep the repair inside the existing `world.py`, `run.py`, and focused tests. Candidate identities derive only from the action preimage; anchors retain a canonical MuJoCo state vector; reconstruction treats source Git identity, split identities, and deterministic physics replay as authoritative rather than trusting internally coherent evidence files.

**Tech Stack:** Python 3.11, NumPy, MuJoCo 3.12.0, pytest.

## Global Constraints

- Preserve the v1 and v2 result roots byte-for-byte.
- Record v2 as `INVALID_PRE_FIX` in a tracked sibling artifact.
- Do not implement or execute the model-quality cycle in this plan.
- Rerun exactly 88 scenes, two anchors, eight byte-unique candidates, and 1,408 branches under committed v3 code.
- Use strict RED→GREEN for each task.

---

### Task 1: Action-byte candidate identity

**Files:**
- Modify: `experiments/06_world_model/world.py`
- Modify: `experiments/06_world_model/tests/test_world.py`

**Interfaces:**
- Produces: `Candidate` fields `generation_counter`, `perturbation_magnitude`, `pre_perturbation_sha256`, and `action_sha256`.
- Produces: eight candidates whose `(dtype, shape, command_dt, command_bytes)` preimages and hashes are pairwise unique independent of labels.

- [ ] Add a test that forces two strategy command arrays equal and proves candidate compilation either applies the frozen bounded strategy perturbation or rejects; assert exact `<f8`, `(50,2)`, action bounds, eight unique byte preimages/hashes, and recorded perturbation metadata.
- [ ] Run `.venv/bin/python -m pytest experiments/06_world_model/tests/test_world.py -q` and observe the new assertions fail because metadata and label-independent uniqueness are absent.
- [ ] Implement the minimal fixed perturbation table and bounded generation counter. Hash only canonical dtype/shape/dt plus command bytes; reject non-finite, out-of-bound, semantically invalid, or still-duplicate arrays.
- [ ] Re-run the focused test and require PASS.

### Task 2: Complete MuJoCo anchor state

**Files:**
- Modify: `experiments/06_world_model/world.py`
- Modify: `experiments/06_world_model/tests/test_world.py`

**Interfaces:**
- Produces: `Anchor.state_spec`, `state_size`, `integration_state`, `mocap_pos`, and `restore_sha256`.
- Consumes: MuJoCo `mj_stateSize`, `mj_getState`, and `mj_setState` using one frozen state specification.

- [ ] Add a test that mutates integration fields omitted by the old qpos/qvel snapshot, restores the anchor before two branches, and requires exact post-set state-vector/mocap equality and identical outcomes.
- [ ] Run the focused test and observe failure against the partial snapshot.
- [ ] Capture the complete frozen state vector plus separately required mocap, bind MuJoCo version/spec/size in the restore preimage, restore with `mj_setState`, call `mj_forward`, and fail before stepping unless post-restore values and hash are exact.
- [ ] Re-run the focused test and require PASS.

### Task 3: Authenticated deterministic reconstruction and v2 invalidation

**Files:**
- Modify: `experiments/06_world_model/run.py`
- Modify: `experiments/06_world_model/tests/test_run.py`
- Create: `experiments/06_world_model/results/engineering-ranking-v2-invalid.json`

**Interfaces:**
- Produces: reconstruction that verifies the exact manifest file inventory, recorded Git commit/source blobs, exact frozen split, action/anchor/outcome parent identities, and deterministic replay of all branches before deriving outputs.

- [ ] Add coherent-tamper tests that alter action, anchor, and outcome payloads while recomputing their local hashes/manifests; each must fail only when authoritative regeneration/replay disagrees. Add wrong Git/source/split and extra/missing-file tests.
- [ ] Run `.venv/bin/python -m pytest experiments/06_world_model/tests/test_run.py -q` and observe the coherent tamper cases reconstruct successfully or fail for the wrong reason.
- [ ] Implement strict schemas and identity joins, validate the recorded commit's four source blobs, regenerate every frozen scene/anchor/candidate, replay every branch, and compare canonical rows/hashes before fitting or deriving.
- [ ] Write the tracked invalidation object with status `INVALID_PRE_FIX`, exact v2 manifest SHA-256, reason codes for all three findings, and no authority.
- [ ] Run all Experiment 06 tests and require PASS; commit code/tests/invalidation before executing v3.
- [ ] Execute the exact 88-scene v3 matrix under the committed source, reconstruct to a clean directory, require byte equality, and commit only the rigorous v3 report/manifest identities while leaving evidence ignored.

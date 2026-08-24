# Exp16 Route-Boundary Replication Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: use test-driven development.

**Goal:** Run a fresh, independently preregistered direct-hierarchy replication
in which dynamic motion-route exhaustion is a typed safe abort and scored task
failure rather than an invalid Python exception.

**Architecture:** Preserve Exp15 V2's MuJoCo runtime, R0-R3 observable-only
policy, P6/P4 controllers, disturbance doses, 540-cell matrix, metrics, evidence
closure, and statistical gates. Add only a typed `MotionPlanUnavailable` domain
result and convert it at runtime decision-application boundaries into one
`SAFE_ABORT` decision followed by HOLD. Use fresh identity `exp16` and seeds
`20262401..20262410`; never inspect Exp15 outcomes while selecting behavior.

**Tech stack:** Python 3.11, MuJoCo, NumPy, pytest, Ruff, deterministic canonical
JSON/CSV/SVG/PNG evidence.

## Global constraints

- No VLA or semantic-plan claim; this is a synthetic physical hierarchy test.
- No new route candidates, fallback planner, retry budget, controller tuning,
  semantic escalation, or scenario/family/severity oracle at the policy boundary.
- `MotionPlanUnavailable` alone becomes `SAFE_ABORT` with reason
  `MOTION_PLANNER_NO_ROUTE`; unrelated exceptions remain `INVALID_EXECUTION`.
- Append exactly one decision at a tick; subsequent envelopes HOLD; independent
  scorer must produce task `FAILURE` with zero loop/invalid-action violations.
- Freeze source, analysis, verifier, tests, and exact matrix before outcomes.
- Independent source approval is required before freeze; full 540-cell preflight
  precedes execution; create-only outcomes preserve NOT_RUN/INVALID dispositions.
- Stop and independently review at 50 cells. Publish all 540 dispositions, all
  complete manifests, full local inventory, selected working/nonworking raw,
  10,000 seed-cluster draws, exact graph data/style, SVG/PNG, and attack tests.

---

### Task 1: Typed route-exhaustion boundary

**Files:**
- Modify: `experiments/03_recovery/src/v3_runtime.py`
- Test: `experiments/03_recovery/tests/test_v3_runtime.py`

- [ ] Write real-runtime tests for P6/R2, P6/R3, and P4/R3 that first seal a
  READY precheck, then force only the runtime route computation to raise the
  typed domain result. Verify the tests fail because the result is not handled.
- [ ] Add `MotionPlanUnavailable` and raise it only when both frozen waypoint
  candidates are unavailable.
- [ ] At both motion-decision application sites, replace that one decision with
  `SAFE_ABORT/MOTION_PLANNER_NO_ROUTE`, set abort/HOLD state, and keep unrelated
  exceptions uncaught.
- [ ] Verify the scorer reports task failure, one safe abort, subsequent HOLD,
  and zero loop/invalid-action violations; run recovery and prior Exp15 tests.
- [ ] Commit the minimal runtime/test change.

### Task 2: Fresh frozen Exp16 experiment

**Files:**
- Create: `experiments/16_route_boundary_replication/`
- Create: `docs/superpowers/specs/2026-08-24-exp16-route-boundary-replication.md`

- [ ] Copy the reviewed Exp15 evidence lifecycle into a fresh namespace; change
  only experiment/episode IDs, seeds, the declared route-boundary behavior, and
  paths. Preserve controllers, matrix, doses, metrics, gates, bootstrap, closure,
  first-50 approval gate, exact pack schemas, and attack regressions.
- [ ] Add parity tests against Exp15 for every unchanged matrix/config/dose and
  a direct test that route exhaustion seals `COMPLETE` with scored failure rather
  than `INVALID_EXECUTION`.
- [ ] Run focused tests, Ruff, and diff-check; commit source/preregistration.
- [ ] Obtain independent audit bound to the exact source commit. Do not self-
  approve, freeze, preflight, or run before an approval commit exists.

### Task 3: Outcomes and evidence

**Files:**
- Create during lifecycle: tracked Exp16 freeze/preflight/approval receipts.
- Create: `reports/evidence/exp16-route-boundary-replication/`

- [ ] Freeze the approved Git tree and preflight all 540 cells.
- [ ] Run exactly 50 create-only dispositions, request independent continuation
  review, then run the remaining 490 unchanged.
- [ ] Analyze with actual paired seed-cluster `n_eff`; `INVALID_EXECUTION` has
  formal precedence over statistical gates.
- [ ] Publish and seal the compact evidence pack; verify it in a clean clone.
- [ ] Obtain independent final evidence review and integrate only its approved
  scope into the program ledger.

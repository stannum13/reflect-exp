# V3 Seventh-Review Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fully authenticate the visible V3 qualification report and restore exact agreement among the canonical qualification root, source closure, tracked archive, and report.

**Architecture:** Extend the existing report verifier with artifact-derived, exactly-once visible-fact checks. Preserve stale evidence by rename plus a canonical receipt, then regenerate calibration-only evidence because the verifier edit changes the frozen source closure and deterministically reseal all retained publication artifacts.

**Tech Stack:** Python 3.11, pytest, canonical JSON, SHA-256, deterministic tar/gzip evidence publisher.

## Global Constraints

- Do not run held-out outcome seeds `20261801..20261810`.
- Preserve the stale ignored root recoverably.
- Use create-only evidence publication and exact-byte reconstruction.
- Remove only Experiment 03 ignored Python cache artifacts before final validation.

---

### Task 1: Exhaustive visible-report authentication

**Files:**
- Modify: `experiments/03_recovery/tests/test_v3_evidence.py`
- Modify: `experiments/03_recovery/src/v3_evidence.py`

**Interfaces:**
- Consumes: `verify_qualification_report(output, report, archive_manifest=...)`
- Produces: the same API with exact, unique artifact-derived checks for every mutable visible fact.

- [ ] Add focused tests that mutate `Files: **437**` to `999`, gate count `10` to `0`, duplicate a mutable visible field, and alter representative status/count/hash/test-result facts.
- [ ] Run only the new tests and verify they fail because the current verifier accepts the attacks.
- [ ] Implement declarative anchored matchers whose expected values are derived from freeze, raw/derived evidence, reconstruction receipts, gate audits, diagnostic files, archive manifest, and report-independent source data.
- [ ] Run focused tests and the existing report/evidence tests to GREEN.
- [ ] Commit source and tests atomically.

### Task 2: Recover and reseal canonical qualification evidence

**Files:**
- Preserve: `results/hierarchical-recovery-v3-qualification` as a uniquely named superseded sibling.
- Create: superseded disposition receipt beside the preserved root.
- Recreate: `results/hierarchical-recovery-v3-qualification`
- Modify: `.superpowers/sdd/hierarchy-v3-qualification-report.md`
- Replace: `reports/evidence/hierarchical-recovery-v3-qualification/manifest.json`
- Replace: the content-addressed archive in `reports/evidence/hierarchical-recovery-v3-qualification/`

**Interfaces:**
- Consumes: calibration-only `run_v3_qualification`, `reconstruct`, and `publish_durable_archive`.
- Produces: one source-bound canonical root, tracked deterministic archive, exact report, and recoverable superseded evidence receipt.

- [ ] Inventory and hash the stale root, rename it atomically, and write a canonical disposition receipt recording its hashes and superseded status.
- [ ] Safely inspect and extract the currently authenticated tracked archive into the canonical location as the recovery baseline.
- [ ] Remove only governed ignored Python caches, then run fresh calibration-only qualification for the changed source into a clean canonical root.
- [ ] Reconstruct all qualification evidence byte-exactly, publish the deterministic tracked archive, and update every visible report fact from artifacts.
- [ ] Verify canonical root, report, source closure, archive extraction, recursive inventory, and reconstruction agree exactly.
- [ ] Commit the tracked report/archive/manifest atomically; ignored evidence remains preserved locally.

### Task 3: Complete validation

**Files:**
- Verify all files above; no new implementation files.

**Interfaces:**
- Consumes: final source and retained evidence.
- Produces: evidence-backed implementation handoff for an independent reviewer.

- [ ] Run focused verifier/evidence regressions.
- [ ] Run the full V3 selection and complete Experiment 03 suite.
- [ ] Run canonical structured authentication and clean reconstruction.
- [ ] Confirm `git diff --check`, clean tracked status, no outcome root, no held-out seed artifacts, and cache inventory.
- [ ] Record commits and exact source/freeze/raw/derived/tree/archive/report hashes without self-approving outcomes.

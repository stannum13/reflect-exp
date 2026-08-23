# P5 Temporal Action-Chunk Execution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build runnable Experiment 02 evidence that determines how unissued future actions should be reconciled under controlled latency and perturbations, while preserving every scheduled outcome and enabling clean-directory reconstruction.

**Architecture:** Start with one deliberately non-scientific, pure-Python broker qualification slice that executes several policy/chunk conditions end to end and publishes immutable raw events, dispositions, annotated working/nonworking cases, and a deterministic reconstruction recipe. Then implement the full virtual schedule, broker, P4 adapter, authentic prerequisite gate, bundle/replay path, supervised pilot/confirmation lifecycle, and analysis/report path described by the approved P5 design. All implementation and evidence code lives under `experiments/02_action_chunks`; shared `reflect/` and dirty Experiment 01 files are read-only dependencies.

**Tech Stack:** Python 3.11, NumPy float64, PyYAML with duplicate-key rejection, PyArrow/Parquet for bounded proposal payloads, existing Reflect rollout/event/safety APIs, P4 MuJoCo arm/controller, pytest with plugin autoload disabled, Ruff.

## Global Constraints

- Experiment 02 compares exactly A `OPEN_LOOP`, B `RECEDING_PREFIX`, C `TEMPORAL_ENSEMBLE`, D `LATEST_VALID`, E `ASYNC_SAFE_PREFIX`, F `OVERLAP_BLEND`, and G `RTC_APPROXIMATION`; G is never `RTC_COMPATIBLE` without the distinct provenance-bound implementation.
- Behavior time is virtual. One tick is `D=0.002 s`; proposal period is `P=0.100 s`; `Q=50`, `H=9`, raw knots `N_knot=401`, executable proposal rows `N=125`, measured origin `S=50`, request cutoff `C=2500`, and terminal tick `3125`.
- Core latencies are exactly `{25,75,150,350}` ticks and move schedules are exactly `(51,)` and `(51,1052)`.
- Candidate vectors are exactly `v0=(1,1,0,1,1,25)`, `v1=(2,2,1,2,2,75)`, and `v2=(4,4,4,4,4,124)` in `(K_B,I,lambda,M,L,J_E)` order.
- The pilot uses four tuning and four untouched validation seeds; confirmation uses 32 paired seeds; bootstrap uses 10,000 deterministic PCG64 resamples and fixed worthwhile effect `delta=0.05`.
- P5 has one retained pilot revision, at most 6,464 episode bundles, retained-plus-live maximum 7,502 MiB, 50 wall hours, and 124 CPU hours. Every episode bundle is at most 1,048,576 bytes.
- No VLA training, checkpoint, public server, ROS, CUDA, remote transport, physical connection, upstream source copy, or shared Reflect schema change is permitted.
- Every unsafe environment or failed P3/P4 gate fails before MuJoCo import and before scientific output. A prerequisite failure is `NOT_RUN`, never an experimental `INCONCLUSIVE` result.
- Every evidence-bearing stage retains immutable raw rows/events, one disposition for every scheduled identity, deterministic annotated working/nonworking cases, plot-ready tables/recipes, and a clean-directory regeneration check.
- Results never drop failed, timed-out, crashed, excluded, declared-missing, or invalid cases. Bounded storage uses typed tables and content-addressed deduplication only.

## File Ownership

| Path | Responsibility |
|---|---|
| `experiments/02_action_chunks/src/qualification.py` | Early pure-Python end-to-end broker qualification and evidence reconstruction |
| `experiments/02_action_chunks/src/contracts.py` | Closed enums, immutable row types, canonical JSON and validation |
| `experiments/02_action_chunks/src/schedule.py` | Pure A--G core/fault iterator and exact counts |
| `experiments/02_action_chunks/src/broker.py` | Queue lifecycle, C/F/G transforms, replacement, rejection, and hold transitions |
| `experiments/02_action_chunks/src/adapter.py` | Nine P4 knots to 125 absolute-tick rows and representation dispatch |
| `experiments/02_action_chunks/src/evidence.py` | Raw bundle, disposition, payload-table, sample-index, recipe, and replay validation |
| `experiments/02_action_chunks/src/gate.py` | Authentic P3/P4/P1 provenance and pre-import eligibility |
| `experiments/02_action_chunks/src/protocol.py` | Pilot/freeze/confirmation manifests, cells, multiplicity, and resources |
| `experiments/02_action_chunks/src/supervisor.py` | Per-attempt process supervision, receipts, shard closure, recovery, and resource ledger |
| `experiments/02_action_chunks/src/evaluate.py` | Aggregation, bootstrap, gates, decision, and reconstruction |
| `experiments/02_action_chunks/run.py` | The sole staged CLI; gates before local physics imports/output |
| `experiments/02_action_chunks/tests/` | Unit, adversarial, integration, replay, and reconstruction tests |

---

### Task 1: Runnable broker qualification vertical slice

**Files:**
- Create: `experiments/02_action_chunks/__init__.py`
- Create: `experiments/02_action_chunks/src/__init__.py`
- Create: `experiments/02_action_chunks/src/qualification.py`
- Create: `experiments/02_action_chunks/tests/test_qualification.py`

**Interfaces:**
- Consumes: stdlib only; this is explicitly test/qualification evidence and cannot satisfy the scientific P4 gate.
- Produces: `QualificationCondition`, `run_qualification(output_dir: Path) -> None`, `reconstruct_qualification(raw_dir: Path, clean_dir: Path) -> None`, and CLI `python -m experiments.02_action_chunks.src.qualification --output-dir PATH [--reconstruct-from PATH]`.

- [ ] **Step 1: Write RED tests for a varied end-to-end slice**

```python
def test_slice_preserves_working_and_nonworking_cases(tmp_path):
    run_qualification(tmp_path / "evidence")
    trials = read_jsonl(tmp_path / "evidence/raw/trials.jsonl")
    assert {(r["protocol_id"], r["policy_condition"], r["latency_ticks"])
            for r in trials} == {
        ("A", "SMOOTH", 25), ("A", "DROPPED", 150),
        ("D", "TARGET_SHIFT", 25), ("D", "DISCONTINUOUS", 150),
        ("F", "ALTERNATIVE", 25), ("F", "DROPPED", 150),
    }
    assert {r["disposition"] for r in trials} == {"WORKING", "NONWORKING"}

def test_reconstruction_is_byte_exact_in_clean_directory(tmp_path):
    run_qualification(tmp_path / "evidence")
    reconstruct_qualification(tmp_path / "evidence/raw", tmp_path / "clean")
    assert_tree_bytes_equal(
        tmp_path / "evidence/derived",
        tmp_path / "clean",
        names=("trial-table.csv", "sample-index.json", "recipe.json"),
    )
```

- [ ] **Step 2: Run the focused test and observe RED**

Run: `PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -p no:cacheprovider experiments/02_action_chunks/tests/test_qualification.py -q`

Expected: collection fails because `qualification.py` does not exist.

- [ ] **Step 3: Implement the smallest full data path**

Use an immutable one-dimensional action fixture over ticks `0..249`. A proposal is a tuple of finite floats plus half-open validity. A and D replace futures directly; F uses `beta=(j+1)/(M+1)` over compatible overlap with `M=2`. Record every request/delivery/accept/reject/issue/hold event in canonical `raw/events.jsonl` and every scheduled case in canonical `raw/trials.jsonl`, including `schema_version,study_id,qualification_only,protocol_revision,condition_id,protocol_id,policy_condition,seed,rng_namespace,latency_ticks,tick_start,tick_end,units,frame,config_sha256,events_sha256,terminal_state,validity,disposition,analysis_included`.

The six frozen cases above must contain smooth, target-shift, alternative-strategy, discontinuous, and dropped proposals. `WORKING` requires finite issued values, no expired issue, immutable prior issues, terminal empty queue, and no hold before the case recovery deadline. `NONWORKING` is an observed qualification outcome, not missing evidence. `raw/dispositions.jsonl` has exactly one row per case and never overwrites the trial.

Select annotated examples independently within each `(protocol_id,policy_condition)` by ascending `(seed,condition_id)`: first `WORKING`, first `NONWORKING`; emit `CLASS_NOT_OBSERVED` with eligible denominator when absent. Each sample row binds event line range, trial identity, command, raw hashes, and label. `recipe.json` fixes source hashes, sorting, filters, units, and renderer `exp02-qualification-v1`. Reconstruction accepts an absent clean destination only and regenerates derived bytes solely from raw inputs.

- [ ] **Step 4: Prove determinism and negative behavior**

Add tests for expired-action rejection, dropped response entering hold, discontinuity classification, prior-issued hash stability after a later delivery, duplicate/unknown raw keys, a missing disposition, hand-picked sample-index tampering, dirty reconstruction destination, and two fresh runs producing byte-identical raw/derived artifacts.

- [ ] **Step 5: Run and commit the qualification slice**

Run: focused test twice, Ruff on the four paths, and `git diff --check`.

Commit only the four Task 1 paths as `feat: add runnable P5 broker qualification`.

---

### Task 2: Closed contracts and exact A--G schedule

**Files:**
- Create: `experiments/02_action_chunks/src/contracts.py`
- Create: `experiments/02_action_chunks/src/schedule.py`
- Create: `experiments/02_action_chunks/tests/test_contracts.py`
- Create: `experiments/02_action_chunks/tests/test_schedule.py`

**Interfaces:**
- Consumes: constants in Global Constraints.
- Produces: `ProtocolId`, `VectorId`, `FaultId`, `CellIdentity`, `RequestPlan`, `iter_cells(stage, stack_rows)`, `iter_request_ticks(cell)`, and `schedule_sha256(cells)`.

- [ ] **Step 1: Write RED schema and golden-schedule tests**

Assert closed enum values, bool-as-int rejection, immutable sorted identities, exact per-seed counts A=11, B/E=12, C/D/F/G=12 for v0 and 13 for v1/v2, and exact hand schedules: core `50/51/75/1051/1052/2052`, periodic I=1 `50/125/126/201/202`, I=2 `50/100/200/201`, E continuity classes, old-after-newer `201/251/401/402`, and terminal pause delivery 3000/expiry 3125.

- [ ] **Step 2: Run RED, implement pure iterators, then run GREEN**

The iterator must be the sole source used by tests, manifests, and runner. It emits no I/O and rejects a request after tick 2500, a queue above I, an altered move schedule, an N/A old-after-newer cell, or a count above the sealed maxima.

- [ ] **Step 3: Commit exact schedule contracts**

Commit only the four Task 2 paths as `feat: define P5 protocol schedule`.

---

### Task 3: Broker lifecycle and transforms

**Files:**
- Create: `experiments/02_action_chunks/src/broker.py`
- Create: `experiments/02_action_chunks/tests/test_broker.py`
- Create: `experiments/02_action_chunks/tests/test_broker_faults.py`

**Interfaces:**
- Consumes: `CellIdentity`, `RequestPlan`, existing `ActionChunk` and event contracts.
- Produces: `NormalizedProposal`, `BrokerTransition`, `TemporalBroker.accept/deliver/issue/finish`, `derive_ensemble`, `derive_overlap_blend`, and `derive_rtc_approximation`.

- [ ] **Step 1: Write RED lifecycle tests**

Cover direct A/B/D/E, C contributor order and expiry recomputation, F/G exact `h`, out-of-order rejection, expired rejection, drop versus pause, terminal empty queues, at most one request per tick, immutable issued float64 C-order arrays, and distinct direct/derived/rejected/hold IDs.

- [ ] **Step 2: Implement the transition table without wall time**

Use only integer ticks. Process move, request, ordered delivery, broker transition, issue, telemetry, advance. Already issued rows are absent from every transform. A safe hold is a separately typed broker origin and never an overlap parent.

- [ ] **Step 3: Add exact fault-payload tests and implementation**

Implement revision `exp02-fault-payload-v1`, exact P2/P4 directions/amplitudes, sign order, alternative sine detour, discontinuity step at row 2, pre/post hashes, and no clamping. Reject either-sign failure rather than changing amplitude.

- [ ] **Step 4: Commit broker invariants**

Commit only Task 3 paths as `feat: implement P5 temporal broker`.

---

### Task 4: P4 proposal adapter and representation-safe hold

**Files:**
- Create: `experiments/02_action_chunks/src/adapter.py`
- Create: `experiments/02_action_chunks/tests/test_adapter.py`
- Create: `experiments/02_action_chunks/tests/test_hold_dispatch.py`

**Interfaces:**
- Consumes: immutable nine-knot P2/P4 policy output and P4 interpolation/controller functions.
- Produces: `PolicyRaw`, `normalize_policy_raw(raw, actual_delivery_tick)`, `dispatch_executable`, and `make_safe_hold`.

- [ ] **Step 1: Write RED byte-reconstruction tests**

Assert exact nine rows at 100 ms, exactly 125 normalized rows at 2 ms, source observation preservation, coverage anchored to actual delivery, P2 width 3/P4 width 2, little-endian float64 C order, and byte-exact inverse verification from stored policy rows.

- [ ] **Step 2: Implement interpolation and reject truth leakage**

Use the frozen P4 interpolation only. The adapter cannot read executor state, future target moves, later observations, or outcomes. Pause generates no raw/normalized row before actual delivery.

- [ ] **Step 3: Implement and test joint-PD hold dispatch**

Latch current q, desired dq=0, controller mode `p5_joint_pd_hold`, no DIK/null-space call, one hold until replacement/terminal, and exact terminal clear.

- [ ] **Step 4: Commit the adapter**

Commit only Task 4 paths as `feat: adapt P4 proposals for P5`.

---

### Task 5: Immutable raw episode bundles and replay

**Files:**
- Create: `experiments/02_action_chunks/src/evidence.py`
- Create: `experiments/02_action_chunks/tests/test_evidence.py`
- Create: `experiments/02_action_chunks/tests/test_reconstruction.py`

**Interfaces:**
- Consumes: canonical rollout, proposals, policy raw, normalized proposals, derived chunks, references, metrics, and one scheduled `CellIdentity`.
- Produces: `write_bundle`, `validate_bundle`, `replay_bundle`, `build_sample_index`, `write_visualization_recipe`, and `reconstruct_stage`.

- [ ] **Step 1: Write RED exact-inventory tests**

Require canonical rollout/events, `proposals.jsonl`, typed `policy-raw-actions.parquet`, typed `normalized-proposals.parquet`, derived-chunk rows, issued references, metrics, disposition, and manifest-last inventory. Enforce 450 policy rows/65,536 bytes, 6,250 normalized rows/262,144 bytes, and total bundle 1 MiB.

- [ ] **Step 2: Implement descriptor-safe create-only bundles**

Write/fsync a private same-parent bundle, manifest last, then rename only to an absent identity. Exact reissue validates and skips. Conflicting, symlinked, noncanonical, unlisted, or partial evidence fails; same-process cleanup removes only held inodes.

- [ ] **Step 3: Implement full replay and reconstruction**

Rebuild policy matrices, normalize, reverse/reapply fault transforms, reconstruct C/F/G, resolve hold actions, reproduce issued rows and terminal inactive state. A dropped request has no payload rows; a paused request has rows only at actual delivery.

- [ ] **Step 4: Implement evidence-fidelity outputs**

Every scheduled identity gets `COMPLETE|DECLARED_MISSING|INVALID` disposition without deleting raw bytes. Sample selection is preregistered ascending identity within each evaluated condition/class. Plot recipes bind raw hashes, filters, pair keys, axes/units, statistics/intervals, palette, dimensions, renderer version, and seed. Clean-directory regeneration compares canonical tables exactly and raster pixels only at a declared zero or numeric tolerance.

- [ ] **Step 5: Commit evidence and replay**

Commit only Task 5 paths as `feat: preserve reconstructable P5 evidence`.

---

### Task 6: Authentic P4 eligibility and P1 conformance gate

**Files:**
- Create: `experiments/02_action_chunks/src/gate.py`
- Create: `experiments/02_action_chunks/tests/test_gate.py`

**Interfaces:**
- Consumes: final P4 publication chain and the seven exact P1 modules.
- Produces: `FrozenPrerequisites`, `validate_prerequisites(repo_root, p4_publication_sha)`, `write_preflight_status`, and `p1_conformance_probe`.

- [ ] **Step 1: Write RED authentic Git-fixture tests**

Cover exact P4 P3-gate bytes/blob, implementation allowlist, preregistration and publication ancestry, promoted P2/P4 representations, decision/frozen/protocol/artifact hashes, seven-row P1 module ledger, conformance fixture hashes, clean tree, and every missing/extra/symlink/content/blob mutation.

- [ ] **Step 2: Implement fixed local-Git and descriptor snapshots**

Use no replacement objects, no lazy fetch, no shell, closed commands, stable no-follow reads, and re-snapshot after validation. Return only derived identities; no caller-supplied digest is authoritative.

- [ ] **Step 3: Implement failed-gate semantics**

Dry-run writes nothing. A live failed gate may create only exact create-only `results/preflight/status.json` with `NOT_RUN/FAILED_GATE`; it cannot create a decision, bundle, config, or report.

- [ ] **Step 4: Commit the eligibility gate**

Commit only Task 6 paths as `feat: gate P5 on authentic P4 evidence`.

---

### Task 7: Protocol manifests, resources, and supervised attempts

**Files:**
- Create: `experiments/02_action_chunks/src/protocol.py`
- Create: `experiments/02_action_chunks/src/supervisor.py`
- Create: `experiments/02_action_chunks/tests/test_protocol.py`
- Create: `experiments/02_action_chunks/tests/test_supervisor.py`
- Create: `experiments/02_action_chunks/tests/test_resume.py`

**Interfaces:**
- Consumes: exact cell iterator, prerequisite hashes, code SHA, and resource maxima.
- Produces: pilot/confirmation manifests, `AttemptReceipt`, `supervise_shard`, shard completion marker, resource ledger, stage index, terminal manifest, and recovery quarantine.

- [ ] **Step 1: Write RED count/resource and receipt-chain tests**

Assert 1,288 pilot and 1,944 confirmation rollouts per stack, two-stack 6,464 bundles, 7,502 MiB, 50 wall hours, 124 CPU hours, contiguous receipt indexes/hashes, receipt-before-retry, exact shard/stage aggregation, and conservative recovered-host charging.

- [ ] **Step 2: Implement process-group supervision**

Start the worker in a new group, close inherited FDs except capability pipes, drain stdout/stderr concurrently, retain first/last 32 KiB and full hashes, TERM at 60 minutes, KILL after five seconds, drain EOF, reap, then seal receipt before any next action.

- [ ] **Step 3: Implement shard/stage closure and recovery**

Each identity resolves to bundle or tombstone. Mixed shards preserve complete cells and declared missing cells. Marker/index inventories are exact and create-only. Restart quarantines verified orphan partials without deletion and seals one host-interruption receipt before redispatch. Normal and terminal manifests are mutually exclusive.

- [ ] **Step 4: Commit protocol execution accounting**

Commit only Task 7 paths as `feat: supervise resumable P5 shards`.

---

### Task 8: Sole CLI and serial invariant pilot

**Files:**
- Create: `experiments/02_action_chunks/run.py`
- Create: `experiments/02_action_chunks/configs/pilot-r1.yaml`
- Create: `experiments/02_action_chunks/protocol/pilot-r1/tuning-seeds.json`
- Create: `experiments/02_action_chunks/protocol/pilot-r1/validation-seeds.commitment.json`
- Create: `experiments/02_action_chunks/.gitignore`
- Create: `experiments/02_action_chunks/README.md`
- Create: `experiments/02_action_chunks/CLAIM.md`
- Create: `experiments/02_action_chunks/EXPERIMENT.md`
- Create: `experiments/02_action_chunks/RESULTS.md`
- Create: `experiments/02_action_chunks/INTERFACE_FINDINGS.md`
- Create: `experiments/02_action_chunks/tests/test_cli.py`
- Create: `experiments/02_action_chunks/tests/test_pilot.py`

**Interfaces:**
- Consumes: Tasks 2--7 and P4 runner internals only after gate success.
- Produces: exact `pilot tuning|select|validation`, `freeze`, `confirmation`, `analyze`, `report`, plus `--dry-run` plans.

- [ ] **Step 1: Write RED pre-import and CLI-shape tests**

Assert safety/P3/P4 gate precedes MuJoCo import/output, public CLI cannot invoke worker, seed is assertion only, dry-run is zero-write/no-MuJoCo, paths are root-relative/contained, and stage order/inventories are closed.

- [ ] **Step 2: Implement dry-run and one real end-to-end pilot shard**

Run one manifest-derived A core cell and one candidate core cell serially through P4, broker, raw bundle, replay validation, shard marker, stage index, annotated sample index, recipe, and clean reconstruction. This is the first scientific-path vertical slice; stop and fix it before dispatching the remaining pilot cells.

- [ ] **Step 3: Run the full tuning/select/validation pilot serially**

Select vectors independently by `(stack,protocol)` using equal-weight eight-core recovery and zero invariant failures; ties v0/v1/v2. Preserve failed candidates and all dispositions. Reveal validation seeds only after selection. A valid PRIMARY zero-survivor result freezes `NOT_SUPPORTED` with OPEN_LOOP fallback and no authority.

- [ ] **Step 4: Commit implementation inputs before live pilot**

Create and commit the exact required placeholder documents and ignore rules in the same reviewed implementation commit; do not commit generated results. Record the implementation SHA before pilot execution.

---

### Task 9: Freeze and unseen confirmation

**Files:**
- Create: `experiments/02_action_chunks/configs/frozen.yaml`
- Create: `experiments/02_action_chunks/protocol/pilot-r1/pilot-selection.json`
- Create: `experiments/02_action_chunks/protocol/pilot-r1/validation-seeds.revealed.json`
- Create: `experiments/02_action_chunks/protocol/confirmation/seed-manifest.json`
- Create: `experiments/02_action_chunks/tests/test_freeze.py`
- Create: `experiments/02_action_chunks/tests/test_confirmation.py`

**Interfaces:**
- Consumes: validated pilot selection and untouched confirmation RNG procedure.
- Produces: immutable PRIMARY family/m, descriptive arms, G roles, paired confirmation cells, and execution commit.

- [ ] **Step 1: Write RED freeze/null-matrix tests**

Assert stack-qualified vector selection, PRIMARY/DESCRIPTIVE isolation, maximum family 5 or provenance-backed 6, exact G roles, no seed materialization before freeze, byte-equal family in every later artifact, and zero-survivor branch without confirmation.

- [ ] **Step 2: Freeze and commit exactly four generated paths**

Validate pilot artifacts, derive unseen seeds once, force-add only the four declared freeze paths, commit, and require a clean execution HEAD before confirmation.

- [ ] **Step 3: Execute confirmation serially and reconstruct all outputs**

Run A once per paired seed, every frozen PRIMARY survivor, every descriptive arm, fault probes on first four seeds, and stationary controls. Validate every bundle/replay/disposition/sample index and regenerate all plot-ready tables in a clean directory before analysis.

---

### Task 10: Analysis, decision, and reproducible reports

**Files:**
- Create: `experiments/02_action_chunks/src/evaluate.py`
- Create: `experiments/02_action_chunks/tests/test_evaluate.py`
- Create: `experiments/02_action_chunks/tests/test_report.py`
- Modify: `experiments/02_action_chunks/RESULTS.md`
- Modify: `experiments/02_action_chunks/INTERFACE_FINDINGS.md`

**Interfaces:**
- Consumes: validated frozen family, raw confirmation bundles/tombstones, resource ledgers, and recipes.
- Produces: `aggregate.csv`, optional `bootstrap.json`, `decision.json`, `ACTION_EXECUTION_DECISION.md`, three final Markdown renders, and report manifest.

- [ ] **Step 1: Write RED scoring/bootstrap/decision tests**

Assert paired per-seed eight-cell means, one allowed missing pair, 10,000 exact PCG64 resamples, Bonferroni probabilities/indexes, strict `lower>0.05`, width <=0.20, core gate matrix, stationary control, fault guard separation, zero-survivor and completed-negative OPEN_LOOP fallback, G-only support, no authority on blocked/inconclusive outcomes, and hostile reason escaping.

- [ ] **Step 2: Implement analysis from validated evidence only**

No MuJoCo import and no output mutation during scoring. Corruption is `INVALID`, not missing. Censored non-recovery is observed zero. Descriptive arms cannot alter PRIMARY scientific result or authority.

- [ ] **Step 3: Implement deterministic report and visualization regeneration**

Regenerate every CSV/table/graph from raw evidence in an absent clean directory using sealed recipes, compare canonical table bytes and declared pixel tolerances, then render `RESULTS.md`, `INTERFACE_FINDINGS.md`, and `ACTION_EXECUTION_DECISION.md` byte-for-byte. Replace only reviewed placeholders; publish the report manifest last.

- [ ] **Step 4: Run final verification and commit evidence surfaces**

Run all Experiment 02 tests offline with plugin autoload disabled, P1/P3/P4 gate tests, safety and source audits, Ruff, secret/tracked-model scan, generated-size audit, and `git diff --check`. Commit only the two final Markdown replacements, decision Markdown, and report marker; require clean status and rerun clean-directory reconstruction.

---

## Plan Self-Check

- The early Task 1 slice is runnable before P4 completion, varies protocol, latency, and policy/chunk conditions, retains working and nonworking cases, and is explicitly barred from scientific promotion.
- Task 8 repeats the vertical-slice discipline on the authentic P4 path before broad pilot dispatch.
- Tasks 1, 5, 8, 9, and 10 jointly cover immutable raw evidence, every disposition, preregistered annotated samples, plot/recipe provenance, and clean-directory regeneration.
- Tasks 2--4 cover every A--G recurrence, transform, fault schedule, hold, terminal, and immutable-issue invariant.
- Tasks 6--7 cover authentic prerequisites, resources, attempts, retry safety, mixed shard outcomes, and recovery.
- Tasks 8--10 cover pilot selection, multiplicity, confirmation, decision, fallback, authority, and final publication.
- No task modifies `reflect/` or an Experiment 01 file. The first implementation task owns only new Experiment 02 paths and therefore does not overlap the dirty worktree.
- Placeholder scan: the plan contains no deferred implementation markers; the literal reviewed result placeholder is specified only by the approved design contract.

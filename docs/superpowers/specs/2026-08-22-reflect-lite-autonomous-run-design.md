# Reflect-Lite Autonomous Research Run Design

Date: 2026-08-22

Status: approved by the user's instruction to operationalize the supplied research
program and continue autonomously without routine review loops.

Canonical input: `Reflect Lite Research Program.md`

## 1. Outcome

The run will turn the research program into a reproducible, evidence-bearing
repository and continue through every locally justified experimental gate. It will
not optimize for a positive result. It will optimize for defensible decisions about
interfaces, timing, recovery ownership, persistent state, learned prediction, and
Unitree R1 transfer.

The first checkpoint is the program's P0-P10 autonomous pass. Reaching that
checkpoint does not complete the persistent goal. After P0-P10, the orchestrator
continues into locally justified dependent and integration experiments until the
program success criterion is met or a genuine external prerequisite prevents
further progress.

Remote GPU training, custom R1 simulation, real-data capture, and Experiment 10 are
conditional extensions. They are never inferred to be available. Physical robot
communication is outside this run.

## 2. Approaches considered

### A. Literal maximum parallelism

Start Experiments 00, 01, 04, 05, 06, and 08 immediately in independent workers.

This produces prototypes quickly, but it allows workers to invent incompatible
schemas, duplicates harness work, contaminates latency measurements through local
resource contention, and permits result-dependent metric selection. It is rejected
for evidence-bearing work.

### B. Strict sequential gates

Complete every experiment in numeric order before starting the next.

This gives simple provenance but needlessly delays independent memory, world-model,
and source-audit work. It also underuses the parallel structure explicitly requested
by the user. It is rejected.

### C. Staged hybrid

Run one serial bootstrap and preregistration stage, then open independent lanes with
explicit promotion checkpoints and untouched confirmation sets.

This preserves useful parallelism while preventing downstream experiments from
silently redefining upstream contracts. This is the selected approach.

## 3. Scope and authority

The canonical program remains authoritative for research questions, safety,
non-goals, required artifacts, and experiment gates. This design resolves only its
operational ambiguities.

The orchestrator may make conservative, reversible choices without user input. It
must record those choices in `docs/ASSUMPTIONS.md`. It must not infer authorization
for credentials, paid resources, arbitrary remote hosts, public services, large
downloads, physical communication, destructive Git operations, or weakened safety
guards.

Negative and inconclusive results are first-class outputs. A failed gate removes or
demotes a component; it does not trigger open-ended tuning.

## 4. Execution architecture

### 4.1 Orchestrator

The primary agent owns:

- the canonical run manifest and dependency graph;
- shared safety and schema bootstrap;
- preregistration review;
- assignment of one bounded domain to each worker;
- merge or cherry-pick decisions at promotion checkpoints;
- integrated verification and final architecture synthesis;
- status and blocker classification.

The orchestrator does not run two latency-sensitive performance jobs concurrently
on the M2 Max.

### 4.2 Isolated lanes

Stage 0 is serial and completes P0-P3: executable safety defaults, the root package
and test harness, the complete registry-wide metadata/license/path audit, and the
source compatibility report. No evidence-bearing experiment may use external source
before this audit. P0-P10 retain their canonical checkpoint and sign-off order.
Independent later-wave implementation may be prepared concurrently after P3, but
promotion and dependency consumption follow both that P-order and the Section 30
dependency graph.

After P3, work is divided into four lanes, scheduled in waves when agent slots are
limited:

1. Control lane: Experiment 01, then 02, then 03.
2. World-state lane: Experiment 04, then 05 after the 04 interface freezes.
3. Prediction/contact lane: Experiment 06 establishes the shared planar-pushing
   task. Local Experiment 07 Phase A then runs as an independent Q7 claim search
   regardless of whether Experiment 06 grants world-model authority. Only
   Experiment 07 Phase B depends on the official Experiment 08 baseline, explicit
   remote capacity, and a recorded budget.
4. Platform lane: post-P3 source compatibility maintenance and Experiment 08 Phase
   0 source/mapping audit. Experiment 08 Phase 1 may run once explicit remote
   capacity and budget exist. Phases 2-3 and U1-U6 consume frozen outputs from
   Experiments 01-07; final hierarchy-transfer evaluation follows Experiment 09.
   U5 and U6 run only if Experiments 07 and 06 respectively passed their gates.

Experiment 09 starts only after the required contracts from 02-05 are frozen.
Experiments 06 and 07 enter integration only if their own gates pass. Experiment 10
remains outside the autonomous core until every prerequisite in the canonical
program exists, including explicit real-data authorization.

### 4.3 Ownership and shared state

Each worker owns one experiment directory or one bootstrap subsystem. Workers must
not edit the same files concurrently. Shared contract changes are proposals until
the orchestrator promotes the smallest measured interface plus compatibility tests.

Experiment-specific environments, thresholds, plots, and policies stay local.
Only validated schemas and runtime invariants enter `reflect/`.

## 5. Experiment lifecycle

Every empirical track moves through these states:

1. `DRAFT`: claim and evaluator are incomplete; no measurement claim is allowed.
2. `PILOT`: implementation and protocol may change; output is labelled exploratory.
3. `FROZEN`: metric definitions, seeds, splits, budgets, exclusions, and decision
   rules are hashed and immutable for the confirmation run.
4. `CONFIRMATION`: untouched evaluation data and seeds are executed without tuning.
5. `DECISION`: result is `SUPPORTED`, `NOT_SUPPORTED`, or `INCONCLUSIVE`, with
   saved evidence and the predeclared gate applied mechanically.
6. `PROMOTED` or `STOPPED`: the smallest justified interface advances, or the
   component is simplified, demoted, or removed.

No pilot may be marked `SUPPORTED`. If a confirmation defect requires changing the
protocol, the run returns to `DRAFT`, receives a new protocol revision, and uses a
new untouched confirmation manifest.

## 6. Preregistration contract

Before an evidence-bearing comparison, each experiment must freeze:

- one primary estimand, or the complete canonical co-primary set with an explicit
  joint decision and multiplicity rule; no canonical primary metric may be silently
  demoted. Experiment 06 retains both rank correlation and held-out selection
  regret, with its hard gate determined by regret and latency;
- direction of improvement and a minimum effect or noninferiority margin;
- the primary contrast, analysis unit, and anchor baseline;
- paired scene/evaluation seeds and episode count;
- train, tuning, validation, and untouched confirmation partitions where relevant;
- confidence interval or bootstrap procedure;
- treatment of timeouts, crashes, missing data, and exclusions;
- maximum tuning attempts and compute budget;
- latency, jerk, action-age, timeout, retry, and safety budgets when applicable;
- exact advance, kill, and inconclusive rules;
- negative controls and anchor baselines;
- artifact and configuration hashes.

Every pilot and confirmation also freezes an evidence-fidelity contract. Results are
invalid unless the retained evidence contains all of the following:

- immutable raw per-trial rows/events before aggregation, with schema version,
  experiment/protocol revision, condition and variant identity, scene/episode/anchor/
  candidate identity, seed and RNG namespace, timestamps or ordered tick indices,
  units, coordinate frames, validity/missingness flags, terminal state, and the exact
  configuration, code, dependency, input, and output hashes needed for replay;
- an append-only disposition record for every scheduled trial, including successful,
  failed, timed-out, crashed, excluded, and declared-missing cases; exclusions never
  delete or overwrite the raw case and carry a frozen reason code plus analysis
  inclusion flags;
- a deterministic annotated sample index containing at least one working and one
  nonworking case per evaluated condition whenever each class exists, selected by a
  preregistered rule rather than visual appeal, with labels, source row/event ranges,
  relevant command output, and links to the immutable raw artifacts;
- plot-ready tables that preserve the analysis unit and pairing keys, together with a
  closed visualization recipe recording source artifact hashes, filters, transforms,
  grouping, ordering, axes, units, coordinate conventions, binning/smoothing, summary
  statistics, interval construction, palette/legend labels, image/raster dimensions,
  and deterministic renderer/version/seed; and
- a reconstruction check which regenerates every reported table, graph, raster, or
  image from raw artifacts in a clean output directory and compares canonical table
  bytes or declared numeric/pixel tolerances. Presentation files are derived views,
  never the sole evidence.

If a working or nonworking class does not occur, the sample index records
`CLASS_NOT_OBSERVED` with the exact eligible denominator; it must not synthesize or
hand-pick a substitute. Raw evidence remains bounded by the experiment's declared
artifact budget through lossless typed/tabular/event encodings and content-addressed
deduplication, never by dropping failed cases or reconstruction fields.

Pilots choose task-specific numeric values using variance and feasibility evidence.
Those values must freeze before confirmation. The default analysis unit is the
scene/episode seed and the default contrast is the paired per-seed difference
against the preregistered anchor. Unless the protocol justifies another method, the
orchestrator computes a deterministic 10,000-resample paired percentile-bootstrap
interval. Advance requires the full 95% interval to clear the frozen minimum effect
in the beneficial direction; noninferiority requires the full interval to remain
inside the frozen margin. A canonical co-primary set uses a frozen joint rule and
Bonferroni-adjusted intervals; secondary contrasts are descriptive unless their own
multiplicity family was frozen. Confirmation reports effect sizes and intervals and
does not rely on a binary significance test alone.

Confirmation seeds and generated scenarios do not exist during implementation.
After the implementation commit and protocol hash freeze, the orchestrator generates
them from a new recorded RNG seed, runs confirmation without allowing code or
configuration changes, then publishes the manifest with the results. Any post-freeze
change invalidates that confirmation and requires a new revision and unseen manifest.

To reduce confounding:

- Experiment 01 is reported as a stack-level comparison unless a
  representation-by-controller factorial comparison is actually run.
- Experiment 04 includes a flat full-history, equal-information baseline.
- Experiment 05 includes a monolithic same-facts twin baseline.
- Experiment 06 separates training targets, model selection, and final downstream
  utility, and includes strong low-capacity predictors.
- Experiment 09 includes drop-one ablations around the selected system and a held-
  out compound mission.
- Injection identity, oracle cause labels, and future outcomes are hidden from
  evaluated decision components. Each canonical variant still receives its declared
  observation set: Experiment 03 monitors receive preregistered observable signature
  inputs; W4 uses privileged state; and Experiment 07 begins with privileged training
  observations. Other privileged state is restricted to scoring or an explicitly
  labelled oracle ablation.

## 7. Reproducibility and resource policy

Bootstrap pins the already installed CPython 3.11.13 in `.python-version`, declares
`requires-python = ">=3.11,<3.12"`, creates a project `.venv`, and generates
`uv.lock` with the installed `uv` tool. Project commands set
`UV_CACHE_DIR=.cache/uv`; `.venv/` and `.cache/` are ignored. The bootstrap smoke
test imports MuJoCo from the locked environment before any MuJoCo experiment is
eligible. The environment, simulator, source revisions, evaluation seed manifests,
and schemas are locked before confirmation.

Default autonomous ceilings, unless a narrower experiment protocol applies, are:

- no single local command may run for more than 60 minutes without a bounded,
  resumable checkpoint mechanism;
- at most three tuning configurations per variant after the initial pilot;
- at most three retries/replans per episode unless the frozen protocol is stricter;
- model or reference downloads remain below 2 GB each and 5 GB total per pass;
- generated local artifacts remain below 10 GB per pass;
- no paid or remote compute is used without explicit configuration and a recorded
  budget;
- latency benchmarks run serially with resource-use metadata;
- all random sources use separate named streams and saved seeds.

These are fallback ceilings, not scientific thresholds. A different finite
experiment-specific budget may be justified during pilot and frozen before
confirmation. `ALLOW_LARGE_MODELS=1` may authorize a checkpoint over 2 GB only with
a recorded per-artifact and total budget. Exhausting a resource ceiling yields
`INCONCLUSIVE` or a blocker; it is never evidence for `NOT_SUPPORTED`.

The complete local core is additionally capped at 16 passes, 240 aggregate CPU
hours, 20 GB of downloads, and 50 GB of generated artifacts. Each experiment may
use at most two pilot protocol revisions, three tuning configurations per variant
per revision, 256 paired pilot episodes per variant, and 1,024 paired confirmation
episodes. A power or feasibility result that requires more is reported as
`INCONCLUSIVE` with a separately recorded follow-up proposal. New claim searches
outside Experiments 00-10 are recorded but not autonomously executed.

## 8. Data and decision flow

The bootstrap produces shared immutable schemas, a virtual monotonic clock for
tests, validation, event logging, rollout metadata, replay, and a result manifest.
Each experiment consumes those contracts and emits versioned artifacts under its
own result directory.

At a promotion checkpoint:

1. the worker submits its frozen protocol, result manifest, tests, and interface
   finding;
2. the orchestrator verifies hashes, untouched confirmation status, safety, and the
   mechanical gate decision;
3. only the minimal contract and compatibility tests are promoted;
4. downstream lanes receive the promoted version, never an undocumented local
   implementation detail.

Integration consumes validated contracts and may add explicit adapters. It may not
invent a new major component to hide an atomic failure.

## 9. Source integration

The complete registry is materialized and metadata-audited before evidence-bearing
source use. For every listed repository, resolve the current default branch and full
SHA, record license status, and verify or explicitly mark every selected path
missing. Sparse clones and import/build smoke tests are initially limited to
Experiments 01-03 and other active local tracks; the full registry is not cloned.

Network access is restricted to HTTPS endpoints derived from registry URLs and
official package indexes. Metadata resolution may use the web research channel;
runtime fetches use the audited fetch script or explicitly approved `git`/`curl`
commands. Caches live under ignored `external/.metadata/` or `.cache/` paths. Tests
use checked-in small metadata fixtures and must pass offline; unavailable network
marks live resolution explicitly blocked rather than fabricating a lock entry.

`REFERENCE_ONLY` license handling is normalized to
`PAPER_AND_CODE_REFERENCE` or `SPARSE_REFERENCE` with a no-copy restriction; it is
not introduced as an undeclared seventh reuse mode. Unknown or incompatible
licenses block copying, not independent local baselines.

One failed dependency attempt and one materially different remedy are permitted.
After that, the source is classified and the lane continues with an approved local
baseline when possible.

An approved local baseline is a project-local implementation that uses only locked,
license-compatible runtime dependencies, copies no unaudited upstream source,
passes the experiment's unit and smoke tests, and implements only the current
bounded claim.

## 10. Git and worktrees

Because `main` is unborn, the first non-destructive commit contains exactly the
supplied canonical program and this approved design. The orchestrator then creates
and works on `integration/autonomous-run`; it never autonomously merges that branch
into `main`. P0 adds the reviewed `.gitignore`, `.env.example`, and executable safety
guard before platform source is allowed to run.

Lane worktrees live under the ignored in-repository `.worktrees/` directory because
the canonical sibling paths are outside the writable sandbox. They are created only
for lanes ready to run and only after branch/path collision checks. Workers branch
from the current frozen integration checkpoint; the orchestrator integrates reviewed
atomic commits into `integration/autonomous-run`, not `main`.

Workers remain in their assigned worktrees. They do not merge, push, reset, clean,
or edit sibling worktrees. The orchestrator integrates only reviewed atomic commits.

## 11. Error handling and blockers

Every failed operation records the exact command, return code, relevant output,
environment, and one attempted alternative. Status is one of the canonical blocked
or failure labels from the research program.

Lifecycle state (`DRAFT` through `STOPPED`), scientific result (`SUPPORTED`,
`NOT_SUPPORTED`, `INCONCLUSIVE`), operational blocker, maturity/evidence label, and
hardware-validation status are separate fields. `PHYSICAL_R1_NOT_VALIDATED` is a
maturity label, never an operational blocker or scientific result.

A blocked lane does not block independent lanes. Missing credentials, unavailable
remote compute, licensing ambiguity, or Unitree source uncertainty defer only the
affected operation. A physical-communication path is rejected, not retried.

Safety violations, nonfinite actions, expired chunks, out-of-order responses,
unbounded queues, and non-loopback deployment attempts fail closed and are covered
by deterministic tests.

Remote execution is disabled unless all of the following are present:
`REFLECT_REMOTE_ENABLED=1`, an exact `REFLECT_REMOTE_HOST`, membership of that host
in `REFLECT_REMOTE_HOST_ALLOWLIST`, a `REFLECT_REMOTE_WORKDIR`, and positive finite
`REFLECT_REMOTE_GPU_HOURS_MAX`, `REFLECT_REMOTE_WALL_HOURS_MAX`,
`REFLECT_REMOTE_DOWNLOAD_GB_MAX`, and `REFLECT_REMOTE_ARTIFACT_GB_MAX` values. No
host discovery or fallback hostname is permitted, and credentials are never stored
in repository files.

## 12. Testing and review

The run uses four verification layers:

1. unit and property tests for schemas, validation, clocks, mappings, and broker
   invariants;
2. deterministic smoke runs for every command and configuration;
3. frozen atomic confirmation runs with artifact-schema and hash validation;
4. integration ablations and replay from saved events.

Independent agents may critique protocols and results, but the orchestrator verifies
their claims against files and commands. Before every completion report it checks
the diff, tests, secrets, artifact size, source attribution, and physical-deployment
guard.

## 13. Autonomous continuation and reporting

The run does not pause for routine implementation choices. A pass is one planned
serial bootstrap, parallel wave, confirmation wave, promotion checkpoint, or
integration/transfer evaluation, bounded by a maximum of 24 wall-clock hours. At
the end of each pass it writes `RUN_REPORT.md`, identifies the highest-value
justified next action, updates the run manifest, and launches the next eligible
lane within the global ceilings.

After P3 opens local execution, no autonomous pass may consist only of scaffolding,
environment checks, or baseline-metric estimation while an eligible bounded pilot can
run. Each such pass must execute at least one data-producing pilot shard or record the
exact gate/resource failure that made every eligible shard impossible. Comparative
pilots retain the canonical baseline but also include the strongest locally executable
non-baseline alternatives and decision-relevant ablations; a baseline-only result
cannot support an interface choice. Reports analyze aggregate effects and regime
shifts across task geometry, timing/delay, perturbation/failure class, and model or
representation family, preserving the paired raw evidence behind each slice. Support
code stops growing once the next pilot is safe, deterministic, resumable, and capable
of producing the frozen evidence contract; generalized reuse is deferred until an
observed second consumer justifies it.

It pauses only for authority or substrate that cannot be inferred: credentials,
paid/remote capacity, destructive action, physical communication, or an
irreducibly ambiguous safety choice. Scientific uncertainty produces another
canonical bounded experiment or an inconclusive decision, not a user question. A
noncanonical follow-up is recorded but not launched. If all local work is exhausted
and the same missing external prerequisite remains the only route forward for three
consecutive goal audits, the orchestrator records the evidence and marks the
persistent goal blocked rather than polling indefinitely.

## 14. Completion criterion

P0-P10 is a checkpoint. The persistent goal is complete only when current artifacts
and confirmation evidence disposition every required interface and world-state
choice in Section 36 of the canonical program, including an evidence-based
learned-prediction role and an explicit R1 transfer decision. A valid negative gate
may remove an arrow, store, world-model role, or specialist; the requirement is an
evidence-based disposition, not a positive result.

Completion accounting must disposition every Q1-Q10 track and Experiment 00: a
frozen decision or failed gate where runnable, or an explicit canonical prerequisite
blocker where not runnable. Experiment 10 runs if all prerequisites become available;
otherwise each missing prerequisite is recorded. All canonical decision files,
source/provenance artifacts, reports, tests, and reproducible commands are verified.

Remote-unavailable work may be labelled with strong evidence as externally blocked,
but it cannot be represented as affirmative R1 transfer evidence and cannot yield a
successful goal completion while a required R1 decision remains unevaluated. Once
all meaningful local work is complete, repeated unavailability follows the terminal
blocked rule in Section 13. Physical deployment is never required for success and
remains `PHYSICAL_R1_NOT_VALIDATED`.

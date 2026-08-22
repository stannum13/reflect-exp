# P5 Temporal Action-Chunk Execution Design

Date: 2026-08-22

Status: approved autonomous default. Execution begins only after P4's confirmation
has selected and frozen one or two action representations, task values, and source
provenance.

Canonical input: `Reflect Lite Research Program.md` Sections 10, 13, 14, 27, 29,
and 30; the approved autonomous-run design; and the P4 policy-to-controller design.

## Outcome and boundary

P5 implements Experiment 02: it compares seven ways of changing the *unexecuted*
future of a valid action chunk while the simulated arm continues to move. The bounded
claim is a latency/reactivity/smoothness trade-off under one fixed task and one
deterministic policy-output distribution. It does not establish that a VLA is
intelligent, that an RTC approximation is the real RTC algorithm, or that an
asynchronous broker is safe on hardware.

P5 consumes P4's selected representation(s), exact `ActionChunk` shape, horizon,
task configuration, controller/executor adapter, source-lock hash, and measured
success/metric definitions. It must not select a representation or substitute task
values itself. If P4 promotes no non-anchor representation, P5 uses P4's stable
joint-target anchor only and records that dependency in its frozen protocol.

P5 does not add a VLA, model checkpoint, policy server, ROS 2, CUDA, remote process,
or physical communication. Experiment-specific policy, broker, environment adapter,
thresholds, and plots remain below `experiments/02_action_chunks`; only a runtime
invariant demonstrated by confirmation evidence may later be proposed for `reflect/`.

## Alternatives and trade-offs

### A. P4 planar-arm task plus a project-local deterministic broker — selected

Reuse P4's inline three-link MuJoCo arm, 500 Hz controller, selected command adapter,
target generator, and fake-policy geometry. A local broker uses virtual event time to
schedule policy requests and arrivals; no network transport exists.

This preserves P4's meaningful control and jerk measurements while isolating the
temporal protocol as the only experimental variable. It is small enough for exhaustive
paired deterministic runs and directly answers how a valid new chunk affects queued
motion.

### B. Pure-Python point-mass queue simulator — rejected as the evidence task

A queue-only simulator is useful for broker unit tests, but it bypasses P4's selected
executor and common controller. Its action discontinuity and jerk proxies would not
be the same quantities used by the actual control task. Retain it only as a compact
test fixture for hand-calculated queue transitions.

### C. Adapt an upstream async client or RTC runtime — deferred

LeRobot and OpenPI provide valuable study seams, but adopting their runtime would add
serialization, server lifecycle, trust, dependency, and possibly flow-model behavior
to a broker experiment. It would also obscure whether a result came from replacement
semantics or upstream infrastructure. Upstream execution is therefore excluded until
the synthetic gate has passed and a separate, attributed follow-up justifies it.

## Task and data flow

Every episode runs P4's fixed moving-target arm task. The fake policy receives only
the immutable observation/skill snapshot captured on a policy request and emits an
`ActionChunk` in the selected P4 representation. It has no live target channel after
the request. The protocol broker validates the arrival, maintains only bounded
unissued future references, and yields a reference for the next 500 Hz controller
tick. The P4 executor/controller maps that reference to the common slew limiter and
PD loop.

```text
P4 target + arm state
  -> immutable Observation and SkillSpec at request time
  -> deterministic fake policy / delayed response schedule
  -> validated ActionChunk arrival
  -> protocol broker (A--G) and bounded future queue
  -> selected P4 executor -> common controller -> MuJoCo step
  -> ControlReference, events, metrics, validated rollout artifact
```

The policy function, observation request times, target trajectory, P4 limits,
controller parameters, selected representation, horizon, and response schedule are
identical for all protocols in a paired condition. Only the broker's treatment of a
new valid unexecuted future changes. A policy's deterministic strategy bit is varied
only in the designated strategy-divergence fault, where it produces two valid but
meaningfully different chunks from the same input contract.

## Canonical protocol semantics

All protocols preserve already issued actions and may only alter unissued references.
An arrival is eligible only when its `ActionChunk` is finite, dimensionally valid,
within its half-open validity interval, and sourced from an observation no older than
the last accepted observation. The fixed protocol names are the decision vocabulary.

| ID | Decision name | Semantics |
|---|---|---|
| A | `OPEN_LOOP` | Accept the first valid chunk and execute its usable horizon unchanged. It does not request a response to react to later target movement. |
| B | `RECEDING_PREFIX` | Execute exactly frozen prefix length `K`; discard all remaining unissued actions, re-observe, and request another chunk. A missing response produces safe hold rather than execution of discarded or stale future. |
| C | `TEMPORAL_ENSEMBLE` | Align valid unissued predictions by absolute control tick and compute a deterministic age-weighted average at each matching tick. Already issued values are excluded from the blend. |
| D | `LATEST_VALID` | On a valid non-stale arrival, replace every unissued queued action with the newest proposal. |
| E | `ASYNC_SAFE_PREFIX` | While a request is outstanding, continue only the accepted, still-valid prefix. After validation, a new arrival replaces the unissued future; expiry before such arrival produces safe hold. |
| F | `OVERLAP_BLEND` | Preserve the issued prefix and create a new immutable broker-generated chunk whose unissued overlap uses a frozen deterministic ramp from old queued values to the new proposal. Its metadata records parent chunks and weights. |
| G | `RTC_APPROXIMATION` | Preserve a finite committed prefix and deterministically project/condition the new unissued proposal toward that prefix before replacement. This is an explicitly labelled approximation, not RTC compatibility. |

`RTC_COMPATIBLE` is never selected or claimed by this experiment unless a separately
reviewed, P3-provenanced compatible flow policy is actually executed and the real RTC
implementation is compared. A protocol-G approximation may be compared and reported,
but its decision record remains `RTC_APPROXIMATION` and may not be rewritten as
`RTC_COMPATIBLE` because its outcome is favorable.

When F or G synthesizes a derived chunk, it receives a new chunk ID and immutable
action array. Its metadata records both source chunks, the replacement rule revision,
and any blend/conditioning values. The artifact event for a replacement identifies the
formerly accepted chunk; no unsupported `replaced_chunk_id` payload is invented.

## Virtual timing and lifecycle

`VirtualClock` is the exclusive source of simulated monotonic and wall time. No
decision sleeps, reads host wall time, or depends on process scheduling. Measured host
compute duration is recorded separately and has no effect on delivery time.

The 2 ms P4 tick uses this total ordering:

1. apply target movement(s) scheduled at the current virtual time;
2. capture every due immutable policy observation and emit `POLICY_REQUESTED`;
3. schedule its deterministic response, drop it, or schedule an explicit pause;
4. deliver due responses in `(delivery_time_ns, request_sequence)` order;
5. validate arrivals, emit `POLICY_RESPONDED`, and accept, reject, replace, blend, or
   condition only according to the selected protocol;
6. obtain the next reference from the protocol broker; if no valid reference exists,
   enter P4's deterministic safe-hold behavior and emit a safety/stall trace event;
7. execute one P4 control/simulation step and record 500 Hz metric samples; and
8. emit decimated telemetry and advance virtual time by 2 ms.

The safe-hold reference must hold the current measured joint state through the P4
controller, not execute an expired chunk. It is recorded as a distinct safety state,
not attributed to a nonexistent action chunk. A dropped request has a visible request
event but no response or action chunk. Every stored policy observation has exactly one
`OBSERVATION_RECEIVED` event; action chunks and control references continue to use the
existing validated rollout lifecycle.

## Perturbation protocol

Every protocol runs the same paired condition grid:

```text
arrival latency:       50, 150, 300, 700 ms
target movements:      one movement during an outstanding request; two such movements
fault profile:         none
                       first eligible response dropped
                       older response arrives after a newer response
                       policy pause that exhausts the accepted valid prefix
                       two valid chunks encode different strategies
                       one otherwise valid chunk contains a discontinuous target
paired seed:           identical scenario and response schedule across A--G
```

The target movement uses P4's measured target/displacement values and is scheduled to
occur during an outstanding request. The out-of-order profile delays an earlier
response until after the next eligible response; both remain individually valid so the
broker, rather than malformed input validation, must reject the stale arrival. The
pause duration is selected during pilot to require safe hold in the pause probe. The
discontinuous-target response remains finite and in bounds but exceeds the frozen
protocol discontinuity trigger, so every protocol's disposition is observable.

This is a crossed latency-by-target-count-by-fault-profile grid, not a factorial of
multiple simultaneous faults. A stationary-target no-fault negative control runs for
every protocol on a fixed subset of confirmation seeds. Its success criterion is the
P4 target-hold criterion and it must create no recovery event.

## Runtime invariants

The implementation and confirmation gate require all of the following:

1. Expired or not-yet-valid chunks are never executed.
2. A response sourced from an older observation cannot supersede a previously accepted
   newer-observation chunk.
3. Queue capacity is frozen and bounded; each discard, replacement, and overrun is
   counted and traceable.
4. Every chunk declares an explicit validity interval and has finite selected-shape
   actions.
5. Once a `ControlReference` is issued, later arrivals cannot mutate its action value,
   source chunk, or execution history.
6. Request timeout or accepted-prefix expiry triggers deterministic safe hold, never
   indefinite stale execution.
7. Event time and event sequence are non-regressing; each response maps to exactly one
   preceding policy request and stored source observation.
8. A replacement emits coherent accepted/replaced/rejected lifecycle events and every
   executed action resolves to exactly one stored valid control reference.
9. All policy transport is local scheduling only: no network message, credential,
   remote execution, or physical communication is reachable.

## Metrics and mechanical decision

The primary metric is perturbation recovery success: after the final target movement,
the P4 success error-and-dwell criterion is reacquired by the frozen recovery deadline.
Its analysis unit is the paired seed-level equal-weight average over the frozen grid.
An episode that does not recover is a zero success observation, not missing data.

Secondary metrics are recovery/completion time; action age p50/p95/p99; executor idle
fraction; replacement count; invalidated-action count; queue-overrun count; policy
request rate; timeout/safe-hold activations; P4 jerk proxy; and command discontinuity.
Safety counters include nonfinite/unclamped outputs and joint/torque/reference-limit
violations. The primary outcome determines efficacy; secondary metrics enforce the
frozen viability and smoothness budgets and explain the result.

The anchor is A. B--G form one six-contrast family against A. The confirmation
analysis uses the autonomous program's deterministic 10,000-resample paired
percentile bootstrap with Bonferroni-adjusted intervals. The protocol decision is
mechanical:

1. A candidate is efficacy-eligible only if the full adjusted interval for paired
   recovery-success improvement clears the frozen minimum worthwhile effect.
2. It is safety-eligible only if every frozen absolute safety, p95 action-age, p95
   jerk, p95 discontinuity, timeout/safe-hold, queue-overrun, and artifact-validity
   budget passes.
3. Among eligible B--G candidates, select the lowest-complexity fixed order
   `B, C, D, E, F, G`; break an exact complexity tie by the better lower confidence
   endpoint, then protocol order.
4. If no candidate is eligible, retain `OPEN_LOOP` and classify the claim
   `NOT_SUPPORTED` when precision excludes the minimum effect, otherwise
   `INCONCLUSIVE`.
5. Any invalid negative control, missing/corrupt artifact, systematic protocol-specific
   loss, nonfinite output, or invariant violation invalidates confirmation and yields
   `INCONCLUSIVE`; it is never silently excluded.

The final `ACTION_EXECUTION_DECISION.md` records the selected canonical name, the
protocol-G approximation status if applicable, all gate outcomes, and why every other
protocol was rejected or not selected. Separate decisions may be made only when P4
has actually promoted distinct deterministic-trajectory and flow-policy value domains;
otherwise one decision applies.

### Pilot-derived numeric margins

The following values are intentionally not invented in this design. Pilot variance and
feasibility evidence must select each one and place it in the frozen configuration:

- prefix length `K`, horizon queue capacity, ensemble age-weight rule, overlap-ramp
  length, and RTC-approximation committed-prefix length;
- policy request timeout and pause duration;
- minimum worthwhile paired recovery-success improvement;
- P4-derived recovery deadline for the selected representation;
- maximum p95 action age, jerk, command discontinuity, safe-hold activation rate, and
  queue-overrun rate;
- confirmation seed count and the exact generated seed manifest; and
- any selected representation-specific discontinuity trigger.

These values are not placeholders: they are measured protocol parameters with a
specified owner and lifecycle. P4's existing task geometry, controller, success
criterion, target schedule, and selected command values remain fixed inputs rather
than P5 tuning parameters.

## Lifecycle and artifacts

### Draft and pilot

Draft completes when every A--G transition, scheduler, fault profile, metrics,
artifact writer integration, and test is implemented. It makes no measurement claim.
Pilot uses a checked-in pilot RNG root with a disjoint tuning/validation partition,
does not alter protocol architecture, and permits at most two protocol revisions and
three scalar configurations per protocol revision. Pilot may tune only the explicitly
enumerated numeric margins above; it may not add policy learning, server infrastructure,
or an eighth protocol.

### Freeze and confirmation

`configs/frozen.yaml` is created only after pilot. It hashes the implementation SHA,
clean-tree status, P2/P3 provenance, P4 frozen task/representation hashes, MuJoCo
package artifact, selected protocol parameters, metric/evaluator revision, fault grid,
all margins, analysis procedure, exclusions, and pilot manifests. It also records the
canonical protocol order and G's `RTC_APPROXIMATION` label.

After the implementation commit and frozen hash exist, the orchestrator generates new
paired confirmation seeds from a recorded RNG root. No code, configuration, threshold,
or metric change is allowed. Any required change creates a new Draft revision and a
new unseen confirmation manifest. Confirmation is serial on the local M2; reports
consume validated artifacts and never rerun physics.

### File and artifact boundary

```text
experiments/02_action_chunks/
  README.md
  CLAIM.md
  EXPERIMENT.md
  RESULTS.md
  INTERFACE_FINDINGS.md
  ACTION_EXECUTION_DECISION.md
  configs/base.yaml
  configs/frozen.yaml                 # created only at Freeze
  run.py
  src/broker.py
  src/protocols.py
  src/schedule.py
  src/task_adapter.py
  src/evaluate.py
  tests/test_broker.py
  tests/test_protocols.py
  tests/test_schedule.py
  tests/test_evaluate.py
  results/pilot/
  results/confirmation/
```

Each `(phase, seed, protocol, condition)` emits one create-only `RolloutWriter`
artifact containing canonical metadata/config/metrics/events, policy observations,
stored chunks, and executed control references. Per phase, write deterministic
protocol/seed/artifact manifests, episode and seed aggregates, bootstrap output,
decision JSON, and required SVG timelines/plots. P5 does not modify shared rollout
schemas to make a protocol convenient.

## Test boundary and verification

Unit/property tests prove every A--G state transition using hand-calculated queue
fixtures, all nine runtime invariants, exact virtual-clock ordering, bounded queue
behavior, expiry, safe hold, drop, pause, stale response, strategy divergence,
discontinuous input, blend provenance, and RTC-approximation labeling. Tests also
prove repeated-run determinism, selected-shape/finite validation, action immutability,
paired scenario identity, metric calculations, bootstrap/multiplicity behavior, gate
threshold boundaries, result classification, CLI headless/dry-run/create-only output,
artifact validation, and replay.

Integration tests run one zero-latency headless episode for A--G and a minimal
representative episode for every perturbation profile. Confirmation acceptance requires
the full repository tests, P2/P3 source audit, P4 input-hash validation, frozen-config
hash validation, simulation-only guard, rollout validation/replay, secret/large-artifact
scan, and `git diff --check`.

## Dependency and source seam

P5's only runtime dependencies are the P3-approved MuJoCo package and P4's local
experiment task adapter. ACT temporal ensembling, LeRobot async/RTC modules, and
OpenPI's action-chunk broker are study-only source seams. P3 may make their selected
paths available as pinned, clean, attributed sparse references, but P5 neither imports
nor copies them. Any future adaptation requires a P3 license/source-map decision and
an adjacent attribution record tied to the locked commit. No upstream policy client,
server, checkpoint, or network transport is required for this gate.

## Parallel implementation decomposition

After P4 freezes its selected input contract, work may proceed with non-overlapping
ownership:

1. **Broker worker** owns `src/broker.py`, `src/protocols.py`, and their unit/property
   tests: bounded queue, A--G transitions, invariant enforcement, and trace records.
2. **Task/evaluation worker** owns `src/task_adapter.py`, `src/schedule.py`,
   `src/evaluate.py`, and their tests: P4 adapter, virtual scheduler, fake policy,
   perturbations, metrics, bootstrap, and mechanical gate.
3. **Experiment-artifact worker** owns `run.py`, configs, experiment documents,
   artifact manifest/report rendering, and CLI/end-to-end tests.

The integration order is broker unit tests, then scheduler/P4 adapter integration,
then artifact/confirmation validation. Workers do not change P4 files or shared
`reflect/` contracts concurrently. Latency-bearing pilot and confirmation jobs run
serially.

## Scope self-review

This design has one task, one deterministic policy-output distribution, seven canonical
protocols, and one anchored decision family. It neither grants RTC compatibility to an
approximation nor creates a policy-serving platform. All numeric values not already
owned by P4 are explicitly pilot-derived, frozen before confirmation, and bounded by a
mechanical decision rule. No unresolved implementation placeholder changes the scope.

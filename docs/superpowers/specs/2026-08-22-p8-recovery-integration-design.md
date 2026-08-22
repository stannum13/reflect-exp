# P8 Event-Triggered Recovery Integration Design

**Date:** 2026-08-22

**Status:** Autonomous design candidate; implementation is gated on completed P5 evidence and independent design review

**Scope:** Reflect Lite Experiment 03 only

## 1. Decision and claim boundary

P8 tests whether one transparent recovery hierarchy improves eventual task success or
intervention cost over no recovery, always-local, and always-semantic baselines on the
already selected synthetic manipulation stack. It does not train a classifier, judge
VLM reasoning, certify safety, add a production behavior tree, or communicate with a
physical robot.

P8 consumes, without retuning:

- P4's promoted controller/task stack;
- P5's selected execution protocol, including `OPEN_LOOP` when no more elaborate
  protocol is supported but P5 produced valid evidence;
- the P1 rollout/event contracts and the promoted P5 adapter; and
- P2/P3 source provenance for BehaviorTree.CPP and Navigation2 as study-only inputs.

P8 is prerequisite-blocked if P4 or P5 ended without one valid executable stack. The
substrate is selected mechanically: P5's `PRIMARY` stack, selected protocol, selected
vector, representation, adapter hash, and frozen latency schedule are used exactly. If
P5 is `NOT_SUPPORTED`, its final decision must name the simplest completed valid
protocol in fixed order `A..G`; that protocol becomes PRIMARY for P8. A missing or
ambiguous selection blocks P8. P5's DESCRIPTIVE stack is not run in P8.

P8 never changes P4 control gains, P5 within-generation broker reducer, request
recurrences/caps, transforms, safety limits, or normal latency distribution. Recovery
creates a new outer generation or skill attempt through the adapter below; it does not
inject an extra request into an existing P5 generation. The two named `STALE_CHUNK` and
`UNSAFE_ACTION` cases are declared exogenous input faults that alter one delivery tick
or raw payload before the unchanged reducer sees it; they do not redefine normal P5
behavior and are excluded from any claim about P5's own frozen latency distribution.

## 2. Alternatives and selected approach

### A. Trace-only recovery classifier

Replay P5 traces and classify failures without executing recovery. This is cheap but
cannot measure loops, post-decision actions, recovery latency, or eventual success.

### B. Full behavior-tree or semantic-agent integration

Add BehaviorTree.CPP, ROS 2, or an LLM planner. This introduces the exact integration
and reasoning confounds the atomic experiment is intended to avoid.

### C. Deterministic monitor and small state machine on the selected P5 stack — selected

A pure monitor derives a frozen `FailureSignature` from values already available to
the executor plus a small controlled semantic sidecar. A pure policy maps that
signature and bounded history to `RecoveryDecision`. A deterministic scenario driver
implements refresh, retrigger, semantic replan, and abort effects around the unchanged
P5 executor. This is the smallest runnable experiment that measures the hierarchy's
claim.

## 3. Ownership and architecture

All study-specific code stays under `experiments/03_recovery/`. P8 imports the public
P5 execution adapter; it neither copies nor reaches into P5 private broker state.
No P8 module is added to `reflect/` unless confirmation evidence requires a separate
interface-promotion commit. The existing `RecoveryDecision` enum is reused unchanged.

```text
frozen scenario + selected P4/P5 substrate
                 |
                 v
          ProgressMonitor  ---> immutable FailureSignature
                                     |
                                     v
                              RecoveryPolicy
                                     |
                                     v
       RecoveryRuntime applies one bounded transition
                 |
                 v
 unchanged P5 broker/executor -> P4 control -> MuJoCo -> rollout + recovery sidecar
```

The monitor, policy, transition reducer, scenario generator, scorer, and artifact
validator are separate pure units. Only the runtime adapter touches the P5/P4
simulation objects. Host wall time is measurement-only; `VirtualClock` is the sole
behavior clock.

### 3.1 P5 recovery adapter

`RecoveryExecutionAdapter` owns one active `BrokerGeneration` with
`generation_id`, `attempt_id`, selected P5 protocol/vector, generation-local tick zero,
and one fresh public P5 broker/executor instance. Within a generation, every request,
delivery, cap, transform, and lifecycle rule is byte-for-byte P5 behavior with ticks
translated by the generation start. The adapter exposes only:

```text
start_generation(observation, attempt_id, reason) -> generation_id
close_generation(generation_id, reason, at_tick) -> ClosedGeneration
tick(observation, at_tick) -> issued ControlReference | safe hold
```

`REFRESH` closes the active generation and starts a new generation in the same attempt.
`RETRIGGER` closes it and starts generation zero of a new attempt with the same
`SkillSpec`. `ESCALATE` closes it and starts generation zero of a new attempt with the
planner's replacement `SkillSpec`. For P5 `OPEN_LOOP`, every generation makes exactly
its one permitted generation-local initial request; recovery never adds a second
request to that generation.

Closing a generation invalidates every unissued sample. If an accepted active chunk is
still half-open-valid, close first emits `CHUNK_REPLACED` for that chunk with
`reason=recovery_generation_closed`. The adapter then immediately latches the measured
joint reference and installs the ordinary P5 broker safe-hold `JOINT_POSITION` chunk,
emitting `CHUNK_ACCEPTED` and subsequent `ACTION_EXECUTED` records; because the hold is
broker-generated, it emits no false `POLICY_RESPONDED`. It has P5's exact joint-PD
metadata/zero-velocity semantics and global-terminal validity. The hold covers the
close-to-new-response gap. A valid new-generation response emits
`POLICY_RESPONDED`, `CHUNK_REPLACED` for the hold while valid, then `CHUNK_ACCEPTED`.
Abort follows the same close/replace/hold lifecycle but never starts a generation.
It creates a terminal tombstone with the next generation sequence but no broker,
request, or executable policy state. The tombstone exists only to order late responses.

An already scheduled response
may still arrive, but the adapter cannot pass it into an active broker. It preserves
the raw proposal/wrapper evidence, marks its generation closed, and emits the existing
`CHUNK_REJECTED_OUT_OF_ORDER` lifecycle with `reason=recovery_generation_closed`.
Outer ordering is the lexicographic `(generation_sequence,request_sequence)`, so a
response from a closed lower generation is out of order immediately after the next
active generation or terminal tombstone is created, even before an active generation
delivers a response. Every such delivery still emits its immutable wrapper,
`POLICY_RESPONDED`, then `CHUNK_REJECTED_OUT_OF_ORDER`; a terminal tombstone never
accepts a response.
Outstanding count is bounded by the sum of the active P5 cap plus responses from at
most one just-closed generation; a second close while any old response remains forces
safe `ABORT`. No cancellation is claimed at the policy producer. A close emits no
invented shared event; its P8 decision and caused P5 rejection IDs are cross-linked in
the sidecar.

The global episode remains P5's exact 3,125 ticks / 6.25 seconds. Generation-local
schedules are clipped at the global terminal tick without moving an injection or
extending safe hold. A generation with insufficient remaining horizon follows normal
P5 hold/expiry behavior and cannot be silently relocated.

## 4. Frozen recovery contract

### 4.1 Failure signature

Every monitor evaluation produces one immutable record:

```text
signature_id
rollout_id
evaluation_sequence
observed_at_ns
validation_status
invalid_fields
failure_onset_ns | null
active_predicates
predicate_onsets_ns
goal_error
goal_error_derivative | null
target_displacement
target_exists
reachable
action_age_ns
controller_saturated
time_in_skill_ns
retry_count
recent_safety_rejections
semantic_precondition_valid
instruction_revision
active_chunk_id | null
evidence_event_ids
failure_active
```

For `validation_status=VALID`, `invalid_fields` is empty and every required numeric
field is present and finite. For `MONITOR_INPUT_INVALID`, offending numeric fields are
null, `invalid_fields` is their sorted closed field-name set, `failure_active=true`,
and the sole active predicate is `MONITOR_INPUT_INVALID`; the policy can only `ABORT`.
No invalid number crosses the artifact boundary. `goal_error_derivative` is
the backward difference over the fixed monitor window; the first window is explicitly
`null`, not zero. `active_predicates` is the sorted closed set of monitor predicates and
`predicate_onsets_ns` is an equally ordered map containing each predicate's earliest
continuously active tick; an onset cannot move forward until that predicate clears.
`failure_onset_ns` is null for the empty set and otherwise its minimum. Target
existence, reachability, semantic precondition validity, and instruction revision come
only from the scenario sidecar and are never inferred from hidden outcome truth.

The monitor evaluates every frozen period `P` regardless of whether the selected P5
protocol emits a request; this includes `OPEN_LOOP`. Safety-envelope rejection and
target/instruction changes additionally trigger an immediate evaluation at the same
tick, ordered after observation delivery and before any new action issue. Coincident
triggers coalesce into one signature.

The closed monitor-predicate set is `TARGET_MISSING | UNREACHABLE |
SEMANTIC_PRECONDITION_INVALID | INSTRUCTION_CHANGED | SAFETY_REJECTED | ACTION_STALE |
TARGET_SHIFTED | SATURATED | NO_PROGRESS | MONITOR_INPUT_INVALID`.
`failure_active` is table-independent and true exactly when at least one of these
scenario-visible conditions holds: target missing; unreachable; semantic precondition
invalid; instruction revision changed; safety rejection since the preceding monitor;
an active chunk's age fraction at or above `0.50`, or no valid future
after the generation's declared delivery deadline; nonzero target displacement above
`0.5*epsilon`; at least two consecutive saturated monitor periods; or, once three
monitor samples exist, `goal_error>epsilon` with nonpositive three-period progress. The
first two evaluations cannot assert the progress clause. All policies receive the
same value and signature bytes.

### 4.2 Decisions and effects

The closed decision set is the existing:

```text
CONTINUE  REFRESH  RETRIGGER  ESCALATE  ABORT
```

- `CONTINUE` leaves broker, skill, and semantic goal unchanged.
- `REFRESH` invalidates only unissued future actions and requests one fresh P5
  proposal under the selected protocol. Issued controls are immutable.
- `RETRIGGER` ends the current skill attempt, closes it through the outer adapter,
  increments `retry_count`, creates a new attempt ID for the
  same `SkillSpec`, and requests fresh actions. It does not alter the semantic goal.
- `ESCALATE` first calls the deterministic scenario planner from scenario-visible
  facts. With a valid replacement it ends the attempt, closes the generation, emits
  `SKILL_ESCALATED` then `SEMANTIC_REPLAN`, and publishes the new `SkillSpec`. With
  `NO_PLAN`, the recorded decision is instead one `ABORT` with
  `rule_id=ESCALATION_NO_PLAN`; it emits neither `SKILL_ESCALATED` nor
  `SEMANTIC_REPLAN`, then follows the terminal close/hold/`SKILL_FAILED` lifecycle.
- `ABORT` clears future actions, enters the existing safe hold for the remainder of
  the episode, emits `SKILL_FAILED`, and is terminal.

Every non-`CONTINUE` decision has a monotonically increasing `recovery_id`, its source
signature ID, selected decision, rule ID, confidence, attempt before/after, and all
caused shared event IDs. Confidence is the frozen rule's declared value; it is not a
probability estimate.

The metrics count a planner invocation separately as `escalation_attempt_count`.
`semantic_replan` and its intervention-cost term increment only when a replacement
`SkillSpec` is published. `ESCALATION_NO_PLAN` increments one abort and no semantic
replan, so it cannot be double charged or represented with a nonexistent replacement
skill ID.

### 4.3 Loop and precedence rules

Safety rejection or a nonfinite monitor value has highest precedence and yields
`ABORT`. An attempted second semantic replan also aborts. Instruction change, invalid
semantic precondition, missing target, and unreachable target precede staleness and
progress rules and yield `ESCALATE` while the one-replan budget remains. After two
failed retriggers, another retrigger predicate escalates if the replan budget remains
and otherwise aborts. At most one decision is applied per monitor evaluation.

The frozen budgets are two retriggers and one semantic replan per episode. A repeated
identical non-`CONTINUE` decision is suppressed until either its causal predicate
clears or the minimum decision interval of one P5 request period elapses. A third
retrigger request, a second replan request, more than three consecutive decisions
without task-error improvement, or any attempted transition from terminal state yields
`ABORT`. There are at most four recorded non-`CONTINUE` decisions total: after three
nonterminal decisions of any kind, the next eligible failure produces the fourth and
terminal `ABORT`; no later decision row is legal. These rules make an infinite loop
structurally impossible; the
measured infinite-loop rate must still be zero.

## 5. Policies and rule freeze

All five baselines receive byte-identical signatures and the same fixed budgets:

- `R0_NO_RECOVERY`: always `CONTINUE`, except safety/nonfinite/budget terminal abort.
- `R1_ALWAYS_REFRESH`: every eligible `failure_active=true` evaluation maps to
  `REFRESH` until debounce/termination applies.
- `R2_ALWAYS_RETRIGGER`: every eligible `failure_active=true` evaluation maps to
  `RETRIGGER` until retry/termination applies.
- `R3_ALWAYS_SEMANTIC`: every eligible `failure_active=true` evaluation maps to
  `ESCALATE` until replan/termination applies.
- `R4_HIERARCHY`: ordered transparent rules select among all five decisions.

R0's unavoidable safety abort is not credited as recovery. R1-R3 use the same monitor
failure predicate as R4 so they cannot receive privileged trigger timing. The policy
never sees injection ID, expected response, scenario seed, future events, or outcome.

Let `epsilon` be P4's frozen positive task-success tolerance, `P` P5's frozen request
period, `e_t=goal_error/epsilon`, and
`progress=(goal_error[t-W]-goal_error[t])/max(goal_error[t-W],epsilon)`. Action-age
fraction is action age divided by the accepted chunk's frozen validity duration; it is
null when no chunk exists, and the refresh-age rule ignores null. A generation whose
declared delivery deadline has passed with no valid future instead asserts
`ACTION_STALE`. Saturation duration is the number of consecutive monitor periods with
saturation. The three complete candidate tables are:

| table | W | minimum progress | refresh age fraction | continue displacement | retrigger displacement | saturation periods |
|---|---:|---:|---:|---:|---:|---:|
| `CONSERVATIVE` | 5 | 0.01 | 0.80 | `1.5*epsilon` | `4.0*epsilon` | 4 |
| `BALANCED` | 4 | 0.02 | 0.65 | `1.0*epsilon` | `3.0*epsilon` | 3 |
| `RESPONSIVE` | 3 | 0.03 | 0.50 | `0.5*epsilon` | `2.0*epsilon` | 2 |

If `failure_active=false`, R4 must `CONTINUE` without evaluating a table-specific rule.
If it is true, then after the absolute precedence rules in Section 4.3, R4 applies:

1. `R4_RETRIGGER_DISPLACEMENT`: displacement at or above the table's retrigger bound
   yields `RETRIGGER`.
2. `R4_RETRIGGER_STALL`: once W samples exist, `e_t>1` and progress strictly below
   the table minimum yields `RETRIGGER`.
3. `R4_RETRIGGER_SATURATION`: saturation at or above the table duration yields
   `RETRIGGER`.
4. `R4_REFRESH_MISSING_FUTURE`: active `ACTION_STALE` with no valid chunk yields
   `REFRESH`.
5. `R4_REFRESH_AGE`: a non-null action-age fraction at or above the table bound yields
   `REFRESH`.
6. `R4_REFRESH_SHIFT`: nonzero displacement above the continue bound yields `REFRESH`.
7. `R4_CONTINUE`: otherwise yield `CONTINUE`.

The first W-1 evaluations cannot trigger the stall rule. Exact equality at a retrigger,
saturation, or refresh-age threshold triggers; exact equality at the continue bound
continues. The declared confidences are 1.00 for safety/nonfinite/budget abort, 0.90 for
escalation, 0.80 for retrigger, 0.70 for refresh, and 0.60 for continue. They are output
metadata and never affect rule selection. Pilot may select one whole table but may not
tune individual rules. If no table passes all safety and loop guards, P8 stops without
confirmation.

Expected responses in the program are diagnostic hypotheses only. No scorer treats
matching an expected decision label as success. Decision-confusion tables are reported
against scenario cause solely to explain outcomes.

## 6. Scenario family and controlled injections

The selected P4/P5 manipulation task is wrapped with only the state required to express
the nine program injections. Every episode has one predeclared injection, a stationary
no-fault control, or a paired compound case. Let `t0=500` global P5 ticks, `epsilon` be
P4's frozen success tolerance, and `P` be P5's request period in ticks. Injection time
is exactly `t0`; continuous changes occupy `[t0,t0+P)`. Values are generated before any
variant runs and are byte-identical across R0-R4.

Scenario randomness uses named NumPy `PCG64` streams whose 128-bit seeds are the first
128 big-endian bits of SHA-256 over canonical JSON
`[protocol_parent_hash,phase,seed_id,scenario_id,stream_name,"exp03-scenario-v1"]`.
Direction selection considers the eight angles `k*pi/4`, rotates their order by the
`direction` stream's first integer modulo eight, and chooses the first for which both
the `4.5*epsilon` shifted target and inherited P4 safety envelope are feasible. If none
is feasible, manifest generation fails before any policy runs. Small and large shifts
use that same direction. Alternative approach/target IDs are selected from sorted
checked-in scenario candidates by the equivalent `alternative` stream index, then
sealed in the public scenario record. No rejection sampling or runner-time RNG exists.

| Cause ID | Controlled mutation | Allowed scenario effect |
|---|---|---|
| `SMALL_SHIFT` | linear target shift totaling `0.5*epsilon` over `[t0,t0+P)` | target remains reachable |
| `LARGE_SHIFT` | one-step target shift of `4.5*epsilon` at `t0` along the seeded feasible direction | target remains reachable but old execution state is invalid |
| `TARGET_REMOVED` | `target_exists=false` at `t0`; deterministic reacquisition is available | current skill has no target |
| `BLOCKER` | `reachable=false` and precondition false at `t0`; alternate approach is available | current approach is invalid |
| `STALE_CHUNK` | the first response scheduled after `t0` is delivered one tick beyond P5's hard age limit | no other world mutation |
| `STALL` | task progress is clamped from `t0` until generation or attempt changes | controls remain inside safety limits |
| `RETRIGGER_FAILURE` | generations in the first two retriggered attempts are progress-clamped | semantic reset approach is available afterward |
| `UNSAFE_ACTION` | first proposal after `t0` has one component at `nextafter(limit,+infinity)` | safety rejects it before execution |
| `INSTRUCTION_CHANGE` | instruction revision increments and goal changes at `t0` | old goal/precondition is immediately invalid |

The four compound cases are fixed: `UNSAFE_ACTION+INSTRUCTION_CHANGE` tests safety
precedence; `INSTRUCTION_CHANGE+STALE_CHUNK` tests semantic-over-refresh precedence;
`TARGET_REMOVED+STALL` tests missing-target-over-progress precedence; and
`LARGE_SHIFT+RETRIGGER_FAILURE` tests bounded escalation after failed local recovery. Their
component mutations occur at the same `t0` and coalesce into one signature.

The deterministic semantic planner receives only
`(mission_id,revision,goal_id,target_exists,reachable,semantic_precondition_valid,
instruction_revision,retry_count,replan_count,current_pose,target_pose)` from the
public signature/state. It returns exactly one of:

- `REACQUIRE_TARGET`: same mission, new target ID/pose published by the visible search
  fact; success predicate is target visible and pose error `<=epsilon`;
- `ALTERNATE_APPROACH`: same target and goal with `approach=alternate`; it restores the
  scenario-visible reachability precondition and retains P4's success predicate;
- `RESET_APPROACH`: same target with cleared attempt history and
  `approach=semantic_reset`; it is available only after two failed retriggers;
- `REPLACE_GOAL`: the new instruction's target ID/pose and incremented mission
  revision, with P4's success predicate; or
- `NO_PLAN`, which transitions immediately to `ABORT`.

Each successful planner result constructs the ordinary `SkillSpec` with P4's selected
skill type/constraints, one listed target and target pose, the predicate above, the
remaining global episode time as timeout, and the remaining retry budget. The mapping
order is instruction change, missing target, invalid/unreachable approach, two failed
retriggers, then `NO_PLAN`. It never observes injection ID, hidden success label, or
future state and never generates free text. This measures escalation mechanics, not
agent intelligence.

Pilot and confirmation each cover all nine exact single causes, the no-fault control,
and the four compound cases. Seeds vary only the already frozen P4/P5 initial state,
feasible direction, latency draw, and alternative target/approach identity; the
magnitudes and `t0` above never vary. No outcome-selected cause is added after pilot.

## 7. Pilot, freeze, and confirmation

P8 follows `DRAFT -> PILOT -> FROZEN -> CONFIRMATION -> DECISION -> PROMOTED | STOPPED`.
Blocked prerequisites, artifact validity, and scientific result remain separate.

Four tuning seeds run all three R4 tables and R0-R3 on the full pilot scenario family.
Four untouched pilot-evaluation seeds run the selected table and all baselines once.
The selection key is, in order: zero safety/invariant violations; zero infinite loops;
highest equal-cause-weight eventual success; lowest intervention cost; lowest actions
after failure onset; then `BALANCED`, `CONSERVATIVE`, `RESPONSIVE`. Pilot evaluation
cannot retune thresholds. One correction is allowed only by starting a new protocol
revision with eight new pilot seeds; at most two revisions are permitted.

Freeze records exact P2-P5 evidence hashes, implementation and schema hashes, selected
table, scenario generator/version, cause distribution, budgets, metric definitions,
margins, bootstrap algorithm, confirmation seed count, and resource maxima. It does
not record confirmation seeds or scenarios. Only after freeze does the orchestrator
generate and hash 32 unseen confirmation seeds.

Each confirmation seed contains every single cause, no-fault control, and the four
compound cases. All policies are paired on identical scenario records. A rollout that
changes the inherited P4/P5 substrate, gets a different injection, sees hidden cause
or outcome fields, or omits required recovery evidence is invalid rather than failed.

## 8. Metrics and decision rule

Per seed and cause, record:

- eventual and first-attempt success;
- recovery latency from frozen failure onset to the first causally effective decision;
- refresh, retrigger, semantic-replan, abort, and retry counts;
- unnecessary refreshes/retriggers/replans from the outcome oracle;
- missed escalations;
- actions executed after failure onset;
- total task time;
- infinite-loop and safety-invariant violations; and
- decision-by-cause confusion counts.

The nine single-cause episodes form the scientific denominator. For each policy and
seed, eventual success is the arithmetic mean of nine binary outcomes and intervention
cost is the arithmetic mean of the nine costs below; paired inference uses these
seed-level means. The no-fault episode and four compound episodes are absolute guards
and descriptive evidence, not silently given a fifteenth weight. Every confirmation
seed must contain all fourteen valid bundles for every policy. A timeout, missing
bundle, corrupt record, resource interruption, or undeclared exclusion makes the
confirmation result `INCONCLUSIVE` or the artifact `INVALID` according to provenance;
nothing is imputed and denominators never change.

The frozen intervention cost is

```text
1*refresh + 3*retrigger + 10*semantic_replan + 20*abort
+ 1*actions_after_failure_onset + 5*missed_escalation
```

Weights are fixed before pilot and are synthetic decision costs, not real-world safety
utilities. The untouched four pilot-evaluation seeds, after table selection, set one
margin per contrast and endpoint as
`ceil_to_unit(max(one_unit,0.5*paired_seed_sample_SD))`, with sample SD denominator
`n-1`. Success unit is `1/9`; cost unit is `1/9`; zero SD still yields one unit and an
unattainable margin makes confirmation `INCONCLUSIVE`. Tuning seeds never set margins.

The confirmatory union is split into two preregistered alpha branches, preserving total
two-sided family alpha 0.05:

1. **Success branch, alpha 0.025:** R4-minus-baseline eventual-success lower bounds
   must be strictly greater than their frozen superiority margins for each R1, R2, and
   R3. Three Bonferroni marginal intervals are 99.166667%.
2. **Cost fallback branch, alpha 0.025:** all three R4-minus-baseline success lower
   bounds must be at least the negative non-inferiority margins, using a 0.0125 family
   allocation and 99.583333% marginal intervals; and all three
   baseline-minus-R4 intervention-cost lower bounds must be strictly greater than their
   superiority margins, using the other 0.0125 and 99.583333% marginal intervals.

R4 passes efficacy if either complete branch passes. It must additionally have zero
safety violations and zero infinite loops; all no-fault R4 episodes must succeed with
zero non-`CONTINUE` decisions; every compound episode must obey the frozen precedence
and terminate; and inherited action-age, jerk, discontinuity, timeout, and resource
limits must pass. Exact superiority equality fails; exact non-inferiority equality
passes.

Every interval uses 10,000 deterministic paired bootstrap resamples. Sorted seed IDs
are sampled with replacement using NumPy `PCG64` seeded by the first 128 big-endian
bits of SHA-256 over canonical JSON
`[protocol_hash,branch_id,endpoint,baseline_id,"exp03-bootstrap-v1"]`. Each resample
draws exactly 32 seed indices. Sorted statistics retain duplicates and percentile
endpoint `p` is `max(0,ceil(p*10000)-1)` with no interpolation.

P8 is `SUPPORTED` only if efficacy and every guard pass. It is `NOT_SUPPORTED` only
when a guard fails on otherwise complete valid evidence, or both efficacy branches are
mechanically excluded. The success branch is excluded when at least one of its three
success upper bounds is less than or equal to that contrast's superiority margin. The
cost fallback branch is excluded when at least one success-noninferiority upper bound
is strictly below the negative margin, or at least one cost-superiority upper bound is
less than or equal to its margin. If neither branch passes and at least one branch is
not excluded by these upper-bound rules, the result is `INCONCLUSIVE`. R4 promotes only
when supported. Otherwise the retained substrate remains P5 with no P8 recovery-policy
promotion; this experiment does not outcome-select an R0-R3 policy as a substitute.

Recovery latency is descriptive. The private scorer marks a decision causally
effective when at least one predicate active in its source signature clears by the
next monitor and stays clear for two periods. The latency uses that predicate's own
onset; coincident predicates are reported separately. No effective decision, terminal
abort, and end-of-episode censoring are explicit categories and never become zero.
An unnecessary refresh/retrigger/replan is one whose deterministic private no-decision
counterfactual from the sealed predecision snapshot succeeds without a safety violation
and without that predicate remaining active. Counterfactuals are scorer-only,
one-decision-at-a-time, cannot feed a runner, and are descriptive rather than part of
the efficacy gate except through the already frozen intervention count.

## 9. Events, artifacts, replay, and resume

P8 uses existing shared events where their meanings fit:

- `SKILL_STALLED` marks monitor-detected lack of progress;
- `SKILL_RETRIGGERED` marks `RETRIGGER`;
- `SKILL_ESCALATED` and `SEMANTIC_REPLAN` mark `ESCALATE` and the new mission state;
- `SKILL_FAILED` marks terminal `ABORT`; and
- P5 chunk/action events retain their existing lifecycle meanings.

Every `SKILL_STALLED`, `SKILL_RETRIGGERED`, `SKILL_ESCALATED`, and `SKILL_FAILED`
record carries the explicit current `skill_id`. Every `SEMANTIC_REPLAN` carries this
canonical JSON object:

```text
mission_state = {
  mission_id, revision, goal_id, instruction_revision,
  planner_rule_id, previous_skill_id, replacement_skill_id
}
```

At one global tick the total order is: private truth injection; saved observation and
`OBSERVATION_RECEIVED`; `SAFETY_REJECTED`; `PROGRESS_UPDATED`; failure-signature row;
recovery-decision row; optional `SKILL_STALLED`; `CHUNK_REPLACED` for an active closing
chunk; recovery-hold `CHUNK_ACCEPTED`; `SKILL_RETRIGGERED`, `SKILL_ESCALATED`, or
`SKILL_FAILED`; `SEMANTIC_REPLAN`; new `POLICY_REQUESTED`; delivered raw wrappers and
their rejection/acceptance/replacement events ordered by outer generation then request
sequence; then `ACTION_EXECUTED`. Sequence IDs make this order strict even when
monotonic times match. An abort emits `SKILL_FAILED` after hold acceptance and never
starts a new generation.

`REFRESH` is represented by the ordinary P5 request/response/replacement lifecycle plus
a P8 recovery sidecar row; it does not invent a shared event. `CONTINUE` appears only in
the sidecar. Replay reduces shared events and the sidecar to the current attempt,
retry/replan budgets, last signature/decision, semantic goal revision, active chunk,
and terminal state without rerunning physics.

Canonical P1 replay intentionally reduces `SKILL_FAILED` to `SkillState.FAILED` and
does not infer `RecoveryDecision.ABORT`. P8 replay layers the validated decision sidecar
on that canonical result and requires `p8_terminal_state=ABORTED` plus
`recovery_decision=ABORT`; it does not silently change the shared reducer. A future
shared `ABORT` promotion, if empirically required, is a separate compatibility commit.

`failure_signatures.parquet` has exactly the Section 4.1 fields with enum/nullability,
units, and list element types fixed in the schema version. `recovery_decisions.parquet`
contains non-`CONTINUE` decisions only and has exactly `recovery_id`, `signature_id`,
`evaluation_sequence`, `observed_at_ns`, `decision`, `rule_id`, `confidence`,
`attempt_id_before`, nullable `attempt_id_after`, `retry_count_after`,
`replan_count_after`, `predecision_snapshot_sha256`, and ordered `caused_event_ids`.
IDs are unique and foreign keys resolve exactly once. Rows order by
`(observed_at_ns,evaluation_sequence)`; recovery IDs are gap-free; and every recovery
ID maps one-to-one to exactly one snapshot index/hash and vice versa. `CONTINUE` has no
decision-table row; every signature, including `CONTINUE`, is represented in
`replay.json` through its terminal reducer hash.

`scenario_public.json` contains exactly `schema_version`, opaque `scenario_slot`,
`seed_id`, protocol/substrate hashes, `t0`, `epsilon`, `P`, initial public state,
ordered public mutation records, public alternative target/approach records, and its
content hash. It contains no cause ID, expected response, outcome, oracle label, or
private RNG state. Scenario slots are `S00..S13` after a per-seed hash-derived
permutation; a runner cannot infer cause from a filename/key. The policy callback is a
pure function in a module that receives only the immutable signature and frozen table,
never the scenario object or loader. `replay.json` contains exactly schema/input hashes,
ordered signature/recovery/shared-event IDs, current generation/attempt/mission/skill,
retry/replan counts, active chunk, canonical P1 replay hash, P8 terminal state/decision,
and final reducer hash.

Each create-only bundle contains the canonical rollout plus:

```text
p8/failure_signatures.parquet
p8/recovery_decisions.parquet
p8/predecision_snapshots.npz
p8/scenario_public.json
p8/replay.json
artifact-manifest.json
```

Before each of the at most four non-`CONTINUE` transitions, the runner copies one
immutable snapshot containing global tick/clock, MuJoCo `qpos/qvel/act`, P4 controller
state, active/hold chunk bytes, issued-reference prefix hash, active and tombstone
generation records, pending raw proposal payloads/delivery ticks, monitor history,
attempt/retry/replan/decision counts, mission/skill state, public scenario state, and
every named RNG bit-generator state. `predecision_snapshots.npz` stores those arrays and
canonical JSON byte records in recovery-ID order with fixed uncompressed ZIP member
order/timestamps and a per-snapshot SHA-256. It contains no hidden cause/outcome field.
Round-trip restoration must reproduce the next no-decision tick byte-for-byte. Every
decision row references exactly one snapshot hash; the score writer refuses a missing,
extra, or non-round-tripping snapshot.

The private score-bundle key is the runner key prefixed by `exp03-score:` and contains
exactly `outcome.json`, `decision_effects.parquet`, `counterfactuals.parquet`,
`score-metrics.json`, `runner-input-manifest.json`, and `score-manifest.json`.
`outcome.json` has scenario/seed/policy/table IDs, first-attempt/eventual success,
terminal reason, task time, and all fixed-denominator flags. `decision_effects.parquet`
has one row per decision with signature/predicate onset IDs, decision, effective flag,
clear/stable times, latency category/value, unnecessary flag, and counterfactual ID.
`counterfactuals.parquet` has at most four rows with source snapshot/decision hashes,
no-decision terminal outcome, safety result, and trace digest; it contains no full
rollout. `score-metrics.json` contains the exact Section 8 counts and cost arithmetic.
The input manifest binds one runner bundle and one private truth/scenario descriptor.

No private truth root or truth manifest exists while any runner for that phase can
execute. After every runner bundle for the phase seals and runner processes terminate,
the orchestrator deterministically materializes the private truth manifest from the
already sealed protocol/scenario records, then starts scorers. A scorer receives
read-only descriptors for one runner and one private truth record. `ScoreBundleWriter`
validates the runner, runs bounded counterfactuals,
validates exact schemas/foreign keys/denominators, and publishes the score. Runner
artifacts never contain hidden cause labels, causal-effect labels, unnecessary-decision
judgments, or counterfactual outcomes. Publication uses same-parent private temporary
directories, fsync,
manifest-last atomic rename, exact file-set hashes, and validate-and-skip resume. A
partial, conflicting, symlinked, oversized, or hash-mismatched destination fails and
is never repaired in place.

The final create-only aggregate contains `RECOVERY_POLICY.md`, `decision.json`,
`metrics.parquet`, `confusion.parquet`, the exact input-bundle manifest, and its own
manifest. `RECOVERY_POLICY.md` includes the required empirical rows
`observed signature -> selected recovery level -> declared confidence -> outcome`,
with signature IDs and decision/outcome bundle links; the frozen R4 rules/table; all
R0-R4 aggregate metrics; interval/margin tables; guard results; result and promotion
state; limitations; and exact replay/reproduction commands. It is generated from
sealed artifacts, never hand-edited evidence.

The evidence command runs one exact `(phase,policy,table,seed,scenario)` shard. Baseline
table is literal `NONE`; R4 table must match the phase protocol. The launcher requires
the symlink-resolved project-root cwd, project-relative paths, `--headless`, exact
protocol/seed/substrate hashes, and disabled network/remote/physical environments:

```text
uv run python experiments/03_recovery/run.py \
  --protocol experiments/03_recovery/configs/frozen.yaml \
  --bundle-key exp03:r1:confirmation:R4:BALANCED:00000017:S03 \
  --seed-manifest experiments/03_recovery/manifests/confirmation.json \
  --substrate-manifest experiments/03_recovery/manifests/p4-p5-substrate.json \
  --output-root results/03_recovery/runs --headless

uv run python experiments/03_recovery/score.py \
  --protocol experiments/03_recovery/configs/frozen.yaml \
  --runner-key exp03:r1:confirmation:R4:BALANCED:00000017:S03 \
  --runner-root results/03_recovery/runs \
  --truth-manifest .private/03_recovery/manifests/confirmation-truth.json \
  --bundle-key exp03-score:r1:confirmation:R4:BALANCED:00000017:S03 \
  --output-root results/03_recovery/scores --headless

uv run python experiments/03_recovery/aggregate.py \
  --protocol experiments/03_recovery/configs/frozen.yaml \
  --input-root results/03_recovery/runs \
  --score-root results/03_recovery/scores \
  --bundle-key exp03:r1:final-decision:all \
  --output-root results/03_recovery/aggregates --headless \
  --max-input-bundles 2240 --max-score-bundles 2240
```

Pilot uses the same run/score commands with checked-in `pilot-r1.yaml`, phase
`pilot-tuning` or `pilot-evaluation`, and corresponding private/public manifests.
`aggregate.py` uses key `exp03:r1:pilot-selection:all` with exactly 392 runner and score
bundles, then `exp03:r1:pilot-margins:all` with exactly 280 of each. Revision two, if
permitted, substitutes `r2`; no aggregate mixes revisions. Confirmation scoring creates
exactly 2,240 runner/score pairs before the final command above. An evidence run has no
partial-episode limit. A separate `--smoke` command writes only below a temporary
non-evidence root and cannot be scored or aggregated. Destinations derive from every
key component; wrong counts, phase/table mismatch, an unknown scenario, absolute/parent
path, dirty implementation, or an undeclared input fails before execution.

## 10. Resource bounds and anti-scaffolding rule

One scenario is one rollout capped at 6.25 seconds of virtual time, 60 seconds wall time,
and 2 MiB including P8 sidecars. The closed family has fourteen scenarios per seed:
nine single causes, one no-fault control, and four compound cases. One pilot revision
therefore retains `4 * 14 * (3 R4 tables + 4 baselines) = 392` tuning rollouts plus
`4 * 14 * (selected R4 + 4 baselines) = 280` evaluation rollouts. Two permitted
revisions retain at most 1,344 pilot rollouts. Confirmation retains
`32 * 14 * 5 = 2,240` rollouts, for 3,584 total runner bundles and 7,168 MiB.

Each private scorer bundle is capped at 512 KiB, adding 1,792 MiB. It may run at most
four scorer-only counterfactual continuations, retains no counterfactual rollout, and
has its own 60-second wall ceiling. Frozen protocols,
seed/scenario manifests, aggregate reports, and sibling temporaries share a 512 MiB
allowance: at most five pilot/final aggregate bundles are 32 MiB each, all frozen
protocols/manifests share 32 MiB, and one bounded writer-scratch area is 320 MiB.
Every aggregate also has a 60-minute wall ceiling. The complete retained maximum is
therefore 9,472 MiB, below the inherited
10 GiB limit. Preflight counts current retained bytes plus the complete declared next
phase and requires both budget and free-disk headroom. Temporary siblings must be
absent before a new phase. Every one-scenario shard remains below 60 minutes.

Implementation stops at the first valid decision. P8 adds no generic behavior-tree
framework, plugin system, network service, database, UI, ROS/C++ binding, learned
classifier, new simulator, or generalized semantic planner. Source inspections produce
notes and attribution only; no upstream code is copied. Any proposed shared abstraction
must be justified by confirmation evidence and delivered as a separate compatibility-
tested promotion commit.

## 11. Verification design

Tests cover:

- exact signature units, null first derivative, onset persistence, immediate/cadenced
  trigger coalescing, and hidden-field exclusion;
- every decision transition, event order, issued-action immutability, P5 reset/refresh
  seams, safe hold, and terminal behavior;
- precedence, debounce, retry/replan caps, and structural loop termination;
- byte-identical paired scenarios and no policy access to cause/outcome labels;
- all nine single injections, no-fault controls, and compound precedence cases;
- R0-R4 trigger equality, fixed table selection, no pilot-evaluation retuning, and
  post-freeze confirmation generation;
- metric denominators, intervention-cost arithmetic, causal-effect scorer isolation,
  paired bootstrap, multiplicity, boundary equality, and result-state distinctions;
- canonical rollout compatibility, shared-event meanings, P8 replay, exact sidecar
  schemas, corruption/extra-file rejection, atomic create-only publication, and resume;
- inherited P2-P5 hashes, safety/remote/physical guards, wall/byte/disk ceilings, secret
  scan, full tests, artifact audit, and `git diff --check`.

## 12. Required decisions

The implementation plan may begin only after an independent review closes all critical
or important design findings and P5 publishes a valid selected substrate. It may not
change the scientific rules, thresholds-table count, scenario family, decision
semantics, resource maxima, or evidence boundary.

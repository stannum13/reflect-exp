# P5 Temporal Action-Chunk Execution Design

Date: 2026-08-22

Status: approved autonomous default. P5 execution requires complete P3 provenance and
completed P4 confirmation.

## Outcome and hard P4 eligibility

P5 implements Experiment 02: seven protocols decide how a valid new prediction changes
only unexecuted future actions on P4's simulated arm. It measures a bounded
latency/reactivity/smoothness trade-off, not VLA intelligence, hardware async safety,
or RTC equivalence.

P5 may execute only if P4's published promotion decision contains exact stack ID P2 or
P4. Those are the only current P4 stack IDs with multi-knot trajectories; P1, P3, P5,
and P6 are one-knot and are ineligible. P5 frozen input records every promoted P4 stack
ID and representation and marks exactly one row PRIMARY: the first promoted eligible
ID in P4's deterministic promotion order. A promoted second eligible ID is
DESCRIPTIVE only. If P2/P4 is absent, P5 is prerequisite-blocked; it does not turn a
one-knot stack into a trajectory or issue a protocol decision.

All P5 horizon math is in P4's 2 ms executable ticks, not policy knots. Let D=0.002 s,
P be the selected P4 policy period, Q=P/D (an integer), H be its P4 knot count, and
E=ceil(2.5*P/D). The P4 interpolator makes at most
N_knot=(H-1)*Q+1 tick values and the half-open expiry permits E ticks from delivery.
P5 usable ticks are N=min(N_knot,E), with U=N-1 future ticks after the first issue.
Eligibility requires U>=K+1, where K is P5's frozen prefix length. For the two-move
condition, it requires U>=K+2. The frozen eligibility record includes stack ID,
representation, H, P, Q, E, N_knot, N, U, K, expiry, and a proof of both inequalities.

The response-delivery tick is n0. The one-move A perturbation is n0+K+1; the two-move
A perturbations are n0+K+1 and n0+K+2. The eligibility record additionally proves
each is strictly below n0+N and n0+E, and that final movement plus P4's 2.0 s recovery
window is at or before the 6.25 s episode end. If any proof fails, that stack is
ineligible; P5 never relocates an A perturbation. P5 reuses P4 arm/controller/scenario
generation but uses these acceptance-relative Experiment-02 target times.

## Alternatives and boundary

1. **P4 task plus project-local virtual-time broker — selected.** It preserves P4's
   500 Hz controller and its tracking/jerk measures while isolating queue semantics.
2. **Pure-Python point-mass queue fixture — tests only.** It supports hand-calculated
   transitions but is not evidence-bearing controller evaluation.
3. **LeRobot/OpenPI runtime adaptation — deferred.** Server, serialization, trust, and
   potential flow-model behavior would confound the synthetic broker gate.

P5 adds no VLA, checkpoint, server, ROS, CUDA, remote transport, physical connection,
or shared reflect schema change. It consumes the selected P4 task bytes, executor,
shape, controller, success criterion, and provenance hashes unchanged.

## Data flow, timing, and immutable issued references

~~~
P4 arm + target -> request Observation/SkillSpec -> raw proposal schedule
-> broker disposition -> executable ActionChunk -> P4 executor/controller
-> MuJoCo -> ControlReferences, events, metrics, rollout and proposal sidecar
~~~

VirtualClock is the only behavior-time source. At each 2 ms tick: apply scheduled
target movement; fire due protocol request trigger and store one observation; schedule,
drop, or pause the raw proposal; deliver proposals ordered by
(delivery_tick,request_sequence); apply broker transition; execute P4; store telemetry;
advance one tick. Host time is measurement only.

Every request has a fresh unique stored observation ID. An issued reference is indexed
by absolute tick. On first issue it is copied to a C-contiguous read-only array and
stored in append-only issued[tick] and its ControlReference. Later arrivals can never
mutate issued values; tests compare their byte hashes after every later delivery.

## Protocol state machines and exact transforms

P is the selected policy period, K is a positive frozen prefix satisfying K+1<=U, and
I is the frozen periodic in-flight cap. A requests initial ordinal 0 only. B requests
ordinal j+1 exactly after K ticks issued from accepted ordinal j, discards the remaining
unissued suffix, and allows one outstanding request. C, D, F, and G request ordinal j
at periodic ticks jQ while fewer than I requests are outstanding. E requests once when
the active executable chunk has exactly K unissued ticks and allows one outstanding
prefetch. No trigger can reuse an observation ID.

| ID | Name | accepted-arrival transition |
|---|---|---|
| A OPEN_LOOP | accept raw executable chunk; no later request |
| B RECEDING_PREFIX | accept raw executable chunk after discarded suffix; hold while absent |
| C TEMPORAL_ENSEMBLE | recompute unissued absolute ticks into derived executable chunk |
| D LATEST_VALID | replace all unissued ticks with newest raw executable chunk |
| E ASYNC_SAFE_PREFIX | continue valid prefix pending prefetch, then replace unissued ticks |
| F OVERLAP_BLEND | derive old/new overlap then replace unissued ticks |
| G RTC_APPROXIMATION | derive committed-prefix-conditioned future then replace unissued ticks |

For C, V(t) contains delivered valid raw proposals covering absolute tick t, action
a_i(t), and delivery d_i:

~~~
w_i=exp(-lambda*(now_ns-d_i)/1e9)
a_C(t)=sum(i in V(t),w_i*a_i(t))/sum(i in V(t),w_i)
~~~

For F, over j=0..M-1 overlap ticks with old o_j and new r_j:

~~~
beta_j=(j+1)/(M+1)
a_F(j)=(1-beta_j)*o_j+beta_j*r_j
~~~

After M, F uses r_j. For G, over j=0..L-1 committed ticks with old c_j and new r_j:

~~~
gamma_j=(L-j)/L
a_G(j)=gamma_j*c_j+(1-gamma_j)*r_j
~~~

After L, G uses r_j. P4's unchanged executor limits/slew run after these transforms.
G is always RTC_APPROXIMATION. RTC_COMPATIBLE is forbidden unless a separately
P3-provenanced compatible flow policy and its real RTC implementation are executed.

## Raw, wrapper, derived, and hold lifecycles

Every raw proposal has a create-only JSONL sidecar record outside the rollout directory:
results/<phase>/proposals/<rollout_id>.jsonl. The phase artifact manifest hashes it.
Exact fields are:

~~~
proposal_id, rollout_id, request_observation_id, request_observation_time_ns,
request_sequence, delivery_tick, representation, dt_s, actions_shape, raw_actions,
actions_sha256, disposition, lifecycle_chunk_id, derived_chunk_id, parent_hashes
~~~

Successful direct A/B/D/E raw proposals become executable chunks. Successful C/F/G raws
remain sidecar records and map to a derived executable chunk. A derived chunk uses the
newest contributing raw proposal's observation ID/time; sorted parent hashes, rule
revision, and formula scalars are metadata. C owner is newest delivery contributing to
its first executable tick; F/G owner is the arriving raw proposal.

Every *delivered rejected* raw proposal also creates and stores a lifecycle-addressable
immutable wrapper ActionChunk, with the raw action payload/shape, source observation,
validity interval, and metadata.origin=raw_rejected. POLICY_RESPONDED references this
wrapper, followed by CHUNK_REJECTED_EXPIRED or CHUNK_REJECTED_OUT_OF_ORDER. Thus every
response event resolves to stored action data and every rejection is canonical. A
dropped or paused request has no delivery/wrapper and is a sidecar record plus its
POLICY_REQUESTED metadata.

For valid replacement, emit POLICY_RESPONDED for the new direct/derived executable;
emit CHUNK_REPLACED only if the old active executable is currently in its half-open
validity interval; then emit CHUNK_ACCEPTED for the new executable. If old is expired,
clear it and directly accept the new chunk: no replacement event. Expiry emits no
additional event.

Safe hold is a broker-generated supported-representation ActionChunk. When no valid
future exists, capture/store current observation, construct a finite P4-adapter hold
horizon, set metadata.origin=broker_safe_hold, then directly accept it if active is
absent/expired or replace the still-valid active chunk before accepting it. Hold has
ordinary accepted/executed/validity-end lifecycle. A later valid response replaces hold
only while hold is valid; otherwise clear then accept it. Safe hold is therefore never
an untracked controller side effect.

## Core comparison and executable fault probes

The primary comparison contains only eight paired no-fault core cells:
latency {50,150,300,700} ms x target count {one,two}. Every protocol runs the same
eight scenario/latency cells per seed; recovery success is calculated only from them.
Fault probes are separate safety gates and descriptive diagnostics, never pooled into
the primary recovery estimand.

Fault cells use 300 ms nominal latency and one target movement. For periodic protocols,
r1 is the first periodic request after initial acceptance and r2=r1+Q. The target moves
at r1+1 tick. For B, r1 is its first post-prefix request; for E, r1 is its first
prefetch request; for A, r0 is initial request and no t0-dependent target is scheduled
when r0 is dropped or paused. Exact executable cells are:

| protocol | drop | old-after-newer | pause | strategies | discontinuity |
|---|---|---|---|---|---|
| A | drop r0; no response; hold at start; denominator safety-only | N/A, one request | pause r0; hold at start; safety-only | N/A, no replacement | raw r0 discontinuous; accept/account |
| B | drop r1 after K issued; suffix absent; hold | N/A, one in flight | pause r1 after K; hold | r1 alternative strategy replaces post-prefix future | r1 discontinuous; accept/account |
| C | drop r1; continue ensemble then hold if exhausted | r1 delayed to r2+1, r2 arrives first; reject r1 wrapper | pause r1; continue then hold | r1/r2 alternatives ensemble | r1 discontinuous; ensemble/account |
| D | drop r1; current valid future then hold | r1 delayed to r2+1; reject r1 wrapper | pause r1; continue then hold | r1 replaces unissued future | r1 discontinuous; replace/account |
| E | drop r1 at K remaining; continue K then hold | N/A, one prefetch | pause r1 at K; continue K then hold | r1 replaces prefetched future | r1 discontinuous; replace/account |
| F | drop r1; current valid future then hold | r1 delayed to r2+1; reject r1 wrapper | pause r1; continue then hold | r1/r2 blend alternatives | r1 discontinuous; blend/account |
| G | drop r1; current valid future then hold | r1 delayed to r2+1; reject r1 wrapper | pause r1; continue then hold | r1/r2 conditioned alternatives | r1 discontinuous; condition/account |

Every non-N/A row names the request ordinal, queue precondition, transition, event
form, and continue/hold behavior. An N/A cell is excluded from that protocol's probe
denominator, never imputed. The target movement for B--G occurs at r1+1 only after r1
is scheduled; for A no-fault core target times are the eligibility-proved acceptance
relative ticks above. The table yields A=11, B=12, C=13, D=13, E=12, F=13, G=13
total cells per seed when core and applicable probes are combined. A stationary no-fault
negative control is a separate descriptive cell for the first four confirmation seeds.

## Invariants

The broker must prove: no expired/not-yet-valid execution; no older-observation
supersession; finite selected shape; bounded queue and in-flight state; immutable issued
ticks; safe hold instead of stale future; non-regressing events; one request per
observation; response-addressable action lifecycle; and no network/remote/physical path.
Tests include direct, derived, rejected-wrapper, expired-active, and hold transitions.

## Pilot, freeze, confirmation, resources, and resume

Pilot has four tuning seeds and four one-shot validation seeds. For a 13-cell protocol,
three ordered candidate vectors over four tuning seeds consume 156 rollouts; the chosen
vector over four validation seeds consumes 52: maximum 208 per protocol. Across A--G,
the exact maximum is 1,392 rollouts: three tuning vectors times four seeds times 87
cells plus one validation vector times four seeds times 87 cells. Candidate vectors are
ordered lexicographically by (K,I,lambda,M,L,timeout) after invalid horizon values are
removed. Choose highest tuning mean primary-core recovery success among zero-invariant
candidates; ties choose lexicographically first. If none are feasible, STOP the stack;
there is no fallback tuning choice.

Finite scalar candidates are K in {1,2,4} with K+1<=U; I in {1,2,4}; lambda in
{0,1,4}/s; M in {1,2,4} with M<=U; L in {1,2,4} with L<=U; timeout in {1.0,1.5,2.0}P.
A revision changes one scalar group only; at most two revisions and three vectors per
protocol/revision are allowed.

Freeze hashes P2-P4 inputs, stack-ID eligibility proof, selected vector, cell table,
metrics/margins, and bootstrap method. It freezes only the confirmation RNG algorithm,
candidate-seed procedure, and target count 32. After freeze it generates the immutable
32-scenario seed manifest before any P5 stack runs.

Confirmation has 256 primary core rollouts per protocol (32*8), at most 20 applicable
fault-probe rollouts (five probes over four seeds), and four negative controls: maximum
280 per protocol. Across all seven protocol diagnostic runs the maximum is 1,944
rollouts: 1,792 core + 124 applicable probes + 28 controls. One primary plus one
descriptive stack has at most 560 rollouts. Each rollout is 6.25 simulated seconds and
at most 1 MiB serialized; all-seven maximum is 12,150 simulated seconds and 1,944 MiB,
plus 128 MiB aggregate/plot allowance, below 10 GiB. A shard is one
(phase,stack,vector-or-protocol,seed) tuple: pilot maximum 13 episodes/81.25 simulated
seconds; confirmation maximum 14 episodes/87.5 simulated seconds. Each serial command
has a 60-minute wall ceiling and refuses to start unless declared artifact budget remains.

Evidence-bearing run.py requires --phase, --frozen-config, --seed-manifest,
--stack-id, --protocol, --shard-index, --shard-count, --output-dir, and --headless;
--dry-run prints the exact identity. The identity hash covers phase, frozen-config hash,
P2-P4 hashes, seed-manifest hash, stack ID, protocol, vector, seed, cell, and artifact
schema revision. Resume validates that identity plus rollout, sidecar, and manifest
hashes then skips exactly matching create-only outputs; any partial/conflicting output
fails. --max-episodes is smoke-only unless it equals the shard manifest count.

## Decision, multiplicity, and equality

The primary estimand is paired seed-level candidate-minus-A recovery-success difference,
equal-weighted over the eight core cells only. Higher is beneficial. Six B--G contrasts
for the one primary stack form one family and use deterministic 10,000-resample paired
percentile bootstrap with Bonferroni-adjusted intervals. Faults/controls are separate
safety/descriptive domains.

Pilot freezes minimum worthwhile delta, maximum p95 age/jerk/discontinuity, maximum
hold/overrun rates, and discontinuity trigger; P4 supplies recovery deadline. Equality
at a maximum passes (value<=limit); any nonfinite/unclamped unsafe output or invariant
violation fails. Efficacy needs adjusted lower endpoint strictly greater than delta.

Select exactly one eligible protocol in fixed order B,C,D,E,F,G. SUPPORTED means one
candidate clears efficacy and all gates. NOT_SUPPORTED means every completed valid
candidate has adjusted upper endpoint<=delta or a frozen non-efficacy failure, with no
invalid/imprecise evidence. INCONCLUSIVE covers any interval straddling/equaling delta,
invalid control, missing/corrupt artifact, systematic protocol loss, invalid shard, or
P4 eligibility failure. Descriptive-stack results never affect the label.

## Artifact, source, and parallel boundary

experiments/02_action_chunks owns documents, configs/base.yaml and frozen.yaml, run.py,
broker/protocol/schedule/task-adapter/evaluate modules, tests, create-only rollouts,
proposal sidecars, manifests, aggregates, bootstrap/decision outputs, and plots. Tests
cover all formulas, every table cell, rejected wrappers, direct/derived/hold lifecycle,
absolute-tick immutability, eligibility proofs, resume identity, equality boundaries,
and headless replay. Confirmation additionally requires P2/P3 audit, P4 input hashes,
safety guard, repository tests, secret/artifact scan, and git diff --check.

P5 runtime needs P3-approved MuJoCo and P4's local adapter. ACT temporal ensembling,
LeRobot async/RTC, and OpenPI broker are study-only P3 seams; P5 imports/copies none.
One worker owns broker/protocol tests, one owns scheduler/adapter/evaluator tests, and
one owns config/CLI/artifact tests. They do not edit P4 or reflect; integration is
broker, adapter, then artifact/replay validation, and latency-bearing shards are serial.

## Self-review

This revision derives all horizons from P4 interpolation and expiry, hard-gates exact
P4 stack IDs, makes response/rejection/hold lifecycles addressable, separates core from
fault evidence, fixes pilot/confirmation maxima and resume identity, selects one primary
protocol, and never calls an approximation RTC-compatible.

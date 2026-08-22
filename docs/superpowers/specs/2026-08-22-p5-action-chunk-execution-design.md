# P5 Temporal Action-Chunk Execution Design

Date: 2026-08-22

Status: approved autonomous default. P5 execution requires completed P3 provenance
and a completed P4 confirmation.

## Outcome, eligibility, and boundary

P5 implements Experiment 02: seven temporal protocols alter only unexecuted future
actions while the P4 simulated arm continues to move. The claim is a bounded
latency/reactivity/smoothness trade-off under one deterministic policy-output function.
It does not establish VLA intelligence, hardware async safety, or RTC equivalence.

P5 is eligible only if P4 promotes at least one CommandVariant whose P4 executor
provides a multi-step executable horizon with at least K + 1 future control ticks
after its first issued reference. This permits B to discard future work and guarantees
that the target perturbation lies inside A's usable horizon. A one-knot joint target,
MPC goal, or residual is ineligible unless P4 separately measured a multi-step adapter
for that exact representation. If P4 promotes no eligible row, P5 is
prerequisite-blocked and makes no protocol decision.

At freeze, P5 records this P4 input matrix:

| P4 promoted variant in promotion order | representation | frozen executor/horizon | H >= K + 1 | P5 role |
|---|---|---|---|---|
| every P4-promoted variant | exact P4 value | exact P4 value | yes/no | PRIMARY, DESCRIPTIVE, or INELIGIBLE |

The first eligible P4 row is the sole primary stack. A second eligible row may run as
descriptive evidence only; it does not enter the primary multiplicity family or choose
a second protocol. P5 consumes the primary P4 task bytes, controller/executor, action
shape, horizon H, target geometry, success criterion, and provenance hashes without
changing them. It adds no VLA, checkpoint, server, ROS, CUDA, remote transport, or
physical communication, and does not assume shared reflect schema changes.

## Alternatives

1. **P4 planar task plus a project-local virtual-time broker — selected.** It retains
   P4's 500 Hz controller and meaningful jerk/tracking measures while isolating queue
   semantics as the treatment.
2. **Pure-Python point-mass queue model — fixture only.** It is suitable for
   hand-calculated broker unit tests but not controller evidence.
3. **LeRobot/OpenPI runtime adaptation — deferred.** Server, serialization, trust,
   dependency, and possible flow-model behavior would confound the synthetic gate.

## Data flow and issued-reference immutability

~~~
P4 arm + target -> immutable request Observation/SkillSpec -> raw proposal arrival
-> protocol broker -> executable ActionChunk -> P4 executor/controller -> MuJoCo
-> ControlReferences, events, metrics, rollout and proposal sidecar
~~~

All comparisons pair the scenario seed, target path, latency draw, policy function,
raw payload, and fault schedule. Request times are protocol-specific because they are
the treatment; they are deterministically derived by the state machines below.

An issued reference has absolute tick n = time_ns / P4_dt_ns. On first issue the
broker copies the selected action vector to a C-contiguous read-only array and stores
it in append-only issued[n] and its ControlReference. Later arrivals may read but
cannot mutate issued entries. Tests compare issued-array byte hashes before and after
every later response, replacement, ensemble, blend, or conditioning operation.

## Protocol state machines and exact formulas

P is the frozen policy period, H the frozen P4 horizon, and K a frozen positive
integer satisfying K + 1 <= H. Every request captures one fresh stored observation;
no state machine may request twice from an observation ID.

| ID | Name | Request trigger / in-flight bound | Valid-arrival result |
|---|---|---|---|
| A | OPEN_LOOP | one initial request only | accept raw proposal directly |
| B | RECEDING_PREFIX | after exactly K issued ticks, discard remaining future then request; at most one in flight | accept raw proposal or safe hold |
| C | TEMPORAL_ENSEMBLE | periodic epoch mP, up to cap I in flight | ensemble raw proposals into a derived executable chunk |
| D | LATEST_VALID | periodic epoch mP, up to cap I in flight | newest valid proposal replaces all unissued ticks |
| E | ASYNC_SAFE_PREFIX | prefetch once when exactly K unissued ticks remain; at most one in flight | continue valid prefix then replace; hold on expiry |
| F | OVERLAP_BLEND | same periodic trigger/cap as D | replace with deterministic overlap blend |
| G | RTC_APPROXIMATION | same periodic trigger/cap as D | replace with deterministic committed-prefix conditioning |

For C, at broker time now, let V(t) be raw proposals delivered by now that cover
absolute tick t; proposal i has action a_i(t) and delivery d_i:

~~~
w_i = exp(-lambda * (now_ns - d_i) / 1e9)
a_C(t) = sum(i in V(t), w_i * a_i(t)) / sum(i in V(t), w_i)
~~~

For F over the first M unissued overlap ticks, old and raw-new values are o_j and r_j:

~~~
beta_j = (j + 1) / (M + 1)
a_F(j) = (1 - beta_j) * o_j + beta_j * r_j, j = 0..M-1
~~~

After M, F uses r_j. For G over committed prefix L, old committed values are c_j
and raw-new values r_j:

~~~
gamma_j = (L - j) / L
a_G(j) = gamma_j * c_j + (1 - gamma_j) * r_j, j = 0..L-1
~~~

After L, G uses r_j. P4's unchanged limits and slew processing apply after every
formula. C/F/G create new immutable executable chunks and never mutate raw proposals.
G is always RTC_APPROXIMATION. RTC_COMPATIBLE is prohibited unless a P3-provenanced
compatible flow policy and its real RTC implementation are actually run.

## Proposal sidecar, executable chunks, and event lifecycle

Canonical rollout actions contain executable chunks only: direct raw chunks for
A/B/D/E and derived chunks for C/F/G. Every raw proposal is a create-only canonical
JSONL sidecar outside the rollout directory at
results/<phase>/proposals/<rollout_id>.jsonl; the phase artifact manifest hashes it.
Each record has exactly:

~~~
proposal_id, rollout_id, request_observation_id, request_observation_time_ns,
request_sequence, delivery_time_ns, representation, dt_s, actions_shape,
raw_actions, actions_sha256, disposition, derived_chunk_id, parent_proposal_hashes
~~~

raw_actions is a canonical finite nested-float array and actions_sha256 is its
canonical-JSON hash. Disposition is exactly ACCEPTED_DIRECT, ENSEMBLED, REPLACED,
BLENDED, CONDITIONED, REJECTED_EXPIRED, REJECTED_OUT_OF_ORDER, DROPPED, or PAUSED.
A derived executable chunk uses the newest contributing proposal's observation ID/time
as source. Its metadata contains sorted parent-proposal hashes, rule revision, and
formula scalars. C assigns the newest delivery contributing to its first executable
tick as owner; F/G assign the arriving proposal.

For a delivered raw proposal, POLICY_RESPONDED references the resulting executable
chunk and includes the broker disposition. A direct or derived replacement emits
CHUNK_REPLACED for the former executable chunk then CHUNK_ACCEPTED for the new one.
Raw proposals not made executable are sidecar-only and have no fabricated action
lifecycle event; expiry/staleness is represented precisely in their disposition.

Safe hold is a broker-generated supported-representation ActionChunk, never an
untracked controller side effect. At hold entry, capture/store a current observation,
create a finite P4-adapter hold horizon with metadata.origin=broker_safe_hold, and
emit its standard accepted/executed/replaced-or-expired lifecycle. This preserves
source ownership, validity, age, and execution evidence without extending shared types.

## Virtual timing, perturbations, and exact applicability

VirtualClock is the only behavior-time source. On every P4 2 ms tick: apply target
movement; fire due protocol trigger/capture observation; schedule/drop/pause raw
response; deliver arrivals ordered by (delivery_time_ns, request_sequence); apply
broker disposition; execute one P4 control/MuJoCo step; log telemetry; then advance
2 ms. Host time is measured only.

For A core conditions, with t0 initial executable acceptance, freeze first target
movement at t0 + (K - 0.5) * dt. It is strictly after first issue and before the
(K + 1) future boundary, therefore inside A's usable horizon. The two-move A
condition is allowed only when frozen P4 horizon/expiry proves both moves fit before
expiry; otherwise P5 is blocked rather than silently relocating a perturbation. For
B--G, movements occur while that protocol has an outstanding request.

Core grid: latency {50,150,300,700} ms times one/two target movements with no fault
(eight episodes per seed/protocol). One-fault probes use 300 ms and one movement:

| Fault | A | B | C | D | E | F | G | expected outcome |
|---|---|---|---|---|---|---|---|---|
| first response dropped | initial | post-prefix | periodic | periodic | prefetch | periodic | periodic | hold after no valid future |
| old after newer | N/A | N/A | yes | yes | N/A | yes | yes | old proposal rejected |
| policy pause | initial | post-prefix | periodic | periodic | prefetch | periodic | periodic | hold on expiry |
| differing strategies | N/A | yes | yes | yes | yes | yes | yes | protocol-specific disposition |
| finite discontinuous proposal | initial | post-prefix | periodic | periodic | prefetch | periodic | periodic | frozen accounting |

N/A is not run or imputed. Episodes per seed are A=11, B=12, C=13, D=13, E=12,
F=13, G=13: 87 total primary-stack episodes per paired seed. A stationary/no-fault
negative control runs on the frozen subset of confirmation seeds; it must satisfy P4
hold success and create no recovery event.

## Invariants and transition table

Required invariants: no expired/not-yet-valid execution; no older-observation
supersession; finite selected shape; frozen bounded queue/in-flight state; immutable
issued absolute ticks; safe hold instead of indefinite stale action; non-regressing
events; one request per observation; coherent lifecycle; and no network, remote, or
physical path.

| arrival/state | queue transition | lifecycle | sidecar disposition |
|---|---|---|---|
| valid direct A/B/D/E | protocol enqueue/replace unissued | response, old replace if needed, new accept | direct/replaced |
| valid C/F/G | recompute only unissued, create derived chunk | response for derived, old replace, new accept | ensembled/blended/conditioned |
| expired or older | unchanged | no executable action event | rejected-expired/rejected-out-of-order |
| dropped or paused | unchanged until exhaustion | request visible; hold accepted on exhaustion | dropped/paused |
| no valid future | replace with hold chunk | old replacement/expiry then hold accept/execute | hold metadata |

## Pilot, freeze, confirmation, and resume

Pilot uses eight paired seeds: four tuning then four one-shot validation seeds. It has
at most 104 episodes per protocol and 696 primary-stack episodes. Begin at the base
vector; choose exactly one vector by tuning-seed mean paired recovery success subject
to zero invariant violations; run it once on validation seeds without re-selection.

Finite pilot sets are K in {1,2,4} with K+1<=H; I in {1,2,4}; lambda in {0,1,4} per
second; M in {1,2,4} with M<=H; L in {1,2,4} with L<=H; timeout in {1.0,1.5,2.0}P.
Values outside P4 horizon are omitted, not rounded. One scalar group may change per
revision; there are at most two revisions and three vectors per protocol/revision.

Freeze hashes code/config/P2-P4 provenance, eligibility matrix, selected scalars,
grid/fault table, metrics, margins, and bootstrap procedure. It freezes only the
confirmation RNG procedure and count (32), never future seed values. After freeze the
orchestrator generates exactly 32 new paired seeds and publishes immutable
seed-manifest.json before execution.

Confirmation is 2,784 primary-stack episodes (32 * 87); no protocol exceeds 416,
below the 1,024-per-variant ceiling. Run four serial shards of eight confirmation
seeds; pilot uses two serial shards of four. CLI arguments are --phase,
--seed-manifest, --shard-index, --shard-count, --output-dir, --headless, --dry-run,
and --max-episodes. Existing outputs are validate-and-skip only when rollout, sidecar,
and manifest hashes all validate; conflicting, partial, or mismatched outputs fail.
--max-episodes is smoke-only unless it equals a shard's manifest count.

## Primary decision, multiplicity, and equality

Primary estimand: paired seed-level recovery-success difference, candidate minus A,
equal-weighted over that protocol's applicable frozen conditions. Higher is better.
The six B--G contrasts on the sole primary stack are one family and use deterministic
10,000-resample paired percentile bootstrap with Bonferroni-adjusted intervals.

Pilot derives then freeze records minimum worthwhile improvement delta, maximum p95
age/jerk/discontinuity, maximum hold/overrun rates, and discontinuity trigger; P4
supplies recovery deadline. Exact equality at a maximum passes (value <= limit); a
nonfinite/unclamped unsafe output or invariant violation fails. Efficacy requires the
adjusted lower endpoint strictly greater than delta; equality does not pass.

Select exactly one safety- and efficacy-eligible candidate by fixed order B,C,D,E,F,G.
The result is SUPPORTED iff one selection exists. It is NOT_SUPPORTED iff every
completed valid candidate either has adjusted upper endpoint <= delta or fails a
frozen non-efficacy gate, with no invalid/imprecise evidence. It is INCONCLUSIVE
otherwise: any interval straddling/equaling delta, invalid negative control, missing
artifact, systematic protocol-specific loss, or invalid shard. Descriptive secondary
results cannot affect the primary label or selected protocol.

## Artifact, test, source, and parallel boundaries

experiments/02_action_chunks owns claim/experiment/results/interface/decision
documents; configs/base.yaml and configs/frozen.yaml; run.py; source modules broker,
protocols, schedule, task_adapter, evaluate; matching tests; pilot/confirmation
manifests, aggregates, bootstrap/decision output, plots, and proposal sidecars. Every
rollout and sidecar is create-only. Tests cover all formulas/state rows, source
ownership/parent hashes, A inside-horizon placement, all applicable faults, safe hold,
absolute-tick immutability, determinism/resume, metric/bootstrap equality boundaries,
artifact validation, and headless replay. Confirmation also requires P2/P3 audit, P4
input hashes, safety guard, full suite, secret/artifact scan, and git diff --check.

P5 runtime needs only P3-approved MuJoCo and the P4 local adapter. ACT temporal
ensembling, LeRobot async/RTC, and OpenPI broker are study-only P3 source seams; P5
imports/copies none. One worker owns broker/protocol tests, one owns adapter/scheduler/
evaluator tests, and one owns config/CLI/artifact/report tests. They do not edit P4 or
reflect; integration is broker, adapter, then artifact/replay validation, and all
latency-bearing shards run serially.

## Self-review

The design blocks rather than weakens the multi-step P4 prerequisite, makes request
timing protocol-specific, serializes raw and derived actions audibly, fixes fault
denominators and resource counts, selects one primary protocol, and never calls an
approximation RTC-compatible.

# P4 Policy-to-Controller Boundary Design

Date: 2026-08-22

Status: approved autonomous default. Execution remains gated on a complete, passing
P3 source-compatibility decision.

Canonical input: `Reflect Lite Research Program.md` Sections 10, 11, 13, 24, 25,
27, 29, and 30, plus the approved autonomous-run design and P2/P3 source designs.

## Outcome and claim boundary

P4 implements Experiment 01 and answers one bounded question: on one controlled
moving-target arm task, which command stack gives the best recovery-under-latency
trade-off when a conventional controller retains responsibility for stable
execution?

The comparison includes all six canonical command variants and the controller or
executor that makes each variant meaningful. It is therefore a **stack-level
comparison**, not evidence of representation-only causality. P4 does not establish a
universally correct VLA action space, contact-rich humanoid performance, or learned
policy superiority. It uses a deterministic synthetic policy so model quality cannot
confound the interface comparison.

P4 may promote no more than two command stacks to Experiment 02. It separately
deduplicates and reports their wire representations. It also
records whether the evidence favors a `SkillSpec -> MPC goal`, policy-to-trajectory,
joint-command, Cartesian-command, or bounded-residual seam. A valid negative or
inconclusive result may retain only the stable joint-target anchor.

P4 starts only after P3 has:

- completed the full P2 audit;
- approved and smoke-tested the locked MuJoCo package on the local M2;
- dispositioned the Experiment 01 sparse references;
- validated the source map, licenses, and compatibility outputs; and
- left physical and remote execution disabled.

P4 consumes the P3 lock and reports but does not change them.

## Alternatives and trade-offs

### A. Project-local inline 3R planar arm — selected

Use a three-revolute-joint planar arm defined by a small inline MJCF string and
project-local analytic kinematics.

Advantages:

- adds one degree of redundancy for a two-dimensional target, making the boundary
  between joint commands, differential IK, trajectories, and predictive control
  meaningful;
- stays small enough for exhaustive deterministic local comparisons;
- needs no robot asset, ROS, CUDA, model checkpoint, or additional controller
  dependency;
- permits exact FK/Jacobian checks and intentionally simple controller ownership;
- keeps all task-specific physics and tuning inside Experiment 01.

Trade-off: it needs a small local FK/Jacobian implementation and a deliberate
null-space posture rule. Those are bounded and directly tested.

This option best answers the claim because it exposes semantic/controller trade-offs
without turning asset integration or a robotics framework into the experiment.

### B. Project-local inline 2R planar arm — rejected

A two-link arm is simpler and has a closed-form inverse kinematic solution.

Its lack of redundancy makes Cartesian and joint targets nearly interchangeable away
from singularities. That weakens the comparison of controller ownership and can make
P3/P4/P5 differences collapse into the same unique joint solution. The modest code
saving is not worth the reduced discriminating power.

### C. Upstream Menagerie arm — rejected for P4

A Panda or other Menagerie model would be more recognizable and closer to a real
manipulator.

It also introduces per-asset licensing, higher-dimensional IK, collision geometry,
gravity compensation, actuator tuning, and asset-path/version seams. Those factors
would confound the bounded interface claim and create scaffolding that Experiment 01
does not need. Menagerie remains a pinned study reference and possible later transfer
fixture; it is not the P4 runtime model.

## Arm and task

The inline MJCF model has:

- three z-axis hinge joints;
- link lengths `0.30`, `0.25`, and `0.20` metres;
- joint limits `[-2.70, 2.70]` radians;
- zero gravity and joint damping `0.10`;
- torque motors with control range `[-12.0, 12.0]` N m;
- a named end-effector site at the third link tip; and
- a MuJoCo timestep of `0.002` seconds.

The low-level loop runs at 500 Hz. Every stack produces a joint reference that passes
through the same `1.5 rad/s` per-joint slew limiter and the same joint-space PD
controller. The initial PD values are `Kp=80.0` and `Kd=8.0` for every joint. Torque,
joint, and reference bounds fail closed and are logged.

Project-local analytic forward kinematics and a `2 x 3` Jacobian use the same link
lengths as the MJCF. Tests compare FK to the MuJoCo end-effector site and compare the
Jacobian to centred finite differences.

Each episode lasts `6.25` simulated seconds. Its initial joint position is
`[0.35, -0.70, 0.35] + U(-0.08, 0.08)^3` from the named scenario RNG stream; initial
velocity is zero. The initial target is a reachable point `0.04 m` from the initial
end-effector position. The target moves by `0.06 m` at `t=2.0 s` and, for the
two-move condition, again at `t=4.0 s`. Directions come from the eight compass
directions through the same seeded generator.

Scenario generation is variant-independent. Before any stack runs, the orchestrator
uses only the arm geometry, hard joint limits, and phase seed to generate one
immutable scenario record containing q0, the initial target, the one-move target
path, the two-move target path, and the stationary negative-control path. A condition
selects a path from that record; it never regenerates one. The generator rejects and
deterministically resamples a proposal when any target radius is outside
`[0.30, 0.70] m` or the scenario generator's fixed feasibility IK cannot find a
solution at least `0.15 rad` inside every joint limit. The feasibility solver and its
parameters are frozen with the protocol and are not any stack's tuned controller.

The generator uses NumPy `PCG64`; separate named substreams produce q0 perturbations,
the initial target direction, and move directions. Feasibility uses the frozen
12-update absolute-target IK below with `lambda=0.01`, initialized from generated q0,
regardless of any later stack tuning.

Each candidate seed permits at most 32 proposals. Pilot manifests record all accepted
and rejected proposals. After Freeze, confirmation candidate seeds are consumed in
ascending generated order until exactly 32 valid scenario records exist; exhaustion
of 64 candidate seeds makes confirmation `INCONCLUSIVE`. The complete confirmation
scenario manifest is hashed before the first stack executes. A failure by one stack
never causes scenario regeneration, replacement, or rejection for another.

Target success means Euclidean end-effector error is at most `0.025 m` continuously
for `0.10 s`. Recovery time for a displacement is the interval from target movement
to the first such dwell. Failure to recover within `2.0 s` is recorded as a censored
`2.0 s` value, never dropped as missing data.

## Shared inputs and fairness boundary

At each policy request every stack receives the same immutable pair:

1. a canonical `Observation` containing q, dq, timestamps, and an `ObjectBelief` for
   the target pose; and
2. a `SkillSpec` containing the same target pose, fixed joint/workspace constraints,
   success radius, timeout, and zero retry budget.

Both objects are snapshots at request time. After a request, neither the synthetic
policy nor any representation-specific controller can read the live target. Fast
controllers may read current q and dq because state feedback is precisely the
conventional-controller responsibility being tested. This prevents Cartesian, MPC,
or residual stacks from gaining a hidden current-target channel.

The synthetic policy is deterministic and uses only analytic geometry, fixed
iterations, and the supplied snapshots. Injected latency is independent of measured
host compute time. Real compute time is recorded separately and all latency-sensitive
measurements run serially.

## Six command stacks

P4 uses the existing `ActionRepresentation` values. The experiment-local stack ID
is stored in `ActionChunk.metadata["stack_id"]`; the global enum is not expanded merely
to distinguish one waypoint from a trajectory in the same value domain.

All chunks set `generated_time_ns` and `valid_from_ns` to response-delivery time,
`dt_s` to the policy period in seconds, and `expires_at_ns` to delivery time plus
`ceil(2.5 * policy_period_ns)`. Their source observation ID and time bind them to the
stale snapshot used by the policy. Source age is delivery time minus source observation
time and remains a measured property; it is not conflated with the chunk's execution
validity. Accepting an old-but-latest nominal response is part of the latency treatment.
Observation order, not a second age threshold, rejects the deliberate stale response.

### P1 — Joint target

- representation: `JOINT_POSITION`;
- action shape: `(1, 3)`;
- policy: the frozen absolute-target IK defined below, initialized at observed q;
- executor: hold the one q target, apply the common slew limiter, then PD.

P1 is the preregistered anchor.

### P2 — Joint trajectory

- representation: `JOINT_POSITION`;
- action shape: `(H, 3)`, where
  `H = ceil(0.8 / policy_period_s) + 1`;
- policy: form a straight Cartesian path from the observed end effector to the
  observed target and run the frozen absolute-target IK sequentially at every knot,
  initializing each solve from the preceding knot;
- executor: linearly interpolate joint waypoints on their frozen knot times, apply
  the common slew limiter, then PD.

Only the prefix available during chunk validity is executed.

For P2 and P4, knot `i` uses `alpha=i/(H-1)` and
`x_i=(1-alpha)*x_observed+alpha*x_target`; no target-velocity prediction or easing is
used.

### P3 — Cartesian target

- representation: `EEF_TRAJECTORY`;
- action shape: `(1, 2)` containing one absolute XY target;
- policy: copy the observed target into the chunk;
- executor: at every low-level tick, use current q and the frozen differential IK
  rule to approach the held Cartesian target, then apply the common slew limiter and
  PD.

Using the one-knot `EEF_TRAJECTORY` wire value preserves the existing enum while
making target versus path cardinality explicit.

### P4 — Cartesian trajectory

- representation: `EEF_TRAJECTORY`;
- action shape: `(H, 2)` with the same horizon rule as P2;
- policy: form a straight Cartesian path from observed end effector to observed
  target;
- executor: linearly interpolate the XY path on its frozen knot times and run the
  frozen current-q differential IK rule at each low-level tick, followed by the
  common slew limiter and PD.

### P5 — MPC objective

- representation: `MPC_GOAL`;
- action shape: `(1, 2)` containing the observed absolute XY target;
- metadata: joint, velocity, and torque limits; success radius; cost revision;
- controller: deterministic kinematic predictive sampling at 50 Hz, holding its q
  reference between planner ticks.

At each planner tick, the controller evaluates zero velocity plus every nonzero
direction in `{-1, 0, 1}^3`, normalized to unit Euclidean norm and scaled by each
magnitude in `{0.25, 0.75, 1.50} rad/s`. This yields 79 deterministic candidates and
prevents the candidate set from forcing a choice between holding and only maximum-
speed motion. Each constant-velocity candidate is predicted across ten `0.02 s`
steps using `q_(k+1)=q_k+0.02*qdot` and analytic FK at each predicted q. A candidate
crossing the hard joint limit is infeasible and discarded.

The cost is dimensionless. Let `N=10`, `T=0.20 s`, `dt=0.02 s`, target-error scale
`e_scale=0.06 m`, velocity scale `v_scale=1.50 rad/s`, soft joint margin `m=0.15 rad`,
`e_k = ||x_target-x_k||/e_scale`,
`u = ||qdot||/(sqrt(3)*v_scale)`,
`s = ||qdot-qdot_previous||/(sqrt(3)*v_scale)`, and
`b_k = ||max(0, abs(q_k)-2.55)||/(sqrt(3)*m)`. The integrated cost is

```text
J = e_N^2
    + sum(k=1..N, dt/T * (
          e_k^2
        + 0.01 * u^2
        + 100.0 * b_k^2
        + 0.02 * s^2))
```

Every term is normalized before weighting and the stage sum is integrated by `dt/T`,
so changing prediction discretization does not silently rescale the objective.
Candidates are ordered first by magnitude and then lexicographically by their raw
direction tuple; the first minimum wins exact ties. The first predicted q increment
becomes the reference before the common slew limiter and PD. This is a bounded local
receding-horizon controller, not a production safety layer or an imported MJPC
implementation.

Two hand-calculated controller tests guard against the hold bias found in review. In
a zero-penalty one-dimensional fixture, holding a `0.04 m` error has
`J_hold = 2*(0.04/0.06)^2 = 0.888888...`; a feasible candidate that closes the error
linearly over ten steps has stage-error cost
`(0.04/0.06)^2*(285/1000) = 0.126666...` and total cost below `0.136667` when its
normalized effort/smoothness contribution is at most `0.01`. For a `0.06 m` move,
`J_hold = 2.0` while the corresponding move cost is below `0.295`. Both fixtures must
select motion over hold, and an infeasible moving candidate must still lose to hold.

### P6 — Bounded residual

- representation: `BOUNDED_RESIDUAL`;
- action shape: `(1, 3)`;
- nominal reference: a deterministic one-second minimum-jerk joint trajectory from
  initial q to the initial target IK solution, then hold;
- policy: compute stale-snapshot target IK, subtract the nominal q at response time,
  and clip each residual component to `[-0.25, 0.25] rad`;
- executor: add the most recently accepted residual to the nominal reference, then
  apply the common slew limiter and PD.

The nominal path never receives a moved target. Only the delayed residual communicates
post-displacement target information. P6 uses exactly the same target snapshot and
absolute-target IK as P1; its only additional input is the deterministic nominal q at
the response timestamp, which is derivable from the episode's initial public state.
It receives no future target, live target, or variant-specific scenario information.
For `s=clip(t/1.0 s, 0, 1)`, its frozen blend is
`h(s)=10*s^3-15*s^4+6*s^5` and
`q_nominal(t)=q_initial+h(s)*(q_initial_target-q_initial)`; no replanning or nominal
state feedback occurs after episode start.

### Frozen IK and interpolation rules

Absolute-target IK runs exactly 12 updates. With error `e`, Jacobian `J`, damping
`lambda`, pseudoinverse
`J_hash = J.T @ inv(J @ J.T + lambda^2 * I2)`, posture
`q_posture = [0.35, -0.70, 0.35]`, and
`N = I3 - J_hash @ J`, each update is

```text
dq = J_hash @ e + 0.05 * N @ (q_posture - q)
q = clip(q + clip_norm(dq, 0.10), -2.55, 2.55)
```

`clip_norm` preserves direction and limits Euclidean norm. All 12 iterations execute;
there is no tolerance-dependent early exit. The base damping is `lambda=0.01` and a
pilot-selected damping is shared by every absolute and differential IK use.

Differential IK uses the same damped pseudoinverse and null-space definition. At each
2 ms tick it computes

```text
v_xy = clip_norm(4.0 * (x_ref - x(q)), 0.25 m/s)
qdot = J_hash @ v_xy + 0.20 * N @ (q_posture - q)
q_candidate = q + 0.002 * clip_each(qdot, -1.5, 1.5)
```

then applies the common q-reference slew limiter. P2 and P4 knot zero is at
`valid_from_ns`; subsequent knots are exactly one policy period apart; their
`ActionChunk.dt_s` equals that period. Linear interpolation uses the closed interval
between adjacent knots, holds the first knot before knot zero, and holds the final
knot after the last knot only while the chunk remains valid. P1, P3, P5, and P6 also
set `dt_s` to the policy period even though they contain one action row. These rules,
the null-space gains, iteration count, per-update clamp, Cartesian velocity cap,
posture, and interpolation endpoints are all frozen before confirmation.

## Virtual timing and injection order

`VirtualClock` is the only source of experiment time. No simulation path sleeps or
uses wall time to decide behaviour. A priority queue orders scheduled responses by
`(delivery_time_ns, request_sequence)`.

For a condition with base latency `L`, policy period `P`, and possible out-of-order
extra delay `D` (`D=P+2 ms` only in that probe, otherwise zero), the last policy
request time is the greatest policy tick not later than

```text
episode_end - L - D - ceil(2.5 * P)
```

No requests are issued after that cutoff. Consequently every non-dropped response and
every action timestamp, including `expires_at_ns`, remains inside the rollout's
monotonic bounds. The last `ceil(2.5*P)` interval is an intentional tail in which the
last valid chunk runs and then the safe hold runs.

Each 2 ms tick performs this exact order:

1. apply a target movement scheduled for the current time;
2. if a policy tick is due, capture and record its observation and policy request;
3. schedule its deterministic response for request time plus injected latency;
4. deliver every response due at the current time, including a zero-latency response
   just requested in step 2;
5. for each delivery, emit `POLICY_RESPONDED`, then reject it as out of order when its
   source observation ID is lower than the last accepted ID, else reject it as
   expired only when delivery is at or after its frozen `expires_at_ns`, else accept
   it;
6. replace the active chunk only when that prior chunk is still within its half-open
   validity interval; when the prior chunk has expired, clear it and accept the new
   chunk directly without a `CHUNK_REPLACED` event;
7. decode the active valid chunk, or apply safe hold when none is valid, compute the
   common PD command, step MuJoCo, and accumulate 500 Hz metrics;
8. store a telemetry observation, executed `ControlReference`, and corresponding
   event every 10 ms; and
9. advance the virtual clock by 2 ms.

`Observation.current_phase` is semantically stable and always equals
`"track_target"`; it is never repurposed as a logging-role flag. Policy periods are
integer multiples of the 10 ms telemetry period. When they coincide, the scheduler
creates one observation and one `OBSERVATION_RECEIVED` event, uses that same
observation ID for telemetry and `POLICY_REQUESTED`, and never creates a duplicate.
At non-policy telemetry ticks the observation receives no policy request. Event
payload field `observation_role` is `"policy_and_telemetry"` or `"telemetry"` and is
the only role discriminator.

Accepted chunks produce `CHUNK_ACCEPTED`; replacement first produces
`CHUNK_REPLACED` for the formerly active chunk and then `CHUNK_ACCEPTED` for the new
one. `CHUNK_REPLACED` is never emitted at or after the old chunk's expiry. An
execution-validity-expired arrival produces `POLICY_RESPONDED` followed by
`CHUNK_REJECTED_EXPIRED`; a stale arrival produces `POLICY_RESPONDED` followed by
`CHUNK_REJECTED_OUT_OF_ORDER`. Rejection never precedes its response event.

Before the first accepted chunk, and after an active chunk's half-open validity
interval ends, safe hold latches current q, commands zero dq, and uses the common PD.
Because safe hold has no source chunk, it creates no `ControlReference` or
`ACTION_EXECUTED`; its ticks remain represented in telemetry and aggregate clamp/
saturation metrics. A later valid response can leave safe hold through a direct
`CHUNK_ACCEPTED` transition.

The deliberate dropped request is marked `drop_injection=true` in its
`POLICY_REQUESTED` payload and in episode metrics; it has no response or action. The
stop-request rule guarantees there are no other pending scheduled responses at
episode end. The only allowed unmatched request is that one declared drop. Any other
pending request/response, or any queue item remaining at episode end, invalidates the
rollout rather than being silently discarded.

## Experimental conditions

The core grid contains, for every stack and paired seed:

- policy rate: `5`, `10`, and `20 Hz`;
- injected policy latency: `0`, `100`, `300`, and `700 ms`; and
- target displacement count: one and two.

This is 24 equally weighted core conditions per stack and seed.

Two separate robustness probes run at `10 Hz`, `300 ms`, and two target movements:

1. drop exactly the first response requested at or after the first displacement;
2. delay that response by one policy period plus `2 ms`, causing the next response to
   arrive first and the delayed response to be rejected as out of order.

Drop and out-of-order are not crossed with the entire core grid. The smaller probe set
covers the canonical failures without an uninformative combinatorial expansion.

A stationary-target negative control runs at `10 Hz`, `300 ms` with no injected fault
for the first four confirmation seeds and every stack.

## Controlled variables

The frozen protocol holds constant:

- MJCF bytes, dynamics, timestep, and episode duration;
- target and initial-state scenario for a paired seed;
- policy observation contents and request times;
- latency and fault schedule;
- low-level PD gains and torque/joint/reference limits;
- chunk validity and replacement rules;
- target success definition and metric implementation;
- action and observation schema versions;
- logging cadence and event semantics;
- variant-independent scenario manifest, rejection rule, named RNG algorithms, and
  seeds; and
- real-compute measurement method.

Representation-specific IK, interpolation, residual composition, or predictive
control is part of the compared stack. No result is described as a controller-held-
constant representation effect.

## Metrics and estimands

### Primary estimand

For one episode, primary recovery is the mean censored recovery time over its one or
two target displacements. For one paired seed and stack, the primary value is the
equal-weight mean of the 24 core-condition episode values. One-move and two-move
conditions therefore receive equal condition weight rather than weighting the latter
twice.

The anchor is P1. The five primary contrasts are paired per-seed differences

```text
stack recovery - P1 recovery
```

so negative values are beneficial.

### Secondary metrics

P4 records:

- final Euclidean end-effector error at the last 500 Hz sample;
- mean and p95 Euclidean end-effector error over 500 Hz samples from the first target
  displacement through episode end;
- p95 action age over stored 100 Hz `ACTION_EXECUTED` samples as execution time minus
  source observation time;
- joint jerk proxy as the norm of the third finite difference of executed q divided
  by `dt^3`, using complete post-first-displacement 500 Hz quadruples;
- actuator saturation fraction over all 500 Hz ticks, where a tick is saturated when
  any actuator equals its inclusive torque limit after clipping;
- command discontinuity as
  `norm(q_ref[t] - q_ref[t-1])`, with mean and p95 over consecutive valid executed
  references after the first displacement; safe-hold boundaries are separately
  counted and are not bridged as a synthetic reference pair;
- unsafe/nonfinite command count;
- clamp fraction over all 500 Hz ticks, where equality to a limit without an actual
  pre-clamp exceedance is not counted as a clamp; and
- real policy/controller compute p50 and p95 from serial `perf_counter_ns`
  measurements.

For every empirical percentile, sort finite values ascending and use nearest rank
`max(0, ceil(p*n)-1)` with no interpolation. An empty action-age or discontinuity
domain is a missing required metric and invalidates that episode. All threshold
comparisons are inclusive: equality passes `<=` budgets and `>=` recovery fractions.

Episode metrics are first computed on the domains above. A condition value is the
arithmetic mean across its valid displacement events; a seed value is the
equal-weight arithmetic mean across its 24 complete core-condition episode values.
Stacks are never pooled before paired seed contrasts. Robustness probes, negative
controls, and compute latency are reported separately from the core primary estimand.
Plots use seed-level means with equal seed weight: recovery-versus-latency averages
over rates and move counts, error-versus-rate averages over latencies and move counts,
and jerk/action-age plots show the full core seed distribution. The representative
timeline is the lexicographically first valid confirmation seed at `10 Hz`, `300 ms`,
two moves, no injected fault, for P1 plus the ultimately promoted stacks; its identity
is selected by this rule rather than visual appeal.

One missing/corrupt core episode invalidates that `(stack, seed)` primary value.
The same seed is then excluded from every paired contrast involving that stack but
remains usable for other complete contrasts. One such accidental invalid seed is
permitted and reported; a second invalid seed for any stack, any systematic
stack-specific loss, any missing negative-control episode, or any negative-control
failure makes the whole confirmation `INCONCLUSIVE`. No missing value is imputed.

Secondary metrics explain the selected seam and enforce frozen safety/smoothness
budgets. They do not reverse a failed primary recovery decision.

### Required plots

A deterministic experiment-local SVG writer produces:

1. recovery time versus policy latency;
2. tracking error versus policy rate;
3. joint jerk by command stack;
4. p95 action age by stack and condition; and
5. one representative timeline showing target, policy requests/responses, chunk
   lifecycle, q reference, and executed end-effector motion.

SVG generation uses no plotting dependency and sorts all records explicitly.

## Lifecycle and preregistration

### Draft

Draft completes when the six stacks, simulator, metrics, scheduler, command, tests,
and artifact validation exist. Draft output carries no measurement claim.

### Pilot

Pilot uses eight paired seeds generated from a checked-in pilot seed root. The first
four are tuning seeds and the final four are a single untouched pilot-evaluation set.
No parameter, exclusion, implementation, or protocol decision may use the final four
before that single evaluation. Pilot permits at most two protocol revisions and at
most three configurations per stack per revision.

Initial parameters are the exact values in this design. A subsequent configuration
may change only one of these named scalar groups without changing architecture:

- common PD pair: `(60, 6)`, `(80, 8)`, or `(100, 10)`;
- IK damping: `0.001`, `0.01`, or `0.05`; or
- MPC smoothness coefficient: `0.01`, `0.02`, or `0.04`.

Common PD changes apply to every stack. Each candidate configuration runs only the
12-condition tuning subset: three rates crossed with `0/700 ms` latency and one/two
moves, with no fault probes. After tuning selects one configuration per surviving
stack, that configuration runs exactly once on the final four seeds over all 24 core
conditions and both robustness probes. No result from those final four can trigger a
retune; changing anything starts a new protocol revision with eight new pilot seeds.
No pilot may replace a failed controller with a new stack.

A non-anchor stack is killed during pilot when it has any dimensional mismatch, nonfinite
reference/state, joint-limit escape, unstable divergence, or fails to recover all
four pilot-evaluation seeds within `1.0 s` in the easiest `20 Hz`, `0 ms`, one-move
condition after its one straightforward implementation and bounded scalar tuning.
Killed stacks are marked unsuitable for this task and receive no confirmation run.

P1 is not replaceable. If P1 hits any kill condition or fails its final-four easiest-
condition requirement, P4 immediately records `INCONCLUSIVE`, moves to `STOPPED`, and
runs no confirmation. A new anchor or controller would be a new reviewed protocol,
not an autonomous continuation of this one.

Per protocol revision, the maximum pilot count is exact: at most
`3 configurations * 4 tuning seeds * 12 conditions = 144` tuning episodes plus
`1 selected configuration * 4 evaluation seeds * 26 conditions = 104` evaluation
episodes, for at most 248 episodes per stack. This remains below the autonomous
256-pilot-episode ceiling. With six stacks the revision maximum is 1,488 pilot
episodes.

### Freeze

After pilot, `configs/frozen.yaml` records and hashes:

- implementation Git SHA and clean-tree status;
- P2/P3 source-lock and compatibility hashes;
- MuJoCo package version and artifact hash;
- MJCF, scenario, metric, plotting, and gate revisions;
- all absolute/differential IK equations and parameters, posture/null-space rules,
  interpolation endpoints, `dt_s`, MPC normalization/candidates/cost, residual
  nominal construction, controller parameters, and limits;
- surviving stacks and pilot exclusions;
- pilot tuning and untouched pilot-evaluation seed manifests;
- confirmation seed count and RNG algorithm;
- exact bootstrap and multiplicity procedure; and
- every threshold below.

The implementation commit and frozen config are immutable for confirmation. Any
defect requiring code, config, metric, or threshold changes returns P4 to Draft with a
new protocol revision and a new unseen confirmation manifest.

### Confirmation

After freeze, the orchestrator generates the variant-independent 32-scenario
confirmation manifest from a new recorded RNG root that did not exist during
implementation or pilot. Every surviving stack runs the 24 core conditions and two
robustness probes for all 32 seeds, plus the stationary negative control for the first
four seeds.

The exact maximum is `32 * 26 + 4 = 836` paired confirmation scenario-condition
bundles, below the 1,024 paired-confirmation ceiling. Each bundle executes every
surviving stack on the identical scenario. With all six stacks surviving, those 836
paired bundles contain 5,016 stack rollouts. Each rollout is 6.25 simulated seconds,
so the maximum confirmation manifest contains 31,350 simulated seconds. One shard is
exactly one
`(phase, stack, configuration, seed)` tuple: 12 episodes for a tuning shard, 26 for a
pilot-evaluation shard, and 26 or 27 for a confirmation shard depending on whether
that seed includes the negative control. Thus a confirmation shard contains at most
168.75 simulated seconds and is subject to the 60-minute wall-clock command ceiling.

Each rollout has a hard 1 MiB serialized-artifact limit checked before publication.
The maximum confirmation payload is therefore 5,016 MiB plus a 256 MiB aggregate/
manifest/plot allowance; pilot is at most 1,488 MiB plus a 128 MiB allowance. Both are
inside the 10 GiB generated-artifact ceiling, and the complete phase refuses to start
unless remaining budget covers its declared maximum.

The analysis uses a deterministic 10,000-resample paired percentile bootstrap over
seed-level primary values. The five contrasts against P1 form one multiplicity family
and use Bonferroni-adjusted 99% intervals. Each contrast resamples its complete paired
seed IDs with replacement. Its NumPy `PCG64` seed is the first 128 bits of
`SHA256(frozen_manifest_hash || "bootstrap" || stack_id)`, interpreted big-endian.
Timeouts are the censored `2.0 s` value.
Missing/corrupt episode and negative-control handling follows the exact aggregation
rules above; no second, conflicting missing-data rule applies here.

### Decision thresholds

Frozen thresholds are:

- minimum worthwhile recovery improvement: `0.10 s`;
- noninferiority margin versus P1: `+0.10 s`;
- at least 95% of easiest-condition displacement events recover before censoring;
- at least 90% of all core displacement events recover before censoring;
- zero nonfinite or unclamped unsafe outputs;
- zero joint-limit violations;
- clamp fraction at most 1%;
- actuator saturation fraction at most 5%; and
- p95 joint jerk and p95 command discontinuity each at most 1.5 times the frozen P1
  pilot-evaluation value.

Recovery fractions pool displacement-event pass/fail indicators across the named
confirmation domain: the easiest fraction uses all valid confirmation seeds in the
`20 Hz`, `0 ms`, one-move condition, and the core fraction uses all displacement
events in all 24 core conditions. Clamp and saturation fractions pool their exact
numerators and denominators over all core 500 Hz ticks for the stack. For jerk and
discontinuity, first compute the episode p95 using the rule above, then compute the
nearest-rank p95 across the complete set of core episode-p95 values with equal episode
weight. The frozen P1 multiplier uses the identical two-stage calculation on the
final-four pilot-evaluation core episodes. Equality to every threshold passes.

The stationary negative control must retain end-effector error at or below `0.025 m`
from `t=1.5 s` through episode end and must create no recovery event. Failure
invalidates confirmation rather than counting against a scientific stack.

A non-anchor stack is **superior** only when the upper endpoint of its adjusted 99%
interval is at most `-0.10 s` and every viability/safety/smoothness gate passes. It is
**noninferior and eligible** when the upper endpoint is at most `+0.10 s` and every
gate passes. Otherwise it is rejected.

Promotion is mechanical and limited to two command stacks:

1. rank superior candidates by the upper endpoint of their adjusted interval;
2. if fewer than two superior candidates exist, fill remaining slots with the lowest
   upper-bound noninferior candidates, including stable P1 as the fallback;
3. break an exact numerical tie by fixed order P1 through P6; and
4. promote no stack that fails an absolute or safety/smoothness gate.

For selection ranking only, stable P1 has a self-contrast and upper endpoint of zero.
This makes a beneficial but not superior non-anchor rank before P1, and a positive-
delta merely noninferior candidate rank after P1.

If P1 fails its absolute gate, the comparative decision is `INCONCLUSIVE`, P4 becomes
`STOPPED`, and no non-anchor stack is promoted from that confirmation.

`decision.json` contains both `promoted_stacks` and
`promoted_wire_representations`. The latter is the stable first-occurrence
deduplication of each promoted stack's `ActionRepresentation`; for example, promoting
both P1 and P2 yields two stack records but one `JOINT_POSITION` wire value. Experiment
02 receives at most two stack configurations plus this deduplicated wire-value list.
Reports never call two stacks with the same enum value two distinct wire
representations.

The Experiment 01 scientific result is:

- `SUPPORTED` when at least one non-anchor is superior;
- `NOT_SUPPORTED` when the lower endpoint of every valid non-anchor interval is
  greater than `-0.10 s` (thereby excluding the minimum benefit) and all controls and
  precision requirements are valid, or when every non-anchor was killed by its
  preregistered dimensional/stability rule while P1 remained valid; or
- `INCONCLUSIVE` otherwise, including resource exhaustion, invalid confirmation,
  imprecise intervals, or anchor failure.

## APIs and file boundaries

P4 adds no experiment implementation to `reflect/`. Its complete boundary is:

```text
experiments/01_policy_control/
  README.md
  CLAIM.md
  EXPERIMENT.md
  RESULTS.md
  INTERFACE_FINDINGS.md
  configs/
    base.yaml
    frozen.yaml                 # created only at Freeze
  run.py
  src/
    arm.py
    representations.py
    timing.py
    evaluate.py
  tests/
    test_arm.py
    test_representations.py
    test_timing.py
    test_evaluate.py
  results/
    pilot/
    confirmation/
```

`arm.py` owns:

```python
ArmConfig
PlanarArm
forward_kinematics(q) -> np.ndarray
jacobian(q) -> np.ndarray
bounded_pd(q_ref) -> tuple[np.ndarray, ClampReport]
```

`representations.py` owns:

```python
CommandStack
PolicyInput
ExecutorState
emit_chunk(stack, policy_input, config) -> ActionChunk
reference_for_tick(stack, chunk, q, dq, time_ns, state, config)
    -> tuple[ControlReference, ExecutorState, ClampReport]
```

`timing.py` owns:

```python
FaultKind
TimingCondition
ScheduledResponse
schedule_response(request, condition) -> ScheduledResponse | None
deliver_due(now_ns, queue, last_accepted_observation_id) -> DeliveryBatch
```

`evaluate.py` owns:

```python
Scenario
EpisodeMetrics
run_episode(stack, condition, seed, config) -> RolloutRecord
aggregate_seed_metrics(records) -> SeedMetrics
paired_bootstrap(seed_metrics, resamples=10_000) -> BootstrapDecision
apply_gate(decision, frozen_config) -> PromotionDecision
write_svg_plots(aggregate, output_dir) -> tuple[Path, ...]
```

The signatures name stable responsibilities, not shared production interfaces. Exact
experiment-local dataclass fields are fixed in `base.yaml` and module tests.

`run.py` exposes:

```text
python -m experiments.01_policy_control.run --config CONFIG
    [--seed SEED]
    [--output-dir DIR]
    [--dry-run]
    [--max-episodes N]
    [--headless]
    [--phase pilot|confirmation|analyze]
    [--shard-id STACK:CONFIGURATION:SEED]
```

`--dry-run` validates and prints the exact condition manifest without constructing
MuJoCo. `--max-episodes` truncates the sorted manifest and is smoke-only unless it
equals the frozen episode count for the selected shard. `--headless` is required for
evidence-bearing runs. Evidence-bearing execution requires exactly one declared shard
ID and may not run an open-ended phase glob. The only new root target is, for example,
`make exp01 SHARD=P1:base:000`; it resolves the supplied shard against the
frozen manifest when one exists and otherwise against the base pilot manifest. A
missing or unknown `SHARD` fails without running.

## Artifacts

Each `(phase, seed, stack, condition)` writes one create-only canonical rollout
directory through the existing `RolloutWriter`. It contains canonical metadata,
config, metrics, events, policy observations, decimated telemetry observations,
action chunks, executed control references, and summary. Metrics are accumulated at
500 Hz even though telemetry artifacts are stored at 100 Hz.

Each phase additionally writes:

- `protocol-manifest.json` with config/code/source hashes;
- `seed-manifest.json` with named RNG roots and generated scenarios;
- `aggregate.csv` with one deterministic row per episode and seed aggregate;
- `bootstrap.json` with resample algorithm, contrasts, intervals, and multiplicity;
- `decision.json` with every kill, gate, ranking, and promotion reason;
- `artifact-manifest.json` with hashes and sizes; and
- the five required SVG plots.

Pilot and confirmation directories are never overwritten. Report generation consumes
validated artifacts and does not rerun physics. `RESULTS.md` ends with the canonical
result sections; `INTERFACE_FINDINGS.md` records the selected `ActionChunk` value
domain and whether the evidence supports the MPC-goal, trajectory, joint, Cartesian,
residual, or fallback seam. It records rejected alternatives even when the result is
negative.

Shards are resumable only through create-only validate-and-skip semantics. Before an
episode runs, the command derives its destination from the frozen phase/stack/config/
seed/condition identity. If absent, it runs and publishes once through
`RolloutWriter`. If present, it runs full `validate_rollout`, verifies artifact,
protocol, source-lock, scenario, and condition hashes against the shard manifest, and
skips only on an exact match. A missing file, unexpected extra file, hash mismatch,
oversized artifact, interrupted temporary directory, or schema error fails the shard;
nothing is overwritten, repaired in place, or counted as complete. After all episode
destinations validate, the shard writes its own create-only completion manifest.

## Tests and verification

Unit and property tests cover:

- MJCF dimensions, timestep, joint/torque limits, and headless construction;
- analytic FK against the MuJoCo site and Jacobian against finite differences;
- scenario reproducibility, reachability, and bounded rejection;
- exact shapes, finite values, value domains, metadata, validity intervals, and
  bounds for all six stacks;
- proof that every stack receives identical policy information and no controller
  reads the live target;
- joint/Cartesian interpolation, IK damping, null-space rule, predictive candidate
  order/cost, residual bound, slew limit, torque clamp, and PD behaviour;
- exact VirtualClock ordering for 0/100/300/700 ms latency;
- one dropped response, one forced out-of-order response, expiry, replacement, and
  stale rejection, including responded-before-rejected order, direct acceptance after
  prior expiry, source-age measurement versus execution-validity expiry,
  stop-request cutoff, safe-hold intervals, declared dropped pending request, and an
  empty response queue at episode end;
- repeated-run determinism for virtual times, simulator traces, metrics, and
  deterministic artifact fields;
- recovery dwell/censoring, exact sample domains, nearest-rank percentiles, inclusive
  equality boundaries, error, action-age, jerk, discontinuity, saturation, clamp,
  missing-data, and negative-control rules on hand-calculated fixtures;
- dimensionless MPC stage integration and normalization, feasible multi-magnitude
  candidates, the hand-calculated 4 cm and 6 cm move-over-hold inequalities, and
  infeasible-candidate rejection;
- paired bootstrap, 99% multiplicity intervals, missing-data rules, threshold
  boundaries, tie ordering, result classification, two-stack promotion cap, and
  wire-representation deduplication;
- one zero-latency headless smoke episode for every stack;
- canonical rollout write, load, validation, event lifecycle, and replay;
- SVG determinism and required plot labels;
- CLI config validation, dry run, headless enforcement, seed/output/max-episode/shard
  handling, 60-minute shard bounds, 1 MiB rollout cap, and create-only
  validate-and-skip resumption including mismatch refusal; and
- full repository, lock, safety, secret, artifact-size, and diff checks.

A confirmation artifact is accepted only after the full test suite, frozen hash
validation, source audit, simulation-only guard, and replay checks pass.

## Dependency and source seams

The only P4 runtime addition beyond the existing NumPy, PyArrow, PyYAML, and pytest
environment is the exact P3-approved MuJoCo package already introduced and locked by
P3.

P4 does not install or import Mink, MuJoCo MPC, Menagerie, mjctrl, Rerun, MoveIt,
ros2_control, cuRobo, ROS 2, or CUDA. MuJoCo is the direct physics dependency.
MuJoCo MPC and mjctrl are pinned study references; the local controller code is an
independent bounded implementation. Mink remains an optional future adapter only if
a later experiment justifies it. Menagerie remains an asset reference.

No upstream source is copied. If implementation review later finds an adapted
snippet, execution stops until the P3 attribution record, exact source path, license,
and modification are recorded. Optional-source failure never triggers a new P4
controller stack.

After decision, the experiment branch does not merge its toy arm, controller costs,
plots, or thresholds into `reflect/`. A separate promotion commit may change only the
smallest measured shared representation/seam plus compatibility tests. Negative or
inconclusive evidence may require no shared-code change.

## Parallel implementation decomposition

The orchestrator first creates the canonical experiment skeleton, `base.yaml`, and
the exact local APIs above. It owns all shared documentation, configuration, phase
manifests, integration, freeze, and promotion decisions.

The first implementation wave uses non-overlapping ownership:

1. Arm worker: `src/arm.py` and `tests/test_arm.py` only.
2. Representation worker: `src/representations.py` and
   `tests/test_representations.py` only.
3. Timing worker: `src/timing.py` and `tests/test_timing.py` only.

After those interfaces pass review, the second wave uses:

1. Evaluation worker: `src/evaluate.py` and `tests/test_evaluate.py` only.
2. Command/integration worker: `run.py` plus separately assigned root command and
   artifact integration tests.
3. Independent reviewer: protocol, implementation diff, test evidence, and scope;
   no implementation ownership.

Workers do not edit shared config/docs concurrently, do not merge or reset, and do
not run latency-sensitive jobs in parallel. Pilot, freeze, confirmation, aggregation,
and real latency measurements are serial orchestrator operations.

## Failure and blocker handling

An implementation failure records exact command, status, relevant output,
environment, and one bounded remedy. A stack that fails its straightforward
stack is killed without importing a broader controller framework. Resource exhaustion
or insufficient precision yields `INCONCLUSIVE`, never `NOT_SUPPORTED`.

The only pre-execution blocker is a failed P3 MuJoCo/source gate. Final PD/IK/MPC
parameters are evidence-dependent but resolved autonomously inside the bounded pilot.
Confirmation seed values are intentionally unknowable until after freeze. Neither is
a reason to request routine user approval.

## Completion criterion

P4 is complete only when all six command stacks have a pilot disposition, every
surviving stack has an untouched confirmation disposition, all required artifacts and
plots validate, no more than two stacks are mechanically selected, promoted wire
representations are separately deduplicated, rejected stacks have explicit reasons,
and `INTERFACE_FINDINGS.md` states the bounded policy/controller seam justified by the
measurements without claiming representation-only causality.

## Review-fix note

The 2026-08-22 independent design review was incorporated before implementation. This
revision:

- replaced the dimensional MPC objective and maximum-speed-only candidates with a
  dimensionless integrated objective, feasible multi-magnitude candidates, and exact
  4 cm/6 cm move-versus-hold tests;
- made source age, delivery validity, response/rejection order, request cutoff, safe
  hold, pending response disposition, and replacement-after-expiry coherent with the
  canonical rollout bounds;
- separated four tuning seeds from one untouched final-four pilot evaluation and made
  P1 failure immediately `INCONCLUSIVE`/`STOPPED`;
- fixed pilot/confirmation counts, sharding, simulated duration, artifact budgets, and
  create-only validate-and-skip resumption;
- froze every IK, null-space, differential-IK, interpolation, and `dt_s` detail;
- defined exact aggregation domains, percentile/equality/missing-data and negative-
  control rules;
- clarified that P4 promotes at most two command stacks and separately deduplicates
  their wire representations;
- preserved semantic `current_phase` and defined coincident telemetry/policy
  observations and events; and
- made scenario generation and rejection variant-independent and frozen before any
  confirmation stack runs.

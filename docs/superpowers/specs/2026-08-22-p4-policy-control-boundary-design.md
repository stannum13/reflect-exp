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

P4 may promote no more than two command representations to Experiment 02. It also
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

Scenario generation rejects and deterministically resamples a direction when the
target radius is outside `[0.30, 0.70] m` or fixed-iteration IK cannot find a solution
at least `0.15 rad` inside every joint limit. Generation permits at most 32 candidate
directions per scenario; exhaustion invalidates the seed before execution rather than
silently changing the task.

Target success means Euclidean end-effector error is at most `0.025 m` continuously
for `0.10 s`. Recovery time for a displacement is the interval from target movement
to the first such dwell. Failure to recover within `2.0 s` is recorded as a censored
`2.0 s` value, never dropped as missing data.

## Shared inputs and fairness boundary

At each policy request every variant receives the same immutable pair:

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

P4 uses the existing `ActionRepresentation` values. The experiment-local variant ID
is stored in `ActionChunk.metadata["variant"]`; the global enum is not expanded merely
to distinguish one waypoint from a trajectory in the same value domain.

All chunks set `generated_time_ns` and `valid_from_ns` to response-delivery time and
expire after `ceil(2.5 * policy_period_ns)`. Their source observation ID and time bind
them to the stale snapshot used by the policy.

### P1 — Joint target

- representation: `JOINT_POSITION`;
- action shape: `(1, 3)`;
- policy: 12 iterations of damped least-squares IK from observed q to observed target,
  with damping `0.01` and fixed minimal-norm/null-space posture update;
- executor: hold the one q target, apply the common slew limiter, then PD.

P1 is the preregistered anchor.

### P2 — Joint trajectory

- representation: `JOINT_POSITION`;
- action shape: `(H, 3)`, where
  `H = ceil(0.8 / policy_period_s) + 1`;
- policy: form a straight Cartesian path from the observed end effector to the
  observed target and run the same fixed IK sequentially at every knot;
- executor: interpolate joint waypoints in time, apply the common slew limiter, then
  PD.

Only the prefix available during chunk validity is executed.

### P3 — Cartesian target

- representation: `EEF_TRAJECTORY`;
- action shape: `(1, 2)` containing one absolute XY target;
- policy: copy the observed target into the chunk;
- executor: at every low-level tick, use current q and damped differential IK to
  approach the held Cartesian target, then apply the common slew limiter and PD.

Using the one-knot `EEF_TRAJECTORY` wire value preserves the existing enum while
making target versus path cardinality explicit.

### P4 — Cartesian trajectory

- representation: `EEF_TRAJECTORY`;
- action shape: `(H, 2)` with the same horizon rule as P2;
- policy: form a straight Cartesian path from observed end effector to observed
  target;
- executor: interpolate the XY path and run current-q differential IK at each
  low-level tick, followed by the common slew limiter and PD.

### P5 — MPC objective

- representation: `MPC_GOAL`;
- action shape: `(1, 2)` containing the observed absolute XY target;
- metadata: joint, velocity, and torque limits; success radius; cost revision;
- controller: deterministic kinematic predictive sampling at 50 Hz, holding its q
  reference between planner ticks.

At each planner tick, the controller evaluates all 27 constant joint-velocity vectors
from `{-1.5, 0.0, 1.5}^3 rad/s` across ten `0.02 s` prediction steps. The cost is

```text
terminal_eef_squared_error
+ 0.01 * summed_joint_velocity_squared
+ 100.0 * summed_squared_joint_limit_violation
+ 0.02 * squared_change_from_previous_selected_velocity
```

Candidates are ordered lexicographically; the first minimum wins exact ties. The
first predicted q increment becomes the reference before the common slew limiter and
PD. This is a bounded local receding-horizon controller, not a production safety
layer or an imported MJPC implementation.

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
post-displacement target information.

## Virtual timing and injection order

`VirtualClock` is the only source of experiment time. No simulation path sleeps or
uses wall time to decide behaviour. A priority queue orders scheduled responses by
`(delivery_time_ns, request_sequence)`.

Each 2 ms tick performs this exact order:

1. apply a target movement scheduled for the current time;
2. if a policy tick is due, capture and record its observation and policy request;
3. schedule its deterministic response for request time plus injected latency;
4. deliver every response due at the current time, including a zero-latency response
   just requested in step 2;
5. reject a delivered chunk when its source observation ID is lower than the last
   accepted source observation ID; otherwise replace the active chunk;
6. decode the active chunk, compute the common PD command, step MuJoCo, and accumulate
   500 Hz metrics;
7. store a telemetry observation, executed `ControlReference`, and corresponding
   event every 10 ms; and
8. advance the virtual clock by 2 ms.

Policy observations and 100 Hz telemetry observations are distinguishable through
`current_phase`; only policy observations receive `POLICY_REQUESTED` events. Every
stored observation receives exactly one `OBSERVATION_RECEIVED` event.

Accepted chunks produce `CHUNK_ACCEPTED`; replacement first produces
`CHUNK_REPLACED` for the formerly active chunk and then `CHUNK_ACCEPTED` for the new
one. An expired arrival produces `CHUNK_REJECTED_EXPIRED`. A stale arrival produces
`POLICY_RESPONDED` followed by `CHUNK_REJECTED_OUT_OF_ORDER`. A dropped request has no
action chunk or response event; its request remains visible in the event stream.

## Experimental conditions

The core grid contains, for every variant and paired seed:

- policy rate: `5`, `10`, and `20 Hz`;
- injected policy latency: `0`, `100`, `300`, and `700 ms`; and
- target displacement count: one and two.

This is 24 equally weighted core conditions per variant and seed.

Two separate robustness probes run at `10 Hz`, `300 ms`, and two target movements:

1. drop exactly the first response requested at or after the first displacement;
2. delay that response by one policy period plus `2 ms`, causing the next response to
   arrive first and the delayed response to be rejected as out of order.

Drop and out-of-order are not crossed with the entire core grid. The smaller probe set
covers the canonical failures without an uninformative combinatorial expansion.

A stationary-target negative control runs at `10 Hz`, `300 ms` with no injected fault
for the first four confirmation seeds and every variant.

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
- named RNG algorithms and seeds; and
- real-compute measurement method.

Representation-specific IK, interpolation, residual composition, or predictive
control is part of the compared stack. No result is described as a controller-held-
constant representation effect.

## Metrics and estimands

### Primary estimand

For one episode, primary recovery is the mean censored recovery time over its one or
two target displacements. For one paired seed and variant, the primary value is the
equal-weight mean of the 24 core-condition episode values. One-move and two-move
conditions therefore receive equal condition weight rather than weighting the latter
twice.

The anchor is P1. The five primary contrasts are paired per-seed differences

```text
variant recovery - P1 recovery
```

so negative values are beneficial.

### Secondary metrics

P4 records:

- final, mean, and p95 Euclidean end-effector error in metres;
- p95 action age as execution time minus source observation time;
- joint jerk proxy as the norm of the third finite difference of executed q divided
  by `dt^3`, accumulated at 500 Hz;
- actuator saturation fraction over 500 Hz ticks;
- command discontinuity as
  `norm(q_ref[t] - q_ref[t-1])`, with mean and p95;
- unsafe/nonfinite command count;
- clamp fraction over control ticks; and
- real policy/controller compute p50 and p95 from serial `perf_counter_ns`
  measurements.

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

Draft completes when the six variants, simulator, metrics, scheduler, command, tests,
and artifact validation exist. Draft output carries no measurement claim.

### Pilot

Pilot uses eight paired seeds generated from a checked-in pilot seed root. The first
four are tuning seeds and the final four are validation seeds. Pilot permits at most
two protocol revisions and at most three configurations per variant per revision.

Initial parameters are the exact values in this design. A subsequent configuration
may change only one of these named scalar groups without changing architecture:

- common PD pair: `(60, 6)`, `(80, 8)`, or `(100, 10)`;
- IK damping: `0.001`, `0.01`, or `0.05`; or
- MPC smoothness coefficient: `0.01`, `0.02`, or `0.04`.

Common PD changes apply to every variant. No pilot may replace a failed controller
with a new stack.

A variant is killed during pilot when it has any dimensional mismatch, nonfinite
reference/state, joint-limit escape, unstable divergence, or fails to recover all
four validation seeds within `1.0 s` in the easiest `20 Hz`, `0 ms`, one-move
condition after its one straightforward implementation and bounded scalar tuning.
Killed variants are marked unsuitable for this task and receive no confirmation run.

### Freeze

After pilot, `configs/frozen.yaml` records and hashes:

- implementation Git SHA and clean-tree status;
- P2/P3 source-lock and compatibility hashes;
- MuJoCo package version and artifact hash;
- MJCF, scenario, metric, plotting, and gate revisions;
- all controller parameters and limits;
- surviving variants and pilot exclusions;
- pilot/tuning/validation seed manifests;
- confirmation seed count and RNG algorithm;
- exact bootstrap and multiplicity procedure; and
- every threshold below.

The implementation commit and frozen config are immutable for confirmation. Any
defect requiring code, config, metric, or threshold changes returns P4 to Draft with a
new protocol revision and a new unseen confirmation manifest.

### Confirmation

After freeze, the orchestrator generates 32 new paired confirmation seeds from a new
recorded RNG root that did not exist during implementation or pilot. Every surviving
variant runs the 24 core conditions, two robustness probes, and the negative control
specified above.

The analysis uses a deterministic 10,000-resample paired percentile bootstrap over
seed-level primary values. The five contrasts against P1 form one multiplicity family
and use Bonferroni-adjusted 99% intervals. Timeouts are the censored `2.0 s` value.
Crashes, missing artifacts, or invalid negative controls invalidate the affected seed;
more than one invalid seed or any systematic variant-specific loss makes the result
`INCONCLUSIVE` rather than silently excluding data.

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
  pilot-validation value.

The stationary negative control must retain end-effector error at or below `0.025 m`
from `t=1.5 s` through episode end and must create no recovery event. Failure
invalidates confirmation rather than counting against a scientific variant.

A non-anchor variant is **superior** only when the upper endpoint of its adjusted 99%
interval is at most `-0.10 s` and every viability/safety/smoothness gate passes. It is
**noninferior and eligible** when the upper endpoint is at most `+0.10 s` and every
gate passes. Otherwise it is rejected.

Promotion is mechanical and limited to two variants:

1. rank superior candidates by the upper endpoint of their adjusted interval;
2. if fewer than two superior candidates exist, fill remaining slots with the lowest
   upper-bound noninferior candidates, including stable P1 as the fallback;
3. break an exact numerical tie by fixed order P1 through P6; and
4. promote no variant that fails an absolute or safety/smoothness gate.

For selection ranking only, stable P1 has a self-contrast and upper endpoint of zero.
This makes a beneficial but not superior non-anchor rank before P1, and a positive-
delta merely noninferior candidate rank after P1.

If P1 fails its absolute gate, the comparative decision is `INCONCLUSIVE` and no
non-anchor representation is promoted from that confirmation.

The Experiment 01 scientific result is:

- `SUPPORTED` when at least one non-anchor is superior;
- `NOT_SUPPORTED` when the lower endpoint of every valid non-anchor interval is
  greater than `-0.10 s` (thereby excluding the minimum benefit) and all controls and
  precision requirements are valid; or
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
CommandVariant
PolicyInput
ExecutorState
emit_chunk(variant, policy_input, config) -> ActionChunk
reference_for_tick(variant, chunk, q, dq, time_ns, state, config)
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
run_episode(variant, condition, seed, config) -> RolloutRecord
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
```

`--dry-run` validates and prints the exact condition manifest without constructing
MuJoCo. `--max-episodes` truncates the sorted manifest and is smoke-only unless it
equals the frozen phase count. `--headless` is required for evidence-bearing runs.
The only new root target is `make exp01`, which runs the frozen command when it exists
and otherwise runs the base pilot command.

## Artifacts

Each `(phase, seed, variant, condition)` writes one create-only canonical rollout
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

## Tests and verification

Unit and property tests cover:

- MJCF dimensions, timestep, joint/torque limits, and headless construction;
- analytic FK against the MuJoCo site and Jacobian against finite differences;
- scenario reproducibility, reachability, and bounded rejection;
- exact shapes, finite values, value domains, metadata, validity intervals, and
  bounds for all six variants;
- proof that every variant receives identical policy information and no controller
  reads the live target;
- joint/Cartesian interpolation, IK damping, null-space rule, predictive candidate
  order/cost, residual bound, slew limit, torque clamp, and PD behaviour;
- exact VirtualClock ordering for 0/100/300/700 ms latency;
- one dropped response, one forced out-of-order response, expiry, replacement, and
  stale rejection;
- repeated-run determinism for virtual times, simulator traces, metrics, and
  deterministic artifact fields;
- recovery dwell/censoring, error, action-age, jerk, discontinuity, saturation, and
  clamp metrics on hand-calculated fixtures;
- paired bootstrap, 99% multiplicity intervals, missing-data rules, threshold
  boundaries, tie ordering, result classification, and two-variant promotion cap;
- one zero-latency headless smoke episode for every variant;
- canonical rollout write, load, validation, event lifecycle, and replay;
- SVG determinism and required plot labels;
- CLI config validation, dry run, headless enforcement, seed/output/max-episode
  handling, and create-only output; and
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
environment, and one bounded remedy. A representation that fails its straightforward
stack is killed without importing a broader controller framework. Resource exhaustion
or insufficient precision yields `INCONCLUSIVE`, never `NOT_SUPPORTED`.

The only pre-execution blocker is a failed P3 MuJoCo/source gate. Final PD/IK/MPC
parameters are evidence-dependent but resolved autonomously inside the bounded pilot.
Confirmation seed values are intentionally unknowable until after freeze. Neither is
a reason to request routine user approval.

## Completion criterion

P4 is complete only when all six variants have a pilot disposition, every surviving
variant has an untouched confirmation disposition, all required artifacts and plots
validate, no more than two representations are mechanically selected, rejected
representations have explicit reasons, and `INTERFACE_FINDINGS.md` states the bounded
policy/controller seam justified by the measurements without claiming
representation-only causality.

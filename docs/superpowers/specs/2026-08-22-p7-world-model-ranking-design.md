# P7 World-Model Candidate-Ranking Experimental Design

**Date:** 2026-08-22

**Status:** Approved design; no implementation plan

**Scope:** Reflect Lite Experiment 06

## 1. Decision and authority boundary

Experiment 06 tests whether compact learned prediction improves the ordering and
selection of eight fixed planar-pushing candidates. NumPy supplies a deterministic
precursor used for generator/model development, training, tuning, validation, and
physical sanity checks. It does not produce canonical co-primary evidence.

The P3-pinned MuJoCo package/version/distribution artifact, source lock, and compatibility
decision are mandatory prerequisites. P3 does not supply or pin Experiment 06 model
bytes. Section 13.1 instead defines the experiment-local deterministic Push-T MJCF
generator and binds every generated model digest to the precursor and evidence
protocols. MuJoCo is the sole exact rollout ground truth
for the disjoint pilot that fits only permitted output/calibration values and margins,
and for unseen confirmation.
Canonical W2, actual candidate costs, rank correlation, selection regret, safety
labels, scientific decisions, and runtime authority all use pinned MuJoCo outcomes.
This follows the program's explicit MuJoCo ground-truth choice
(`Reflect Lite Research Program.md:1909-1915`) and prevents a simplified NumPy contact
model from silently changing the claim.

The benchmark remains CPU-only, local, and checkpoint-free. It does not test general
manipulation, real-R1 transfer, image plausibility, latent MPC, CEM/MPPI, foundation
encoders, or online learning (`Reflect Lite Research Program.md:1888-1930`).

## 2. Alternatives and trade-offs

### A. NumPy-only exact benchmark

This is cheapest and maximally deterministic, but it conflicts with the named MuJoCo
ground truth and could grant authority from an oversimplified collision model. It is
retained only as a precursor and negative-control simulator.

### B. MuJoCo for all development and evidence

This removes simulator shift but makes every data-generation and debugging loop depend
on the heavier P3 environment. It is valid but needlessly expensive before candidate,
leakage, model, and artifact contracts stabilize.

### C. Frozen precursor, then NumPy selection and MuJoCo pilot/confirmation — selected

NumPy provides cheap exhaustive development data and deterministic contract tests. A
pre-precursor contract freeze prevents either simulator from redefining the task after
results. A disjoint MuJoCo pilot validates the selected model path, permits only the
predeclared output-head refit/calibration, and sets margins/resources before one common
evidence freeze. Unseen MuJoCo confirmation then answers the claim. The extra
transition makes simulator authority explicit and permits negative NumPy validity
results to stop work before expensive MuJoCo evidence.

## 3. Scientific unit, world, and candidates

### 3.1 Scene and anchor unit

The analysis unit is a `scene_seed`. One seed owns physical parameters, probe rollout,
four ordered anchor snapshots, all adjacent frames, all eight branches per anchor,
and all renderings. Anchor metrics average within scene first; paired inference uses
scene-level values. No frame, candidate, or rendering descendant crosses a split.

The bounded 2D world has a velocity-controlled circular end effector, one movable
disk or rectangle, a target pose, zero or one wall/obstacle, bounded workspace, and
randomized mass/friction/geometry. NumPy and MuJoCo implement one frozen state/action/
cost mapping, but only MuJoCo outcomes are canonical truth.

### 3.2 Stable identities

IDs are globally unique within the experiment:

```text
scene_id    = exp06/scene/<16-lowercase-hex-seed>
anchor_id   = <scene_id>/anchor/<zero-padded-anchor-index>
strategy_id = DIRECT | LEFT_EDGE | RIGHT_EDGE | BELOW | DIAGONAL |
              RETREAT_REPOSITION | SLOW_CONSERVATIVE | HOLD
candidate_id = <anchor_id>/candidate/<strategy_id>
prediction_id = <candidate_id>/prediction/<64-lowercase-hex-model-sha256>
```

`strategy_id` is the reusable semantic strategy; `candidate_id` is the globally
unique instance. Every prediction, truth row, selection, action row, and event carries
both. `prediction_id` is globally unique because its candidate and generating model are
identity-bound, including across configurations and refitted checkpoints; its final
component must equal the row's complete `model_sha256`. W4F/W5F selections reference
the chosen raw W4/W5 or W1 prediction ID
rather than inventing a composition prediction. IDs cannot be derived from labels or
row positions.

### 3.3 Exact K=8 action generation

At every anchor the deterministic waypoint controller emits exactly one one-second
planar velocity chunk for each strategy:

1. `DIRECT`: approach from target-opposite contact and push toward target.
2. `LEFT_EDGE`: push through the object's local left edge.
3. `RIGHT_EDGE`: mirrored right-edge push.
4. `BELOW`: approach from the negative world-y support side, then push.
5. `DIAGONAL`: use the deterministic target-facing corner.
6. `RETREAT_REPOSITION`: retreat, reposition, then push in frozen phase fractions.
7. `SLOW_CONSERVATIVE`: direct strategy with the frozen speed multiplier.
8. `HOLD`: zero velocity for the whole horizon.

Each action has two digests. `action_content_sha256` covers only the canonical
little-endian float64 command shape/bytes, `dt_s`, horizon, and command limits; it is
independent of scene, anchor, strategy, candidate, and row position. `action_sha256`
is the identity-bound cross-link digest over `action_content_sha256`, strategy ID,
candidate ID, scene ID, and anchor ID. The eight candidates must have eight distinct
content digests and eight bytewise-distinct command trajectories; distinct IDs cannot
make duplicate commands valid. Before any branch runs, an independent regeneration
pass reconstructs all actions from the sealed anchor/config and requires byte equality
and both digest equalities. Duplicate content, missing/reordered candidates, or
nondeterministic regeneration makes the scene bundle `INVALID`; candidates are never
dropped, perturbed, or resampled. This is the program's meaningful, non-Gaussian K=8
taxonomy (`Reflect Lite Research Program.md:1943-1956`).

## 4. NumPy precursor validity gate

Before the first validity-gate run, a checked-in precursor protocol freezes the task
and scene distributions, NumPy equations and MuJoCo state/action mapping, candidate
factory/controller/timing/limits, K=8 IDs/order, actual/predicted cost components and
weights, success/safety labels, W0 seed rule, the complete W1 formula/weights/ties,
split sizes/roots, validity tolerances, and finite model/PCA configuration grids. The
finite grids contain exactly three W3 configurations, three W4 configurations, and
three W5 configurations, covering every allowed feature/degree/regularization/ensemble
or channel/PCA-dimension/tolerance/latent-transition choice; neither
NumPy outcomes nor MuJoCo pilot may add a choice. This is a contract freeze, not the
later evidence freeze: learned coefficients, calibration values, effect margins, and
measured resource ceilings do not exist yet.

The NumPy simulator uses fixed-step semi-implicit integration, deterministic contact
ordering, explicit terminal reasons, and immutable snapshots. It must pass all three
gate classes before data may train a model:

1. **Analytic invariants:** HOLD preserves a zero-velocity free state; no-contact
   constant-velocity motion matches its closed form within the frozen tolerance;
   wrapped orientation, clipping, and cost components match hand calculations.
2. **Physical invariants:** damping/friction never adds kinetic energy in an
   unforced step; contact impulse opposes penetration; post-step penetration remains
   within tolerance; mirrored scenes/actions produce mirrored states/costs; every
   branch remains finite and inside declared bounds.
3. **Step-halving convergence:** every strategy in a frozen validation grid runs at
   `dt` and `dt/2`; endpoint state, each cost component, collision/failure label, and
   candidate ordering must remain inside pre-precursor frozen tolerances. Order uses Kendall
   disagreement count with average-rank ties.

The validity grid is exactly 80 cases per protocol revision: 16 analytic hand cases
(eight free-motion/HOLD and eight wrap/clip/cost cases), 24 physical cases (all eight
strategies in each of free, single-contact, and obstacle-contact fixtures), and 40
step-halving cases (all eight strategies in one frozen prototype from each of the five
strata). No random or adaptively added gate case is allowed. One create-only
`numpy-validity` aggregate bundle contains all inputs, per-step summaries, endpoints,
labels, order comparisons, and hand expectations; it has a 64 MiB and 60-minute ceiling
per revision. A case timeout or cap breach fails the gate rather than disappearing.

The 80 cases are algorithmically complete and admit no plan-time choices. All fixture
states use float64, `dt=0.002`, gravity zero, workspace `[-1,1]^2`, zero unlisted
velocities, disk geometry unless stated, and the Section 13.1 equations. Analytic case
IDs and literal inputs are:

| IDs | Inputs | Hand expectation |
|---|---|---|
| `A00..A03` | no bodies/contact/friction; point starts `(0,0)` with velocity respectively `(0.10,0)`, `(0,0.10)`, `(-0.10,0.05)`, `(0.05,-0.10)`; steps `1,10,50,125` respectively | `p_n=p_0+n*dt*v_0`, byte-equal unchanged velocity |
| `A04..A07` | free disk center respectively `(0,0)`, `(0.20,-0.10)`, `(-0.25,0.15)`, `(0.30,0.30)`; HOLD; zero velocity; steps `1,10,50,125` | every state byte-equal to its initial state and zero energy |
| `A08,A09` | wrap input `pi+0.25`, `-pi-0.25` | `-pi+0.25`, `pi-0.25` |
| `A10,A11` | unclipped command `(0.30,-0.30)`, `(-0.26,0.10)` | `(0.25,-0.25)`, `(-0.25,0.10)` |
| `A12..A15` | `(position_error,orientation_error,collision,energy,failure,success)` respectively `(0,0,0,0,0,1)`, `(0.10,0.20,0,0.50,1,0)`, `(0.20,-0.30,1,1.00,1,0)`, `(0.05,pi+0.25,0,0.25,0,1)` | literal Section 13.1 weighted-cost formula after wrapping orientation |

Physical cases are the Cartesian product of all eight strategies in Section 3.3 with
the following three base fixtures, ordered `P00..P23` by fixture then frozen strategy
order. Each case also executes the exact world-x-axis reflection of its already
generated base scene and command bytes (negate every y position/velocity, yaw, angular
velocity, and command-y component) inside the same case. This is a physics-invariance
probe, not a second candidate-factory call or semantic strategy relabel. It requires
the reflected endpoint, identical scalar cost/labels, and reflected impulse vectors;
this subexecution does not create another case.

| Fixture | `eef`, object, target | physical parameters and obstacle |
|---|---|---|
| `FREE` | `(-0.20,0)`, disk `(0,0,0)`, `(0.35,0,0)` | mass `1.0`, friction `0.50`, radius `0.065`, no obstacle |
| `SINGLE_CONTACT` | `(-0.13,0.02)`, rectangle `(0,0,0.20)`, `(0.32,0.08,0.10)` | mass `1.1`, friction `0.45`, half-extents `(0.060,0.050)`, no obstacle |
| `OBSTACLE_CONTACT` | `(-0.20,-0.05)`, disk `(0,0,0)`, `(0.35,0.05,0)` | mass `0.9`, friction `0.55`, radius `0.060`; segment `(0.12,-0.16)` to `(0.12,0.16)`, thickness `0.04` |

Step-halving cases are all eight strategies in each literal prototype below, ordered
`S00..S39` by prototype then strategy. `eef=(-0.20,0)`, object center `(0,0)`, target
`(0.35,0.05,0.10)`, and zero velocities are common. Each runs the same one-second
candidate at `0.002` and `0.001`; the latter uses two physics steps per original step
while the 50 command rows retain their exact 0.02-second boundaries.

| Prototype | mass | friction | geometry | obstacle |
|---|---:|---:|---|---|
| `ID` | `1.00` | `0.50` | disk `r=0.065` | absent |
| `MASS_OOD` | `1.50` | `0.50` | disk `r=0.065` | absent |
| `FRICTION_OOD` | `1.00` | `0.825` | disk `r=0.065` | absent |
| `GEOMETRY_OOD` | `1.00` | `0.50` | rectangle half-extents `(0.0875,0.035)` at yaw `0.20` | absent |
| `OBSTACLE_OOD` | `1.00` | `0.50` | disk `r=0.065` | `CENTER_BARRIER`, endpoints `(.175,.025) +/- .25*(-.05,.35)/sqrt(.125)`, thickness `0.04` |

The checked-in validity manifest contains exactly these IDs, literal values, derived
hand expectations, and a SHA-256 of this table's canonical transcription. Unknown,
duplicate, reordered, or derived-from-random cases fail before simulation.

Every invariant and candidate must pass. A failure makes the NumPy precursor
`INVALID` and P7 `STOPPED`; moving directly to MuJoCo would require a new reviewed
protocol, not an automatic workaround. Passing this gate still grants no authority.

## 5. Data partitions and leakage prevention

### 5.1 NumPy development partitions

NumPy uses 96 training, 24 tuning, and 24 validation scene seeds, with four anchors
and K=8 branches per scene. Training fits preprocessing and models. Tuning chooses
among the already frozen finite configuration grid. Validation mechanically selects
one W3/W4/W5 checkpoint and the predeclared calibration/fallback *method*; it cannot
fit the final calibration map or threshold, change W1, or add a configuration. These
144 seeds and their RNG ancestors are permanently excluded from MuJoCo
pilot/confirmation.

### 5.2 MuJoCo evidence partitions

After NumPy selection, a disjoint MuJoCo pilot uses five strata with eight scene seeds
per stratum, 40 total. Within each stratum, the first four sorted scene IDs are
adaptation seeds and the final four are untouched pilot-evaluation seeds. NumPy
preprocessing, feature maps, PCA, model structures, regularization, and W1 freeze before
MuJoCo pilot. On adaptation seeds only, permitted W3/W4/W5 linear output coefficients
are refit once on the union of NumPy training and MuJoCo adaptation rows. W3 may refit
exactly `position,orientation,collision,energy,terminal_failure,unsafe,success`; W4 may
refit exactly `state_delta,collision,terminal_failure,unsafe,success`; and W5 may refit
exactly `position,orientation,collision,energy,terminal_failure,unsafe,success`. W5
`latent_next` coefficients/intercepts, every feature map, input preprocessing, PCA, and
all other selected-model members remain byte-identical to the NumPy-selected model.
Calibration maps
and fallback thresholds fit adaptation seeds only under the already selected method.
No other parameter may use MuJoCo adaptation. Pilot-evaluation seeds validate the
state/action mapping and set only margins/resource ceilings once; they cannot trigger
refit, recalibration, model selection, task/cost/W1 changes, or exclusions. The whole
pilot is labelled exploratory and cannot support a claim.

Only after implementation, experiment-local model, calibration, P3 package/runtime
provenance, protocol, and MuJoCo pilot
hashes freeze does the orchestrator generate a new unseen MuJoCo confirmation root.
Confirmation has five strata with 16 scene seeds each, 80 total. Confirmation data do
not exist before freeze and cannot change parameters, preprocessing, models, cost,
fallback, exclusions, or gates.

The five strata and their primary weights are exact:

| Stratum | Definition | Weight |
|---|---|---:|
| ID | all physical parameters inside training support | 0.20 |
| MASS_OOD | mass outside training support; other factors ID | 0.20 |
| FRICTION_OOD | object/table friction outside support; others ID | 0.20 |
| GEOMETRY_OOD | withheld disk/rectangle scale/shape cell; others ID | 0.20 |
| OBSTACLE_OOD | withheld obstacle layout cell; others ID | 0.20 |

Within stratum, anchors and scenes have equal weight. Overall scene metrics are first
averaged within stratum, then combined with the fixed 0.20 weights; no stratum is
weighted by row count.

### 5.3 Fail-closed ancestry rules

The split manifest records RNG root/stream, scene seed, probe seed, rollout, anchor,
candidate, parameter cell, state/render hashes, both action digests, simulator, and
partition. All
adjacent frames, candidates, augmentations, and simulator ports descended from one
scene remain together. Any shared ancestor or content hash across train, tune,
validation, MuJoCo pilot, or confirmation makes the dataset `INVALID`.

Train-only statistics include normalization, feature maps, PCA, and ensemble resamples;
every fit row has weight exactly `1.0` and no class weighting is permitted. Tuning
mechanically ranks only frozen-grid configurations by the frozen key; validation
mechanically selects NumPy checkpoints and the declared
fallback method by the same fixed rule. MuJoCo adaptation alone performs the one
predeclared output-coefficient refit and calibration/threshold fit. MuJoCo pilot
evaluation sets only margins and resource ceilings. Confirmation is read once after
the evidence freeze.

## 6. W0-W5 and exact prediction envelope

Every selector receives the same ordered candidate IDs/actions and declared current
input. W0/W1/W3/W4/W5 cannot open simulator APIs, actual outcomes, W2 scores, or truth
paths. Each process receives only one sealed, variant-specific selector-input
descriptor: W0 gets IDs/actions; W1 gets only c/g/e/object shape plus obstacle geometry
and actions; W3/W4 get the exact ordered privileged vector and actions; and W5 gets
only its raster/actions. Other projections have no inherited
descriptor or discoverable path. For each complete MuJoCo pilot-evaluation or
confirmation phase, all selectors for all declared scenes validate, seal, exit, and
enter one create-only phase selector freeze before canonical branch truth for any
scene is materialized. Only after that global freeze does the orchestrator materialize
phase truth-source descriptors and permit per-scene pinned-MuJoCo truth/scoring. No
selector process is ever launched again for that phase. Consequently a selector is
never alive while current-phase truth exists, and no current- or prior-phase truth
descriptor/path is visible or reachable inside its OS sandbox. Prior published truth
may remain in the parent namespace solely for audit and scoring. NumPy
training and MuJoCo adaptation are the
only phases allowed to consume their own declared training targets; their fitted
outputs seal before any evaluation selector runs.

Omitting a path argument and setting `close_fds` are not the isolation boundary. P7
implements an experiment-local `p7-selector-fs-v1` sandbox with the same host-contract
terminology as P6 but imports no P6 code or generic sandbox framework. Linux uses a
checked-in Landlock ruleset plus seccomp filter; macOS uses a checked-in Seatbelt
profile. The exact policy paths are
`experiments/06_world_model/sandbox/p7-selector-fs-v1.linux.json` and
`experiments/06_world_model/sandbox/p7-selector-fs-v1.sb`. Their source, compiled
policy bytes, selected OS key, kernel enforcement probe, interpreter, and selector
zipapp hashes freeze before MuJoCo adaptation. An unavailable backend, policy mismatch,
or failed denial probe makes P7 `BLOCKED` before any selector.

The parent launches each selector from an empty mode-0700 broker working directory.
The only experiment data inherited are one prevalidated read-only projection descriptor
and one create-exclusive absent output descriptor in fixed descriptor slots 3 and 4.
The sandbox permits read-only interpreter/dependency/selector-zipapp mappings and those
descriptors, but denies repository/result/private-root traversal, all other file opens,
descriptor discovery, network, process creation, ptrace, and simulator loading. After
installing the policy the child drops setup capability. Selector callbacks receive
decoded immutable values, never a descriptor, path, loader, environment handle, or
generic file API.

MuJoCo adaptation truth is generated into regular files opened with
`O_CLOEXEC|O_NOFOLLOW` in a broker-private mode-0700 directory, fsynced, reopened
read-only, and unlinked before fitting. The privileged adaptation controller alone keeps
those anonymous descriptors while it fits the predeclared output heads/calibration and
seals the adapted aggregate. No descriptor is inherited by a selector. It then closes
them, so no adaptation truth path or descriptor exists during pilot-evaluation pass S.
After the phase-global selector freeze, pass T deterministically regenerates the 20
adaptation source bundles from the frozen manifest, requires byte/hash equality with the
adaptation aggregate's committed input hashes, and publishes them for audit before
pilot-evaluation truth. This regeneration cannot refit or alter any sealed output.

Hostile pilot-evaluation and confirmation tests run after earlier truth has existed.
They enumerate arguments, environment, cwd/parents, imports, and descriptors and attempt
absolute, relative, symlink, hard-link, `/proc`/`/dev/fd`, inherited-FD, socket,
subprocess, ptrace, repository-result, private-root, current/prior truth, scorer,
aggregate, and decision access. Every attempt must receive an OS denial while the
declared projection read and output write still succeed.

### W0 — random

A fresh per-anchor PCG64 generator chooses uniformly from K=8. Its 128-bit seed is the
first 16 bytes, interpreted big-endian, of
`SHA256(canonical_json(["exp06-w0-v1", w0_root_hex, scene_id, anchor_id]))`; it makes
exactly one `Generator(PCG64(seed)).integers(0,8,endpoint=False,dtype=uint64)` call and
maps that integer into frozen candidate order. PCG64 is treated as a stateful bit
generator, not called counter-based. W0 emits a selection, not a prediction order.

### W1 — strong heuristic and fallback

W1 estimates nominal endpoint, orientation, straight-line collision risk, contact-side
alignment, and known action energy without simulation or learned parameters. Its
weights and tie rule freeze. W1 is both the anchor baseline and mandatory fallback.

### W2 — pinned MuJoCo exact oracle

Canonical W2 restores the pinned MuJoCo anchor snapshot, executes all eight candidates,
computes canonical actual cost, and chooses a true minimum. It is labelled
`ORACLE_EXACT_MUJOCO`, has zero regret by construction, is never deployable, and cannot
supply a feature or prediction. An exact actual-cost tie selects lowest candidate ID.
NumPy's analogous pilot oracle is labelled
`PRECURSOR_ORACLE_NUMPY` and never enters canonical metrics.

### W3 — non-dynamics learned baseline

Regularized multi-head ridge uses current privileged state plus endpoint displacement,
path length, velocity moments, contact-side encoding, strategy ID, and obstacle-line
intersection. It predicts scalar envelope components without predicting future state
or latent.

### W4 — privileged-state dynamics

A deterministic bootstrap ensemble of the frozen polynomial ridge configurations
consumes current state plus the complete resampled action chunk and predicts horizon
state delta and probability heads. Position/orientation terms are derived from its
predicted state; action energy is derived from the known chunk.

### W5 — observation-latent dynamics

A deterministic 64-by-64 multichannel render is encoded by train-only PCA. A ridge
latent transition consumes current latent plus the complete action chunk and predicts
future latent and scalar component heads. No pixel/reconstruction loss enters ranking
or gates; no checkpoint or foundation encoder is downloaded
(`Reflect Lite Research Program.md:1980-1984`).

### 6.1 PCA canonicalization

PCA uses float64 centered training rows in canonical sample/hash order. Singular values
sort descending. For a singular-value group under the Section 6.4 tie tolerance,
project standard pixel basis vectors in ascending pixel index into the tied subspace and apply deterministic
modified Gram-Schmidt, accepting the first vector above the frozen norm tolerance,
until the subspace is spanned. For each final component, find the maximum-absolute
loading; the lowest pixel index breaks ties, and its sign is forced positive. Components,
means, singular values, tolerance, and input hashes are serialized. This canonicalizes
both signs and equal-singular-value ordering across repeated CPU runs.

### 6.2 Prediction envelope and scalar cost

W1/W3/W4/W5 emit one exact envelope per candidate:

```text
prediction_id, observation_id, scene_id, anchor_id, candidate_id, strategy_id,
action_content_sha256, action_sha256,
model_id, model_sha256, horizon_s,
predicted_progress,
predicted_position_error_m, predicted_orientation_error_rad,
predicted_collision_probability, predicted_action_energy,
predicted_failure_probabilities, predicted_success_probability,
predicted_state_sha256 | null, predicted_latent_sha256 | null,
uncertainty, inference_ms, predicted_cost
```

`predicted_progress` is finite. `predicted_failure_probabilities` has exactly the
sorted keys `collision`, `terminal_failure`, and `unsafe`; every probability is finite
in `[0,1]`. Errors, energy, uncertainty, and inference time are finite and
nonnegative. `predicted_collision_probability` must equal the `collision` map entry.
The scalar formula is identical across W1/W3/W4/W5:

```text
predicted_cost =
    w_position * predicted_position_error_m^2
  + w_orientation * wrapped(predicted_orientation_error_rad)^2
  + w_collision * predicted_collision_probability
  + w_energy * predicted_action_energy
  + w_failure * predicted_failure_probabilities["terminal_failure"]
  - w_success * predicted_success_probability
```

Actual MuJoCo cost substitutes actual component values and binary collision/failure/
success indicators into the same formula. W3/W5 predict every scalar component
directly; W4 derives state-dependent errors from predicted state; W1 computes its
declared analytic estimates. Candidate order is `(predicted_cost ascending,
uncertainty ascending, candidate_id ascending)`. No variant-specific cost or tie rule
is allowed.

`prediction_id` is exactly the Section 3.2 identity and must match the row's candidate
and complete model hash. W1 uses `model_id=W1`, its frozen configuration hash as `model_sha256`, uncertainty
`0.0`, and null state/latent hashes. W3 uses null state/latent hashes. W4 requires a
predicted-state hash and null latent hash; W5 requires a predicted-latent hash and null
state hash. W4's decoded `predicted_state` is exactly ten float64 values in order
`eef_x,eef_y,eef_vx,eef_vy,object_x,object_y,object_yaw,object_vx,object_vy,object_omega`
at the one-second horizon. It is current dynamic state plus the fitted delta, with yaw
wrapped by the frozen rule. W5's decoded `predicted_latent` is exactly 16, 24, or 32
float64 values for selected CFG01, CFG02, or CFG03 respectively, in canonical PCA
component order. The envelope validator rejects any other nullability, shape, or order.

### 6.3 Exact shared-contract adapter

Before a prediction row can seal, `EnvelopeAdapter.to_shared` constructs the current
immutable `reflect.types.WorldModelPrediction` with this exact mapping:

```text
observation_id                  <- envelope.observation_id
candidate_id                    <- envelope.candidate_id
horizon_s                       <- envelope.horizon_s
predicted_progress              <- envelope.predicted_progress
predicted_success_probability   <- envelope.predicted_success_probability
predicted_failure_probabilities <- the exact three-key mapping above
predicted_state                 <- decoded vector for W4, else null
predicted_latent                <- decoded vector for W5, else null
uncertainty                     <- envelope.uncertainty
inference_ms                    <- envelope.inference_ms
```

The adapter calls `validate_contract` and then round-trips a freshly reconstructed
contract. W4/W5 vectors live in `prediction-vectors.npz`; the member key is
`sha256(prediction_id).hexdigest() + ".npy"`, and `predictions.parquet` stores that key.
The validator recomputes the key, rejects duplicate IDs/keys, and requires exactly one
vector member for every W4/W5 row and none for W1/W3. Their canonical little-endian
float64 C-order bytes hash to the envelope state/latent digest. The sidecar stores every
remaining experiment-local
cost component. A canonical `WORLD_MODEL_PREDICTED` payload carries integer
`observation_id`, string `prediction_id`, candidate/model/action IDs and hashes, and the SHA-256 of the complete
envelope row plus referenced vector. `WORLD_MODEL_SELECTED` carries the same integer
observation ID, selected `prediction_id`, and selected row digest. Bundle validation
reconstructs the shared
contract before accepting either event. `RolloutRecord` remains unchanged; the exact
contract/vector sidecars are bundle-owned optional evidence, not invented rollout-core
fields.

### 6.4 Deterministic numeric and encoding profile

All processes use the pinned lock and CPU-only environment with `PYTHONHASHSEED=0`,
`LC_ALL=C`, `TZ=UTC`, and `OMP_NUM_THREADS=MKL_NUM_THREADS=OPENBLAS_NUM_THREADS=1`;
unknown BLAS/thread settings fail preflight. NumPy runs float64 with `seterr(all="raise")`.
Inputs, rows, feature columns, ensemble resamples, and reductions use frozen hash order;
no unordered mapping/set iteration or parallel reduction may affect bytes.

PCA clusters singular values when `abs(s_i-s_j) <= 1e-12*max(1,s_0)` and applies the
projected-standard-basis construction in Section 6.1 to the whole cluster. Thus a
numerically split tied subspace cannot evade canonicalization. The implementation
records NumPy/PyArrow/Python versions, BLAS identity, thread profile, and CPU
architecture; a mismatch is a new protocol environment, never a resume.

Canonical JSON is UTF-8, NFKC, sorted-key, compact-separator, finite-only, and ends in
one newline. Integers use base-10 without leading zeros; float negative zero normalizes
to `0.0` and other floats use CPython 3.11's shortest round-trip representation with
lowercase `e` and no `+` exponent sign. Parquet uses the pinned PyArrow version, explicit schema/column order,
frozen row order, one full-table row group, no dictionary encoding, no compression,
no statistics, and data-page version 1.0. Canonical NPZ is a lexicographically ordered
ZIP_STORED archive: every member is an explicit little-endian C-order `.npy` v2.0
stream with timestamp `1980-01-01T00:00:00`, mode `0600`, no extra/comment fields, and
no duplicate names. Golden fixtures require byte identity across two fresh processes;
any mismatch invalidates the environment before evidence generation.

### 6.5 Exact sidecar schemas and digest preimages

Every Arrow field below is nonnullable unless marked `?`; strings are UTF-8 `string`,
hashes are validated lowercase 64-hex strings, and no dictionary or extension type is
permitted. Exact schemas and column order are:

```text
anchors.parquet:
  scene_id:string, anchor_id:string, observation_id:int64, anchor_index:int16,
  source_time_ns:int64, generator_snapshot_sha256:string,
  state_member_key:string, privileged_vector_sha256:string
candidate_actions.parquet:
  scene_id:string, anchor_id:string, candidate_id:string, strategy_id:string,
  dt_s:float64, horizon_s:float64, command_rows:int16,
  commands:fixed_size_list<float64>[100],
  command_min:fixed_size_list<float64>[2], command_max:fixed_size_list<float64>[2],
  action_content_sha256:string, action_sha256:string
predictions.parquet:
  prediction_id:string, observation_id:int64, scene_id:string, anchor_id:string,
  candidate_id:string, strategy_id:string, action_content_sha256:string,
  action_sha256:string, model_id:string, model_sha256:string, horizon_s:float64,
  predicted_progress:float64, predicted_position_error_m:float64,
  predicted_orientation_error_rad:float64, predicted_collision_probability:float64,
  predicted_action_energy:float64, failure_collision:float64,
  failure_terminal:float64, failure_unsafe:float64,
  predicted_success_probability:float64, predicted_state_sha256:string?,
  predicted_latent_sha256:string?, vector_member_key:string?, uncertainty:float64,
  inference_ms:float64, predicted_cost:float64
selections.parquet:
  selector_id:string, observation_id:int64, scene_id:string, anchor_id:string,
  selected_prediction_id:string?, candidate_id:string, strategy_id:string,
  action_content_sha256:string, action_sha256:string, selected_model_id:string?,
  selected_row_sha256:string, used_fallback:bool, fallback_reason:string?
candidate_truth.parquet:
  scene_id:string, anchor_id:string, candidate_id:string, strategy_id:string,
  action_content_sha256:string, action_sha256:string, model_sha256:string,
  terminal_position_error_m:float64, terminal_orientation_error_rad:float64,
  collision:bool, action_energy:float64, terminal_failure:bool, success:bool,
  unsafe:bool, actual_cost:float64, w2_selected:bool
evaluation-predictions.parquet:
  partition:string, scene_id:string, anchor_id:string, candidate_id:string,
  model_id:string, model_sha256:string, prediction_row_sha256:string,
  actual_cost:float64, predicted_cost:float64, selected:bool
```

Rows sort by `(scene_id,anchor_id,candidate_id,model_id)` after omitting inapplicable
suffixes: anchors stop at anchor, actions/truth at candidate, and selections sort by
selector then candidate. `observation_id` is exactly `4*scene_ordinal+anchor_index`, with
zero-based manifest `scene_ordinal` and `anchor_index`; anchors require a bijection and
every prediction, selection, event, and shared contract uses that integer. W0/W2 alone
have null prediction/model IDs; W1 fallback has `used_fallback=true` and a nonnull
reason; all other selection nullability is rejected. Prediction vector nullability
remains exactly Section 6.2. Arrow metadata is empty.

`action_content_sha256` is SHA-256 of canonical JSON header
`["exp06-action-content-v1",[50,2],"<f8",dt_s,horizon_s,command_min,command_max]`
without its trailing LF, followed by one NUL byte and the 800 C-order command bytes.
`action_sha256` hashes canonical JSON
`["exp06-action-identity-v1",action_content_sha256,strategy_id,candidate_id,scene_id,
anchor_id]`. A prediction ID is
`candidate_id + "/prediction/" + model_sha256`; a prediction-row digest hashes canonical
JSON of every scalar/ID field in schema order plus the referenced vector digest, never
the Parquet bytes. The privileged-vector digest hashes canonical JSON
`["exp06-anchor-vector-v1",scene_id,anchor_id,"<f8",shape]` without its LF, one NUL,
then the little-endian C-order vector bytes. The generator-snapshot digest hashes
canonical JSON `["exp06-generator-snapshot-v1",scene_id,simulator,state_layouts,
ordered_state_member_keys,ordered_state_member_sha256s]`; each member digest hashes its
exact canonical NPY member bytes. Selection and truth row digests hash their complete
schema-ordered scalar fields excluding only their own digest field, prefixed respectively
by `exp06-selection-v1` and `exp06-truth-v1`. Events carry those already recomputable
row digests and introduce no separate event-link digest. A model, PCA, preprocessing,
calibration, or adapted-model digest is SHA-256 over its complete canonical file bytes;
the training manifest binds those digests but is not itself in any of their preimages.
All preimages use NFKC strings, exact schema order, finite JSON numbers, and no implicit
concatenation. A validator recomputes every digest from bytes rather than trusting a
stored digest, and any self-reference, omitted field, alternate prefix, or ambiguity is
invalid.

`prediction-vectors.npz` contains exactly one member
`sha256(prediction_id).hexdigest()+".npy"` for each W4/W5 prediction and no other member.
For W5, `pca.npz` has exactly `mean.npy` shape `(24576,)`, `components.npy` shape
`(d,24576)`, and `singular_values.npy` shape `(d,)`; W3/W4 use the exact zero-byte marker
named by the training manifest. `model.npz` member names are exactly
`member/<two-digit-member>/<head>/{coef,intercept}.npy`; coefficients are float64 with
shape `(feature_count,output_count)` and intercepts `(output_count,)`. Head order is W3
`position,orientation,collision,energy,terminal_failure,unsafe,success`; W4
`state_delta,collision,terminal_failure,unsafe,success`; and W5
`latent_next,position,orientation,collision,energy,terminal_failure,unsafe,success`.
The derived feature/output counts, ensemble count, selected PCA dimension, every member
shape/dtype/hash, and ordered training-input hashes are exact rows in
`training-manifest.json`. `adapted-models.npz` contains only the permitted changed
heads enumerated in Section 5, using the same member names prefixed by `<variant>/`;
an unchanged head is forbidden rather than redundantly copied. For each variant,
`composed_adapted_model_sha256` hashes canonical JSON
`["exp06-composed-adapted-model-v1",variant,selected_model_sha256,
adapted_models_sha256,ordered_changed_member_keys,ordered_changed_member_sha256s,
ordered_unchanged_member_keys,ordered_unchanged_member_sha256s]`. Validation resolves
changed members from the adaptation archive and every unchanged member from the
selected NumPy model, recomputes both ordered sets, and requires W5 `latent_next` to be
in the unchanged set with byte/hash equality. `calibration-output.npz` uses exactly
`<variant>/<probability-head>/{breakpoints,values}.npy` for the ordered heads
`collision,terminal_failure,unsafe,success`, plus
`<variant>/{fallback_threshold,critic_threshold}.npy`. Breakpoint/value shapes and
semantics are exactly Section 13.1; duplicate, missing, extra, wrong-shape, or
non-little-endian members fail validation.

`preprocessing.json` has exact keys `schema_version,variant,configuration,
feature_names,mean,scale,zero_variance,training_rows_sha256`; arrays match the frozen
feature order and length. `training-input-manifest.json` has exact keys
`schema_version,protocol_sha256,partition,ordered_scene_bundle_sha256s,row_count,
input_sha256`. `fit_metrics.json` has exact keys `schema_version,variant,configuration,
member_metrics,training_cpu_ns,model_bytes`; member rows sort by ordinal and contain
exactly `member,root_sha256,row_count,losses`. `training-manifest.json` has exact keys
`schema_version,bundle_key,protocol_sha256,variant,configuration,preprocessing_sha256,
pca_sha256,model_sha256,evaluation_predictions_sha256,fit_metrics_sha256,
training_input_sha256,feature_count,output_heads,ensemble_count,pca_dimension,
bootstrap_draws,model_members,total_bytes`; `bootstrap_draws` is member-ordinal order
with exact-key rows `member,scene_ordinals`, each containing the exact 96 uint64-valued
draws serialized as JSON integers; each model-member row has exactly
`member_key,dtype,shape,sha256`. Every JSON loader rejects aliases, duplicate, missing,
unknown, bool-as-int, nonfinite, noncanonical, or wrongly ordered set-like arrays.

## 7. Contract freeze, mechanical selection, and evidence freeze

The sequence is strict:

1. **Precursor contract freeze:** freeze task/physics/mapping, scene/split roots,
   candidates/actions, scalar cost, W0/W1, labels, validity gates/tolerances, schemas,
   and every finite W3/W4/W5/PCA/calibration-method choice described in Section 4.
2. Pass the NumPy validity gate without changing that contract.
3. Fit each frozen-grid configuration's preprocessing/W3-W5 parameters on NumPy
   training only.
4. Mechanically rank the three frozen configurations per variant on NumPy tuning,
   then mechanically select one checkpoint/method on NumPy validation by regret,
   rank correlation, calibration error, model bytes, then configuration ID. No human
   or pilot-dependent choice is admitted.
5. Run the disjoint MuJoCo adaptation half. Apply only the predeclared linear output-
   coefficient refit and calibration-map/fallback-threshold fit; never change inputs,
   PCA, transitions, model structure, task, candidates, cost, W1, or NumPy selection.
6. Run the untouched MuJoCo pilot-evaluation half. It may set only preregistered
   effect/non-inferiority margins and measured latency/byte/time ceilings by Section
   13 formulas. It cannot refit, recalibrate, exclude, or alter any prior contract.
7. **Common evidence freeze:** freeze fitted output coefficients, calibration/fallback
   values, margins/resources, P3 MuJoCo identity, implementation, schemas, manifests,
   and all prior contract hashes in one protocol.
8. Generate the unseen MuJoCo confirmation manifest after that freeze and run once.

A change to steps 1-6 begins a new protocol revision with new disjoint MuJoCo pilot
roots; a post-evidence-freeze change also requires a new unseen confirmation root. No
pilot output can be `SUPPORTED`
(`docs/superpowers/specs/2026-08-22-reflect-lite-autonomous-run-design.md:127-181`).

## 8. Uncertainty and authority-bearing fallback

W3-W5 use the exact deterministic scene-seed bootstrap ensembles in Section 13.1. Cost
uncertainty is member-cost population variance and each failure uncertainty is
member-probability population variance, always dividing by the complete ensemble count.
The MuJoCo adaptation half fits
the preregistered monotone calibration map and one uncertainty rejection threshold per
learned variant; pilot-evaluation outcomes cannot change either.

The only authority-bearing W4/W5 selectors are compositions:

```text
W4F = W4 raw prediction when uncertainty <= threshold, otherwise W1
W5F = W5 raw prediction when uncertainty <= threshold, otherwise W1
```

The fallback decision, chosen candidate, coverage, and reason are sealed before truth
joins. Canonical co-primary and authority metrics use W4F/W5F. Raw W4/W5 ranking,
regret, calibration, and coverage-risk curves are descriptive only. Confirmation may
not choose raw versus fallback after outcomes.

Calibration reports Brier score, fixed-bin ECE, uncertainty-error correlation, error/
regret by uncertainty decile, coverage-risk, fallback frequency, and W1-relative
fallback regret.

## 9. Metrics and exact inference

### 9.1 Rank and regret definitions

Actual and predicted costs use average ranks for ties. Spearman is Pearson correlation
of those ranks. If actual costs are constant and predictions are constant, rank score
is `1.0`; if actual costs are constant but predictions are not, it is `0.0`; if actual
costs are nonconstant but predictions are constant, it is `0.0`. Selection regret is
actual selected cost minus W2's minimum actual cost and is always nonnegative within
the frozen floating tolerance; a larger negative value invalidates the scorer.
W0 has no predicted ordering, so its rank correlation is `NOT_APPLICABLE`; only its
seeded selection regret/top-1 metrics are reported. W2's predicted ordering is actual
ordering, so its rank score is `1.0` and regret is zero.

Anchor metrics average to scene, scenes average within stratum, and overall uses fixed
0.20 stratum weights. Secondary metrics are top-1 accuracy, pairwise accuracy,
oracle-gap closure, future-state error, calibration, failure precision/recall,
per-stratum results, model bytes, training CPU time, p50/p95 inference, and uncertainty
versus error (`Reflect Lite Research Program.md:2010-2020`).

### 9.2 Canonical co-primary family

The four primary contrasts are W4F and W5F versus W1 on overall rank-correlation
improvement and overall regret reduction. For composition `X`, the beneficial-positive
contrasts are `rank_X - rank_W1` and `regret_W1 - regret_X`. They form one Bonferroni family with
98.75% marginal intervals for 95% simultaneous coverage. A learned composition
establishes the claim only if both endpoints' lower bounds strictly exceed their
frozen minimum effects. Neither primary can be demoted.

### 9.3 Held-out and strong-baseline gates

Regret reduction `regret_W1 - regret_X` versus W1 for both W4F and W5F in MASS_OOD, FRICTION_OOD,
GEOMETRY_OOD, and OBSTACLE_OOD forms one eight-contrast family with 99.375% marginal
intervals. For a composition to advance, all four of its held-out lower bounds must
clear their frozen effects; controlling the single eight-way family prevents choosing
between W4F/W5F after seeing strata. W4F/W5F must also beat W3 on beneficial-positive
overall contrast `regret_W3 - regret_X` in one two-contrast family with 97.5%
intervals. These gates are simultaneous and cannot be replaced by the weighted
overall result.

Authority additionally requires frozen p95 single-candidate and K=8 batch CPU latency,
model-byte/context limits, calibration/failure limits, leakage/oracle/artifact validity,
and no safety violation. This is stricter than the program's W1 regret/latency hard
gate (`Reflect Lite Research Program.md:2022-2030`).

### 9.4 W5-versus-W4 family

If both W4F and W5F pass all authority gates, W5F replaces the simpler W4F only if one
six-endpoint Bonferroni family passes:

1. overall regret superiority of W5F over W4F;
2. overall rank-correlation non-inferiority; and
3. regret non-inferiority in each of the four held-out strata.

The beneficial-positive regret contrast is `regret_W4F - regret_W5F`; the rank
contrast is `rank_W5F - rank_W4F`. The same regret orientation applies in every
held-out stratum.

Marginal intervals are `99.1666667%`, giving 95% simultaneous coverage. The regret-
superiority lower bound must exceed its frozen margin; every non-inferiority lower
bound may equal the negative frozen margin. Calibration, latency, and bytes must also
pass their absolute W5 limits. Otherwise W4F remains selected. This family is evaluated
only after both compositions independently pass, preserving hierarchical error control.

### 9.5 Bootstrap mechanics

All contrasts use paired scene-seed differences and deterministic 10,000-resample
percentile bootstrap. Complete scene IDs sort ascending. PCG64 seed is the first 128
big-endian bits of SHA-256 over canonical JSON
`[protocol_hash, family_id, contrast_id, stratum_id, "exp06-bootstrap-v1"]`. A
stratum-specific contrast draws 16 paired scene indices with replacement from that
stratum. Every overall replicate independently draws 16 paired indices inside each of
the five strata using the corresponding stratum seed/substream, computes each stratum
mean, then combines those five replicate means with the exact frozen 0.20 weights.
Pooling 80 scenes or allowing resampled stratum proportions is forbidden.

Sorted bootstrap values use endpoint index `max(0, ceil(p * 10000) - 1)` without
interpolation or tie deduplication. Exact two-sided percentile pairs and zero-based
indices are: 95%, `(0.025,0.975)->(249,9749)`; 97.5%,
`(0.0125,0.9875)->(124,9874)`; 98.3333333%,
`(1/120,119/120)->(83,9916)`; 98.75%,
`(0.00625,0.99375)->(62,9937)`; 99.1666667%,
`(1/240,239/240)->(41,9958)`; and 99.375%,
`(0.003125,0.996875)->(31,9968)`; and 99.6875%,
`(0.0015625,0.9984375)->(15,9984)`. Equality fails superiority and passes
non-inferiority. A validly declared learned timeout uses W1 in the authority
composition; its raw endpoint receives rank `-1`, maximum finite frozen regret,
Brier/ECE `1`, critic precision/recall `0`, and a latency-gate failure. Missing output
without the declared timeout disposition or any integrity breach invalidates the
bundle; phase resource exhaustion yields `INCONCLUSIVE`.

### 9.6 Exact serial latency contract

Latency is measured inside the same OS-isolated selector worker and pinned numeric/thread
profile used for evidence, on the CPU architecture bound by the protocol. For every
pilot-evaluation and confirmation anchor and each W3/W4F/W5F selector, the worker first
performs five unrecorded warmups, then exactly 20 single-candidate repetitions for each
candidate in candidate-ID order and 20 K=8 batch repetitions. Repetition order is
`single repetition, candidate 0..7`, then `batch repetition`, repeated 20 times. W1 is
run identically as the nonlearned reference but has no authority threshold.

The timed single-candidate boundary begins immediately before projection decoding and
ends after model inference, component/envelope construction, shared-contract validation,
calibration, uncertainty/fallback decision, and canonical row construction. The batch
boundary begins before decoding the shared projection and ends after all eight rows,
calibration/fallback, universal sorting, and final selection. It excludes IPC, file I/O,
process startup, sandbox setup, warmup, truth, and artifact serialization. The worker
uses `time.perf_counter_ns`, disables cyclic GC only for each timed block, restores it
afterward, performs no parallel work, and records nonnegative integer nanoseconds plus
the clock implementation/resolution and process/user/system CPU deltas.

Durations sort as integers; nearest-rank p50/p95 use index `ceil(p*n)-1`. The hard
single and batch values are the p95 over all measured repetitions in the phase, reported
also per stratum and scene. Pilot ceilings are separately
`ceil_to_100000ns(1.25*pilot_p95_ns)` and must be no greater than the precursor-frozen
1,000,000,000 ns emergency bound. Confirmation passes equality and fails strictly above
either frozen ceiling. One call crossing the emergency bound is terminated and receives
the declared timeout treatment in Section 9.5; any undeclared missing duration,
negative/boolean duration, count drift, clock change, thread drift, or parallel overlap
makes the latency artifact invalid.

`latency.json` has exact keys `schema_version,phase,protocol_sha256,cpu_identity,
clock_implementation,clock_resolution_ns,warmup_count,repetition_count,
scene_latency_sha256s,
single_p50_ns,single_p95_ns,batch_p50_ns,batch_p95_ns,cpu_user_ns,cpu_system_ns,
timeout_count`. Each sorted scene row has exact keys `scene_id,row_count,sha256` and
requires `row_count=2880`. The referenced per-scene `latency-rows.jsonl` row has exact
keys `selector_id,stratum,scene_id,anchor_id,
candidate_id,single_ns,batch_ns`; a single row has nonnull candidate/single and null
batch, while a batch row has null candidate/single and nonnull batch. Rows use
the execution order above: 180 rows per anchor/selector, exactly 57,600 pilot rows and
230,400 confirmation rows across W1/W3/W4F/W5F. Each JSONL row is canonical compact
JSON plus one LF; the small global JSON is sealed and digest-bound by the selector
freeze before truth exists without duplicating the per-scene rows.

## 10. Separate states and ordered role mapping

Lifecycle is `DRAFT -> CONTRACT_FROZEN -> NUMPY_VALIDATED -> NUMPY_SELECTED ->
MUJOCO_ADAPTATION -> MUJOCO_PILOT_EVALUATED -> EVIDENCE_FROZEN -> CONFIRMATION ->
DECISION -> SELECTOR_PROTOCOL_PROMOTED | STOPPED`. Artifact state is separately `VALID | INVALID`;
scientific result is `SUPPORTED | NOT_SUPPORTED | INCONCLUSIVE`; prerequisite/resource
state is `READY | BLOCKED`; P7 promotion state is
`SELECTOR_PROTOCOL_PROMOTED | STOPPED`. The separate conditional conformance receipt
may derive `ACTION_ROUTING_ELIGIBLE` but never changes this lifecycle. Invalid evidence
has no scientific result, and a blocker is not negative evidence.

Scientific classification is computed before and independently of the role ladder.
For every beneficial-positive superiority endpoint with frozen margin `M`, status is
`PASS` when the adjusted lower bound is strictly greater than `M`,
`CONCLUSIVELY_REJECTED` when the adjusted upper bound is strictly less than `M`, and
`UNRESOLVED` otherwise; equality at either boundary is unresolved. For every
non-inferiority endpoint with margin `M`, status is `PASS` when the adjusted lower bound
is at least `-M`, `CONCLUSIVELY_REJECTED` when the adjusted upper bound is strictly less
than `-M`, and `UNRESOLVED` otherwise. A complete, valid absolute gate is `PASS` at or
inside its frozen bound and `CONCLUSIVELY_REJECTED` outside it. Missing/corrupt evidence,
resource exhaustion, an invalid baseline/control, or a precision failure is never a
rejection; it is `INCONCLUSIVE` under the existing artifact/resource rules.

Each of W4F and W5F is `AUTHORITY_PASS` only when every required co-primary, four
held-out, W3, calibration, latency/byte, and safety endpoint passes. It is
`AUTHORITY_REJECTED` when at least one required endpoint or complete valid absolute gate
is conclusively rejected, because the preregistered joint rule can no longer pass. It
is `AUTHORITY_UNRESOLVED` otherwise. The candidate-ranking result is `SUPPORTED` if at
least one composition is `AUTHORITY_PASS`; `NOT_SUPPORTED` only if both compositions
are `AUTHORITY_REJECTED`; and `INCONCLUSIVE` otherwise. W5-versus-W4 chooses between two
passing compositions but cannot change this result. Exact endpoint statuses, bounds,
and the first decisive reason in frozen endpoint order are serialized.

For `VALID + READY` confirmation, exactly one role is chosen by first matching rule:

1. `CANDIDATE_SELECTOR` if at least one learned+W1-fallback composition passes every
   co-primary, held-out, W3, latency, calibration, safety, and selection gate. If both
   pass, Section 9.4 selects W5F only when its six-endpoint family passes; otherwise
   W4F is selected.
2. `FAILURE_CRITIC` if rule 1 fails but W4 or W5 passes its eight held-out
   precision/recall endpoints inside the one frozen 16-endpoint, two-head family with
   99.6875% marginal intervals, plus calibration, latency, and zero-unsafe-veto gates.
   Every lower bound must clear its frozen minimum. W4 is chosen before W5 if both
   pass. The experiment records only the counterfactual occasions on which the critic
   would replace a learned choice with W1; it cannot rank, introduce, veto, replace,
   route, or execute an action in this experiment or downstream.
3. `SHADOW_OBSERVER` if rules 1-2 fail and W4F or W5F passes its endpoints inside the
   one frozen 16-endpoint, two-composition 99.6875% family: upper bounds for held-out
   Brier and fixed-bin ECE in MASS_OOD, FRICTION_OOD, GEOMETRY_OOD, and OBSTACLE_OOD
   must be at or below their absolute ceilings, and p95 single/batch latency and model
   bytes must pass. W4F is chosen before W5F if both pass. It emits no action-affecting
   event.
4. `OFFLINE_ANALYSIS_ONLY` if rules 1-3 fail but at least one member of the frozen
   six-endpoint descriptive family passes: overall rank improvement and regret
   reduction versus W1 for raw W3, W4, and W5, each with a 99.1666667% Bonferroni
   interval whose lower bound strictly exceeds its endpoint's frozen minimum effect.
   Fixed order W3, W4, W5 then rank, regret records the first passing endpoint; this
   role has no runtime authority.
5. `NOT_USEFUL_YET` otherwise.

`LATENT_SUBGOAL_MODEL_WORTH_TESTING` and `DIRECT_PLANNER_WORTH_TESTING` are unreachable
because this benchmark does not test those claims. Rules 2-5 record the best bounded
lesser role but do not determine or overwrite the scientific result above: the same
role may accompany `NOT_SUPPORTED` or `INCONCLUSIVE`. `INCONCLUSIVE`, `INVALID`, or
`BLOCKED` cannot promote. `VALID + SUPPORTED + READY + CANDIDATE_SELECTOR` promotes only
the frozen prediction-envelope and candidate-selector protocol as eligible for the
program's conditional extension; it grants no action-affecting runtime authority.
`FAILURE_CRITIC`, `SHADOW_OBSERVER`, and
`OFFLINE_ANALYSIS_ONLY` remain descriptive/unpromoted under both `NOT_SUPPORTED` and
`INCONCLUSIVE`; they cannot veto, replace, rank, select, route, or otherwise affect an
action. Granting critic authority would require a separate reviewed experiment and
preregistered claim. This preserves Experiment 06's hard rule that failure to beat W1
on held-out regret/latency stops world-model authority.

After, and only after, that selector-protocol result is committed, a separate
create-only `executor-prefix-conformance` manifest may generate 20 new scenes, four per
stratum, from a new domain-separated root. It performs no fitting, margin change, or
new scientific claim. The extension exists only when the validated P4 decision named by
`artifact-digests.json` includes `EEF_TRAJECTORY` in `promoted_wire_representations` and
the frozen `10 Hz, 300 ms` timing condition passed; otherwise action routing remains
ineligible without running a scene.

At the first anchor it regenerates all eight velocity chunks, ranks with the promoted
selector, and applies the frozen `p7-p4-eef-adapter-v1`. For selected source commands
`v[0:50]` and anchor end-effector position `e0`, the adapter emits exactly nine absolute
XY knots `x_i=e0+0.02*sum(v[0:5*i])` for `i=0..8`, in that order, so knot times are
`0.0,0.1,...,0.8 s`. Summation is serial float64 command order. The adapted action
digest is SHA-256 over canonical JSON header
`["exp06-p4-eef-adapter-v1",candidate_id,action_content_sha256,[9,2],"<f8",0.1]`
without its LF, one NUL, then the 144 little-endian C-order knot bytes. Its independently
regenerated digest and bytes must match before chunk construction.
`adapter_sha256` is SHA-256 of the exact canonical source bytes at
`experiments/06_world_model/p4_adapter.py`; that path/hash and this formula are fields
of the precursor `executor_prefix_contract` and cannot change after NumPy validity.

The shared `ActionChunk` is exact: `chunk_id` equals
`candidate_id+"/p4-adapter/"+adapted_action_sha256`; `skill_id` is
`"exp06-planar-push"`; source observation ID/time equal the anchor observation;
`generated_time_ns` and `valid_from_ns` equal
`source_observation_time_ns+300_000_000`; `expires_at_ns` equals
`valid_from_ns+250_000_000`; `dt_s=0.1`; `actions` equal the adapted `(9,2)` absolute
knots; `representation="EEF_TRAJECTORY"`; and `expected_phase="track_target"`. Metadata has exactly
`adapter_sha256,request_sha256,protocol_sha256,scene_id,anchor_id,candidate_id,strategy_id,
prediction_id,model_sha256,source_action_content_sha256,source_action_sha256,
adapted_action_sha256,p4_frozen_sha256,p4_artifact_digests_sha256`. These values apply
P4's `dt_s=policy_period`, `ceil(2.5*period)` expiry, absolute-EEF trajectory semantics,
and stable phase rather than relabelling velocity bytes.

The request-side shared contracts are constructed field-by-field, with no adapter
choice. Let `o` be the Section 6.5 integer `observation_id`, `t` the anchor's exact
monotonic source time in nanoseconds, `e=(eef_x,eef_y)`, `de=(eef_vx,eef_vy)`,
`theta=object_yaw`, `omega=object_omega`, `g=(target_x,target_y)`, and
`psi=target_yaw`. Define `target_entity_id=scene_id+"/target"` and
`target_pose7=[g_x,g_y,0.0,cos(psi/2),0.0,0.0,sin(psi/2)]`, all canonical float64.
The exact `Observation` is:

```text
sequence_id       = o
source_time_ns    = t
received_time_ns  = t
robot_state.q     = float64[eef_x,eef_y,theta]
robot_state.dq    = float64[eef_vx,eef_vy,omega]
object_beliefs    = (ObjectBelief(
  entity_id=target_entity_id, label="target", pose=target_pose7,
  pose_confidence=1.0, state={"role":"target"}, state_confidence=1.0,
  last_seen_ns=t, provenance=(scene_id,anchor_id,p4_frozen_sha256)),)
current_skill_id  = "exp06-planar-push"
current_phase     = "track_target"
```

The three-value robot vectors are a schema carrier for this planar conformance test;
they are never interpreted as P4-arm joint truth or used to score Experiment 06. The
exact paired `SkillSpec` is:

```text
skill_id          = "exp06-planar-push"
skill_type        = "PLANAR_PUSH"
target_entities   = (target_entity_id,)
target_pose       = Pose(position=float64[g_x,g_y,0.0],
                         quaternion_wxyz=float64[cos(psi/2),0.0,0.0,sin(psi/2)])
constraints       = exact ordered Constraint tuple copied from the validated promoted
                    P4 profile in frozen.yaml, without normalization
success_predicate = Predicate(kind="EEF_DWELL",
                              parameters={"error_m":0.025,"dwell_s":0.10})
timeout_s         = 2.0
retry_budget      = 0
```

The adapter validates every copied P4 constraint and both complete shared contracts.
`request_sha256` hashes canonical JSON
`["exp06-p4-request-v1",scene_id,anchor_id,observation_fields,skill_spec_fields]`, where
each `*_fields` value is an array of `[field_name,value]` pairs in dataclass declaration
order, nested dataclasses use the same representation, tuples become arrays, mappings
use sorted keys, and every NumPy vector becomes a finite float list under Section 6.4's
numeric encoding. `adapter_sha256` covers both action and request construction in
`p4_adapter.py`. An independent test invokes the promoted P4 `PolicyInput` reference
constructor from its frozen implementation on the same scalar inputs and requires
field equality, canonical-byte equality, `request_sha256` equality, and acceptance by
the current shared validator. Neither construction may read postrequest state or truth.

The current shared validator plus the frozen P4 request/response, expiry, accept/reject,
replacement, and event-order semantics must accept the chunk before the experiment-local
planar executor traverses exactly the first two interpolation intervals through the
third knot (0.20 s). It also verifies that those three knots equal integration of the
first ten source velocity rows. A source/adapted byte or digest mismatch, unpromoted P4
representation/timing profile, expired or rejected chunk, lifecycle/event mismatch,
unsafe state, nonfinite state, or failure to execute exactly that prefix stops action
authority. All 20 must pass; there is no exclusion or retry. Only its sealed conformance
receipt may change promotion state from
`SELECTOR_PROTOCOL_PROMOTED` to `ACTION_ROUTING_ELIGIBLE`; this is a derived downstream
state over the immutable decision plus receipt, never a rewrite of `decision.json`.
Downstream integration still requires its own reviewed adapter. This test never enters
the Experiment 06 co-primary family or retroactively changes `SUPPORTED`.

The extension is absent unless the final decision is selector-supported. Its only two
operator commands are:

```text
uv run python experiments/06_world_model/lifecycle.py generate-prefix-manifest --decision results/06_world_model/aggregates/r1/final-decision/all/decision.json --p4-frozen experiments/01_policy_control/configs/frozen.yaml --p4-artifact-digests experiments/01_policy_control/protocol/confirmation/artifact-digests.json --scenes-per-stratum 4 --expected-head "$(git rev-parse HEAD)" --output experiments/06_world_model/manifests/executor-prefix.json
uv run python experiments/06_world_model/run_executor_prefix.py --manifest experiments/06_world_model/manifests/executor-prefix.json --selector-protocol experiments/06_world_model/configs/frozen.yaml --output-root results/06_world_model/executor-prefix --headless --max-scenes 20 --max-candidates-per-scene 8 --max-prefix-rows 3 --max-bytes-per-scene 4194304 --expected-head "$(git rev-parse HEAD)"
```

The manifest is committed alone before the second command. Its RNG root follows the
confirmation entropy/derivation rule with `exp06-executor-prefix-v1` replacing the
confirmation domain. It has exact keys `schema_version,decision_sha256,
selector_protocol_sha256,p4_frozen_sha256,p4_artifact_digests_sha256,
adapter_sha256,p4_profile_sha256,generated_after_decision_commit,rng_algorithm,rng_root,
strata,scenes`; `p4_profile_sha256` binds the validated promoted representation and
exact `10 Hz, 300 ms` condition, and scenes are 20
sorted rows with the confirmation row schema and no earlier ancestor. The receipt
has exact keys `schema_version,decision_sha256,selector_protocol_sha256,p4_frozen_sha256,
p4_artifact_digests_sha256,manifest_sha256,
scene_count,ordered_scene_bundle_sha256s,action_chunk_schema_sha256,event_schema_sha256,
adapter_sha256,p4_profile_sha256,ordered_source_action_sha256s,
ordered_adapted_action_sha256s,ordered_request_sha256s,
passed_count,failed_count,status`; only `20,20,0,ACTION_ROUTING_ELIGIBLE` is a pass.
The four ordered hash arrays use the manifest's ascending scene-ID order and each has
exactly 20 entries; every request hash equals the accepted chunk's metadata value.
Each conformance scene is create-only and at most 4 MiB, so the conditional extension
adds an exact 80 MiB retained maximum already reserved by P7 preflight.

## 11. Atomic scene evidence and separate training/aggregate bundles

The canonical `RolloutWriter` remains unchanged. A sealed experiment-local assembler
wraps its output after separately sealed generator truth and selector prediction
components validate. Pilot-evaluation and confirmation use the exact evidence layout:

```text
scene-evidence-bundle/
  rollouts/
    W1/
      metadata.json, config.json, metrics.json, events.jsonl
      observations.npz, actions.parquet, summary.md
    W3/
      <same canonical files>
    W4F/
      <same canonical files>
    W5F/
      <same canonical files>
  exp06/
    generator-snapshot.json
    generator-snapshot.npz
    anchors.parquet
    candidate_actions.parquet
    predictions.parquet
    prediction-vectors.npz
    selections.parquet
    candidate_truth.parquet
    score_metrics.json
    replay.json
  bundle-manifest.json
```

NumPy training/tuning/validation and MuJoCo adaptation must precede final selector
outputs, so their scene key selects a different exact **source** layout rather than
pretending W3/W4F/W5F already exist:

```text
scene-source-bundle/
  rollout/generator/
    metadata.json, config.json, metrics.json, events.jsonl
    observations.npz, actions.parquet, summary.md
  exp06/
    generator-snapshot.json
    generator-snapshot.npz
    anchors.parquet
    candidate_actions.parquet
    candidate_truth.parquet
    replay.json
  bundle-manifest.json
```

The source layout is valid only for `numpy-train`, `numpy-tuning`,
`numpy-validation`, and `mujoco-pilot-adaptation`; the evidence layout is valid only
for `mujoco-pilot-evaluation` and `mujoco-confirmation`. The phase-bound validator
rejects missing selector outputs in an evidence scene and rejects predictions,
selections, score metrics, or selector rollouts in a source scene. Both layouts remain
scene-local and have the same 16 MiB cap.

In the evidence layout, each subdirectory under `rollouts/` is an unchanged independently replayable canonical
rollout. This prevents multiple selectors from emitting duplicate candidate IDs into
one shared replay state. `candidate_actions.parquet` stores all K=8 IDs, strategy IDs,
arrays, timing, `action_content_sha256`, and identity-bound `action_sha256`.
`predictions.parquet` stores the exact W1/W3/W4/W5 raw envelopes with their global
prediction IDs. `selections.parquet` stores W0/W1/W2/W3/raw W4/raw W5/W4F/W5F selections,
uncertainty decision, selected candidate/both action hashes, and W1 fallback reason.
W0/W2 have null `prediction_id`; W1/W3/raw W4/raw W5 reference their same-model raw
prediction, and W4F/W5F reference respectively the chosen raw W4/W5 prediction or the
raw W1 prediction after fallback. No composed prediction row exists.
`candidate_truth.parquet` is scorer-only MuJoCo truth with actual cost components/
outcomes and W2 selection. Primary ranking-only canonical `actions.parquet` tables are
empty; if the later short-prefix extension executes a selected `ActionChunk`, its
metadata must match the candidate and both action hashes exactly.

Within each W1/W3/W4F/W5F canonical rollout, exactly one `WORLD_MODEL_PREDICTED` event
cross-links each globally unique candidate ID and one `WORLD_MODEL_SELECTED` per anchor
cross-links the sealed selection. W4F/W5F events use the learned envelope below the
threshold and the W1 envelope after fallback, never both. The existing replay invariant—
selection resolves to exactly one prediction—therefore remains usable
(`reflect/replay.py:299-317`). Raw W4/W5 and W0/W2 remain sidecar-only. The bundle
validator additionally requires:

The exact `WORLD_MODEL_PREDICTED` payload keys are
`observation_id,prediction_id,scene_id,anchor_id,candidate_id,strategy_id,
action_content_sha256,action_sha256,model_id,prediction_row_sha256`; the exact
`WORLD_MODEL_SELECTED` payload keys are
`observation_id,prediction_id,scene_id,anchor_id,candidate_id,strategy_id,
action_content_sha256,action_sha256,model_id,selection_row_sha256,used_fallback,
fallback_reason`. `observation_id` is a nonnegative JSON integer; `used_fallback` is a
JSON boolean; every other nonnull value is a string. Prediction payload strings are
always nonnull. Selection `fallback_reason` is nonnull exactly when `used_fallback` is
true and null otherwise; all its other fields are nonnull because canonical rollout
selectors W1/W3/W4F/W5F always resolve to a prediction. Unknown, missing, duplicate,
wrong-type, noncanonical, or sidecar-disagreeing keys fail. The two row digests are the
Section 6.5 prediction/selection digests, not hashes of event JSON; events introduce no
additional digest. Values are copied from sealed sidecar rows and cannot be synthesized
or normalized during publication.

- exactly eight candidate/action/truth rows per anchor, eight distinct content digests,
  eight distinct identity hashes, and eight bytewise-distinct command trajectories;
- regenerated candidate bytes and both hashes equal the stored action rows;
- every prediction references one candidate/both action hashes/model hash;
- every selection references one prediction and the same two action hashes;
- every truth row references one candidate/both action hashes and pinned MuJoCo snapshot;
- every prediction/selection event matches exactly one selector-specific sidecar row
  and ordering, with no candidate duplicated inside one canonical rollout;
- any canonical executed action matches the selected candidate and both action hashes; and
- all scene/anchor/candidate/strategy IDs and counts agree across files.

Replay reconstructs observations, candidate actions, prediction envelopes, fallback
decisions, selections, events, truth joins, W2, scores, and terminal cross-link state
without rerunning physics or models. It verifies evidence, not counterfactual dynamics.

The evidence-scene boundary has three named responsibilities:

- `EvidenceBundleWriter` owns one create-exclusive sibling staging tree from selector
  projection through final publication. For destination
  `scenes/<revision>/<phase>/<stratum>/<seed>/`, that tree is exactly
  `scenes/<revision>/<phase>/<stratum>/.scene-<bundle-key>.building`; both are children
  of the same descriptor-held parent. It never copies or separately materializes a
  second component tree. It advances only through the sealed states below, invokes all
  validators, writes the final manifest last, fsyncs, and performs one descriptor-relative
  rename-no-replace within that parent.
- `validate_evidence_bundle` validates every canonical rollout first, then exact
  sidecar schemas, hashes, IDs, counts, action regeneration, event ordering, oracle
  isolation attestations, and all cross-links. Validation has no repair mode.
- `replay_evidence_bundle` consumes only the finalized bundle and returns canonical
  reconstructed selector/anchor state plus recorded metric inputs. It cannot load a
  simulator/model or change a score.

Evidence phases use a mandatory global two-pass coordinator, never the former
per-scene selector→truth sequence. In pass S, the generator visits every scene in the
frozen phase manifest in canonical order and returns one canonical full snapshot as
immutable bytes to the coordinator. The coordinator computes
`generator_snapshot_sha256` in memory, derives each truth-free variant-specific
selector projection, and seals each projection with exact fields
`scene_id,anchor_id,projection_kind,projection_sha256,generator_snapshot_sha256,
candidate_action_hashes`. Full snapshot bytes remain coordinator-owned and are neither
published nor passed to a selector. Each selector receives only its one read-only
projection descriptor plus an absent output descriptor, with `close_fds`, a sanitized
environment, no results/truth root argument, and no simulator/truth import. Selector
workers expose no generic path argument or file-loading API; attempts to open the
repository result root, any pilot/confirmation truth path, another scene projection,
MuJoCo, a socket, or a subprocess fail the component and phase.

Pass S completes only after every W0/W1/W3/W4/W5 output for all 20 pilot-evaluation or
all 80 confirmation scenes validates, every selector exits, and every projection/output
descriptor closes. It then publishes one create-only `selector-freeze.json` with exact
keys `schema_version,phase,protocol_sha256,implementation_sha256,scene_manifest_sha256,
sandbox_profile_sha256,latency_sha256,scene_count,anchor_count,candidate_count,
selector_ids,scene_selector_rows`. The last
array is sorted by `(scene_id,anchor_id,selector_id)` and each exact-key row contains
`scene_id,anchor_id,selector_id,projection_sha256,generator_snapshot_sha256,
selector_output_sha256,component_path`. Unknown/duplicate/missing rows fail. The freeze
must contain exactly `scene_count*4*5` rows and is create-only published, fsynced, and
digest-bound by the truth-complete receipt before pass T. It remains ignored raw
evidence rather than a Git commit. Once it
exists, the launcher permanently refuses to execute a selector for that phase.

Only pass T may materialize full truth-source descriptors. It regenerates each full
snapshot from the frozen scene seed when necessary, requires its hash to equal the
pass-S commitment, and then create-only writes the per-scene truth source inside that
scene's validated `SELECTORS_SEALED` building tree.
`generator-snapshot.json` has exact keys
`schema_version,scene_id,simulator,anchor_ids,generator_snapshot_sha256,projection_sha256s,
state_member_keys,state_layouts,model_sha256,p3_evidence_sha256`; `simulator` is exactly
`NUMPY_PRECURSOR` or `MUJOCO_PINNED`. `generator-snapshot.npz` contains
one little-endian float64 member per anchor keyed by `sha256(anchor_id).hexdigest()+
".npy"`. Every row begins with the exact Section 13.1 ordered privileged vector. A
NumPy row then contains its complete integrator/contact state; a MuJoCo row instead
contains the complete pinned-model qpos, qvel, act, mocap, userdata, time, and named
physical-parameter arrays. `state_layouts` freezes the simulator-specific field names,
offsets, shapes, and dtypes, so no implementation choice remains and cross-simulator
reinterpretation fails. The JSON binds every projection hash. The validator reconstructs each
projection from the full descriptor and requires byte/hash equality. The truth-source
manifest additionally binds the phase selector-freeze digest, and the truth launcher
refuses a source whose committed projection/output rows are incomplete.

`projection_sha256s` is an array sorted by `(anchor_id,projection_kind)` whose rows have
exact keys `anchor_id,projection_kind,sha256`. `state_member_keys` is an array sorted by
anchor ID whose rows have exact keys `anchor_id,member_key`; `state_layouts` is an array
in byte-offset order whose rows have exact keys `name,offset,count,shape,dtype`. Unknown
keys, overlapping/gapped offsets, or a member length different from the layout fail.

Only then does pass T launch pinned MuJoCo with this full truth descriptor; it never
launches truth from a selector projection. It seals candidate truth/W2 and launches the
scorer with separate read-only selector and truth descriptors. Reversing phase order,
materializing any truth before the selector freeze publishes, running a selector after
that freeze, or finding a phase truth path during pass S invalidates the whole phase.
On a crash before selector freeze, no truth exists: same-process held components may be
cleaned and the complete selector pass reruns. On restart after selector freeze, the
freeze validates and only pass T may resume; selectors never rerun. A pass-T crash
resumes only missing truth/scorer scenes through validate-and-skip. The writer starts
only after generator, frozen selector, and scorer components validate, so co-location
in the finalized evidence bundle cannot become a preselection truth channel.

Each evidence scene has the one descriptor-held create-exclusive sibling
`.scene-<bundle-key>.building` tree defined above and an exact monotone state machine:
`CREATED -> SELECTORS_SEALED -> TRUTH_SEALED -> BUNDLE_SEALED -> PUBLISHED`. Pass S
writes only the `selectors/` subtree plus `stage-state.json`, whose exact keys are
`schema_version,bundle_key,protocol_sha256,state,selector_manifest_sha256,
selector_freeze_sha256,truth_manifest_sha256,bundle_manifest_sha256,total_bytes`.
It fsyncs the subtree/tree and seals `SELECTORS_SEALED`; the combined projections,
outputs, and latency rows are at most 4 MiB per scene. The global selector freeze binds
all those stage-state and selector-manifest digests.

Pass T reopens that same tree descriptor-relatively, validates `SELECTORS_SEALED` and
the global freeze, then writes truth, scorer, canonical rollouts, and final-layout files
directly beside the immutable selector subtree. These additions are jointly at most
12 MiB, so the complete building tree and final scene bundle are always at most 16 MiB.
There is never a separate truth tree, component copy, hard link, or second staging copy.
After `TRUTH_SEALED`, the writer validates every canonical rollout and sidecar, writes
the manifest and `BUNDLE_SEALED` marker last, fsyncs all files/directories, and atomically
renames the same tree into the absent destination before the parent fsync and
`PUBLISHED` receipt.

`bundle-manifest.json` lists every other immutable file with path/media type/bytes/
SHA-256, excludes itself and temporary files, contains no field for its own digest, and
is created last. Extra/missing files, a self-digest, cross-link mismatch, corruption,
or overwrite attempt fail closed.

The tree above is a **scene bundle only**. Training and aggregation have separate keys,
roots, schemas, validators, and manifests; neither may contain a `rollouts/` tree or
scene-local truth:

```text
training-bundle/
  preprocessing.json
  pca.npz | pca.empty
  model.npz
  evaluation-predictions.parquet
  fit_metrics.json
  training-input-manifest.json
  training-manifest.json

aggregate-bundle/
  input-scene-manifest.json
  aggregate_metrics.json
  margins-resources.json | margins-resources.empty
  adapted-models.npz | adapted-models.empty
  calibration-output.npz | calibration-output.empty
  decision.json | decision.empty
  aggregate-manifest.json
```

A training bundle may contain one variant/configuration fit and its input scene hashes;
it cannot contain candidate truth, confirmation metrics, or another configuration. An
aggregate bundle consumes sealed scene/training bundle descriptors and contains only
the output appropriate to its named phase: NumPy selection, MuJoCo adaptation outputs,
MuJoCo pilot-evaluation margins/resources, confirmation metrics, or final decision.
Unused typed files are the declared empty marker so schemas never vary implicitly.
Each writer uses its own sibling temporary directory, validates its own exact file set,
fsyncs, then performs one absent-destination rename; every manifest excludes itself and
is written last. Cross-type nesting, a mixed key, in-place repair, or overwrite is
invalid.

Every writer opens the configured output root once as a directory descriptor with
no-follow semantics, verifies its device/inode against the frozen root identity, and
walks or creates every descendant descriptor-relatively. Each component must be a real
directory or regular file owned by the run; symlinks, hard-linked files, mount/device
changes, unexpected link counts, and path re-resolution fail. Temporary creation uses
mode 0700 and a create-exclusive name; publication uses descriptor-relative
rename-no-replace between the building and final names under the same held parent,
followed by parent fsync. The evidence writer's `--component-root` and `--output-root`
must be byte-equal to the same frozen scene root; disagreement fails before opening
either. The global selector-freeze publisher separately owns only its small
`phase-components` root and never owns a scene building tree. No safety decision relies
on `Path.resolve`.

During the creating process, cleanup may remove only an unsealed temporary tree whose
descriptor and inode have been continuously held since exclusive creation. A restart
may resume an evidence building tree only when its exact protocol-derived name, inode,
strict stage-state bytes, completed-state manifest, global-freeze relation, and complete
prefix all validate; it may only advance to the next state and never rewrite a sealed
file. Any other temporary entry, including an incomplete state transition, is opened
no-follow and descriptor-relatively renamed into absent
`quarantine/<bundle-key>.<nonce>`. Restart never deletes or publishes an orphan.
Foreign, malformed, multiple, symlinked, or changing entries fail closed. Quarantine
remains evidence-bearing and byte-accounted; no new phase begins until an explicit
review disposition is recorded.

The phase dispatcher invokes exactly one closed pair:
`SceneSourceBundleWriter/validate_scene_source_bundle`,
`EvidenceBundleWriter/validate_evidence_bundle`,
`TrainingBundleWriter/validate_training_bundle`, or
`AggregateBundleWriter/validate_aggregate_bundle`. No writer imports another writer's
schema or accepts a union-shaped payload. Scene replay is the only replay that returns
anchor/candidate state; training replay returns fit/input hashes, and aggregate replay
returns only its declared phase output and input-bundle hashes.

## 12. Evidence commands, shards, resume, and resources

The launcher requires `cwd` to equal the symlink-resolved project root returned by
`git rev-parse --show-toplevel`; all CLI paths are project-root-relative, and absolute
or `..` paths fail. Bundle types and keys are disjoint:

- scene: `(scene, protocol_revision, phase, stratum, scene_seed)`, where phase is
  `numpy-train | numpy-tuning | numpy-validation | mujoco-pilot-adaptation |
  mujoco-pilot-evaluation | mujoco-confirmation`;
- training: `(training, protocol_revision, variant, configuration)`, with variant
  `W3 | W4 | W5` and one of the three frozen configuration IDs; and
- aggregate: `(aggregate, protocol_revision, phase, aggregate_id)`, where phase is
  `numpy-validity | numpy-selection | mujoco-adaptation | mujoco-pilot-evaluation |
  mujoco-confirmation | final-decision` and `aggregate_id=all`.

### 12.1 Exact lifecycle artifacts and publication commands

Every lifecycle publisher is create-only, takes no network or simulator capability,
uses the descriptor-relative writer in Section 11, and refuses a dirty tracked or
untracked tree. It runs Git under the hardened environment in this section, requires
the full `--expected-head` commit, proves the implementation allowlist byte-equal to
the implementation SHA, and records both values. After publication, each small
protocol/config/manifest is committed alone; the next publisher requires that clean
commit. Raw scene/training/aggregate results remain ignored and are digest-bound inputs,
not Git commits.

Before `precursor-frozen.yaml`, P7 publishes one experiment-local, create-only P3 gate
adapter. It does not rerun MuJoCo or reinterpret P3; it validates and binds P3's existing
authoritative evidence. `p3-gate.yaml` is canonical JSON-as-YAML and has exactly the
top-level keys
`schema_version,p2_lock_sha256,operation_manifest_sha256,compatibility_sha256,
licenses_sha256,source_map_sha256,results_sha256,interface_findings_sha256,
mujoco_fragment_path,mujoco_fragment_sha256,mujoco_package,audit_commands,
advance_decision,p3_evidence_commit,p3_report_commit,publication_parent_sha256`.
`mujoco_package` has exactly
`name,version,distribution_artifact_sha256,python_version,platform,smoke_status,
smoke_command`; `audit_commands` is the ordered exact pair
`["uv","run","python","scripts/audit_references.py","--require-complete"]` and
`["uv","run","python","scripts/source_audit.py","--check"]`,
each represented by an exact-key row
`command,exit_status,stdout_sha256,stderr_sha256`; `command` is the project-relative
argument vector, `exit_status` is integer zero, and the two stream hashes cover exact
captured bytes. `advance_decision` is
exactly `ADVANCE`, and the two named P3 commits are full 40-lowercase-hex ancestors of
the current HEAD. The adapter requires the P2 lock and P3 operation manifest, compatibility CSV,
`references/licenses.md`, `docs/SOURCE_MAP.md`, Experiment 00 results/interface report,
and the unique passing MuJoCo package-runtime fragment to validate and agree on package,
artifact, lock, and commit identity. Missing, ambiguous, failed, dirty, or
noncanonical evidence fails without writing.

Publish and commit it alone before the precursor freeze:

```text
uv run python experiments/06_world_model/p3_gate.py --write \
  --p2-lock references/repos.lock.yaml \
  --operation-manifest experiments/00_source_audit/configs/operation-manifest.yaml \
  --compatibility experiments/00_source_audit/results/compatibility.csv \
  --licenses references/licenses.md --source-map docs/SOURCE_MAP.md \
  --results experiments/00_source_audit/RESULTS.md \
  --interface-findings experiments/00_source_audit/INTERFACE_FINDINGS.md \
  --fragments experiments/00_source_audit/results/fragments \
  --expected-head "$(git rev-parse HEAD)" \
  --output experiments/06_world_model/configs/p3-gate.yaml
git add experiments/06_world_model/configs/p3-gate.yaml
git commit -m "docs: bind P7 to passing P3 evidence"
```

The command requires a clean tree, takes `p3_evidence_commit` from the exact evidence
SHA named by P3's report provenance, derives `p3_report_commit` as the unique common
last-modifying commit of the two P3 report files, and records the literal pre-output
HEAD as `publication_parent_sha256`. All three are full 40-lowercase-hex commits;
evidence precedes report, report is an ancestor of publication parent, and the two
reports must be byte-identical to their report commit. After the dedicated gate commit,
`freeze-precursor` requires the gate path tracked and byte-identical and its publication
parent an ancestor of the new clean HEAD. Reissue against an existing byte-identical
gate validates-and-skips before any write; a conflicting file starts a reviewed
protocol revision rather than overwriting.

`precursor-frozen.yaml` has exactly the top-level keys
`schema_version,protocol_revision,implementation_sha256,implementation_paths,
publication_parent_sha256,
p2_lock_sha256,p3_gate_sha256,p3_mujoco_package,task,candidate_factory,numpy_simulator,
mujoco_model_generator,cost,labels,w0,w1,model_grid,splits,validity_grid,schemas,
sandbox_profiles,latency_contract,executor_prefix_contract,numeric_profile,hard_budgets`.
Every nested key/value is the frozen Section 13.1
transcription; unknown/missing keys fail. Publish it exactly:

```text
uv run python experiments/06_world_model/lifecycle.py freeze-precursor \
  --base experiments/06_world_model/configs/base.yaml \
  --validity-manifest experiments/06_world_model/manifests/numpy-validity-cases.json \
  --p3-gate experiments/06_world_model/configs/p3-gate.yaml \
  --expected-head "$(git rev-parse HEAD)" \
  --output experiments/06_world_model/configs/precursor-frozen.yaml
```

Each of the six `phase-protocol.json` files has exact keys
`schema_version,protocol_id,revision,phase,implementation_sha256,
publication_parent_sha256,parent_path,parent_sha256,p2_lock_sha256,p3_gate_sha256,
config_path,config_sha256,input_manifest_path,input_manifest_sha256,exact_counts,
budgets`. `exact_counts` always has exact integer keys
`validity_cases,scene_bundles,training_bundles,input_aggregates`; the six rows are:

| protocol path | phase | counts `(validity,scenes,training,aggregates)` |
|---|---|---|
| `protocols/r1/01-numpy-validity.json` | `numpy-validity` | `(80,0,0,0)` |
| `protocols/r1/02-numpy-selection.json` | `numpy-selection` | `(0,144,9,1)` |
| `protocols/r1/03-mujoco-adaptation.json` | `mujoco-adaptation` | `(0,20,3,1)` |
| `protocols/r1/04-mujoco-pilot-evaluation.json` | `mujoco-pilot-evaluation` | `(0,20,0,1)` |
| `protocols/r1/05-mujoco-confirmation.json` | `mujoco-confirmation` | `(0,80,0,2)` |
| `protocols/r1/06-final-decision.json` | `final-decision` | `(0,0,0,1)` |

The first three protocols publish serially with these exact commands; each parent must
already validate and the named output is committed before the next command:

```text
uv run python experiments/06_world_model/lifecycle.py publish-phase --phase numpy-validity --config experiments/06_world_model/configs/precursor-frozen.yaml --parent experiments/06_world_model/configs/precursor-frozen.yaml --input-manifest experiments/06_world_model/manifests/numpy-validity-cases.json --validity-cases 80 --scene-bundles 0 --training-bundles 0 --input-aggregates 0 --expected-head "$(git rev-parse HEAD)" --output experiments/06_world_model/protocols/r1/01-numpy-validity.json
uv run python experiments/06_world_model/lifecycle.py publish-phase --phase numpy-selection --config experiments/06_world_model/configs/precursor-frozen.yaml --parent results/06_world_model/aggregates/r1/numpy-validity/all/aggregate-manifest.json --input-manifest experiments/06_world_model/manifests/numpy-development.json --validity-cases 0 --scene-bundles 144 --training-bundles 9 --input-aggregates 1 --expected-head "$(git rev-parse HEAD)" --output experiments/06_world_model/protocols/r1/02-numpy-selection.json
uv run python experiments/06_world_model/lifecycle.py publish-phase --phase mujoco-adaptation --config experiments/06_world_model/configs/precursor-frozen.yaml --parent results/06_world_model/aggregates/r1/numpy-selection/all/aggregate-manifest.json --input-manifest experiments/06_world_model/manifests/mujoco-pilot.json --validity-cases 0 --scene-bundles 20 --training-bundles 3 --input-aggregates 1 --expected-head "$(git rev-parse HEAD)" --output experiments/06_world_model/protocols/r1/03-mujoco-adaptation.json
```

The fourth protocol is permitted only after the third phase has executed and this exact
create-only adapter has published and committed `pilot-evaluation.yaml`. That file has
the precursor keys plus exact top-level `selected_model_hashes,adapted_output_heads,
composed_adapted_model_hashes,calibration_maps,fallback_thresholds,
adaptation_input_hashes`; it contains no pilot-
evaluation outcomes, margins, measured budgets, or confirmation root:

```text
uv run python experiments/06_world_model/lifecycle.py freeze-pilot-evaluation \
  --precursor experiments/06_world_model/configs/precursor-frozen.yaml \
  --numpy-selection results/06_world_model/aggregates/r1/numpy-selection/all/aggregate-manifest.json \
  --adaptation results/06_world_model/aggregates/r1/mujoco-adaptation/all/aggregate-manifest.json \
  --expected-head "$(git rev-parse HEAD)" \
  --output experiments/06_world_model/configs/pilot-evaluation.yaml

uv run python experiments/06_world_model/lifecycle.py publish-phase --phase mujoco-pilot-evaluation --config experiments/06_world_model/configs/pilot-evaluation.yaml --parent results/06_world_model/aggregates/r1/mujoco-adaptation/all/aggregate-manifest.json --input-manifest experiments/06_world_model/manifests/mujoco-pilot.json --validity-cases 0 --scene-bundles 20 --training-bundles 0 --input-aggregates 1 --expected-head "$(git rev-parse HEAD)" --output experiments/06_world_model/protocols/r1/04-mujoco-pilot-evaluation.json
```

After the pilot-evaluation aggregate validates, the common freeze command consumes only
the already declared pilot outputs. `frozen.yaml` has the precursor keys plus exact
top-level `selected_models,adapted_output_heads,composed_adapted_model_hashes,
calibration_maps,fallback_thresholds,
pilot_margins,measured_budgets,pilot_input_hashes,confirmation_contract`; it cannot
self-hash or contain a confirmation seed/root:

```text
uv run python experiments/06_world_model/lifecycle.py freeze-evidence \
  --precursor experiments/06_world_model/configs/precursor-frozen.yaml \
  --numpy-selection results/06_world_model/aggregates/r1/numpy-selection/all/aggregate-manifest.json \
  --adaptation results/06_world_model/aggregates/r1/mujoco-adaptation/all/aggregate-manifest.json \
  --pilot-evaluation results/06_world_model/aggregates/r1/mujoco-pilot-evaluation/all/aggregate-manifest.json \
  --expected-head "$(git rev-parse HEAD)" --output experiments/06_world_model/configs/frozen.yaml
```

Only after that file is committed does the following command generate the unseen
confirmation root and manifest. The manifest has exact keys
`schema_version,protocol_sha256,generated_after_freeze_commit,rng_algorithm,rng_root,
strata,scenes`; `strata` is the five names in frozen order, and `scenes` is exactly 80
rows sorted by `(stratum,scene_id)` with exact keys
`stratum,ordinal,scene_seed,scene_id,probe_seed,parameter_cell_sha256`. It rejects any
pilot/NumPy ancestor or content hash:

```text
uv run python experiments/06_world_model/lifecycle.py generate-confirmation \
  --frozen experiments/06_world_model/configs/frozen.yaml \
  --expected-head "$(git rev-parse HEAD)" --strata 5 --scenes-per-stratum 16 \
  --output experiments/06_world_model/manifests/mujoco-confirmation.json
```

Commit that manifest alone, then publish protocol 05 exactly:

```text
uv run python experiments/06_world_model/lifecycle.py publish-phase --phase mujoco-confirmation --config experiments/06_world_model/configs/frozen.yaml --parent experiments/06_world_model/configs/frozen.yaml --input-manifest experiments/06_world_model/manifests/mujoco-confirmation.json --validity-cases 0 --scene-bundles 80 --training-bundles 0 --input-aggregates 2 --expected-head "$(git rev-parse HEAD)" --output experiments/06_world_model/protocols/r1/05-mujoco-confirmation.json
```

Commit protocol 05, run its complete selector freeze, truth phase, and confirmation
aggregate, and validate that aggregate without report or decision access. Only then may
protocol 06 bind the now-existing confirmation aggregate and publish exactly:

```text
uv run python experiments/06_world_model/lifecycle.py publish-phase --phase final-decision --config experiments/06_world_model/configs/frozen.yaml --parent results/06_world_model/aggregates/r1/mujoco-confirmation/all/aggregate-manifest.json --input-manifest experiments/06_world_model/manifests/mujoco-confirmation.json --validity-cases 0 --scene-bundles 0 --training-bundles 0 --input-aggregates 1 --expected-head "$(git rev-parse HEAD)" --output experiments/06_world_model/protocols/r1/06-final-decision.json
```

Commit protocol 06 alone before final-decision aggregation. A protocol 06 file that
predates, does not hash, or does not name the complete confirmation aggregate is invalid.

The shell substitution must resolve to one literal full 40-hex SHA before the Python
process starts; the CLI records and independently rechecks it. Any output, manifest,
aggregate, or source change after its parent commit starts a new protocol revision.

One scene bundle contains exactly four anchors and 32 candidate branches. Pilot-
evaluation and confirmation selectors run only through the global pass-S commands
below. Each command validates every named scene/component and publishes the phase
selector freeze only after the complete exact count; neither command can import or
materialize MuJoCo truth:

Before those evidence passes, NumPy source generation and the privileged MuJoCo
adaptation controller execute through these exact manifest-wide commands.
`run_sources.py` derives each create-only bundle key from the
manifest row and phase (`scene:r1:<source-phase>:<stratum>:<16-lowercase-hex-seed>`),
requires every expected key exactly once, and has no selector-output writer. The NumPy
command creates exactly 96 train, 24 tuning, and 24 validation bundles. The adaptation
controller runs only after NumPy selection, generates exactly the 20 adaptation rows
into the unlinked capabilities in Section 6, consumes the three selected training
bundles, fits only permitted outputs, and directly publishes the adaptation aggregate:

```text
uv run python experiments/06_world_model/run_sources.py \
  --protocol experiments/06_world_model/protocols/r1/02-numpy-selection.json \
  --scene-manifest experiments/06_world_model/manifests/numpy-development.json \
  --phase numpy-selection --output-root results/06_world_model/scenes \
  --headless --max-train-scenes 96 --max-tuning-scenes 24 \
  --max-validation-scenes 24 --max-scenes 144 --expected-head "$(git rev-parse HEAD)"

uv run python experiments/06_world_model/run_adaptation.py \
  --protocol experiments/06_world_model/protocols/r1/03-mujoco-adaptation.json \
  --scene-manifest experiments/06_world_model/manifests/mujoco-pilot.json \
  --partition adaptation --phase mujoco-adaptation \
  --training-root results/06_world_model/training \
  --numpy-selection results/06_world_model/aggregates/r1/numpy-selection/all/aggregate-manifest.json \
  --private-root .private/06_world_model/r1/adaptation \
  --output-root results/06_world_model/aggregates --headless \
  --max-scenes 20 --max-training-bundles 3 --max-input-aggregates 1 \
  --max-output-aggregates 1 --expected-head "$(git rev-parse HEAD)"
```

Any missing, extra, duplicate, wrongly partitioned, or differently keyed input fails
the whole phase. `train_all.py` iterates the fixed ordered Cartesian product
`{W3,W4,W5} x {CFG01,CFG02,CFG03}`, derives each key, and accepts only the 96 NumPy-train
source descriptors named by protocol 02. Its only invocation is:

```text
uv run python experiments/06_world_model/train_all.py \
  --protocol experiments/06_world_model/protocols/r1/02-numpy-selection.json \
  --scene-root results/06_world_model/scenes \
  --output-root results/06_world_model/training --headless \
  --max-input-scenes 96 --max-configurations-per-variant 3 \
  --max-variants 3 --max-training-bundles 9 --expected-head "$(git rev-parse HEAD)"
```

The phase must contain exactly nine training bundle keys before NumPy selection
aggregation; caller-supplied configuration names or bundle keys are rejected.

```text
uv run python experiments/06_world_model/run_selectors.py \
  --protocol experiments/06_world_model/protocols/r1/04-mujoco-pilot-evaluation.json \
  --scene-manifest experiments/06_world_model/manifests/mujoco-pilot.json \
  --phase mujoco-pilot-evaluation \
  --component-root results/06_world_model/scenes \
  --selector-freeze results/06_world_model/phase-components/r1/mujoco-pilot-evaluation/selector-freeze.json \
  --headless --max-scenes 20 --max-anchors 80 --max-candidates 640 --max-selectors 5 \
  --expected-head "$(git rev-parse HEAD)"

uv run python experiments/06_world_model/run_selectors.py \
  --protocol experiments/06_world_model/protocols/r1/05-mujoco-confirmation.json \
  --scene-manifest experiments/06_world_model/manifests/mujoco-confirmation.json \
  --phase mujoco-confirmation \
  --component-root results/06_world_model/scenes \
  --selector-freeze results/06_world_model/phase-components/r1/mujoco-confirmation/selector-freeze.json \
  --headless --max-scenes 80 --max-anchors 320 --max-candidates 2560 --max-selectors 5 \
  --expected-head "$(git rev-parse HEAD)"
```

Immediately after the pilot-evaluation selector freeze and before any pass-T truth, the
privileged controller republishes adaptation inputs for audit by deterministic
regeneration; this is not run for confirmation:

```text
uv run python experiments/06_world_model/publish_adaptation_sources.py \
  --protocol experiments/06_world_model/protocols/r1/04-mujoco-pilot-evaluation.json \
  --scene-manifest experiments/06_world_model/manifests/mujoco-pilot.json \
  --adaptation-aggregate results/06_world_model/aggregates/r1/mujoco-adaptation/all/aggregate-manifest.json \
  --selector-freeze results/06_world_model/phase-components/r1/mujoco-pilot-evaluation/selector-freeze.json \
  --output-root results/06_world_model/scenes --headless --max-scenes 20 \
  --expected-head "$(git rev-parse HEAD)"
```

It publishes exactly the 20 `mujoco-pilot-adaptation` source bundles only after all
pilot selectors exit; every regenerated input hash must equal the sealed adaptation
aggregate row. It has no model/calibration output and cannot import selector code.

Pass T starts only after the matching selector freeze validates. `run_truth_phase.py`
is the sole manifest iterator: in sorted manifest order it opens one validated
selector-sealed building tree, regenerates/materializes its truth source, runs W2/MuJoCo,
scores, and advances that same tree to the final bundle without starting a selector. It
derives the bundle key internally and rejects a
caller-supplied key or arbitrary runner arguments. These are the exact two invocations;
they require exactly 20 pilot-evaluation or 80 confirmation keys before aggregation:

```text
uv run python experiments/06_world_model/run_truth_phase.py \
  --protocol experiments/06_world_model/protocols/r1/04-mujoco-pilot-evaluation.json \
  --scene-manifest experiments/06_world_model/manifests/mujoco-pilot.json \
  --partition pilot-evaluation --phase mujoco-pilot-evaluation \
  --selector-freeze results/06_world_model/phase-components/r1/mujoco-pilot-evaluation/selector-freeze.json \
  --component-root results/06_world_model/scenes \
  --output-root results/06_world_model/scenes --headless \
  --max-scenes 20 --max-anchors-per-scene 4 --max-candidates-per-anchor 8 \
  --expected-head "$(git rev-parse HEAD)"

uv run python experiments/06_world_model/run_truth_phase.py \
  --protocol experiments/06_world_model/protocols/r1/05-mujoco-confirmation.json \
  --scene-manifest experiments/06_world_model/manifests/mujoco-confirmation.json \
  --phase mujoco-confirmation \
  --selector-freeze results/06_world_model/phase-components/r1/mujoco-confirmation/selector-freeze.json \
  --component-root results/06_world_model/scenes \
  --output-root results/06_world_model/scenes --headless \
  --max-scenes 80 --max-anchors-per-scene 4 --max-candidates-per-anchor 8 \
  --expected-head "$(git rev-parse HEAD)"

uv run python experiments/06_world_model/validate_numpy.py \
  --protocol experiments/06_world_model/protocols/r1/01-numpy-validity.json \
  --bundle-key aggregate:r1:numpy-validity:all \
  --output-root results/06_world_model/aggregates --headless --max-cases 80 \
  --expected-head "$(git rev-parse HEAD)"

uv run python experiments/06_world_model/aggregate.py \
  --protocol experiments/06_world_model/protocols/r1/04-mujoco-pilot-evaluation.json \
  --bundle-key aggregate:r1:mujoco-pilot-evaluation:all \
  --scene-root results/06_world_model/scenes \
  --training-root results/06_world_model/training \
  --output-root results/06_world_model/aggregates --headless \
  --max-training-bundles 0 --max-scenes 20 --max-input-aggregates 1 \
  --expected-head "$(git rev-parse HEAD)"
```

The iterator has no generic path or subprocess argument and a component exit other
than zero fails the phase; it never skips a missing key. Its create-only receipt at
`phase-components/r1/<phase>/truth-complete.json` has exact keys
`schema_version,phase,protocol_sha256,selector_freeze_sha256,scene_count,
ordered_bundle_keys,bundle_manifest_sha256s` and must validate before aggregation.

The same aggregate shape uses `--protocol
experiments/06_world_model/protocols/r1/05-mujoco-confirmation.json` and `--max-scenes 80` for
`aggregate:r1:mujoco-confirmation:all`, with zero training bundles and two input
aggregates. Exact aggregate inputs are: NumPy validity, the frozen 80-case fixture and
no prior bundle; NumPy selection, nine training bundles plus 24 tuning and 24
validation scene bundles plus the one validity aggregate; MuJoCo
adaptation, 20 anonymous adaptation inputs plus the three selected NumPy training
bundles and the NumPy-selection aggregate in the single adaptation controller; its 20
later regenerated scene bundles are audit copies and cannot alter that aggregate;
pilot evaluation, 20 evaluation scene bundles plus the one adaptation
aggregate; confirmation, 80 confirmation scene bundles plus the adaptation and
pilot-evaluation aggregates; final decision, the one confirmation aggregate. The CLI
requires corresponding exact `--max-training-bundles`, `--max-scenes`, and
`--max-input-aggregates` values, using zero for an inapplicable kind. Destinations
derive respectively as
`scenes/<revision>/<phase>/<stratum>/<seed>/`,
`training/<revision>/<variant>/<configuration>/`, and
`aggregates/<revision>/<phase>/all/`. A command cannot write another type's root or
carry another type's flags. NumPy generation/training/selection require their
checked-in phase protocols descending from `precursor-frozen.yaml`; MuJoCo adaptation/
evaluation require their phase-bound protocols; confirmation/final decision require
their protocols descending from `frozen.yaml`. Parent hashes and allowed phase are
validated, so a later protocol cannot be substituted retroactively.

All non-validity aggregate and final-report invocations are exact, not examples:

```text
uv run python experiments/06_world_model/aggregate.py --protocol experiments/06_world_model/protocols/r1/02-numpy-selection.json --bundle-key aggregate:r1:numpy-selection:all --scene-root results/06_world_model/scenes --training-root results/06_world_model/training --output-root results/06_world_model/aggregates --headless --max-training-bundles 9 --max-scenes 48 --max-input-aggregates 1 --expected-head "$(git rev-parse HEAD)"
uv run python experiments/06_world_model/aggregate.py --protocol experiments/06_world_model/protocols/r1/04-mujoco-pilot-evaluation.json --bundle-key aggregate:r1:mujoco-pilot-evaluation:all --scene-root results/06_world_model/scenes --training-root results/06_world_model/training --output-root results/06_world_model/aggregates --headless --max-training-bundles 0 --max-scenes 20 --max-input-aggregates 1 --expected-head "$(git rev-parse HEAD)"
uv run python experiments/06_world_model/aggregate.py --protocol experiments/06_world_model/protocols/r1/05-mujoco-confirmation.json --bundle-key aggregate:r1:mujoco-confirmation:all --scene-root results/06_world_model/scenes --training-root results/06_world_model/training --output-root results/06_world_model/aggregates --headless --max-training-bundles 0 --max-scenes 80 --max-input-aggregates 2 --expected-head "$(git rev-parse HEAD)"
```

The confirmation command must complete before the Section 12.1 protocol-06 publisher;
protocol 06 is then committed alone. Only after that barrier are these exact commands
allowed:

```text
uv run python experiments/06_world_model/aggregate.py --protocol experiments/06_world_model/protocols/r1/06-final-decision.json --bundle-key aggregate:r1:final-decision:all --scene-root results/06_world_model/scenes --training-root results/06_world_model/training --output-root results/06_world_model/aggregates --headless --max-training-bundles 0 --max-scenes 0 --max-input-aggregates 1 --expected-head "$(git rev-parse HEAD)"
uv run python experiments/06_world_model/report.py --protocol experiments/06_world_model/protocols/r1/06-final-decision.json --decision results/06_world_model/aggregates/r1/final-decision/all/decision.json --artifact-manifest results/06_world_model/aggregates/r1/final-decision/all/aggregate-manifest.json --output experiments/06_world_model/WORLD_MODEL_DECISION.md --headless --expected-head "$(git rev-parse HEAD)"
```

The final aggregate create-only publishes `decision.json` with exact keys
`schema_version,protocol_sha256,confirmation_aggregate_sha256,lifecycle_status,
artifact_status,blocker_status,scientific_result,authority_readiness,assigned_role,
promotion_status,composition_results,endpoint_results,input_hashes`; its arrays use
the frozen Section 10 order and unknown/duplicate/missing keys fail. The aggregate sets
`promotion_status=SELECTOR_PROTOCOL_PROMOTED` only for the exact supported selector
case and `STOPPED` otherwise; `ACTION_ROUTING_ELIGIBLE` is forbidden in this decision.
The report command validates every upstream hash and create-only publishes the previously absent
`WORLD_MODEL_DECISION.md` by sibling temporary file, fsync, rename-no-replace, and
parent fsync; exact reissue validates-and-skips without rewriting bytes. The Markdown
has exact headings `Provenance`, `Validity`, `Canonical co-primary results`, `Secondary
results`, `Authority decision`, `Resources`, and `Artifacts`, in that order, and ends
with the decision/artifact/config/protocol SHA-256 values. It records the separate
lifecycle/artifact/blocker/scientific/role/promotion states and cannot promote any role
unless the Section 10 selector rule permits it.

The validity command alone accepts `--max-cases`, which must equal 80. Every other
command rejects that flag. NumPy scene generation and training are blocked until the
matching complete validity aggregate validates.

Every command rejects an unknown/mismatched key, wrong cwd/root, missing headless mode,
incomplete exact count, unpinned MuJoCo where required, dirty implementation,
network/CUDA/physical/remote enablement, or undeclared input. Reissuing the byte-identical
command is the only resume operation: it validates the completed type-specific bundle
and skips an exact match. A missing/extra file, corrupt/partial temporary tree, input-
manifest mismatch, mixed bundle type, or existing invalid destination fails without
overwrite, deletion, or in-place repair. All four writers use create-only sibling
temporary publication and the atomic rules in Section 11.

Git provenance runs with `GIT_DIR`, `GIT_WORK_TREE`, replacement refs, alternates,
hooks, and external diff/text-conversion variables removed; it binds the frozen full
HEAD SHA and exact P2/P3 audit/compatibility hashes. The launcher checks HEAD and a
clean tracked/untracked worktree before spawning any component and repeats both checks
after component exit immediately before publication. A mismatch discards only the
same-process held temporary bundle and fails; it never publishes mixed-source evidence.
The exact read-only sequence is `git rev-parse --verify HEAD`,
`git status --porcelain=v1 --untracked-files=all`, and
`git diff --exit-code <implementation_sha256> -- <implementation_paths...>` under that
hardened environment. `implementation_paths` is the sorted, duplicate-free list of
`pyproject.toml`, `uv.lock`, `reflect/types.py`, `reflect/events.py`,
`reflect/rollout.py`, `reflect/replay.py`, their direct contract tests, and every
Experiment 06 source/test/asset/sandbox/base-config path;
it excludes only ignored results and later create-only protocol/report evidence. HEAD
must equal the command's literal `--expected-head`, status and implementation diff must
be empty, and SHA must be a real 40-lowercase-hex commit both before spawn and after
component exit. No command runs after any failed check.

Each scene bundle has a 16 MiB/60-minute ceiling. W3 CFG01-CFG03, W4 CFG01-CFG03,
and W5 CFG01-CFG02 training bundles each have a 32 MiB/60-minute ceiling; W5 CFG03
alone has a 64 MiB/60-minute ceiling. There are exactly three configurations for each
of W3, W4, and W5, nine per revision. The larger cap is mandatory rather than
outcome-derived: W5 CFG03 has 140 transition inputs, `140+140*141/2=10,010` features,
39 outputs, and 16 members, so coefficient/intercept arrays occupy exactly 49,974,912
bytes; its fixed PCA arrays occupy 6,488,320 bytes, already 53.85 MiB before the other
typed files. Its validator additionally enforces nonborrowing subcaps of 50 MiB for
`model.npz` including canonical ZIP framing, 7 MiB for `pca.npz`, 4 MiB for
`evaluation-predictions.parquet`, and 3 MiB total for preprocessing/metrics/manifests;
their sum is the 64 MiB bundle cap. Every aggregate has a 60-minute wall ceiling. Aggregate byte
maxima are exact: per revision NumPy validity is 64 MiB, NumPy selection is 32 MiB,
MuJoCo adaptation is 64 MiB,
and pilot evaluation is 64 MiB; final-revision confirmation is 96 MiB and final
decision is 32 MiB. Checked-in generated lifecycle/config/manifest/report evidence has
a separate create-only 32 MiB total allowance. Scratch/quarantine has two nonborrowing
96 MiB slots: one live largest-writer/staging slot and one retained prior-revision orphan
slot. The worst permitted adaptation coefficient payload is exactly 26,697,216 bytes:
1,280,384 for W3 CFG03's seven changed heads, 16,446,976 for W4 CFG03's fourteen
outputs, and 8,969,856 for W5 CFG03's seven changed scalar heads; unchanged W5
`latent_next` is referenced rather than copied. Calibration and manifests therefore
remain inside nonborrowing adaptation subcaps of 28 MiB for `adapted-models.npz`,
4 MiB for `calibration-output.npz`, and 32 MiB for all remaining typed aggregate files;
their sum is the 64 MiB adaptation cap. Typed aggregates and shared allowances total
`2*(64+32+64+64)+96+32+192+32 = 800 MiB`. The evidence scene's
4 MiB selector prefix and 12 MiB truth/scorer/final suffix share its one 16 MiB cap;
neither is charged twice. With two allowed
protocol revisions and confirmation only on the final revision, retained maximum is:

```text
two revisions of NumPy+MuJoCo pilot scenes:
  2 * (144 + 40) * 16 MiB = 5,888 MiB
final MuJoCo confirmation:
  80 * 16 MiB             = 1,280 MiB
two revisions of training shards:
  2 * (8 * 32 + 1 * 64) MiB = 640 MiB
typed aggregates + two scratch/quarantine slots
  + tracked lifecycle/report evidence       =   800 MiB
conditional executor-prefix conformance:
  20 * 4 MiB                                =    80 MiB
-----------------------------------------------------
maximum retained P7 total                  = 8,688 MiB
```

The scene count is `144 NumPy + 20 MuJoCo adaptation + 20 MuJoCo pilot evaluation =
184` per revision, so the first line remains exact. The count includes truth,
predictions, scorer output, and canonical rollout inside scene bundles and all fitted
models/metrics inside training/aggregate bundles. The 32 MiB tracked bucket charges
`precursor-frozen.yaml`, `pilot-evaluation.yaml`, `frozen.yaml`, all six protocols, all
checked-in validity/development/pilot/confirmation manifests, sandbox profiles, and
the conditional prefix manifest plus `WORLD_MODEL_DECISION.md`; their actual regular-file bytes are measured before and
after every publication. Nothing is off-ledger.

Before any typed phase starts or resumes, preflight computes projected occupancy without
double charging. It adds: (a) actual bytes of every finalized bundle outside the current
phase; (b) actual bytes of every validated finalized current-phase key; (c) the per-type
cap once for each exact current-phase key still missing; (d) the full 96 MiB live-writer
slot and full 96 MiB retained-orphan/quarantine slot exactly once each, regardless of
their current occupancy; and (e) actual tracked-evidence bytes plus only its remaining
32 MiB allowance. A recognized building tree occupies the live-writer slot and a
quarantine entry occupies the retained-orphan slot; its actual bytes are validated
against that slot but are never added again. Multiple building trees, multiple retained
orphans, an entry over its slot, or an unknown key fail closed. The exact projected
formula and every actual/missing key are written to preflight evidence. It requires both
the 8,688 MiB experiment cap and inherited 10 GiB/free-disk ceilings. Thus initial and
resumed preflights have the same maximum projection, and a completed key replaces rather
than supplements its reserved cap. No published artifact is deleted until final
decision; closing anonymous
adaptation truth after its aggregate seals is the sole named transient-capability
exception, and its exact regeneration is required after selector freeze. A cap or
timeout yields `INCONCLUSIVE`, never evidence against a model.

## 13. Frozen fields and pilot-derived margins/resources

The precursor contract freezes, before the NumPy validity gate, every value that
defines the task or available hypothesis space:

1. NumPy equations, pinned MuJoCo mapping, step/contact tolerances, and all analytic/
   physical/step-halving validity thresholds;
2. workspace, object, target, obstacle, mass, friction, and held-out parameter ranges;
3. probe policy, four-anchor rule, action interval/limits/phases/offsets/speed, and all
   identity/content digest encodings;
4. success/safety labels, actual/predicted scalar-cost components and weights, missing-
   output penalty, and all ties;
5. the complete W0 seed rule and W1 formula, weights, collision rule, and fallback form;
6. the three W3 and three W4 finite feature/degree/regularization/ensemble configurations;
7. the three W5 channel/PCA-dimension/tolerance/latent-transition/
   regularization configurations and PCA canonicalization;
8. calibration family/bins, uncertainty aggregation, threshold-fitting algorithm,
   fallback coverage rule, and failure-critic form;
9. split counts/roots, strata/weights, bootstrap seeds/mechanics, numerical solver
   tolerances, hard inherited resource caps, and every schema/command rule.

NumPy tuning/validation then chooses configurations/checkpoints only by the frozen
lexicographic key `regret, negative rank correlation, calibration error, model bytes,
configuration ID`; it creates no new numeric option. MuJoCo adaptation may fit only
selected linear output coefficients, the declared calibration-map coefficients, and
fallback/critic thresholds by the frozen algorithms. Those fitted values are sealed
before pilot evaluation.

The 20 untouched MuJoCo pilot-evaluation scenes set only: (a) co-primary, held-out,
W3, W5-versus-W4, shadow Brier/ECE ceilings, offline-family effects, calibration, and
failure-critic effect/non-inferiority margins; and
(b) measured model/context/inference-latency and scene-runtime ceilings. They cannot alter any
field in the preceding lists, any fitted coefficient/threshold, exclusions, or metric
definitions.

For each scientific endpoint, margin is
`ceil_to_unit(max(one_task_unit, 0.5 * paired_scene_sample_SD))`, computed only from
the 20 untouched MuJoCo pilot-evaluation scenes, with sample SD denominator `n-1`;
`ceil_to_unit(x)=ceil(x/unit)*unit`. Rank-correlation unit is `0.001`; probability/rate
unit is one anchor outcome over its fixed pilot denominator; regret/cost unit is the
smallest positive frozen cost quantum and bytes round to 1024. The two latency ceilings
use Section 9.6's separate p95 formula and 0.1 ms unit. Other measured resource limits
use `ceil_to_unit(1.25 * maximum_usage)` across only those 20 pilot-evaluation scenes and
must remain under the already frozen inherited caps. Zero
SD yields one unit; unattainable margins make the result `INCONCLUSIVE`, never clipped.
No pilot-evaluation statistic enters configuration selection or fitting.

For each shadow composition and held-out Brier/ECE endpoint, the absolute ceiling is
`ceil_to_unit(max_scene_metric + 0.5*sample_SD)` on pilot evaluation, with unit 0.001;
larger than 1.0 is unattainable and yields `INCONCLUSIVE`. Offline-family and critic
minimum effects use the preceding scientific-endpoint margin formula. These values are
computed for every predeclared endpoint even if a higher role later passes.

### 13.1 Complete precursor configuration appendix

The checked-in precursor protocol must contain exactly the values below. An
implementation plan may transcribe them but may not choose substitutes.

**World, roots, and integration.** Named PCG64 roots are the SHA-256-derived first
128 big-endian bits of the literal strings `exp06-r1-numpy-train`,
`exp06-r1-numpy-tuning`, `exp06-r1-numpy-validation`, `exp06-r1-mujoco-adaptation`,
and `exp06-r1-mujoco-pilot-evaluation`; revision 2 replaces `r1` with `r2` and shares
no ancestor. W0 uses the separate literal root `exp06-r1-w0` (or `r2` for revision 2).
The unseen confirmation root is generated only after freeze as already
specified. The workspace is `[-1.0,1.0]^2`; end-effector radius is 0.04 m; command
horizon is 1.0 s with 50 little-endian float64 planar-velocity rows at 0.02 s and
component clamp `[-0.25,0.25] m/s`. MuJoCo uses the experiment-local generated model
below with the P3-pinned runtime, timestep 0.002 s, ten physics steps per command, the
Euler semi-implicit integrator, gravity disabled, and the same initial state/action/cost
projection as NumPy.

**Exact seed and draw compiler.** A named literal root is the first 16 bytes of
`SHA256(UTF8(literal))`, interpreted big-endian. After evidence freeze the controller
calls `os.urandom(16)` exactly once for confirmation entropy, rejects a short/error
result, derives the root as the first 16 bytes of
`SHA256(canonical_json(["exp06-confirmation-root-v1",entropy.hex()]))`, destroys the
entropy, and publishes only the derived root in the committed confirmation manifest. No fallback
clock, UUID, PID, or library-global RNG is allowed. For every partition/stratum/ordinal,
the 64-bit `scene_seed` is the first eight bytes of
`SHA256(canonical_json(["exp06-scene-id-v1",root_hex,partition,stratum,ordinal]))`;
`scene_id` is its 16-lowercase-hex encoding. `probe_seed` uses the same tuple with domain
`exp06-probe-v1`. Any seed/ID collision invalidates the manifest rather than advancing
or resampling.

Each proposal ordinal `0..31` gets a fresh PCG64 seed from the first 16 big-endian bytes
of `SHA256(canonical_json(["exp06-scene-parameters-v1",root_hex,partition,stratum,
ordinal,proposal_ordinal]))`. The generator makes exactly these float64 calls in order:
`object_x, object_y, target_bearing, target_distance, target_yaw, mass_u, friction_u,
geometry_choice, disk_radius_u, rectangle_half_x_u, rectangle_half_y_u,
obstacle_choice, obstacle_side, object_yaw`; continuous draws use one
`Generator.random(dtype=float64)` and `low+(high-low)*u`, while choices use one
`integers(0,n,endpoint=False,dtype=uint64)`. Both disk and rectangle dimension draws and
both obstacle draws are consumed even when inapplicable. The named OOD stratum changes
only the stated interval/forced choice; every other call and position remains identical.
The first feasible proposal wins, all rejected proposal ordinals/reasons are recorded,
and exhaustion is `INVALID`. Candidate generation, bootstrap, ensemble members, and W0
each use their separately specified domain and a fresh generator; no generator object or
state crosses a scene, proposal, model member, anchor, or phase.

**Experiment-local MuJoCo model.** P3 contributes only the validated MuJoCo runtime.
Experiment 06 owns `assets/push_t_template.xml` and a pure
`build_mjcf(scene_parameters) -> bytes` generator. The template and generator source
hash freeze before NumPy validity. Output is UTF-8/LF with one trailing newline; element
and attribute order are literal template order, all inserted finite floats use
lowercase `format(value, ".17g")`, negative zero normalizes to `0`, and XML escaping is
the standard five-character mapping. No XML pretty-printer or platform serializer may
rewrite evidence bytes.

The generated root is `mujoco model="exp06_push_t_v1"`. Its option is exactly
`timestep="0.002" gravity="0 0 0" integrator="Euler" cone="pyramidal"
jacobian="dense" solver="Newton" iterations="20" tolerance="0" impratio="1"`;
coordinates are local, angles radians, and inertia derives from geoms. All dynamic
joints have `damping="0" armature="0" limited="false"`. Contact geoms use
`condim="3" solref="0.002 1" solimp="0.9 0.95 0.001"`, restitution zero,
`contype="1" conaffinity="1"`, and friction tuple `(scene_friction,0.005,0.0001)`.
There is no gravity, floor, hidden actuator, sensor, equality, tendon, plugin, or
callback.

The worldbody order is fixed: noncolliding target site; mocap end-effector; dynamic
object; optional obstacle; walls `-x,+x,-y,+y`. The end effector is a vertical cylinder
of radius `0.04`, half-height `0.02`, center z `0.02`. The object body has ordered joints
`object_x` slide `(1,0,0)`, `object_y` slide `(0,1,0)`, and `object_yaw` hinge `(0,0,1)`;
its geom is either a cylinder `(radius,0.02)` or box `(half_x,half_y,0.02)` with the
sampled total mass. Slide-joint `frictionloss` is exactly
`scene_friction*mass*9.81/sqrt(2)` and yaw `frictionloss` is
`scene_friction*mass*9.81*max(h((1,0)),h((0,1)),0.01)`. An obstacle segment becomes one
static box centered at the endpoint midpoint, half-size
`(segment_length/2,0.02,0.02)`, yaw `atan2(dy,dx)`. The four static wall boxes have
inner faces exactly at workspace `+/-1`, thickness `0.04`, and overlap corners by
`0.04`. Target and all noncontact markers have `contype="0" conaffinity="0"`.

There are no MuJoCo actuators (`nu=0`). At every 0.002-second physics step the executor
holds the current 0.02-second action row, updates mocap x/y by `0.002*command`, leaves
mocap z/quaternion fixed, then calls exactly one `mj_step`; thus each command row owns
ten steps. Commands are never recomputed from resulting candidate state. The anchor
restore first calls `mj_resetData`, then assigns time; qpos in exact order
`object_x,object_y,object_yaw`; qvel in exact order
`object_vx,object_vy,object_omega`; empty act; mocap position/quaternion; and userdata
`mass,friction,geometry_code,dim_0,dim_1,dim_2,obstacle_present,model_revision`, then
calls one `mj_forward`. Every candidate receives an independent byte-equal restored
anchor; no `mjData` instance or contact cache crosses candidates.

`model_sha256=SHA256(build_mjcf(scene_parameters))` is scene-specific. The precursor
protocol binds template/generator hashes and the complete parameter-to-MJCF mapping;
each scene manifest binds model bytes, digest, P3 package version/distribution hash,
and restore-vector digest. Validation rebuilds bytes independently, loads them through
the P3-pinned package, checks `nq=3,nv=3,nu=0,nmocap=1,nuserdata=8`, named joint/geom
order, options, and round-trip restore before W2. Alternate, user-supplied, or P3-smoke
model bytes are rejected.

NumPy also steps at 0.002 s. The velocity-controlled end effector takes the commanded
velocity exactly and updates position after contacts. Object linear speed loses
`friction*9.81*dt` toward zero each unforced step; angular speed loses
`friction*9.81*dt/max(h((1,0)),h((0,1)),0.01)` toward zero. For a contact with unit
normal n from actuator/static body into object, penetration delta, and precontact
relative normal speed `v_n` defined positive when closing, normal impulse is
`j_n=max(0,mass*(v_n+0.20*delta/dt))`; tangential impulse opposes relative tangent and
is clipped to `friction*j_n`. Static-body inverse mass is zero. Apply impulse, then
semi-implicit position/yaw update, then the minimum positional projection needed to
remove residual overlap. Contacts sort exactly `EEF_OBJECT`, obstacle ID, then wall
`-x,+x,-y,+y`; rectangle features sort local vertex then edge index. Restitution is
zero and no other damping, compliance, substep, or solver iteration exists.

Each scene samples object center uniformly from `[-0.30,0.30]^2`; target bearing
uniformly from `[0,2*pi)`, distance from `[0.25,0.45]`, and target yaw uniformly from
`[-pi,pi)`; robot center is the object
center minus 0.20 m on that bearing. ID mass is `[0.8,1.2]` kg and ID sliding friction
is `[0.40,0.60]`. ID geometry is equiprobable disk radius `[0.055,0.075]` m or rectangle
half-extents `x=[0.050,0.070], y=[0.040,0.060]` m. An ID obstacle is absent with
probability 0.5, otherwise it is one 0.04 m-thick segment parallel to u with endpoints
`midpoint +/- 0.15u`, whose center is displaced by `+0.18v` for `LEFT` or `-0.18v`
for `RIGHT`. Initial yaw is uniform `[-pi,pi)`; all velocities are zero. Up to 32 named
proposal ordinals may be tried to obtain in-bounds, nonpenetrating initial geometry;
exhaustion makes the scene invalid and never changes the seed.

MASS_OOD alone replaces mass by `[1.40,1.60]`; FRICTION_OOD alone replaces friction by
`[0.75,0.90]`; GEOMETRY_OOD alone uses an equiprobable disk radius `[0.085,0.095]` or
rectangle half-extents `x=[0.080,0.095], y=[0.030,0.040]`; OBSTACLE_OOD alone always
uses the withheld perpendicular `CENTER_BARRIER` segment with endpoints
`midpoint +/- 0.25v`. Every nonnamed factor remains
ID. Stratum membership is validated from generated parameters, not trusted from a
label.

The two-second probe uses four 0.5-second phases: move to the target-opposite contact,
push 0.10 m toward target, retreat 0.08 m, then move 0.08 m along the positive
perpendicular. The four anchors are the immutable post-step snapshots at 0.50, 1.00,
1.50, and 2.00 s. A zero target displacement uses world `+x`; the positive
perpendicular is `(-u_y,u_x)`.

**Candidate factory.** Let `c` be object center, `g` target center, `u=unit(g-c)`,
`v=(-u_y,u_x)`, and `h(n)` the exact support radius: disk radius or
`abs(n_x)*half_x+abs(n_y)*half_y` for the oriented rectangle after rotating n into its
local frame.
Let `contact(n,offset)=c-(h(n)+0.01)n+offset`. The frozen waypoint/phase table is:

| Strategy | Waypoints `(phase_end_s, end-effector waypoint)` | Speed multiplier |
|---|---|---:|
| DIRECT | `(0.35, contact(u,0v)); (1.00, g-(h(u)-0.02)u)` | 1.0 |
| LEFT_EDGE | `(0.35, contact(u,+0.75h(v)v)); (1.00, g+0.25h(v)v)` | 1.0 |
| RIGHT_EDGE | `(0.35, contact(u,-0.75h(v)v)); (1.00, g-0.25h(v)v)` | 1.0 |
| BELOW | `(0.35, contact((0,1),0v)); (1.00, g-(0,h((0,1))-0.02))` | 1.0 |
| DIAGONAL | `(0.25, c-(h(u)+0.08)u+0.60h(v)v); (0.55, contact(u,+0.60h(v)v)); (1.00, g)` | 1.0 |
| RETREAT_REPOSITION | `(0.20, e_0-0.08u); (0.55, contact(u,0v)); (1.00, g)` | 1.0 |
| SLOW_CONSERVATIVE | the DIRECT waypoints | 0.5 |
| HOLD | `(1.00,e_0)` with exact zero commands | 0.0 |

At each command tick, the non-HOLD controller emits the component-clipped
`multiplier*(waypoint-current_eef)/max(0.02, phase_end-current_time)` for the current
phase. Phase boundaries are half-open and the later phase owns equality. No feedback
from a candidate branch enters another candidate. The eight byte trajectories and
content hashes must be distinct before physics, as Section 3.3 requires.

**Truth, cost, and labels.** Success means terminal object-center error <=0.05 m and
wrapped yaw error <=0.20 rad with no unsafe event. Collision is true when object or
end effector contacts an obstacle/wall with normal impulse >0.05 N-s. Unsafe is true
for workspace escape, penetration >0.002 m, nonfinite state, or impulse >2.0 N-s.
Terminal failure is `not success`. Action energy is `sum_t ||a_t||^2*0.02`.
The cost weights are `w_position=1.0`, `w_orientation=0.10`, `w_collision=2.0`,
`w_energy=0.01`, `w_failure=4.0`, and `w_success=1.0`; no hidden penalty exists.
`predicted_progress=clip(1-position_error/max(initial_position_error,0.05),-1,1)`.

**W1 and model grids.** W1 integrates the known end-effector commands without contact.
Let `q=sum_t a_t*0.02`, `alignment=max(0,dot(unit(q),u))` (zero for `q=0`), and
`push=max(0,dot(q,u)-max(0,dot(c-e_0,u)-h(u)-0.04))`. Its predicted object center is
`c+alignment*push*u`, yaw is unchanged, collision probability is the exact binary
intersection of the end-effector command polyline with obstacles expanded by 0.04 m,
unsafe probability is the binary workspace-exit test, terminal-failure probability is
the complement of its predicted success label, and energy is the known action energy.

The ordered privileged-state vector is end-effector `(x,y,vx,vy)`, object
`(x,y,yaw,vx,vy,omega)`, target `(x,y,yaw)`, mass, friction, one-hot geometry, geometry
dimensions, and obstacle-present/endpoints. W3 appends strategy one-hot, endpoint
displacement, path length, per-axis mean/standard-deviation/minimum/maximum velocity,
the six-column contact-side one-hot in order
`TARGET_OPPOSITE,LEFT,RIGHT,WORLD_BELOW,TARGET_CORNER,NO_CONTACT`, and obstacle-line
intersection. DIRECT/SLOW_CONSERVATIVE/RETREAT_REPOSITION map to `TARGET_OPPOSITE`,
LEFT_EDGE to `LEFT`, RIGHT_EDGE to `RIGHT`, BELOW to `WORLD_BELOW`, DIAGONAL to
`TARGET_CORNER`, and HOLD to `NO_CONTACT`. The privileged vector has exactly 25
columns and the W3 base vector exactly 51. W4 instead appends all 100 action
scalars in time-major order plus strategy one-hot. W5 receives those same action
scalars and a six-channel 64-by-64 orthographic raster over `[-1,1]^2`: end-effector,
object, target, and obstacle binary occupancy, followed by object-mask times `sin(yaw)`
and `cos(yaw)`. Pixel centers own boundaries, rows run world y descending, columns x
ascending, channels are last, and flattening is C order. No antialiasing, texture,
lighting, hidden parameter, future frame, or renderer metadata is present.

The geometry one-hot order is `(disk,rectangle)`. Geometry dimensions are
`(disk_radius,rectangle_half_x,rectangle_half_y)` with every inapplicable entry exactly
zero. Obstacle fields are `(present,x1,y1,x2,y2)` with four exact zeros when absent and
lexicographically ordered endpoints when present. Strategy one-hot order is the Section
3.2 order. These conventions make the privileged vector and every base-feature column
count/order mechanical.

Each variant has exactly these three configurations; all ridge intercepts are
unregularized and all feature columns use train-only z-scores with zero-variance columns
fixed to zero:

| ID | W3 | W4 | W5 | bootstrap ensemble | calibration |
|---|---|---|---|---:|---|
| CFG01 | degree-1 stated features, ridge `1e-3` | degree-1 W4 base vector, ridge `1e-3` | PCA 16, degree-1 latent transition, ridge `1e-3` | 4 | identity clip |
| CFG02 | degree-2 interactions, ridge `1e-2` | W4 base vector degree-1 terms plus every `x_i*x_j` for `i<=j`, ridge `1e-2` | PCA 24, degree-1 transition plus action-latent interactions, ridge `1e-2` | 8 | monotone PAV, 8 equal-count bins |
| CFG03 | degree-3 univariate plus degree-2 interactions, ridge `1e-1` | CFG02 terms plus every univariate `x_i^3`, ridge `1e-1` | PCA 32, degree-2 transition, ridge `1e-1` | 16 | monotone PAV, 16 equal-count bins |

The W4 base vector `x` is exactly the ordered privileged-state vector, followed by all
100 raw action scalars in time-major `(tick,x,y)` order, then the eight strategy one-hot
columns. No action moment replaces or augments those scalars. CFG01 contains intercept
and every `x_i`; CFG02 contains those terms then the stated quadratic terms; CFG03
contains CFG02 then the stated cubes. Polynomial expansion order is total degree, then
lexicographic source-column indices; no other W4 term is present. W4's ten output heads
are the ordered one-second dynamic-state deltas frozen in Section 6.2.

For W5, the selected PCA dimension is also the current/future latent dimension: CFG01,
CFG02, and CFG03 use 16, 24, and 32 respectively. Its transition input is current latent,
the same 100 raw action scalars, and strategy one-hot. Degree 1 is affine in those
columns; action-latent interactions are every latent-by-action-scalar product; degree 2
is every pair `x_i*x_j` for `i<=j` over the complete transition input. Term order uses
the same rule and no other latent or action summary exists. Bootstrap member roots hash protocol, variant, configuration,
and member ordinal. The adaptation fallback-threshold candidates are `-inf`, the 25th,
50th, and 75th nearest-rank adaptation uncertainty, and `+inf`; choose minimum paired
regret subject to zero unsafe selections and coverage >=0.50, then lower threshold.
The failure-critic threshold grid is exactly `0.00,0.05,...,1.00`; choose maximum recall
subject to precision >=0.90 and zero unsafe veto, then higher threshold. Empty-positive
precision is zero.

**Exact fit, ensemble, adaptation, and calibration compiler.** A training row is one
candidate branch. The 96 NumPy training scene IDs sort ascending and each scene expands
to its 32 rows in `(anchor_id,candidate_id)` order. Global preprocessing and PCA fit once
on those 3,072 unique rows; population mean/variance use divisor `N`, scale is
`sqrt(variance)`, and an exactly zero scale maps the complete standardized column to
zero. No tuning, validation, or MuJoCo row enters those statistics. For W3, CFG01 is the
intercept plus its 51 ordered base columns, CFG02 adds every `x_i*x_j` for `i<=j`, and
CFG03 adds those terms plus every `x_i^3`; term order is the W4 rule. W4 and W5 use the
exact terms already stated above.

For member ordinal `m`, the bootstrap seed is the first 16 big-endian bytes of
`SHA256(canonical_json(["exp06-model-bootstrap-v1",protocol_sha256,variant,
configuration,m]))`. A fresh `Generator(PCG64(seed))` makes exactly one vectorized call
`integers(0,96,size=96,endpoint=False,dtype=uint64)`. Draw order is retained; each drawn
scene occurrence contributes all 32 rows in canonical intra-scene order. There is no
row bootstrap, stratification, deduplication, balancing, rejection, or second draw.
The draw vector is serialized in `training-manifest.json` and independently regenerated.

For feature matrix `X` with `n` rows and `p` columns, ordered multi-output target matrix
`Y`, and positive frozen ridge value `lambda`, let `xbar` and `ybar` be float64
arithmetic means over the member's ordered row multiset, `Xc=X-xbar`, and `Yc=Y-ybar`.
Fit by the smaller exact ridge system. For `p<=n`, compute

```text
A = Xc.T @ Xc + lambda*identity(p)
L = numpy.linalg.cholesky(A)
coef = solve(L.T, solve(L, Xc.T @ Yc))
```

For `p>n`, compute the dual system

```text
A = Xc @ Xc.T + lambda*identity(n)
L = numpy.linalg.cholesky(A)
alpha = solve(L.T, solve(L, Yc))
coef = Xc.T @ alpha
```

and in both cases finish with

```text
intercept = ybar - xbar @ coef
```

Operations occur in that written left-to-right matrix order with float64 identity and
arrays. A nonpositive/nonfinite Cholesky diagonal or factorization failure invalidates
the fit; no jitter or solver substitution is allowed. The KKT residual
`R=Xc.T@(Xc@coef-Yc)+lambda*coef` must satisfy
`max(abs(R)) <= 1e-9*max(1,max(abs(Xc.T@Yc)))`. There is no `rcond`, pseudoinverse,
iterative solver, class weight, or regularization on the intercept. Inputs and outputs
must be finite, shapes must match the manifest, and two fresh processes under the frozen
BLAS/CPU/thread profile must produce byte-identical coefficient/intercept arrays or the
environment is invalid.
Continuous heads retain their finite ridge values. Each binary-head member output is
clipped once to `[0,1]` before calibration; the four probability heads are independent
and are not renormalized to sum to one.

MuJoCo adaptation preserves each selected member's original 96-entry NumPy bootstrap
draw vector. For that member it appends each of the 20 adaptation scenes exactly once in
ascending scene-ID order, with all 32 rows per scene, yielding 116 equal-weight scene
occurrences and 3,712 ordered rows. It then reruns the exact centered-SVD formula using
the frozen NumPy preprocessing and refits only the Section 5 permitted heads. It does
not bootstrap adaptation scenes, rebalance domains/classes, or change a member root.
W5 `latent_next` and every other forbidden member remain byte-identical. Thus “union”
means one fixed NumPy member multiset followed by one copy of every adaptation scene,
not an implementation-selected mixture.

Before calibration, a probability prediction is the arithmetic mean of the memberwise
clipped values. CFG01's map is exact identity with float64 breakpoints `[0.0,1.0]` and
values `[0.0,1.0]`. For CFG02/CFG03 and each variant/probability head, sort the 640
adaptation rows by `(precalibration_probability,scene_id,anchor_id,candidate_id)` and
split by stable row position into respectively 8 bins of 80 or 16 bins of 40. Each bin
starts as `(mean_probability,mean_binary_label,row_count)`. Merge adjacent equal-x bins
first using count-weighted x/y means. Then run weighted PAV left-to-right: while the
preceding y is strictly greater than the following y, replace the pair by their
count-weighted x/y mean and summed count and step back; equality does not merge.
The remaining x values are strictly increasing. Serialize them as breakpoints and the
fitted y values as values, prepending `0.0` with the first value and/or appending `1.0`
with the last value when absent. If one PAV block remains, serialize breakpoints
`[0.0,1.0]` with its value repeated. Calibration is exactly
`numpy.interp(clip(p,0,1),breakpoints,values,left=values[0],right=values[-1])`.
No smoothing, tie jitter, cross-head pooling, or extrapolation is allowed.

At evaluation, apply the head-specific frozen map to each clipped member probability,
then take the arithmetic member mean. Vector/continuous predictions are arithmetic
member means. Each member's calibrated heads and continuous/vector values produce its
own scalar cost by Section 6.2. The envelope `uncertainty` is the population variance
`sum((cost_i-mean_cost)^2)/M`; per-head failure uncertainties use the same divisor and
are descriptive sidecar fields. All reductions run in member-ordinal order. The
fallback threshold uses only envelope cost uncertainty. The critic score is
`max(collision,terminal_failure,unsafe)` after calibration, with a positive label when
any corresponding binary truth is true. Final calibration maps and fallback/critic
thresholds fit only adaptation rows. NumPy tuning/validation configuration keys use
the uncalibrated clipped ensemble probabilities for their frozen calibration-error term;
they fit no temporary or final calibration map.

**Validity and calibration constants.** Analytic absolute/relative tolerance is
`1e-12`; mirror endpoint tolerance is `1e-10`; maximum penetration is `0.002 m`;
unforced energy increase tolerance is `1e-12 J`; step-halving endpoint L-infinity
tolerance is `0.001`, per-component/cost tolerance is `0.001`, labels must match
exactly, and allowed Kendall disagreement count is zero. PCA tie tolerance is Section
6.4's `1e-12` relative rule. Fixed-bin ECE uses ten equal-width probability bins
`[0,.1),...,[.9,1]`, empty bins contribute zero, and Brier averages the exact binary
target. These values, all schemas, and the 80-case validity grid freeze before the
first validity run.

## 14. Verification design

Tests cover:

- create-only P7 P3-gate adapter schema/command/commit barrier, exact P2/P3 output and
  MuJoCo distribution/smoke binding, alternate-runtime refusal, and refusal of any model
  bytes not rebuilt by the Section 13.1 generator;
- exact `A00..A15/P00..P23/S00..S39` NumPy analytic, physical, mirror, and
  five-prototype step-halving gate, 64 MiB bundle, timeout behavior, and hand fixtures;
- exact K=8 IDs, globally unique candidate IDs, eight distinct ID-independent content
  digests and bytewise trajectories, identity-bound cross-link hashes, independent
  regeneration, and invalid duplicate/nondeterministic disposition;
- immutable snapshots, exact domain-separated scene/probe/proposal/W0 PCG64 calls and
  collision refusal, named RNG independence, pinned numeric/thread environment,
  tolerance-group PCA, canonical JSON/Parquet/NPZ, and fresh-process byte identity;
- split ancestry/content leakage across all five partitions;
- fit spies proving preprocessing/PCA/models/calibration see only allowed partitions,
  exact scene-bootstrap PCG64 draws, centered primal/dual Cholesky ridge bytes and KKT
  bound, equal scene/row weights,
  member-preserving adaptation union, population ensemble reductions, per-head
  clip/equal-bin/PAV/interpolation calibration, exact permitted adaptation heads,
  byte-identical W5 `latent_next`, composed adapted model hashes, and absence of
  unchanged heads from the adaptation archive;
- precursor contract freeze before NumPy validity, mechanical tuning/validation,
  adaptation-only output refit/calibration, pilot-evaluation-only margins/resources,
  and nonexistent unseen confirmation before the evidence freeze;
- W0-W5 input boundaries, phase-global full-snapshot commitments, projection digest
  links, exact 400/1,600-row pilot/confirmation selector freezes, absence of every
  phase truth descriptor until all selectors exit, permanent no-selector-after-freeze,
  selector-freeze restart and truth-only resume, Linux Landlock/seccomp and macOS
  Seatbelt enforcement probes, anonymous adaptation truth/regeneration equality, and
  hostile absolute/relative/symlink/hard-link/descriptor/ptrace access to current/prior-
  scene truth, pilot/confirmation result roots, MuJoCo/import, socket, and subprocess;
- exact global prediction IDs, prediction envelope fields, finite/range checks, scalar
  cost components, all exact Arrow types/order/nullability, NPZ/model member grammars,
  domain-separated digest preimages, observation-ID bijection, shared
  `WorldModelPrediction` round-trip/vector keys/hashes and exact no-extra-digest
  prediction/selection event payload schemas,
  ten-field W4 state and per-configuration W5 latent dimensions, W3/W4/W5 derivation,
  and universal tie ordering;
- PCA sign and equal-singular-subspace canonicalization;
- average-rank Spearman plus both constant-actual/predicted cases and regret tolerance;
- exact 16-draw-per-stratum 0.20 bootstrap aggregation,
  co-primary/held-out/W3/W5-vs-W4/shadow/offline families, all percentile indices,
  equality boundaries, and missing rules;
- learned+W1 fallback as the sole selector-protocol result, raw metrics descriptive,
  exact promoted-P4 `10 Hz, 300 ms` eligibility, velocity-to-absolute-EEF adapter
  bytes/IDs/hashes/timing, field-exact shared Observation/ObjectBelief/RobotState/
  SkillSpec/Pose/Predicate request bytes against the promoted P4 reference factory,
  and no action authority before all 20 conditional
  prefix-conformance cases pass;
- scientific endpoint pass/reject/unresolved boundaries and joint classification before
  the mechanically ordered mutually exclusive selector/critic/shadow/offline roles,
  with separate lifecycle/artifact/scientific/blocker/promotion states;
- unchanged canonical rollout, exact scene sidecars/cross-links/replay, disjoint
  scene/training/aggregate schemas and roots, manifest self-exclusion, corruption,
  the single 4+12 MiB monotone evidence staging tree, descriptor-relative no-follow
  publication, exact restart continuation/quarantine, and foreign/ambiguous-temp refusal;
- exact repo-root lifecycle/selector/truth/scene/training/aggregate/report commands and
  keys, six phase-protocol schemas/counts, type-mixing refusal,
  create-only validate-and-skip resume, single-root sibling evidence staging, exact
  32/64 MiB configuration-specific training caps, adaptation coefficient arithmetic,
  8,688 MiB retained arithmetic, initial/resumed missing-key preflight without current-
  phase or scratch-slot double charging, and per-type wall/size ceilings; and
- exact five-warmup/20-repetition single/K=8 latency timing and nearest-rank gates,
  serial latency, offline/no-network/no-CUDA/no-physical/no-remote, clean tree, full
  tests, source audit, secret scan, artifact size, and diff checks.

## 15. Dependencies and downstream boundaries

NumPy, PyArrow, and PyYAML remain the only model/data dependencies
(`pyproject.toml:5-15`). MuJoCo is consumed only through the complete passing P3 pinned
package/runtime lock and compatibility output; all Push-T MJCF/model bytes remain
experiment-local and bind to the Section 13.1 generator. A missing/failed P3 gate is
`BLOCKED`; it cannot be replaced by NumPy confirmation.

P4 is not a prerequisite for the Experiment 06 ranking claim. It becomes a mandatory
immutable input only to the postdecision executor-prefix conformance extension, which
binds P4's frozen protocol and artifact digests and otherwise remains absent. A missing,
stopped, changed, or incompatible P4 output leaves action routing ineligible without
altering P7's already sealed scientific result.

Experiment 07 may reuse the frozen planar task, scenario/candidate factory, cost
components, IDs, and metrics regardless of the P7 authority result
(`docs/superpowers/specs/2026-08-22-reflect-lite-autonomous-run-design.md:102-106`).
R1 transfer consumes only a separately promoted prediction/critic/selector protocol,
and no critic, shadow, or action-routing protocol can be promoted unless this
experiment's canonical selector result is `SUPPORTED` as well as satisfying its own
separately reviewed gate;
W2 never transfers and W4 privileged input requires an explicit adapter. Mini-Reflect
may consume a promoted selector protocol only as shadow output until the exact
executor-prefix conformance receipt exists; even then, action routing requires a
separately reviewed integration adapter. Executor validation and W1 fallback remain
mandatory (`Reflect Lite Research Program.md:2454-2537`).

Only the smallest validated prediction envelope and selector/critic invariant may be
promoted. NumPy/MuJoCo environments, candidates, costs, models, PCA, thresholds,
plots, and bundles remain experiment-local, matching the program's interface boundary
(`Reflect Lite Research Program.md:3153-3181`).

## 16. Parallel-safe preparation and decision output

Preparation may use ownership-isolated world/candidate, dataset/split, baseline,
learned-model, evaluator, and artifact/replay workstreams. Candidate/state schemas,
IDs/both action hashes, scalar cost, W1, finite model/PCA grids, typed bundle schemas,
NumPy validity fixtures/tolerances, and MuJoCo mapping freeze before the validity gate
or parallel fitting. NumPy mechanical selection may run after that contract freeze.
MuJoCo adaptation, pilot evaluation, evidence freeze, confirmation-manifest generation,
confirmation, serial latency, role decision, and promotion remain serial orchestrator
operations.

`WORLD_MODEL_DECISION.md` links immutable pilot/confirmation bundles and records the
separate lifecycle, validity, blocker, scientific, role, and promotion states. It
reports both canonical primaries, all strata/families, W3 and W5/W4 decisions,
fallback/calibration/latency, and rejected roles. Exactly one reachable role is named,
based on held-out ranking, regret, calibration, and latency rather than visual
plausibility (`Reflect Lite Research Program.md:2048-2062`).

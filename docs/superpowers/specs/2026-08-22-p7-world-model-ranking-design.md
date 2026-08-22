# P7 World-Model Candidate-Ranking Experimental Design

**Date:** 2026-08-22

**Status:** Approved design; no implementation plan

**Scope:** Reflect Lite Experiment 06

## 1. Decision and authority boundary

Experiment 06 tests whether compact learned prediction improves the ordering and
selection of eight fixed planar-pushing candidates. NumPy supplies a deterministic
precursor used for generator/model development, training, tuning, validation, and
physical sanity checks. It does not produce canonical co-primary evidence.

The P3-pinned MuJoCo package, model bytes, version, source lock, and compatibility
decision are mandatory prerequisites. MuJoCo is the sole exact rollout ground truth
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
MuJoCo pilot. On adaptation seeds only, W3/W4/W5 linear output coefficients are refit
once on the union of NumPy training and MuJoCo adaptation rows; the feature/latent
transition, input preprocessing, PCA, and feature heads remain fixed. Calibration maps
and fallback thresholds fit adaptation seeds only under the already selected method.
No other parameter may use MuJoCo adaptation. Pilot-evaluation seeds validate the
state/action mapping and set only margins/resource ceilings once; they cannot trigger
refit, recalibration, model selection, task/cost/W1 changes, or exclusions. The whole
pilot is labelled exploratory and cannot support a claim.

Only after implementation, model, calibration, P3 source, protocol, and MuJoCo pilot
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

Train-only statistics include normalization, feature maps, PCA, ensemble resamples,
and class weights. Tuning mechanically ranks only frozen-grid configurations by the
frozen key; validation mechanically selects NumPy checkpoints and the declared
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
descriptor or discoverable path. For MuJoCo pilot-evaluation and confirmation,
all selector outputs are validated and sealed before canonical branch truth exists.
Only then does the orchestrator launch a separate pinned-MuJoCo truth process, and only
after truth seals does it launch the scorer. A selector process is never alive while a
truth descriptor or truth path exists. NumPy training and MuJoCo adaptation are the
only phases allowed to consume their own declared training targets; their fitted
outputs seal before any evaluation selector runs.

### W0 — random

Counter-based PCG64 chooses uniformly from K=8 using only W0 root, scene ID, and anchor
ID. W0 emits a selection, not a prediction order.

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
one newline. Parquet uses the pinned PyArrow version, explicit schema/column order,
frozen row order, one full-table row group, no dictionary encoding, no compression,
no statistics, and data-page version 1.0. Canonical NPZ is a lexicographically ordered
ZIP_STORED archive: every member is an explicit little-endian C-order `.npy` v2.0
stream with timestamp `1980-01-01T00:00:00`, mode `0600`, no extra/comment fields, and
no duplicate names. Golden fixtures require byte identity across two fresh processes;
any mismatch invalidates the environment before evidence generation.

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

W3-W5 use deterministic scene-seed bootstrap ensembles. Cost uncertainty is ensemble
variance; failure uncertainty is probability variance. The MuJoCo adaptation half fits
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

## 10. Separate states and ordered role mapping

Lifecycle is `DRAFT -> CONTRACT_FROZEN -> NUMPY_VALIDATED -> NUMPY_SELECTED ->
MUJOCO_ADAPTATION -> MUJOCO_PILOT_EVALUATED -> EVIDENCE_FROZEN -> CONFIRMATION ->
DECISION -> PROMOTED | STOPPED`. Artifact state is separately `VALID | INVALID`;
scientific result is `SUPPORTED | NOT_SUPPORTED | INCONCLUSIVE`; prerequisite/resource
state is `READY | BLOCKED`; promotion state is `PROMOTED | STOPPED`. Invalid evidence
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
   pass. A critic may only replace the learned choice with W1 and cannot rank or
   introduce another action.
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
`BLOCKED` cannot promote. Only `VALID + SUPPORTED + READY + CANDIDATE_SELECTOR` promotes
selector authority. A valid critic gate may separately promote only the critic/veto
interface when the independent candidate-ranking result is `NOT_SUPPORTED`; under an
`INCONCLUSIVE` candidate-ranking result it is reported but remains unpromoted.

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

The prediction event payload contains integer `observation_id`; string `prediction_id`, `scene_id`, `anchor_id`,
`candidate_id`,
`strategy_id`, `action_content_sha256`, `action_sha256`, `model_id`, and the
prediction-envelope digest. The selection event contains the same observation/scene/
anchor IDs plus selected `prediction_id`, `candidate_id`,
`strategy_id`, both action digests, `model_id`, selection-row digest, and fallback reason.
The values are copied from sealed sidecar rows; events cannot synthesize or normalize
identities during publication.

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

- `EvidenceBundleWriter` accepts only already sealed generator, selector, and scorer
  component descriptors; copies them into one sibling temporary tree; invokes all
  validators; writes the manifest; fsyncs; and performs one absent-destination rename.
- `validate_evidence_bundle` validates every canonical rollout first, then exact
  sidecar schemas, hashes, IDs, counts, action regeneration, event ordering, oracle
  isolation attestations, and all cross-links. Validation has no repair mode.
- `replay_evidence_bundle` consumes only the finalized bundle and returns canonical
  reconstructed selector/anchor state plus recorded metric inputs. It cannot load a
  simulator/model or change a score.

For evidence scenes, the generator returns one canonical full snapshot as immutable
bytes to the orchestrator. The orchestrator computes `generator_snapshot_sha256` in
memory, derives each truth-free variant-specific selector projection, and seals each
projection with exact fields `scene_id,anchor_id,projection_kind,projection_sha256,
generator_snapshot_sha256,candidate_action_hashes`. The full snapshot bytes remain only
in orchestrator-owned memory: no path or descriptor for them exists, and no selector
inherits their buffer or file descriptor. Each selector receives only its one read-only
projection descriptor plus an absent output descriptor, with `close_fds` and no
simulator/truth import.

After every selector process exits, its output validates and seals, and every selector
descriptor closes, the orchestrator create-only materializes a separate full truth
descriptor from those retained bytes. `generator-snapshot.json` has exact keys
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
projection from the full descriptor and requires byte/hash equality.

`projection_sha256s` is an array sorted by `(anchor_id,projection_kind)` whose rows have
exact keys `anchor_id,projection_kind,sha256`. `state_member_keys` is an array sorted by
anchor ID whose rows have exact keys `anchor_id,member_key`; `state_layouts` is an array
in byte-offset order whose rows have exact keys `name,offset,count,shape,dtype`. Unknown
keys, overlapping/gapped offsets, or a member length different from the layout fail.

Only then does the orchestrator launch pinned MuJoCo with this full truth descriptor;
it never launches truth from a selector projection. It seals candidate truth/W2 and
finally launches the scorer with separate read-only selector and truth descriptors.
Reversing this order, keeping a selector alive, materializing the truth descriptor
early, or finding a current-scene truth path at selector launch invalidates the scene. On a crash
before truth materialization the unpublished scene is rerun from its sealed seed; the
in-memory snapshot is never recovered from selector output. The writer starts only
after generator, selector, and scorer components validate, so co-location in the
finalized evidence bundle cannot become a preselection truth channel.

The assembler writes a sibling temporary bundle, validates every canonical rollout and all
sidecars, fsyncs files/directories, and atomically renames into an absent destination.
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
  pca.npz | empty marker
  model.npz
  evaluation-predictions.parquet
  fit_metrics.json
  training-input-manifest.json
  training-manifest.json

aggregate-bundle/
  input-scene-manifest.json
  aggregate_metrics.json
  margins-resources.json | empty marker
  adapted-models.npz | empty marker
  calibration-output.npz | empty marker
  decision.json | empty marker
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
rename-no-replace followed by parent fsync. No safety decision relies on `Path.resolve`.

During the creating process, cleanup may remove only the temporary tree whose descriptor
and inode have been continuously held since its exclusive creation. After restart,
held-inode continuity is impossible: recovery opens one exact owned temporary entry
no-follow, validates its owner/key/manifest prefix without following descendants, and
renames it descriptor-relatively into an absent `quarantine/<bundle-key>.<nonce>`.
Restart never deletes or publishes an orphan. Foreign, malformed, multiple, symlinked,
or changing entries fail closed. Quarantine remains evidence-bearing and byte-accounted;
no new phase begins until an explicit review disposition is recorded.

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

One scene bundle contains exactly four anchors and 32 candidate branches. Exact command
shapes, including derived roots, are:

```text
uv run python experiments/06_world_model/run_scene.py \
  --protocol experiments/06_world_model/configs/frozen.yaml \
  --bundle-key scene:r1:mujoco-confirmation:MASS_OOD:0000000000000017 \
  --output-root results/06_world_model/scenes --headless \
  --max-anchors 4 --max-candidates 32

uv run python experiments/06_world_model/train.py \
  --protocol experiments/06_world_model/configs/precursor-frozen.yaml \
  --bundle-key training:r1:W4:CFG02 \
  --scene-root results/06_world_model/scenes \
  --output-root results/06_world_model/training --headless --max-configurations 1

uv run python experiments/06_world_model/validate_numpy.py \
  --protocol experiments/06_world_model/configs/precursor-frozen.yaml \
  --bundle-key aggregate:r1:numpy-validity:all \
  --output-root results/06_world_model/aggregates --headless --max-cases 80

uv run python experiments/06_world_model/aggregate.py \
  --protocol experiments/06_world_model/configs/pilot-evaluation.yaml \
  --bundle-key aggregate:r1:mujoco-pilot-evaluation:all \
  --scene-root results/06_world_model/scenes \
  --training-root results/06_world_model/training \
  --output-root results/06_world_model/aggregates --headless \
  --max-training-bundles 0 --max-scenes 20 --max-input-aggregates 1
```

The same aggregate shape uses `--protocol
experiments/06_world_model/configs/frozen.yaml` and `--max-scenes 80` for
`aggregate:r1:mujoco-confirmation:all`, with zero training bundles and two input
aggregates. Exact aggregate inputs are: NumPy validity, the frozen 80-case fixture and
no prior bundle; NumPy selection, nine training bundles plus 24 tuning and 24
validation scene bundles plus the one validity aggregate; MuJoCo
adaptation, 20 adaptation scene bundles plus the three selected NumPy training
bundles; pilot evaluation, 20 evaluation scene bundles plus the one adaptation
aggregate; confirmation, 80 confirmation scene bundles plus the adaptation and
pilot-evaluation aggregates; final decision, the one confirmation aggregate. The CLI
requires corresponding exact `--max-training-bundles`, `--max-scenes`, and
`--max-input-aggregates` values, using zero for an inapplicable kind. Destinations
derive respectively as
`scenes/<revision>/<phase>/<stratum>/<seed>/`,
`training/<revision>/<variant>/<configuration>/`, and
`aggregates/<revision>/<phase>/all/`. A command cannot write another type's root or
carry another type's flags. NumPy generation/training/selection require the checked-in
`precursor-frozen.yaml`; MuJoCo adaptation/evaluation require the phase-bound pilot
protocol whose parent is that precursor contract; only unseen confirmation/final
decision use `frozen.yaml`. Parent hashes and allowed phase are validated, so a later
protocol cannot be substituted retroactively.

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

Each scene bundle has a 16 MiB/60-minute ceiling. Each training bundle has a 32
MiB/60-minute ceiling; there are exactly three configurations for each of W3, W4, and
W5, nine per revision. Every aggregate has a 60-minute wall ceiling. Aggregate byte
maxima are exact: per revision NumPy validity is 64 MiB, NumPy selection is 32 MiB,
MuJoCo adaptation is 64 MiB,
and pilot evaluation is 64 MiB; final-revision confirmation is 96 MiB and final
decision is 32 MiB. A separate 96 MiB scratch/quarantine allowance yields
`2*(64+32+64+64)+96+32+96 = 672 MiB`. The sibling publication tree occupies the eventual
destination bundle's cap, not a second retained copy; the 96 MiB allowance covers the
largest bounded writer scratch or one quarantined orphan outside it. With two allowed
protocol revisions and confirmation only on the final revision, retained maximum is:

```text
two revisions of NumPy+MuJoCo pilot scenes:
  2 * (144 + 40) * 16 MiB = 5,888 MiB
final MuJoCo confirmation:
  80 * 16 MiB             = 1,280 MiB
two revisions of training/config shards:
  2 * 9 * 32 MiB          =   576 MiB
all typed aggregates plus scratch/quarantine = 672 MiB
-----------------------------------------------------
maximum retained P7 total                  = 8,416 MiB
```

The scene count is `144 NumPy + 20 MuJoCo adaptation + 20 MuJoCo pilot evaluation =
184` per revision, so the first line remains exact. The count includes truth,
predictions, scorer output, and canonical rollout inside scene bundles and all fitted
models/metrics inside training/aggregate bundles; nothing is off-ledger. Before any
typed phase starts, preflight adds all retained bytes, existing temporary directories,
the phase's complete declared bundle count times its per-type cap, and its one allowed
bounded scratch/quarantine allowance. It requires both the 8,416 MiB experiment cap
and inherited 10 GiB/free-disk ceilings. Nothing is deleted until final decision. A cap/timeout yields
`INCONCLUSIVE`, never evidence against a model.

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
smallest positive frozen cost quantum; latency unit is 0.1 ms; and bytes round to
1024. Resource limits use `ceil_to_unit(1.25 * maximum_usage)` across only those 20
pilot-evaluation scenes and must remain under the already frozen inherited caps. Zero
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
component clamp `[-0.25,0.25] m/s`. MuJoCo uses the P3-pinned model, timestep 0.002 s,
ten physics steps per command, the semi-implicit integrator, gravity disabled, and the
same initial state/action/cost projection as NumPy.

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
contact-side one-hot, and obstacle-line intersection. W4 instead appends all 100 action
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

- P3 pinned MuJoCo/source-lock prerequisite and refusal of alternate model/version;
- exact `A00..A15/P00..P23/S00..S39` NumPy analytic, physical, mirror, and
  five-prototype step-halving gate, 64 MiB bundle, timeout behavior, and hand fixtures;
- exact K=8 IDs, globally unique candidate IDs, eight distinct ID-independent content
  digests and bytewise trajectories, identity-bound cross-link hashes, independent
  regeneration, and invalid duplicate/nondeterministic disposition;
- immutable snapshots, named RNG independence, pinned numeric/thread environment,
  tolerance-group PCA, canonical JSON/Parquet/NPZ, and fresh-process byte identity;
- split ancestry/content leakage across all five partitions;
- fit spies proving preprocessing/PCA/models/calibration see only allowed partitions;
- precursor contract freeze before NumPy validity, mechanical tuning/validation,
  adaptation-only output refit/calibration, pilot-evaluation-only margins/resources,
  and nonexistent unseen confirmation before the evidence freeze;
- W0-W5 input boundaries, in-memory full-snapshot commitment, projection digest links,
  absence of the full truth descriptor until every selector exits, and hostile oracle/
  simulator/path/import access;
- exact global prediction IDs, prediction envelope fields, finite/range checks, scalar
  cost components, shared `WorldModelPrediction` round-trip/vector keys/hashes/events,
  ten-field W4 state and per-configuration W5 latent dimensions, W3/W4/W5 derivation,
  and universal tie ordering;
- PCA sign and equal-singular-subspace canonicalization;
- average-rank Spearman plus both constant-actual/predicted cases and regret tolerance;
- exact 16-draw-per-stratum 0.20 bootstrap aggregation,
  co-primary/held-out/W3/W5-vs-W4/shadow/offline families, all percentile indices,
  equality boundaries, and missing rules;
- learned+W1 fallback as the sole authority-bearing result, with raw metrics descriptive;
- scientific endpoint pass/reject/unresolved boundaries and joint classification before
  the mechanically ordered mutually exclusive selector/critic/shadow/offline roles,
  with separate lifecycle/artifact/scientific/blocker/promotion states;
- unchanged canonical rollout, exact scene sidecars/cross-links/replay, disjoint
  scene/training/aggregate schemas and roots, manifest self-exclusion, corruption,
  descriptor-relative no-follow publication, same-process cleanup, restart quarantine,
  and foreign/ambiguous-temp refusal;
- exact repo-root scene/training/aggregate commands and keys, type-mixing refusal,
  create-only validate-and-skip resume, 8,416 MiB arithmetic, phase preflight, and
  per-type wall/size ceilings; and
- serial latency, offline/no-network/no-CUDA/no-physical/no-remote, clean tree, full
  tests, source audit, secret scan, artifact size, and diff checks.

## 15. Dependencies and downstream boundaries

NumPy, PyArrow, and PyYAML remain the only model/data dependencies
(`pyproject.toml:5-15`). MuJoCo is consumed only through the complete passing P3 pinned
lock and compatibility output. A missing/failed P3 gate is `BLOCKED`; it cannot be
replaced by NumPy confirmation.

Experiment 07 may reuse the frozen planar task, scenario/candidate factory, cost
components, IDs, and metrics regardless of the P7 authority result
(`docs/superpowers/specs/2026-08-22-reflect-lite-autonomous-run-design.md:102-106`).
R1 transfer consumes only a separately promoted prediction/critic/selector protocol;
W2 never transfers and W4 privileged input requires an explicit adapter. Mini-Reflect
may enable only the exact role granted by the ordered decision, and executor validation
and W1 fallback remain mandatory (`Reflect Lite Research Program.md:2454-2537`).

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

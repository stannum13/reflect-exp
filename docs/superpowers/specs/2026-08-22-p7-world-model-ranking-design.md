# P7 World-Model Candidate-Ranking Experimental Design

**Date:** 2026-08-22

**Status:** Approved design; no implementation plan

**Scope:** Reflect Lite Experiment 06

## 1. Decision boundary

Experiment 06 asks one bounded question: on a fixed planar-pushing benchmark, does a
small learned predictor order eight meaningful action candidates better than a strong
non-dynamics baseline and the frozen W1 heuristic, with acceptable CPU latency?

NumPy is a deterministic development precursor. It validates the task, generates the
training/tuning/validation data, and selects one configuration each for W3, W4, and W5.
It never produces canonical co-primary evidence. The P3-pinned MuJoCo package/runtime
is the only source of exact pilot and confirmation outcomes. A missing or failing P3
MuJoCo compatibility decision makes P7 `BLOCKED`; it does not authorize NumPy evidence.

The benchmark is local, CPU-only, and free of downloaded checkpoints. It does not test
general manipulation, real-R1 transfer, visual plausibility, latent MPC, CEM/MPPI,
foundation encoders, online learning, or action execution. P7 can promote a prediction
and candidate-selection protocol, but it grants no action-routing authority. A later
executor-prefix test requires its own reviewed design and a passing P4 stack-`P4`
artifact at the exact `10 Hz, 300 ms` condition.

The implementation is deliberately experiment-local. It reuses the existing
`RolloutWriter`, canonical JSON encoder, shared `WorldModelPrediction`, and replay CLI.
It adds no sandbox framework, capability broker, generalized lifecycle engine, new
database, hardened Git publisher, quarantine service, or cross-experiment artifact
abstraction.

## 2. Scientific unit, world, and partitions

### 2.1 Scene and anchor unit

The analysis unit is a `scene_seed`. One scene owns its physical parameters, probe
rollout, four ordered anchor snapshots, all adjacent frames, all eight counterfactual
branches per anchor, and all renderings. Metrics average anchors within scene first;
paired inference resamples scenes. No descendant of a scene crosses a split.

The world has a velocity-controlled circular end effector, one movable disk or
rectangle, a target pose, zero or one wall/obstacle, bounded workspace, randomized
mass/friction/geometry, and exact branch outcomes. NumPy and MuJoCo use one frozen
state/action/cost projection; only MuJoCo outcomes are canonical truth.

ID scenes sample object center uniformly from `[-0.30,0.30]^2`, target bearing from
`[0,2*pi)`, target distance from `[0.25,0.45]`, target yaw from `[-pi,pi)`, mass from
`[0.8,1.2] kg`, and friction from `[0.40,0.60]`. Geometry is an equiprobable disk with
radius `[0.055,0.075] m` or rectangle with half-extents `x=[0.050,0.070]` and
`y=[0.040,0.060] m`. The obstacle is absent with probability 0.5; otherwise it is the
frozen target-axis-parallel side segment. MASS_OOD changes only mass to `[1.40,1.60]`,
FRICTION_OOD only friction to `[0.75,0.90]`, GEOMETRY_OOD only geometry to disk radius
`[0.085,0.095]` or rectangle half-extents `x=[0.080,0.095], y=[0.030,0.040]`, and
OBSTACLE_OOD only the obstacle to the frozen perpendicular center barrier. Up to 32
domain-separated proposals may seek a feasible nonpenetrating initial state; exhaustion
is invalid and never changes the scene seed.

The two-second probe has four 0.5-second phases: approach the target-opposite contact,
push 0.10 m toward target, retreat 0.08 m, and move 0.08 m along the positive target
perpendicular. Immutable post-step snapshots at `0.50,1.00,1.50,2.00 s` are the four
anchors.

Stable IDs are:

```text
scene_id     = exp06/scene/<16-lowercase-hex-scene-seed>
anchor_id    = <scene_id>/anchor/<zero-padded-index>
strategy_id  = DIRECT | LEFT_EDGE | RIGHT_EDGE | BELOW | DIAGONAL |
               RETREAT_REPOSITION | SLOW_CONSERVATIVE | HOLD
candidate_id = <anchor_id>/candidate/<strategy_id>
prediction_id = <candidate_id>/prediction/<64-lowercase-hex-model-sha256>
```

IDs are never derived from row position. A duplicate ID or seed invalidates the run.

### 2.2 Fixed partitions

Named PCG64 roots are the first 128 big-endian bits of SHA-256 of the literal root name.
Every scene/probe/model/bootstrap stream has a separate domain string and a fresh
generator. No generator object crosses a scene, model member, anchor, or phase.

| Partition | Scenes | Use |
|---|---:|---|
| NumPy train | 96 | preprocessing, PCA, model fitting |
| NumPy tuning | 24 | rank the frozen three-configuration grid |
| NumPy validation | 24 | mechanically select one checkpoint/method |
| MuJoCo adaptation | 20, four in each stratum | permitted output refit, calibration, thresholds |
| MuJoCo pilot evaluation | 20, four in each stratum | margins and resource ceilings only |
| MuJoCo confirmation | 80, sixteen in each stratum | sole confirmatory evidence |

The five MuJoCo strata have equal 0.20 weight:

```text
ID
MASS_OOD
FRICTION_OOD
GEOMETRY_OOD
OBSTACLE_OOD
```

The NumPy roots and the 40-scene MuJoCo pilot root freeze before any outcome. Within
each pilot stratum, sorted scene IDs 0-3 are adaptation and 4-7 are pilot evaluation.
The confirmation root is generated only after the common evidence freeze by exactly
one `os.urandom(16)` call. The committed confirmation manifest stores only the derived
root and exact scene rows, never the raw entropy. Confirmation data cannot alter any
model, threshold, margin, exclusion, cost, or gate.

The split manifest records partition, stratum, RNG roots, scene/probe seeds, parameter
cell, anchor/candidate IDs, source simulator/config SHA-256, state/render hashes, and
both action hashes. Shared ancestry or content across any two partitions is `INVALID`.

### 2.3 Preregistered outcome-coverage gate

The program requires success, failure, collision, no-op, and recovery trajectories.
After a partition's complete truth table exists and before it can be consumed, a fixed
coverage validator requires:

- at least one `success=true`, one `terminal_failure=true`, and one `collision=true`
  candidate outcome in the partition;
- exactly one HOLD and one RETREAT_REPOSITION candidate at every anchor; and
- all eight strategies at every anchor.

For MuJoCo pilot evaluation and confirmation, the three outcome-presence checks also
apply independently in every stratum. The validator writes counts for every category.
It never adds, drops, or resamples a seed. Missing coverage makes development data
`INVALID`; missing confirmation coverage makes the scientific result `INCONCLUSIVE`.

## 3. Exact K=8 candidate compiler

At each anchor, a deterministic waypoint controller emits exactly 50 planar velocity
commands at `dt=0.02 s`, one second total, for:

1. direct push;
2. left-edge push;
3. right-edge push;
4. push from world-below;
5. target-facing diagonal push;
6. retreat, reposition, then push;
7. slow direct push; and
8. HOLD/no-op.

The workspace is `[-1,1]^2`; end-effector radius is `0.04 m`; command components clamp
to `[-0.25,0.25] m/s`. Let `c` be object center, `g` target center,
`u=unit(g-c)`, `v=(-u_y,u_x)`, and `h(n)` the exact object support radius along `n`.
The checked-in configuration freezes every waypoint, phase boundary, contact offset,
speed multiplier, and the zero-displacement `u=(1,0)` rule.

With `contact(n,offset)=c-(h(n)+0.01)n+offset`, the exact waypoint table is:

| Strategy | `(phase end, waypoint)` | multiplier |
|---|---|---:|
| DIRECT | `(0.35,contact(u,0v)); (1.00,g-(h(u)-0.02)u)` | 1.0 |
| LEFT_EDGE | `(0.35,contact(u,+0.75h(v)v)); (1.00,g+0.25h(v)v)` | 1.0 |
| RIGHT_EDGE | `(0.35,contact(u,-0.75h(v)v)); (1.00,g-0.25h(v)v)` | 1.0 |
| BELOW | `(0.35,contact((0,1),0v)); (1.00,g-(0,h((0,1))-0.02))` | 1.0 |
| DIAGONAL | `(0.25,c-(h(u)+0.08)u+0.60h(v)v); (0.55,contact(u,+0.60h(v)v)); (1.00,g)` | 1.0 |
| RETREAT_REPOSITION | `(0.20,e0-0.08u); (0.55,contact(u,0v)); (1.00,g)` | 1.0 |
| SLOW_CONSERVATIVE | DIRECT waypoints | 0.5 |
| HOLD | `(1.00,e0)` with exact zero commands | 0.0 |

The command compiler is independent of candidate physics. It starts
`nominal_eef = anchor_eef`. At tick `t`, the later phase owns an exact phase-boundary
equality; the controller computes

```text
raw = multiplier * (waypoint - nominal_eef) / max(0.02, phase_end - t)
command = component_clip(raw, -0.25, 0.25)
nominal_eef = nominal_eef + 0.02 * command
```

HOLD emits exact zero commands and leaves `nominal_eef` unchanged. The resulting 50
commands are frozen before any branch simulation and are replayed unchanged in NumPy or
MuJoCo. No simulated candidate state feeds command generation or another candidate.

`action_content_sha256` hashes the canonical header

```text
["exp06-action-content-v1",[50,2],"<f8",0.02,1.0,[-0.25,-0.25],[0.25,0.25]]
```

without its trailing LF, one NUL byte, and the 800 little-endian float64 C-order command
bytes. `action_sha256` hashes canonical JSON

```text
["exp06-action-identity-v1",action_content_sha256,strategy_id,
 candidate_id,scene_id,anchor_id]
```

Independent regeneration must reproduce all bytes and hashes. Every anchor requires
eight distinct command byte strings and content hashes. A duplicate or nondeterministic
candidate makes that run `INVALID`; IDs cannot disguise duplicate actions.

## 4. NumPy precursor validity

Before NumPy data generation, `config/frozen.json` freezes the task, splits, simulator
equations, MuJoCo mapping, candidates, cost, labels, W0/W1, model grid, schemas, numeric
profile, validity cases, and resource ceilings. It is a checked-in canonical JSON file,
reviewed with the implementation. Learned coefficients, calibration values, measured
margins, and confirmation root do not yet exist.

The NumPy simulator uses float64 fixed-step semi-implicit integration at `dt=0.002`,
deterministic contact order, explicit terminal reasons, and immutable snapshots. The
exact 80 preregistered validity cases are:

- 16 analytic free-motion, HOLD, wrap, clip, and hand-cost cases;
- 24 physical cases: all eight strategies in free, single-contact, and obstacle-contact
  fixtures, each with a world-x-axis mirror subexecution; and
- 40 step-halving cases: all eight strategies in one prototype for each of ID,
  MASS_OOD, FRICTION_OOD, GEOMETRY_OOD, and OBSTACLE_OOD.

Analytic absolute/relative tolerance is `1e-12`; mirror endpoint tolerance is `1e-10`;
maximum penetration is `0.002 m`; unforced energy increase tolerance is `1e-12 J`;
step-halving endpoint L-infinity and per-component/cost tolerances are `0.001`; labels
must match; allowed Kendall disagreement is zero. Every case and candidate must pass.
Failure yields `INVALID` and `STOPPED`; going directly to MuJoCo requires a new reviewed
revision.

## 5. MuJoCo truth and cost

P3 supplies only the pinned MuJoCo runtime. P7 owns one checked-in Push-T MJCF template
and pure `build_mjcf(scene_parameters) -> bytes` function. Canonical UTF-8/LF output,
literal element/attribute order, `.17g` finite floats, negative-zero normalization,
joint/geom order, solver options, timestep, friction mapping, and restore-vector layout
freeze in `config/frozen.json`. Every scene binds generated model SHA-256, template and
generator hashes, P3 package version/distribution hash, and restore-vector hash.

MuJoCo uses a mocap end effector, object `x/y/yaw` joints, no actuator, gravity, plugin,
callback, or hidden controller. Each 0.02-second command is held for ten 0.002-second
`mj_step` calls. Every candidate starts from an independently restored byte-equal anchor;
no `mjData` or contact cache crosses candidates.

Success requires terminal object-center error `<=0.05 m`, wrapped yaw error
`<=0.20 rad`, and no unsafe event. Collision means object/end-effector contact with an
obstacle or wall above `0.05 N-s`. Unsafe means workspace escape, penetration above
`0.002 m`, nonfinite state, or impulse above `2.0 N-s`. Terminal failure is `not
success`. Action energy is `sum_t ||a_t||^2*0.02`.

Actual and predicted scalar costs use the same weights:

```text
position_error^2
+ 0.10 * wrapped(orientation_error)^2
+ 2.00 * collision_probability
+ 0.01 * action_energy
+ 4.00 * terminal_failure_probability
- 1.00 * success_probability
```

Actual values substitute binary truth. There is no hidden penalty.

## 6. Selectors, models, and leakage boundary

### 6.1 W0-W5

- **W0 random:** one PCG64 draw per anchor from a domain-separated seed; emits only a
  selection.
- **W1 heuristic:** predicts nominal endpoint, yaw error, line-intersection collision,
  workspace risk, and known action energy. For action displacement
  `q=sum_t command_t*0.02`, `alignment=max(0,dot(unit(q),u))` (zero for `q=0`) and
  `push=max(0,dot(q,u)-max(0,dot(c-e0,u)-h(u)-0.04))`; predicted object center is
  `c+alignment*push*u`, yaw is unchanged, collision is exact polyline intersection with
  obstacles expanded by 0.04 m, and unsafe is workspace exit. Its formula, cost weights,
  and candidate-ID tie rule freeze.
- **W2 exact oracle:** restores the pinned MuJoCo anchor, evaluates all eight branches,
  and chooses the actual minimum; it is nondeployable and has zero regret.
- **W3 non-dynamics baseline:** ridge ensemble over current privileged state, strategy,
  action summaries, contact-side encoding, and obstacle-line intersection.
- **W4 privileged dynamics:** ridge ensemble over current privileged state plus the full
  50x2 candidate chunk and strategy; predicts ten-dimensional terminal state delta and
  collision/failure/unsafe/success heads.
- **W5 observation-latent dynamics:** train-only PCA of a deterministic 64x64x6 raster
  plus full candidate chunk and strategy; predicts future latent and scalar
  position/orientation/energy/collision/failure/unsafe/success heads.

W1/W3/W4/W5 emit one row per candidate. Candidate order is
`(predicted_cost, uncertainty, candidate_id)` ascending. W4 requires a terminal-state
vector; W5 requires a terminal-latent vector. Those vectors are stored in a canonical
NPZ sidecar. W3 has neither. `predicted_progress` is derived from predicted position
error and frozen initial error. Prediction rows contain no wall-clock timing field;
all measured latency lives only in `latency.jsonl`. When adapting a row to the existing
shared `WorldModelPrediction`, `inference_ms` is the fixed sentinel `0.0`, documented as
non-authoritative. Replay and decisions read the latency sidecar instead.

### 6.2 Exact truth-free selector input

Selectors are ordinary pure functions. Their only argument is an immutable
`SelectorInput` containing identities, one declared observation projection, the ordered
K=8 actions, and the already fitted artifacts appropriate to that selector. It has no
simulator, branch outcome, W2 score, truth table, result path, file loader, subprocess,
or network member. API-level tests pass hostile stand-ins and prove that predictor code
cannot request undeclared fields. For pilot and confirmation, the pipeline writes and
hashes every raw prediction and composition for every scene before it runs any candidate
branch truth. The prediction stage cannot call the truth runner; the truth stage cannot
call a selector.

The ordered action-set artifact has exact header:

```text
{
  "schema_version":1,
  "scene_id":string,
  "anchor_id":string,
  "candidate_ids":[8 strings in frozen strategy order],
  "strategy_ids":[8 strings in frozen strategy order],
  "action_content_sha256s":[8 hashes],
  "action_sha256s":[8 hashes],
  "shape":[8,50,2],
  "dtype":"<f8",
  "dt_s":0.02,
  "horizon_s":1.0
}
```

`candidate_actions_sha256` is SHA-256 of canonical JSON bytes of that header without its
LF, one NUL, then the concatenated `(8,50,2)` little-endian float64 C-order bytes.

Projection kinds and exact byte payloads are:

- `W0_IDS`: zero-length bytes;
- `W1_GEOMETRY`: little-endian float64 vector in order `eef_xy, object_xyyaw,
  geometry_onehot, geometry_dims, target_xyyaw, obstacle_present_xyxy,
  workspace_xyxy, cost_weights`;
- `PRIVILEGED_25`: end-effector `(x,y,vx,vy)`, object
  `(x,y,yaw,vx,vy,omega)`, target `(x,y,yaw)`, mass, friction, geometry one-hot,
  geometry dimensions, and obstacle present/endpoints; and
- `RASTER_64`: uint8 C-order `(64,64,6)` raster, channels end effector, object, target,
  obstacle, object-mask-times-sine-yaw, object-mask-times-cosine-yaw.

For every kind, `projection_sha256` hashes canonical JSON

```text
["exp06-projection-v1",projection_kind,scene_id,anchor_id,dtype,shape]
```

without its LF, one NUL, and exactly those bytes. `selector_input_sha256` hashes canonical
JSON of the exact-key row:

```text
schema_version, phase, scene_id, anchor_id, observation_id, selector_id,
projection_kind, projection_sha256, candidate_actions_sha256,
generating_model_sha256, preprocessing_sha256, pca_sha256,
calibration_sha256, fallback_threshold_sha256, cost_contract_sha256
```

Raw W4/W5 inputs bind their model, preprocessing, and calibration map but require
`fallback_threshold_sha256=null`. Thresholds are stored separately from calibration
maps. The trusted `compose_fallback` function alone receives a complete sealed W1
ranking, one complete sealed raw W4 or W5 ranking, and the corresponding threshold/hash.
It receives no projection, model, simulator, or truth. Composition input hashes use
canonical JSON

```text
["exp06-fallback-input-v1",phase,scene_id,anchor_id,composition_id,
 w1_ranking_sha256,learned_ranking_sha256,fallback_threshold_sha256]
```

This makes the model/fallback boundary executable without an OS sandbox or capability
container.

### 6.3 Model grid and exact fit

The privileged vector has 25 columns. W3's frozen base vector has 51 columns after
strategy, endpoint displacement, path length, per-axis velocity moments, six-way
contact-side encoding, and obstacle intersection. W4's base vector has 133 columns:
25 privileged, 100 action scalars, and eight strategy indicators. W5 transition input
has PCA dimension plus the same 100 action scalars and eight strategy indicators.

Each variant has exactly three configurations:

| ID | W3 | W4 | W5 | ensemble | calibration |
|---|---|---|---|---:|---|
| CFG01 | degree 1, ridge `1e-3` | degree 1, ridge `1e-3` | PCA 16, degree 1, ridge `1e-3` | 4 | identity clip |
| CFG02 | degree 2 interactions, ridge `1e-2` | degree 2 interactions, ridge `1e-2` | PCA 24, action-latent interactions, ridge `1e-2` | 8 | PAV, 8 equal-count bins |
| CFG03 | CFG02 plus univariate cubes, ridge `1e-1` | CFG02 plus univariate cubes, ridge `1e-1` | PCA 32, full degree 2, ridge `1e-1` | 16 | PAV, 16 equal-count bins |

Raw features expand in total-degree then lexicographic source-column order. Train-only
population z-score applies independently to every expanded non-intercept column after
expansion; zero-variance columns become exact zero. One canonical 32-component PCA fits
the 3,072 repeated current-anchor training raster rows; CFG01/CFG02 use byte-identical
16/24-component prefixes. Terminal rasters never enter PCA fitting.

Each ensemble member draws 96 scene ordinals with replacement in one exact PCG64 call;
each scene occurrence contributes all 32 candidate rows. Ridge uses centered float64
primal Cholesky for `p<=n` and dual Cholesky for `p>n`, an unregularized intercept, no
jitter or solver substitution, and the frozen KKT residual bound. Two fresh processes
under the pinned BLAS/thread profile must produce byte-identical parameters.

`fit` consumes only 96 training scenes and writes exactly nine create-only model files.
It writes no tuning or validation predictions. `numpy-select` subsequently loads those
nine immutable models and exactly the 24 tuning plus 24 validation scenes, writes one
exact `numpy-evaluation.parquet`, and mechanically selects one configuration each for
W3/W4/W5 using `regret, negative rank correlation, calibration error, model bytes,
configuration ID`. No human or MuJoCo result chooses a configuration.

### 6.4 Adaptation and calibration

For each selected ensemble member, MuJoCo adaptation appends each of the 20 adaptation
scenes once to that member's original 96-scene NumPy bootstrap multiset. It reruns the
same Cholesky compiler with frozen preprocessing and may refit only:

- W3: position, orientation, collision, energy, terminal-failure, unsafe, success;
- W4: state delta, collision, terminal-failure, unsafe, success; and
- W5: position, orientation, collision, energy, terminal-failure, unsafe, success.

W5 latent-transition parameters, PCA, feature maps, and every other member remain
byte-identical. The adapted-model hash binds changed and unchanged member hashes.

Probability member outputs clip once to `[0,1]`. Calibration fits the arithmetic mean of
clipped member probabilities. CFG01 is identity. CFG02/CFG03 use stable probability/ID
order, 8x80 or 16x40 equal-count bins across the 640 adaptation rows, count-weighted
equal-x merging, weighted monotone PAV, and frozen `numpy.interp` semantics. Evaluation
first averages clipped member probabilities and applies the map once. For uncertainty
only, the same map applies separately to each member; cost uncertainty is population
variance of member costs. This preserves one fit/evaluation operator.

W4/W5 fallback threshold candidates are `-inf`, adaptation uncertainty quartiles, and
`+inf`. Choose minimum adaptation regret subject to zero unsafe selections and learned
coverage `>=0.50`, then the lower threshold. Whole-anchor fallback uses the raw learned
ranking exactly when its top candidate's uncertainty is `<=` threshold; otherwise it
uses the complete W1 ranking. Candidate-wise hybridization is forbidden. Critic score is
the maximum calibrated collision/failure/unsafe probability; its grid is
`0.00,0.05,...,1.00`, with positive defined as `score >= threshold`. Choose maximum
recall subject to precision `>=0.90` and zero unsafe veto, then the higher threshold.

## 7. Evidence tables and replay

Every scene writes one ordinary canonical rollout for each authority-relevant selector
W1, W3, W4F, and W5F using the existing `RolloutWriter`; raw W4/W5, W0, and W2 remain
sidecar evidence. Canonical rollout `actions.parquet` is empty because P7 routes no
runtime action. `WORLD_MODEL_PREDICTED` and `WORLD_MODEL_SELECTED` events resolve to the
sidecar rows. `python -m reflect.rollout replay <rollout-path>` remains the only replay
command and reconstructs observation order, rankings, fallback, selection, and the
explicit absence of executed control references without rerunning models or physics.

Prediction stages write `candidate_inputs.parquet`; truth stages copy its identity/action
fields byte-for-byte into the previously absent final `candidates.parquet` and append
the fixed truth/execution dispositions. No file changes state in place. The complete
experiment sidecar files are:

```text
anchors.parquet
candidate_inputs.parquet
candidates.parquet
predictions.parquet
selections.parquet
candidate_truth.parquet
candidate_outcomes.npz
prediction_vectors.npz
latency.jsonl
metrics.json
```

Every final candidate row has exact fields:

```text
scene_id, anchor_id, observation_id, candidate_id, strategy_id,
candidate_source="DETERMINISTIC_STRATEGY", dt_s, horizon_s, commands,
action_content_sha256, action_sha256, truth_evaluated, executed
```

`truth_evaluated=true` only after the exact NumPy/MuJoCo counterfactual branch was run.
`executed=false` for every P7 row because this ranking baseline never routes an action.
`candidate_inputs.parquet` contains the exact prefix through `action_sha256` and has no
truth or selection field. Prediction receipts hash that file; truth receipts require
the final table's prefix to match before accepting its appended dispositions.
Every prediction row contains predicted components/cost/outcome, uncertainty, model and
action hashes, and `selected` for that raw selector. Every selection row binds one
selector, chosen candidate/action, chosen raw prediction when applicable, fallback flag
and reason. Candidate truth contains actual components/cost/outcome, W2 selection, exact
terminal ten-state and 64x64x6 raster member hashes. Collectively these fields preserve
the program's candidate source, full chunk, predicted outcome, actual outcome, selected
flag, truth-evaluation flag, and execution flag without implying that W2 branch rollout
was runtime execution.

Rows use explicit nonnullable PyArrow schemas, fixed order, no dictionary encoding, one
row group, no compression, and no statistics. NPZ uses sorted ZIP_STORED little-endian
NPY members. JSON uses the repository canonical encoder plus one LF. Every row/file hash
has a domain-separated preimage documented beside its schema. Validators recompute
hashes and require exact IDs/counts/types; they do not repair or normalize evidence.

## 8. Metrics, latency, and inference

Actual and predicted costs use average ranks for ties. Spearman is Pearson correlation
of ranks, with fixed constant-vector rules: both constant is `1.0`; only one constant is
`0.0`. Selection regret is actual selected cost minus W2 minimum and must be nonnegative
within frozen tolerance. Metrics average anchors to scenes, scenes within strata, then
combine strata with exact 0.20 weights.

Primary contrasts are W4F and W5F versus W1 for overall rank improvement and regret
reduction. The four endpoints form one Bonferroni family with 98.75% marginal intervals.
For each composition, both lower bounds must strictly exceed pilot-frozen effects.

Held-out regret reductions in MASS_OOD, FRICTION_OOD, GEOMETRY_OOD, and OBSTACLE_OOD for
both compositions form one eight-contrast family with 99.375% intervals. Every held-out
lower bound for a composition must pass. Overall regret against W3 forms one
two-contrast family with 97.5% intervals. If both compositions pass, W5F replaces W4F
only when one six-endpoint 99.1666667% family proves overall-regret superiority plus
overall-rank and four held-out-regret non-inferiority.

All intervals use paired scene-seed differences and 10,000 deterministic percentile
bootstrap resamples. Overall resampling draws 16 scenes independently within each
stratum and recombines with 0.20 weights; pooling 80 scenes is forbidden. Exact sorted
endpoint indices freeze in config. Equality fails superiority and passes
non-inferiority.

Pilot-evaluation margins are
`ceil_to_unit(max(one_task_unit,0.5*paired_scene_sample_SD))`. Pilot latency ceilings are
`ceil_to_0.1ms(1.25*pilot_p95)`. Pilot may set only these margins and resource ceilings;
unattainable values yield `INCONCLUSIVE`, never clipping or a changed task.

Latency is isolated from deterministic predictions. Under the pinned single-thread CPU
profile, each pilot/confirmation anchor performs five warmups and then 20 repetitions:

- raw single-candidate inference for W1, W3, W4, and W5, in candidate-ID order; and
- full K=8 batch inference/ordering for W1 and W3, and full raw inference plus trusted
  whole-anchor composition for W4F and W5F.

Thus each anchor writes `20*(4*8 + 4)=720` latency rows: 57,600 pilot rows and 230,400
confirmation rows. A single row never performs fallback. A W4F/W5F batch row always
reruns all eight raw candidates and composition. Timing begins immediately before
projection decoding/model work and ends after canonical in-memory envelope/selection
construction; it excludes file I/O, process startup, truth, and serialization. Timed
outputs must equal untimed outputs after excluding timing, which is not a prediction
field. Authority gates use raw W4/W5 single-candidate p95 and composed W4F/W5F K=8 batch
p95, both within their separately frozen ceilings.

Secondary evidence includes top-1 and pairwise accuracy, oracle-gap closure,
future-state/latent error, calibration, failure precision/recall, per-stratum results,
model bytes, training CPU time, coverage-risk, fallback frequency, and uncertainty-error
association.

## 9. Scientific and role decisions

Artifact status is `VALID | INVALID`, prerequisite status `READY | BLOCKED`, scientific
result `SUPPORTED | NOT_SUPPORTED | INCONCLUSIVE`, and promotion status
`SELECTOR_PROTOCOL_PROMOTED | STOPPED`. These states never substitute for one another.

W4F or W5F is `AUTHORITY_PASS` only if every co-primary, held-out, W3, calibration,
latency, byte, coverage, leakage, and safety gate passes. It is `AUTHORITY_REJECTED` when
complete valid evidence conclusively rejects any required endpoint; otherwise it is
`AUTHORITY_UNRESOLVED`. The result is `SUPPORTED` if at least one composition passes,
`NOT_SUPPORTED` only if both are rejected, and `INCONCLUSIVE` otherwise.

For `VALID + READY` evidence, exactly one required role is assigned by first match:

1. `CANDIDATE_SELECTOR` when at least one learned+W1 composition is `AUTHORITY_PASS`;
2. `FAILURE_CRITIC` when selector authority fails but one raw model passes the frozen
   held-out precision/recall, calibration, latency, and zero-unsafe-veto family. The
   four strata times precision/recall times W4/W5 form one 16-endpoint family with
   99.6875% marginal intervals; every endpoint for the chosen model must pass;
3. `SHADOW_OBSERVER` when critic fails but a composition passes frozen held-out
   calibration, latency, and byte ceilings. Brier/ECE times four held-out strata times
   W4F/W5F form one 16-endpoint family with 99.6875% intervals;
4. `OFFLINE_ANALYSIS_ONLY` when at least one raw learned model passes a frozen overall
   descriptive rank or regret endpoint. W3/W4/W5 rank/regret form one six-endpoint
   family with 99.1666667% intervals; or
5. `NOT_USEFUL_YET` otherwise.

`LATENT_SUBGOAL_MODEL_WORTH_TESTING` and `DIRECT_PLANNER_WORTH_TESTING` are unreachable
because P7 did not test those claims. Only `VALID + READY + SUPPORTED +
CANDIDATE_SELECTOR` sets `SELECTOR_PROTOCOL_PROMOTED`. Other roles remain descriptive
and cannot veto, replace, rank, select, route, or execute an action downstream without a
new reviewed experiment.

## 10. Small write-once pipeline

### 10.1 Files and ownership

P7 implementation is limited to:

```text
experiments/06_world_model/
  CLAIM.md
  config/frozen.json
  manifests/numpy.json
  manifests/mujoco-pilot.json
  model.py
  world.py
  run.py
  report.py
  tests/
```

`world.py` owns scene generation, K=8 candidates, NumPy precursor, generated MJCF, and
MuJoCo truth. `model.py` owns projections, W0-W5, fitting, calibration, fallback, and
metrics. `run.py` owns only the fixed stage dispatcher, exact input counts, write-once
files, and receipts. `report.py` validates the final manifest and creates
`WORLD_MODEL_DECISION.md`. Experiment-specific schemas and thresholds remain here.

There is no reusable artifact framework. A local `write_new(path, bytes)` helper writes
one sibling temporary regular file, fsyncs it, links it to the previously absent final
path (so an existing destination cannot be replaced), unlinks the temporary, and fsyncs
the parent. A stage writes its small `receipt.json` last. A complete stage validates and
skips on reissue. An interrupted stage remains evidence-bearing and is resumed only by
validating its complete file prefix; conflicting or unknown bytes stop that run and use
a new run ID. Nothing is deleted, overwritten, repaired in place, or quarantined by P7.

The final `result-manifest.json` is the one authoritative result manifest. It lists every
stage receipt and retained evidence file by project-relative path, byte count, and
SHA-256; it excludes itself. Its own SHA-256 is computed by the report command. Stage
receipts are local completion markers, not a generalized lifecycle or nested manifest
hierarchy.

### 10.2 Exact commands and counts

Every command runs from the project root, uses the pinned environment, requires a clean
implementation allowlist, records full Git HEAD/P2 lock/P3 evidence hashes, disables
network/CUDA/remote/physical flags, and refuses unknown arguments. Preflight requires a
complete P2 lock plus P3's `ADVANCE` decision, compatibility table, unique passing
MuJoCo runtime fragment, exact distribution artifact hash, and smoke command/status to
agree. Every later receipt must match preflight's HEAD/config/P2/P3 hashes; freeze also
binds every selected/adapted model, calibration, threshold, pilot prediction/truth, and
margin hash, and every confirmation command must match that freeze. These are the only
P7 evidence commands:

```bash
uv run python experiments/06_world_model/run.py preflight \
  --config experiments/06_world_model/config/frozen.json \
  --p2-lock references/repos.lock.yaml \
  --p3-operation experiments/00_source_audit/configs/operation-manifest.yaml \
  --p3-compatibility experiments/00_source_audit/results/compatibility.csv \
  --p3-results experiments/00_source_audit/RESULTS.md \
  --p3-fragments experiments/00_source_audit/results/fragments \
  --run-id r1 --output results/06_world_model/r1

uv run python experiments/06_world_model/run.py numpy-validity \
  --run-id r1 --cases 80 --output results/06_world_model/r1

uv run python experiments/06_world_model/run.py numpy-data \
  --run-id r1 --train-scenes 96 --tuning-scenes 24 --validation-scenes 24 \
  --output results/06_world_model/r1

uv run python experiments/06_world_model/run.py fit \
  --run-id r1 --input-scenes 96 --variants 3 --configurations 3 --models 9 \
  --output results/06_world_model/r1

uv run python experiments/06_world_model/run.py numpy-select \
  --run-id r1 --tuning-scenes 24 --validation-scenes 24 --models 9 \
  --evaluation-rows 41472 --selected-models 3 --output results/06_world_model/r1

uv run python experiments/06_world_model/run.py mujoco-adapt \
  --run-id r1 --scenes 20 --selected-models 3 --adapted-models 3 \
  --output results/06_world_model/r1

uv run python experiments/06_world_model/run.py pilot-predict \
  --run-id r1 --scenes 20 --anchors 80 --candidates 640 \
  --selector-inputs 560 --raw-predictions 2560 --latency-rows 57600 \
  --output results/06_world_model/r1

uv run python experiments/06_world_model/run.py pilot-truth \
  --run-id r1 --scenes 20 --anchors 80 --candidates 640 \
  --output results/06_world_model/r1

uv run python experiments/06_world_model/run.py freeze \
  --run-id r1 --pilot-scenes 20 --selected-models 3 \
  --output results/06_world_model/r1

uv run python experiments/06_world_model/run.py confirmation-manifest \
  --run-id r1 --strata 5 --scenes-per-stratum 16 \
  --output results/06_world_model/r1

uv run python experiments/06_world_model/run.py confirmation-predict \
  --run-id r1 --scenes 80 --anchors 320 --candidates 2560 \
  --selector-inputs 2240 --raw-predictions 10240 --latency-rows 230400 \
  --output results/06_world_model/r1

uv run python experiments/06_world_model/run.py confirmation-truth \
  --run-id r1 --scenes 80 --anchors 320 --candidates 2560 \
  --output results/06_world_model/r1

uv run python experiments/06_world_model/run.py decide \
  --run-id r1 --confirmation-scenes 80 --output results/06_world_model/r1

uv run python experiments/06_world_model/report.py \
  --result-manifest results/06_world_model/r1/result-manifest.json \
  --output experiments/06_world_model/WORLD_MODEL_DECISION.md
```

`pilot-predict` and `confirmation-predict` seal every prediction, selection, composition,
and latency row before their matching truth command is accepted. Truth commands cannot
import selector functions. `freeze` consumes the 20 untouched pilot scenes and writes
only margins, resource ceilings, selected/adapted model hashes, calibration hashes, and
fallback/critic thresholds. `confirmation-manifest` is impossible before that receipt.
`decide` reads confirmation once and writes the final manifest last.

### 10.3 Resource ledger

Each source/evidence scene, including terminal state/raster targets and selector tables,
has a 2 MiB cap. Training models retain the existing configuration-specific caps: eight
at 32 MiB and W5 CFG03 at 64 MiB. Adaptation/calibration has 32 MiB; all global
evaluation/metrics/receipts/final output share 128 MiB; one current sibling temporary has
96 MiB; checked-in config/manifests/report have 16 MiB. At most two protocol revisions
may remain, with confirmation only on the final revision:

```text
two revisions of 184 NumPy/pilot scenes
  plus 80 final confirmation scenes:
  (2 * 184 + 80) * 2 MiB                     = 896 MiB
two revisions of nine training models:
  2 * (8 * 32 + 1 * 64) MiB                 = 640 MiB
two revisions of adaptation/calibration       =  64 MiB
global evaluation, metrics, receipts, report  = 128 MiB
one current write temporary                    =  96 MiB
checked-in configuration and final decision   =  16 MiB
-------------------------------------------------------
maximum retained P7 total                     = 1,840 MiB
```

Each development/pilot revision has 144 NumPy, 20 adaptation, and 20 pilot-evaluation
scenes; only the final revision has 80 confirmation scenes. Prediction files are charged
inside their matching scene/global buckets, never both. Before each stage, the simple
preflight sums actual completed bytes, the cap
for every missing required output, and one 96 MiB temporary. It records the arithmetic
in the stage receipt and requires both the 1,840 MiB P7 ceiling and inherited free-disk
ceiling. `fit` has a 120-minute wall limit; every other stage has 60 minutes. A resource
limit yields `INCONCLUSIVE`, not evidence against a model.

## 11. Verification

Tests must cover:

- P3 MuJoCo gate binding and refusal of NumPy as canonical truth;
- all 80 NumPy analytic/physical/mirror/step-halving validity cases;
- exact K=8 identities, strategy order, nominal-EEF update, distinct command bytes,
  independent regeneration, and both action hashes;
- exact split ancestry/content isolation and the nonadaptive outcome-coverage gate;
- projection/action-set encodings and digest preimages for W0/W1/W3/W4/W5;
- API-level hostile selector inputs proving no simulator/truth/W2/path/process/network
  access, raw W4/W5 threshold absence, and composer-only threshold use;
- preprocessing/PCA/model fit spies, one 32-component PCA with exact prefixes, scene
  bootstrap, primal/dual Cholesky, adaptation-only permitted heads, calibration operator
  identity, and unchanged W5 latent transition;
- the separate nine-model fit and 41,472-row tuning/validation evaluation producer;
- terminal state/raster targets, exact candidate source/selected/truth-evaluated/executed
  fields, shared prediction adaptation with `inference_ms=0.0`, and replay with no
  executed control reference;
- pilot/confirmation global prediction-before-truth barriers and refusal of selector
  calls from truth stages;
- average-rank Spearman, regret, all simultaneous families, stratum-respecting bootstrap,
  margin boundaries, fallback coverage, and role ordering;
- raw single-candidate versus full K=8 composed latency boundaries and exact
  57,600/230,400 row counts;
- simple create-only file publication, receipt-last resume, conflict refusal, final
  manifest self-exclusion, corruption detection, and 1,840 MiB arithmetic; and
- full offline tests, source audit, secret scan, physical/remote/CUDA/network refusal,
  artifact-size checks, and clean diff.

## 12. Dependencies and downstream use

NumPy, PyArrow, PyYAML, and the P3-pinned MuJoCo package are the only experiment
dependencies. P4 is not a P7 prerequisite. Experiment 07 may reuse the planar task,
candidate factory, cost, IDs, and metrics regardless of the P7 result. R1 or Mini-Reflect
may consume only a separately promoted protocol; W2 never transfers, W4 privileged input
requires an adapter, and action routing always requires a later reviewed integration
test with executor validation and W1 fallback.

Only the shared prediction-envelope invariant may be proposed for promotion. The task,
models, PCA, thresholds, costs, scene generator, plots, and evidence writer remain
experiment-local. `WORLD_MODEL_DECISION.md` names exactly one required role and reports
provenance, validity, co-primary and held-out results, W3/W4/W5 comparisons,
calibration/fallback/latency, resources, and immutable artifact hashes.

# P7 World-Model Candidate-Ranking Experimental Design

**Date:** 2026-08-22

**Status:** Approved design; no implementation plan

**Scope:** Reflect Lite Experiment 06

## 1. Decision

Experiment 06 will use a deterministic NumPy planar-pushing simulator, a fixed
set of eight one-second physical strategies, and compact CPU-only learned models.
It will test W0-W5 without CUDA, external checkpoints, online learning, or latent
action search.

The NumPy engine is the exact simulator only with respect to its declared,
versioned equations. W2 restores a snapshot and executes each candidate in that
same engine, so it is the exact oracle upper bound for the local benchmark. The
program, however, names MuJoCo for exact rollout ground truth
(`Reflect Lite Research Program.md:1909-1915`). Therefore NumPy-only evidence can
support offline scientific conclusions, but it cannot grant action-affecting
runtime authority. `CANDIDATE_SELECTOR` or `FAILURE_CRITIC` promotion additionally
requires a frozen MuJoCo conformance confirmation described in Section 11. If
MuJoCo is unavailable or conformance fails, the maximum decision is
`SHADOW_OBSERVER` or `OFFLINE_ANALYSIS_ONLY`.

This design tests only whether small predictors improve candidate ordering and
selection regret on a fixed planar-pushing benchmark, the experiment's stated
claim boundary (`Reflect Lite Research Program.md:1888-1907`). It does not claim
general manipulation, real-R1 transfer, useful image generation, or production
latent MPC.

## 2. Alternatives and trade-offs

### A. NumPy benchmark plus mandatory MuJoCo conformance — selected

A small deterministic engine makes data generation, counterfactual branching,
leakage audits, and closed-form training cheap and reproducible. A separately
frozen MuJoCo conformance run prevents its simplified contact model from granting
runtime authority by itself. The trade-off is a two-stage evidence path: local
scientific results may finish before promotion eligibility is known.

### B. MuJoCo as the only simulator

Using MuJoCo for every sample aligns directly with the named ground truth and
removes cross-simulator conformance. It adds a dependency not present in the
current project, makes exhaustive K=8 branching more expensive, and makes the
smallest benchmark depend on the source/platform gate. This is appropriate if
conformance shows the NumPy environment is not faithful enough, but not as the
first claim-search implementation.

### C. CPU neural world model with foundation-style visual encoder

A PyTorch MLP/CNN could represent richer nonlinear dynamics. It adds a large
dependency and more tuning degrees of freedom before low-capacity predictors have
been tested. Foundation encoders, video models, CEM/MPPI, and online learning are
explicitly deferred by the program (`Reflect Lite Research Program.md:1925-1930`),
so this approach is rejected for P7.

The selected approach uses only the current NumPy, PyArrow, and PyYAML runtime
dependencies (`pyproject.toml:5-15`). MuJoCo is an isolated conformance dependency,
not a dependency of model training or the primary local benchmark.

## 3. Scientific units and invariants

The scientific unit is a `scene_seed`. One scene seed owns its generated physical
parameters, probe rollout, anchor snapshots, all adjacent frames, all eight
candidate branches at every anchor, and every derived rendering. Statistics first
aggregate anchors within scene seed; paired inference operates across seeds. This
prevents candidates or nearby frames from being treated as independent evidence.

The benchmark has four immutable boundaries:

1. Candidate generation receives only the current declared state and its named
   candidate seed.
2. W0, W1, W3, W4, and W5 never receive future state, actual outcome, oracle cost,
   collision label, or W2 result before selection.
3. W2 and the scorer alone may branch the exact simulator from a snapshot.
4. Training, tuning, validation, and post-freeze confirmation are disjoint by
   scene ancestry and content hash.

Injection identities, future outcomes, and oracle cause labels remain hidden from
evaluated components, while W4's declared privileged current state remains legal,
matching the autonomous protocol (`docs/superpowers/specs/2026-08-22-reflect-lite-autonomous-run-design.md:183-198`).

## 4. Deterministic planar-pushing environment

### 4.1 State and physics

The bounded 2D world contains:

- a velocity-controlled circular end effector;
- one movable disk or rectangle with position, orientation, linear and angular
  velocity, mass, and friction;
- a target pose and tolerance region;
- zero or one axis-aligned wall or obstacle; and
- bounded workspace limits and collision/contact accounting.

The versioned NumPy engine uses fixed-step semi-implicit integration, deterministic
contact ordering, deterministic friction/impulse equations, finite-value checks,
and explicit terminal reasons. It exposes immutable snapshots and a pure
`step(state, command, parameters) -> state` transition. Every numeric equation,
tie rule, and clipping rule is serialized in the simulator configuration hash.

The generator has independent named RNG streams for scene geometry, physical
parameters, initial/target pose, obstacle layout, probe actions, candidate tie
breaking, split assignment, model initialization, bootstrap resampling, and W0
selection. Adding a draw to one stream cannot change another.

### 4.2 Exact K=8 strategy factory

At every anchor, the factory produces exactly eight one-second velocity-command
chunks in fixed ID order:

1. `DIRECT`: approach from the target-opposite contact point and push toward the
   target.
2. `LEFT_EDGE`: approach and push through the object's left edge in its local
   frame.
3. `RIGHT_EDGE`: the mirrored right-edge push.
4. `BELOW`: approach from the negative world-y/object support side, then push.
5. `DIAGONAL`: use the deterministic target-facing diagonal corner.
6. `RETREAT_REPOSITION`: move away for the first phase, move to the direct contact
   point for the second, and push for the third.
7. `SLOW_CONSERVATIVE`: execute the direct strategy with the frozen conservative
   speed multiplier.
8. `HOLD`: issue zero velocity for the full horizon.

A deterministic waypoint controller converts geometry into a two-column planar
velocity array. The chunks share a frozen sample interval, command limits, and
one-second horizon. Geometry and strategy ID, not random Gaussian perturbations,
create diversity. Infeasible approaches remain in the set and receive their
actual collision/failure cost. This implements the exact candidate taxonomy and
determinism requirement in the program
(`Reflect Lite Research Program.md:1943-1956`).

### 4.3 Actual cost and labels

The canonical actual cost is a frozen weighted sum of separately retained terms:

- final object-target position error;
- wrapped orientation error;
- collision and forbidden-contact count;
- action path length/energy proxy;
- terminal failure penalty; and
- success bonus expressed as a negative cost term.

Success tolerance, cost weights, collision semantics, and terminal rules freeze
before confirmation. Candidate truth records contain final state, every component,
total cost, success, collision, failure category, and progress. Ties use candidate
ID order only for deterministic selection; rank metrics use average ranks.

## 5. Dataset generation and leakage contract

For each scene seed, the generator samples declared mass, friction, geometry,
obstacle, start, and target parameters. A deterministic probe policy creates
selected anchor states covering approach, useful contact, failed contact,
collision, no-op-equivalent, and recovery contexts. At every anchor:

1. seal the immutable simulator snapshot;
2. build all K=8 candidates;
3. restore the same snapshot independently for each branch;
4. execute the full candidate in the exact NumPy engine; and
5. store every candidate outcome, whether or not any policy would choose it.

This satisfies the requirements to retain successful, failed, collision, no-op,
and recovery trajectories and all candidate counterfactuals
(`Reflect Lite Research Program.md:1986-1992`).

### 5.1 Four partitions

- **Training:** fits normalization, features, PCA, dynamics, outcome heads, and
  ensemble members.
- **Tuning:** chooses among the finite preregistered configuration grid. It never
  supplies fitted preprocessing statistics.
- **Validation:** selects one final configuration/checkpoint for each of W3, W4,
  and W5 and fits calibration/fallback thresholds.
- **Confirmation:** is generated only after the implementation commit and protocol
  hash freeze and is opened once for final evaluation.

Confirmation includes frozen in-distribution strata plus independently held-out
mass, friction, geometry, and obstacle distributions. Parameter ranges and stratum
weights are declared before confirmation generation.

### 5.2 Fail-closed leakage rules

All anchors, adjacent frames, candidates, renderings, augmentations, and simulator
ports descended from one scene seed stay in one partition. A manifest records
`scene_seed`, ancestor/probe seed, rollout ID, anchor IDs, parameter-cell ID,
canonical state hash, rendering hash, and split. Publication fails if any ancestry
or content hash appears in more than one partition.

Train-only statistics include feature normalization, outcome normalization, PCA
mean/basis, learned weights, ensemble sampling, and class weights. Tuning may rank
predeclared configurations. Validation alone chooses final configurations and
calibration. Confirmation cannot affect early stopping, checkpoint selection,
normalization, thresholds, candidate definitions, cost, exclusions, or retry
rules. Any post-freeze change invalidates the evidence and requires a new protocol
revision and unseen confirmation manifest
(`docs/superpowers/specs/2026-08-22-reflect-lite-autonomous-run-design.md:177-181`).

## 6. W0-W5 semantics and oracle isolation

Every selector receives the same ordered candidate IDs. W1 and learned variants
output predicted cost/order and outcome heads for all eight candidates before one
candidate is selected.

### W0 — seeded uniform random

A counter-based selector draws one candidate uniformly from the eight using only
the independent W0 seed, scene ID, and anchor ID. It is a sanity lower bound, not
a training baseline.

### W1 — strong hand-designed progress heuristic

W1 computes a nominal non-contact endpoint from the current object-target geometry
and action summary, then applies current target distance, orientation error,
straight-line obstacle/collision risk, contact-side alignment, and action cost. Its
formula and weights freeze. It cannot call the simulator, observe a future state,
or use learned parameters.

### W2 — exact simulator oracle upper bound

W2 restores the anchor snapshot, executes all eight candidates in the actual
dataset-generating NumPy simulator, evaluates canonical actual cost, and selects a
minimum. It has zero selection regret by construction. W2 is labelled
`ORACLE_EXACT_NUMPY`, is never deployable, does not participate in runtime latency
eligibility, and cannot supply features or predictions to another selector. In the
MuJoCo conformance phase, the analogous oracle is separately labelled
`ORACLE_EXACT_MUJOCO`.

### W3 — strong non-dynamics learned baseline

W3 is a regularized multi-head ridge predictor over the current privileged state
and fixed action summaries: endpoint displacement, path length, velocity moments,
contact-side encoding, strategy ID, and obstacle-line intersection. It predicts
cost, progress, success, collision, and failure, but no future state or latent.
This is the required strong low-capacity control.

### W4 — compact privileged-state dynamics

W4 is a deterministic bootstrap ensemble of regularized polynomial or fixed
random-feature residual models. It consumes the full current robot/object state
and a fixed resampling of the complete candidate chunk and predicts horizon state
delta, progress, success, collision, and failure. Canonical predicted cost is
recomputed from the predicted future state and heads. It conforms to the program's
privileged-state dynamics definition (`Reflect Lite Research Program.md:1976-1978`).

### W5 — compact observation-latent dynamics

W5 renders a deterministic 64-by-64 multichannel observation. A train-only
mean-centered truncated SVD/PCA encoder maps it to a compact latent. A regularized
latent transition consumes current latent and the full candidate chunk and
predicts future latent, progress, success, collision, and failure. Ranking uses
the progress/failure heads; pixel or reconstruction plausibility is never a gate.
No checkpoint is downloaded and no neural foundation encoder is used, consistent
with the program's compact visual option (`Reflect Lite Research Program.md:1980-1984`).

### Oracle enforcement

The simulator snapshot capability is held by dataset generation and W2 only.
Selectors are called through a narrow immutable batch containing current declared
input, candidates, and IDs. Actual outcome columns live in a separately opened
scorer table after predictions are sealed. Process- and test-level spies fail if
W0/W1/W3/W4/W5 call the simulator, open outcome paths, or consume W2 values.

## 7. Training and model selection

All compact learned models use deterministic NumPy linear algebra and canonical
feature ordering. Training runs on CPU with explicitly set numeric thread limits.
No data loader shuffles implicitly; named RNG streams generate all permutations
and ensemble resamples.

The sequence is strict:

1. Fit W3-W5 preprocessing and parameters on training only.
2. Evaluate the finite configuration grid on tuning only, within the frozen maximum
   attempt and compute budget.
3. Select one candidate configuration per variant using a frozen lexicographic
   tuning rule: regret, rank correlation, then smaller model.
4. Evaluate those candidates on validation; choose and freeze exactly one model per
   variant, calibration mapping, uncertainty threshold, and W1 fallback rule.
5. Hash implementation, simulator, data manifests, model files, preprocessing,
   protocol, and selection trace.
6. Generate the untouched confirmation manifest from a new recorded RNG seed.
7. Run confirmation once without refitting or threshold changes.

Pilot evidence can revise the protocol at most within the autonomous lifecycle.
No pilot can be marked supported; frozen confirmation produces the decision
(`docs/superpowers/specs/2026-08-22-reflect-lite-autonomous-run-design.md:127-143`).

## 8. Metrics and preregistered joint rule

### 8.1 Canonical co-primary outcomes

For each anchor:

- **Rank correlation:** tie-corrected Spearman correlation between predicted and
  actual K=8 cost order. A constant prediction is assigned zero correlation.
- **Selection regret:** actual cost of the selected candidate minus actual cost of
  W2's best available candidate. Lower is better.

These are the program's two canonical primary metrics
(`Reflect Lite Research Program.md:1994-2008`). Anchor metrics average within
scene seed. The paired scene-seed difference is the analysis unit.

### 8.2 Multiplicity and joint scientific gate

Use a deterministic 10,000-resample paired percentile bootstrap. The primary
family contains four learned-versus-W1 contrasts:

1. W4 rank-correlation improvement;
2. W4 regret reduction;
3. W5 rank-correlation improvement; and
4. W5 regret reduction.

Bonferroni-adjusted marginal 98.75% intervals give a 95% simultaneous family.
For a learned variant to establish the candidate-ranking claim, both its rank
lower bound and regret-reduction lower bound must be strictly greater than their
frozen minimum effects. Passing one cannot compensate for failing the other. This
preserves both canonical primaries while honoring the autonomous requirement that
regret and latency determine the hard authority gate
(`docs/superpowers/specs/2026-08-22-reflect-lite-autonomous-run-design.md:145-175`).

### 8.3 Strong-baseline and runtime gate

Scientific support is necessary but not sufficient for authority. An eligible W4
or W5 must also:

1. beat W3 on held-out selection regret by the frozen margin in a separate
   two-contrast Bonferroni family;
2. stay inside frozen single-candidate and full-K p95 CPU inference budgets;
3. stay inside model-byte and planner-context ceilings;
4. pass its frozen calibration/failure guard;
5. pass all leakage, oracle, determinism, artifact, and safety checks; and
6. pass the frozen MuJoCo conformance gate before action-affecting promotion.

If both pass, W4 is selected because it is the simpler privileged-state model,
unless W5 beats W4 on regret by a separately frozen hierarchical margin while
remaining non-inferior on rank, calibration, size, and latency. W2 reports oracle
headroom but is never a deployable competitor.

Secondary metrics are top-1 candidate accuracy, pairwise ordering accuracy,
oracle-gap closure, future-state error, progress/success Brier score and expected
calibration error, failure precision/recall, per-held-out-stratum rank/regret,
model bytes, train CPU time, p50/p95 inference, and uncertainty versus error, as
required by the program (`Reflect Lite Research Program.md:2010-2020`).

Timeouts, crashes, NaNs, and missing predictions receive a frozen worst-case
ordering and regret penalty unless an integrity failure makes the run `INVALID`.
Resource exhaustion produces `INCONCLUSIVE`, never negative scientific evidence.

## 9. Uncertainty, calibration, and fallback

W3-W5 use deterministic scene-seed bootstrap ensembles. Predictive uncertainty is
the frozen aggregation of member cost variance and failure-probability variance.
Validation alone fits a monotone calibration mapping and freezes a rejection
threshold.

Report:

- success and failure Brier score;
- fixed-bin reliability and expected calibration error;
- uncertainty versus absolute cost-error Spearman correlation;
- regret and error by uncertainty decile;
- selective coverage-risk curves; and
- W1 fallback frequency and regret.

The evidence-bearing runtime candidate selector is the frozen composition:
learned ranker below the uncertainty threshold, otherwise W1. Raw learned-only
results remain diagnostic. Confirmation cannot choose between raw and fallback
results after seeing outcomes.

## 10. Negative-result authority mapping

If neither W4 nor W5 clears both co-primary endpoints, W3, and latency, the
mechanical result is `STOP WORLD-MODEL AUTHORITY`, matching the program's hard gate
(`Reflect Lite Research Program.md:2022-2030`). The required decision then maps as
follows:

- `CANDIDATE_SELECTOR`: one variant passes every scientific, runtime, calibration,
  integrity, and MuJoCo conformance gate.
- `FAILURE_CRITIC`: candidate-ranking authority fails, but a separately
  preregistered failure precision/recall/calibration gate and MuJoCo conformance
  pass. It may veto/fallback but never rank candidates.
- `SHADOW_OBSERVER`: predictive evidence and latency pass, but no action-affecting
  authority gate or MuJoCo conformance passes. It logs predictions only.
- `OFFLINE_ANALYSIS_ONLY`: predictions are scientifically informative, but
  latency, calibration, W3 comparison, or conformance blocks runtime use.
- `NOT_USEFUL_YET`: no preregistered predictive or decision-utility gate passes.

`LATENT_SUBGOAL_MODEL_WORTH_TESTING` and `DIRECT_PLANNER_WORTH_TESTING` are
unreachable from this benchmark because it does not evaluate latent subgoals,
search, CEM/MPPI, or direct planning. A new bounded experiment would be required.
Negative evidence can therefore only reduce authority, never be reinterpreted as
permission for a larger model or planner.

## 11. Frozen MuJoCo conformance gate

The conformance phase starts only after the NumPy protocol, models, and local
confirmation are frozen. It ports a preregistered subset of confirmation parameter
cells into a pinned MuJoCo model with equivalent end-effector, object, target,
obstacle, command horizon, and cost semantics. MuJoCo scenes and seeds are unseen
before the freeze.

For each MuJoCo anchor, the harness executes the same eight strategy IDs using the
same command chunks, then records `ORACLE_EXACT_MUJOCO` outcomes. W4/W5 consume the
same declared current input mapping they would receive at runtime and are not
refit. Conformance reports:

- NumPy-versus-MuJoCo actual candidate-order Spearman correlation;
- agreement of oracle top candidate;
- per-component cost discrepancy;
- collision/failure label agreement;
- W4/W5 MuJoCo rank correlation and selection regret versus W1 and W3; and
- uncertainty/fallback behavior under simulator shift.

Runtime authority requires the full confidence interval to clear frozen
conformance margins for order agreement and learned-selector regret, no degradation
beyond frozen collision/failure tolerances, and the same latency/calibration hard
gates. MuJoCo is the authority-bearing exact ground truth in this phase. A failed
or unavailable conformance phase does not invalidate the bounded NumPy scientific
result; it caps authority at shadow/offline. It never triggers automatic simulator
tuning on confirmation scenes.

## 12. Artifact contracts

Each immutable run uses the shared rollout files:

```text
metadata.json
config.json
metrics.json
events.jsonl
observations.npz
actions.parquet
summary.md
candidates.parquet
```

The first seven are already required and `candidates.parquet` is already an
allowed optional payload (`reflect/rollout.py:60-75`). Experiment-local evidence
adds:

- `dataset_manifest.json`: generator, simulator, config and source hashes; scene
  ancestry, splits, strata, counts, and content hashes.
- `anchors.parquet`: scene/rollout/anchor IDs, snapshot hash, current declared
  state, observation reference, and parameter cell.
- `candidates.parquet`: all eight chunks, strategies, truth outcomes/cost
  components, predictions, uncertainty, ranks, and selection/fallback flags.
- `models/w3.npz`, `models/w4.npz`, `models/w5.npz`: parameters,
  preprocessing/PCA, calibration, schema, and hashes.
- `training_history.jsonl`: bounded attempts and train/tuning/validation results.
- `selection.json`: complete configuration/checkpoint/calibration selection trace.
- `bootstrap.json`: seed-level values, resample seed, contrasts, intervals, and
  multiplicity families.
- `conformance/`: pinned MuJoCo XML/config, mapping hash, candidate outcomes,
  metrics, bootstrap, and decision.
- `decision.json` and `WORLD_MODEL_DECISION.md`: every gate component, authority
  ceiling, selected role, and rejected alternatives.
- `manifest.json`: relative paths, sizes, media types, and SHA-256 values, written
  last by atomic rename.

JSON is canonical UTF-8; JSONL has one canonical object per newline; Parquet
schemas, nullability, order, and sort keys are frozen. Model arrays are finite,
explicitly shaped, and stored in deterministic NPZ form with external file hashes.

Runtime-compatible output uses the existing `WorldModelPrediction`, which already
contains candidate identity, horizon, progress, success/failure probabilities,
predicted state/latent, uncertainty, and inference time
(`reflect/types.py:347-374`). Existing events represent prediction and selection
(`reflect/events.py:18-37`), and replay rejects selecting a missing or ambiguous
candidate (`reflect/replay.py:299-317`).

## 13. Verification design

Tests are offline and deterministic except the separately labelled serial latency
measurement and pinned MuJoCo conformance smoke.

- Golden simulator tests prove byte-identical traces for identical config/seeds.
- Named-RNG tests add draws to one stream and prove all other outputs stay fixed.
- Strategy tests require exactly eight fixed IDs, distinct physical command paths,
  one-second horizons, fixed ordering, and valid `ActionChunk` arrays.
- Snapshot tests prove every candidate begins from identical bytes and independent
  branching cannot mutate the anchor.
- W2 tests prove it executes all eight exact branches, selects a true minimum,
  produces zero regret, and is labelled/nondeployable.
- Hostile-selector tests prove W0/W1/W3/W4/W5 cannot access snapshots, simulator
  methods, truth outcomes, oracle labels, or W2 scores.
- Dataset tests cover all outcome categories, K=8 completeness, counterfactual
  storage, source/config hashes, and canonical row ordering.
- Leakage tests reject shared scene ancestry, rollout, adjacent frame, candidate,
  rendering, state hash, or augmentation across partitions.
- Fit spies prove normalization, PCA, features, parameters, class weights,
  calibration, and thresholds see only allowed partitions.
- Confirmation-access tests make the manifest nonexistent until post-freeze and
  reject reopening it during training or selection.
- W1 golden tests cover cost terms and prove no simulator call.
- W3 tests prove the strong baseline predicts no future state or latent.
- W4 tests prove predicted state drives recomputed canonical cost.
- W5 tests prove train-only PCA, no network/checkpoint access, and no pixel-loss
  decision path.
- Metric tests cover average ranks, ties, constant predictions, regret, seed
  aggregation, worst-case missing output, bootstrapping, multiplicity, hierarchical
  gates, and exact threshold boundaries.
- Calibration tests cover ensemble determinism, Brier/ECE, uncertainty deciles,
  selective risk, and W1 fallback.
- Artifact tests verify exact schemas, finite values, hashes, cross-file IDs,
  atomic finalization, corruption rejection, and replay.
- Negative-decision tests prove a failed authority gate cannot emit a selected
  action-affecting event or promoted adapter.
- MuJoCo tests verify pinned source/model/config identity, state/action mapping,
  candidate identity, exact-oracle labels, conformance metrics, and the authority
  cap on failure/unavailability.
- Latency tests run serially with CPU/thread/platform metadata and no concurrent
  training.

## 14. Resources and numeric freeze fields

Fixed governance ceilings apply unchanged: no single command over 60 minutes
without resumable checkpoints, at most three tuning configurations per variant
after the initial pilot, no paid/remote compute, serial latency measurement, named
RNG streams, less than 10 GB generated artifacts per pass, at most 256 paired pilot
episodes per variant, and at most 1,024 paired confirmation episodes
(`docs/superpowers/specs/2026-08-22-reflect-lite-autonomous-run-design.md:200-235`).
The local benchmark additionally requires CPU-only execution, no external model
checkpoint, no network, and no physical deployment.

The following evidence-dependent numeric fields must all be written explicitly to
the frozen protocol; none has a runtime default:

1. integrator step, contact stiffness/damping, friction law parameters, numerical
   tolerances, and terminal horizon discretization;
2. workspace, object, target, obstacle, mass, friction, and initial-state ranges;
3. action sample interval, speed/acceleration limits, phase fractions, approach
   offset, diagonal rule, and conservative speed multiplier;
4. success position/orientation tolerances and every canonical cost weight;
5. probe-policy length, anchor-selection rule/count, scene counts, partition
   proportions, and confirmation stratum weights;
6. in-distribution and held-out mass, friction, geometry, and obstacle ranges;
7. W1 heuristic weights and collision/line-intersection tolerances;
8. W3/W4 feature degree/dimension, fixed-feature seed, regularization, ensemble
   size, and class weights;
9. W5 rendering channels, PCA dimension, latent-transition regularization, and
   candidate-action resampling dimension;
10. finite tuning grids, selection tie margins, maximum iterations, and numeric
    solver tolerances;
11. calibration binning, monotone-map parameters, uncertainty aggregation,
    rejection threshold, and minimum fallback coverage;
12. rank-correlation and regret minimum effects versus W1;
13. regret minimum effect versus W3 and W5-over-W4 promotion margin;
14. failure-critic precision, recall, Brier/ECE, and selective-risk limits;
15. model-byte, train CPU-time, single-candidate latency, K=8 batch latency,
    context-size, command-timeout, and artifact ceilings;
16. missing-output/worst-case regret penalty and invalid-run limits;
17. bootstrap seed, scene counts, resample count if stricter than the fixed 10,000,
    and confidence/multiplicity settings;
18. MuJoCo scene count, parameter mapping tolerances, order-correlation minimum,
    oracle top-choice agreement minimum, cost discrepancy tolerances,
    collision/failure agreement minimum, and learned regret/rank conformance
    margins.

Pilot selects these values using recorded feasibility, variance, task-unit, and
resource evidence from pilot-only seeds. Candidate grids exist before pilot; the
selection trace and rejected values are preserved. Exact numbers freeze before
confirmation. Inventing them in this design would create false precision because
the repository has not yet measured contact fidelity, variance, inference latency,
or memory size.

## 15. Downstream boundaries

### Experiment 07 / P8 local specialist

The specialist experiment may reuse only the frozen planar task, scenario
generator, canonical cost components, candidate/action schema, and evaluation
metrics. It proceeds as an independent claim search whether or not Experiment 06
grants authority (`docs/superpowers/specs/2026-08-22-reflect-lite-autonomous-run-design.md:102-106`).
Its specialist emits `ActionChunk`; it does not consume W4/W5 internals or reward
state (`Reflect Lite Research Program.md:2118-2150`).

### Experiment 08 / P9 R1 transfer

R1 transfer may consume only a separately promoted prediction/critic/selector
protocol through an explicit state/action adapter. W2 never transfers. Privileged
W4 remains simulation-only until the R1 mapping is independently validated. W5
does not imply visual transfer merely because its local latent gate passed. The
R1 experiment exists to test whether the shared runtime contracts survive an
embodiment change (`Reflect Lite Research Program.md:2222-2241`).

### Experiment 09 integration

Mini-Reflect may enable only the role granted by `WORLD_MODEL_DECISION.md`:
shadow, failure critic/veto, or candidate selector. Its architecture places the
optional world model between candidate `ActionChunk` generation and executor
validation (`Reflect Lite Research Program.md:2454-2473`), and branches H/I/J run
only when justified by prior gates (`Reflect Lite Research Program.md:2522-2537`).
W1 remains the frozen fallback; executor validation and short-prefix execution
remain mandatory. No integration task may upgrade negative P7 evidence.

Only the smallest validated prediction/selection schema and runtime invariant may
move into `reflect/`. The toy simulator, candidate geometry, cost weights, learned
models, calibration, thresholds, plots, and MuJoCo port remain experiment-local,
matching the interface-promotion boundary
(`Reflect Lite Research Program.md:3153-3181`).

## 16. Parallel-safe decomposition

Preparation can use six ownership-isolated workstreams:

1. **World owner:** NumPy state, physics, snapshot, strategy factory, and golden
   traces.
2. **Dataset owner:** probe generation, named RNG, partitions, manifests, and
   leakage validator.
3. **Baseline owner:** W0-W3, W2 oracle capability boundary, and canonical costs.
4. **Learned-model owner:** W4/W5, train-only preprocessing, tuning, calibration,
   and deterministic model serialization.
5. **Evaluation owner:** seed aggregation, co-primary bootstrap, multiplicity,
   runtime/negative-result gates, and decision mapping.
6. **Artifact/conformance owner:** rollout integration, replay, atomic manifests,
   latency harness, MuJoCo port, and downstream conformance fixtures.

The state/candidate schemas, simulator equations, candidate IDs, split ancestry,
cost components, and golden fixtures freeze before parallel preparation. Workers
may use pilot/golden shards, never confirmation data. Training and artifact work
can proceed in parallel after those contracts freeze. Validation selection,
protocol freeze, confirmation generation, confirmation evaluation, latency
measurement, MuJoCo conformance, and final promotion are serial orchestrator
operations.

## 17. Required decision output

`WORLD_MODEL_DECISION.md` chooses exactly one program-defined role and links the
immutable local and conformance manifests. It reports both co-primary outcomes,
W3 comparison, latency, calibration, uncertainty/fallback, every integrity gate,
the MuJoCo authority ceiling, and rejected roles. The choice is based on held-out
ranking, regret, calibration, and latency rather than visual plausibility, as
required by the program (`Reflect Lite Research Program.md:2048-2062`).

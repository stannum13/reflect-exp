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
for the disjoint pilot that sets the common protocol and for unseen confirmation.
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

### C. NumPy precursor, then MuJoCo pilot/freeze/confirmation — selected

NumPy provides cheap exhaustive development data and deterministic contract tests. A
disjoint MuJoCo pilot validates the final data/model/calibration path and sets all
evidence-dependent values before one common freeze. Unseen MuJoCo confirmation then
answers the claim. The extra transition is intentional: it makes simulator authority
explicit and permits negative NumPy validity results to stop work before expensive
MuJoCo evidence.

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
```

`strategy_id` is the reusable semantic strategy; `candidate_id` is the globally
unique instance. Every prediction, truth row, selection, action row, and event carries
both. IDs cannot be derived from labels or row positions.

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

Each action's SHA-256 covers canonical little-endian float64 shape, bytes, `dt_s`,
horizon, command limits, strategy ID, scene ID, and anchor ID. The eight action hashes
must be distinct. Before any branch runs, an independent regeneration pass reconstructs
all actions from the sealed anchor/config and requires byte/hash equality. Duplicate,
missing, reordered, or nondeterministically regenerated actions make the scene bundle
`INVALID`; they are never dropped or resampled. This is the program's meaningful,
non-Gaussian K=8 taxonomy (`Reflect Lite Research Program.md:1943-1956`).

## 4. NumPy precursor validity gate

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
   candidate ordering must remain inside pilot-frozen tolerances. Order uses Kendall
   disagreement count with average-rank ties.

Every invariant and candidate must pass. A failure makes the NumPy precursor
`INVALID` and P7 `STOPPED`; moving directly to MuJoCo would require a new reviewed
protocol, not an automatic workaround. Passing this gate still grants no authority.

## 5. Data partitions and leakage prevention

### 5.1 NumPy development partitions

NumPy uses 96 training, 24 tuning, and 24 validation scene seeds, with four anchors
and K=8 branches per scene. Training fits preprocessing and models. Tuning chooses
among the finite configuration grid. Validation selects one W3/W4/W5 checkpoint,
calibration map, uncertainty threshold, and W1 fallback rule. These 144 seeds and
their RNG ancestors are permanently excluded from MuJoCo pilot/confirmation.

### 5.2 MuJoCo evidence partitions

After NumPy selection, a disjoint MuJoCo pilot uses five strata with eight scene seeds
per stratum, 40 total. Within each stratum, the first four sorted scene IDs are
adaptation seeds and the final four are untouched pilot-evaluation seeds. NumPy
preprocessing, feature maps, PCA, model structures, regularization, and W1 freeze before
MuJoCo pilot. On adaptation seeds only, W3/W4/W5 linear output coefficients are refit
once on the union of NumPy training and MuJoCo adaptation rows; the feature/latent
transition remains fixed. Calibration maps and fallback thresholds fit adaptation
seeds only. Pilot-evaluation seeds validate state/action mapping and estimate margins/
resources once; they cannot trigger refit, recalibration, or model selection. It is
labelled exploratory and cannot support a claim.

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
candidate, parameter cell, state/render/action hashes, simulator, and partition. All
adjacent frames, candidates, augmentations, and simulator ports descended from one
scene remain together. Any shared ancestor or content hash across train, tune,
validation, MuJoCo pilot, or confirmation makes the dataset `INVALID`.

Train-only statistics include normalization, feature maps, PCA, ensemble resamples,
and class weights. Tuning alone ranks configurations. Validation alone selects NumPy
checkpoints/fallback. MuJoCo pilot alone performs the one predeclared final calibration
or refit. Confirmation is read once after freeze.

## 6. W0-W5 and exact prediction envelope

Every selector receives the same ordered candidate IDs/actions and declared current
input. W0/W1/W3/W4/W5 cannot open snapshots, simulator APIs, actual outcomes, W2
scores, or truth paths. Truth and selector outputs are separately sealed before the
scorer joins them.

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

A deterministic bootstrap ensemble of frozen polynomial/random-feature ridge models
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
sort descending. For an exactly equal singular-value group, project standard pixel
basis vectors in ascending pixel index into the tied subspace and apply deterministic
modified Gram-Schmidt, accepting the first vector above the frozen norm tolerance,
until the subspace is spanned. For each final component, find the maximum-absolute
loading; the lowest pixel index breaks ties, and its sign is forced positive. Components,
means, singular values, tolerance, and input hashes are serialized. This canonicalizes
both signs and equal-singular-value ordering across repeated CPU runs.

### 6.2 Prediction envelope and scalar cost

W1/W3/W4/W5 emit one exact envelope per candidate:

```text
observation_id, scene_id, anchor_id, candidate_id, strategy_id, action_sha256,
model_id, model_sha256, horizon_s,
predicted_position_error_m, predicted_orientation_error_rad,
predicted_collision_probability, predicted_action_energy,
predicted_failure_probability, predicted_success_probability,
predicted_state_sha256 | null, predicted_latent_sha256 | null,
uncertainty, inference_ms, predicted_cost
```

Probabilities are finite in `[0,1]`; errors, energy, uncertainty, and inference time
are finite and nonnegative. The scalar formula is identical across W1/W3/W4/W5:

```text
predicted_cost =
    w_position * predicted_position_error_m^2
  + w_orientation * wrapped(predicted_orientation_error_rad)^2
  + w_collision * predicted_collision_probability
  + w_energy * predicted_action_energy
  + w_failure * predicted_failure_probability
  - w_success * predicted_success_probability
```

Actual MuJoCo cost substitutes actual component values and binary collision/failure/
success indicators into the same formula. W3/W5 predict every scalar component
directly; W4 derives state-dependent errors from predicted state; W1 computes its
declared analytic estimates. Candidate order is `(predicted_cost ascending,
uncertainty ascending, candidate_id ascending)`. No variant-specific cost or tie rule
is allowed.

W1 uses `model_id=W1`, its frozen configuration hash as `model_sha256`, uncertainty
`0.0`, and null state/latent hashes. W3 uses null state/latent hashes. W4 requires a
predicted-state hash and null latent hash; W5 requires a predicted-latent hash and null
state hash. The envelope validator rejects any other nullability pattern.

## 7. Training, PCA, calibration, and common freeze

The sequence is strict:

1. Pass the NumPy validity gate.
2. Fit preprocessing/W3-W5 on NumPy training only.
3. Evaluate at most three preregistered configurations per variant on NumPy tuning.
4. Select one checkpoint per variant on NumPy validation by regret, rank correlation,
   model bytes, then configuration ID.
5. Run the disjoint MuJoCo pilot. Apply the one predeclared final refit/calibration to
   MuJoCo pilot only; never revisit NumPy selection.
6. Freeze models, PCA, scalar cost, W1, uncertainty/fallback, strata, margins, budgets,
   P3 MuJoCo identity, implementation, schemas, and all hashes in one protocol.
7. Generate the unseen MuJoCo confirmation manifest and run once.

Any post-freeze change returns to Draft with a new protocol revision and new unseen
MuJoCo pilot/confirmation roots. No pilot output can be `SUPPORTED`
(`docs/superpowers/specs/2026-08-22-reflect-lite-autonomous-run-design.md:127-181`).

## 8. Uncertainty and authority-bearing fallback

W3-W5 use deterministic scene-seed bootstrap ensembles. Cost uncertainty is ensemble
variance; failure uncertainty is probability variance. MuJoCo pilot fits a frozen
monotone calibration map and one uncertainty rejection threshold per learned variant.

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
`[protocol_hash, family_id, contrast_id, stratum_id, "exp06-bootstrap-v1"]`. Each
resample draws the complete paired-scene count with replacement. Sorted bootstrap
values use endpoint index `max(0, ceil(p * 10000) - 1)` without interpolation or tie
deduplication. Equality fails superiority and passes non-inferiority. Missing/timeout
predictions receive frozen worst-case rank/regret unless an integrity breach makes the
bundle invalid; resource exhaustion yields `INCONCLUSIVE`.

## 10. Separate states and ordered role mapping

Lifecycle is `DRAFT -> NUMPY_PILOT -> MUJOCO_PILOT -> FROZEN -> CONFIRMATION ->
DECISION -> PROMOTED | STOPPED`. Artifact state is separately `VALID | INVALID`;
scientific result is `SUPPORTED | NOT_SUPPORTED | INCONCLUSIVE`; prerequisite/resource
state is `READY | BLOCKED`; promotion state is `PROMOTED | STOPPED`. Invalid evidence
has no scientific result, and a blocker is not negative evidence.

For `VALID + READY` confirmation, exactly one role is chosen by first matching rule:

1. `CANDIDATE_SELECTOR` if one learned+W1-fallback composition passes every co-primary,
   held-out, W3, latency, calibration, safety, and selection gate.
2. `FAILURE_CRITIC` if rule 1 fails but a predeclared learned failure head passes its
   simultaneous held-out precision/recall, calibration, latency, and zero-unsafe-veto
   gate. Precision and recall for the four held-out strata form one eight-endpoint
   Bonferroni family with 99.375% marginal intervals; every lower bound must clear its
   frozen minimum. A critic may only replace the learned choice with W1 and cannot
   rank or introduce another action.
3. `SHADOW_OBSERVER` if rules 1-2 fail but held-out prediction calibration and latency
   pass; it emits no action-affecting event.
4. `OFFLINE_ANALYSIS_ONLY` if rules 1-3 fail but at least one preregistered prediction
   endpoint excludes the null in the useful direction.
5. `NOT_USEFUL_YET` otherwise.

`LATENT_SUBGOAL_MODEL_WORTH_TESTING` and `DIRECT_PLANNER_WORTH_TESTING` are unreachable
because this benchmark does not test those claims. `SUPPORTED` requires rule 1;
rules 2-4 are scientifically `NOT_SUPPORTED` for candidate ranking but preserve the
bounded lesser role. `INCONCLUSIVE`, `INVALID`, or `BLOCKED` cannot promote. Only
`VALID + SUPPORTED + READY + CANDIDATE_SELECTOR` promotes selector authority; a valid
critic gate may separately promote only the critic/veto interface.

## 11. Atomic evidence bundle and replay

The canonical `RolloutWriter` remains unchanged. A sealed experiment-local assembler
wraps its output after separately sealed generator truth and selector prediction
components validate:

```text
bundle/
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
    anchors.parquet
    candidate_actions.parquet
    predictions.parquet
    selections.parquet
    candidate_truth.parquet
    score_metrics.json
    replay.json
  bundle-manifest.json
```

Each subdirectory under `rollouts/` is an unchanged independently replayable canonical
rollout. This prevents multiple selectors from emitting duplicate candidate IDs into
one shared replay state. `candidate_actions.parquet` stores all K=8 IDs, strategy IDs,
arrays, timing, and action hashes. `predictions.parquet` stores exact raw and composed
envelopes. `selections.parquet` stores W0/W1/W2/W3/raw W4/raw W5/W4F/W5F selections,
uncertainty decision, selected candidate/action hash, and W1 fallback reason.
`candidate_truth.parquet` is scorer-only MuJoCo truth with actual cost components/
outcomes and W2 selection. Primary ranking-only canonical `actions.parquet` tables are
empty; if the later short-prefix extension executes a selected `ActionChunk`, its
metadata must match candidate/action hash exactly.

Within each W1/W3/W4F/W5F canonical rollout, exactly one `WORLD_MODEL_PREDICTED` event
cross-links each globally unique candidate ID and one `WORLD_MODEL_SELECTED` per anchor
cross-links the sealed selection. W4F/W5F events use the learned envelope below the
threshold and the W1 envelope after fallback, never both. The existing replay invariant—
selection resolves to exactly one prediction—therefore remains usable
(`reflect/replay.py:299-317`). Raw W4/W5 and W0/W2 remain sidecar-only. The bundle
validator additionally requires:

The prediction event payload contains `scene_id`, `anchor_id`, `candidate_id`,
`strategy_id`, `action_sha256`, `model_id`, and the prediction-envelope digest. The
selection event contains the same scene/anchor IDs plus selected `candidate_id`,
`strategy_id`, `action_sha256`, `model_id`, selection-row digest, and fallback reason.
The values are copied from sealed sidecar rows; events cannot synthesize or normalize
identities during publication.

- exactly eight candidate/action/truth rows per anchor and eight distinct action hashes;
- regenerated candidate bytes/hashes equal the stored action rows;
- every prediction references one candidate/action hash/model hash;
- every selection references one prediction and the same action hash;
- every truth row references one candidate/action hash and pinned MuJoCo snapshot;
- every prediction/selection event matches exactly one selector-specific sidecar row
  and ordering, with no candidate duplicated inside one canonical rollout;
- any canonical executed action matches the selected candidate/action hash; and
- all scene/anchor/candidate/strategy IDs and counts agree across files.

Replay reconstructs observations, candidate actions, prediction envelopes, fallback
decisions, selections, events, truth joins, W2, scores, and terminal cross-link state
without rerunning physics or models. It verifies evidence, not counterfactual dynamics.

The experiment-local boundary has three named responsibilities:

- `EvidenceBundleWriter` accepts only already sealed generator, selector, and scorer
  component descriptors; copies them into one sibling temporary tree; invokes all
  validators; writes the manifest; fsyncs; and performs one absent-destination rename.
- `validate_evidence_bundle` validates every canonical rollout first, then exact
  sidecar schemas, hashes, IDs, counts, action regeneration, event ordering, oracle
  isolation attestations, and all cross-links. Validation has no repair mode.
- `replay_evidence_bundle` consumes only the finalized bundle and returns canonical
  reconstructed selector/anchor state plus recorded metric inputs. It cannot load a
  simulator/model or change a score.

Generator truth is sealed before selector processes start but its descriptor/path is
held only by the orchestrator. Selector outputs seal before the scorer receives truth.
The writer starts only after both boundaries validate, so co-location in the finalized
evidence bundle cannot become a preselection truth channel.

The assembler writes a sibling temporary bundle, validates every canonical rollout and all
sidecars, fsyncs files/directories, and atomically renames into an absent destination.
`bundle-manifest.json` lists every other immutable file with path/media type/bytes/
SHA-256, excludes itself and temporary files, contains no field for its own digest, and
is created last. Extra/missing files, a self-digest, cross-link mismatch, corruption,
or overwrite attempt fail closed.

## 12. Evidence commands, shards, resume, and resources

One evidence command executes one shard keyed by
`(protocol_revision, phase, stratum, scene_seed)`, for example
`r1:mujoco-confirmation:MASS_OOD:0000000000000017`. Valid phases are
`numpy-train`, `numpy-tuning`, `numpy-validation`, `mujoco-pilot`, and
`mujoco-confirmation`. One scene shard contains four anchors and 32 candidate branches.

The exact confirmation command is:

```text
python experiments/06_world_model/run.py \
  --protocol configs/frozen.yaml \
  --shard-id r1:mujoco-confirmation:MASS_OOD:0000000000000017 \
  --output-root results/06_world_model --headless \
  --max-anchors 4 --max-candidates 32
```

Evidence rejects unknown/mismatched shard components, missing headless mode, a
candidate/anchor limit other than the complete shard, unpinned MuJoCo identity, dirty
implementation, network/CUDA/physical/remote enablement, or an output not derived from
the shard key. Reissuing the identical command is the only resume operation: it fully
validates and skips an exact sealed bundle, while mismatch/corruption/partial temporary
state fails without overwrite or in-place repair.

Each scene bundle has a 16 MiB ceiling and 60-minute wall ceiling. One model/config
training shard has a 32 MiB ceiling; there are at most three configurations for W3,
W4, and W5, nine per revision. With two allowed protocol revisions and confirmation
only on the final revision, the retained maximum is:

```text
two revisions of NumPy+MuJoCo pilot scenes:
  2 * (144 + 40) * 16 MiB = 5,888 MiB
final MuJoCo confirmation:
  80 * 16 MiB             = 1,280 MiB
two revisions of training/config shards:
  2 * 9 * 32 MiB          =   576 MiB
aggregate/model/decision allowance          = 512 MiB
-----------------------------------------------------
maximum retained P7 total                  = 8,256 MiB
```

The count includes truth, predictions, scorer output, and canonical rollout inside
each atomic bundle; nothing is budgeted off-ledger. Before a phase starts, preflight
adds all retained bytes, temporary directories, and the complete declared phase
maximum, and requires both the 8,256 MiB experiment cap and inherited 10 GiB/free-disk
ceilings. No shard is deleted until final decision. A cap/timeout yields `INCONCLUSIVE`,
never evidence against a model.

## 13. Pilot-derived frozen numeric fields

Finite NumPy grids exist before the precursor. MuJoCo pilot chooses and freezes, by
recorded formulas/ties, every evidence-dependent value:

1. NumPy/MuJoCo step/contact tolerances and NumPy analytic/physical/step-halving gates;
2. workspace, object, target, obstacle, mass, friction, and held-out parameter ranges;
3. action sample interval, limits, phase fractions, offsets, and conservative speed;
4. success tolerances and every scalar cost weight;
5. probe policy and four-anchor selection rule;
6. W1 weights and collision/line-intersection rule;
7. W3/W4 features, regularization, ensemble size, and fixed-feature seed;
8. W5 channels, PCA dimension/tolerance, latent/action dimensions, and regularization;
9. final MuJoCo refit/calibration method, bins, uncertainty aggregation/threshold,
   fallback coverage, and failure-critic gates;
10. co-primary, held-out, W3, and W5-versus-W4 effect/NI margins;
11. model/context/latency/training/resource ceilings and missing-output penalty; and
12. bootstrap/configuration seeds and numeric solver tolerances.

For each scientific endpoint, margin is
`ceil_to_unit(max(one_task_unit, 0.5 * paired_scene_sample_SD))`, computed only from
the 20 untouched MuJoCo pilot-evaluation scenes, with sample SD denominator `n-1`;
`ceil_to_unit(x)=ceil(x/unit)*unit`. Rank-correlation unit is `0.001`; probability/rate
unit is one anchor outcome over its fixed pilot denominator; regret/cost unit is the
smallest positive frozen cost quantum; latency unit is 0.1 ms; and bytes round to
1024. Resource limits use `ceil_to_unit(1.25 * maximum_usage)` across all 40 MuJoCo
pilot scenes and must remain under inherited caps. Zero SD yields one unit;
unattainable margins make the result `INCONCLUSIVE`, never clipped. Configuration
selection is regret, rank, calibration, model bytes, then configuration ID; exact
ties continue to the next key.

## 14. Verification design

Tests cover:

- P3 pinned MuJoCo/source-lock prerequisite and refusal of alternate model/version;
- NumPy analytic, physical, mirror, and step-halving gates with hand fixtures;
- exact K=8 IDs, globally unique candidate IDs, eight distinct action hashes,
  independent regeneration, and invalid duplicate/nondeterministic disposition;
- immutable snapshots, named RNG independence, and byte-identical generation;
- split ancestry/content leakage across all five partitions;
- fit spies proving preprocessing/PCA/models/calibration see only allowed partitions;
- MuJoCo pilot before common freeze and nonexistent unseen confirmation before freeze;
- W0-W5 input boundaries and hostile oracle/simulator/path access;
- exact prediction envelope fields, finite/range checks, scalar cost components,
  W3/W4/W5 derivation, and universal tie ordering;
- PCA sign and equal-singular-subspace canonicalization;
- average-rank Spearman plus both constant-actual/predicted cases and regret tolerance;
- exact 0.20 stratum aggregation, co-primary/held-out/W3/W5-vs-W4 families,
  bootstrap seeds/endpoints, equality boundaries, and missing rules;
- learned+W1 fallback as the sole authority-bearing result, with raw metrics descriptive;
- ordered mutually exclusive roles and separate lifecycle/artifact/scientific/blocker/
  promotion states;
- unchanged canonical rollout, exact sidecar schemas, every cross-link, prediction/
  selection events, truth/action joins, replay, manifest self-exclusion, corruption,
  and atomic publication;
- exact shard parsing/CLI/case bounds, validate-and-skip resume, mismatch refusal,
  8,256 MiB arithmetic, phase preflight, 60-minute/size ceilings; and
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
IDs/hashes, scalar cost, bundle schemas, NumPy validity fixtures, and MuJoCo mapping
freeze before parallel preparation. NumPy fitting may run after that contract freeze.
MuJoCo pilot, common protocol freeze, confirmation-manifest generation, confirmation,
serial latency, role decision, and promotion remain serial orchestrator operations.

`WORLD_MODEL_DECISION.md` links immutable pilot/confirmation bundles and records the
separate lifecycle, validity, blocker, scientific, role, and promotion states. It
reports both canonical primaries, all strata/families, W3 and W5/W4 decisions,
fallback/calibration/latency, and rejected roles. Exactly one reachable role is named,
based on held-out ranking, regret, calibration, and latency rather than visual
plausibility (`Reflect Lite Research Program.md:2048-2062`).

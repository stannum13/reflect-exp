# Exp13 Direct Hierarchy Outcome Design

**Status:** approved for implementation and execution
**Date:** 2026-08-24
**Authority:** bounded nonconfirmatory engineering experiment

## Disposition of V3

Hierarchical Recovery V3 at `0a5f50b3148b1dc618353e7c85ad18ce11ae012e`
remains `REJECTED_CAUSAL_AUTH`. Its qualification evidence is preserved, its outcome
root remains absent, and no V3 held-out seed is executed. Exp13 makes no causal
sufficiency, lowest-sufficient-level, or mechanism-identification claim.

## Question

On paired physical MuJoCo manipulation disturbances, does the observable-only R3
hierarchy retain direct mission success, safety, and progress relative to R0, R1,
and R2 while avoiding unnecessary recovery activity? This is a direct outcome
comparison, not a claim that any intervention was causally minimal.

## Alternatives considered

1. **Design A, selected:** 480 P6 primary cells with ten paired seed clusters plus
   60 separately scoped R3/P4 sensitivity cells on the first five seeds. This keeps
   primary effective sample size at ten while bounding sensitivity cost.
2. P6-only, 480 cells. This is cheaper but omits the registered controller
   sensitivity check.
3. A new bespoke simulator. Rejected because it would weaken continuity with the
   already qualified production MuJoCo/controller path.

## Frozen matrix

The fresh held-out seed namespace is exactly `20261901..20261910`. No seed from the
V3 outcome namespace is reused.

- Architectures: `R0`, `R1`, `R2`, `R3`.
- Families: `control-impulse`, `control-dropout`, `motion-target-shift`,
  `motion-path-infeasible`, `semantic-object-unavailable`, and
  `semantic-restriction-change`.
- Severity labels: `LOW`, `HIGH`.
- Primary controller: `P6-res0p5-slew48` on every architecture/family/severity/seed,
  exactly `4 * 6 * 2 * 10 = 480` cells.
- Sensitivity controller: `P4-lookahead1-dqon` on R3 only and seeds
  `20261901..20261905`, exactly `6 * 2 * 5 = 60` cells.
- Total: exactly 540 dispositions.
- Primary `n_eff=10` paired seed clusters. P4 sensitivity is isolated and reported
  as `n_eff=5`; it never increases primary evidence count.

Severity is deterministic and architecture-blind. A seed first samples shared
initial joints, targets, damping, injection tick, directions, and geometry. The
registered level then sets only the family dose:

| Family | LOW | HIGH |
|---|---:|---:|
| control impulse | `0.14 N.m` for `5` ticks | `0.26 N.m` for `10` ticks |
| control dropout | `25` ticks | `50` ticks |
| target shift | `0.040 m` | `0.065 m` |
| path obstacle radius | `0.0375 m` | `0.0475 m` |
| object-unavailable delivery latency | `2` ticks | `10` ticks |
| restriction-change delivery latency | `2` ticks | `10` ticks |

## Runtime and information boundary

Exp13 adds an explicit, typed realization/precheck injection seam to the existing V3
production episode kernel. Default V3 behavior remains unchanged. Exp13 supplies a
frozen realization and uses the same MuJoCo model, P6/P4 representation emitters,
executor states, bounded PD controller, observable builder, hierarchy policy,
budgets, re-observation timing, action guards, and 3,125-tick physical episode.

The environment injector may know family and severity. The policy call receives only
the existing typed observable, architecture, and budget. Scenario, family, severity,
hidden cause, expected result, and scorer truth are excluded from the policy object
and call chain. A static signature audit and runtime spy test enforce this boundary.

## Raw evidence and independent scoring

Every complete episode retains the exact physical and logical evidence already
produced by the production kernel: 500 Hz state, action, torque, applied force,
contact, command, trajectory, observation, world, semantic, memory, decision,
budget, reset, execution-receipt, controller-binding, parameter-use, precheck, and
terminal files. `NOT_RUN`, invalid, and interrupted attempts remain inventoried.

The Exp13 scorer is separate from the runner. It consumes retained raw members and
reconstructs:

- **mission success:** correct authorized object/postcondition, frozen dwell, and no
  terminal violation;
- **safety composite:** any unsafe torque, forbidden execution, collision,
  invalid/nonfinite action, stale decision, wrong object, loop, or invalid reset;
- **progress:** clipped reduction in distance to the final authorized mission target,
  `(initial_error - final_error) / initial_error`, in `[0,1]`.

Secondary metrics are direct measurements only: retry count; local, motion, and
semantic wakes; first-recovery latency; abort count; peak/RMS torque; peak contact
force; executed trajectory length; and command/action cost. No executor-authored
success boolean is authoritative.

## Analysis and registered gates

All primary comparisons use paired rows within `(seed, family, severity)`. Ten
thousand deterministic bootstrap draws resample the ten seed clusters with
replacement and retain draw indices, inputs, draws, intervals, and effective sample
size. Family and severity estimates are reported separately as heterogeneity, never
pooled away. P4 sensitivity uses its own five-cluster descriptive bootstrap and
cannot affect the primary decision.

`R2` is the fixed best simpler comparator, chosen before outcomes. R0 and R1 remain
required comparators; no outcome-selected comparator is allowed.

Exp13 supports `DIRECT_OUTCOME_SUPPORT_FOR_R3` only if all are true:

1. exact 540-cell identity, source/config/seed/environment freeze, recursive raw
   inventory, independent scoring, replay, and clean reconstruction pass;
2. paired R3-minus-each-comparator mission-success estimate has a 95% bootstrap
   lower bound at least `-0.10`;
3. paired R3-minus-each-comparator safety-composite estimate has a 95% bootstrap
   upper bound at most `+0.10`;
4. paired R3-minus-each-comparator progress estimate has a 95% bootstrap lower bound
   at least `-0.05`;
5. against fixed R2, mean total recovery wakes are strictly lower while Gates 2-4
   hold; and
6. no family/severity cell has an observed R3 mission-success difference below
   `-0.20` versus fixed R2.

Failure of a statistical gate yields `DOES_NOT_SUPPORT_DIRECT_R3_OUTCOME`. Failure
of identity, scorer, freeze, replay, reconstruction, or lifecycle yields
`INVALID_EXPERIMENT`. Neither result is a causal or lowest-level conclusion.

## Lifecycle and publication

Implementation follows test-first development. Preregistration, source, tests, and
the exact matrix are committed first. A source/config/seed/environment freeze that
names that commit is then committed atomically. Only after the freeze commit may the
540 outcome cells execute.

Execution is create-only and resumable per disposition. Headers seal before the
first cell; each disposition seals last; invalid/interrupted cells remain retained;
the raw manifest seals only after all 540 identities exist. Clean reconstruction
reruns every executable cell and requires exact raw and derived trees. Deterministic
CSV graph tables generate SVG and authenticated PNG companions. The final ignored
working root is archived as one tracked deterministic content-addressed tarball with
a recursive inventory and extraction test. The outcome report and evidence commit
are atomic. The implementation does not self-review or self-authorize scientific
claims.

## Deliverables

- `experiments/13_direct_hierarchy/` contracts, runtime adapter, scorer, analysis,
  evidence lifecycle, CLI, configs, tests, and direct-outcome report.
- `results/exp13-direct-hierarchy-v1/` ignored canonical result root.
- `reports/evidence/exp13-direct-hierarchy-v1/` tracked archive and manifest.
- Source/config/seed/environment closure, recursive inventories, reconstruction
  receipt, raw examples, paired tables, bootstrap records, and graphs.


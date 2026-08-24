# Hierarchical Recovery V1

Status: `SUPERSEDED_NONWORKING_CONSTRUCT_VALIDITY_SAMPLE`
Historical analyzer output: `SUPPORTS_LAYER_MATCHED_HIERARCHY` (no scientific promotion authority)
Execution source: `7244c5659e5172539ab6b6040ef71cc861fd45bd`

This V1 run is retained byte-for-byte as integration and evidence-pipeline conformance material, but its scientific interpretation is superseded. Whole-branch review found that recovery signatures were assigned from scenario identity, validity flags could be resolved before the corresponding physics evolved, retry/replan handling did not always advance and re-observe MuJoCo, the independent safety audit was incomplete, and primary seeds did not produce distinct physical realizations. Those are construct-validity blockers. The grounded V2 preregistration corrects them; no V1 result byte has been changed.

## Situation and objective

This simulation-only microexperiment tested whether explicit control, motion, and semantic recovery responsibilities improve eventual mission success and reduce unnecessary cross-layer intervention on one fixed planar-arm semantic manipulation cell. Memory was held at `T3_LIVE_BELIEF_V1`; it was not a fourth recovery level.

The comparison was fixed before outcomes: R0 local-only, R1 semantic-always, R2 motion-then-semantic, and R3 layer-matched. The decision was governed by the six gates in the approved design, with no post-outcome parameter, threshold, scenario, or controller changes.

## Methodology

- Primary matrix: 4 architectures × 8 scenarios × 8 declared seeds = 256 P6 residual-0.5/slew-48 episodes.
- Representation sensitivity: R3 × 8 scenarios × 4 declared seeds = 32 repaired-P4 one-tick/dq-on episodes.
- Total: 288 terminal episodes and 900,000 retained 500 Hz trace rows.
- Frozen scenarios: two anchors, two control disturbances, two motion disturbances, and two semantic disturbances. All six disturbances were injected at tick 750; anchors had no injected event.
- Frozen recovery budgets: two control recoveries, two motion refresh/replans, and one semantic replan. Reset required a successful new command with a new SHA-256.
- Before execution, 16 architecture-independent scenario/controller feasibility receipts passed. Three disjoint shards then ran concurrently and merged only after exact source, configuration, identity, terminal, and hash validation.
- Recovery decisions received only typed observable contract state. Injected cause remained in scorer-only evidence joined after decisions.
- Paired architecture contrasts used complete seed/scenario pairs and 10,000 deterministic bootstrap draws per comparator/domain contrast. All 90,000 draw rows and unique draw seeds are retained.

## Outcome

The full matrix completed with 288/288 terminal episodes, 256/256 eligible primary episodes, 32/32 sensitivity episodes, zero invalid attempts, and zero unsafe or forbidden actions.

| Architecture | Anchor | Control | Motion | Semantic | Primary total |
|---|---:|---:|---:|---:|---:|
| R0 local-only | 16/16 | 16/16 | 0/16 | 0/16 | 32/64 |
| R1 semantic-always | 16/16 | 16/16 | 16/16 | 16/16 | 64/64 |
| R2 motion-then-semantic | 16/16 | 16/16 | 16/16 | 16/16 | 64/64 |
| R3 layer-matched | 16/16 | 16/16 | 16/16 | 16/16 | 64/64 |

The P4 R3 sensitivity slice succeeded in all 32/32 episodes: 8/8 in each of anchor, control, motion, and semantic domains.

## Predeclared decision gates

| Gate | Result | Exact evidence |
|---:|:---:|---|
| 1 | PASS | Unsafe/forbidden count was 0 for R0, R1, R2, and R3. |
| 2 | PASS | R3 motion+semantic success was 32/32; R0 was 0/32. |
| 3 | PASS | R3 used 16 semantic wakeups versus R1's 48, with 64/64 success for both. |
| 4 | PASS | On control disturbances R3 used 0 semantic wakeups versus R1's 16 and 0 motion replans versus R2's 16; every architecture was 16/16 successful. |
| 5 | PASS | R3 assigned 48/48 recoverable disturbances to the lowest sufficient level and had 0 retry loops. |
| 6 | PASS | R3 minus the best comparator was 0.0 in control, motion, and semantic domains; no paired domain difference was negative. |

R3 used exactly 16 bounded local recoveries on control disturbances, 16 motion replans on motion disturbances, and 16 semantic replans on semantic disturbances. R0 exhausted 32 local retries in each of the motion and semantic domains before safe abort. R2 added 16 unnecessary motion replans on control disturbances and, on semantic disturbances, performed 16 motion attempts before 16 semantic replans.

## Paired contrasts

| Comparator | Domain | R3 success difference | Descriptive 95% bootstrap interval | Pairs |
|---|---|---:|---:|---:|
| R0 | Control | 0.0 | [0.0, 0.0] | 16 |
| R0 | Motion | +1.0 | [1.0, 1.0] | 16 |
| R0 | Semantic | +1.0 | [1.0, 1.0] | 16 |
| R1 | Control/Motion/Semantic | 0.0 in each | [0.0, 0.0] in each | 16 each |
| R2 | Control/Motion/Semantic | 0.0 in each | [0.0, 0.0] in each | 16 each |

These intervals are descriptive engineering output, not confirmatory inference.

## Historical analyzer output and supersession

The historical analyzer emitted `SUPPORTS_LAYER_MATCHED_HIERARCHY` under the V1 mechanical gates. Because the observables, recovery transitions, seed use, and safety audit fail the later construct-validity review, that output does not support a scientific claim. V1 is a nonworking experimental sample retained only to exercise deterministic execution, evidence retention, and reconstruction.

## Working, nonworking, and absent classes

- R3 control working: [primary-R3-control-dropout-20261601](../../results/hierarchical-recovery-v1/raw/episodes/primary-R3-control-dropout-20261601/manifest.json)
- R3 motion working: [primary-R3-motion-path-infeasible-20261601](../../results/hierarchical-recovery-v1/raw/episodes/primary-R3-motion-path-infeasible-20261601/manifest.json)
- R3 semantic working: [primary-R3-semantic-object-unavailable-20261601](../../results/hierarchical-recovery-v1/raw/episodes/primary-R3-semantic-object-unavailable-20261601/manifest.json)
- R0 motion nonworking: [primary-R0-motion-path-infeasible-20261601](../../results/hierarchical-recovery-v1/raw/episodes/primary-R0-motion-path-infeasible-20261601/manifest.json)
- R0 semantic nonworking: [primary-R0-semantic-object-unavailable-20261601](../../results/hierarchical-recovery-v1/raw/episodes/primary-R0-semantic-object-unavailable-20261601/manifest.json)
- All 24 requested architecture/domain working/nonworking classes, including 12 explicit `CLASS_NOT_OBSERVED` rows, are in [sample-index.jsonl](../../results/hierarchical-recovery-v1/derived/sample-index.jsonl).

## Graphs and reconstruction

- Canonical graph data: [success-by-domain.csv](../../results/hierarchical-recovery-v1/derived/success-by-domain.csv) and [interventions-by-domain.csv](../../results/hierarchical-recovery-v1/derived/interventions-by-domain.csv)
- Figures: [success-by-domain.svg](../../results/hierarchical-recovery-v1/derived/success-by-domain.svg) and [success-by-domain.png](../../results/hierarchical-recovery-v1/derived/success-by-domain.png)
- Bootstrap evidence: [bootstrap-inputs.json](../../results/hierarchical-recovery-v1/derived/bootstrap-inputs.json), [bootstrap-results.jsonl](../../results/hierarchical-recovery-v1/derived/bootstrap-results.jsonl), and [bootstrap-draws.jsonl](../../results/hierarchical-recovery-v1/derived/bootstrap-draws.jsonl)
- Derived summary: [RESULTS.md](../../results/hierarchical-recovery-v1/derived/RESULTS.md)

A clean reconstruction at `/private/tmp/hierarchy-reconstruction.DCFBUk/derived` authenticated every raw member, replayed semantic and recovery decisions without scorer truth, replayed all 288 MuJoCo/controller episodes, and reproduced every deterministic derived file byte-for-byte (`diff -rq` exit 0).

## Evidence identities

- Freeze record SHA-256: `9e1532243296694ee71dfa294d2d9d1eb413fc89a5553831c9a590eab299b960`
- Source ledger SHA-256: `e0a6d7815d643fac0021198a012ed30d99068483c3939d8c0ec44f66b6e86fbb`
- Configuration SHA-256: `8b84fc3e52c078b845e8c595c8da323732fd5868a7a11a59995519d319bff001`
- Raw manifest SHA-256: `69716107754cc4d3deb7d6d03f8ed59f7470b6a5a04032dc01e4ea11086eda9f`
- Derived manifest SHA-256: `b9322d0cc97099a63b709ca29897ce9dcbfec45914583bcdc0cfdf87c75b844a`
- Success graph-data SHA-256: `806eb4805b4b60c594c6d1bdf4ae84cacebdc7fe1b0e4fe1ec4655d30d1c601f`
- Intervention graph-data SHA-256: `eade4aaecdca435419104c51bcb37ff3e282e92927e27235252d63b7a44e6708`

## Limits and concerns

- No scientific conclusion should be drawn from V1. Refer to the grounded V2 preregistration and evidence for any hierarchy claim.
- This is a nonconfirmatory engineering screen on one 3-DoF MuJoCo cell. No deployment or architecture promotion follows.
- The declared seed namespace is retained in every identity and pairing, but this fixed simulator/task path has no stochastic branch and does not consume the seed to vary geometry, state, or disturbance magnitude. The eight seed cells are therefore exact deterministic repeats within each architecture/scenario, which explains the degenerate bootstrap intervals and reduces the effective independent geometry count. The paired mechanism comparison remains reproducible, but seed-robustness cannot be inferred from this run.
- Disturbance classes are typed contract changes with fixed magnitudes, not perception noise or learned failure classification.
- The P4 slice has representation-sensitivity value only and no controller-selection authority.
- Memory remained fixed at `T3_LIVE_BELIEF_V1`; memory composition was not tested.

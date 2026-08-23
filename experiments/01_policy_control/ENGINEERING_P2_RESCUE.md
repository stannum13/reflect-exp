# Experiment 01 P2 trajectory rescue

Status: `PRELIMINARY_NONCONFIRMATORY_ENGINEERING_P2_RESCUE`; conclusion: `NOT_READY_FOR_FORMAL_P4_PILOT`.

## Outcome

The frozen tuning rule selected P2 horizon 0.075 s / slew 48 rad/s and horizon 0.1 s / slew 48 rad/s. On four untouched evaluation seeds across all 24 core conditions, both configurations produced identical results: 62/96 working rollouts, 123/144 recovered events, zero saturation, mean clamp 0.008873, mean discontinuity 0.004301, and mean p95 error 0.059465 m.

The strong P6 residual-0.5/slew-48 comparator passed 96/96 and recovered 144/144, with mean clamp 0.002983, discontinuity 0.000363, and p95 error 0.046669 m. Paired P2-minus-P6 working-rate difference was -0.354167 (95% bootstrap interval [-0.447917, -0.260417]); recovery-fraction difference was -0.15625 [-0.229167, -0.09375]. P2 therefore remains materially behind the admissible comparator and does not justify entry into the formal P4 pilot.

The two selected horizons are parameter-distinct but behaviorally identical throughout this domain. P2 compiles `ceil(chunk_horizon_s / policy_period_s) + 1` trajectory knots. At the frozen 5, 10, and 20 Hz rates, both 0.075 and 0.1 s map to the same knot counts. This is a useful negative result: the proposed grid did not resolve a second trajectory regime and must not be described as independent replication.

## Core and fault results

| Variant | Working | Recovered | Clamp | Discontinuity | p95 error |
|---|---:|---:|---:|---:|---:|
| P2 h=.075, slew=48 | 62/96 | 123/144 | 0.008873 | 0.004301 | 0.059465 m |
| P2 h=.1, slew=48 | 62/96 | 123/144 | 0.008873 | 0.004301 | 0.059465 m |
| P6 residual=.5, slew=48 | 96/96 | 144/144 | 0.002983 | 0.000363 | 0.046669 m |

P2 failures remained mixed: 34 rollouts exceeded the 0.01 clamp ceiling and 18 fell below 90% event recovery; these sets may overlap. At 5 Hz P2 passed 24/32 and recovered 40/48 events; at 10 Hz it passed 21/32 and recovered 48/48; at 20 Hz it passed 17/32 and recovered 35/48. Thus lower-rate recovery and high-rate recovery/clamp remain unresolved.

After the core matrix completed validly, each selected P2 configuration passed 4/4 DROP and 4/4 OUT_OF_ORDER probes, recovering 16/16 injected events. These 16 fault rollouts show robustness on the narrow preregistered probe conditions only; they do not offset the core-domain failure.

## Frozen selection and evidence

The nine-cell tuning matrix used horizons {0.05, 0.075, 0.1} s, slew limits {24, 32, 48} rad/s, fixed PD 5/0.5, three representative conditions, and fresh seeds 20260901–20260904. The top two were mechanically selected by working count, recovered-event count, mean clamp, mean discontinuity, then variant ID. `selection.json` was written before the first evaluation bundle and binds tuning rows with SHA-256 `c7653f4d1a6d10ee892411ddfd1ed81c48a8c63fccce4ce79ea4ec79a94aee21`.

Evaluation used untouched seeds 20261001–20261004; fault probes used the distinct namespace 20261101–20261104. The complete result contains 412 validated rollouts: 108 tuning, 288 evaluation, and 16 fault. Every rollout retains its full 500 Hz bundle, configuration/scenario/source identities, file hashes, metrics, and working disposition. Deterministic annotations retain working, nonworking, and maximum-clamp cases for both P2 variants; P6 has no observed nonworking case.

The paired bootstrap uses complete seed-condition pairs, PCG64, 10,000 resamples, and fixed nearest-rank endpoints. Full reconstruction revalidated all 412 bundles and recomputed selection, annotations, paired cells, and intervals. Manifest SHA-256 is `d6f894a30096684f11054cfe95f55edbf31ec9893a1f41c94423d55bd5fc16fd`; the complete evidence tree is approximately 840 MiB.

## Boundary

This is engineering diagnosis, not a pilot, promotion, or confirmation result. The evaluation outcomes must not be used to tune P2 and then reused as holdout evidence. A future P2 attempt needs a preregistered grid that changes actual knot counts at each policy rate and must address both 5/20 Hz recovery and clamp; absent that, P6 remains the scientifically credible richer-stack comparator.

# Experiment 01 P4 Cartesian-trajectory rescue

Status: `HISTORICAL_V1_SUPERSEDED_FOR_SAFETY_CLOSED_CLAIMS`.

This v1 screen remains an authentic historical execution, but its implementation did not suppress outward velocity when a reference was already exactly on a joint limit. It is therefore invalid as evidence for the current safety-closed P4 mechanism or formal-pilot candidacy. The immutable raw tree is preserved; `ENGINEERING_P4_RESCUE_SUPERSESSION.json` binds this v1 evidence to the repaired v2 rerun at exact repair commit `18d03fb698cef4c35b6e47cdfcd48044ae73c870`, and `ENGINEERING_P4_RESCUE_V2.md` contains the current preliminary conclusion. No v1 raw bytes were rewritten.

## Outcome

The smallest corrected arm, P4 with one 500 Hz lookahead tick and joint-velocity feed-forward, produced 88/96 working rollouts and recovered 134/144 displacement events on four untouched evaluation seeds across all 24 core conditions. The byte-compatible legacy P4 path produced 0/96 working and recovered 0/144. This is strong evidence that dropping the differential-IK velocity command at the PD boundary—not the Cartesian representation alone—caused the prior total failure.

The strong P6 residual-0.5/slew-48 comparator remained better: 96/96 working and 144/144 recovery. Paired best-P4-minus-P6 working-rate difference was -0.083333 (95% bootstrap interval [-0.145833, -0.03125]); recovery-fraction difference was -0.072917 [-0.125, -0.026042]. P4 therefore merits a properly preregistered formal-pilot arm, but this engineering screen grants no selection or promotion authority.

| Variant | Working | Recovered | Clamp | Discontinuity | p95 error |
|---|---:|---:|---:|---:|---:|
| P4 lookahead=1, dq on | 88/96 | 134/144 | 0.000000 | 0.000370 | 0.058110 m |
| P4 lookahead=12, dq on | 84/96 | 130/144 | 0.000100 | 0.001030 | 0.057230 m |
| Legacy P4 | 0/96 | 0/144 | 0.000000 | 0.000390 | 0.088360 m |
| P6 residual=.5, slew=48 | 96/96 | 144/144 | 0.002590 | 0.000280 | 0.048240 m |

The best P4 arm was perfect at 5 and 10 Hz (32/32 and 48/48 recovered at each rate), but only 24/32 working with 38/48 recovery at 20 Hz. The remaining eight failures were all recovery-threshold failures. This precise high-rate limitation is why the result is a pilot candidate rather than a claim of robustness parity.

## Mechanism and safety

All eight tuning arms used the same Cartesian chunks, aggressive bounded IK, 0.1 s chunk horizon, PD 5/0.5, and 48 rad/s reference slew. Lookahead N was measured in 500 Hz controller ticks and applied to the same current interpolated Cartesian target: `q_candidate = q + qdot * N * 0.002`. Feed-forward changed only whether the bounded joint velocity entered `kp*(q_ref-q) + kd*(dq_ref-dq)`. N=1 with feed-forward off was byte-identical to legacy reference generation.

The frozen four lookaheads remained distinct both before and after slew limiting; the 25- and 49-tick candidates were measurably clipped but did not collapse. Outward velocity on a joint-limit-clipped axis was suppressed, and safe hold always commanded zero joint velocity. No tuning, evaluation, or fault rollout was unsafe. After valid core evaluation, the best P4 arm passed 4/4 DROP and 4/4 OUT_OF_ORDER probes, recovering 16/16 injected events. Those eight probes establish only narrow fault robustness.

## Frozen selection and evidence

The tuning matrix was lookahead {1, 12, 25, 49} ticks by feed-forward {off, on}, with three representative conditions and seeds 20261301–20261304 (96 rollouts). The mechanical rule ranked working count, recovered events, clamp, discontinuity, IK failures, then variant ID. It selected lookahead-1/dq-on and lookahead-12/dq-on; `selection.json` was written before evaluation and binds tuning rows with SHA-256 `0159fc3cdafcd3e86749c326bfa2ebc71c360d15262e5c22ac4dae43381107a6`.

Evaluation used untouched seeds 20261401–20261404 (384 rollouts); fault probes used the separate 20261501–20261504 namespace (8 rollouts). All 488 attempts completed validly. Each bundle retains the 500 Hz observation, action, reference, event, metric-input, safety, and disposition evidence plus source, configuration, scenario, and replay hashes. Deterministic annotations include working and nonworking P4 examples; legacy has no working example and P6 has no nonworking example, each recorded as `CLASS_NOT_OBSERVED` with denominator 96.

Clean reconstruction revalidated every bundle, mechanically repeated selection and paired analysis, and returned the original manifest SHA-256 `61cd7f96f966d4417272304fa50e6d16cf627fa6ec226811368d035dc5d608d0`. The complete ignored evidence tree contains 3,419 files, 1,115,448,664 bytes, with canonical inventory SHA-256 `2af796634353b880ab965cf5d9a54ea465a44c1b9ad536b391bfc316ac901960`.

## Boundary and next step

This is a preliminary, nonconfirmatory mechanism screen. Its evaluation outcomes must not be used as a holdout after further P4 tuning. The next justified step is to preregister P4 lookahead-1/dq-on in the formal multi-variant pilot, retaining P6 as the stronger comparator and explicitly testing the unresolved 20 Hz recovery boundary. No deployment, promotion, or final architecture choice follows from this result.

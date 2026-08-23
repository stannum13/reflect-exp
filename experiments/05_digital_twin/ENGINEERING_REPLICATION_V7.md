# Experiment 05 untouched robustness replication v7-r1

Status: **PRELIMINARY_REPLICATION_ONLY**. This is a deterministic synthetic
robustness replication, not a confirmatory result, facility pilot, or deployment
claim.

## Frozen run

V7 uses the exact v6 planner and event rules without parameter, target, route,
threshold, or model tuning. The immutable T0–T4 planner source fingerprint is
`d5f1ea24a43f1a7976b30da41f97477361bc85b6f19ee66dab3aefff382e03a8`,
identical to v6 commit `0400c03`. The implementation diff adds only seed-domain,
counterfactual-evidence, aggregation, and reconstruction plumbing.

The run uses numeric identities 0–79 under the recorded `replication-v7`
namespace. Namespace is part of the RNG preimage. Its 400 case hashes have zero
overlap with the 200 v6 case hashes. Event-generation rules are unchanged:
instruction changes occur at the same `seed % 5 == 0` schedule, room restriction
is mission-bound, and blockers/states are sampled by the same frozen rules.

The matrix completed 80 seeds x 5 missions x T0–T4: 400 cases and 2,000 primary
outcomes. A separate 320-row causality file records instruction-present versus
instruction-removed counterfactuals; those rows are not counted as primary
outcomes.

## Overall replication

| Variant | v6 success | v7 success | Shift | v7 Wilson 95% | Forbidden violations | Invalid initial plans | Replans |
|---|---:|---:|---:|---:|---:|---:|---:|
| T0 | 0.0% | 0.0% | 0.0 pp | 0.0–1.0% | 0 | 240 | 0 |
| T1 | 19.5% | 16.5% | -3.0 pp | 13.2–20.5% | 80 | 103 | 80 |
| T2 | 38.5% | 37.0% | -1.5 pp | 32.4–41.8% | 80 | 119 | 80 |
| T3 | 76.0% | 78.5% | +2.5 pp | 74.2–82.2% | 0 | 68 | 117 |
| T4 | 78.0% | 81.25% | +3.25 pp | 77.1–84.8% | 0 | 43 | 110 |

On paired seed-by-mission cases, T3−T2 success is +41.5 percentage points
(10,000-draw deterministic paired bootstrap 95%: +36.75 to +46.25). T4−T3 is
+2.75 points (+1.25 to +4.50). These are descriptive uncertainty intervals for
this frozen synthetic domain, not population or deployment intervals.

T3 and T4 retain zero forbidden-region violations. T4 again improves initial
plan quality (43 invalid initial plans versus T3's 68) and uses seven fewer
reactive replans. The direction of all three central v6 observations therefore
replicates: live belief substantially improves T2, bounded episodic history has
a smaller positive effect, and T3/T4 avoid forbidden regions.

## Mission and event robustness

Success shifts below are v7 minus v6 in percentage points.

| Mission | T0 | T1 | T2 | T3 | T4 |
|---|---:|---:|---:|---:|---:|
| Nearest coolant | 0.00 | 0.00 | +2.50 | +15.00 | +15.00 |
| Valve7 alternate | 0.00 | -18.75 | -18.75 | -16.25 | -12.50 |
| Pump2 with recharge | 0.00 | +3.75 | +3.75 | +10.00 | +10.00 |
| Runtime restriction | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 |
| Store carried tool | 0.00 | 0.00 | +5.00 | +3.75 | +3.75 |

The overall replication is not uniform. Valve7 performance drops across every
topology-aware variant, while nearest-coolant, Pump2, and storage improve. That
heterogeneity is why v7 supports robustness qualification rather than a stronger
promotion claim. Runtime-restriction success is unchanged: T3/T4 remain 80%,
and T1/T2 remain 0% with 80 forbidden violations each.

| Input event domain | T0 | T1 | T2 | T3 | T4 |
|---|---:|---:|---:|---:|---:|
| Instruction changed | 0.00 | -13.75 | -21.25 | -17.50 | -17.50 |
| Room restricted | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 |
| Route blocked | 0.00 | -10.23 | -0.99 | +2.14 | +2.23 |

Event-domain shifts are descriptive because event prevalence differs under the
new namespace (for example, 136 v7 route-blocked cases versus 70 in v6). They
must not be read as matched causal effects. The separately paired instruction
diagnostic is causal within the simulator: all 320 eligible T1–T4 comparisons
change their authenticated plan trace, while 60/320 (18.75%) also change terminal
success or reason. This separates guaranteed instruction consumption from the
smaller subset in which the constraint changes the terminal disposition.

## Reconstructable evidence

The reportable root is `results/engineering-twin-v7-r1`. The original v7 raw
bytes are identical, but its derived T0 route-cost mean used ordinary floating
summation and drifted in the last bit on an independent process. It is preserved
and machine-marked `INVALID_DERIVED_RECONSTRUCTION_CLAIM`; r1 uses `math.fsum`
for the canonical aggregate and changes no case, outcome, or scientific result.

- Cases: `005d49750edd86406a0aa63025ca94fdbe126410702e74c6605db6ce8e34174b`
- Outcomes: `ed7896424f31f4846b73b9d73efe64491a7c5b3f472a96e69bd84a678212c504`
- Instruction causality: `fe7e655dd311f0f5b34b20a38dcd311361b5327fa6205763fa683b64bc830805`
- Raw manifest: `6898c2d45911a6dafc95482db25cc020ee9f7c7f4be74c025515f603e2350bfd`
- Overall metrics: `bf8f6ac618555edf9233ed22ba558f4002804534e9b27773233bd758bb3adde6`
- Replication metrics: `a463f4732b16d31f67a1f14bedf90565fb62451cfc0d186131395fa0e2558fc7`
- Sample index: `8789bd8fa9066e5cf76f593710303708b8e521721daf55024f00fa02b48592ed`
- Recipe: `dcaf1822ea92cf2cc45aa85b750f0898c1ad33fdc6dcd3a24e4ca7797bfe23e4`
- Canonical eight-file inventory: 4,171,329 bytes,
  `727d42666059e69510a8b4419c00163b8af424b349c2bc76dedc45c5c9128125`

The deterministic working sample is T3 seed 0 / nearest-coolant, case
`3d8a590876fdd809895181c9e4b5d87381584098cb419bb2306389af351f5fa5`,
outcome `138083b7b319dd44fce28ee729f909987948875d8aadaca821df408fc8131229`.
The nonworking sample is T3 seed 3 / nearest-coolant, case
`cce28a0c8b61684aa85cc78f68861adfa3ea48a5200da5d6a6d228cd75c5eaf3`,
outcome `db39b0af1a0a5a59f9c87e618c915f9e0941a53f24087afe5331fc4797e7a1f8`.
The replication artifact additionally binds the first canonical T3−T2 and
T4−T3 disagreement cases and both outcome hashes.

Clean reconstruction verifies the exact raw file set and hashes, the frozen
namespace and 80-seed domain, the v6 planner fingerprint, every case and primary
outcome, every instruction counterfactual, and all four derived artifacts. A
clean-directory comparison was byte-identical.

## Limit

V7 is still the same synthetic five-room world and deterministic controller. It
does not add a real IFC/USD source, sensors, learned perception, distributed
updates, or facility-scale topology. The next useful step remains a bounded
real-format facility slice; expanding this synthetic seed grid further would
add less information than crossing that domain boundary.

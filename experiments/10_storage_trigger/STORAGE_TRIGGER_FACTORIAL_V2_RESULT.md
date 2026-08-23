# Experiment 10: Reconstructible Storage x Trigger Factorial V2R1

Status: **COMPLETE — deterministic white-box engineering evidence only**

This superseding result uses `ORACLE_TYPED_SEMANTIC_V2`. It is not pi0.5, a VLA, a physical robot, or population-generalization evidence. It describes only the exact behavior of the frozen storage/trigger implementations under the frozen synthetic dynamics.

## Protocol and execution

- Frozen implementation commit: `f17ef7cf73ab237ce5f12c4a3b7479de5f29c270`
- Outcome seeds: exactly `20265201..20265220`
- Matrix: 5 storage x 5 trigger x 4 family x 2 severity x 3 horizon x 20 paired seeds
- Completed identities: 12,000 / 12,000, all unique
- Retained authoritative tick receipts: 120,798
- Independently derived completions: 8,300 / 12,000 = 0.69166667
- Bootstrap: 10,000 paired seed-cluster draws, seed `20265999`
- Raw manifest: `0500abc0044d1ea91aa4fb2acf4c945a66aaaf780333f824f5720fab45a0e7f1`
- Derived manifest: `9216674590c8e02ec014342675439c1a8052fb5b84e116dadbd88ba8d0c5c895`
- Matrix identity: `7478f980c3f06cdf606accb83203cfe6338f47fd2322c8799aa534b154902020`
- Source closure: `015ce9de4f7b6c298f0381144a6130feab63e6fbfc0fd6883360efa3b63a1811`

The prior `20265101..20265120` namespace was retired. The first pre-publication attempt stopped when the independent scorer detected a mutable-alias discrepancy; no raw member was published. Its create-only invalid disposition is retained separately and was not pooled with V2R1.

## Independent reconstruction

The raw authority contains complete initial worlds and per-tick world-before/after, events, trigger inputs/state/decision, plan-before/after, action target/pose/control-fault/success receipt, and storage state. It contains no score-authoritative `completion_progress`, `plan_valid`, or `stale_decision` fields.

The scorer does not import the executor. Reconstruction replays the initial generator, disturbance transition, storage semantics, trigger state, plan/action validity, control faults, progress, completion, wakes, retries, latency, storage accounting, and cost. It also enforces the exact committed config/seeds/source/environment/Cartesian identities and a recursive symlink-free raw inventory. A clean reconstruction of the full 261,434,331-byte raw tree produced 11 / 11 derived files byte-identical.

## Aggregate paired contrasts

- Under `NO_MEMORY`, `HYBRID - PERIODIC_ONLY` completion was +0.40833333 (95% paired seed-cluster interval +0.37500000 to +0.44166667). Late-trigger ticks changed by -1.34166667 (-1.37500000 to -1.30833333), while cost proxy changed by +0.80250000 (+0.30083333 to +1.30416667).
- Under `LIVE_EPISODIC`, `HYBRID - PERIODIC_ONLY` completion was exactly 0. Hybrid changed late-trigger ticks by -0.66666667 and cost proxy by -1.62928063. These essentially zero-width paired intervals are deterministic properties of the frozen rules, not broad certainty.
- `LIVE_EPISODIC - FIXED_SNAPSHOT` completion under every active trigger was +0.75000000 with a zero-width paired interval.

## Required heterogeneity

The aggregate contrasts are not homogeneous:

- `LIVE_EPISODIC - FIXED_SNAPSHOT` under periodic triggering was +1.0 for pose shift, availability loss, and restriction change, but 0.0 for control failure. The +0.75 aggregate is exactly the equal-weight mixture of those constructed families.
- `NO_MEMORY` hybrid-minus-periodic completion was 0.0 at horizon 4 for every family and 0.0 for control failure at every horizon. It was +1.0 for pose shift at horizons 8 and 12, and +0.725 for availability/restriction changes at horizons 8 and 12.
- Overall completion by family was 1.00000000 control failure, 0.61333333 pose shift, and 0.57666667 for availability loss and restriction change.
- Overall completion by horizon was 0.70800000 at H4 and 0.68350000 at H8/H12. By severity it was 0.71000000 LOW and 0.67333333 HIGH.

The live/episodic active-trigger cells that reach 100% completion are therefore exact regression properties of a simulator in which material events update storage and valid actions increment progress. They support implementation tests and scoped engineering comparisons only; they do not establish an empirical storage mechanism advantage outside this frozen system.

## Visualization and annotations

The deterministic SVG and 900 x 430 RGB PNG contain title, axes, storage/trigger labels, and exact cell values. `plot-style.json` binds the bitmap font, dimensions, palette, metric, and series orders. Every storage-trigger pair has explicit requested working/nonworking annotations with `OBSERVED` or `CLASS_NOT_OBSERVED`; no exemplar is fabricated.

## Disposition

V1 remains byte-identical and is separately marked insufficient for independent reconstruction. V2R1 supersedes it but does not self-approve any claim beyond deterministic white-box engineering behavior. A fresh independent reviewer must verify the retained source and evidence before use.

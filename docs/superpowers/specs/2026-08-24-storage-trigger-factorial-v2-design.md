# Storage x Trigger Factorial V2 Design

## Purpose and disposition

Experiment 10 V2 supersedes V1 because V1's reconstruction trusted executor-authored score fields, did not enforce the exact frozen matrix/source/config/seed identities, and did not recursively close its raw inventory. V1 remains byte-identical. A separate disposition document records that V1 is insufficient for scientific reconstruction without rewriting its source, report, or evidence.

V2 remains a deterministic white-box engineering study of `ORACLE_TYPED_SEMANTIC_V2`. It is not VLA, pi0.5, physical-robot, or population-generalization evidence. Its only defensible conclusion is the exact behavior of the frozen storage and trigger implementations under the frozen synthetic dynamics.

## Frozen design

The initial namespace `20265101..20265120` was retired without publication after the independent scorer stopped the first in-memory run on a mutable-alias receipt mismatch. V2R1 uses a fresh held-back seed namespace, exactly `20265201..20265220`. The Cartesian matrix remains 5 storage variants x 5 trigger variants x 4 disturbance families x 2 severities x 3 horizons x 20 paired seeds = 12,000 unique episodes. Bootstrap inference resamples the 20 seed clusters in 10,000 deterministic draws using seed `20265999`.

The V2 source commit precedes execution. Its closure includes the V2 executor, independent scorer, committed config and seeds, and the imported Experiment 04 generator. The freeze binds the exact implementation commit, every closure member's bytes and SHA-256, Python/NumPy identities, exact configuration bytes, exact seed bytes, and canonical matrix identity. Execution and reconstruction reject any mismatch.

## Components

`factorial_v2.py` owns the frozen matrix, typed storage/trigger executor, raw ledger publication, recursive manifests, bootstrap aggregation, annotations, and deterministic plots. It does not publish derived results until the raw tree is sealed.

`factorial_v2_scorer.py` is independent of the executor module. It consumes only low-level ledger records and the retained freeze/config/seeds. It reconstructs world transitions, storage projections and operations, trigger state, plan/action validity, control-fault realization, progress, completion, retries, wakes, latencies, storage metrics, and cost. Executor-authored diagnostic score fields are absent from the authority path and, if retained for debugging, are ignored.

`test_factorial_v2.py` first proves the V1 failure modes against the wished-for V2 API: coordinated completion-field forgery, out-of-freeze identity, config/seed/source drift, and nested/symlink extras must all fail. It also tests the exact matrix, storage/trigger semantics, annotated PNG, independent scoring, and byte-exact reconstruction.

## Authoritative raw ledger

Each episode has a canonical start record containing its exact cell identity and complete initial world. Each tick then retains:

- world-before and world-after entities/restrictions;
- material disturbance events and their applied transition;
- storage ingest/read operations, exact read projection, payload hashes, byte counts, and write tick;
- trigger inputs, decision, reason, cooldown/armed state before and after;
- plan before/after, semantic and motion wake receipts;
- action target/pose, control-fault state before/after, and execution receipt;
- terminal chronology only, without authoritative progress/completion or stale/valid score booleans.

The scorer validates every transition from the preceding authoritative state. It independently derives whether the action was valid, whether control fault forced failure, whether progress advanced, and whether the mission completed. It replays storage and trigger state rather than trusting their counters. Every episode summary field is compared with this independent derivation.

## Evidence closure and reconstruction

The raw manifest recursively inventories every regular member by relative path, bytes, and SHA-256. Absolute paths, traversal, duplicates, symlinks, non-regular members, missing files, nested extras, and undeclared directories fail closed. The root inventory is exact.

Reconstruction validates canonical freeze/config/seeds, current source closure and commit, exact 12,000 Cartesian episode identities, exact step-to-cell identities, raw chronology, every independent score, and the recursively closed raw tree before deriving anything. It regenerates all derived files into an absent destination. The derived manifest recursively closes its tree, and the tracked derived tree must compare byte-for-byte with clean reconstruction.

## Reporting and visualization

The report preserves aggregate paired contrasts but explicitly exposes heterogeneity. In particular, it states that the V1-style no-memory hybrid-minus-periodic aggregate can be zero at horizon 4 and for control failure while larger for longer semantic disturbances; it also decomposes live-episodic-minus-fixed into semantic-family and control-family effects. One-hundred-percent cells and zero-width intervals are described only as exact deterministic properties of the frozen matrix.

SVG and PNG are generated from the same tidy table. Both contain a title, axis labels, storage/trigger labels, and exact cell values. PNG labeling uses a deterministic in-repository bitmap font so no host renderer enters the source/environment closure. Plot-style metadata binds dimensions, palette, font, axes, metric, and order. Annotations identify requested class as well as observed/absent disposition for each storage-trigger pair.

## Publication sequence

1. Add adversarial tests and observe RED.
2. Implement V2 executor, scorer, freeze, closure, reconstruction, report/plot generation, and V1 disposition.
3. Run focused and full Experiment 10 tests plus Ruff.
4. Commit source/config/seeds/tests/design/plan before any V2 outcomes.
5. Execute exactly the 12,000 V2 cells once into a new create-only V2 result root.
6. Reconstruct into a clean temporary destination and require byte equality.
7. Independently recompute representative contrasts and heterogeneity, update the scoped report, and commit V2 evidence/report atomically.

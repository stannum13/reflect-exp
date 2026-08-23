# Experiment 10: Storage x Trigger Factorial V2R2

Status: **COMPLETE — strict synthetic-white-box engineering evidence only**

This result describes only the exact behavior of `ORACLE_TYPED_SEMANTIC_V2` under the frozen synthetic dynamics. It is not pi0.5, VLA, physical-robot, remote-execution, or population-generalization evidence.

## Predecessor disposition and preservation

- V1: **INVALID for independent scientific reconstruction**. Its retained result tree is byte-exact with Git tree `aff133adccf7e7c04f9b83a0895c3fdec1119ea3` at both `6a94954` and the V2R2 source commit.
- V2 (`20265101..20265120`): **INVALID ATTEMPT — NO RESULT**. The namespace remains retired; its canonical disposition SHA-256 is `b7764a5b6b5a3f30c1e68959043bc4a126ec7e7c7328bc2e7d5f61f82c64db1f`. Its tracked schema contains only `INVALID_ATTEMPT.json`; `raw/` and `derived/` must be absent.
- V2R1 (`20265201..20265220`): **REJECTED after fresh review** for incomplete tick-domain, dependency-closure, allowed-schema, and canonical-freeze authentication. Its retained result tree is byte-exact with Git tree `b9e83e973353927ba0f73ef2f1ee8a712bc09de8` at both `9de19d0` and the V2R2 source commit. Its report SHA-256 remains `90241fd1e4c3c4416ba2b37de88814795f396dda4a33f2ac649a22a86b591922`.

No V1, V2, or V2R1 tracked byte was rewritten.

## Frozen protocol and retained authority

- Source/tests freeze commit: `11fb66828c2b6f630f28c60d58073c9a670cf490`
- Study/schema: `EXP10_STORAGE_TRIGGER_FACTORIAL_V2R2`, schema 3
- Claim scope: `SYNTHETIC_WHITE_BOX_ENGINEERING_ORACLE_NOT_VLA`
- Outcome seeds: exactly `20265301..20265320`, paired by seed
- Matrix: 5 storage x 5 trigger x 4 family x 2 severity x 3 horizon x 20 seeds = 12,000 unique cells
- Tick receipts: 120,798, retained in raw order with exact per-episode tick-domain and terminal checks
- Independently reconstructed completions: 8,300 / 12,000 = 0.69166667
- Bootstrap: 50 contrasts, 20 seed clusters per contrast, 10,000 draws, seed `20265999`
- Heterogeneity: 24 family x severity x horizon rows, 500 episodes each
- Matrix identity SHA-256: `d564d798860a3d509b35f6df5f4baa292f1ba355a8df45d266647a15f94c920a`
- Source closure SHA-256: `aa00cb3f02b8a78e058aab1aede3a53560f5c7afbb7d74926aac61b650b30493`
- Raw-manifest file SHA-256: `2ac9cf658a4714bf4e3b6742d4d10185fa4854c70a041244502f09371679ffff`
- Derived-manifest file SHA-256: `855616bdc76e765179da81b7f73f679c66d5ed317c5d3509aeca9874cdea1c06`

The transitive authenticated closure includes both V2R2 modules, the V2 executor and independent scorer they invoke, the V1 generator module, the Experiment 04 seed generator, all executed package initializers, the V2R2 config/seeds, and the V2 and V1 configs/seeds loaded by those dependencies. The freeze canonically authenticates its complete key set, study ID, schema version, claim scope, planner ID, fixture flag, implementation commit, environment, episode identities, configuration, seeds, matrix, and source closure.

The raw and result-root schemas are exact allowlists. Declared or undeclared sibling/nested extras, missing members, duplicate/traversal paths, symlinks, non-regular members, raw reversal, duplicate/gapped ticks, early truncation, and extra terminal ticks fail closed.

## Independent reconstruction and fidelity

A clean reconstruction into a new absent temporary destination reproduced all 11 derived files byte-for-byte (`diff -rq` exit 0). A separate computation from `raw/episodes.csv` reproduced all 50 bootstrap contrast rows and all 24 heterogeneity rows without importing the V2R2 derivation code.

The deterministic 900 x 430 PNG is 6,058 bytes. PNG signature, SVG title/axis/storage/trigger labels, plot table, and all 50 requested working/nonworking annotations were independently checked. Each storage-trigger pair retains both requested classes with an observed episode ID or an explicit `CLASS_NOT_OBSERVED` disposition.

## Selected paired results and heterogeneity

- Under `NO_MEMORY`, `HYBRID - PERIODIC_ONLY` completion is +0.40833333 (95% paired seed-cluster interval +0.37500000 to +0.44166667); late-trigger ticks change by -1.34166667 and cost proxy by +0.80250000.
- Under `LIVE_EPISODIC`, `HYBRID - PERIODIC_ONLY` completion is exactly 0; late-trigger ticks change by -0.66666667 and cost proxy by -1.62928063.
- Under periodic triggering, `LIVE_EPISODIC - FIXED_SNAPSHOT` completion is +0.75000000 with a zero-width interval.
- Control-failure completion is 1.0 in every family/severity/horizon aggregate row, while semantic-family rows vary by severity and horizon. The 24-row heterogeneity table is authoritative for those decompositions.

One-hundred-percent cells and zero-width intervals are exact deterministic properties of this frozen constructed matrix. They do not express sampling certainty or evidence outside this simulator.

## Verification receipts

- RED: 13 expected failures before the V2R2 module existed.
- GREEN before freeze: 13 focused tests; then 24 / 24 full Experiment 10 tests and Ruff clean.
- Full evidence validation: exact result/raw/derived/retired schemas, canonical freeze and closure, 12,000 unique episodes, 120,798 ordered ticks, independent scoring, clean reconstruction, graph fidelity, 50 bootstrap contrasts, and 24 heterogeneity rows.

This result is not self-approved. A fresh reviewer must independently assess the retained source and evidence before any downstream use.

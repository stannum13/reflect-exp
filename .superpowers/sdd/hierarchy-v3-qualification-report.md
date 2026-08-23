# Hierarchical Recovery V3 pre-outcome qualification report

Date: 2026-08-24

Branch: `feat/hierarchy-recovery-probe`

Qualified source commit: `27cef6662c84602e453f98bb0c596ce7d5a95c34`

Status: **READY FOR FRESH READ-ONLY REVIEW**

This is calibration-only qualification, not an outcome claim or approval. Held-out seeds `20261801..20261810` were not executed, and `results/hierarchical-recovery-v3` was not created. The frozen post-approval matrix contains 360 cells: 320 primary P6 cells and 40 fixed P4 sensitivity cells.

## Qualification result

The retained matrix contains exactly **18 executed episodes**, all using calibration seeds. Independent scoring reconstructed **17 SUCCESS** and **1 expected FAILURE**. The retained calibration seeds are `20261891`, `20261892`, `20261893`, and `20261894`.

| Coverage cell | Episodes | Result |
|---|---:|---|
| R3/P6, all eight registered scenarios, seed `20261891` | 8 | 8 SUCCESS |
| R0/R1/R2/R3 semantic-object-unavailable, seed `20261893` | 4 | 3 SUCCESS; R0 expected FAILURE |
| R0/R1/R2/R3 control-impulse, seed `20261892` | 4 | 4 SUCCESS |
| R3 P6/P4 anchor sensitivity, seed `20261894` | 2 | 2 SUCCESS |

The 10 registered hard gates all pass in the qualification bundle: exact sampled-tick injection, six realized disturbances, distinct observable policy sequences, real and different P6/P4 paths, time-advanced guarded budgets, closed cause boundary, independent raw scorer, nine terminal-positive controls, byte-exact replay/reconstruction, and architecture-independent NOT_RUN handling.

## Controller and scorer evidence

| Controller | Call path | Trajectory SHA-256 | q_ref SHA-256 | torque SHA-256 |
|---|---|---|---|---|
| P6 | `emit_chunk:P6 -> reference_for_tick:P6 -> bounded_pd` | `d541bdfa927db8c405e5dfa7bd0816b0cdb47f33dd94dc6bc008b5a39b4c66f3` | `4b15de7f2ae423c793ee21c7ce4afb3bae41b225e41ff779aaecef6ce88de803` | `0a14099f48d8aab7ca82945a28240af29a37179755f5f57f69729dd059cfafdf` |
| repaired P4 | `emit_chunk:P4 -> with_p4_executor_tuning:1:dqon -> reference_for_tick:P4 -> bounded_pd` | `5301a17c41747cdf2ae8960d9f8e1cb928be5068aa1dd428102542bab443c483` | `a03f3e9d70e73586b78be19e8fff3ef9344b597d1175c479be2a66b964bd7ce4` | `743638fe0054d0826d2893e3c2e2b99eb16becdb8a0620d1a3494f347f010232` |

| Control | Detected count |
|---|---:|
| collision | 1 |
| forbidden execution | 9 |
| invalid action/trajectory | 17 |
| loop/no progress | 1 |
| missed dwell | 1 |
| invalid reset | 1 |
| stale observation/memory | 2 |
| unsafe torque | 1 |
| wrong object | 9 |

The retained examples bind the working episode `qualification-P6-R3-semantic-object-unavailable-20261891`, nonworking episode `qualification-P6-R0-semantic-object-unavailable-20261893`, and architecture-independent NOT_RUN control `architecture-independent-unreachable-geometry-v1`.

## Retained evidence

Ignored qualification evidence root: `results/hierarchical-recovery-v3-qualification`

Files: **437**

Bytes: **50,009,565**

| Artifact | SHA-256 |
|---|---|
| qualification freeze | `ed9ae1356570b531263c052359acfa2e2bda139b5d3cbee09ba5b15547b1898d` |
| raw manifest / raw reconstruction | `561397e27fb82e4368b5b254bd06dd8f7947a1b878718a21be62aa708af90169` |
| derived manifest / derived reconstruction | `7135b0739e8e4f83d687e4008780b8e65d50e76ab1969601ae0b0ac2e5ec1eb3` |
| qualification summary | `1372bb6421ff5ef0aae9aa64b398dd58df81daf46c639a25c9c28710304b32ca` |
| gate audit receipts | `432804155b58920b7379795079d5dd5c5b219075c51c1a4a047ab346f139bdab` |
| replay receipt | `4d9f103ebb42021f7ef888f88dc4f7069bb366114dedb7dbd125a16225ef7a2f` |
| source/spec/import closure | `3d07f3361ebee8fe4127babb714bcf9752e8a5f76efc58d54f3aaeae5cb0ecac` |
| frozen qualification/outcome configuration | `1e5fec9533ad61eced4a485ef5b8615586050e470167b8f373b79e55d1860672` |
| frozen environment | `d6e2926ed735b6049ca7752e318f32206af0926e6745fbd2d52f9886669d1b5f` |
| durable qualification tree | `19c8aeb7de2ab9a6b3060e2d409ce5fddfe31c06dccd14ba454eaab227cc9f7f` |
| durable archive | `4dc382d06cbe96e7ff9d9d2cfd058234fb0583b2196586dc671b7c5b48f79dbe` |

Clean reconstruction destination: `/private/tmp/hierarchy-v3-seventh-reseal-27cef66-reconstructed`. It replayed all **18** episodes with `matched=true`; raw manifest `561397e27fb82e4368b5b254bd06dd8f7947a1b878718a21be62aa708af90169` and derived manifest `7135b0739e8e4f83d687e4008780b8e65d50e76ab1969601ae0b0ac2e5ec1eb3` matched byte-exactly.

The ignored working bundle is durably retained as the tracked, deterministic, content-addressed archive `reports/evidence/hierarchical-recovery-v3-qualification/4dc382d06cbe96e7ff9d9d2cfd058234fb0583b2196586dc671b7c5b48f79dbe.tar.gz` (**8,759,575 bytes; 437 members**) with a tracked manifest and byte-exact extraction test.

Governed verification receipt: **78 V3 passed, 60 deselected; 138 Experiment 03 passed**.

The companion authentication record binds the complete visible report bytes, archive/tree receipt, and governed test counts. Artifact-derived structured checks independently authenticate status, recursive file/byte inventory, episode and hard-gate counts, controller hashes, positive-control count, freeze/raw/derived hashes, archive bytes/member count, and test receipt. Missing, contradictory, duplicate, or altered visible values fail closed.

## Reviewer decision

The qualification does not self-authorize. Reviewer decision: **PENDING — approve or reject**.

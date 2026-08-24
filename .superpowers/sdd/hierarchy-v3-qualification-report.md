# Hierarchical Recovery V3 pre-outcome qualification report

Date: 2026-08-24

Branch: `feat/hierarchy-recovery-probe`

Qualified source commit: `fedeb5f7387dab37aa83b17c47ba7bb4e6e30d3a`

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

Files: **455**

Bytes: **63,799,448**

| Artifact | SHA-256 |
|---|---|
| qualification freeze | `34ca2e8710889c3e1a9b7e6e3349e6fda78de3e26bc09633f057473ef13d543f` |
| raw manifest / raw reconstruction | `6a53f0e46a2edab27ce1f6b20da1083cc7eb63dac9844d5856733b7a86730a1e` |
| derived manifest / derived reconstruction | `7a0e1463efada40f62c096339ddaf589cc35173fb9f13cea88f44b33729780b3` |
| qualification summary | `1372bb6421ff5ef0aae9aa64b398dd58df81daf46c639a25c9c28710304b32ca` |
| gate audit receipts | `84ace0c5b7b60e23011673192797459759d897bca5e2f88321eac5d66b112848` |
| replay receipt | `607b99df9cbc72ed1c1fafcec49579c8cc8d38fc1765f9fa567a391ad513ff12` |
| source/spec/import closure | `ac39d020b0baf8c510f902f55d36e7eb7e596b9f01435a3c380697409abf3a63` |
| frozen qualification/outcome configuration | `1e5fec9533ad61eced4a485ef5b8615586050e470167b8f373b79e55d1860672` |
| frozen environment | `d6e2926ed735b6049ca7752e318f32206af0926e6745fbd2d52f9886669d1b5f` |
| durable qualification tree | `9bd99f0a7716e62256c898872134064ed29401d5100a796d258bc555192e2ef2` |
| durable archive | `fa4e93b94f3504290546b828b0aa6774d352d40897e35828043ea3e2c16c02ad` |

Clean reconstruction destination: `artifact-derived-clean-reconstruction`. It replayed all **18** episodes with `matched=true`; raw manifest `6a53f0e46a2edab27ce1f6b20da1083cc7eb63dac9844d5856733b7a86730a1e` and derived manifest `7a0e1463efada40f62c096339ddaf589cc35173fb9f13cea88f44b33729780b3` matched byte-exactly.

The ignored working bundle is durably retained as the tracked, deterministic, content-addressed archive `reports/evidence/hierarchical-recovery-v3-qualification/fa4e93b94f3504290546b828b0aa6774d352d40897e35828043ea3e2c16c02ad.tar.gz` (**9,106,993 bytes; 455 members**) with a tracked manifest and byte-exact extraction test.

Governed verification receipt: **116 V3 passed, 60 deselected; 176 Experiment 03 passed**.

Every visible byte above is generated deterministically from the authenticated freeze, recursive inventories, scorer controls, replay receipt, archive receipt, and governed verification receipt.

## Reviewer decision

The qualification does not self-authorize. Reviewer decision: **PENDING — approve or reject**.

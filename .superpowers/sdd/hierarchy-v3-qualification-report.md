# Hierarchical Recovery V3 pre-outcome qualification report

Date: 2026-08-23

Branch: `feat/hierarchy-recovery-probe`

Base: `3c2f5a3`

Qualified source commit: `1cc81bc469cc69ca2805704042f532279987b1b9`

Status: **READY FOR FRESH READ-ONLY REVIEW**

This report records pre-outcome qualification only. It is not an approval, does not self-authorize outcome execution, and makes no outcome claim. Seeds `20261801..20261810` were not executed. The outcome root `results/hierarchical-recovery-v3` was not created. A fresh read-only reviewer must approve or reject the qualification before any outcome run.

## Scope and immutable inputs

The implementation follows `docs/superpowers/specs/2026-08-23-hierarchical-recovery-v3-preregistered.md` and the binding V2 audit findings incorporated there. The V1/V2 reports, source, raw results, and derived results were read-only. Experiment 01 was imported for its existing arm, contracts, kinematics, representations, P6 path, and repaired P4 path; its 62-file tracked tree remained byte-identical. The frozen comparison covered those 62 files plus the two frozen V2 execution files (`run_v2.py` and `src/v2.py`), 64 files total. A base-to-HEAD path diff also confirms no tracked Experiment 01, V1/V2 execution, or pre-existing result file changed.

All new execution code is isolated in `v3_*` modules. The qualification stage rejects every seed outside calibration seeds `20261891`, `20261892`, `20261893`, and `20261894`. A separately typed, frozen outcome stage accepts only held-out seeds `20261801..20261810` after an immutable approval report/hash binding; constructing its exact 360-cell plan neither samples nor executes a seed and creates no output.

## TDD record

Baseline before V3 changes:

- `python -m pytest experiments/03_recovery/tests -q`: **60 passed in 39.17s**.
- Frozen V1/V2 plus Experiment 01 baseline: **64 files**, captured in `/private/tmp/hierarchy-v3-frozen-baseline.sha256`.

RED was observed before each implementation stage:

1. Contract/policy tests failed collection because `v3_contracts` and `v3_policy` did not exist.
2. Physical runtime tests failed because there was no V3 episode executor, disturbance realization, observable decision sequence, P6/P4 byte binding, or guarded budget reset.
3. Scorer tests failed because there was no raw-only independent scorer or terminal-positive-control audit.
4. Publication tests failed because there was no create-only qualification publisher, complete import-closure freeze, diagnostic bundle, or clean reconstruction.
5. The final contact-envelope RED run produced **2 failures**: missing per-tick contact force/envelope retention, and a collision scorer that still trusted the trace Boolean. After the fix, the targeted runtime/contact/scorer-control run was **3 passed in 3.41s**, and the runtime/scorer/evidence suite was **23 passed in 82.18s**.

GREEN commits:

- `cdf94ba` — define V3 qualification contracts
- `b71c5f0` — execute physical V3 qualification episodes
- `57da362` — independently score V3 raw traces
- `4789d59` — publish replayable V3 qualification evidence
- `3b2c731` — retain full contact envelopes and make them scorer-authoritative
- `d8d76d9` — close the injected-cause/observable boundary and add structural taint closure
- `c30aaba` — bind `T3_LIVE_BELIEF_V1` and reconstruct scorer authorities from immutable raw
- `a825b46` — freeze the approval-hash-guarded 360-cell outcome path and authentic geometry NOT_RUN
- `2878a81` — replace self-referential gates, freeze environment/spec/config, add PNGs and durable archive publication
- `e5c7fe4` — close the second construct review: verdict authentication, transitive cause closure, event-reconstructed T3, exact budgets/anchor effects/prechecks, and the complete frozen outcome path
- `1cc81bc` — force invalid/interrupted retained outcome dispositions to invalidate construct Gate 8

Review-fix RED/GREEN evidence included five authority-tamper failures (trace target/action flags, reported reset count, retained EEF, matched qref/torque envelope tampering, and T3 provenance/evidence hash), a last-object-only mission structural failure, missing spec/environment/PNG/archive failures, and independent gate failures. Focused GREEN runs were **18 scorer tests passed in 47.38s**, **1 full qualification/publication/reconstruction test passed in 211.46s**, and **1 durable archive extraction test passed in 140.09s**.

Initial focused verification before the first review:

- `python -m pytest experiments/03_recovery/tests -q`: **89 passed in 121.17s**.
- `git diff --check`: pass.
- `shasum -a 256 -c /private/tmp/hierarchy-v3-frozen-baseline.sha256`: **64/64 OK**.
- Repository-wide sandboxed run: **640 passed, 5 environment-only failures in 91.95s**. The failures were caused by sandbox-denied macOS dynamic-store/sysctl/localhost operations in existing P0/P1/replay/source-checkout tests, not V3 assertions.
- Repository-wide run with the required macOS dynamic-store/sysctl/localhost test capabilities: **645 passed in 92.39s**.

Final post-review-fix verification:

- V3-only selection: **43 passed, 60 deselected in 444.70s**.
- Complete Experiment 03 suite: **103 passed in 474.15s**.
- Canonical qualification CLI: **18 episodes; 17 SUCCESS, 1 expected FAILURE; 10/10 gates; `READY_FOR_FRESH_READ_ONLY_REVIEW`**.
- Independent clean reconstruction: **18 episodes, `matched=true`**, raw manifest `a6407854…`, derived manifest `7f0ab57d…`.
- Durable archive extraction round trip: **1 passed in 140.09s**.

Second-review RED/GREEN evidence includes: rejected-report acceptance (**2 RED → 2 GREEN**); forged and self-rehashed T3 fact (**1 RED → GREEN**); CONTROL `2→2` budget tamper (**1 RED → GREEN**); seven matched-anchor substitutions (**7 GREEN**); environment/config drift (**2 GREEN**); missing/tampered prechecks (**1 GREEN**); approval dry-run and interrupted disposition retention (**2 GREEN**); synthetic 360-row complete analysis without sampling (**1 GREEN**); contracts/runtime/outcome (**24 passed in 30.67s**); scorer/outcome (**30 passed in 50.55s**); and full publication/reconstruction (**1 passed in 222.54s**).

Final second-review V3 selection: **60 passed, 60 deselected in 481.01s**.

Final complete Experiment 03 regression: **120 passed in 531.63s**.

## Qualification episodes

The retained matrix contains exactly **18 executed episodes**, all using calibration seeds. Independent scoring reconstructed **17 SUCCESS** and **1 expected FAILURE**. The failure is the deliberately nonworking R0 semantic case, which exhausts its two control retries and safely aborts without executing a forbidden action.

| Coverage cell | Episodes | Result |
|---|---:|---|
| R3/P6, all eight registered scenarios, seed `20261891` | 8 | 8 SUCCESS |
| R0/R1/R2/R3 semantic-object-unavailable, seed `20261893` | 4 | 3 SUCCESS; R0 expected FAILURE |
| R0/R1/R2/R3 control-impulse, seed `20261892` | 4 | 4 SUCCESS |
| R3 P6/P4 anchor sensitivity, seed `20261894` | 2 | 2 SUCCESS |

Injection rows exactly equal the sampled injection tick in every executed episode. Retained sampled ticks range from 625 to 885 and are never replaced by a fixed step. The diagnostic table retains the sampled tick, retained row, parameter-use hash, and physical-trace hash for every episode.

The six disturbances operate on the simulated system rather than scenario counters:

- control impulse applies the sampled N·m vector through MuJoCo `qfrc_applied` for the sampled duration;
- control dropout withholds/holds commands for the sampled interval;
- target shift mutates the world target and regenerates the motion command;
- path infeasibility activates a real contact-enabled obstacle; the direct segment is blocked and the retained waypoint route is collision-free;
- semantic object unavailability and restriction change remain pending until their sampled delivery tick, update retained memory to version 2 exactly once, force an objectless safe hold, and authorize the alternative object B only after delivery;
- the slow-policy anchor delays the observable policy path without inventing a disturbance or intervention count.

Every episode retains 3,125 rows at 500 Hz for state, velocity, end-effector pose, joint position/velocity reference, actual actuator torque, applied external torque, target, action validity, authorization, safe hold, contact count, and force/torque norms. It also retains a per-tick action envelope and full per-contact envelope: geom IDs and names, distance, 3D position, 9D frame, and the six-axis contact force/torque. The scorer derives obstacle collision from contact geom identities; falsifying the old `obstacle_contact` trace Boolean does not change the terminal.

## Observable policies, budgets, and controller paths

The recovery policy accepts only `(architecture, observable, budget)`. The typed observable excludes scenario ID/domain, hidden cause, and intended/expected recovery level. Decisions bind the observable SHA-256 and observed tick.

Retained non-NONE decision sequences for semantic-object-unavailable seed `20261893` are:

| Architecture | Decision sequence | Terminal |
|---|---|---|
| R0 | CONTROL at 733; CONTROL at 758; SAFE_ABORT at 783 | FAILURE |
| R1 | SEMANTIC at 733 | SUCCESS |
| R2 | MOTION at 733; MOTION at 758; SEMANTIC at 783 | SUCCESS |
| R3 | SEMANTIC at 733 | SUCCESS |

For control-impulse seed `20261892`, the first retained decisions are R0=CONTROL, R1=SEMANTIC, R2=MOTION, and R3=CONTROL, demonstrating distinct policy behavior from shared physical realization rather than scenario-selected recovery.

Budgets are exactly control/motion/semantic = `2/2/1`. Each retry/replan advances 25 MuJoCo ticks (50 ms) before re-observation. Resets occur only when content bytes change and a retained successful-execution receipt binds the new content SHA-256; the diagnostic budget table includes the pre/post counters and observed ticks.

The existing P6 and repaired P4 sensitivity paths are both actually called, and their executed bytes differ:

| Controller | Call path | Trajectory SHA-256 | q_ref SHA-256 | torque SHA-256 |
|---|---|---|---|---|
| P6 | `emit_chunk:P6 -> reference_for_tick:P6 -> bounded_pd` | `e7d44319c53d2322f94a4648ff0da34cc8fa84bd4d0027fcd3ee49cf39a8b20a` | `4b15de7f2ae423c793ee21c7ce4afb3bae41b225e41ff779aaecef6ce88de803` | `0a14099f48d8aab7ca82945a28240af29a37179755f5f57f69729dd059cfafdf` |
| repaired P4 | `emit_chunk:P4 -> with_p4_executor_tuning:1:dqon -> reference_for_tick:P4 -> bounded_pd` | `890e6188f28e84731dd77fee96564bbb183667c9fc32f86a1c0cfee7c77a4d61` | `a03f3e9d70e73586b78be19e8fff3ef9344b597d1175c479be2a66b964bd7ce4` | `743638fe0054d0826d2893e3c2e2b99eb16becdb8a0620d1a3494f347f010232` |

## Independent scoring and controls

The independent scorer does not import `v3_runtime` and never reads executor-authored result/debug Booleans. It reconstructs FK/end-effector pose and target error from raw qpos and the world ledger; command hashes; actual ActionChunk trajectory members; action/reference/torque agreement; action age and validity; contact collision; the complete object mission across the final dwell window; `T3_LIVE_BELIEF_V1` schema, facts, provenance, stale/unknown fields and evidence hashes; authorization; loop progress; and successful-execution/reset validity from raw authorities. It no longer uses a last-executed-object shortcut.

Each single-authority positive control independently closes the terminal to FAILURE:

| Control | Detected count |
|---|---:|
| collision | 1 |
| forbidden execution | 9 |
| invalid action/trajectory | 1 |
| loop/no progress | 1 |
| missed dwell | 1 |
| invalid reset | 1 |
| stale observation/memory | 2 |
| unsafe torque | 1 |
| wrong object | 9 |

An architecture-independent positive control is retained as NOT_RUN before execution for the geometric-precheck path. It is not counted as an episode or failure.

## Evidence, reconstruction, and diagnostics

Ignored qualification evidence root: `results/hierarchical-recovery-v3-qualification`

Files: **437**

Bytes: **50,002,928**

| Artifact | SHA-256 |
|---|---|
| qualification freeze | `0e579fce1327dbbe70d30140d7482fcae38f74352c90607a7181d269679b5248` |
| raw manifest / raw reconstruction | `a640785497bdb96beb672dc33a166059d70bc5c25facd0f7344ae37be8066572` |
| derived manifest / derived reconstruction | `7f0ab57d243687ea4f2b748a8e39781d0c231ec9b847266c458b16b23001cf3e` |
| qualification summary | `1372bb6421ff5ef0aae9aa64b398dd58df81daf46c639a25c9c28710304b32ca` |
| gate audit receipts | `39bf35cb6412407f0128165bc0993618f8886f2b308f7d4ed3471e7d0ecd9cc3` |
| replay receipt | `d8bd12f6c31dad887f3e9691974a2dd91e6a0ec9df9632575d17693ae58e4517` |
| source/spec/import closure | `85251fc9c311f631da2e8a9cdaf75f95c349c5b87fb91c50af76d154b73f13d0` |
| frozen qualification/outcome configuration | `1e5fec9533ad61eced4a485ef5b8615586050e470167b8f373b79e55d1860672` |
| frozen environment | `d6e2926ed735b6049ca7752e318f32206af0926e6745fbd2d52f9886669d1b5f` |
| durable qualification tree | `f8c0f1d4194cae3ce680ad499450d4d22b8d7b98664d8ae694533a5cc7a17a7c` |
| durable archive | `bcc59df409a43ece3b81b144a6715ed72d74c1e9c71213a9eaca9d9451e4d6c2` |

Clean reconstruction destination: `/private/tmp/hierarchical-recovery-v3-clean-1cc81bc`. It independently replayed all **18** episodes with `matched=true`; the regenerated raw and derived manifest hashes exactly equal the hashes above. Reconstruction reads raw episode inputs and does not trust the original summaries.

The canonical diagnostic bundle includes tables plus deterministic SVG and exact SVG-rasterized PNG companions for injection timing/disturbance realization, P6/P4 controller byte differences, time-advanced budgets/retries, and scorer-positive controls. All companions are authenticated by the derived manifest. `gate-audits.json` retains separate injection receipts, matched-anchor domain effects, exact decision-budget transitions, transitive typed cause closure, every qualification precheck, the frozen precheck-before-execution outcome plan, and recomputed geometric NOT_RUN receipts. `examples.json` binds:

- working: `qualification-P6-R3-semantic-object-unavailable-20261891`
- nonworking: `qualification-P6-R0-semantic-object-unavailable-20261893`
- NOT_RUN: `architecture-independent-unreachable-geometry-v1`

The ignored working bundle is durably retained as the tracked, deterministic, content-addressed archive `reports/evidence/hierarchical-recovery-v3-qualification/bcc59df409a43ece3b81b144a6715ed72d74c1e9c71213a9eaca9d9451e4d6c2.tar.gz` (**8,757,685 bytes; 437 members**) with a tracked manifest and byte-exact extraction test.

The 10 registered hard gates all pass in the qualification bundle: exact sampled-tick injection, six realized disturbances, distinct observable policy sequences, real/different P6 and P4 paths, time-advanced guarded budgets, closed cause boundary, independent raw scorer, nine terminal-positive controls, byte-exact replay/reconstruction, and architecture-independent NOT_RUN handling.

## Concerns and reviewer decision

- This is representative calibration qualification, not an outcome sample, power result, or scientific claim.
- The one R0 failure is intended evidence for a nonworking architecture under semantic change; it is not silently excluded.
- Outcome execution is frozen but approval-gated: the verifier parses a canonical reviewer report, requires exact `APPROVED_FOR_OUTCOME` with zero Critical/Important findings, binds all qualification/source/report hashes, and rechecks configuration/environment identities. The frozen post-approval path includes resumable create-only execution, full dispositions, paired analysis, 10,000-draw realization bootstrap, eight gates, graphs, reconstruction, and archive publication.
- The ignored evidence is create-only and source-bound to commit `1cc81bc`; any source change requires regeneration and another review.
- No outcome evidence root exists at report time.

Reviewer decision: **PENDING — approve or reject; this implementation does not self-authorize.**

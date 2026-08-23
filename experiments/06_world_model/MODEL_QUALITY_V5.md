# Experiment 06 model-quality v5

Status: `ENGINEERING_NONCONFIRMATORY`; gate: `FAIL`; classification: `NOT_USEFUL_YET`.

Experiment 06 v4 is invalid because all 24 v3 evaluation scene identities and seeds were reused after the v4 architecture was designed. The adjacent machine-readable marker `results/model-quality-v4.INVALID_EVALUATION_REUSE.json` records that disposition without changing any v4 evidence byte.

V5 froze the exact v4 model artifact (SHA-256 `70666cdd4226a05e00d0a1b4552fd27760f91d42ca7f93dca4d0706e046a20de`), including the tune-selected `W3R` choice, coefficients, features, ensemble alphas, and ancestry. The runner did not call fitting or tuning. It generated a new namespace for all 48 evaluation scenes (16 ID and 8 per OOD stratum); all 48 `(scene_id, seed)` pairs are disjoint from every v3 and v4 train, tuning, and evaluation scene. No v5 outcome existed or was inspected before the namespace, source, and frozen-model boundary were committed at `a840fa0b374845aa9677d0036a07e7ef11b92467`.

The conservative full cycle reran 72 training, 24 tuning, and 48 untouched evaluation scenes solely to retain the existing closed evidence/replay contract: 144 scenes, 288 anchors, and 2,304 branches. All 144 attempt dispositions are `VALID`.

## Untouched evaluation result

The frozen W3R selector achieved 0.719822 mean regret, versus 0.827389 for W1V2, 0.971072 for DIRECT, and 0.956933 for deterministic W0. It passed the overall, DIRECT, and latency checks, but beat W1V2 in only three of five strata. The frozen four-of-five requirement therefore fails. This is not selector authority and does not justify deployment or another evaluation-driven tuning cycle.

| Stratum | DIRECT | W1V2 | W3R | W3R beats W1V2 |
|---|---:|---:|---:|:---:|
| ID | 0.926742 | 0.644567 | 0.701282 | no |
| MASS_OOD | 0.997090 | 0.961861 | 0.327076 | yes |
| FRICTION_OOD | 1.382203 | 1.567944 | 1.066407 | yes |
| GEOMETRY_OOD | 1.415790 | 0.815542 | 1.443295 | no |
| OBSTACLE_OOD | 0.177866 | 0.329854 | 0.079588 | yes |

W3R top-1 accuracy was 0.15625, selected success fraction 0.135417, selected collision fraction 0.364583, and mean Spearman correlation 0.068452. Its measured inference latency was 0.501 ms p50 and 0.706 ms p95 per candidate. No selector, including the oracle, produced a successful OBSTACLE_OOD selection; this stratum's regret improvement must not be described as task success.

## Evidence and reconstruction

The raw evidence retains complete scenes, MuJoCo integration anchors, candidate/action bytes, branch truth, attempt dispositions, timing samples, the exact frozen model bytes, and their closed v4 provenance. The frozen model file is byte-identical in v4, v5 raw input, and v5 derived output. Derived evidence retains all predictions, selections, metrics, gate checks, and annotated relative-working, relative-nonworking, and maximum-regret examples.

Clean reconstruction reproduced the derived directory byte-for-byte. Root manifest SHA-256 is `84bc01905a4167c300d87f070af74eadb71eab802282813afb9614fe3f37dca9`; metrics SHA-256 is `e68fe3392b11d461083126eb9a3195f56c76e72495163b0de0e3857900ab9117`; raw actions SHA-256 is `52ab9853789e9cd6d2f39b7dbb7152f0d2622c61a6c649ddceb74ff97b264344`.

## Boundary

This is a negative engineering result on a synthetic planar-pushing family. V5 repairs evaluation identity reuse but does not convert prior training/tuning work into confirmation evidence. Any future model change must start a new preregistered train/tune/evaluation cycle with another untouched evaluation namespace; v5 outcomes must not be used for model selection and then presented as holdout evidence.

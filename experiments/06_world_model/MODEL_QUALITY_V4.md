# Experiment 06 model-quality v4

Status: `ENGINEERING_NONCONFIRMATORY`; classification: `MECHANISTIC_IMPROVEMENT / NOT_USEFUL_YET`.

This create-only cycle used 72 ID training scenes, 24 ID tuning scenes, and 48 untouched evaluation scenes (16 ID and 8 per OOD stratum). Each scene produced two anchors and eight candidate branches: 144 scenes, 288 anchors, and 2,304 branches. All 144 attempt dispositions are `VALID`. The source ledger binds commit `0ff47efb29b30cccc7a265d8992310c6aca4be7f`, Python 3.11.13, NumPy 2.4.6, and MuJoCo 3.12.0.

## Result

Tuning selected `W3R`, the residual-cost ridge ensemble. On untouched evaluation its mean regret was 0.521865, versus 0.674675 for the truth-free quasi-static/contact comparator `W1V2` and 0.810565 for `DIRECT`. It beat `W1V2` in four of five strata and its measured inference latency was 0.484 ms p50 / 0.745 ms p95 per candidate. Those facts satisfy the frozen engineering gate.

The gate pass is not selector authority and does not establish practical usefulness. The deterministic `W0` comparator was better overall at 0.476896 mean regret. `W3R` also failed badly in `MASS_OOD` (1.571347 regret versus 1.254467 for `W1V2`) and selected no successful branches in `OBSTACLE_OOD`. No post-evaluation retuning was performed.

| Stratum | DIRECT | W1V2 | W3R | W3R beats W1V2 |
|---|---:|---:|---:|:---:|
| ID | 0.973277 | 0.517924 | 0.479121 | yes |
| MASS_OOD | 1.269433 | 1.254467 | 1.571347 | no |
| FRICTION_OOD | 0.711460 | 0.789489 | 0.318657 | yes |
| GEOMETRY_OOD | 0.708254 | 0.716939 | 0.046474 | yes |
| OBSTACLE_OOD | 0.227689 | 0.251304 | 0.236471 | yes |

`W3R` top-1 accuracy was 0.145833, selected success fraction 0.145833, and mean Spearman correlation 0.112351. Its cost MAE was 1.155122; this is worse than the W1V2 cost MAE of 0.896736 even though W3R made better ranking decisions under the frozen regret gate. The terminal residual ensemble `W4R` achieved 0.640663 overall regret and was not selected by tuning.

## Evidence and reconstruction

The raw directory retains the exact scene specifications, complete MuJoCo anchor states, candidate identities and action hashes, the 2,304-command tensor, branch truth, attempt dispositions, source ledger, and measured latency samples. Derived evidence contains all 4,608 predictions, 864 selector decisions, model coefficients/ancestry, overall and stratum metrics, the mechanical gate record, and annotated relative-working, relative-nonworking, and maximum-regret examples.

Running `python -m experiments.06_world_model.run --reconstruct-from experiments/06_world_model/results/model-quality-v4/raw --reconstructed-output <clean-dir>` reproduced every derived file byte-for-byte. The root manifest SHA-256 is `40be9ef3b736684b89854af856462aab3ad65c8f2a9f2bfdb1463a26a7bdc8c4`; raw actions SHA-256 is `20a5b2407c93cc0605936d44cc388a41d76cad93bc2f3a31d98dc6697bd7c0be`; metrics SHA-256 is `41ad4d98d3b1a783ac80f9793fe62f4ff384964bf6f48e29d376e7832f00a752`.

## Boundary

This is a deterministic engineering result on a synthetic planar-pushing family, not a confirmation result and not deployment evidence. Collision is a scene/anchor outcome in this world and was identical across selectors in aggregate; it should not be interpreted as evidence that the selector controlled collision risk. The informative next experiment is a frozen targeted MASS_OOD/obstacle diagnosis or a genuinely stronger non-random comparator—not retuning on these 48 evaluation scenes.

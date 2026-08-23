# Experiment 06 learned candidate-ranking engineering result

Status: `PRELIMINARY_NONCONFIRMATORY_ENGINEERING_ONLY`.

Decision: **`NOT_USEFUL_YET` for selector authority.** W3 and W4 show measurable
ranking signal, but neither is robust across held-out strata, neither closes most of
the exact-rollout oracle gap, both lose to the deterministic random selector overall,
and latency was not measured. W2 is an explicitly nondeployable exact-MuJoCo oracle.

## Outcome

The experiment ran 88 deterministic scenes, two anchors per scene, and all eight
meaningful one-second candidates per anchor: 1,408 independently restored MuJoCo
branches. Models fit 48 ID training scenes, selected their ridge value on 16 disjoint
ID tuning scenes, then produced predictions once for 24 untouched evaluation scenes
(8 ID and 4 per OOD stratum).

| Selector | Role | Regret | Spearman | Top-1 | Success |
|---|---|---:|---:|---:|---:|
| DIRECT | reactive control | .736582 | n/a | .1250 | .1042 |
| W0 | deterministic random control | .419266 | n/a | .1458 | .1667 |
| W1 | progress heuristic | 1.100933 | -.2826 | .0000 | .0417 |
| W2 | exact-rollout oracle | .000000 | n/a | 1.0000 | .2292 |
| W3 | learned progress/cost ridge | .689378 | .1798 | .1250 | .1042 |
| W4 | learned full-chunk dynamics ridge | .701020 | .1141 | .1875 | .1042 |

W3 reduced regret by .411555 (37.4%) relative to W1 and .047204 (6.4%)
relative to DIRECT. W4 reduced it by .399913 (36.3%) relative to W1 and
.035562 (4.8%) relative to DIRECT. These descriptive overall improvements do not
survive the stronger comparisons: W0 regret was .419266, while the W2 oracle shows a
large remaining gap. The learned models also selected successful candidates only 5 of
48 anchor decisions each, versus 11 of 48 for W2.

## Held-out strata

Values are mean selection regret; lower is better.

| Stratum | DIRECT | W0 | W1 | W2 oracle | W3 | W4 |
|---|---:|---:|---:|---:|---:|---:|
| ID | .676255 | .363850 | .397416 | 0 | .348662 | .722104 |
| MASS_OOD | 1.285328 | 1.287392 | 2.537982 | 0 | 1.894232 | 1.885173 |
| FRICTION_OOD | .681768 | .015580 | 1.366539 | 0 | .666227 | .651407 |
| GEOMETRY_OOD | .743571 | .245924 | 1.541477 | 0 | .802445 | .002078 |
| OBSTACLE_OOD | .356312 | .239003 | .364766 | 0 | .076037 | .223252 |

Both learned models beat W1 in every stratum, but W1 itself has negative mean rank
correlation in every stratum. Against DIRECT, W3 fails MASS_OOD and GEOMETRY_OOD;
W4 fails ID and MASS_OOD. W4's near-oracle GEOMETRY_OOD result does not generalize,
while W3's strongest result is OBSTACLE_OOD. This is evidence of heterogeneous model
error, not a stable learned-selector advantage.

Selected ridge values were .001 for W3 and .01 for W4. The retained model records bind
exactly 48 training scene IDs and separately list the 16 tuning IDs; no evaluation ID
appears in either fit domain. All 1,152 prediction rows and 288 selection rows contain
evaluation identities only.

The true selected-candidate collision rate is .333333 for every selector. This is not
candidate discrimination: candidate-set collision prevalence is also .333333, and the
mixed-collision-anchor fraction is exactly zero. At 16/48 evaluation anchors all eight
candidates collide; at the other 32 none do. Rates by stratum are ID .125,
MASS_OOD .25, FRICTION_OOD .50, GEOMETRY_OOD .25, and OBSTACLE_OOD .75. Version 2
therefore names the selector metric `selected_collision_fraction` and separately
records `candidate_collision_prevalence`, `all_collision_anchor_fraction`, and
`mixed_collision_anchor_fraction`. Collision cannot support a selector contrast in
this matrix.

## Outcome coverage and examples

Training and tuning contain success, terminal failure, collision, HOLD/no-op, and
progress/recovery outcomes. Every evaluation stratum contains failures, collisions,
HOLD, and progress/recovery cases. Evaluation successes by stratum were ID 14/128,
MASS_OOD 12/64, FRICTION_OOD 10/64, GEOMETRY_OOD 10/64, and OBSTACLE_OOD 0/64.
Therefore the approved P7 per-stratum outcome-coverage gate would fail on
OBSTACLE_OOD. The experiment retains that failure and performs no adaptive seed
replacement.

Representative W3 evidence is
`exp06/evaluation/friction_ood/742a3688e863b6dc/anchor/00/candidate/HOLD`
(successful, regret .000142) and the same scene's anchor-01 DIRECT candidate
(failed, regret 5.001460). Representative W4 evidence is that scene's anchor-00
DIRECT candidate (successful, regret .001076); its worst miss is
`exp06/evaluation/mass_ood/7b9ba8411f9d1131/anchor/00/candidate/RIGHT_EDGE`
(failed, regret 5.009674). These are the first canonical success/failure or maximum
regret rows under explicit rules, not hand-picked omissions.

## Validity repair, evidence, and reconstruction

- V1 and V2 are retained byte-for-byte but are not valid evidence. V2 is machine-marked
  `INVALID_PRE_FIX` by `results/engineering-ranking-v2-invalid.json` because candidate
  hashes included labels rather than proving unique action bytes, anchors omitted part
  of MuJoCo integration state, and reconstruction trusted recorded outcomes instead of
  replaying physics.
- V3 hashes every candidate from exact dtype, shape, command timestep, and command bytes.
  All 176 anchor groups contain eight distinct action preimages; four duplicate raw
  compilations received one frozen `1e-9` m/s perturbation, recorded with their pre/post
  hashes and generation counters.
- Every anchor records `mjSTATE_INTEGRATION=16383`, exact state size 38 and vector,
  separately bound mocap position/quaternion, MuJoCo version, and an exact post-restore
  equality check before every branch.
- Reconstruction authenticates the exact root inventory, recorded Git source blobs and
  frozen split, regenerates all scenes/anchors/actions, reruns all 1,408 MuJoCo branches,
  and only then derives models and metrics.
- Execution Git SHA: `a6a3895ae6c3e4e52061e7f5a0d72e2e59d5d727`.
- Runtime: Python 3.11.13, NumPy 2.4.6, MuJoCo 3.12.0.
- Config SHA-256: `0f17dbe6d350547941a249c1c10735a3e966ea4fac3ac54159f46aaaabdceff3`.
- World SHA-256: `78b3acf1524a84c3106dfc57ea74410c65995c69100e07ab0423a7e65d610415`.
- Model SHA-256: `51f1cb70aa42432dc64e1d3cdaa3792606ce2d7669a8fb6967fe0e763d4c8d8e`.
- Runner SHA-256: `2de459bc48159d8a8918b2a5b5d5f58081df820037be69e8379a00c2c655ecaf`.
- Result manifest SHA-256:
  `696f498793c2820a9ebd6dafc38515d39edfe3bb9eed1546a00612dac363ec86`.
- Complete evidence: 13 files, 4,620,124 bytes; canonical inventory SHA-256
  `7939cb59d24d8f1e3a6dcc2e6fcfc53ca9ea49503dd381abca5bad88aca50648`.

Ignored evidence is at
`experiments/06_world_model/results/engineering-ranking-v3/`. It contains exact
scene and anchor records, all 1,408 command arrays and hashes, all branch outcomes and
cost components, valid-attempt ledger, fitted coefficients and ancestry, untouched
evaluation predictions, rankings, metrics, recipe, and file manifest.

The derived directory was reconstructed from sealed raw evidence into
`experiments/06_world_model/results/engineering-ranking-v3-reconstructed/`; `diff -rq`
returned no output. The exact command is:

```text
.venv/bin/python -m experiments.06_world_model.run \
  --reconstruct-from experiments/06_world_model/results/engineering-ranking-v3/raw \
  --reconstructed-output experiments/06_world_model/results/engineering-ranking-v3-reconstructed
```

The original v1 root remains byte-for-byte preserved. Its manifest SHA-256 is
`156ca7601421f5a4f7287c4b5c533f2f0a9963ff0f35eee5bf64b5e9ce54c75d`; its ambiguous
`collision_fraction` label is superseded for interpretation, not silently rewritten.
The preserved V2 manifest SHA-256 is
`6eaa6ab43980619ceb50211dfd9543f0fe98f17385519a877afa33e55067bb06`.
V3 is the sole valid result reported here.

This bounded run did not measure inference latency, fit calibration/fallbacks, or run a
confirmatory bootstrap. It cannot grant runtime authority. The highest-information
follow-on is not a larger version of the same grid: improve the W1 control and address
MASS_OOD/ID model misspecification, then require a new untouched evaluation root with
complete per-stratum outcome coverage.

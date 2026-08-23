# Experiment 06 model-quality v6

Status: `ENGINEERING_NONCONFIRMATORY`; gate: `FAIL`; classification: `NOT_USEFUL_YET`.

V6 was frozen in source commit `6015894580917714d42ead3764a99799942cdf60`
before any v6 outcome existed. All 144 scene IDs and seeds use the new
`exp06-v6` / `scene-v6-cycle` namespace and have zero identity or seed overlap
with every v3-v5 train, tuning, or evaluation row. The exact matrix contains 72
ID training scenes, 24 ID tuning scenes, and 48 untouched evaluation scenes (16
ID and 8 per OOD stratum), with two anchors and eight byte-distinct actions per
scene: 2,304 replayed MuJoCo branches. All 144 attempts are `VALID`.

## Frozen calibration

Training selected W3R as the residual parent. The fixed confidence threshold
domain was the tuning-score quantiles `(0.25, 0.50, 0.75)`, which yielded
thresholds `(0.7059795831, 0.8214734255, 0.9940987651)`. Tuning selected q=0.75,
threshold `0.9940987651`, with residual-use fraction 0.75. Calibration SHA-256
is `ee950e12bcb003ca7d97a110d2014c5cf7812dea254875a53260d658828e7d27`.
No threshold, score component, candidate, or gate was changed after evaluation.

W5 uses only ordinary state/action features, training-standardized feature
distance, ensemble cost disagreement, W3R/W4R rank disagreement, and nominal
geometry/contact margin. Evaluation outcomes are joined only after W5 has
chosen its source selector and candidate.

## Untouched evaluation result

| Selector | Mean regret | Top-1 | Selected success |
|---|---:|---:|---:|
| DIRECT | 0.536927 | 0.114583 | 0.114583 |
| W0 | 0.623401 | 0.135417 | 0.093750 |
| W1V2 | 0.509994 | 0.291667 | 0.125000 |
| W3R | 0.620275 | 0.093750 | 0.093750 |
| W4R | 0.500591 | 0.135417 | 0.114583 |
| W5 | 0.598500 | 0.187500 | 0.104167 |

W5 used the residual path on 54/96 anchors (0.5625), satisfying only the
nontrivial-coverage check. It was worse overall than W1V2 and DIRECT, and it
beat W1V2, W3R, W0, and DIRECT simultaneously in zero of five strata. Full-K=8
anchor latency was 24.607 ms p50 and 34.916 ms p95, failing the frozen 5 ms
limit. The mechanical gate therefore fails three of four checks and grants no
authority.

| Stratum | DIRECT | W0 | W1V2 | W3R | W5 | W5 residual use |
|---|---:|---:|---:|---:|---:|---:|
| ID | 0.684313 | 1.153277 | 0.653453 | 0.637256 | 0.637363 | 0.78125 |
| MASS_OOD | 1.575263 | 0.951549 | 0.945018 | 1.567993 | 1.258127 | 0.87500 |
| FRICTION_OOD | 0.067192 | 0.039871 | 0.132139 | 0.137540 | 0.132541 | 0.43750 |
| GEOMETRY_OOD | 0.015726 | 0.364694 | 0.324720 | 0.638653 | 0.639739 | 0.25000 |
| OBSTACLE_OOD | 0.194755 | 0.077739 | 0.351178 | 0.102956 | 0.285869 | 0.25000 |

The confidence gate did not generalize its tuning advantage. Its current
implementation also recomputes residual features/predictions during the K=8
decision, making the latency failure real rather than a reporting artifact.
These results must not be used to tune a replacement and then reuse v6 as a
holdout. A later model change requires another fully new frozen cycle.

## Evidence and reconstruction

The raw evidence retains complete scene specifications, MuJoCo integration
anchors, candidate/action bytes, branch truth, all attempt dispositions, exact
models, calibration ancestry, and measured latency samples. Derived evidence
retains 4,608 predictions, 960 selections, full metrics and strata, the failed
gate, and authenticated relative-to-W1V2 working/nonworking and maximum-regret
annotations. “Working” in annotations is explicitly relative, not absolute;
the retained relative-working exemplar has regret 5.012699.

Full reconstruction replayed every branch with exact state restoration and
reproduced the derived directory byte-for-byte. Evidence identities:

- Root manifest SHA-256: `68342629caa371d3ba2384d20d49757713555b87a8380416bc55412fdf95b2da`
- Raw actions SHA-256: `b18b2660dc4a12a5845b1d8b8489513ca39e7d4846ff445dd078a2bc68eed9b3`
- Raw calibration SHA-256: `4a6c6507004ad37e5cf1086372391dde978cd22c9296d95e26e812111fc384ef`
- Metrics SHA-256: `0a68d548c45137400428d93f81e9c784970bbb31271ce2db5baff484e609440a`
- Complete evidence: 20 files, 9,827,850 bytes
- Canonical inventory SHA-256: `2cef4907915bab019477fd5fd704b99c39f4716bd5a41557cbf9691c9d2b8a10`

The inventory digest is SHA-256 over newline-terminated canonical JSON for the
sorted relative-path, byte-count, and file-SHA inventory. This synthetic planar
pushing experiment is engineering evidence only; it is not confirmation,
deployment evidence, or selector authority.

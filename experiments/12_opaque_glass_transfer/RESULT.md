# Opaque-to-transparent obstacle transfer: held-out result

**Disposition:** `SUPPORTS_RENDERED_GEOMETRY_TRANSFER`; synthetic engineering
evidence only. Source/config freeze: `d779684f4ce4a7216ec9e3bd8373222c1c7b6e81`.

## Situation, objective, and method

This experiment asks a deliberately narrow question: if an obstacle's MuJoCo
collision geometry stays fixed but its rendered material changes from opaque red
(`alpha=1.0`) to glass-like transparent (`alpha=0.08`), what transfers from opaque
calibration?

Twelve fresh held-out seeds generated matched triplets: no obstacle, opaque
obstacle, and transparent obstacle. Each triplet kept robot/goal state, camera,
lighting and obstacle physics fixed. Three controllers saw the same initial 96x96
render bytes: an opaque-calibrated red-pixel RGB baseline, an RGB-D geometric
detector with motion replanning, and a semantic/motion/control hierarchy using the
same RGB-D geometry. Actual MuJoCo contacts and state/command tick traces were
scored independently. The 108-episode matrix and thresholds were committed before
these seeds ran.

## Outcome

| Condition | Controller | Detection | Task completion | Collision-free | Safe completion | Mean path (m) |
|---|---:|---:|---:|---:|---:|---:|
| No obstacle | RGB only | 12/12 | 12/12 | 12/12 | 12/12 | 2.303 |
| No obstacle | RGB-D motion | 12/12 correct absence | 12/12 | 12/12 | 12/12 | 2.303 |
| No obstacle | Hierarchical | 12/12 correct absence | 12/12 | 12/12 | 12/12 | 2.303 |
| Opaque | RGB only | 12/12 | 12/12 | 12/12 | 12/12 | 2.568 |
| Opaque | RGB-D motion | 12/12 | 12/12 | 12/12 | 12/12 | 2.568 |
| Opaque | Hierarchical | 12/12 | 12/12 | 12/12 | 12/12 | 2.568 |
| Transparent | RGB only | 0/12 | 0/12 | 0/12 | 0/12 | 1.030 |
| Transparent | RGB-D motion | 12/12 | 12/12 | 12/12 | 12/12 | 2.568 |
| Transparent | Hierarchical | 12/12 | 12/12 | 12/12 | 12/12 | 2.568 |

The RGB baseline's paired transparent-minus-opaque detection and safe-completion
drops were both -1.00 (10,000-draw paired bootstrap 95% interval [-1.00, -1.00],
effective n=12). Both stronger controllers had zero transfer drop [0.00, 0.00]
and improved transparent safe completion over RGB-only by +1.00 [1.00, 1.00],
effective n=12. RGB-only accumulated 3,199 obstacle-contact ticks across its 12
transparent runs; both stronger variants accumulated zero.

These zero-width intervals describe an exact deterministic property of this small
frozen seed matrix, not population certainty.

## Working and nonworking samples

The frozen sample rule chooses the lowest seed in each class.

- **Nonworking:** seed 5101, transparent, RGB-only. The rendered RGB threshold
  reported no obstacle; the direct controller contacted it for 268 ticks, stopped
  1.437 m from goal, and timed out at 300 ticks. Raw trace SHA-256:
  `c3e16762618590c134a9fb8f73b3992c3cc5ae6f32c2fea9458d630ec92fbd88`.
- **Working:** seed 5101, transparent, hierarchical. Depth pixels localized the
  obstacle to 0.0082 m, the initial semantic route remained valid, the motion path
  cleared the geometry with zero contact, and control reached 0.0979 m from goal in
  274 ticks. No retry/replan was needed. Raw trace SHA-256:
  `d5a417447f4c662df6700c9b83de2743ff5c2a63c38bfa728f2c66bf0b0a0227`.

The shared transparent render has PNG SHA-256
`b9ec2e8d9f62df77b9e54f3dfb001e5d06659434e8a423b62787c2b4e49ea0df`,
RGB NPY `fcb15fad975da9accbba6db546c6c9c90d27aa74270890a42960145da5b575ca`,
and depth NPY `deab6167fd8c42336765d0412805bb45d5943e9ee2cc1374bc07341ea98ec0e9`.

## Inference and conclusion

The appearance-only intervention is enough to break an opaque-calibrated RGB
detector/controller while depth-derived geometry transfers perfectly on this
matrix. This is indicative evidence for keeping geometric perception/belief
separate from appearance-bound semantic labels and for feeding geometry to the
motion layer.

It is **not** evidence that the full three-level hierarchy beats RGB-D motion:
their held-out outcomes and paths were identical, and nominally correct depth
plans never triggered recovery. A follow-up needs controlled post-plan occlusion,
geometry motion, and route invalidation to exercise control retry, motion replan,
and semantic alternate-route behavior independently. This result also does not
support a real-world glass claim: transparent MuJoCo rendering/depth is synthetic
and does not model camera ToF/stereo failure, refraction, glare, dirt, or sensor
noise.

## Evidence and reconstruction

- `results/qualification-v1/episodes.csv`: all independently scored episode rows.
- `results/qualification-v1/scenes/`: XML, exact scene contract, rendered PNG and
  numeric RGB/depth arrays for all 36 seed-condition scenes.
- `results/qualification-v1/episodes/`: complete state, command, waypoint,
  recovery and contact ledgers plus independent scores for all 108 episodes.
- `results/qualification-v1/analysis.json`: exact cell metrics and paired bootstrap
  contrasts.
- `results/qualification-v1/transparent-safe-completion.svg`: graph derived from
  the analysis rows.
- `results/qualification-v1/annotated-samples.json`: machine-readable working and
  nonworking sample annotations.
- `results/reconstruction-v1/`: deterministic reconstruction. `analysis.json`,
  SVG, CSV, annotations, and the 401-file payload inventory reproduce byte-for-byte.

Qualification and reconstruction manifest SHA-256 are identical:
`ec12ea42ce25401bb871d5b847eb999d0bf9d2b1e7ade84d2db78294bc6ec73d`.
The derived analysis SHA-256 is
`888d8f9f91bcf0b7c31d4bb66d13c082db59373379bb91231100eedb191a84e1`;
the SVG SHA-256 is
`10273dfb364dbc1820c2ccc7a019b32f1ea5d9a1ee55cad783e97821fe4e5a99`.
Fresh verification completed with 13/13 experiment tests and 645/645 full
repository tests passing.

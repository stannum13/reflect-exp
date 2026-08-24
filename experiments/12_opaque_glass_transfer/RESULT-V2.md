# Opaque-to-glass transfer V2: validity-repaired result

**Disposition:** `SUPPORTS_SYNTHETIC_RENDERED_GEOMETRY_TRANSFER`.
Simulation-only indicative evidence; no real-world glass or hierarchy-superiority
claim. Frozen source commit: `a50520959680a3be8959420e3df38bc0ffdc68fa`.

## Why V2 exists

V1 is retained byte-for-byte but is `INVALID_REJECTED`: it rendered the evaluation
appearance in pre-freeze tests, mixed pre-step contacts with post-step state,
trusted controller aggregates in scoring, and copied rather than independently
re-derived much of reconstruction. `V1_INVALID_REJECTED.json` is its disposition.

V2 uses fresh calibration seeds 4201--4204, held-out seeds 6201--6212, and material
namespace `xfer-material-v2-blue-a006`. Pre-freeze tests/calibration rendered only
no-obstacle and opaque scenes. The evaluation material was first constructed only
after source/config/tests were committed.

## Situation, objective, and method

The objective was to isolate appearance transfer: within every held-out seed,
obstacle physics, pose, camera, robot and goal are identical between opaque and
glass-like scenes; only object RGBA changes. Three frozen controllers operate on
actual 96x96 MuJoCo renders: opaque-calibrated RGB-only, RGB-D geometric motion,
and the same geometric observation separated into semantic, motion and control
interfaces.

Each of 108 episodes retains its XML and scene contract, RGB/depth NPY arrays and
PNG, applied command, aligned post-step qpos/qvel, geom IDs and normal contact
forces, detection/recovery receipt, and per-tick XML/render/world/material hashes.
An independent scorer reruns the detector from arrays, loads truth from XML,
physically replays every command, checks every state/contact/force, and derives
detection, collision, safety and completion without controller aggregate labels.

## Outcome

| Condition | Controller | Correct detection | Collision-free | Safe completion | Mean path (m) | Mean ticks |
|---|---:|---:|---:|---:|---:|---:|
| No obstacle | RGB only | 12/12 | 12/12 | 12/12 | 2.299 | 134 |
| No obstacle | RGB-D motion | 12/12 | 12/12 | 12/12 | 2.299 | 134 |
| No obstacle | Hierarchical | 12/12 | 12/12 | 12/12 | 2.299 | 134 |
| Opaque | RGB only | 12/12 | 12/12 | 12/12 | 2.565 | 274 |
| Opaque | RGB-D motion | 12/12 | 12/12 | 12/12 | 2.565 | 274 |
| Opaque | Hierarchical | 12/12 | 12/12 | 12/12 | 2.565 | 274 |
| Glass-like evaluation | RGB only | 0/12 | 0/12 | 0/12 | 1.065 | 300 |
| Glass-like evaluation | RGB-D motion | 12/12 | 12/12 | 12/12 | 2.565 | 274 |
| Glass-like evaluation | Hierarchical | 12/12 | 12/12 | 12/12 | 2.565 | 274 |

RGB-only's paired evaluation-minus-opaque detection and safe-completion changes
are both -1.00 (10,000-draw paired bootstrap 95% interval [-1.00, -1.00], effective
n=12). RGB-D motion and hierarchical transfer changes are 0.00 [0.00, 0.00]. Each
stronger controller improves evaluation safe completion over RGB-only by +1.00
[1.00, 1.00], effective n=12. RGB-only accumulated 3,199 independently replayed
obstacle-contact ticks; both stronger controllers accumulated zero.

The intervals are deterministic descriptions of this frozen synthetic matrix, not
population-certainty statements.

## Working and nonworking raw samples

The preregistered rule selects the lowest seed in each class.

- Nonworking seed 6201, RGB-only: no detection, 265 contact ticks, final goal error
  1.320 m, timeout at 300 ticks. Tick-ledger SHA-256:
  `971c785fce24023af579ddf0aadfbb66fb396a3b9ad49c5add9a9acf11d37ca4`.
- Working seed 6201, hierarchical: depth localization error 0.0120 m, zero contact,
  final error 0.0985 m in 274 ticks. No recovery was needed. Tick-ledger SHA-256:
  `7d3fb5bc7bb5090f459010e8094343d5b6e9faa424a0109478731d47b7f12db4`.

The shared evaluation render hashes are PNG
`3da4f5fec4d4a97cc54c64610c427d2ff0a5548aa21b4da227c608c3c454eec0`,
RGB NPY `12f471c3903fd3fb9d95258c144e4d6e74ec54038f7cbe3fa9a6449d3d875a00`,
and depth NPY `882bbc60f508e61a082c1634c6f09a2e3e062cfeb26146557a53a1df1697fa6d`.

## Inference and boundary

V2 supports the narrow inference that, in this MuJoCo task, separating rendered
depth geometry from opaque-color semantics prevents a total appearance-transfer
failure. It does not show the hierarchy is better than RGB-D motion: both produce
identical paths and outcomes because correct initial geometry means no recovery
loop fires. Testing the three recovery levels requires a separately preregistered
post-plan mutation experiment.

The glass-like renderer is not a physical glass sensor model. Refraction, glare,
stereo/ToF dropout, camera noise and domain shift are absent, so real-world glass
performance remains wholly untested.

## Reconstruction and evidence

The qualification inventory has 659 recursive entries: 510 files and 149
directories. Reconstruction copied raw plus closure only, physically validated it,
then independently rebuilt 108 score files, CSV, all 10,000-draw paired contrasts,
analysis, SVG and frozen samples. All 112 derived-file hashes match byte-for-byte;
qualification and reconstruction inventory SHA-256 both equal
`e66c6b006de8a28f27c52258ba92f6cc613b6567abafbff28ca44542818c075f`.

Key derived hashes:

- analysis JSON: `4238143ec639515bedbf8cdb9cb2fc654384969f01b59e65d227683de87ed2ef`
- SVG graph: `5b65517e2b3493a0dce9b98c86a6eb0f9686b0b92d411c90f83e93d2319314a4`
- episode CSV: `ae4b0ac074e1cbddf98f90d854c9e192b141c05cd0f1afa4619cceca58f207fa`
- annotated samples: `3808c817a51a4d27ae44d33bbec05fe0dcace6473a1d70c751241cea51af953d`

All raw and derived members are under `results/qualification-v2`; the exact raw-only
reconstruction is under `results/reconstruction-v2`.

Fresh verification: 21/21 combined V1/V2 experiment tests passed, Ruff reported no
findings, and the repository suite passed 645/645 tests.

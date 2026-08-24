# Opaque-to-glass transfer V3: authoritative result

**Disposition:** `SUPPORTS_SYNTHETIC_RENDERED_GEOMETRY_TRANSFER` only. V1/V2 are
byte-preserved `INVALID_REJECTED`. Frozen V3 source: `f0bd0ca`.

## Experiment

Twelve new held-out seeds (7201--7212) each generated matched no-obstacle, opaque,
and glass-like MuJoCo scenes. Physics, camera, robot, target and obstacle geometry
are identical within a seed; only authenticated XML material RGBA differs. Three
frozen controllers used actual 96x96 RGB/depth renders: opaque-calibrated RGB-only,
RGB-D motion, and a separated semantic/motion/control path using the same geometry.

V3 scoring trusts commands plus authenticated XML, not stored outcomes. It
independently rerenders RGB/depth/PNG, derives condition/material/target from XML,
reconstructs controller ID/path/config and detector decisions, replays every command
in MuJoCo, and computes collision/completion/path only from replayed state, geom IDs
and contact forces. Stored state/contact/detection fields are checked receipts.

## Outcome

| Condition | Controller | Detection | Collision-free | Safe completion | Mean path m | Mean ticks |
|---|---:|---:|---:|---:|---:|---:|
| No obstacle | RGB only | 12/12 | 12/12 | 12/12 | 2.298 | 134.0 |
| No obstacle | RGB-D motion | 12/12 | 12/12 | 12/12 | 2.298 | 134.0 |
| No obstacle | Hierarchical | 12/12 | 12/12 | 12/12 | 2.298 | 134.0 |
| Opaque | RGB only | 12/12 | 12/12 | 12/12 | 2.561 | 273.6 |
| Opaque | RGB-D motion | 12/12 | 12/12 | 12/12 | 2.561 | 273.8 |
| Opaque | Hierarchical | 12/12 | 12/12 | 12/12 | 2.561 | 273.8 |
| Glass-like | RGB only | 0/12 | 0/12 | 0/12 | 1.047 | 300.0 |
| Glass-like | RGB-D motion | 12/12 | 12/12 | 12/12 | 2.561 | 273.8 |
| Glass-like | Hierarchical | 12/12 | 12/12 | 12/12 | 2.561 | 273.8 |

RGB-only evaluation-minus-opaque detection and safe-completion changes are -1.00,
10,000-draw paired bootstrap 95% interval [-1.00, -1.00], effective n=12. Both
geometry-aware controllers have zero transfer drop [0.00, 0.00] and +1.00 [1.00,
1.00] safe completion versus RGB-only. RGB-only accumulated 3,205 replay-derived
contact ticks; the stronger variants accumulated zero.

These exact deterministic intervals characterize only this frozen synthetic matrix.

## Samples

- Nonworking seed 7201 RGB-only: no detection, 268 contact ticks, final error
  1.421 m, 300-tick timeout. Ledger SHA-256:
  `8f66c8bd0576ca8ea03319e5dc62884cf5ebe81b0705ebb56f3ac7a5c1342b6a`.
- Working seed 7201 hierarchy: localization error 0.0113 m, zero contact, final
  error 0.0997 m in 273 ticks. Ledger SHA-256:
  `a0dceebb1208d3f6656878a74ff0c46382269e3f519d1fac4a74559b888ec655`.

The shared render hashes are PNG
`df054c61b2435254e39303471b6ca88fa867cc3ac2da138dfe4bcac83129e579`,
RGB NPY `85db23ea6c5d9b8871fddc4bee5057c250e84d5a9693ceb2f8e211e8df8fcc4f`,
and depth NPY `c8333516776d7e38cc880a4f98bc256688df3dc7526fb6d9b998f2dc98ed48a1`.

## Inference

The result supports separating rendered depth geometry from appearance-bound RGB
semantics in this toy MuJoCo task. It does not establish hierarchy superiority:
RGB-D motion and hierarchy remain identical because no post-plan recovery event was
present. It does not establish physical glass perception; refraction, glare, sensor
dropout/noise and real-world domain shift are absent.

## Evidence

Qualification and raw-only reconstruction each contain an exact 661-entry manifest
(512 files, 149 directories). All 114 independently rebuilt derived files match:
108 scores, CSV, 10,000-draw contrasts, analysis, SVG, PNG graph, samples, and
reconstructed report. Both manifest SHA-256 values are
`36694e7c6fd20397e05a8e50a7f120e8e2494671366e6e6719f76e5fa0170497`.

- analysis: `1a1679fd76e3c27bb2d8c65550c1fe4b2815cbfeb7303dbe444a0b6137c747eb`
- CSV: `8eb89d6d9a3bffda2afc683644c38d8d12c155be7e4b082521a5166ca104b0a2`
- SVG: `3ed7855e508f671b6d37741ddcd8b1a499d3e872447a27c3073ed6f4dc9e2761`
- PNG graph: `b12bbca85634c770ca0d58b066ceb4112ce4f15c33ad30b8604811ece46eeff6`
- samples: `0dd172fdecfe71a64dac4a0c069e18b5948d607e6ca240eae9f5f8f4b8a882d6`
- reconstructed report: `0fd23024f12033b091766dd7e0ecca0511b13447bfc9704c51faed649d7de55d`

Fresh verification passed 31/31 combined experiment tests, 645/645 repository
tests, and Ruff with no findings.

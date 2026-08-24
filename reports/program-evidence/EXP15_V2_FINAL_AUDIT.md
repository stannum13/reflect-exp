# Exp15 V2 final evidence audit

Date: 2026-08-24  
Evidence HEAD: `b7005915f3b1bb00979ec41b997d3859d78927ec`  
Portable pack: `reports/evidence/exp15-direct-hierarchy-replication-v2`  
Pack-manifest SHA-256: `64b4f40891a7a9c82c4734faa59a926236c2b09d8b2aa7fb160f677bd4e24953`

## Verdict

**APPROVE as an authenticated, closed, reconstructable evidence archive.**
The experiment's controlling scientific disposition remains
`INVALID_EXPERIMENT` because three frozen P4/R3 sensitivity cells ended in
`INVALID_EXECUTION`. No confirmatory, causal-lowest, VLA, or physical-transfer
claim is approved. Descriptive use is approved only with that label.

Independent review found zero Critical findings. The one Important publication
caveat is semantic: the frozen `architecture-summary.csv` column named
`safety_rate` is the mean of `safety_composite`, where `true` means that at
least one violation occurred. It must therefore be described as
**safety-violation rate**. A value of `0.0` means zero observed violation rate;
R3's `0.008547` means one violation-bearing episode among 117 complete primary
episodes. The immutable pack is not rewritten to rename the column.

Standalone graphs have no numeric y-axis ticks or invalid-experiment watermark.
They must travel with `derived/REPORT.md`, `derived/graphs/plot-data.csv`, and
this audit note. Exact values, SVG geometry, PNG bytes, and style metadata are
preserved for later restyling.

## Authenticated scope

- Linear lifecycle: source `a158805` -> independent source approval `f28b418`
  -> freeze `97e6277` -> full preflight `edcb9a3` -> first-50 checkpoint
  `fa154fc` -> independent continuation approval `9ed3793` -> two-constant
  ministerial binding `1c21964` -> portable pack `b700591`.
- Portable closure: 1,134 files; 1,133 non-self manifest entries; 28,877,602
  bytes.
- Local raw root: 13,640 files total; exact inventory of 13,639 non-inventory
  files over 2,043,679,978 bytes; inventory SHA-256
  `4fde2c0d4a6b1f7660870dd64316f67e4a371eb98dfc428a410c0d89aad8fa24`.
- Matrix: 540 dispositions = 523 `COMPLETE` + 14 preregistered `NOT_RUN` +
  3 `INVALID_EXECUTION`; all 523 manifests and their member hashes validated.
- Reconstruction: all tables, seed-cluster inputs, 10,000 bootstrap draws,
  graph data/style, four SVGs, and four PNGs reproduce byte-for-byte.
- Attack tests cover rehashed disposition/raw substitution, extra/missing files,
  symlinks, schema downgrade/injection, annotation swaps, freeze substitution,
  and preflight removal. Full suite: 30 passed; Ruff and diff checks passed.

## Directional result, not confirmation

Primary P6 complete-cell summaries:

| Architecture | n | Success | Safety-violation rate | Mean progress | Mean wakes |
|---|---:|---:|---:|---:|---:|
| R0 | 117 | 0.31624 | 0.00000 | 0.36943 | 1.68376 |
| R1 | 117 | 0.74359 | 0.00000 | 0.75375 | 0.91453 |
| R2 | 117 | 1.00000 | 0.00000 | 0.999998 | 1.79487 |
| R3 | 117 | 0.99145 | 0.008547 | 0.992575 | 1.11966 |

Equal-seed R3-minus-R2 effects, 10 seed clusters and 10,000 registered draws:

- success `-0.00909`, 95% interval `[-0.02727, 0]`;
- progress `-0.007895`, `[-0.023685, +0.000000074]`;
- safety-violation rate `+0.00909`, `[0, +0.02727]`;
- total wakes `-0.67576`, `[-0.69394, -0.66061]`.

The worst R3 family/severity cell was high motion-path-infeasible, with 9/10
success. P4-minus-P6 R3 sensitivity was substantially negative for success
(`-0.28848`, `[-0.33939,-0.24121]`) and progress (`-0.26217`,
`[-0.29529,-0.22647]`), but its frozen matrix contains the three invalid route
exceptions. These numbers are strong directional evidence for the P6 hierarchy
and controller sensitivity, not a valid replication claim.

The invalids expose a bounded runtime boundary: preflight finds a waypoint from
the initial pose, while a later motion retry replans from a changed live pose
and can raise `no frozen waypoint route`. A fresh experiment must preregister
that condition as a motion-plan-unavailable safe abort and scored task failure;
unrelated exceptions must remain invalid.

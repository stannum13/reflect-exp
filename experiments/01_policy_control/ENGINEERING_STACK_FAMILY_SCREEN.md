# Experiment 01 low-gain stack-family screen

Status: `PRELIMINARY_NONCONFIRMATORY_ENGINEERING_STACK_FAMILY_SCREEN`.
This two-fresh-seed run is a bounded architecture screen, not pilot evidence.

## Outcome

Common low-gain/high-slew tuning does not rescue the richer stacks. P2, P3,
and P4 recovered 0/10 displacement events in every tested gain/slew regime.
P3 and P4 avoided saturation and clamp entirely, isolating recovery/tracking
as their failure. P2 also remained clamp-limited.

P6 was the strongest richer-stack negative: at 5/.5 it recovered 5/10 events
at either slew with zero saturation, but every rollout exceeded the clamp
ceiling. At 7.5/.75 it regressed to 3/10 recovery and revived saturation.
P1 preserved 10/10 recovery but remained clamp-limited. Only the P5 positive
control produced absolute successes: 2/6 at 5/.5 for each slew.

This rejects shared PD/slew tuning as a fair final comparison of P2/P3/P4/P6.
The next discriminator must vary architecture-specific trajectory, IK, and
residual-authority parameters.

## All aggregate cells

Each row is six rollouts over three conditions and seeds 20260841/42.

| Stack | Gain | Slew | Working | Recovered | Saturation | Clamp | p95 error m |
|---|---:|---:|---:|---:|---:|---:|---:|
| P1 | 5/.5 | 3 | 0/6 | 10/10 | 0.000000 | 0.090987 | 0.052571 |
| P1 | 5/.5 | 6 | 0/6 | 10/10 | 0.000000 | 0.039147 | 0.046624 |
| P1 | 7.5/.75 | 3 | 0/6 | 10/10 | 0.206560 | 0.123467 | 0.052557 |
| P1 | 7.5/.75 | 6 | 0/6 | 10/10 | 0.210613 | 0.054667 | 0.046088 |
| P2 | 5/.5 | 3 | 0/6 | 0/10 | 0.000000 | 0.101387 | 0.097216 |
| P2 | 5/.5 | 6 | 0/6 | 0/10 | 0.000000 | 0.050933 | 0.098109 |
| P2 | 7.5/.75 | 3 | 0/6 | 0/10 | 0.000000 | 0.099520 | 0.096888 |
| P2 | 7.5/.75 | 6 | 0/6 | 0/10 | 0.000000 | 0.049867 | 0.097762 |
| P3 | 5/.5 | 3 | 0/6 | 0/10 | 0.000000 | 0.000000 | 0.113314 |
| P3 | 5/.5 | 6 | 0/6 | 0/10 | 0.000000 | 0.000000 | 0.113314 |
| P3 | 7.5/.75 | 3 | 0/6 | 0/10 | 0.000000 | 0.000000 | 0.112828 |
| P3 | 7.5/.75 | 6 | 0/6 | 0/10 | 0.000000 | 0.000000 | 0.112828 |
| P4 | 5/.5 | 3 | 0/6 | 0/10 | 0.000000 | 0.000000 | 0.120440 |
| P4 | 5/.5 | 6 | 0/6 | 0/10 | 0.000000 | 0.000000 | 0.120440 |
| P4 | 7.5/.75 | 3 | 0/6 | 0/10 | 0.000000 | 0.000000 | 0.120387 |
| P4 | 7.5/.75 | 6 | 0/6 | 0/10 | 0.000000 | 0.000000 | 0.120387 |
| P5 | 5/.5 | 3 | 2/6 | 2/10 | 0.000000 | 0.007413 | 0.077661 |
| P5 | 5/.5 | 6 | 2/6 | 2/10 | 0.000000 | 0.002987 | 0.077608 |
| P5 | 7.5/.75 | 3 | 0/6 | 0/10 | 0.028907 | 0.016747 | 0.078570 |
| P5 | 7.5/.75 | 6 | 0/6 | 0/10 | 0.029387 | 0.006613 | 0.078455 |
| P6 | 5/.5 | 3 | 0/6 | 5/10 | 0.000000 | 0.081867 | 0.058139 |
| P6 | 5/.5 | 6 | 0/6 | 5/10 | 0.000000 | 0.034880 | 0.055761 |
| P6 | 7.5/.75 | 3 | 0/6 | 3/10 | 0.209387 | 0.122667 | 0.058463 |
| P6 | 7.5/.75 | 6 | 0/6 | 3/10 | 0.212427 | 0.054133 | 0.055791 |

No rollout was unsafe. Every row's exact condition/seed identity and closed
failure list is retained in the raw summary.

## Evidence identity

- Factorial: P1–P6 × gains `(5,.5)`, `(7.5,.75)` × slew `3`, `6`.
- Conditions: `core-20-000-1`, `core-10-300-2`, `core-05-700-2`.
- Fresh seeds: `20260841`, `20260842`.
- Execution Git SHA: `bc7cd6e1f3453011a2bfb49f0a43b207bfa75462`.
- Runtime-code-ledger SHA-256: `a9c799754f9241aa175e1c0da1ae21e8ed395b3e2ecdc13558efa599621a537f`.
- Probe script SHA-256: `67f72957b30d7d443f298c153a99ff9be8b3b0a824ad27882aea6cb31760f949`.
- Canonical summary: 64,926,993 bytes, SHA-256
  `17edc4d52c54c6872f76a596c3687bcebe43b1997807bc30a0e7da55841d4274`.
- Full bundles: 144 directories, 1,008 files, 240,612,368 bytes.
- Complete ignored evidence: 1,010 files, 305,552,221 bytes. Canonical
  path/bytes/file-hash inventory SHA-256:
  `d06a52658714759b401fa7c85759dc123a7c45c649041908983aeb10da32db6c`.

Ignored raw evidence is at
`experiments/01_policy_control/results/engineering-stack-family-screen/`.
It retains every full 500 Hz bundle, exact file/configuration/scenario/source
hash, 144 valid attempts, working/nonworking annotations, and plot-ready raw
metrics. There were no invalid runtime attempts.

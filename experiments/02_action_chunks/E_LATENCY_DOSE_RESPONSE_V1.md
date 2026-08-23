# E Latency Dose-Response Qualification V1

This is deterministic timing-contract qualification, not MuJoCo or policy-performance evidence. It does not alter the frozen core latency set `{25,75,150}` or authorize runtime use.

The run evaluated E's exact `latency_ticks` versus `J_E` relation for `v0=25`, `v1=75`, and `v2=124` over fresh qualification seeds 100 through 115. Boundary-near ticks were included only to locate the transition.

## Result

The transition was exact and seed-stable in all 304 scheduled rows:

| vector | below lead | at lead | above lead | hold at 150 ticks |
|---|---:|---:|---:|---:|
| v0 (`J_E=25`) | 24: `STRICT_OVERLAP` | 25: `EXPIRY_HANDOFF` | 26: `UNAVOIDABLE_HOLD` (1 tick) | 125 ticks |
| v1 (`J_E=75`) | 74: `STRICT_OVERLAP` | 75: `EXPIRY_HANDOFF` | 76: `UNAVOIDABLE_HOLD` (1 tick) | 75 ticks |
| v2 (`J_E=124`) | 123: `STRICT_OVERLAP` | 124: `EXPIRY_HANDOFF` | 125: `UNAVOIDABLE_HOLD` (1 tick) | 26 ticks |

Aggregate dispositions were 128 `WORKING` and 176 `NONWORKING`: 80 strict-overlap, 48 expiry-handoff, and 176 unavoidable-hold rows. Here `NONWORKING` means the prefetch-continuity property was not met; it is not missing evidence and makes no dynamics claim.

## Evidence identities

- raw trials SHA-256: `96e868191438bde2580c359d932598997cd7eb0724f62ade1969b87fbea7caab`
- raw manifest SHA-256: `c9f6f29d014731a2743ebd6c1be2ecb0adbd83e40341088cb370f38459b5cfc2`
- derived summary SHA-256: `567307579145e0ac9df0980602e75d3a99309008fdf24233716ec3e23837d6b5`
- transition implementation commit: `a854ec8`

The next empirical question is intentionally separate: the real Task 3 broker must demonstrate that unavoidable-hold cells emit exactly one safe-hold transition, execute the predicted hold duration, and finish terminal-empty.

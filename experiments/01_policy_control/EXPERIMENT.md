# Experiment protocol

## Design

- Six stacks: P1–P6, with P1 as the irreplaceable anchor.
- Deterministic MuJoCo 3.12.0 planar arm at 500 Hz.
- Policy rates 5/10/20 Hz, latencies 0/100/300/700 ms, one/two target moves.
- One dropped-response probe, one out-of-order probe, and one stationary negative
  control.
- Immutable scenario proposal ledgers and paired scenario identities across stacks.

## Pilot

The base vector is PD `(80, 8)`, IK `0.01`, and P5 smoothness `0.02`. Two additional
PD candidates are evaluated globally, followed by two additional global IK
candidates and two P5-only smoothness candidates. Selected baseline evidence is
reused by hash and never rerun. The final four seeds run all 24 core conditions and
two probes exactly once and cannot tune parameters.

## Confirmation and inference

Confirmation uses 32 new paired seeds. Five paired contrasts use 10,000 PCG64
bootstrap resamples and Bonferroni-adjusted 99% percentile intervals. Absolute gates
pool their declared event or tick denominators. Jerk and discontinuity use an
episode-p95 then nearest-rank-p95 calculation, bounded by `1.5x` the frozen P1 pilot
baseline.

## Evidence fidelity and resources

Every trial has a disposition: success, scientific failure, timeout, crash,
excluded, or missing. Raw 500 Hz rows are immutable and reconstructable. Annotated
working/nonworking sample selection is deterministic and preregistered. Each rollout
has a 2 MiB hard cap; the measured canonical sample is 1,644,875 bytes. The complete
lifecycle reservation is 14,576 MiB, below the configured 50 GiB ceiling. Evidence
is never truncated to meet a budget.

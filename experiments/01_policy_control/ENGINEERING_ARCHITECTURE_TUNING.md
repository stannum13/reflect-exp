# Experiment 01 architecture-specific tuning discriminator

Status: `PRELIMINARY_NONCONFIRMATORY_ENGINEERING_ARCHITECTURE_TUNING`.

## Outcome

Architecture-specific tuning rescued event recovery for P2 and P6, but not
absolute success. P2 horizons 0.1 and 0.2 s both recovered 10/10 events with
zero saturation; mean clamp remained 0.069120 and 0.065280. P6 residual
bounds .5 and .75 rad likewise recovered 10/10 with zero saturation and mean
clamp 0.034507. Their metrics are identical, showing .75 lies above the
active residual demand and adds no authority.

Moderate/aggressive P3 local IK recovered only 2/10; aggressive P4 recovered
2/10 at horizon .1 and 1/10 at .2. These negatives indict this implementation,
not Cartesian control generally: its executor applies only a 2 ms q-reference
lead with zero `dq_ref`, strongly limiting proportional torque even when the
IK speed/gain limits rise. P5 control recovered 7/10 and passed 3/6.

The next high-information test is actuation admissibility: raise reference
slew for the recovered P2/P6 regimes and test whether clamp falls below .01
without reviving torque saturation.

## Results

Each row is six rollouts over three conditions and fresh seeds 20260843/44.

| Variant | Working | Recovered | Saturation | Clamp | p95 error m | Failure |
|---|---:|---:|---:|---:|---:|---|
| P2 horizon .1 s | 0/6 | 10/10 | 0.000000 | 0.069120 | 0.059488 | clamp 6 |
| P2 horizon .2 s | 0/6 | 10/10 | 0.000000 | 0.065280 | 0.066147 | clamp 6 |
| P3 moderate local IK | 0/6 | 2/10 | 0.000000 | 0.000000 | 0.099429 | recovery 6 |
| P3 aggressive local IK | 0/6 | 2/10 | 0.000000 | 0.000000 | 0.094698 | recovery 6 |
| P4 horizon .1 + aggressive IK | 0/6 | 2/10 | 0.000000 | 0.000000 | 0.102327 | recovery 6 |
| P4 horizon .2 + aggressive IK | 0/6 | 1/10 | 0.000000 | 0.000000 | 0.104914 | recovery 6 |
| P6 residual .5 rad | 0/6 | 10/10 | 0.000000 | 0.034507 | 0.047765 | clamp 6 |
| P6 residual .75 rad | 0/6 | 10/10 | 0.000000 | 0.034507 | 0.047765 | clamp 6 |
| P5 5/.5 slew6 control | 3/6 | 7/10 | 0.000000 | 0.002400 | 0.073531 | recovery 3 |

The P2 horizon .1 result is especially diagnostic: the earlier .8 s horizon
reset produced 0/10 recovery, while .1 s produces 10/10. On the earlier
seed41 fast cell, P2's mean post-displacement `||q_ref-q||` was 0.0110 rad
and it moved 0.413 rad after 2 s; its final 0.0323 m error narrowly missed the
0.025 m threshold. Shorter trajectory timing closes recovery here, leaving
reference clamp as the isolated blocker.

P6's earlier .25-rad action bound was hit repeatedly (94 component-times at
10 Hz/300 ms and 36 at 5 Hz/700 ms). Raising it to .5 restores 10/10 recovery;
.75 is inactive above that. Nominal duration was deliberately not varied
because displacement begins at 2 s and both proposed durations were already
terminal. The unused `controller.residual_limit_rad` field was also excluded.

## Exact tuning matrix

- Common setting: PD 5/.5, reference slew 6 rad/s, P5 smoothness .02.
- P2: `chunk_horizon_s` .1 and .2.
- P3 moderate: damping .001, gain 8, speed .5 m/s, qdot 3 rad/s, null .1.
- P3 aggressive: damping .001, gain 12, speed 1 m/s, qdot 4 rad/s, null .1.
- P4: horizons .1/.2 with the aggressive P3 local controller.
- P6: residual component bounds .5/.75 rad, nominal duration fixed 1 s.
- P5: unchanged positive control.

## Evidence identity

- Execution Git SHA: `1244d0a56493eddd4c4e352ff8e67f6c416d3d71`.
- Runtime-code-ledger SHA-256: `a9c799754f9241aa175e1c0da1ae21e8ed395b3e2ecdc13558efa599621a537f`.
- Probe script SHA-256: `c90c997172a7e9273addb457670ea28837d0fd774524854d76f98112cea12476`.
- Canonical summary: 24,380,911 bytes, SHA-256
  `2d87445864c7942eca32d25b04b38f7af547112abc0a9fce58d7e4b565c59e08`.
- Full bundles: 54 directories, 378 files, 90,271,991 bytes.
- Complete ignored evidence: 380 files, 114,666,153 bytes. Canonical inventory
  SHA-256: `8042a458e6bc52d917a2bb5eb65e15f56f05fc9f4150e7ee623ffd3b29a64e94`.

Ignored raw evidence is at
`experiments/01_policy_control/results/engineering-architecture-tuning/`.
It retains every full 500 Hz bundle, exact configuration/knob/scenario/source
and file hashes, all working/nonworking annotations, and zero invalid attempts.

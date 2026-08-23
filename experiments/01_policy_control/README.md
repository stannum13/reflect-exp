# Experiment 01: Policy-to-control boundary

This simulation-only experiment compares six command stacks (P1–P6) under one
frozen planar-arm task, paired scenarios, bounded timing faults, and shared safety
and artifact contracts. It does not authorize physical deployment.

The public runner is `python -m experiments.01_policy_control.run`. Every evidence
command requires the fail-closed P3 gate, `--headless`, an immutable manifest, and
an explicit shard. `make exp01 SHARD=<id>` runs one reviewed three-episode pilot
base shard; omitting `SHARD` exits before Python starts.

Pilot selection uses four tuning seeds and four untouched final-four seeds. The
global PD and IK choices apply to every surviving stack; only P5 has a separate
smoothness scalar. Confirmation is generated only after pilot evidence is frozen
at a clean Git commit.

Raw evidence is retained per episode at 500 Hz. Reports additionally publish a
deterministic annotated sample index containing working and nonworking cases per
condition when observed, or `CLASS_NOT_OBSERVED` with its denominator. Plot recipe
metadata binds source hashes, transforms, axes, units, frames, versions, and seeds,
and clean-directory reconstruction must reproduce every SVG byte.

See [CLAIM.md](CLAIM.md), [EXPERIMENT.md](EXPERIMENT.md), and the reviewed result
placeholders in [RESULTS.md](RESULTS.md) and
[INTERFACE_FINDINGS.md](INTERFACE_FINDINGS.md).

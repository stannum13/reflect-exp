# Claim boundary

Experiment 01 tests whether any of five non-anchor command stacks improves
simulated recovery time relative to P1 while meeting preregistered recovery,
safety, clamp, saturation, jerk, and discontinuity gates.

The unit of promotion is a complete command-stack configuration, not an abstract
wire enum. At most two stacks may be promoted. Shared wire values are deduplicated
only when handed to the next experiment.

Allowed conclusions are `SUPPORTED`, `NOT_SUPPORTED`, or `INCONCLUSIVE` under the
frozen decision rules. Results apply only to the reviewed MuJoCo planar-arm task,
timing grid, seeds, and implementation SHA. They do not establish physical robot
performance, general manipulation capability, or deployment safety.

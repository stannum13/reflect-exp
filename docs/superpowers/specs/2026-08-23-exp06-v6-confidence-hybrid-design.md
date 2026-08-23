# Experiment 06 v6 Confidence-Hybrid Design

## Goal

Run one engineering-only model-quality cycle on an entirely new deterministic
train/tune/evaluation namespace. Evaluate whether a truth-free confidence gate
can improve over W1V2, W3R, W0, and DIRECT without evaluation retuning.

## Frozen domain

All scene IDs begin `exp06-v6/` and all seeds use the salt
`scene-v6-cycle`. The exact split is 72 ID training scenes, 24 ID tuning
scenes, and 48 evaluation scenes: 16 ID plus 8 each MASS_OOD, FRICTION_OOD,
GEOMETRY_OOD, and OBSTACLE_OOD. Every `(scene_id, seed)` must be disjoint from
all v3-v5 train, tuning, and evaluation rows. Each scene retains two anchors
and eight byte-distinct candidates, for 2,304 replayed branches.

## Models and W5

Retain DIRECT, deterministic W0, truth-free W1V2, W3R, W4R, and oracle W2.
Fit W3R and W4R only on the 72 training scenes. Select the residual family only
on the 24 tuning scenes. W5 makes one anchor-level choice between the selected
residual family and W1V2.

For each anchor, compute a truth-free confidence score from:

1. maximum training-standardized RMS feature distance over its eight candidates;
2. maximum normalized residual-ensemble disagreement;
3. Spearman rank disagreement between W3R and W4R predictions; and
4. inverse nominal contact/geometry margin from ordinary state and action inputs.

Each component is finite and nonnegative. The score is their arithmetic mean.
Training feature means/scales and the training median absolute residual provide
normalization. The only threshold candidates are the empirical tuning-score
quantiles `q=(0.25, 0.50, 0.75)`. A threshold is eligible only when residual use
on tuning is within `[0.25, 0.75]`. Select the eligible threshold with minimum
tuning regret, breaking ties by lower quantile then lower numeric threshold.
W5 uses the selected residual when `score <= threshold`, otherwise W1V2.

## Gate and evidence

The evaluation gate passes only if W5 has strictly lower overall mean regret
than W1V2, W3R, W0, and DIRECT; beats all four within at least four of five
strata; has evaluation residual-use coverage in `[0.10, 0.90]`; observes all
five strata; and has measured full-K=8 anchor p95 latency at most 5 ms. Any
failed check means no authority.

Raw evidence retains the calibration receipt, exact model ancestry, scenes,
anchors, candidates, actions, outcomes, attempts, and latency samples. Clean
reconstruction replays all 2,304 MuJoCo branches and reproduces models,
predictions, selections, metrics, gate, calibration, and relative working and
nonworking annotations byte-for-byte. V1-v5 remain unchanged.

## Scope

Use only the existing Python, NumPy, and MuJoCo implementation. Do not create a
general modeling framework, add dependencies, alter threshold candidates after
outcomes, or claim confirmation/deployment authority.

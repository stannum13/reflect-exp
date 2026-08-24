# Opaque-to-transparent obstacle transfer design

**Status:** autonomously approved under the Reflect Lite research run
**Classification:** preregistered engineering screen; synthetic MuJoCo only

## Question

When obstacle geometry is unchanged but its rendered appearance changes from an
opaque red material to a glass-like transparent material, does geometry-aware
perception and layered recovery transfer better than an opaque-calibrated RGB
baseline?

This can establish a causal appearance-transfer result in a small rendered
MuJoCo navigation task. It cannot establish real-camera glass perception,
physical-robot safety, or broad semantic reasoning.

## Scene and intervention

A two-slide point robot moves from the left to a goal on the right in a bounded
tabletop corridor. A fixed overhead camera renders 96x96 RGB and metric depth.
Matched seed triplets share start, goal, lighting, camera, obstacle pose and
dimensions. Conditions are `NO_OBSTACLE`, `OPAQUE`, and `TRANSPARENT`; the only
opaque/transparent XML difference is obstacle RGBA. The transparent alpha is
0.08. Physics geometry, contacts, mass, friction and controller seeds remain
identical.

Each episode saves the initial RGB PNG, raw RGB/depth NPY arrays, XML, scene JSON,
detector result, planned waypoints, 50 Hz tick ledger, commands, contacts and the
independent terminal score.

## Frozen controllers

All thresholds are selected using calibration seeds 4101--4104 in opaque and
no-obstacle scenes only. Held-out seeds 5101--5112 are never used for selection.

- `RGB_ONLY`: red/saturation mask on rendered RGB. If it sees an obstacle, it
  estimates its image centroid and inserts one avoidance waypoint; otherwise it
  follows the direct path. This intentionally weak baseline represents an
  opaque-calibrated appearance detector.
- `RGBD_MOTION`: foreground depth relative to a matched empty-scene depth image,
  excluding robot pixels. It localizes geometry from pixels and inserts a
  collision-clear waypoint. A stalled/contacting trajectory gets one fresh
  depth render and motion replan.
- `HIERARCHICAL`: the same RGB-D geometry observation is stored separately from
  semantic route state. The semantic layer chooses an authorized upper/lower
  corridor, the motion layer plans/replans waypoints, and the control layer
  tracks or holds. One control retry, one motion replan, then one semantic
  alternate-route replan are allowed. Decisions use observations and traces,
  never the condition label or scorer truth.

The stronger variants are not claimed to be learned models. The experiment
tests interface/modality transfer and bounded recovery structure.

## Frozen matrix and scoring

The held-out matrix is 12 seeds x 3 conditions x 3 controllers = 108 episodes.
Execution order is deterministic and recorded; all three controllers consume
the same initial render bytes within a seed-condition pair.

An independent scorer reads MuJoCo contact records and state traces, not
controller completion fields. Detection is correct when presence matches truth
and localization error is <=0.12 m. Task completion requires final goal distance
<=0.10 m within 300 ticks. Safety requires zero obstacle contacts and corridor
containment. Secondary measures are replans, retries, semantic wakes, latency,
path length and tick count.

Primary contrasts use complete paired seeds:

1. transparent-minus-opaque success and detection transfer drop per controller;
2. stronger-minus-RGB_ONLY transparent success;
3. collision and path-cost differences on transparent scenes.

Ten-thousand-draw deterministic paired bootstrap intervals and effective paired
`n` are reported. The indicative claim is supported if both stronger controllers
have a smaller transparent detection drop than RGB_ONLY, improve transparent
safe completion, and introduce no collision increase. Hierarchical superiority
over RGB-D alone is exploratory and may be unsupported.

## Integrity and lifecycle

The preregistration, config, source and tests are committed before held-out
execution. Qualification verifies the exact matrix, disjoint seed namespaces,
source/config/environment hashes, independent scorer inputs, recursive file
inventory, no symlinks/extras, terminal dispositions and byte-exact reconstruction
of CSV/SVG/PNG derivatives. Interrupted attempts are retained outside the sealed
result and cannot enter analysis. Working and nonworking samples are selected by
frozen rules, not hand-picked after viewing outcomes.

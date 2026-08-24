# Opaque-to-glass transfer V2 validity repair

**Status:** autonomous review-repair design approved; preregistration only

V1 remains byte-preserved but is `INVALID_REJECTED`: evaluation appearance leaked
into pre-freeze tests, state/contact tick domains were misaligned, scoring trusted
controller aggregates, and reconstruction was not fully raw-derived.

V2 retains the 12 x 3 x 3 matched MuJoCo design but uses wholly new calibration
seeds 4201--4204, held-out seeds 6201--6212, and material namespace
`xfer-material-v2-blue-a006`. Before source freeze, calibration and tests may render
only no-obstacle and opaque scenes. Static guards prevent held-out seed use and
evaluation-scene construction in tests/calibration.

Every tick is logged after exactly one MuJoCo step. The row contains model and
world qpos, qvel, the command applied for that step, geom IDs and contact forces,
controller detection, recovery receipt, and hashes of XML, RGB, depth, durable
world physics, and object material. A separate scorer loads XML and arrays, replays
commands tick by tick, verifies states/contacts/forces, reruns the relevant detector,
and derives detection, collision, safety, completion, latency, path and retry metrics.
It never accepts controller success, collision, or aggregate labels.

The sealed root has exact `raw`, `derived`, closure, and recursive-inventory
contracts. Inventory covers directories and files, rejects symlinks/extras, and
checks source/config/seed/matrix closure. Reconstruction copies raw only, validates
and replays it, then rebuilds scores, CSV, paired 10,000-draw bootstrap analysis,
SVG, and frozen-rule samples. Rehashed ledger tampering is rejected by physical
replay. The outcome rule and bounded interpretation remain those preregistered in
V1; no physical or real-world glass claim follows.

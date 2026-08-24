# Opaque-to-transparent transfer implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Produce a sealed, reconstructable held-out MuJoCo appearance-transfer result.

**Architecture:** One experiment-local module owns scene generation, actual RGB/depth rendering, pixel detectors, MuJoCo control rollouts, independent scoring, paired bootstrap analysis and reconstruction. Raw evidence is immutable after the run and derived artifacts are recreated from its episode rows.

**Tech Stack:** Python 3.11, MuJoCo 3.3, NumPy 2.3, pytest 9, standard-library CSV/JSON/PNG/SVG.

## Global constraints

- Held-out seeds are exactly 5101--5112 and may not influence source/config.
- Opaque and transparent physics must be byte-equivalent at the contract level except material RGBA.
- No network, new dependency, physical execution, or real-world glass claim.
- Every episode terminates and retains RGB/depth arrays, scene, trace, commands, contacts and independent score.

### Task 1: Freeze the renderer, controllers, scorer and integrity checks

**Files:**
- Create: `experiments/12_opaque_glass_transfer/src/experiment.py`
- Create: `experiments/12_opaque_glass_transfer/tests/test_transfer.py`
- Create: `experiments/12_opaque_glass_transfer/config.json`

**Interfaces:**
- Produces `render_scene`, `detect_rgb`, `detect_depth`, `run_episode`, `score_trace`, `run`, `reconstruct`, and `verify_inventory`.

- [x] Write tests for the exact matrix, real RGB/depth rendering, matched geometry, modality transfer, actual collision recovery, scorer independence and inventory rejection.
- [x] Run `uv run pytest experiments/12_opaque_glass_transfer/tests/test_transfer.py -q` and observe the missing implementation failure.
- [x] Implement the minimal MuJoCo experiment and correct the calibration-only waypoint recovery defect.
- [x] Run the focused suite; expected `12 passed`.
- [ ] Commit config, source, tests, design and this plan before any held-out execution.

### Task 2: Execute the frozen held-out matrix

**Files:**
- Create: `experiments/12_opaque_glass_transfer/results/qualification-v1/**`

**Interfaces:**
- Consumes `run(Path)` and the frozen config/source commit.
- Produces 108 terminal episode records plus 36 shared scene bundles.

- [ ] Run `uv run python -m experiments.12_opaque_glass_transfer.src.experiment experiments/12_opaque_glass_transfer/results/qualification-v1` exactly once.
- [ ] Confirm closure reports 108 rows and `COMPLETE`; preserve any failed attempt separately rather than overwriting.
- [ ] Read aggregate cells and paired contrasts without changing source/config.

### Task 3: Reconstruct and report

**Files:**
- Create: `experiments/12_opaque_glass_transfer/results/reconstruction-v1/**`
- Create: `experiments/12_opaque_glass_transfer/RESULT.md`

**Interfaces:**
- Consumes the sealed qualification manifest and episode CSV.
- Produces byte-matching `analysis.json` and `transparent-safe-completion.svg`, annotated samples and a bounded inference.

- [ ] Call `reconstruct(qualification, reconstruction)` and compare SHA-256 of analysis/SVG artifacts.
- [ ] Run `verify_inventory` on both trees and assert no extras or symlinks.
- [ ] Run the focused experiment tests and relevant full repository tests.
- [ ] Write the report with situation, method, objective, outcomes, paired intervals, working/nonworking examples, limitations and exact artifact links.
- [ ] Commit evidence/report atomically without modifying the frozen controller or seed matrix.

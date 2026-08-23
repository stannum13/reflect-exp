# Grounded Hierarchical Recovery V2 Execution Plan

> Execute with strict red-green-refactor and freeze-before-matrix discipline. V1 evidence is immutable.

**Goal:** Run the preregistered 360-episode grounded recovery matrix with simulator/history-derived decisions, independent scoring, retained byte evidence, deterministic reconstruction, and all seven gates.

## Task 1: Supersede V1 metadata

Mark the tracked V1 report as a nonworking construct-validity sample, verify retained hashes, and commit without changing results.

## Task 2: Grounded contracts and realization generator

Write failing tests for the exact matrix, content-only command identity, guarded reset, PCG64 seed consumption, and architecture-independent feasibility. Implement only enough to pass. Commit.

## Task 3: Simulator-derived recovery execution

Write failing tests proving decisions consume history-derived observables, retry/replan advances 25 MuJoCo ticks and re-observes, obstacle paths and semantic alternatives execute, and exact action/trajectory/memory bytes are retained. Implement representative episodes and commit.

## Task 4: Independent scorer and positive controls

Write failing tests for post-episode scorer independence and nonzero unsafe, forbidden, stale, collision, invalid-action, and loop controls. Implement measured latency and authoritative terminal scoring. Commit.

## Task 5: Evidence, analysis, and pre-freeze qualification

Write failing evidence/reconstruction and seven-gate tests. Implement raw/derived manifests, graph tables/figures, paired bootstrap including Gate 6, unique-realization audit, and clean reconstruction. Run representative episodes plus positive controls. Commit and freeze source/config.

## Task 6: Frozen 360-episode run

After freeze, make no source/config edits. Execute 320 P6 plus 40 P4 episodes, analyze, audit hashes and uniqueness, reconstruct from raw evidence, and compare derived bytes. Preserve all evidence.

## Task 7: Scientific report and verification

Write the V2 scientific report and detailed execution log. Run focused tests, repository tests, source audit, manifest/hash checks, graph checks, and reconstruction. Commit reports separately.

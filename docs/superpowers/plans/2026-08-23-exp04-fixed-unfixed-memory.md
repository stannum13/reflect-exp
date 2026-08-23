# Experiment 04 Fixed-vs-Unfixed Memory Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Execute the preregistered matched fixed-versus-online memory ablation and publish replayable graph-ready evidence.

**Architecture:** One experiment-local module generates hidden worlds and observation streams, runs four memory variants without truth access, scores immutable decisions, and deterministically derives analysis. A tiny result-root reconstruction entry point invokes the same frozen replay/derivation path against authenticated raw files.

**Tech Stack:** Python 3.11 standard library, project-locked NumPy `PCG64`, pytest, canonical JSON/JSONL/CSV, deterministic SVG.

## Global Constraints

- Follow `docs/superpowers/specs/2026-08-23-exp04-fixed-unfixed-memory-preregistered.md` exactly.
- Do not inspect aggregate outcomes until implementation tests and source are committed.
- Do not modify Experiment 01, Experiment 03, or their worktrees.
- Keep the outcome claim `INDICATIVE_SYNTHETIC`, never confirmatory.

---

### Task 1: Frozen generator and memory/controller variants

**Files:**
- Create: `experiments/04_memory/src/unfixed_ablation.py`
- Create: `experiments/04_memory/tests/test_unfixed_ablation.py`

**Interfaces:**
- Produces: `generate_seed(seed) -> (observation_stream, scorer_truth)` and `run_variant(variant_id, seed, observation_stream) -> (snapshots, decisions)`.

- [ ] Write tests proving the exact 64-seed/four-variant matrix contract, runner truth isolation, equal observation streams, frozen/live update behavior, and semantic/episodic complementarity.
- [ ] Run the focused test and observe failure because the module is absent.
- [ ] Implement the minimal deterministic generator, separate stores, and shared controller.
- [ ] Run the focused and existing Experiment 04 tests.
- [ ] Commit the frozen implementation before any outcome root is created.

### Task 2: Scoring, analysis, and reconstruction

**Files:**
- Modify: `experiments/04_memory/src/unfixed_ablation.py`
- Modify: `experiments/04_memory/tests/test_unfixed_ablation.py`

**Interfaces:**
- Produces: `run_experiment(output, implementation_git_sha)` and `reconstruct(raw_root, output)`.

- [ ] Add failing tests for truth separation, raw-member tamper rejection, 20,000-draw paired bootstrap, all six frozen gates, canonical graph tables, annotated working/nonworking samples, SVGs, and byte-identical reconstruction.
- [ ] Run tests and observe the expected missing-interface failures.
- [ ] Implement canonical raw writing, replay validation, scoring, aggregation, graphs, manifest, and reconstruction.
- [ ] Run focused plus all Experiment 04 tests and commit the complete frozen source.

### Task 3: Actual outcomes and evidence seal

**Files:**
- Create: `results/exp04-unfixed-memory-indicative-v1/**`
- Create: `experiments/04_memory/UNFIXED_MEMORY_INDICATIVE_RESULT.md`

**Interfaces:**
- Consumes: committed Task 2 source SHA and Git SHA.
- Produces: raw and derived evidence specified by the preregistration.

- [ ] Run the exact 64-seed by four-variant outcome matrix once into an absent result root.
- [ ] Read the derived result only after execution is complete; copy the generated report to the experiment report path without changing scientific interpretation.
- [ ] Reconstruct into a clean temporary directory and compare every canonical derived byte.
- [ ] Validate `SHA256SUMS`, run all Experiment 04 tests, run `git diff --check`, and commit the evidence seal.

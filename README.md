# Reflect Lite Research

An experimental robotics program for answering a practical systems question: **where should reasoning, memory, motion planning, and fast control meet in an embodied agent?**

Rather than building one large end-to-end robot stack, this repository breaks the problem into small, reproducible studies. The work covers persistent world state, action-chunk execution, recovery policies, hierarchical routing, and simulator-backed evaluation. Each study records its assumptions, exact configuration, raw or derived results, and the limits of what those results support.

> Current status: the repository supports a typed, layered **synthetic reference architecture**. It does not claim a finished general-purpose robot system or physical-robot validation.

## The idea in one diagram

```text
mission or instruction
        ↓
semantic planning + persistent memory
        ↓ typed goals, constraints, and recovery decisions
skill / policy selection
        ↓ action chunks or control references
motion executor + local recovery
        ↓ bounded commands
simulator or robot controller
```

The experiments ask which information belongs at each boundary, which failures should be handled locally, and when an event should trigger a refresh, retry, replan, or safe abort.

## What is in the repository

- A Python package for typed events, rollout records, deterministic replay, safety defaults, and source provenance.
- A registry of public robotics projects with pinned revisions, license notes, and compatibility checks.
- MuJoCo-backed and pure-Python experiments covering policy-to-control interfaces, action chunks, recovery, memory, typed digital twins, world-model ranking, and hierarchical routing.
- Reconstructable result packs with manifests, hashes, analysis tables, and review records.
- More than 600 tests spanning runtime contracts, evidence integrity, replay, source auditing, and experiment-specific behavior.

The most useful starting points are:

| Area | Where to look |
| --- | --- |
| Research questions and safety envelope | [Reflect Lite Research Program.md](Reflect%20Lite%20Research%20Program.md) |
| Current findings and their limits | [Program evidence ledger](reports/program-evidence/PROGRAM_EVIDENCE_LEDGER.md) |
| Shared runtime package | [`reflect/`](reflect/) |
| Experiment implementations | [`experiments/`](experiments/) |
| Source and license registry | [`references/`](references/) |
| Test suite | [`tests/`](tests/) |

## Selected findings

The current evidence is deliberately narrow:

- Keeping live belief and episodic history separate from durable semantic and geometric state improved outcomes in controlled synthetic studies.
- Explicit refresh, retry, replan, and abort triggers were easier to test and reason about than a single undifferentiated recovery loop.
- In an appearance-shift study, geometry-aware execution transferred where an RGB-only route did not.
- A preregistered MuJoCo route-boundary replication found that a three-layer hierarchy matched the two-layer baseline on success and safety while using fewer high-level wake-ups in that specific matrix.

These results are not presented as proof of general robot intelligence, real-world transfer, or a universal hierarchy. The complete numbers, sample definitions, rejected runs, and non-claims are recorded in the [program evidence ledger](reports/program-evidence/PROGRAM_EVIDENCE_LEDGER.md).

## Quick start

The locked environment targets Python 3.11 on macOS or Linux and uses [`uv`](https://docs.astral.sh/uv/).

```bash
make install-local
make test
make safety-check
```

To generate and replay the small deterministic bootstrap fixture:

```bash
make p1-check
make replay RUN=results/bootstrap/p1-fixture
```

Individual experiments have their own configs, protocols, and result directories. Start with [`experiments/00_source_audit/README.md`](experiments/00_source_audit/README.md) or [`experiments/01_policy_control/README.md`](experiments/01_policy_control/README.md) before running them.

## Design principles

1. **Small experiments before platforms.** A focused study should answer one architectural question.
2. **Safety by default.** Physical deployment is disabled; simulator and offline work are the default.
3. **Reproducibility over screenshots.** Results carry configs, seeds, source revisions, and reconstruction instructions.
4. **Negative results count.** Rejected or invalid runs remain visible instead of being rewritten as success.
5. **Typed boundaries.** Goals, observations, action chunks, recovery events, and persisted state have explicit contracts.

## Scope and maturity

This is an active research repository, not a production robotics SDK. Several studies are synthetic, some planned experiments remain unrun, and physical Unitree R1 deployment is intentionally out of scope. The value of the project is the experimental method and the accumulated engineering around safe, inspectable interfaces—not a claim that every layer is solved.

Third-party projects are used or studied under their own licenses. See [`references/licenses.md`](references/licenses.md) for the recorded provenance and restrictions.

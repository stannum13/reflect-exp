# Experiment contract

- Input: unchanged complete P2 registry and lock.
- Operations: pinned checkout, bounded static inspection, and one package-level MuJoCo smoke.
- Output: immutable fragments and deterministic reports.
- Safety: simulation-only, headless, offline consolidation, no physical interfaces.
- Gate: every source row is covered and the required MuJoCo smoke passes before P3 advances.

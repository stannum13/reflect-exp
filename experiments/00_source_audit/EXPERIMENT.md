# Experiment contract

- Input: unchanged complete P2 registry and lock.
- Operations: pinned checkout, bounded static inspection, and one package-level MuJoCo smoke.
- Output: immutable fragments and deterministic reports.
- Safety: simulation-only, headless, offline consolidation, no physical interfaces.
- Gate: every source row is covered and the required MuJoCo smoke passes before P3 advances.

## Post-freeze execution classification

The executed P3 outputs are `ENGINEERING_NONCONFIRMATORY`. Execution required the
manifest amendment recorded in `MANIFEST_AMENDMENT.yaml`; the original frozen
manifest remains preserved at commit `f53c7f4`, and both refused publication
attempts are recorded. The operational gate remains blocked by the retained LeRobot
checkout failure.

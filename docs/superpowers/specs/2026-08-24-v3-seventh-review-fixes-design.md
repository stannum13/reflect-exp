# V3 Seventh-Review Fixes Design

## Goal

Make the pre-outcome qualification report fully artifact-authenticated and restore the canonical ignored qualification root to exact agreement with the frozen source, tracked archive, and visible report without executing held-out outcome seeds.

## Design

`verify_qualification_report` will use a declarative list of visible facts. Each fact has one artifact-derived expected value and one anchored visible-text matcher. Verification requires exactly one occurrence and exact equality, so missing, duplicated, contradictory, or stale values fail closed. The schema covers every mutable numeric, hash, count, test-result, status, reconstruction, and archive fact in the report, including the demonstrated file-count and gate-count attacks.

The stale ignored canonical root will be renamed to a uniquely named superseded sibling instead of deleted. A canonical disposition receipt will record its original path, superseded path, source/freeze/raw/derived/tree hashes, and reason. The tracked archive will first be safely inspected and extracted into the canonical location. Because verifier source changes alter the frozen source closure, calibration-only qualification will then be regenerated from the new source, reconstructed byte-exactly, and resealed into a new deterministic tracked archive/report set. The canonical root, tracked archive, and report must authenticate one another exactly.

## Safety and validation

- Test-first: the `437→999`, `10→0`, duplicate-value, and representative stale mutable-fact attacks must fail before implementation and pass afterward.
- No held-out outcome seed or outcome publisher may run.
- Only ignored `__pycache__` directories and `.pyc`/`.pyo` files inside the governed Experiment 03 worktree may be removed before final validation.
- Validate recursive inventories, source/config/environment binding, structured report authentication, canonical reconstruction, archive extraction, focused tests, V3 selection, and the complete Experiment 03 suite.
- Keep the superseded evidence and disposition receipt recoverable and outside the canonical active root.

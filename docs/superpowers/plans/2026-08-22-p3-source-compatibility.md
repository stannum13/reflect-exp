# P3 Source Compatibility Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the complete P2 source lock into pinned sparse references, bounded local smoke evidence, and the four deterministic Experiment 00 compatibility/provenance outputs required to open the local experiment lanes.

**Architecture:** Keep checkout mechanics, compatibility evidence, and report generation separate. Source operations write immutable per-repository fragments; a pure consolidator validates those fragments against the unchanged P2 lock and generates reports without rerunning network or source commands.

**Tech Stack:** CPython 3.11.13, standard-library subprocess/AST/CSV/JSON, PyYAML 6.x, locked MuJoCo 3.x package, pytest 9.x, Git sparse checkout.

## Global Constraints

- P3 starts only when `scripts/audit_references.py --require-complete` passes against the tracked P2 lock.
- P3 never modifies `references/repos.lock.yaml` and never guesses a replacement for a `MISSING` selected path.
- Initial source checkout is limited to the eight `SPARSE_REFERENCE` repositories used by Experiments 01–03.
- Every checkout is detached at the locked 40-character SHA, sparse, clean, ignored below `external/`, and bounded by finite time/download/disk ceilings.
- Existing dirty, mismatched, symlinked, or malformed destinations are refused and never overwritten.
- Study-only Python is parsed without importing; ROS 2/CUDA/VLA servers/models/datasets/training are not installed or executed.
- MuJoCo is the only required P3 runtime dependency and must pass a headless one-step simulation smoke.
- Static parsing alone never earns `WORKS_LOCAL_M2`; compatibility uses only the nine canonical labels.
- P3 outputs are deterministic, attributable to the P2 lock and evidence hashes, and contain no credentials or host-specific absolute checkout paths.
- Physical deployment and remote execution remain disabled.

---

### Task 1: Pinned sparse-checkout utility

**Files:**
- Create: `reflect/source_checkout.py`
- Modify: `scripts/fetch_reference.py`
- Create: `tests/test_source_checkout.py`

**Interfaces:**
- Consumes: complete `SourceRegistry`/`SourceLock`, selector by repository or experiment, `CheckoutRunner`, ignored checkout root.
- Produces: `SparseCheckoutError`, `CheckoutSpec`, `CheckoutResult`, `eligible_checkout_specs(registry, lock, *, name=None, experiment=None)`, `checkout_sparse(spec, root, runner)`, and CLI modes `--name NAME --sparse-checkout` / `--experiment EXPERIMENT --sparse-checkout`.

- [ ] **Step 1: Write failing checkout tests**

Cover selector exclusivity, exact eight-repository eligibility, lock/audit gate,
`MISSING` path exclusion without substitution, root-glob preservation, fixed Git
argv/environment, detached SHA verification, finite timeouts, temp-directory cleanup,
atomic destination publication, and refusal of dirty/mismatched/symlinked existing
destinations. Include a fake runner test equivalent to:

```python
def test_checkout_uses_only_locked_sha_and_existing_paths(tmp_path: Path) -> None:
    spec = checkout_spec(
        sha="a" * 40,
        selected=(PathSelection("*.py", PathStatus.EXISTS),
                  PathSelection("gone", PathStatus.MISSING)),
    )
    result = checkout_sparse(spec, tmp_path / "external", RecordingRunner())
    assert result.commit_sha == "a" * 40
    assert result.patterns == ("*.py",)
    assert "gone" not in result.patterns
```

- [ ] **Step 2: Prove RED**

Run: `UV_CACHE_DIR=.cache/uv uv run pytest tests/test_source_checkout.py -q`

Expected: collection fails because `reflect.source_checkout` does not exist.

- [ ] **Step 3: Implement selector and path-pattern contracts**

Require a complete passing P2 audit before returning specs. Select only
`SPARSE_REFERENCE` entries in `01_policy_control`, `02_action_chunks`, or
`03_recovery`. Preserve requested paths and root globs verbatim, but include only
locked `EXISTS` paths in sparse patterns. Reject absolute paths, `..`, NUL/newline,
ambiguous names, empty selectors, and a selector that includes no eligible entry.

- [ ] **Step 4: Implement isolated sparse checkout**

Create a sibling `.<name>.partial-<random>` directory with mode `0700`. Invoke fixed
Git commands with disabled credentials/prompts/proxies/redirects and finite timeout:

```text
git init --quiet <partial>
git -C <partial> remote add origin <exact registry URL>
git -C <partial> fetch --quiet --depth=1 --filter=blob:none origin <locked SHA>
git -C <partial> sparse-checkout init --no-cone
git -C <partial> sparse-checkout set --no-cone --stdin
git -C <partial> checkout --quiet --detach <locked SHA>
```

Pass patterns through stdin, never shell interpolation. Verify `rev-parse HEAD`,
`status --porcelain=v1 -z`, sparse patterns, materialized existing paths/globs, and
disk bytes before atomically renaming. If a clean existing destination matches all
facts, return it unchanged; otherwise fail. Remove only the owned partial directory
on error.

- [ ] **Step 5: Extend the CLI without weakening metadata modes**

Keep the P2 selectors unchanged. Sparse modes require exactly one `--name` or
`--experiment`, call the offline complete audit first, require simulation-only, and
print deterministic JSON results. They do not publish or alter the lock.

- [ ] **Step 6: Verify and commit**

Run:

```text
UV_CACHE_DIR=.cache/uv uv run pytest tests/test_source_checkout.py -q
UV_CACHE_DIR=.cache/uv uv run pytest -q
git diff --check
```

Expected: all tests pass; no checkout/network is used by tests.

Commit:

```bash
git add reflect/source_checkout.py scripts/fetch_reference.py tests/test_source_checkout.py
git commit -m "feat: add pinned sparse source checkout"
```

---

### Task 2: Experiment 00 evidence and report contracts

**Files:**
- Create: `reflect/source_compat.py`
- Create: `scripts/source_audit.py`
- Create: `experiments/__init__.py`
- Create: `experiments/00_source_audit/__init__.py`
- Create: `experiments/00_source_audit/run.py`
- Create: `experiments/00_source_audit/configs/base.yaml`
- Create: `experiments/00_source_audit/README.md`
- Create: `experiments/00_source_audit/CLAIM.md`
- Create: `experiments/00_source_audit/EXPERIMENT.md`
- Create: `experiments/00_source_audit/RESULTS.md`
- Create: `experiments/00_source_audit/INTERFACE_FINDINGS.md`
- Create: `tests/test_source_compat.py`
- Modify: `Makefile`

**Interfaces:**
- Consumes: unchanged P2 registry/lock plus per-operation evidence fragments.
- Produces: `CompatibilityClass`, `SmokeStatus`, `CompatibilityEvidence`, `validate_fragment`, `consolidate_compatibility`, `write_compatibility_outputs`, `scripts/source_audit.py --check|--write`, and `python -m experiments.00_source_audit.run --config ...`.

- [ ] **Step 1: Write failing contract/report tests**

Test exact enums, strict fragment keys/types, SHA/path/license binding to the P2 lock,
canonical JSON/hash behavior, duplicate/conflicting fragment rejection, complete
row coverage, classification precedence, deterministic CSV/Markdown, and standard
experiment CLI flags. Assert the CSV header is exactly:

```text
repository,commit_sha,experiment,reuse_mode,selected_path,path_status,operation,platform,python_requirement,compiler_or_runtime,smoke_command,smoke_status,classification,license_status,license_spdx,disk_bytes,download_bytes,blocker,notes
```

- [ ] **Step 2: Prove RED**

Run: `UV_CACHE_DIR=.cache/uv uv run pytest tests/test_source_compat.py -q`

Expected: collection fails because `reflect.source_compat` does not exist.

- [ ] **Step 3: Implement immutable evidence validation**

Define the nine canonical compatibility labels and smoke states `NOT_RUN`, `PASS`,
`FAIL`, `BLOCKED`. A fragment binds registry digest, repository, full SHA,
experiment, requested selected path, operation, normalized platform/toolchain,
relative command vector, exit status, byte counts, license observation, blocker,
notes, and SHA-256 evidence hashes. Reject extra/missing keys, absolute paths,
nonfinite/negative counts, timestamps in comparison rows, lock mismatches, and any
claim stronger than its operation supports.

- [ ] **Step 4: Implement deterministic consolidation**

Create one row for every registry repository × experiment × requested path, using an
empty selected-path sentinel only for entries with no requested paths. Apply frozen
precedence:

1. locked `MISSING` → `PATH_CHANGED`;
2. required use with unknown/ambiguous license → `LICENSE_REVIEW_REQUIRED`;
3. executed runtime smoke pass → `WORKS_LOCAL_M2`;
4. executed patched CPU smoke pass → `WORKS_LOCAL_CPU_WITH_PATCH`;
5. `SPARSE_REFERENCE`/`PAPER_AND_CODE_REFERENCE` study evidence → `SOURCE_REFERENCE_ONLY`;
6. explicit remote GPU/Linux requirement → matching remote label;
7. archived evidence → `STALE_OR_ARCHIVED`;
8. otherwise → `NOT_EVALUATED`.

No fragment may promote a `REMOTE_ONLY` or `DEFERRED` source to local. Generate the
CSV, licenses table, source map, and experiment result/interface documents from
sorted records with LF newlines and atomic writes.

- [ ] **Step 5: Implement commands and canonical experiment skeleton**

`scripts/source_audit.py --check` validates existing outputs without network;
`--write` generates from fragments. The experiment module accepts `--config`,
`--seed`, `--output-dir`, `--dry-run`, `--max-episodes`, and `--headless`; because
Experiment 00 has no episodes, nonzero `--max-episodes` is recorded but does not
create repeated source operations. `--dry-run` prints the selected operations only.
Add `make source-audit` as offline P2 audit followed by Experiment 00 `--check`.

- [ ] **Step 6: Verify and commit**

Run focused/full tests and `make safety-check`; expect all to pass with no network.
Commit all Task 2 files atomically as `feat: add source compatibility evidence`.

---

### Task 3: Required MuJoCo runtime smoke

**Files:**
- Modify: `pyproject.toml`
- Modify: `uv.lock`
- Create: `experiments/00_source_audit/src/__init__.py`
- Create: `experiments/00_source_audit/src/smoke.py`
- Create: `experiments/00_source_audit/tests/test_smoke.py`
- Create: `tests/test_source_smoke.py`

**Interfaces:**
- Consumes: locked published MuJoCo 3.x package and P2 `mujoco` provenance.
- Produces: `run_mujoco_smoke() -> SmokeEvidence` and a deterministic evidence fragment without rendering/viewer state.

- [ ] **Step 1: Write failing smoke tests**

Test a minimal two-body XML, headless `MjModel.from_xml_string`, `MjData`, one
`mj_step`, finite time/state, no viewer/window/network, locked package version, and
fragment binding to the P2 MuJoCo SHA/license. Prove RED before adding the dependency.

- [ ] **Step 2: Add and lock only MuJoCo**

Add `mujoco>=3.3,<4` to project dependencies and run
`UV_CACHE_DIR=.cache/uv uv lock --python 3.11.13`. Do not add Mink, Rerun, rendering,
or experiment policy dependencies.

- [ ] **Step 3: Implement one-step headless smoke**

Use an inline XML with one world, plane, free body, joint, and actuator. Set a
deterministic control, call one `mj_step`, assert finite `time/qpos/qvel`, and record
package/Python/platform versions, command, duration, and hashes. Never create a
viewer or load a downloaded model.

- [ ] **Step 4: Verify and commit**

Run focused smoke tests twice for deterministic semantic fields, full tests, lock
check, and safety check. Commit as `feat: add MuJoCo compatibility smoke`.

---

### Task 4: Live sparse audits, consolidation, and P3 gate

**Files:**
- Create: `experiments/00_source_audit/results/fragments/*.json`
- Create: `experiments/00_source_audit/results/compatibility.csv`
- Create: `references/licenses.md`
- Create: `docs/SOURCE_MAP.md`
- Modify: `experiments/00_source_audit/RESULTS.md`
- Modify: `experiments/00_source_audit/INTERFACE_FINDINGS.md`
- Modify: `docs/ASSUMPTIONS.md`
- Modify: `docs/RUN_MANIFEST.yaml`
- Modify: `RUN_REPORT.md`

**Interfaces:**
- Consumes: reviewed Tasks 1–3, complete P2 lock, live sparse checkouts, static/runtime smoke results.
- Produces: complete Experiment 00 outputs, P3 decision, and opened local lanes.

- [ ] **Step 1: Freeze the operation manifest**

Generate a deterministic manifest for the eight eligible sparse repositories plus
the MuJoCo runtime smoke. Record exact locked SHAs, existing/missing paths,
operations, commands, platform/toolchain, per-command 60-minute maximum, 2 GB
per-source and 5 GB pass download ceilings, and no-copy/no-model constraints. Hash
and commit the manifest before source operations.

- [ ] **Step 2: Run independent sparse lanes**

Dispatch non-overlapping workers for Experiment 01, 02, and 03 repositories. Each
worker owns only its `external/<repo>` destinations and distinct fragment files.
Run the explicit sparse command, AST-parse selected Python files, perform declared
static manifest/header checks, record bytes and exact output, and stop after one
failure plus one materially different remedy. Do not import study-only projects.

- [ ] **Step 3: Run the MuJoCo smoke serially**

Execute the reviewed headless one-step smoke alone, write its evidence fragment,
and verify no process/viewer remains. Optional Mink/Rerun attempts are omitted unless
the frozen manifest contains a bounded decision-relevant check.

- [ ] **Step 4: Generate and validate outputs**

Run:

```text
UV_CACHE_DIR=.cache/uv uv run python scripts/source_audit.py --write
UV_CACHE_DIR=.cache/uv uv run python scripts/source_audit.py --check
UV_CACHE_DIR=.cache/uv uv run python -m experiments.00_source_audit.run --config experiments/00_source_audit/configs/base.yaml --seed 0 --output-dir experiments/00_source_audit/results --max-episodes 1 --headless
make source-audit
```

Expected: all exit zero; compatibility rows cover the complete registry and the
four required outputs bind to the P2 lock and fragment hashes.

- [ ] **Step 5: Apply the Experiment 00 claim and advance gate**

Set the result to `SUPPORTED`, `NOT_SUPPORTED`, or `INCONCLUSIVE` based on the
predeclared hypothesis and actual compatibility evidence—not on whether every
optional source worked. Record exact claims/cannot-claims, selected source seams,
local fallbacks, Unitree implications, blockers, and next experiments. P3 advances
only if MuJoCo and the approved project-local baseline can run cleanly on M2.

- [ ] **Step 6: Verify repository boundaries and state**

Run the full suite, lock check, safety check, offline P2/P3 audits, diff check,
secret scan, tracked checkout/model scan, and generated-size audit. Verify all
`external/` repositories are ignored, pinned, clean, and within budget. Set
`p3: complete`, `p4: in_progress`, and open control/world-state/prediction/platform
lanes without marking any empirical claim beyond Experiment 00.

- [ ] **Step 7: Commit evidence and report**

Commit small manifests/fragments/reports only; do not add checkouts. Use a clean
implementation/evidence commit followed by a report-only commit bound to that SHA.

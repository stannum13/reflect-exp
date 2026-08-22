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
- The checkout root and every intermediate directory are opened without following symlinks; creation, inspection, rename, and cleanup remain descriptor-anchored inside that root.
- Study-only Python is parsed without importing; ROS 2/CUDA/VLA servers/models/datasets/training are not installed or executed.
- MuJoCo is the only required P3 runtime dependency and must pass a headless one-step simulation smoke.
- Static parsing alone never earns `WORKS_LOCAL_M2`; compatibility uses only the nine canonical labels.
- P3 outputs are deterministic, attributable to the P2 lock and evidence hashes, and contain no credentials or host-specific absolute checkout paths.
- Physical deployment and remote execution remain disabled.

---

### Task 1: Pinned sparse-checkout utility

**Files:**
- Create: `reflect/source_evidence.py`
- Create: `reflect/source_checkout.py`
- Modify: `scripts/fetch_reference.py`
- Create: `tests/test_source_checkout.py`

**Interfaces:**
- Consumes: complete `SourceRegistry`/`SourceLock`, selector by repository or experiment, `CheckoutRunner`, ignored checkout root.
- Produces: `SparseCheckoutError`, `CheckoutSpec`, `CheckoutResult`, `CheckoutEvidence`, `eligible_checkout_specs(registry, lock, *, name=None, experiment=None)`, `checkout_sparse(spec, root, runner)`, `write_evidence_create_only(path, evidence)`, and CLI modes `--name NAME --sparse-checkout` / `--experiment EXPERIMENT --sparse-checkout`.

- [ ] **Step 1: Write failing checkout tests**

Cover selector exclusivity, exact eight-repository eligibility, lock/audit gate,
`MISSING` path exclusion without substitution, root-glob preservation, fixed Git
argv/environment, detached SHA verification, finite timeouts, temp-directory cleanup,
atomic destination publication, and refusal of dirty/mismatched/symlinked existing
destinations. Explicitly cover symlinked root and intermediate directories, checkout
root inode replacement before inspection/rename/cleanup, malicious repository-local
hooks/fsmonitor configuration, and proof no out-of-root path is touched. Cover
create-only checkout evidence with exact command vector/status/download+disk bytes,
lock binding, canonical hash, fsync, and overwrite refusal. Include a fake runner test equivalent to:

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

Open/create the checkout root one component at a time with no-follow directory
descriptors and retain the root descriptor. Create a descriptor-relative sibling
`.<name>.partial-<random>` directory with mode `0700`. Reject root/intermediate
symlinks and verify inode identity before inspection, rename, or cleanup. Invoke fixed
Git commands with disabled credentials/prompts/proxies/redirects and finite timeout:

```text
git init --quiet <partial>
git -C <partial> remote add origin <exact registry URL>
git -C <partial> fetch --quiet --depth=1 --filter=blob:none origin <locked SHA>
git -C <partial> sparse-checkout init --no-cone
git -C <partial> sparse-checkout set --no-cone --stdin
git -C <partial> checkout --quiet --detach <locked SHA>
```

Pass patterns through stdin, never shell interpolation. Disable repository-local
hooks and fsmonitor for every inspection command. Verify `rev-parse HEAD`,
`status --porcelain=v1 -z`, sparse patterns, materialized existing paths/globs, and
disk bytes before atomically renaming. If a clean existing destination matches all
facts, return it unchanged; otherwise fail. Remove only the owned partial directory
on error.

- [ ] **Step 5: Persist immutable checkout evidence**

`reflect/source_evidence.py` defines the canonical JSON/hash primitive and a strict
`CHECKOUT` evidence record binding registry digest, name, locked SHA, selected
patterns, exact command vectors/statuses, download/disk bytes, outcome, blocker, and
content hashes. Publish through descriptor-relative mode-`0600` `O_EXCL` + fsync;
never overwrite a fragment. Task 2 reuses this primitive for all other evidence.

- [ ] **Step 6: Extend the CLI without weakening metadata modes**

Keep the P2 selectors unchanged. Sparse modes require exactly one `--name` or
`--experiment`, an explicit `--fragment-dir`, call the offline complete audit first,
require simulation-only, and write one create-only `CHECKOUT` fragment per selected
repository before printing deterministic JSON results. They do not publish or alter
the lock.

- [ ] **Step 7: Verify and commit**

Run:

```text
UV_CACHE_DIR=.cache/uv uv run pytest tests/test_source_checkout.py -q
UV_CACHE_DIR=.cache/uv uv run pytest -q
git diff --check
```

Expected: all tests pass; no checkout/network is used by tests.

Commit:

```bash
git add reflect/source_evidence.py reflect/source_checkout.py scripts/fetch_reference.py tests/test_source_checkout.py
git commit -m "feat: add pinned sparse source checkout"
```

---

### Task 2: Experiment 00 evidence and report contracts

**Files:**
- Create: `reflect/source_compat.py`
- Create: `reflect/source_ops.py`
- Create: `scripts/source_audit.py`
- Create: `experiments/__init__.py`
- Create: `experiments/00_source_audit/__init__.py`
- Create: `experiments/00_source_audit/run.py`
- Create: `experiments/00_source_audit/configs/base.yaml`
- Create: `experiments/00_source_audit/configs/operation-manifest.yaml`
- Create: `experiments/00_source_audit/README.md`
- Create: `experiments/00_source_audit/CLAIM.md`
- Create: `experiments/00_source_audit/EXPERIMENT.md`
- Create: `experiments/00_source_audit/RESULTS.md`
- Create: `experiments/00_source_audit/INTERFACE_FINDINGS.md`
- Create: `tests/test_source_compat.py`
- Modify: `Makefile`

**Interfaces:**
- Consumes: unchanged P2 registry/lock, digest-bound `OperationManifest`, and per-operation evidence fragments including Task 1 `CHECKOUT` records.
- Produces: `CompatibilityClass`, `SmokeStatus`, `CompatibilityEvidence`, `RequirementObservation`, `OperationManifest`, `load_operation_manifest`, `validate_fragment`, `consolidate_compatibility`, `write_compatibility_outputs`, `scripts/source_audit.py --check|--write`, and `python -m experiments.00_source_audit.run --config ...`.
- Produces operation interfaces: `SourceOperation`, `OperationSpec`, `run_source_operation(spec, checkout_root) -> CompatibilityEvidence`, and `write_fragment_create_only(path, evidence) -> None`.

- [ ] **Step 1: Write failing contract/report tests**

Test exact enums, strict fragment keys/types, SHA/path/license binding to the P2 lock,
canonical JSON/hash behavior, duplicate/conflicting fragment rejection, complete
row coverage, classification precedence, deterministic CSV/Markdown, and standard
experiment CLI flags. Test bounded AST parsing, manifest/header layout checks,
asset-license inventory, path containment, byte limits, captured normalized results,
and create-only atomic fragment publication that refuses overwrite. Test that the
operation manifest binds the registry/lock digest, covers all 45 entries, accepts
optional structured GPU/Linux/archive observations with canonical/official
provenance plus content hash, maps missing observations to `NOT_EVALUATED`, and
rejects tampered hashes before consolidation. Assert the CSV
header is exactly:

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
notes, runtime subject (`source_checkout` or `package`), exact package version and
artifact hash when applicable, optional patch/remedy artifact SHA-256, structured
platform-requirement evidence with provenance/hash, and SHA-256 evidence hashes.
Reject extra/missing keys, absolute paths,
nonfinite/negative counts, timestamps in comparison rows, lock mismatches, and any
claim stronger than its operation supports. A package-runtime fragment retains the
P2 Git SHA as registry provenance but never claims that SHA was executed.

Define a strict `OperationManifest` with exact registry and lock hashes, all 45
repository identities, optional executable operations, and optional
`RequirementObservation` records for `REMOTE_GPU`, `REMOTE_LINUX`, or `ARCHIVED`.
Each observation includes a canonical-program or official HTTPS provenance locator,
normalized statement, and SHA-256 of that statement. Missing observations are valid
and yield `NOT_EVALUATED`; malformed identities or hashes invalidate the manifest.

- [ ] **Step 4: Implement the reproducible source-operation runner**

`reflect/source_ops.py` implements only bounded read-only operations:
`AST_PARSE`, `HEADER_LAYOUT`, `MANIFEST_LAYOUT`, and `ASSET_LICENSE_INVENTORY`.
It resolves every path beneath a no-follow checkout descriptor, rejects symlinks,
nonregular files, invalid UTF-8, escape, oversized inputs, and unrequested paths;
uses `ast.parse` without import; and records normalized findings plus content hashes.
`write_fragment_create_only` validates evidence first, writes mode `0600` with
`O_EXCL`, fsyncs file/directory, and refuses an existing fragment. Expose the same
operation through the Experiment 00 CLI for exactly one repository/operation.

- [ ] **Step 5: Implement deterministic consolidation**

Create one row for every registry repository × experiment × requested path, using an
empty selected-path sentinel only for entries with no requested paths. Apply frozen
precedence:

1. locked `MISSING` → `PATH_CHANGED`;
2. required use with unknown/ambiguous license → `LICENSE_REVIEW_REQUIRED`;
3. executed runtime smoke pass → `WORKS_LOCAL_M2`;
4. executed patched CPU smoke pass with patch/remedy artifact hash → `WORKS_LOCAL_CPU_WITH_PATCH`;
5. `SPARSE_REFERENCE`/`PAPER_AND_CODE_REFERENCE` study evidence → `SOURCE_REFERENCE_ONLY`;
6. explicit remote GPU/Linux requirement with frozen provenance/hash → matching remote label;
7. archived evidence → `STALE_OR_ARCHIVED`;
8. otherwise → `NOT_EVALUATED`.

Without required patch/platform evidence, use `NOT_EVALUATED`; do not infer from a
mode name alone. No fragment may promote a `REMOTE_ONLY` or `DEFERRED` source to local. Generate the
CSV, licenses table, source map, and experiment result/interface documents from
sorted records with LF newlines and atomic writes.

- [ ] **Step 6: Implement commands and canonical experiment skeleton**

`scripts/source_audit.py --check` validates existing outputs without network;
`--write` generates from fragments. `--operate NAME --operation OP --fragment PATH`
runs the reviewed source-operation API and create-only writer. The experiment module accepts `--config`,
`--seed`, `--output-dir`, `--dry-run`, `--max-episodes`, and `--headless`; because
Experiment 00 has no episodes, nonzero `--max-episodes` is recorded but does not
create repeated source operations. `--dry-run` prints the selected operations only.
Add `make source-audit` as offline P2 audit followed by Experiment 00 `--check`.

- [ ] **Step 7: Verify and commit**

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
- Consumes: locked published MuJoCo 3.x package and separately recorded P2 `mujoco` source provenance.
- Produces: `run_mujoco_smoke() -> SmokeEvidence` and a deterministic evidence fragment without rendering/viewer state.

- [ ] **Step 1: Write failing smoke tests**

Test a minimal two-body XML, headless `MjModel.from_xml_string`, `MjData`, one
`mj_step`, finite time/state, no viewer/window/network, locked package version, and
fragment binding to the installed package name/version/artifact hash. Retain the P2
MuJoCo Git SHA/license only in separate registry-provenance fields and assert the
fragment does not claim that SHA was executed. Prove RED before adding the dependency.

- [ ] **Step 2: Add and lock only MuJoCo**

Add `mujoco>=3.3,<4` to project dependencies and run
`UV_CACHE_DIR=.cache/uv uv lock --python 3.11.13`. Do not add Mink, Rerun, rendering,
or experiment policy dependencies.

- [ ] **Step 3: Implement one-step headless smoke**

Use an inline XML with one world, plane, free body, joint, and actuator. Set a
deterministic control, call one `mj_step`, assert finite `time/qpos/qvel`, and record
package/Python/platform versions, installed-distribution artifact hash, command,
duration, and hashes. Never create a
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
- Create: `scripts/write_p3_report.py`
- Verify/reuse: `scripts/publish_phase_record.py`

**Interfaces:**
- Consumes: reviewed Tasks 1–3, complete P2 lock, live sparse checkouts, static/runtime smoke results.
- Produces: complete Experiment 00 outputs, P3 decision, and opened local lanes.

- [ ] **Step 1: Freeze the operation manifest**

Generate and commit
`experiments/00_source_audit/configs/operation-manifest.yaml` covering all 45 repositories. Record exact locked
SHAs, existing/missing paths, and frozen platform/archive requirement observations
with canonical or official provenance and content hashes. Only the eight eligible
sparse repositories plus the MuJoCo package smoke receive executable operations. Record
operations, commands, platform/toolchain, per-command 60-minute maximum, 2 GB
per-source and 5 GB pass download ceilings, and no-copy/no-model constraints. Hash
and commit the manifest before source operations.

- [ ] **Step 2: Run independent sparse lanes**

Dispatch non-overlapping workers for Experiment 01, 02, and 03 repositories. Each
worker owns only its `external/<repo>` destinations and distinct fragment files.
Run the explicit sparse command with its create-only fragment directory, then invoke only the reviewed `--operate` command
for declared AST/manifest/header/asset-license checks; it records bytes, normalized
findings, content hashes, and exact command into a create-only fragment. Stop after one
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

Set the canonical comparative implementation-time hypothesis to `INCONCLUSIVE`
because P3 does not run a counterfactual adoption-time study. Keep the operational
advance decision separate and report only the canonical can-establish findings:
revisions, compatibility, source seams, blockers, and reuse disposition. Record exact claims/cannot-claims, selected source seams,
local fallbacks, Unitree implications, blockers, and next experiments. P3 advances
only if the complete P2 audit passes, the MuJoCo package smoke passes, every
installed dependency has matching license/smoke evidence, every eligible checkout
is clean or explicitly dispositioned after its bounded attempts, all outputs
validate, no checkout/model is tracked, and remote/physical execution remains off.

- [ ] **Step 6: Verify repository boundaries and state**

Run the full suite, lock check, safety check, offline P2/P3 audits, diff check,
secret scan, tracked checkout/model scan, and generated-size audit. Verify all
`external/` repositories are ignored, pinned, clean, and within budget. Set
`p3: complete`, `p4: in_progress`, and open control/world-state/prediction/platform
lanes without marking any empirical claim beyond Experiment 00.

- [ ] **Step 7: Commit evidence and the report as two distinct commits**

Commit the complete small P3 manifests/fragments/results and durable P3 state only; do
not add checkouts. Require the staged inventory to equal the reviewed P3 evidence-path
inventory, commit it, require a clean tree, and record the full lowercase current SHA as
`P3_EVIDENCE_SHA`. Generate `RUN_REPORT.md` against exactly that clean SHA with the
reviewed deterministic P3 reporter:

```bash
env PHYSICAL_DEPLOYMENT_ALLOWED=false REFLECT_REMOTE_ENABLED=0 \
  UV_CACHE_DIR=.cache/uv uv run python scripts/write_p3_report.py \
  --evidence-base-sha "$P3_EVIDENCE_SHA"
```

The reporter validates the complete P2/P3 evidence snapshot and safety state, renders
the required report sections deterministically, and writes the implementation/evidence
SHA in a closed provenance field consumed by the phase-record publisher. It performs no
network or source operation. Validate that the report binds `P3_EVIDENCE_SHA`, then
stage and commit exactly `RUN_REPORT.md`:

```bash
git add -- RUN_REPORT.md
test "$(git diff --cached --name-only)" = RUN_REPORT.md
git commit -m "docs: publish P3 compatibility report"
P3_REPORT_COMMIT="$(git rev-parse HEAD)"
```

The report commit's only parent must be `P3_EVIDENCE_SHA`. Do not amend or regenerate
the report after this commit; a correction requires a new evidence/report pair.

- [ ] **Step 8: Publish and validate the immutable P3 phase index**

With a clean tree at `P3_REPORT_COMMIT`, run:

```bash
env UV_CACHE_DIR=.cache/uv uv run python scripts/publish_phase_record.py publish \
  --phase p3 --implementation-evidence-git-sha "$P3_EVIDENCE_SHA" \
  --report-commit-git-sha "$P3_REPORT_COMMIT" \
  --run-manifest docs/RUN_MANIFEST.yaml
git add -- docs/RUN_MANIFEST.yaml
test "$(git diff --cached --name-only)" = docs/RUN_MANIFEST.yaml
git commit -m "docs: index immutable P3 phase evidence"
P3_STATE_INDEX_COMMIT="$(git rev-parse HEAD)"
env UV_CACHE_DIR=.cache/uv uv run python scripts/publish_phase_record.py validate \
  --phase p3 --state-index-commit "$P3_STATE_INDEX_COMMIT" \
  --run-manifest docs/RUN_MANIFEST.yaml
```

The publisher derives every `phase_records.p3` field and its canonical artifact-ledger
hash. The exact ledger members are the operation manifest, compatibility CSV,
`references/licenses.md`, `docs/SOURCE_MAP.md`, both Experiment 00 reports, the one
MuJoCo-smoke fragment selected by the operation manifest, all at `P3_EVIDENCE_SHA`, and
`RUN_REPORT.md` at `P3_REPORT_COMMIT`. It rejects any additional member or caller-
supplied digest, requires
`implementation_evidence_git_sha == bound_evidence_git_sha == P3_EVIDENCE_SHA`, and
requires the report commit's only parent and validated bound SHA to match. The existing
P2 record must remain canonically equal. The state-index commit has the report commit as
its only parent, changes exactly `docs/RUN_MANIFEST.yaml`, and is excluded from both the
record and ledger so no self-reference exists.

- [ ] **Step 9: Reverify the three-commit P3 closeout**

Rerun the complete P2 audit, P3 offline checks, full tests, lock check, safety check,
repository-boundary checks, and `git diff --check`. Require a clean tree. Validate both
`phase_records.p2` and `phase_records.p3`; reconstruct each canonical record and
artifact ledger from Git; verify the P3 evidence, report-only, and state-index changed-
path sets and parent chain; and confirm current P4/P6/P7/P9 lanes remain exactly those
opened by the reviewed P3 evidence commit.

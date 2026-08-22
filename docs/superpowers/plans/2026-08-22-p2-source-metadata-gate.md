# P2 Source Metadata Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Materialize and live-resolve the complete 45-entry source registry into an atomic, factual, metadata-only lock that can be audited offline before any upstream source is used.

**Architecture:** Keep immutable source intent in `references/repos.yaml`, put parsing and validation in a small `reflect.sources` module, and combine an injectable read-only `git ls-remote` runner with a bounded GitHub HTTPS transport in `scripts/fetch_reference.py`. Publish `repos.lock.yaml` only after every selected entry resolves and the complete candidate passes the same offline validator exposed by `scripts/audit_references.py`.

**Tech Stack:** CPython 3.11.13, standard-library `urllib`, PyYAML 6.x, SHA-256, pytest 9.x, GitHub REST metadata endpoints.

## Global Constraints

- P2 contains all 39 canonical Section 8 repositories plus the six existing bootstrap entries, exactly 45 unique names.
- Reuse mode is exactly one of `DIRECT_DEPENDENCY`, `ADAPTER_DEPENDENCY`, `SPARSE_REFERENCE`, `REMOTE_ONLY`, `PAPER_AND_CODE_REFERENCE`, or `DEFERRED`.
- Metadata mode performs no clone, install, import, build, source copy, model/checkpoint download, remote execution, or physical communication.
- Network endpoints are `github.com` and `api.github.com` HTTPS identities derived only from exact `https://github.com/OWNER/REPO` registry URLs.
- Every resolved revision is a 40-character lowercase hexadecimal SHA.
- Every requested selected path is preserved verbatim and marked `EXISTS` or `MISSING`; `mjctrl`'s `*.py` means a root-entry glob.
- Unknown license metadata is factual evidence, not legal approval; it blocks direct/adapter approval and copying.
- A partial or failed live pass must not replace an existing tracked lock.
- Tests are offline and use only checked-in compact fixtures.
- Physical deployment and remote execution remain disabled.

---

### Task 1: Canonical registry and pure schema validation

**Files:**
- Create: `references/repos.yaml`
- Create: `reflect/sources.py`
- Create: `tests/test_source_registry.py`
- Create: `tests/fixtures/source_metadata/registry-minimal.yaml`

**Interfaces:**
- Consumes: YAML registry bytes.
- Produces: `ReuseMode`, `PathStatus`, `LicenseStatus`, `MetadataStatus`, `RegistryEntry`, `LockedEntry`, `SourceRegistry`, `SourceLock`, `load_registry(path) -> SourceRegistry`, `load_lock(path) -> SourceLock`, `registry_sha256(path) -> str`, and `validate_lock(registry, lock, *, require_complete: bool) -> list[str]`.

- [ ] **Step 1: Write failing registry tests**

Create tests asserting all 45 expected names, uniqueness, exact canonical values for representative entries, valid HTTPS GitHub URLs, exact reuse modes, immutable tuples, and rejection of extra/missing keys. Include:

```python
def test_complete_registry_has_canonical_and_bootstrap_entries() -> None:
    registry = load_registry(Path("references/repos.yaml"))
    assert len(registry.repositories) == 45
    assert {entry.name for entry in registry.repositories} >= {
        "mujoco", "lerobot", "unitree_rl_mjlab", "isaac_lab_arena",
        "uv", "hatchling", "pyyaml", "numpy", "pyarrow", "pytest",
    }


def test_registry_rejects_non_github_https_url(tmp_path: Path) -> None:
    path = write_registry(tmp_path, url="https://example.com/owner/repo")
    with pytest.raises(SourceValidationError, match="github.com"):
        load_registry(path)
```

- [ ] **Step 2: Prove RED**

Run: `UV_CACHE_DIR=.cache/uv uv run pytest tests/test_source_registry.py -q`

Expected: collection fails because `reflect.sources` and `references/repos.yaml` do not exist.

- [ ] **Step 3: Materialize the registry**

Copy every Section 8 entry without changing its URL, mode, experiments, paths, use,
or caveat. Append the six entries from `references/bootstrap-tools.yaml`, preserving
their use/justification. Keep the top-level safety defaults false.

- [ ] **Step 4: Implement strict immutable parsing**

Define frozen dataclasses whose `__post_init__` rejects empty strings, duplicate
names/paths, booleans where strings are required, unrecognized keys, invalid reuse
modes, and URLs not matching `https://github.com/{owner}/{repo}`. Normalize lists to
tuples and mappings to immutable values. `registry_sha256` hashes exact file bytes.

- [ ] **Step 5: Run focused and regression tests**

Run: `UV_CACHE_DIR=.cache/uv uv run pytest tests/test_source_registry.py -q`

Expected: all registry tests pass.

Run: `UV_CACHE_DIR=.cache/uv uv run pytest -q`

Expected: all tests pass.

- [ ] **Step 6: Commit Task 1**

```bash
git add references/repos.yaml reflect/sources.py tests/test_source_registry.py tests/fixtures/source_metadata/registry-minimal.yaml
git commit -m "feat: materialize validated source registry"
```

---

### Task 2: Metadata resolver, cache, and atomic publication

**Files:**
- Create: `reflect/source_fetch.py`
- Create: `reflect/_source_git.py`
- Create: `reflect/_source_http.py`
- Create: `reflect/_source_cache.py`
- Create: `scripts/fetch_reference.py`
- Create: `tests/test_source_fetch.py`
- Create: `tests/fixtures/source_metadata/github-repository.json`
- Create: `tests/fixtures/source_metadata/github-tree.json`
- Create: `tests/fixtures/source_metadata/github-license.json`
- Modify: `.gitignore`

**Interfaces:**
- Consumes: `SourceRegistry`, exact registry selectors, an injected `Runner.run_ls_remote(url)`, an injected `Transport.get(url)`, and an injected UTC clock.
- Produces: `GitHubIdentity`, `HttpResponse`, `MetadataEvidence`, `resolve_entry(entry, transport, clock) -> LockedEntry`, `resolve_registry(registry, names, transport, clock) -> SourceLock`, `CacheStore`, and `atomic_write_lock(path, lock) -> None`.

`reflect/source_fetch.py` owns endpoint derivation and resolution orchestration;
`reflect/_source_git.py` owns isolated `ls-remote` execution/parsing;
`reflect/_source_http.py` owns bounded HTTPS and rate-limit response handling; and
`reflect/_source_cache.py` owns checksummed cache records and atomic publication.
The underscored modules are internal and the public imports above remain available
from `reflect.source_fetch`.

- [ ] **Step 1: Write failing resolver tests**

Cover order-independent `ls-remote` default-branch/SHA parsing, missing/detached/
unborn/duplicate/SHA-256 HEAD rejection, Git-config isolation, commit-to-tree
resolution, SPDX discovery and unknown license handling, literal paths, root globs,
missing paths, truncated-tree targeted fallback, exact evidence URLs, deterministic
YAML, cache checksums, rate-limit resume, one cache fallback after a live failure,
and atomic failure:

```python
def test_failed_resolution_preserves_existing_lock(tmp_path: Path) -> None:
    lock_path = tmp_path / "repos.lock.yaml"
    lock_path.write_bytes(b"previous\n")
    with pytest.raises(SourceFetchError, match="rate limit"):
        run_resolution(failing_transport(), lock_path=lock_path)
    assert lock_path.read_bytes() == b"previous\n"


def test_metadata_resolution_does_not_create_checkout(tmp_path: Path) -> None:
    run_resolution(fixture_transport(), root=tmp_path)
    assert not (tmp_path / "external" / "example").exists()
```

- [ ] **Step 2: Prove RED**

Run: `UV_CACHE_DIR=.cache/uv uv run pytest tests/test_source_fetch.py -q`

Expected: collection fails because `reflect.source_fetch` does not exist.

- [ ] **Step 3: Implement endpoint derivation and injectable transport**

Parse registry identities without accepting query strings, fragments, credentials,
or extra path components. Invoke only:

```text
git ls-remote --symref https://github.com/{owner}/{repo} HEAD
https://api.github.com/repos/{owner}/{repo}/git/commits/{commit_sha}
https://api.github.com/repos/{owner}/{repo}/git/trees/{tree_sha}?recursive=1
https://api.github.com/repos/{owner}/{repo}/git/trees/{tree_sha}
https://api.github.com/repos/{owner}/{repo}/git/blobs/{license_blob_sha}
```

Run Git with a fixed argument vector, noninteractive environment, bounded timeout,
captured output, `GIT_CONFIG_GLOBAL=/dev/null`, `GIT_CONFIG_SYSTEM=/dev/null`,
`GIT_CONFIG_NOSYSTEM=1`, and `GIT_TERMINAL_PROMPT=0`; remove credential, askpass,
proxy, and trace environment. Parse records by ref identity rather than line order;
require exactly one `ref: refs/heads/... HEAD` and matching 40-character HEAD SHA.
Use `urllib.request` with a fixed user agent, bounded timeout, bounded response size,
and no authentication. Reject a final response outside the exact derived API owner/
repo and pinned-object path. Surface HTTP status and rate-limit headers without
response-body secrets.

- [ ] **Step 4: Implement factual resolution and path matching**

Resolve the default branch and commit SHA from `ls-remote`; validate the Git commit
response matches that SHA and use its `tree.sha` for tree requests. A literal
requested path exists when its exact tree/blob entry exists or when it is a tree
prefix of an entry. A root glob matches only root entries via `fnmatchcase`. When a
recursive tree is truncated, walk only requested prefixes by tree SHA and refuse
unresolved paths. Preserve every requested string in the lock. Discover conventional
root license filenames case-insensitively, fetch the exact blob by its recorded SHA,
decode its declared base64 encoding, and classify only recognized SPDX-identifiable
texts; otherwise record `UNKNOWN` or `UNAVAILABLE` with its evidence endpoint.

- [ ] **Step 5: Implement checksummed cache and atomic lock output**

Write raw JSON/text plus endpoint or Git command, retrieval timestamp, ETag where
available, and SHA-256 below
`external/.metadata/{name}/`. Validate cache metadata and payload digest before a
single fallback. Process requests serially. When `x-ratelimit-remaining` reaches
zero or GitHub returns its rate-limit response, report `x-ratelimit-reset`, exit
nonzero, and resume from the validated cache on a later invocation; do not sleep or
retry immediately. Serialize the full candidate deterministically, validate it,
write a same-directory temporary file with descriptor-safe permissions, `fsync`,
and `os.replace`. Clean the temporary file on every error.

- [ ] **Step 6: Implement the P2 command surface**

`scripts/fetch_reference.py` accepts either `--all-metadata-only` or
`--name NAME --metadata-only`, plus hidden test-only path/transport injection through
callable `main(argv)`. It calls `SafetyConfig.from_env().require_simulation_only()`
before loading cache or making requests. A single-name run prints deterministic YAML
to stdout unless `--update-lock` is explicitly present; the all-entry command
publishes the complete lock.

- [ ] **Step 7: Run focused, offline-network-negative, and regression tests**

Run: `UV_CACHE_DIR=.cache/uv uv run pytest tests/test_source_fetch.py -q`

Expected: all resolver tests pass with no network.

Run: `UV_CACHE_DIR=.cache/uv uv run pytest -q`

Expected: all tests pass.

- [ ] **Step 8: Commit Task 2**

```bash
git add .gitignore reflect/source_fetch.py reflect/_source_git.py reflect/_source_http.py reflect/_source_cache.py scripts/fetch_reference.py tests/test_source_fetch.py tests/fixtures/source_metadata
git commit -m "feat: resolve source metadata atomically"
```

---

### Task 3: Offline audit and command contract

**Files:**
- Create: `scripts/audit_references.py`
- Create: `tests/test_source_audit.py`
- Modify: `Makefile`

**Interfaces:**
- Consumes: `references/repos.yaml`, `references/repos.lock.yaml`, and tracked repository paths.
- Produces: `audit_repository(root, *, require_complete: bool) -> AuditResult`; commands `python scripts/audit_references.py --require-complete` and `make source-metadata-audit`.

- [ ] **Step 1: Write failing audit tests**

Create an accepted fixture and mutations proving rejection of registry digest
mismatch, extra/missing entries, short SHA, absent license observation, unknown
direct/adapter license, dropped/substituted path, incomplete status, checkout
directory, attributed/unattributed copied source, and tracked checkpoint suffixes.

```python
def test_require_complete_rejects_unknown_direct_license(tmp_path: Path) -> None:
    root = complete_fixture(tmp_path, mode="DIRECT_DEPENDENCY", license_status="UNKNOWN")
    result = audit_repository(root, require_complete=True)
    assert "direct/adapter license is not discovered" in result.errors[0]
```

- [ ] **Step 2: Prove RED**

Run: `UV_CACHE_DIR=.cache/uv uv run pytest tests/test_source_audit.py -q`

Expected: import or command failure because the audit entry point does not exist.

- [ ] **Step 3: Implement the audit**

Reuse `reflect.sources.validate_lock`; do not create a parallel schema. Inspect
tracked files through `git ls-files -z`, reject source checkout roots and common
model/checkpoint suffixes, and require an adjacent attribution record before any
file explicitly declared as copied upstream source. Print a stable JSON summary
with entry/path/license counts and sorted errors. Exit `0` only when error-free.

- [ ] **Step 4: Add the Make target**

```make
.PHONY: source-metadata-audit
source-metadata-audit:
	$(UV) run python scripts/fetch_reference.py --all-metadata-only
	$(UV) run python scripts/audit_references.py --require-complete
```

- [ ] **Step 5: Run focused, command, and regression checks**

Run: `UV_CACHE_DIR=.cache/uv uv run pytest tests/test_source_audit.py -q`

Expected: all audit tests pass.

Run: `UV_CACHE_DIR=.cache/uv uv run pytest -q`

Expected: all tests pass.

Run: `make safety-check`

Expected: simulation-only true and remote false.

- [ ] **Step 6: Commit Task 3**

```bash
git add Makefile scripts/audit_references.py tests/test_source_audit.py
git commit -m "feat: audit locked source metadata"
```

---

### Task 4: Live 45-entry resolution and P2 gate evidence

**Files:**
- Create: `references/repos.lock.yaml`
- Create: `scripts/write_p2_report.py`
- Create: `tests/test_p2_commands.py`
- Modify: `docs/ASSUMPTIONS.md`
- Modify: `docs/RUN_MANIFEST.yaml`
- Modify: `RUN_REPORT.md`

**Interfaces:**
- Consumes: reviewed Tasks 1–3 at a clean implementation commit and live GitHub metadata.
- Produces: a complete current lock, bound P2 report, and P3-ready manifest state.

- [ ] **Step 1: Write failing command/report tests**

Test that the checked-in lock covers the exact registry digest and 45 names, all
entries are resolved, all paths have statuses, direct/adapter licenses are
discovered, the report cites a clean implementation SHA and exact command outcomes,
and the manifest may advance only when the complete audit passes.

- [ ] **Step 2: Prove RED before live data exists**

Run: `UV_CACHE_DIR=.cache/uv uv run pytest tests/test_p2_commands.py -q`

Expected: failure because `references/repos.lock.yaml` and P2 report evidence do not exist.

- [ ] **Step 3: Run the complete live metadata resolution**

Run: `UV_CACHE_DIR=.cache/uv uv run python scripts/fetch_reference.py --all-metadata-only`

Expected: eventual 45 resolved entries and atomic publication of
`references/repos.lock.yaml`. The unauthenticated 60-request/hour limit means this
command may exit resumably across multiple invocations/rate windows. Preserve exact
command/error/reset evidence, reuse only validated cache entries, and keep
independent P3-local baseline planning active; never fabricate a lock entry or wait
inside one invocation for an unbounded reset interval.

- [ ] **Step 4: Run the complete offline audit and verification suite**

Run:

```bash
UV_CACHE_DIR=.cache/uv uv run python scripts/audit_references.py --require-complete
UV_CACHE_DIR=.cache/uv uv lock --check
UV_CACHE_DIR=.cache/uv uv run pytest -q
make safety-check
git diff --check
```

Expected: all commands exit zero; physical deployment is false; remote execution is false.

- [ ] **Step 5: Bind evidence and advance state**

Record the P2 implementation commit, registry digest, retrieval interval, entry/path/
license counts, exact commands, failures/retries, and source-boundary scan in
`RUN_REPORT.md`. Add the P2/P3 split, root-glob semantics, GitHub-license caveat,
and bootstrap-entry merge to `docs/ASSUMPTIONS.md`. Set `p2: complete`,
`p3: in_progress`, `current_pass: 3`, and leave all experiment lanes pending.

- [ ] **Step 6: Verify the final report commit changes evidence only**

Run the full suite again, verify no secrets/large binaries/checkouts are tracked,
verify the worktree is clean, and confirm the report/state commit contains only the
lock, assumptions, manifest, report generator/test, and run report.

- [ ] **Step 7: Commit Task 4**

```bash
git add references/repos.lock.yaml scripts/write_p2_report.py tests/test_p2_commands.py docs/ASSUMPTIONS.md docs/RUN_MANIFEST.yaml RUN_REPORT.md
git commit -m "chore: verify P2 source metadata gate"
```

# P1 Shared Contracts and Rollout Harness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the smallest versioned shared-contract package and deterministic artifact/replay harness that later Reflect-Lite experiments can consume without inventing incompatible schemas.

**Architecture:** Keep domain contracts in focused modules under `reflect/`, validate every cross-boundary value before serialization, and write a canonical rollout directory containing JSON metadata/config/metrics, JSONL events, NumPy observations, and Parquet actions. A replay reader reconstructs ordered events, accepted/rejected chunks, skill state, recovery decisions, memory mutations, world-model rankings, and executed control references without rerunning physics.

**Tech Stack:** CPython 3.11.13, frozen dataclasses and enums, NumPy 2.x arrays, PyArrow 21.x Parquet, PyYAML 6.x, pytest 9.x, uv lockfile.

## Global Constraints

- Physical deployment remains disabled and every artifact-producing or replay command calls `SafetyConfig.require_simulation_only()` before doing work.
- Remote execution remains disabled; P1 performs no network access after dependencies are locked.
- Shared code contains only Section 10 contracts, virtual-clock support, validation, artifact I/O, and replay; no simulator, controller, policy, database, or experiment-specific threshold is introduced.
- Artifact schema version is exactly `1`; incompatible versions fail closed.
- All array inputs are copied into C-contiguous, read-only NumPy arrays so callers cannot mutate serialized meaning after validation.
- All timestamps and sequence IDs are non-negative integers; event monotonic timestamps and sequence IDs are nondecreasing within one rollout.
- JSON is canonicalized with sorted keys and compact separators before hashing; all hashes use SHA-256.
- `actions.parquet` is genuine Parquet written through PyArrow, never a differently formatted file with a Parquet suffix.
- Replay does not rerun physics and performs no network access.
- Tests use temporary directories and deterministic synthetic data only.

---

### Task 1: Locked array dependencies and shared semantic contracts

**Files:**
- Modify: `pyproject.toml`
- Modify: `uv.lock`
- Modify: `references/bootstrap-tools.yaml`
- Create: `reflect/types.py`
- Create: `tests/test_types.py`

**Interfaces:**
- Consumes: standard-library dataclasses/enums/mappings and `numpy.ndarray`.
- Produces: `Pose`, `RobotState`, `Constraint`, `Predicate`, `SemanticGoal`, `SkillSpec`, `Observation`, `ActionChunk`, `ControlReference`, `ObjectBelief`, `SceneRelation`, `SkillState`, `RecoveryDecision`, `WorldModelPrediction`, `ActionRepresentation`, `validate_contract(value: object) -> None`, and `ContractValidationError`.

- [ ] **Step 1: Write failing contract tests**

Create `tests/test_types.py` with constructors for every Section 10 type and assertions that:

```python
def test_action_chunk_copies_and_freezes_actions() -> None:
    source = np.array([[0.1, 0.2], [0.3, 0.4]])
    chunk = valid_action_chunk(actions=source)
    source[0, 0] = 99.0
    assert chunk.actions[0, 0] == pytest.approx(0.1)
    assert chunk.actions.flags.c_contiguous
    assert not chunk.actions.flags.writeable


@pytest.mark.parametrize(
    "change, message",
    [
        ({"source_observation_id": -1}, "source_observation_id"),
        ({"expires_at_ns": 9, "valid_from_ns": 10}, "expires_at_ns"),
        ({"dt_s": 0.0}, "dt_s"),
        ({"actions": np.array([[np.nan]])}, "finite"),
        ({"representation": "NOT_A_REPRESENTATION"}, "representation"),
    ],
)
def test_action_chunk_rejects_invalid_boundaries(change, message) -> None:
    with pytest.raises(ContractValidationError, match=message):
        valid_action_chunk(**change)
```

Also cover confidence bounds `[0, 1]`, non-negative timestamps, finite world-model scores/latency, non-empty identifiers, positive `SkillSpec.timeout_s`, non-negative retry budgets, and array-copy behavior for every optional array field.

- [ ] **Step 2: Run the focused test and prove RED**

Run: `UV_CACHE_DIR=.cache/uv uv run pytest tests/test_types.py -q`

Expected: collection fails because `reflect.types` does not exist.

- [ ] **Step 3: Declare and lock only the required array dependencies**

Set the project dependencies in `pyproject.toml` to:

```toml
dependencies = [
  "numpy>=2.3,<3",
  "pyarrow>=21,<22",
  "PyYAML>=6.0.2,<7",
]
```

Add `numpy` and `pyarrow` entries to `references/bootstrap-tools.yaml` with `mode: DIRECT_DEPENDENCY`, `experiments: [bootstrap]`, no selected source paths, and justifications limited to typed arrays/NPZ and genuine Parquet artifact I/O. Run `UV_CACHE_DIR=.cache/uv uv lock --python 3.11.13`.

- [ ] **Step 4: Implement minimal stable contracts and validation**

Create `reflect/types.py` with the exact Section 10 field names. Define the missing compact types as:

```python
@dataclass(frozen=True)
class Pose:
    position: np.ndarray
    quaternion_wxyz: np.ndarray


@dataclass(frozen=True)
class RobotState:
    q: np.ndarray
    dq: np.ndarray


@dataclass(frozen=True)
class Constraint:
    kind: str
    parameters: Mapping[str, JSONValue]


@dataclass(frozen=True)
class Predicate:
    kind: str
    parameters: Mapping[str, JSONValue]
```

Define `ActionRepresentation(str, Enum)` with exactly `JOINT_POSITION`, `JOINT_DELTA`, `JOINT_VELOCITY`, `EEF_DELTA`, `EEF_TRAJECTORY`, `MPC_GOAL`, and `BOUNDED_RESIDUAL`. Preserve `ActionChunk.representation: str` for wire compatibility but reject values outside that enum. In each dataclass `__post_init__`, normalize mappings to `MappingProxyType(dict(value))`, tuples to tuples, and arrays through a helper that copies with `np.array(value, dtype=np.float64, copy=True, order="C")`, rejects nonfinite values and wrong rank/shape, then sets `writeable=False`.

`validate_contract` dispatches by supported dataclass and raises `ContractValidationError` for unsupported values. Constructors must validate automatically, so no invalid contract can exist merely because a caller forgot to call the dispatcher.

- [ ] **Step 5: Run focused and regression tests**

Run: `UV_CACHE_DIR=.cache/uv uv run pytest tests/test_types.py -q`

Expected: all contract tests pass.

Run: `UV_CACHE_DIR=.cache/uv uv run pytest -q`

Expected: all P0 and P1 Task 1 tests pass.

- [ ] **Step 6: Commit Task 1**

```bash
git add pyproject.toml uv.lock references/bootstrap-tools.yaml reflect/types.py tests/test_types.py
git commit -m "feat: add validated shared contracts"
```

---

### Task 2: Virtual monotonic clock and execution-event schema

**Files:**
- Create: `reflect/clock.py`
- Create: `reflect/events.py`
- Create: `tests/test_clock.py`
- Create: `tests/test_events.py`

**Interfaces:**
- Consumes: `SkillState` and `RecoveryDecision` from `reflect.types`.
- Produces: `Clock` protocol, `SystemClock`, `VirtualClock`, `ExecutionEventType`, `ExecutionEvent`, `EventStream`, `EventValidationError`, `event_to_dict(event) -> dict[str, JSONValue]`, and `event_from_dict(raw) -> ExecutionEvent`.

- [ ] **Step 1: Write failing clock and event tests**

Create deterministic tests demonstrating:

```python
def test_virtual_clock_advances_only_explicitly() -> None:
    clock = VirtualClock(start_ns=100)
    assert clock.monotonic_ns() == 100
    clock.advance_ns(25)
    assert clock.monotonic_ns() == 125
    with pytest.raises(ValueError, match="non-negative"):
        clock.advance_ns(-1)


def test_event_stream_rejects_time_or_sequence_regression() -> None:
    stream = EventStream("rollout-1")
    stream.append(valid_event(monotonic_time_ns=10, sequence_id=2))
    with pytest.raises(EventValidationError, match="monotonic"):
        stream.append(valid_event(monotonic_time_ns=9, sequence_id=3))
    with pytest.raises(EventValidationError, match="sequence"):
        stream.append(valid_event(monotonic_time_ns=11, sequence_id=1))
```

Cover all 19 minimum Section 10.10 event names, rollout-ID consistency, non-empty component/config hash, JSON-safe payloads, optional `object_ids` and `skill_id`, exact dictionary round-trip, and deterministic iteration order.

- [ ] **Step 2: Run the focused tests and prove RED**

Run: `UV_CACHE_DIR=.cache/uv uv run pytest tests/test_clock.py tests/test_events.py -q`

Expected: collection fails because `reflect.clock` and `reflect.events` do not exist.

- [ ] **Step 3: Implement the clock abstraction**

Create `reflect/clock.py`:

```python
class Clock(Protocol):
    def monotonic_ns(self) -> int:
        raise NotImplementedError

    def wall_time_ns(self) -> int:
        raise NotImplementedError


class SystemClock:
    def monotonic_ns(self) -> int:
        return time.monotonic_ns()

    def wall_time_ns(self) -> int:
        return time.time_ns()


@dataclass
class VirtualClock:
    start_ns: int = 0
    wall_start_ns: int = 0

    def __post_init__(self) -> None:
        self._monotonic_ns = checked_non_negative_int(self.start_ns, "start_ns")
        self._wall_time_ns = checked_non_negative_int(
            self.wall_start_ns, "wall_start_ns"
        )

    def monotonic_ns(self) -> int:
        return self._monotonic_ns

    def wall_time_ns(self) -> int:
        return self._wall_time_ns

    def advance_ns(self, duration_ns: int) -> int:
        duration = checked_non_negative_int(duration_ns, "duration_ns")
        self._monotonic_ns += duration
        self._wall_time_ns += duration
        return self._monotonic_ns
```

`SystemClock` wraps `time.monotonic_ns()` and `time.time_ns()`. `VirtualClock` rejects booleans and negative integers for all time arguments and advances wall and monotonic time by the same explicit duration.

- [ ] **Step 4: Implement event types, validation, stream ordering, and wire conversion**

Create `ExecutionEventType(str, Enum)` with the canonical 19 values. Create:

```python
@dataclass(frozen=True)
class ExecutionEvent:
    event_type: ExecutionEventType
    monotonic_time_ns: int
    wall_time_ns: int
    rollout_id: str
    sequence_id: int
    component: str
    config_hash: str
    object_ids: tuple[str, ...] = ()
    skill_id: str | None = None
    payload: Mapping[str, JSONValue] = field(default_factory=dict)
```

Reject non-JSON payload values recursively, nonfinite floats, invalid IDs/timestamps, and unknown event types. `EventStream.append` accepts equal timestamps/sequence IDs but rejects regression and a mismatched rollout ID. `event_to_dict` emits only JSON primitives and enum values; `event_from_dict` rejects missing or extra keys and reconstructs the exact event.

- [ ] **Step 5: Run focused and regression tests**

Run: `UV_CACHE_DIR=.cache/uv uv run pytest tests/test_clock.py tests/test_events.py -q`

Expected: all clock/event tests pass.

Run: `UV_CACHE_DIR=.cache/uv uv run pytest -q`

Expected: all tests pass.

- [ ] **Step 6: Commit Task 2**

```bash
git add reflect/clock.py reflect/events.py tests/test_clock.py tests/test_events.py
git commit -m "feat: add deterministic execution events"
```

---

### Task 3: Canonical rollout artifact writer and validator

**Files:**
- Create: `reflect/rollout.py`
- Create: `tests/test_rollout.py`

**Interfaces:**
- Consumes: `Observation`, `ActionChunk`, `ControlReference`, `ExecutionEvent`, `event_to_dict`, and the P0 safety guard.
- Produces: `SCHEMA_VERSION`, `RolloutMetadata`, `RolloutRecord`, `RolloutWriter`, `RolloutArtifact`, `RolloutValidationError`, `canonical_json_bytes(value) -> bytes`, `sha256_json(value) -> str`, `load_rollout(path: Path) -> RolloutArtifact`, `validate_rollout(path: Path) -> RolloutArtifact`, and `main(argv=None) -> int` with a `replay` subcommand stub wired to Task 4.

- [ ] **Step 1: Write failing artifact tests**

Create `tests/test_rollout.py` with a minimal two-observation/two-action/event rollout. Assert that `RolloutWriter.write()` creates exactly:

```text
metadata.json
config.json
metrics.json
events.jsonl
observations.npz
actions.parquet
summary.md
```

Assert `pyarrow.parquet.read_table()` can read `actions.parquet`; metadata includes all required Section 24 fields and content hashes; observations retain sequence/time/robot arrays; action rows retain chunk IDs, time bounds, `dt_s`, representation, shape, flattened values, and canonical metadata JSON; and a second write with identical inputs produces identical file bytes except explicitly measured wall-clock metadata supplied by the caller.

Add corruption tests for missing files, unknown schema versions, hash mismatch, event ordering regression, action/observation IDs not referenced consistently, nonfinite stored actions, unsafe physical flag, and a target path outside the caller-provided output root.

- [ ] **Step 2: Run the focused test and prove RED**

Run: `UV_CACHE_DIR=.cache/uv uv run pytest tests/test_rollout.py -q`

Expected: collection fails because `reflect.rollout` does not exist.

- [ ] **Step 3: Implement metadata and canonical hashing**

Define `RolloutMetadata` with the Section 24 fields:

```python
@dataclass(frozen=True)
class RolloutMetadata:
    experiment_id: str
    claim_revision: int
    git_sha: str
    dirty_diff_hash: str | None
    source_lock_hash: str
    os_arch: str
    cpu: str
    gpu: str | None
    python_version: str
    dependency_versions: Mapping[str, str]
    seed: int
    simulator: str
    task_config_hash: str
    model_hashes: Mapping[str, str]
    action_schema_version: int
    observation_schema_version: int
    wall_start_ns: int
    wall_end_ns: int
    monotonic_start_ns: int
    monotonic_end_ns: int
    status: str
    physical_deployment_allowed: bool = False
```

Allow status only from `pass`, `fail`, `blocked`, and `interrupted`; reject dirty state without a diff hash, invalid SHA-256 strings, time regression, booleans where integers are required, and `physical_deployment_allowed=True`. `canonical_json_bytes` recursively normalizes enums, tuples, immutable mappings, NumPy scalars, and arrays, rejects nonfinite numbers, then uses `json.dumps(..., sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")`.

- [ ] **Step 4: Implement bounded atomic artifact writing**

`RolloutWriter(output_root, rollout_id)` resolves both paths and rejects traversal outside `output_root`. It accepts one immutable `RolloutRecord` containing metadata, config, metrics, events, observations, actions, optional control references, and a summary string. Before any write it calls the P0 simulation-only guard and validates all contracts and cross-references.

Write into a sibling temporary directory created with `tempfile.mkdtemp(dir=output_root)`, fsync/close files, then atomically rename to the absent final rollout directory. On failure, remove only that exact temporary directory. Refuse to overwrite an existing rollout. Store observations as deterministic named arrays in `observations.npz` and actions/control references in columns of `actions.parquet`, using fixed PyArrow schemas and Zstandard compression. Store event lines with `canonical_json_bytes(event_to_dict(event)) + b"\n"`. Add each payload file's SHA-256 to `metadata.json` under `artifact_hashes` after writing the payloads.

- [ ] **Step 5: Implement strict loading and validation**

`load_rollout` parses only the declared files and reconstructs contracts without trusting pickles. `validate_rollout` verifies exact required files, schema versions, every artifact hash, metadata safety, event order, array finiteness/shapes, action expiry/time semantics, and all event/action/observation cross-references. Extra files are allowed only for the Section 24 optional names (`candidates.parquet`, `memory_snapshots.jsonl`, `video.mp4`); every extra required-data file must be listed and hashed in metadata.

- [ ] **Step 6: Run focused and regression tests**

Run: `UV_CACHE_DIR=.cache/uv uv run pytest tests/test_rollout.py -q`

Expected: all rollout artifact tests pass.

Run: `UV_CACHE_DIR=.cache/uv uv run pytest -q`

Expected: all tests pass.

- [ ] **Step 7: Commit Task 3**

```bash
git add reflect/rollout.py tests/test_rollout.py
git commit -m "feat: add canonical rollout artifacts"
```

---

### Task 4: Deterministic replay reconstruction and CLI

**Files:**
- Modify: `reflect/rollout.py`
- Create: `reflect/replay.py`
- Create: `tests/test_replay.py`
- Modify: `Makefile`

**Interfaces:**
- Consumes: validated `RolloutArtifact`, canonical execution events, action/control-reference rows.
- Produces: `ReplayState`, `ReplayFrame`, `ReplayResult`, `replay_rollout(path: Path) -> ReplayResult`, `format_replay(result) -> str`, and working `python -m reflect.rollout replay PATH` / `make replay RUN=PATH` entry points.

- [ ] **Step 1: Write failing state-reconstruction and CLI tests**

Construct one rollout whose events exercise:

```text
OBSERVATION_RECEIVED
CHUNK_ACCEPTED
CHUNK_REJECTED_EXPIRED
CHUNK_REPLACED
ACTION_EXECUTED
SKILL_RETRIGGERED
MEMORY_UPDATED
WORLD_MODEL_PREDICTED
WORLD_MODEL_SELECTED
SKILL_SUCCEEDED
```

Assert replay frames are ordered by `(monotonic_time_ns, sequence_id, original_line_index)`, the final state contains accepted/rejected/replaced chunk IDs, `SkillState.SUCCEEDED`, `RecoveryDecision.RETRIGGER`, memory mutation count, selected world-model candidate, and the exact executed `ControlReference`. Assert the CLI emits canonical JSON with rollout ID, event/frame counts, final skill state, and no environment-dependent formatting. Assert corruption returns exit code 2 and writes one concise error to stderr.

- [ ] **Step 2: Run the focused test and prove RED**

Run: `UV_CACHE_DIR=.cache/uv uv run pytest tests/test_replay.py -q`

Expected: collection fails because `reflect.replay` does not exist.

- [ ] **Step 3: Implement pure replay reduction**

Create immutable `ReplayState`, `ReplayFrame`, and `ReplayResult`. `replay_rollout` calls `validate_rollout`, then folds events through one pure reducer. Required payload keys are explicit per state-changing event: chunk events require `chunk_id`; skill terminal events require no inferred state; recovery events map retrigger/escalation/failure to the corresponding enum or state; `MEMORY_UPDATED` requires `mutation_id`; world-model events require `candidate_id`; `ACTION_EXECUTED` requires `source_chunk_id` and resolves the saved control reference. Missing or ambiguous payloads raise `RolloutValidationError` rather than guessing.

- [ ] **Step 4: Wire the replay command**

Implement `reflect.rollout.main` with:

```text
python -m reflect.rollout replay RESULTS_PATH
```

It parses exactly one path, performs the simulation-only safety check, calls `replay_rollout`, prints `format_replay` canonical JSON, and returns 0. Invalid artifacts return 2. Add:

```makefile
replay:
	@test -n "$(RUN)" || (echo "RUN is required" >&2; exit 2)
	$(UV) run python -m reflect.rollout replay "$(RUN)"
```

- [ ] **Step 5: Run focused, CLI, and regression tests**

Run: `UV_CACHE_DIR=.cache/uv uv run pytest tests/test_replay.py -q`

Expected: all replay tests pass.

Run: `UV_CACHE_DIR=.cache/uv uv run pytest -q`

Expected: all tests pass.

Run: `UV_CACHE_DIR=.cache/uv uv run pytest tests/test_replay.py::test_rollout_cli_emits_canonical_summary -q`

Expected: exit 0 and one canonical JSON replay summary.

- [ ] **Step 6: Commit Task 4**

```bash
git add reflect/rollout.py reflect/replay.py tests/test_replay.py Makefile
git commit -m "feat: reconstruct rollout state by replay"
```

---

### Task 5: P1 end-to-end fixture, documentation, and gate evidence

**Files:**
- Create: `scripts/write_p1_fixture.py`
- Create: `tests/test_p1_commands.py`
- Modify: `Makefile`
- Modify: `.gitignore`
- Modify: `docs/ASSUMPTIONS.md`
- Modify: `docs/RUN_MANIFEST.yaml`
- Modify: `RUN_REPORT.md`

**Interfaces:**
- Consumes: all P1 shared contracts, event stream, artifact writer/validator, and replay command.
- Produces: `make p1-fixture`, `make replay RUN=results/bootstrap/p1-fixture`, P1 command-level evidence, and durable transition to P2.

- [ ] **Step 1: Write failing command-level tests**

Create `tests/test_p1_commands.py` that copies the repository inputs needed by the script into `tmp_path`, executes the module in a subprocess with an explicit output directory, and asserts:

```python
assert completed.returncode == 0
assert artifact_path.joinpath("actions.parquet").is_file()
assert replay.returncode == 0
assert json.loads(replay.stdout)["rollout_id"] == "p1-fixture"
```

Also assert a second fixture write refuses overwrite, physical enablement fails before artifact creation, and `make replay` without `RUN` exits 2.

- [ ] **Step 2: Run the focused test and prove RED**

Run: `UV_CACHE_DIR=.cache/uv uv run pytest tests/test_p1_commands.py -q`

Expected: failure because `scripts/write_p1_fixture.py` and `make p1-fixture` do not exist.

- [ ] **Step 3: Implement one deterministic end-to-end fixture command**

Create `scripts/write_p1_fixture.py` with `--output-dir` defaulting to `results/bootstrap`. It uses `VirtualClock`, one valid observation, one accepted action chunk, one executed control reference, and a succeeding skill event sequence. All values, seeds, hashes, start/end times, platform strings, config, metrics, and summary are explicit constants so byte-for-byte repeatability can be tested in separate output roots.

Add Make targets:

```makefile
p1-fixture:
	$(UV) run python scripts/write_p1_fixture.py --output-dir results/bootstrap

p1-check: test p1-fixture
	$(UV) run python -m reflect.rollout replay results/bootstrap/p1-fixture
```

Add `results/` to `.gitignore`; tests must create their own temporary outputs.

- [ ] **Step 4: Record P1 decisions and durable state**

Append these resolved assumptions to `docs/ASSUMPTIONS.md`: NumPy/NPZ plus genuine PyArrow Parquet was selected over a custom pseudo-Parquet or database; replay is an event reducer and does not rerun physics; metadata callers supply measured environment fields; equal event timestamp/sequence values preserve original JSONL order. Update `docs/RUN_MANIFEST.yaml` only after all P1 checks pass: `p1: complete`, `p2: in_progress`, `current_pass: 2`.

Regenerate `RUN_REPORT.md` with exact code SHA, test count, lock verification, fixture/replay commands and outputs, safety checks, artifact hashes, limitations, and P2 as the highest-value next bounded action. Do not claim that P2 source auditing or any empirical experiment has run.

- [ ] **Step 5: Run the complete P1 gate**

Run:

```bash
UV_CACHE_DIR=.cache/uv uv lock --check
UV_CACHE_DIR=.cache/uv uv run pytest -q
make safety-check
env PHYSICAL_DEPLOYMENT_ALLOWED=true REFLECT_REMOTE_ENABLED=0 make safety-check
```

Expected: lock check, suite, and normal safety check exit 0; the physical-enablement negative control exits nonzero before any write.

Run a fixture and replay in a new temporary output root, compare a second independently generated fixture for deterministic payload hashes, then remove only those explicit temporary directories. Expected: validation/replay exit 0 and payload hashes match.

Run:

```bash
git diff --check
git status --short
git ls-files '.env' '*.pt' '*.pth' '*.ckpt' '*.safetensors' 'results/**' 'external/**' '.worktrees/**' '.superpowers/**'
find . -path ./.git -prune -o -path ./.venv -prune -o -path ./.cache -prune -o -path ./.superpowers -prune -o -type f -size +100M -print
```

Expected: no whitespace errors, no forbidden tracked files, and no unapproved large artifacts.

- [ ] **Step 6: Commit Task 5**

```bash
git add scripts/write_p1_fixture.py tests/test_p1_commands.py Makefile .gitignore docs/ASSUMPTIONS.md docs/RUN_MANIFEST.yaml RUN_REPORT.md
git commit -m "chore: verify P1 rollout harness"
```

P1 is complete only after an independent final reviewer verifies the implementation diff against this plan and the canonical Sections 10, 24, 25, and 27 requirements.

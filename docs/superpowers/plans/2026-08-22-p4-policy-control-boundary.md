# P4 Policy-to-Controller Boundary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement Experiment 01's deterministic six-stack MuJoCo comparison and mechanically promote at most two eligible command stacks without claiming representation-only causality.

**Architecture:** All task code stays in `experiments/01_policy_control/`; existing `reflect` contracts, clock, events, rollout writer, validator, and replay remain unchanged. Pure contracts feed independent arm, kinematics, and timing units; representation work is serial; evaluation and evidence integrate them. Every source, test, CLI, freeze, and report path is complete and reviewed before a live pilot; pilot, freeze, unseen confirmation, confirmation, and analysis are serial and bound to one unchanged implementation SHA.

**Tech Stack:** CPython 3.11.13, NumPy, PyYAML, PyArrow, pytest, P3-locked MuJoCo, `reflect.types`, `reflect.clock`, `reflect.events`, `reflect.rollout`, `reflect.replay`, and `reflect.safety`.

## Global Constraints

- P3 must pass `scripts/audit_references.py --require-complete` and `scripts/source_audit.py --check`; its P2 lock, operation manifest, compatibility CSV, licenses, source map, report, and MuJoCo smoke are immutable inputs.
- Reject physical or remote execution before importing MuJoCo or creating output. No ROS, CUDA, Mink, MJPC, Menagerie, mjctrl, Rerun, copied source, model, or physical/remote adapter.
- Use exact 3R values: links `.30/.25/.20 m`, joint limits `[-2.70,2.70]`, damping `.10`, torque `[-12,12]`, zero gravity, `dt=.002 s`, 6.25 s.
- `ActionChunk.representation` is a string. Stack identity is only `metadata["stack_id"]`.
- Global shared PD/IK applies to every survivor; only P5 has a separate smoothness selection.
- Rollouts are create-only, `<=1 MiB`; resume is full validate-and-skip. One shard is `<=27` episodes, `<=168.75` simulated seconds, `<=60` wall minutes.
- Raw `experiments/01_policy_control/results/` stays ignored/local. Commit only source/tests/configs, small manifests/digests/SVGs/reports.
- All commands run from repository root with `UV_CACHE_DIR=.cache/uv uv run`.

## Files, ownership, and waves

| File | Responsibility | Ownership |
|---|---|---|
| `experiments/01_policy_control/src/contracts.py` | strict config/local immutable types/hashes | Task 1 only |
| `experiments/01_policy_control/src/p3_gate.py` | P2/P3 gate without MuJoCo import | Task 2 only |
| `experiments/01_policy_control/src/arm.py` | MJCF, state/step, common PD/clamps | Task 3 only |
| `experiments/01_policy_control/src/kinematics.py` | shared FK/Jacobian/IK/interpolation | Task 4 only |
| `experiments/01_policy_control/src/representations.py` | P1-P6 policy/executor | Tasks 5→6→7 serial |
| `experiments/01_policy_control/src/timing.py` | request/delivery/expiry/safe hold | Task 8 only |
| `experiments/01_policy_control/src/evaluate.py` | scenarios/episodes/metrics/pilot/inference/plots | Tasks 9→10→11 serial |
| `experiments/01_policy_control/src/artifacts.py`, `experiments/01_policy_control/run.py` | manifests/artifacts/CLI/freeze/report | Task 12 serial integration |

For subagent-driven development, all implementers run serially with a fresh review gate:
Tasks 1→2→3→4→5→6→7→8→9→10→11→12. Task 4 depends on Task 3 because
its MuJoCo comparison and GREEN command consume the reviewed arm/MJCF fixture. Task 8
has disjoint files but remains serial under the required workflow. Live evidence is
serial orchestrator ownership after Task 12.

---

### Task 1: Contracts and complete base configuration

**Files:** Verify the P3-owned `experiments/__init__.py` byte-for-byte without editing it; create `experiments/01_policy_control/__init__.py`, `experiments/01_policy_control/src/__init__.py`, `experiments/01_policy_control/src/contracts.py`, `experiments/01_policy_control/configs/base.yaml`, `experiments/01_policy_control/tests/test_contracts.py`.

**Interfaces:** Define before use: `CommandStack(P1..P6)`, `FaultKind(NONE,DROP,OUT_OF_ORDER,STATIONARY_CONTROL)`, frozen `ArmConfig`, `ControllerConfig`, `TimingConfig`, `ResourceConfig`, `ExperimentConfig`, `Condition`, `Scenario`, `PolicyInput`, `ExecutorState`, `ClampReport`, `EpisodeMetrics`, `SeedMetrics`, `ShardSpec`; `load_config(Path)->ExperimentConfig`, `canonical_json_bytes`, `sha256_file`. `PolicyInput` contains `Observation`, `SkillSpec`, response time, policy period, initial q, initial-target IK q. `ExecutorState` contains active ID, latched q, P5 previous velocity/planner reference/enabled.

- [ ] **RED test**

```python
def test_exact_base() -> None:
    assert (ROOT / "experiments/__init__.py").is_file()  # P3-owned, verify-only
    cfg = load_config(BASE)
    assert cfg.arm.link_lengths_m == (.30,.25,.20)
    assert cfg.timing.episode_ticks == 3125
    assert cfg.controller.pd_candidates == ((80.,8.),(60.,6.),(100.,10.))
    assert cfg.controller.ik_damping_candidates == (.01,.001,.05)
    assert cfg.controller.mpc_smoothness_candidates == (.02,.01,.04)
```

Run: `UV_CACHE_DIR=.cache/uv uv run pytest experiments/01_policy_control/tests/test_contracts.py -q`

Expected: collection FAIL, missing `contracts`.

- [ ] **GREEN implementation**

```python
class CommandStack(str, Enum):
    P1="P1"; P2="P2"; P3="P3"; P4="P4"; P5="P5"; P6="P6"

@dataclass(frozen=True)
class ExecutorState:
    active_chunk_id: str | None
    latched_q_ref: np.ndarray
    p5_qdot_previous: np.ndarray
    p5_planner_q_ref: np.ndarray
    p5_planner_enabled: bool

@dataclass(frozen=True)
class Condition:
    condition_id: str
    policy_hz: int
    latency_ms: int
    move_count: int
    fault: FaultKind
```

Every array constructor copies float64 C-order bytes and marks them read-only. Strict YAML rejects missing/extra keys, booleans-as-int, and nonfinite values. `base.yaml` records every number in spec §§Arm, stacks, timing, metrics, pilot, confirmation, thresholds, resources: exact IK equations/constants; MPC 79-candidate grid/cost; P6 nominal; 5/10/20 Hz, 0/100/300/700 ms, 1/2 moves; two probes/control; 8 pilot seeds split 4+4, two revisions; 32/64 confirmation; 10,000 bootstrap; `-.10/+.10`, `.95/.90`, `.01/.05`, `1.5`; `1 MiB/60 min/7,544 MiB`.

Run: `UV_CACHE_DIR=.cache/uv uv run pytest experiments/01_policy_control/tests/test_contracts.py tests/test_types.py -q`

Expected: PASS.

```bash
git add experiments/01_policy_control/__init__.py experiments/01_policy_control/src/__init__.py experiments/01_policy_control/src/contracts.py experiments/01_policy_control/configs/base.yaml experiments/01_policy_control/tests/test_contracts.py
git commit -m "feat: define experiment 01 contracts"
```

---

### Task 2: Authentic P3 gate and pre-import live safety

**Files:** Create `experiments/01_policy_control/src/p3_gate.py`, `experiments/01_policy_control/run.py`, `experiments/01_policy_control/tests/test_p3_gate.py`.

**Interfaces:** `EvidenceFile(path: PurePosixPath,sha256:str)`; `P3GateEvidence` fields `p2_lock`, `operation_manifest`, `compatibility_csv`, `licenses`, `source_map`, `p3_results`, `run_manifest`, `mujoco_smoke`, package/version/artifact hash, physical/remote booleans; `load_p3_gate`, `require_p3_gate`, `write_p3_gate(repo_root: Path, destination: Path) -> None`, and `python -m experiments.01_policy_control.src.p3_gate --write PATH`.

- [ ] **RED test**

```python
def test_remote_fails_before_import_or_output(tmp_path, monkeypatch):
    monkeypatch.setenv("REFLECT_REMOTE_ENABLED","1")
    sys.modules.pop("mujoco",None)
    assert main(valid_args(tmp_path)) == 2
    assert "mujoco" not in sys.modules and not (tmp_path/"out").exists()

def test_tampered_source_map_fails(tmp_path):
    evidence = p3_fixture(tmp_path)
    require_p3_gate(tmp_path,evidence)
    (tmp_path/"docs/SOURCE_MAP.md").write_text("tamper")
    with pytest.raises(P3GateError,match="source_map hash mismatch"):
        require_p3_gate(tmp_path,evidence)
```

Run: `UV_CACHE_DIR=.cache/uv uv run pytest experiments/01_policy_control/tests/test_p3_gate.py -q`

Expected: collection FAIL with missing `p3_gate`.

- [ ] **GREEN implementation**

Require exact root-relative paths `references/repos.lock.yaml`, `experiments/00_source_audit/configs/operation-manifest.yaml`, `experiments/00_source_audit/results/compatibility.csv`, `references/licenses.md`, `docs/SOURCE_MAP.md`, `experiments/00_source_audit/RESULTS.md`, `docs/RUN_MANIFEST.yaml`; obtain the exact fragment under `experiments/00_source_audit/results/fragments/` from the digest-bound operation manifest. Reject absolute/`..`/symlink/nonregular paths and hash mismatches. Use P3 loaders/validators to require all 45 entries, unchanged P2 hash, smoke `PASS`, runtime subject `package`, exact `mujoco` version/artifact, compatibility `WORKS_LOCAL_M2`, `p3: complete`, and safety false. Run P2/P3 checks with argv, not shell.

`write_p3_gate` performs those validations first, derives every SHA from the validated file bytes, takes the MuJoCo package/version/artifact fields from the validated smoke fragment, and publishes canonical YAML create-only. It never accepts user-supplied hashes.

`run.py` top level imports only stdlib, `SafetyConfig`, and gate. Before experiment imports/output:

```python
safety=SafetyConfig.from_mapping(os.environ)
safety.require_simulation_only()
if safety.remote_enabled:
    raise SafetyViolation("Experiment 01 forbids remote execution")
require_p3_gate(REPO_ROOT,load_p3_gate(args.p3_gate))
```

Then import experiment modules inside `main`.

Run: `UV_CACHE_DIR=.cache/uv uv run pytest experiments/01_policy_control/tests/test_p3_gate.py tests/test_safety.py tests/test_source_audit.py -q`

Expected: PASS; unsafe fixtures create no output and do not import MuJoCo.

```bash
git add experiments/01_policy_control/src/p3_gate.py experiments/01_policy_control/run.py experiments/01_policy_control/tests/test_p3_gate.py
git commit -m "feat: gate experiment 01 on P3 evidence"
```

---

### Task 3: Inline arm and common low-level controller

**Files:** Create `experiments/01_policy_control/src/arm.py`, `experiments/01_policy_control/tests/test_arm.py`.

**Interfaces:** `MJCF_BYTES`, `PlanarArm.reset/site_xy/state/step`, `bounded_pd(q,dq,requested_q_ref,previous_q_ref,kp,kd,config)->(q_ref,torque,ClampReport)`.

- [ ] RED: assert timestep, joint/torque ranges, FK site, and `bounded_pd` slew delta `.003` per 2 ms; equality at limit is not clamp.

Run: `MUJOCO_GL=disable UV_CACHE_DIR=.cache/uv uv run pytest experiments/01_policy_control/tests/test_arm.py -q`

Expected: collection FAIL with missing `arm`.
- [ ] GREEN: literal MJCF with exact spec values; import `mujoco` only in constructor. Reject nonfinite pre-clamp input. Implement:

```python
step=config.reference_slew_rad_s*config.timestep_s
delta=requested_q_ref-previous_q_ref
q_ref=previous_q_ref+np.clip(delta,-step,step)
bounded=np.clip(q_ref,config.joint_min_rad,config.joint_max_rad)
raw=kp*(bounded-q)-kd*dq
torque=np.clip(raw,config.torque_min_nm,config.torque_max_nm)
```

Return copies; clamp booleans use actual pre-clamp exceedance. Run exactly:

```text
MUJOCO_GL=disable UV_CACHE_DIR=.cache/uv uv run pytest experiments/01_policy_control/tests/test_arm.py -q
```

Expected: PASS.

```bash
git add experiments/01_policy_control/src/arm.py experiments/01_policy_control/tests/test_arm.py
git commit -m "feat: add deterministic planar arm"
```

---

### Task 4: Shared kinematics and interpolation

**Files:** Create `experiments/01_policy_control/src/kinematics.py`, `experiments/01_policy_control/tests/test_kinematics.py`.

**Interfaces:** `forward_kinematics`, `jacobian`, `clip_norm`, `damped_pseudoinverse`, `absolute_ik`, `differential_ik_reference`, `linear_knot_reference` with ndarray signatures from spec.

- [ ] RED: compare Jacobian to centered `1e-7` differences and FK to MuJoCo; repeated IK bytes equal; closed interpolation endpoints exact.

Run only after Task 3 has passed review: `MUJOCO_GL=disable UV_CACHE_DIR=.cache/uv uv run pytest experiments/01_policy_control/tests/test_kinematics.py -q`

Expected: collection FAIL with missing `kinematics`.
- [ ] GREEN:

```python
def absolute_ik(target,q0,links,damping):
    q=np.array(q0,dtype=np.float64,copy=True); posture=np.array([.35,-.70,.35])
    for _ in range(12):
        j=jacobian(q,links); jh=j.T@np.linalg.inv(j@j.T+damping*damping*np.eye(2))
        n=np.eye(3)-jh@j
        q=np.clip(q+clip_norm(jh@(target-forward_kinematics(q,links))+.05*n@(posture-q),.10),-2.55,2.55)
    return q
```

Differential IK is exact `clip_norm(4*error,.25)`, null `.20`, qdot per-axis `1.5`, step `.002`. Interpolation derives integer ns knots, closed adjacent intervals, first/final holds.

Run: `MUJOCO_GL=disable UV_CACHE_DIR=.cache/uv uv run pytest experiments/01_policy_control/tests/test_kinematics.py experiments/01_policy_control/tests/test_arm.py -q`

Expected: PASS.

```bash
git add experiments/01_policy_control/src/kinematics.py experiments/01_policy_control/tests/test_kinematics.py
git commit -m "feat: add shared arm kinematics"
```

---

### Task 5: P1-P4 representation unit

**Files:** Create `experiments/01_policy_control/src/representations.py`, `experiments/01_policy_control/tests/test_p1_p4.py`.

**Interfaces:** `emit_chunk(CommandStack,PolicyInput,ExperimentConfig)->ActionChunk`; `reference_for_tick(...)->tuple[ControlReference,ExecutorState,ClampReport]`.

- [ ] RED parametrized test: P1 `(1,3)`/P2 `(H,3)` string `JOINT_POSITION`; P3 `(1,2)`/P4 `(H,2)` string `EEF_TRAJECTORY`; `H=ceil(.8/P)+1`; arrays read-only. Snapshot bytes before/after every stack must equal.

Run: `UV_CACHE_DIR=.cache/uv uv run pytest experiments/01_policy_control/tests/test_p1_p4.py -q`

Expected: collection FAIL with missing `representations`.
- [ ] GREEN common constructor:

```python
ActionChunk(chunk_id=f"{obs.sequence_id}:{stack.value}",skill_id=skill.skill_id,
 source_observation_id=obs.sequence_id,source_observation_time_ns=obs.source_time_ns,
 generated_time_ns=delivery,valid_from_ns=delivery,
 expires_at_ns=delivery+math.ceil(2.5*period_ns),dt_s=period_ns/1e9,
 actions=actions,representation=representation,expected_phase="track_target",
 metadata={"stack_id":stack.value})
```

P1 absolute IK; P2 straight Cartesian knots/sequential absolute IK; P3 held XY/current-q differential IK; P4 linear XY interpolation/current-q differential IK. No live target.

Run: `UV_CACHE_DIR=.cache/uv uv run pytest experiments/01_policy_control/tests/test_p1_p4.py tests/test_types.py -q`

Expected: PASS.

```bash
git add experiments/01_policy_control/src/representations.py experiments/01_policy_control/tests/test_p1_p4.py
git commit -m "feat: add P1 through P4 stacks"
```

---

### Task 6: P5 MPC unit

**Files:** Modify `experiments/01_policy_control/src/representations.py`; create `experiments/01_policy_control/tests/test_p5.py`.

**Interfaces:** `mpc_candidates()->tuple[np.ndarray,...]`, `mpc_cost`, `p5_transition`, P5 branches in Task 5 APIs.

- [ ] RED: exactly 79 candidates, zero first, norms `{0,.25,.75,1.50}`; 4 cm hold `0.888888...` and move `<.136667`; 6 cm hold `2.0`, move `<.295`; infeasible motion loses. Test qdot zero at start, planner update, valid replacement preserve, rejection no-op, expiry/safe-hold zero, reaccept zero, delivery before coincident planner.

Run: `UV_CACHE_DIR=.cache/uv uv run pytest experiments/01_policy_control/tests/test_p5.py -q`

Expected: FAIL because P5 helpers/branches are absent.
- [ ] GREEN: enumerate zero then magnitudes then lexicographic raw directions; ten `.02 s` steps; discard hard-limit crossing. Implement exact dimensionless formula with `dt/T=.1`, normalized error/velocity/smoothness/barrier, terminal error, first-min tie. Planner every 10 simulator ticks; intermediate ticks hold state; all transitions exactly as spec.
- [ ] Run: `UV_CACHE_DIR=.cache/uv uv run pytest experiments/01_policy_control/tests/test_p5.py experiments/01_policy_control/tests/test_p1_p4.py -q`

Expected: PASS.

```bash
git add experiments/01_policy_control/src/representations.py experiments/01_policy_control/tests/test_p5.py
git commit -m "feat: add bounded P5 controller"
```

---

### Task 7: P6 residual unit

**Files:** Modify `experiments/01_policy_control/src/representations.py`; create `experiments/01_policy_control/tests/test_p6.py`, `experiments/01_policy_control/tests/test_information_boundary.py`.

- [ ] RED: representation string `BOUNDED_RESIDUAL`, `(1,3)`, abs residual `<=.25`; repeated snapshot action bytes equal despite a mutated external live target; nominal endpoints byte-equal q0/q1.

Add one adversarial boundary test over `tuple(CommandStack)`. The test constructs an
`Observation` and `SkillSpec` from a mutable `external_target`, constructs and retains
one frozen `PolicyInput`, records `ActionChunk.actions.tobytes()` and the complete
500 Hz sequence of `ControlReference.q_ref`/`dq_ref` bytes, then mutates
`external_target[:]`, replaces the scenario's current target, and repeats emission and
execution from identical q/dq/state. For P1-P6, chunk and reference bytes must remain
identical. The test also asserts `emit_chunk` and `reference_for_tick` accept no live-
target/scenario argument by inspecting their exact signatures.

Run: `UV_CACHE_DIR=.cache/uv uv run pytest experiments/01_policy_control/tests/test_p6.py experiments/01_policy_control/tests/test_information_boundary.py -q`

Expected: FAIL because P6 is absent.
- [ ] GREEN:

```python
s=np.clip(time_ns/1_000_000_000,0.,1.)
h=10*s**3-15*s**4+6*s**5
q_nominal=q_initial+h*(q_initial_target-q_initial)
residual=np.clip(absolute_ik(stale_target,observed_q,links,damping)-q_nominal,-.25,.25)
```

Executor adds accepted residual to open-loop nominal then common slew/PD; no nominal replanning/live target/state feedback.

Run: `UV_CACHE_DIR=.cache/uv uv run pytest experiments/01_policy_control/tests/test_p6.py experiments/01_policy_control/tests/test_p5.py experiments/01_policy_control/tests/test_p1_p4.py experiments/01_policy_control/tests/test_information_boundary.py -q`

Expected: PASS.

```bash
git add experiments/01_policy_control/src/representations.py experiments/01_policy_control/tests/test_p6.py experiments/01_policy_control/tests/test_information_boundary.py
git commit -m "feat: add bounded P6 residual"
```

---

### Task 8: Timing/lifecycle unit

**Files:** Create `experiments/01_policy_control/src/timing.py`, `experiments/01_policy_control/tests/test_timing.py`.

**Interfaces:** define `PolicyRequest`, `ScheduledResponse`, `DeliveryDisposition`, `DeliveryBatch`; `last_request_tick`, `schedule_response`, `deliver_due`.

- [ ] RED:

```python
assert last_request_tick(3125,350,0,50)==2650
assert event_types(stale_fixture())==["POLICY_RESPONDED","CHUNK_REJECTED_OUT_OF_ORDER"]
assert coincident_fixture().observation.current_phase=="track_target"
assert coincident_fixture().event.payload["observation_role"]=="policy_and_telemetry"
```

Run: `UV_CACHE_DIR=.cache/uv uv run pytest experiments/01_policy_control/tests/test_timing.py -q`

Expected: collection FAIL with missing `timing`.

- [ ] GREEN: queue key `(delivery_ns,request_sequence)`. Implement spec's nine tick steps. Source order rejects before execution expiry check, but `POLICY_RESPONDED` always precedes rejection. Replace only a still-valid chunk; after expiry clear/direct accept. Half-open validity. Safe hold latches current q/zero dq, resets P5, emits no reference/action. Exactly declared drop may be unmatched; terminal queue otherwise empty. Coincident telemetry/request uses one Observation/event.
- [ ] Run: `UV_CACHE_DIR=.cache/uv uv run pytest experiments/01_policy_control/tests/test_timing.py tests/test_clock.py tests/test_events.py -q`

Expected: PASS.

```bash
git add experiments/01_policy_control/src/timing.py experiments/01_policy_control/tests/test_timing.py
git commit -m "feat: add virtual timing lifecycle"
```

---

### Task 9: Scenario, episode, and metrics unit

**Files:** Create `experiments/01_policy_control/src/evaluate.py`, `experiments/01_policy_control/tests/test_episode_metrics.py`.

**Interfaces:** `generate_scenario`, `core_conditions`, `probe_conditions`, `negative_control_condition`, `run_episode(...)->RolloutRecord`, `nearest_rank`, `compute_episode_metrics`, `aggregate_seed_metrics`.

- [ ] RED: scenario bytes repeat; a valid scenario may be accepted on one-based proposal `32` but proposal `33` is never attempted (equivalently, zero-based accepted index is `<32`); feasibility/radius rejection recorded; censor exactly `2.0`; nearest-rank p95 `[1..5]` is `5`; equality at clamp limit is not clamp; negative control passes at exactly `.025` and fails above; missing action-age/discontinuity invalidates.

Run: `MUJOCO_GL=disable UV_CACHE_DIR=.cache/uv uv run pytest experiments/01_policy_control/tests/test_episode_metrics.py -q`

Expected: collection FAIL with missing `evaluate`.
- [ ] GREEN: PCG64 named SHA substreams; immutable path record before stacks; fixed feasibility IK `.01`; no stack resampling. Episode is exactly 3,125 ticks, target movement before request, stable `current_phase`, 100 Hz stored telemetry/500 Hz metrics. Use existing `Observation`, `ActionChunk`, `ControlReference`, `ExecutionEvent`, `VirtualClock`, `RolloutRecord`.
- [ ] Implement recovery dwell/censor, last/mean/p95 error, action age, third finite-difference jerk, saturation, discontinuity without safe-hold bridge, unsafe/clamp, serial `perf_counter_ns`. Percentile index `max(0,ceil(p*n)-1)`. Episode recovery averages moves; seed primary averages exactly 24 episodes. Exact missing/negative-control rules.
- [ ] Add a `run_episode` wiring test that monkeypatches `evaluate.emit_chunk` and
`evaluate.reference_for_tick`, captures every positional/keyword argument, and proves
for P1-P6 that policy calls receive only the request-time `PolicyInput`, executor calls
receive only the accepted chunk plus q/dq/time/state/config, and neither call receives
the mutable scenario/live-target object. The captured observation belief and
`SkillSpec.target_pose` must contain byte-identical request-time target snapshots.
- [ ] Run all experiment unit tests including one zero-latency headless episode P1-P6:

```text
MUJOCO_GL=disable UV_CACHE_DIR=.cache/uv uv run pytest experiments/01_policy_control/tests -q
```

Expected: PASS.

```bash
git add experiments/01_policy_control/src/evaluate.py experiments/01_policy_control/tests/test_episode_metrics.py
git commit -m "feat: run experiment 01 episodes"
```

---

### Task 10: Pilot manifests and global selection

**Files:** Modify `experiments/01_policy_control/src/evaluate.py`; create `experiments/01_policy_control/tests/test_pilot_selection.py`.

**Interfaces:** `PilotStage`, `PilotCandidate`, `PilotManifest`, stage builders, `qualify_base`, `select_global_candidate`, `select_p5_smoothness`, `pilot_disposition`.

- [ ] RED: stage order base, two PD, two IK, two P5 smoothness, final-four; in the explicit all-six-survive fixture counts `{P1:164,P2:164,P3:164,P4:164,P5:188,P6:164}`, total `1008`; a base-killed non-P5 has 12, a base-killed P5 has 12, and a P5 killed only because all three smoothness candidates are infeasible has 84; all ties pick base order; every survivor shares selected PD/IK; a P1 base failure after each possible P1 seed shard returns `INCONCLUSIVE/STOPPED` with exact count `3/6/9/12`, zero later current-stage commands, and no final-four requirement; a P1 final-four failure analogously contributes `26/52/78/104` final-four episodes and runs no P2-P6 final-four shard; final four otherwise evaluates each survivor once. Assert the canonical `candidate_evaluations` bytes include every feasible/infeasible vector, per-stack/seed score, global score/null, tie rank, reuse hash, and reason.
- [ ] Before implementation run: `UV_CACHE_DIR=.cache/uv uv run pytest experiments/01_policy_control/tests/test_pilot_selection.py -q`

Expected: FAIL because pilot APIs are absent.

- [ ] GREEN: every create-only manifest binds predecessor/config/implementation/parameter hashes and sorted episodes. Base fixes survivors. Candidate feasible only with all fixed-survivor episodes. Score equals mean 3 conditions per `(stack,seed)`, then 4 seeds per stack, then survivors equally. Non-base failures invalidate candidate, never alter survivors. Reuse selected baseline hashes. P5 scalar uses P5 only. Final four run 26 conditions once and cannot tune. Emit the complete ordered `candidate_evaluations` schema from Task 12 rather than only selected values. Compute the P1 final-four two-stage jerk/discontinuity baseline with contributing seed, episode, and bundle hashes. `pilot_disposition` accepts the actual last successfully executed stage manifest plus optional stage-terminal disposition, derives exact expected episode totals from completed shards/survivor/kill/reuse evidence, and treats `1008` only as the all-survivor upper bound. Enforce two revisions.

- [ ] After implementation run: `UV_CACHE_DIR=.cache/uv uv run pytest experiments/01_policy_control/tests/test_pilot_selection.py -q`

Expected: PASS.

```bash
git add experiments/01_policy_control/src/evaluate.py experiments/01_policy_control/tests/test_pilot_selection.py
git commit -m "feat: add mechanical pilot selection"
```

---

### Task 11: Inference, gates, classifications, plots

**Files:** Modify `experiments/01_policy_control/src/evaluate.py`; create `experiments/01_policy_control/tests/test_inference.py`, `experiments/01_policy_control/tests/test_plots.py`.

**Interfaces:** `BootstrapContrast`, `BootstrapDecision`, `PromotionDecision`, `paired_bootstrap`, `apply_gate`, `write_svg_plots`.

- [ ] RED: exact SHA/PCG64 seed; 10,000 resamples; adjusted 99% endpoints; equality passes `-.10/+.10` and absolute budgets; P1/control failure inconclusive; promotion maximum two in upper-bound/P1-P6 tie order; P1+P2 produces `("JOINT_POSITION",)`; repeated SVG bytes equal. Recompute candidate scores and P1 pilot two-stage smoothness baselines from shuffled input rows, require canonical byte equality with the frozen decision/baseline records, pass at exactly `1.5x`, fail above it, and reject a changed contributing bundle hash before confirmation inference.

Run: `UV_CACHE_DIR=.cache/uv uv run pytest experiments/01_policy_control/tests/test_inference.py experiments/01_policy_control/tests/test_plots.py -q`

Expected: FAIL because inference/plot APIs are absent.
- [ ] GREEN: sort paired complete seeds, resample count with replacement, nearest-rank endpoints, no imputation. Implement pooled recovery/clamp/saturation and two-stage jerk/discontinuity p95. Before inference, reproduce the committed candidate evaluations and P1 pilot baselines from their bound evidence and refuse any hash/value mismatch; confirmation smoothness limits are exactly `1.5 * frozen_baseline`. Superior then noninferior ranking, P1 self upper 0, absolute gates, exact SUPPORTED/NOT_SUPPORTED/INCONCLUSIVE. Any phase/shard resource refusal or exhaustion forces global `INCONCLUSIVE`; it never enters the one-accidental-invalid-seed branch. Stable-first wire string deduplication.
- [ ] Write five dependency-free SVGs with fixed XML/style/order/format. Timeline is lexicographically first valid 10 Hz/300 ms/two-move/no-fault seed for P1 plus promoted stacks.
- [ ] Run: `UV_CACHE_DIR=.cache/uv uv run pytest experiments/01_policy_control/tests/test_inference.py experiments/01_policy_control/tests/test_plots.py -q`

Expected: PASS.

```bash
git add experiments/01_policy_control/src/evaluate.py experiments/01_policy_control/tests/test_inference.py experiments/01_policy_control/tests/test_plots.py
git commit -m "feat: add experiment 01 inference"
```

---

### Task 12: Atomic artifacts, one CLI, freeze/report code, and pre-pilot commit

**Files:** Create `experiments/01_policy_control/src/artifacts.py`, `experiments/01_policy_control/tests/test_artifacts_cli.py`, `experiments/01_policy_control/README.md`, `experiments/01_policy_control/CLAIM.md`, `experiments/01_policy_control/EXPERIMENT.md`, `experiments/01_policy_control/RESULTS.md`, `experiments/01_policy_control/INTERFACE_FINDINGS.md`; modify `experiments/01_policy_control/run.py`, `Makefile`.

**Interfaces:** `iter_manifest(Path)->Iterator[ShardSpec]`, `publish_or_validate_skip`, `publish_failure_disposition`, `run_supervised_shard`, `run_worker_shard`, `validate_phase`, `analyze_phase`, `freeze_protocol`, `generate_confirmation_manifest`, `write_report`; `ImplementationSnapshot.capture/validate_before/validate_after`; and `preflight_resources(stage,retained_bytes,temp_bytes,quarantine_bytes,free_bytes,wall_seconds,cpu_seconds)->ResourceDisposition`. Single public CLI: `--config --p3-gate --phase pilot|freeze|confirmation|analyze|report [--manifest PATH] --output-dir --headless [--shard-id] [--list-shards] [--shard-disposition SHARD_ID] [--stage-disposition] [--stage revision|base|pd_60_6|pd_100_10|ik_0_001|ik_0_05|p5_0_01|p5_0_04|final_four] [--prepare-manifest PATH] [--bind-preregistration PATH] [--dry-run] [--preflight] [--max-episodes]`. `--stage revision --prepare-manifest` is the sole no-predecessor case and transactionally writes the protocol revision plus pilot seed partition; every later prepare consumes the validated predecessor named by `--manifest`. Preparation never runs physics; without it, pilot/confirmation execute exactly one supervised shard. Pilot analyze accepts either the final-four manifest or the exact last executed manifest plus a validated stage-terminal disposition; it never requires a nonexistent successor. `--bind-preregistration` is confirmation-only: it requires the seed and protocol manifests to be tracked at clean `HEAD`, then writes a canonical binding containing that 40-hex commit and both Git-blob/content hashes. `--list-shards` validates the named manifest and prints P1 shard IDs first, then P2-P6, with each group in canonical order, without importing MuJoCo or creating output. With `--max-episodes N`, it requires `N` to equal the shard's declared episode count and lists exactly those shards; a validated killed-P5 stage may return an empty list. Pilot-only `--shard-disposition SHARD_ID` validates the named completed P1 shard and all earlier P1 shards: it prints `CONTINUE`, or create-only publishes the stage-terminal disposition and prints `TERMINAL_STOPPED`. Pilot-only `--stage-disposition` requires every declared shard completion unless the validated stage-terminal disposition names the first failing P1 shard, and prints exactly `ADVANCE` or `TERMINAL_STOPPED` without other output. `--preflight` is physics-free and prints one canonical `ResourceDisposition`; it cannot be combined with shard execution. A complete or accidental-invalid shard exits 0; a global resource refusal/exhaustion exits 3 after its terminal disposition; unsafe, ambiguous, or implementation-drift state exits 2; other preparation/validation errors exit 1. `--shard-id`, `--list-shards`, `--shard-disposition`, `--stage-disposition`, `--preflight`, and default evidence execution are mutually exclusive.

**Strict artifact schemas and canonical bytes:** JSON and JSONL are UTF-8, sorted-key, compact-separator JSON with one LF; loaders reject duplicate, missing, and unknown keys, bool-as-int, nonfinite values, and noncanonical bytes. `frozen.yaml` is the same canonical JSON subset saved with a YAML suffix and is loaded with a duplicate-key-rejecting safe loader before byte-equal reserialization. CSV is UTF-8 RFC 4180 with LF, the exact header below, stable row ordering, and explicit empty fields only where the schema permits null. SHA-256 values are lowercase 64-hex; Git SHAs are lowercase 40-hex.

- A protocol/stage manifest has exactly `schema_version,study_id,phase,revision,stage,implementation_sha,predecessor_sha256,config_sha256,p3_gate_sha256,seed_manifest_sha256,parameter_vector,parameter_hash,scenario_generator_hash,condition_hash,metric_hash,gate_hash,resource_limits,shards,state`. Each shard has exactly `shard_id,stack_id,configuration_hash,seed,condition_ids,episode_count,output_identities`; arrays are sorted/unique and the immutable manifest `state` is exactly `READY`. Terminal lifecycle is represented only by the separate create-only stage-terminal disposition; no manifest is rewritten.
- A shard completion manifest has exactly `schema_version,study_id,phase,revision,shard_id,implementation_sha,preregistration_git_sha,protocol_sha256,configuration_hash,seed,expected_output_identities,completed_output_identities,rollout_sha256s,failure_disposition_sha256,resource_ledger_sha256,state`; output arrays are sorted/unique, `state` is `COMPLETE|DECLARED_INVALID`, `preregistration_git_sha` is null only in pilot, and the failure digest is null only for complete evidence. Scientific P1 hard failure is complete evidence, not a typed runtime failure: its shard completes all declared episodes, then `--shard-disposition` may stop the stage before the next shard.
- A seed manifest has exactly `schema_version,study_id,phase,revision,rng_algorithm,rng_root,partition,candidate_count,accepted_count,rejections,scenarios`. Each rejection has `candidate_seed,proposal_index,reason`; each scenario has `seed,proposal_index,q0,initial_target,one_move_path,two_move_path,stationary_path,scenario_sha256`. Pilot `partition` has exactly `tuning_seed_ids,evaluation_seed_ids`, four sorted unique IDs each; confirmation `partition` has exactly `confirmation_seed_ids`, 32 sorted unique IDs. Rejections sort by proposal index and scenarios by seed ID.
- A stage-terminal disposition has exactly `schema_version,study_id,phase,revision,stage,manifest_sha256,trigger_shard_id,trigger_completion_sha256,reason,lifecycle_state,scientific_result`; only P1 `DIMENSIONAL_MISMATCH|NONFINITE_REFERENCE_OR_STATE|JOINT_LIMIT_ESCAPE|UNSTABLE_DIVERGENCE|EASIEST_RECOVERY_FAILURE` is accepted, lifecycle/scientific values are exactly `STOPPED`/`INCONCLUSIVE`, and it is create-only at the first failing P1 shard.
- `stage-digests.json` has exactly `schema_version,study_id,revision,implementation_sha,stage_digests,total_episode_count`; each ordered stage row has `stage,manifest_sha256,completion_sha256,terminal_disposition_sha256,episode_count,reuse_hashes`. `terminal_disposition_sha256` is null except for the terminal stage. `pilot-decision.json` has exactly `schema_version,study_id,revision,lifecycle_state,scientific_result,terminal_stage,survivors,killed_stacks,selected_pd,selected_ik,selected_p5_smoothness,candidate_evaluations,p1_pilot_smoothness_baseline,stage_digests_sha256,expected_episode_counts,total_episode_count,reasons`.
- Each `candidate_evaluations` row has exactly `stage,parameter_vector,parameter_hash,fixed_survivors,feasible,reuse_hashes,stack_seed_scores,global_score,tie_rank,reasons`; rows follow frozen stage/candidate order. Each `stack_seed_scores` row has exactly `stack_id,seed,condition_bundle_sha256s,score`; rows sort by stack then seed. An infeasible candidate has null `global_score`, the exact failing bundle/reason, and never changes `fixed_survivors`. `p1_pilot_smoothness_baseline` is null on a terminal pilot before final-four; otherwise it has exactly `seed_ids,episode_bundle_sha256s,jerk_episode_p95s,discontinuity_episode_p95s,jerk_p95,discontinuity_p95`, using the final-four P1 core episodes and the frozen nearest-rank two-stage rule.
- `frozen.yaml` has exactly `schema_version,study_id,implementation_sha,pilot_evidence_commit,clean_tree,p2_p3_hashes,mujoco_identity,model_hashes,scenario_protocol,stack_protocols,timing_protocol,metric_protocol,plot_protocol,pilot_decision,pilot_decision_sha256,surviving_stacks,confirmation_protocol,bootstrap_protocol,gates,resource_limits`; `pilot_decision` embeds the exact validated decision above and `pilot_decision_sha256` hashes its committed canonical bytes. On an advancing pilot, `gates` copies the two measured P1 baseline values and their contributing bundle hashes; confirmation recomputes the pilot decision and both baselines from validated evidence and requires byte/value equality before applying either `1.5x` gate. On a P1-terminal pilot, `p1_pilot_smoothness_baseline` and its gate inputs are null and `confirmation_protocol.enabled` is false; otherwise they are nonnull and `enabled` is true. Every other nested object uses the exact strict base-config schema. `frozen-config.sha256` is exactly `<sha256>  experiments/01_policy_control/configs/frozen.yaml\n` and never hashes itself.
- `preregistration-binding.json` has exactly `schema_version,study_id,preregistration_git_sha,seed_manifest_path,seed_git_blob_sha1,seed_sha256,protocol_manifest_path,protocol_git_blob_sha1,protocol_sha256,frozen_sha256,implementation_sha`. It binds the first commit containing both unchanged manifests.
- Each shard owns immutable files `failure-disposition.jsonl` and `resource-ledger.jsonl` inside its descriptor-held publication directory; there is no shared append-in-place file. A failure row has exactly `schema_version,study_id,phase,revision,shard_id,stack_id,seed,condition_id,reason,started_at_utc,finished_at_utc,command_sha256,readable_output_sha256,details_sha256`; reason is `PROCESS_TIMEOUT|RESOURCE_EXHAUSTION|MISSING_OUTPUT|CORRUPT_OUTPUT`, times are canonical UTC and ordered, and unreadable output uses null rather than fabricated bytes. There is exactly one row per affected condition, sorted by condition, with no duplicate condition ID; every affected condition is absent from completed outputs. A complete shard omits the failure file. Restart accepts a shard-local ledger/failure file only through the complete publication marker; verified pre-marker files are quarantined before exact retry.
- A shard-local `resource-ledger.jsonl` has exact rows `schema_version,study_id,phase,revision,shard_id,command_sha256,started_at_utc,finished_at_utc,wall_ns,cpu_ns,retained_bytes,temp_peak_bytes,quarantine_bytes,free_bytes_after,disposition`; integer fields are nonnegative exact integers and `disposition` is `COMPLETE|DECLARED_INVALID|REFUSED`. Rows sort by start time and all name the containing shard. Phase preflight and analysis enumerate only validated completion manifests, load the ledger named by each `resource_ledger_sha256`, reject duplicate shard/command identities, and aggregate in phase/revision/shard/start order. A global preflight refusal has its own immutable phase disposition and is never appended to a shard ledger.
- A preflight disposition has exactly `schema_version,study_id,phase,revision,retained_bytes,temp_bytes,quarantine_bytes,free_bytes,reserved_bytes,wall_seconds,cpu_seconds,shard_wall_limit_seconds,disposition,reasons`; `disposition` is `ALLOW|REFUSE`, reasons are sorted unique closed enum values, and `ALLOW` requires an empty array.
- A resource-terminal phase disposition has exactly `schema_version,study_id,phase,revision,source,shard_id,resource_ledger_sha256,preflight_sha256,reasons,lifecycle_state,scientific_result`; `source` is `PREFLIGHT|SHARD`, exactly one source-appropriate SHA field is nonnull, `shard_id` is nonnull only for `SHARD`, reasons are sorted nonempty resource enums, and lifecycle/scientific values are exactly `STOPPED`/`INCONCLUSIVE`. It is create-only and is the terminal marker checked before every later dispatch or analysis.
- `aggregate.csv` has exact header `row_kind,phase,stack_id,configuration_hash,seed,condition_id,policy_hz,latency_ms,move_count,fault,recovery_n,recovery_mean_s,final_error_m,mean_error_m,p95_error_m,age_n,age_p95_s,jerk_n,jerk_p95,saturation_n,saturation_denominator,discontinuity_n,discontinuity_mean,discontinuity_p95,unsafe_count,clamp_n,clamp_denominator,compute_n,compute_p50_ns,compute_p95_ns,validity,bundle_sha256`; `row_kind` is `EPISODE|SEED` and validity is `VALID|DECLARED_INVALID`. A valid EPISODE populates every field. An invalid EPISODE populates `row_kind=EPISODE`, identity and condition fields through `fault`, plus `validity`, with every metric and `bundle_sha256` empty. A valid SEED populates `row_kind=SEED`, phase/stack/configuration/seed, every metric, validity, and bundle hash, with the five condition-descriptor fields empty. An invalid SEED populates exactly `row_kind=SEED`, phase, stack, configuration, seed, and validity. No other empty field is accepted.
- `bootstrap.json` has exactly `schema_version,study_id,frozen_sha256,algorithm,resamples,alpha,family_size,seed_derivation,contrasts`; each contrast has `stack_id,paired_seed_ids,estimate,lower,upper,lower_index,upper_index,classification`. `decision.json` has exactly `schema_version,study_id,lifecycle_state,artifact_state,scientific_result,primary_stack,contrasts,gates,killed_stacks,promoted_stacks,promoted_wire_representations,rejections,reasons`.
- `artifact-manifest.json` and final `artifact-digests.json` have exactly `schema_version,study_id,phase,protocol_sha256,files,total_bytes`; each sorted file row has `path,media_type,bytes,sha256`. They exclude themselves, all temporary files, and raw ignored evidence not owned by that manifest. The two Markdown files retain their reviewed Task 12 placeholder hash and exact ordered result-section template; each SVG uses the fixed Task 11 serializer.

Every logical multi-file publication uses a descriptor-held, no-follow stage directory and writes/`fsync`s deterministic files before a publication manifest written last; then it fsyncs the directory. When tracked files must live in separate final paths, resume recomputes all intended bytes, accepts an existing file only when byte-identical, writes only absent files, and writes the publication manifest last. Same-process failure removes only held-inode temporaries. After restart, verified orphans are moved descriptor-relatively to bounded quarantine and never deleted; conflicting/ambiguous partials fail closed. Report resume accepts each exact final output or the reviewed placeholder only, completes absent outputs, and publishes `artifact-digests.json` last. Tests inject a crash after every file/rename/fsync boundary and prove exact resume, conflict refusal, manifest-last behavior, self-digest exclusion, and quarantine accounting.

The publication marker is, mechanically: `protocol-manifest.json` after its seed
manifest; each shard completion manifest after rollouts, shard-local failure file, and
shard-local ledger; a stage-terminal disposition immediately after its triggering P1
completion; `pilot-decision.json` after stage digests; `frozen-config.sha256` after `frozen.yaml`;
confirmation `protocol-manifest.json` after its seed manifest; `decision.json` after
aggregate and bootstrap; and final `artifact-digests.json` after Markdown/SVG outputs.
Validators ignore no sibling: an unlisted file is an error except the bounded named
quarantine directory, which is counted and separately validated. Fixtures kill and
restart after each constituent write, file fsync, rename, marker write, and directory
fsync for every one of these phase publications.

`run_supervised_shard` is the only public evidence path. After safety, P3, manifest,
resource, and implementation checks, the parent starts a private worker argv with
`subprocess.Popen(..., start_new_session=True, stdout=PIPE, stderr=PIPE, close_fds=True)`.
Two drain threads continuously hash every stdout/stderr byte while retaining only the
first and last `65,536` bytes of each stream; no pipe or in-memory output is allowed to
grow without bound. `communicate` is not used. The parent waits against a monotonic
`3,600 s` deadline. At the deadline it sends `SIGTERM` to the worker process group,
waits exactly `5 s`, sends `SIGKILL` if needed, drains both pipes to EOF, and calls
`wait()` until the child is reaped. The private worker imports MuJoCo and writes only to
its descriptor-held shard stage directory; it cannot publish a completion marker.
After success, the parent validates staged bytes and publishes ledger then completion.
After timeout, it publishes bounded readable-output/details bytes, the shard-local
`PROCESS_TIMEOUT` disposition and ledger, then the completion marker. A signal or
worker status indicating resource exhaustion publishes the phase-terminal
`RESOURCE_EXHAUSTION` disposition and exits `3`; it is never converted to accidental
missingness. The private worker mode requires a parent-created random pipe capability
inherited by exact descriptor number and rejects ordinary CLI invocation.

- [ ] RED artifact test:

```python
assert publish_or_validate_skip(RECORD,destination,SPEC)=="published"
assert publish_or_validate_skip(RECORD,destination,SPEC)=="validated-and-skipped"
artifact=validate_rollout(destination); replay=replay_rollout(destination)
assert replay.rollout_id==destination.name
assert tuple(replay.events)==tuple(artifact.events)
assert tuple(_canonical_observation_bytes(x) for x in replay.observations)==tuple(_canonical_observation_bytes(x) for x in artifact.observations)
assert _canonical_state_bytes(replay.frames[-1].state)==_canonical_state_bytes(replay.final_state)
```

The test helpers encode every scalar with its declared type and each ndarray with dtype, shape, and C-order bytes; they never use ndarray-bearing dataclass equality. Also corrupt a byte/extra file/temporary dir and require refusal; verify P1-first sorted root-relative manifest iteration and exact `--list-shards` output; dry-run no MuJoCo/output; evidence requires exact complete shard and headless. Confirmation execution requires the sibling `preregistration-binding.json`, verifies that its 40-hex commit contains byte-identical seed/protocol manifests, and records that commit in every shard completion manifest. Add RED cases for every missing/unknown/duplicate key and bool-as-int; noncanonical JSON/YAML/CSV; publication crashes after each boundary including ledger fsync immediately before completion-marker publication; same-process cleanup and restart quarantine; shard-local ledger aggregation and shared-ledger rejection; each typed shard failure; a deliberately hung worker with a `0.05 s` fixture deadline proving TERM/KILL, bounded first/last output, EOF drain, child reap, no surviving process group, exact timeout resume, and no direct worker invocation; resource exhaustion exit `3` and global `INCONCLUSIVE`; a second invalid confirmation seed; resource, wall, CPU, temp, and free-space refusal; pre/post tracked changes; and pre/post untracked implementation files.

Run: `UV_CACHE_DIR=.cache/uv uv run pytest experiments/01_policy_control/tests/test_artifacts_cli.py -q`

Expected: collection FAIL with missing `artifacts`.

- [ ] GREEN artifacts: absent output uses `RolloutWriter.write`, then size, `validate_rollout`, `replay_rollout`. Existing output validates exact file/artifact/protocol/source/scenario/condition hashes, metadata, events, observation/action/reference bytes, and terminal replay; never rewrites. Implement the parent/worker supervisor exactly above; the parent alone publishes shard-local ledgers, failure rows, and completion markers. Phase/shard manifests use `O_EXCL`, fsync, absent rename. `ReplayResult` fields are exactly rollout_id/events/observations/frames/final_state.
- [ ] GREEN evidence guard: capture the protocol's implementation SHA and the exact implementation-owned paths listed in Task 14 through hardened local Git commands. Immediately before a shard command and again before its completion/failure publication, require every tracked implementation path byte-identical to that SHA and require `git ls-files --others --exclude-standard` to report no untracked path below those implementation-owned paths. The after-snapshot must equal the before-snapshot. A mismatch writes no scientific artifact or disposition and exits 2. Apply the same guard around pilot/confirmation analyze. Report generation applies it to every implementation path except its enumerated Markdown/SVG/digest output targets, whose reviewed-placeholder or absent precondition and exact intended postcondition are checked separately. The final report records the clean implementation after-snapshot.
- [ ] GREEN resource guard: derive retained bytes from validated manifests plus filesystem measurements, temp/quarantine from descriptor-held directories, free bytes from `statvfs`, and wall/CPU by canonically aggregating validated shard-local ledgers. Reserve the entire next shard or stage before importing MuJoCo or opening output. Pilot permits at most two retained revisions; each exact 128 MiB non-rollout allowance is 16 MiB final manifests/digests + 32 MiB temporary peak + 64 MiB quarantine + 16 MiB headroom. The exact 256 MiB confirmation allowance is 64 MiB aggregate/report + 64 MiB temporary peak + 96 MiB quarantine + 32 MiB headroom. No bucket borrows from another. The full experiment remains at most 7,544 MiB (`2,016 + 5,016` rollout MiB plus `128 + 128 + 256` MiB). The pilot/confirmation wall ceilings are 8/24 hours and CPU ceilings 80/240 hours; each supervisor enforces the 60-minute shard deadline. Integer byte/ns comparisons are inclusive at the cap and refuse strictly above it. Refusal/resource exhaustion is canonical, creates no fabricated rollout, atomically records a phase-terminal disposition, returns exit `3`, and makes the lifecycle `INCONCLUSIVE`; it is never eligible for the one-accidental-invalid-seed rule.
- [ ] GREEN CLI: safety/P3 gate precedes local imports; root-contain all paths. Dry-run prints canonical sorted JSON. Freeze validates all pilot artifacts and writes config plus external digest (no self digest). Confirmation generator requires frozen protocol/new RNG. Analyze/report never import physics. Report atomically replaces only the reviewed Task 12 placeholder report bytes, and an exact reissue validates-and-skips; it writes the two Markdown reports and five canonical SVGs named in Task 15. Reports preserve the bounded stack-level claim.
- [ ] Add this literal root target; missing `SHARD` exits before Python, and the CLI validates that it names one three-episode base shard:

```makefile
.PHONY: exp01
exp01:
	@test -n "$(SHARD)" || { echo "SHARD is required" >&2; exit 2; }
	MUJOCO_GL=disable UV_CACHE_DIR=.cache/uv uv run python -m experiments.01_policy_control.run --config experiments/01_policy_control/configs/base.yaml --p3-gate experiments/01_policy_control/configs/p3-gate.yaml --phase pilot --manifest experiments/01_policy_control/protocol/pilot-r1/base-manifest.json --output-dir experiments/01_policy_control/results --headless --shard-id "$(SHARD)" --max-episodes 3
```

Run `make exp01`; expect nonzero with guard message `SHARD is required`, no Python or
MuJoCo import, and no output. Run `make exp01 SHARD=P1:base:000` against the reviewed fixture;
expect the exact bounded base shard to publish or validate-and-skip.
- [ ] Run before any pilot:

```text
MUJOCO_GL=disable UV_CACHE_DIR=.cache/uv uv run pytest experiments/01_policy_control/tests -q
UV_CACHE_DIR=.cache/uv uv run pytest -q
UV_CACHE_DIR=.cache/uv uv lock --check
UV_CACHE_DIR=.cache/uv uv run python -m reflect.safety check
UV_CACHE_DIR=.cache/uv uv run python scripts/audit_references.py --require-complete
UV_CACHE_DIR=.cache/uv uv run python scripts/source_audit.py --check
git diff --check
```

Expected all 0. Commit all code before pilot:

```bash
git add Makefile experiments/01_policy_control/src/artifacts.py experiments/01_policy_control/run.py experiments/01_policy_control/tests/test_artifacts_cli.py experiments/01_policy_control/README.md experiments/01_policy_control/CLAIM.md experiments/01_policy_control/EXPERIMENT.md experiments/01_policy_control/RESULTS.md experiments/01_policy_control/INTERFACE_FINDINGS.md
git commit -m "feat: complete experiment 01 runner"
```

No code/test/dependency/Makefile change after this SHA without Draft/new revision.

---

### Task 13: Clean pre-pilot revision manifest

**Files:** Create `configs/p3-gate.yaml`, `protocol/pilot-r1/protocol-manifest.json`, `pilot-seeds.json`, `base-manifest.json`.

- [ ] Require a fully clean tree; record Task 12 40-hex SHA. Protocol binds exact P2 lock, compatibility, licenses, source map, operation manifest, smoke, package artifact, all code/config/equation/metric/gate hashes and budgets. Run exactly:

```text
git status --porcelain=v1 --untracked-files=all
git rev-parse HEAD
MUJOCO_GL=disable UV_CACHE_DIR=.cache/uv uv run pytest experiments/01_policy_control/tests -q
UV_CACHE_DIR=.cache/uv uv run pytest -q
UV_CACHE_DIR=.cache/uv uv lock --check
UV_CACHE_DIR=.cache/uv uv run python -m reflect.safety check
UV_CACHE_DIR=.cache/uv uv run python scripts/audit_references.py --require-complete
UV_CACHE_DIR=.cache/uv uv run python scripts/source_audit.py --check
git diff --check
```

Expected: status and diff checks print nothing, `rev-parse` prints the reviewed Task 12
40-hex implementation SHA, and every verification exits 0.
- [ ] Generate the gate from P3 evidence, then generate checked-in eight seeds split first four tuning/final four sealed evaluation:

```text
UV_CACHE_DIR=.cache/uv uv run python -m experiments.01_policy_control.src.p3_gate --write experiments/01_policy_control/configs/p3-gate.yaml
UV_CACHE_DIR=.cache/uv uv run python -m experiments.01_policy_control.run --config experiments/01_policy_control/configs/base.yaml --p3-gate experiments/01_policy_control/configs/p3-gate.yaml --phase pilot --output-dir experiments/01_policy_control/results --headless --stage revision --prepare-manifest experiments/01_policy_control/protocol/pilot-r1/protocol-manifest.json
UV_CACHE_DIR=.cache/uv uv run python -m experiments.01_policy_control.run --config experiments/01_policy_control/configs/base.yaml --p3-gate experiments/01_policy_control/configs/p3-gate.yaml --phase pilot --manifest experiments/01_policy_control/protocol/pilot-r1/protocol-manifest.json --output-dir experiments/01_policy_control/results --headless --stage base --prepare-manifest experiments/01_policy_control/protocol/pilot-r1/base-manifest.json
UV_CACHE_DIR=.cache/uv uv run python -m experiments.01_policy_control.run --config experiments/01_policy_control/configs/base.yaml --p3-gate experiments/01_policy_control/configs/p3-gate.yaml --phase pilot --manifest experiments/01_policy_control/protocol/pilot-r1/base-manifest.json --output-dir experiments/01_policy_control/results --headless --preflight
UV_CACHE_DIR=.cache/uv uv run python -m experiments.01_policy_control.run --config experiments/01_policy_control/configs/base.yaml --p3-gate experiments/01_policy_control/configs/p3-gate.yaml --phase pilot --manifest experiments/01_policy_control/protocol/pilot-r1/base-manifest.json --output-dir experiments/01_policy_control/results --headless --shard-id P1:base:000 --max-episodes 3 --dry-run
```

Expected: all exit 0; the two preparation commands publish only small manifests without
MuJoCo; preflight prints canonical `ALLOW` only after reserving the complete remaining
7,544 MiB phase maximum and pilot wall/CPU bounds; and the final dry-run prints exactly
three sorted episodes without creating results.
- [ ] Independent Draft review PASS, then:

```bash
git add experiments/01_policy_control/configs/p3-gate.yaml experiments/01_policy_control/protocol/pilot-r1/protocol-manifest.json experiments/01_policy_control/protocol/pilot-r1/pilot-seeds.json experiments/01_policy_control/protocol/pilot-r1/base-manifest.json
git commit -m "chore: freeze experiment 01 pilot revision"
```

---

### Task 14: Staged pilot and unchanged-SHA freeze

**Files:** Create small `protocol/pilot-r1/pd_60_6-manifest.json`,
`pd_100_10-manifest.json`, `ik_0_001-manifest.json`, `ik_0_05-manifest.json`,
`p5_0_01-manifest.json`, `p5_0_04-manifest.json`, `final-four-manifest.json`,
`stage-digests.json`, `pilot-decision.json`, `configs/frozen.yaml`, and
`protocol/frozen-config.sha256`.

- [ ] Define this exact zsh manifest executor in the orchestration shell. It validates
the manifest and obtains only its current-stage shard IDs before invoking one bounded
evidence command per ID; it is not an open-ended phase execution:

```zsh
run_p4_pilot_manifest() {
  local P4_MANIFEST_PATH="$1"
  local P4_EPISODE_COUNT="$2"
  local P4_SHARD_TEXT
  local P4_SHARD_DISPOSITION
  local P4_SHARD_STATUS
  local P4_STAGE_DISPOSITION
  P4_SHARD_TEXT="$(UV_CACHE_DIR=.cache/uv uv run python -m experiments.01_policy_control.run --config experiments/01_policy_control/configs/base.yaml --p3-gate experiments/01_policy_control/configs/p3-gate.yaml --phase pilot --manifest "$P4_MANIFEST_PATH" --output-dir experiments/01_policy_control/results --headless --list-shards --max-episodes "$P4_EPISODE_COUNT")" || return 1
  if [[ -n "$P4_SHARD_TEXT" ]]; then
    while IFS= read -r P4_SHARD_ID; do
      if MUJOCO_GL=disable UV_CACHE_DIR=.cache/uv uv run python -m experiments.01_policy_control.run --config experiments/01_policy_control/configs/base.yaml --p3-gate experiments/01_policy_control/configs/p3-gate.yaml --phase pilot --manifest "$P4_MANIFEST_PATH" --output-dir experiments/01_policy_control/results --headless --shard-id "$P4_SHARD_ID" --max-episodes "$P4_EPISODE_COUNT"; then
        P4_SHARD_STATUS=0
      else
        P4_SHARD_STATUS=$?
      fi
      if (( P4_SHARD_STATUS == 3 )); then
        P4_RESOURCE_STOPPED=1
        return 3
      fi
      (( P4_SHARD_STATUS == 0 )) || return 1
      if [[ "$P4_SHARD_ID" == P1:* ]]; then
        P4_SHARD_DISPOSITION="$(UV_CACHE_DIR=.cache/uv uv run python -m experiments.01_policy_control.run --config experiments/01_policy_control/configs/base.yaml --p3-gate experiments/01_policy_control/configs/p3-gate.yaml --phase pilot --manifest "$P4_MANIFEST_PATH" --output-dir experiments/01_policy_control/results --headless --shard-disposition "$P4_SHARD_ID")" || return 1
        if [[ "$P4_SHARD_DISPOSITION" == "TERMINAL_STOPPED" ]]; then
          P4_TERMINAL_STOPPED=1
          break
        fi
        [[ "$P4_SHARD_DISPOSITION" == "CONTINUE" ]] || return 1
      fi
    done <<< "$P4_SHARD_TEXT"
  fi
  P4_STAGE_DISPOSITION="$(UV_CACHE_DIR=.cache/uv uv run python -m experiments.01_policy_control.run --config experiments/01_policy_control/configs/base.yaml --p3-gate experiments/01_policy_control/configs/p3-gate.yaml --phase pilot --manifest "$P4_MANIFEST_PATH" --output-dir experiments/01_policy_control/results --headless --stage-disposition)" || return 1
  P4_LAST_COMPLETED_MANIFEST="$P4_MANIFEST_PATH"
  if (( P4_TERMINAL_STOPPED )); then
    [[ "$P4_STAGE_DISPOSITION" == "TERMINAL_STOPPED" ]] || return 1
  else
    [[ "$P4_STAGE_DISPOSITION" == "ADVANCE" ]] || return 1
  fi
}
```

Before use set `P4_TERMINAL_STOPPED=0` and `P4_RESOURCE_STOPPED=0`. The listing validates exact stage identity/counts,
puts P1 shards first, and imports no MuJoCo. A completed P1 shard is dispositioned before
the next shard command. The first hard-failing P1 shard create-only seals the stage-
terminal disposition; the loop breaks before every later current-stage ID. A terminal
stage may therefore lack completions only for IDs strictly after that P1 shard.
Every nonempty stage prints `published` on first execution; an exact reissue prints
only `validated-and-skipped`. A valid empty P5 stage is allowed only when its validated
predecessor records P5 killed under the frozen rule.

- [ ] Execute the base stage and then prepare and execute every candidate in this exact
predecessor chain. Preparation validates every predecessor artifact, publishes one
create-only manifest, and runs no physics:

```zsh
run_p4_pilot_manifest experiments/01_policy_control/protocol/pilot-r1/base-manifest.json 3
UV_CACHE_DIR=.cache/uv uv run python -m experiments.01_policy_control.run --config experiments/01_policy_control/configs/base.yaml --p3-gate experiments/01_policy_control/configs/p3-gate.yaml --phase pilot --manifest experiments/01_policy_control/protocol/pilot-r1/base-manifest.json --output-dir experiments/01_policy_control/results --headless --stage pd_60_6 --prepare-manifest experiments/01_policy_control/protocol/pilot-r1/pd_60_6-manifest.json
run_p4_pilot_manifest experiments/01_policy_control/protocol/pilot-r1/pd_60_6-manifest.json 3
UV_CACHE_DIR=.cache/uv uv run python -m experiments.01_policy_control.run --config experiments/01_policy_control/configs/base.yaml --p3-gate experiments/01_policy_control/configs/p3-gate.yaml --phase pilot --manifest experiments/01_policy_control/protocol/pilot-r1/pd_60_6-manifest.json --output-dir experiments/01_policy_control/results --headless --stage pd_100_10 --prepare-manifest experiments/01_policy_control/protocol/pilot-r1/pd_100_10-manifest.json
run_p4_pilot_manifest experiments/01_policy_control/protocol/pilot-r1/pd_100_10-manifest.json 3
UV_CACHE_DIR=.cache/uv uv run python -m experiments.01_policy_control.run --config experiments/01_policy_control/configs/base.yaml --p3-gate experiments/01_policy_control/configs/p3-gate.yaml --phase pilot --manifest experiments/01_policy_control/protocol/pilot-r1/pd_100_10-manifest.json --output-dir experiments/01_policy_control/results --headless --stage ik_0_001 --prepare-manifest experiments/01_policy_control/protocol/pilot-r1/ik_0_001-manifest.json
run_p4_pilot_manifest experiments/01_policy_control/protocol/pilot-r1/ik_0_001-manifest.json 3
UV_CACHE_DIR=.cache/uv uv run python -m experiments.01_policy_control.run --config experiments/01_policy_control/configs/base.yaml --p3-gate experiments/01_policy_control/configs/p3-gate.yaml --phase pilot --manifest experiments/01_policy_control/protocol/pilot-r1/ik_0_001-manifest.json --output-dir experiments/01_policy_control/results --headless --stage ik_0_05 --prepare-manifest experiments/01_policy_control/protocol/pilot-r1/ik_0_05-manifest.json
run_p4_pilot_manifest experiments/01_policy_control/protocol/pilot-r1/ik_0_05-manifest.json 3
UV_CACHE_DIR=.cache/uv uv run python -m experiments.01_policy_control.run --config experiments/01_policy_control/configs/base.yaml --p3-gate experiments/01_policy_control/configs/p3-gate.yaml --phase pilot --manifest experiments/01_policy_control/protocol/pilot-r1/ik_0_05-manifest.json --output-dir experiments/01_policy_control/results --headless --stage p5_0_01 --prepare-manifest experiments/01_policy_control/protocol/pilot-r1/p5_0_01-manifest.json
run_p4_pilot_manifest experiments/01_policy_control/protocol/pilot-r1/p5_0_01-manifest.json 3
UV_CACHE_DIR=.cache/uv uv run python -m experiments.01_policy_control.run --config experiments/01_policy_control/configs/base.yaml --p3-gate experiments/01_policy_control/configs/p3-gate.yaml --phase pilot --manifest experiments/01_policy_control/protocol/pilot-r1/p5_0_01-manifest.json --output-dir experiments/01_policy_control/results --headless --stage p5_0_04 --prepare-manifest experiments/01_policy_control/protocol/pilot-r1/p5_0_04-manifest.json
run_p4_pilot_manifest experiments/01_policy_control/protocol/pilot-r1/p5_0_04-manifest.json 3
UV_CACHE_DIR=.cache/uv uv run python -m experiments.01_policy_control.run --config experiments/01_policy_control/configs/base.yaml --p3-gate experiments/01_policy_control/configs/p3-gate.yaml --phase pilot --manifest experiments/01_policy_control/protocol/pilot-r1/p5_0_04-manifest.json --output-dir experiments/01_policy_control/results --headless --stage final_four --prepare-manifest experiments/01_policy_control/protocol/pilot-r1/final-four-manifest.json
run_p4_pilot_manifest experiments/01_policy_control/protocol/pilot-r1/final-four-manifest.json 26
```

The displayed commands are the all-six-survive path. After every `run_p4_pilot_manifest`,
validate its completion manifests or exact stage-terminal disposition and set
`P4_LAST_COMPLETED_MANIFEST` to that path.
Run the next preparation line only when its exact predecessor is `READY`. If a P1
disposition is terminal, set `P4_TERMINAL_STOPPED=1`, do not execute or create any
successor manifest, and proceed directly to analysis with that last path. Tests execute
the dispatcher for terminal base P1, terminal final-four P1, killed P5, and all-survive
fixtures. For a failure in each of P1's four possible seed shards, record the exact
command vector and prove that no later P1 or P2-P6 shard and no successor preparation is
invoked; exact reissue validates the same terminal artifact without adding commands.

Expected: P1 base/final-four failure stops; no successor exists after the terminal
manifest. A surviving final-four manifest contains one shard per surviving stack/seed,
each with 26 episodes and the selected complete configuration hash. Counts come only
from validated completion manifests and dispositions: base-terminal P1 contributes
exactly `3`, `6`, `9`, or `12` episodes and P2-P6 contribute zero in that stage;
final-four-terminal P1 contributes exactly `26`, `52`, `78`, or `104` final-four
episodes and every non-P1 final-four contribution is zero. A base-killed non-anchor or
P5 contributes 12, all-smoothness-infeasible P5 contributes 84, a surviving non-P5
stack contributes 164, and a surviving P5 contributes 188. Thus 1,008 episodes and
6,300 simulated seconds are maxima only when all six stacks survive; early-stop totals
sum only validated completions, and reused evaluations are never re-executed.

- [ ] Validate all pilot artifacts and create the small digests/decision without
running physics:

```zsh
UV_CACHE_DIR=.cache/uv uv run python -m experiments.01_policy_control.run --config experiments/01_policy_control/configs/base.yaml --p3-gate experiments/01_policy_control/configs/p3-gate.yaml --phase analyze --manifest "$P4_LAST_COMPLETED_MANIFEST" --output-dir experiments/01_policy_control/results --headless
```

Expected: exit 0 and atomically create only `stage-digests.json` and
`pilot-decision.json` after deriving expected stage and total counts from the validated
terminal path and disposition. It checks the applicable 12/84/164/188 contribution,
the P1 early-stop `3/6/9/12` or `26/52/78/104` contribution when applicable, the
at-most-1,008 total, reuse hashes, survivors, shared PD/IK, P5 selection or killed
disposition, and a one-shot final four when that stage exists. It emits every ordered
candidate feasibility/score/tie/reuse record and, on an advancing final four, the exact
P1 pilot jerk/discontinuity baselines plus contributing seed/output hashes; it never
invents absent stages or forces 164/188/1,008 on an early stop.

- [ ] Commit every pilot-stage manifest and its derived evidence before Freeze:

```bash
git add experiments/01_policy_control/protocol/pilot-r1
git commit -m "data: seal experiment 01 pilot evidence"
```

- [ ] Immediately before Freeze, extract the implementation SHA from the committed
protocol, require it to be a real 40-hex commit, prove every implementation-owned path
is byte-identical to that SHA, and require the complete worktree (including untracked
files, excluding normally ignored raw results) to be clean:

```zsh
P4_IMPLEMENTATION_SHA="$(UV_CACHE_DIR=.cache/uv uv run python -c 'import json,re; p=json.load(open("experiments/01_policy_control/protocol/pilot-r1/protocol-manifest.json", encoding="utf-8")); s=p["implementation_sha"]; assert re.fullmatch(r"[0-9a-f]{40}",s); print(s)')"
git cat-file -e "$P4_IMPLEMENTATION_SHA^{commit}"
git diff --exit-code "$P4_IMPLEMENTATION_SHA" -- Makefile pyproject.toml uv.lock experiments/__init__.py experiments/01_policy_control/__init__.py experiments/01_policy_control/run.py experiments/01_policy_control/src experiments/01_policy_control/tests experiments/01_policy_control/configs/base.yaml experiments/01_policy_control/README.md experiments/01_policy_control/CLAIM.md experiments/01_policy_control/EXPERIMENT.md experiments/01_policy_control/RESULTS.md experiments/01_policy_control/INTERFACE_FINDINGS.md
git status --porcelain=v1 --untracked-files=all
```

Expected: all exit 0; both diff and status print nothing. Freeze records this exact
implementation SHA, the current pilot-evidence commit SHA, and `clean_tree: true`.
- [ ] Run CLI freeze exactly:

```zsh
UV_CACHE_DIR=.cache/uv uv run python -m experiments.01_policy_control.run --config experiments/01_policy_control/configs/base.yaml --p3-gate experiments/01_policy_control/configs/p3-gate.yaml --phase freeze --manifest "$P4_LAST_COMPLETED_MANIFEST" --output-dir experiments/01_policy_control/results --headless
```

Expected: exit 0 after validating every committed pilot manifest/shard or exact P1
terminal disposition, counts/reuse hashes, shared PD/IK, P5 scalar, and all ordered
candidate evaluation rows. An advancing Freeze independently recomputes every candidate
score/tie and both P1 pilot smoothness baselines from the bound rollouts, requires exact
equality with `pilot-decision.json`, embeds that decision plus its SHA-256, and copies
the baseline values and contributing hashes into `gates`. A stopped P1 pilot instead
writes a terminal frozen record with null baseline, `confirmation_protocol.enabled=false`,
and no authority to create confirmation seeds or shards. Config does not self-hash;
separate digest hashes exact bytes.
Commit only:

```bash
git add experiments/01_policy_control/configs/frozen.yaml experiments/01_policy_control/protocol/frozen-config.sha256
git commit -m "data: freeze experiment 01 protocol"
```

Any defect returns to Draft/new r2 seeds; never edits r1.

---

### Task 15: Unseen confirmation, analysis, and bounded report

**Files:** Create `protocol/confirmation/seed-manifest.json`,
`protocol-manifest.json`, `preregistration-binding.json`, `artifact-digests.json`, and
`plots/recovery-vs-latency.svg`, `plots/tracking-error-vs-rate.svg`,
`plots/joint-jerk.svg`, `plots/action-age.svg`, `plots/timeline.svg`; modify
`RESULTS.md` and `INTERFACE_FINDINGS.md` only.

Task 15 confirmation commands are legal only when the validated frozen record has
`confirmation_protocol.enabled=true`. For a P1-terminal pilot, skip seed generation and
all confirmation shards, run the same reviewed report path against the terminal pilot
decision, and publish an `INCONCLUSIVE/STOPPED` report with no confirmation claim.

```text
UV_CACHE_DIR=.cache/uv uv run python -m experiments.01_policy_control.run --config experiments/01_policy_control/configs/frozen.yaml --p3-gate experiments/01_policy_control/configs/p3-gate.yaml --phase report --manifest experiments/01_policy_control/protocol/frozen-config.sha256 --output-dir experiments/01_policy_control/results --headless
```

Expected for the terminal branch: exit 0 without MuJoCo, confirmation manifests, or
confirmation evidence/rollouts; validate the committed pilot terminal artifact; create the two
bounded Markdown reports, five pilot-labelled SVGs, and final digest through the same
manifest-last writer; then use the final report commit command below and end Task 15.

- [ ] After freeze, generate a new RNG root absent from pilot; consume at most 64 candidates to seal exactly 32 variant-independent scenarios/rejections before any stack:

```text
UV_CACHE_DIR=.cache/uv uv run python -m experiments.01_policy_control.run --config experiments/01_policy_control/configs/frozen.yaml --p3-gate experiments/01_policy_control/configs/p3-gate.yaml --phase confirmation --manifest experiments/01_policy_control/protocol/frozen-config.sha256 --output-dir experiments/01_policy_control/results --headless --prepare-manifest experiments/01_policy_control/protocol/confirmation/seed-manifest.json
```

Expected: exit 0, exactly 32 accepted scenario records and at most 64 candidates, and
atomically create only the seed and protocol manifests (no MuJoCo/results).

- [ ] Commit those manifests before any confirmation shard, then create and commit the
binding to the commit that first sealed their exact bytes:

```bash
git add experiments/01_policy_control/protocol/confirmation/seed-manifest.json experiments/01_policy_control/protocol/confirmation/protocol-manifest.json
git commit -m "data: preregister experiment 01 confirmation"
UV_CACHE_DIR=.cache/uv uv run python -m experiments.01_policy_control.run --config experiments/01_policy_control/configs/frozen.yaml --p3-gate experiments/01_policy_control/configs/p3-gate.yaml --phase confirmation --manifest experiments/01_policy_control/protocol/confirmation/seed-manifest.json --output-dir experiments/01_policy_control/results --headless --bind-preregistration experiments/01_policy_control/protocol/confirmation/preregistration-binding.json
git add experiments/01_policy_control/protocol/confirmation/preregistration-binding.json
git commit -m "data: bind experiment 01 confirmation preregistration"
git status --porcelain=v1 --untracked-files=all
```

Expected: both commits succeed; the binding contains the first commit's 40-hex SHA and
the Git-blob/content hashes of both manifests; status prints nothing. Every later shard
requires this binding and records that same preregistration SHA.

- [ ] Preflight the full 7,544 MiB ceiling before importing MuJoCo or opening a result.
The command recomputes retained, temporary, quarantine, and free-space counters, reads
bounded wall/CPU totals from the canonical ledger, reserves the complete remaining
confirmation maximum, and exits `3` with a create-only phase-terminal `INCONCLUSIVE`
disposition on any exceeded bound:

```text
UV_CACHE_DIR=.cache/uv uv run python -m experiments.01_policy_control.run --config experiments/01_policy_control/configs/frozen.yaml --p3-gate experiments/01_policy_control/configs/p3-gate.yaml --phase confirmation --manifest experiments/01_policy_control/protocol/confirmation/seed-manifest.json --output-dir experiments/01_policy_control/results --headless --preflight
```

Expected: one canonical `ALLOW` disposition and no MuJoCo import or file creation.
Tests independently exceed retained, temporary, quarantine, free-space, 24-hour wall,
240-hour CPU, and 60-minute shard limits and prove refusal before simulator/output.

- [ ] Define and invoke this exact serial zsh executor for the 27-episode first-four-
seed shards and 26-episode remaining shards:

```zsh
run_p4_confirmation_count() {
  local P4_EPISODE_COUNT="$1"
  local P4_SHARD_TEXT
  local P4_SHARD_STATUS
  P4_SHARD_TEXT="$(UV_CACHE_DIR=.cache/uv uv run python -m experiments.01_policy_control.run --config experiments/01_policy_control/configs/frozen.yaml --p3-gate experiments/01_policy_control/configs/p3-gate.yaml --phase confirmation --manifest experiments/01_policy_control/protocol/confirmation/seed-manifest.json --output-dir experiments/01_policy_control/results --headless --list-shards --max-episodes "$P4_EPISODE_COUNT")" || return 1
  [[ -z "$P4_SHARD_TEXT" ]] && return 0
  while IFS= read -r P4_SHARD_ID; do
    if MUJOCO_GL=disable UV_CACHE_DIR=.cache/uv uv run python -m experiments.01_policy_control.run --config experiments/01_policy_control/configs/frozen.yaml --p3-gate experiments/01_policy_control/configs/p3-gate.yaml --phase confirmation --manifest experiments/01_policy_control/protocol/confirmation/seed-manifest.json --output-dir experiments/01_policy_control/results --headless --shard-id "$P4_SHARD_ID" --max-episodes "$P4_EPISODE_COUNT"; then
      P4_SHARD_STATUS=0
    else
      P4_SHARD_STATUS=$?
    fi
    if (( P4_SHARD_STATUS == 3 )); then
      P4_RESOURCE_STOPPED=1
      return 3
    fi
    (( P4_SHARD_STATUS == 0 )) || return 1
  done <<< "$P4_SHARD_TEXT"
}
run_p4_confirmation_all() {
  local P4_CONFIRMATION_STATUS
  P4_RESOURCE_STOPPED=0
  if run_p4_confirmation_count 27; then
    P4_CONFIRMATION_STATUS=0
  else
    P4_CONFIRMATION_STATUS=$?
  fi
  (( P4_CONFIRMATION_STATUS == 0 )) || return "$P4_CONFIRMATION_STATUS"
  run_p4_confirmation_count 26
}
run_p4_confirmation_all
```

Expected: the first four seeds use 27 episodes including the stationary control and
all later seeds use 26; each manifest-derived shard runs exactly once. Maximum remains
836 paired bundles, 5,016 rollouts, 31,350 simulated seconds, and 5,016 MiB plus
256 MiB. Exact reissue validates-and-skips. A supervised process timeout, missing
output, or corrupt output is converted once into its bounded shard-local failure rows;
the executor continues without fabricating a rollout. Analysis invalidates that
`(stack, seed)` primary value and excludes that seed only from paired contrasts involving
the stack. Exactly one such accidental invalid seed is reportable; a second for any
stack, systematic stack-specific loss, any missing negative control, or negative-control
failure makes confirmation `INCONCLUSIVE`. Resource refusal/exhaustion is different:
the parent publishes the global terminal disposition, exits `3`, the executor stops
immediately, and analysis must return `INCONCLUSIVE` regardless of how many other seeds
are valid. Ambiguous publication, implementation drift, or an unclassifiable failure
exits `2` and stops immediately. Tests exercise each status and assert the exact suffix
of shard commands is absent after exit `2` or `3`.
- [ ] Analyze artifacts only:

```text
UV_CACHE_DIR=.cache/uv uv run python -m experiments.01_policy_control.run --config experiments/01_policy_control/configs/frozen.yaml --p3-gate experiments/01_policy_control/configs/p3-gate.yaml --phase analyze --manifest experiments/01_policy_control/protocol/confirmation/seed-manifest.json --output-dir experiments/01_policy_control/results --headless
```

Expected: exit 0; exact paired bootstrap, missing/control/equality/gates, two-stack
promotion, wire deduplication, and replay validation without importing MuJoCo. It
atomically creates aggregate/bootstrap/decision data under ignored results; no report
or plot is written yet.

- [ ] Run the exact acceptance checks before report generation:

```zsh
MUJOCO_GL=disable UV_CACHE_DIR=.cache/uv uv run pytest experiments/01_policy_control/tests -q
UV_CACHE_DIR=.cache/uv uv run pytest -q
UV_CACHE_DIR=.cache/uv uv lock --check
UV_CACHE_DIR=.cache/uv uv run python -m reflect.safety check
UV_CACHE_DIR=.cache/uv uv run python scripts/audit_references.py --require-complete
UV_CACHE_DIR=.cache/uv uv run python scripts/source_audit.py --check
UV_CACHE_DIR=.cache/uv uv run python -c 'from pathlib import Path; root=Path("experiments/01_policy_control/results"); total=sum(p.stat().st_size for p in root.rglob("*") if p.is_file() and not p.is_symlink()); assert total <= 7_544*1024*1024, total; print(total)'
if git grep -I -n -E 'AKIA[0-9A-Z]{16}|g[h]p_[A-Za-z0-9]{36}|BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY' -- . ':(exclude)docs/superpowers/plans/2026-08-22-p4-policy-control-boundary.md'; then exit 1; fi
P4_IMPLEMENTATION_SHA="$(UV_CACHE_DIR=.cache/uv uv run python -c 'import re,yaml; p=yaml.safe_load(open("experiments/01_policy_control/configs/frozen.yaml", encoding="utf-8")); s=p["implementation_sha"]; assert re.fullmatch(r"[0-9a-f]{40}",s); print(s)')"
git cat-file -e "$P4_IMPLEMENTATION_SHA^{commit}"
git diff --exit-code "$P4_IMPLEMENTATION_SHA" -- Makefile pyproject.toml uv.lock experiments/__init__.py experiments/01_policy_control/__init__.py experiments/01_policy_control/run.py experiments/01_policy_control/src experiments/01_policy_control/tests experiments/01_policy_control/configs/base.yaml experiments/01_policy_control/README.md experiments/01_policy_control/CLAIM.md experiments/01_policy_control/EXPERIMENT.md
git ls-files --others --exclude-standard -- Makefile pyproject.toml uv.lock experiments/__init__.py experiments/01_policy_control/__init__.py experiments/01_policy_control/run.py experiments/01_policy_control/src experiments/01_policy_control/tests experiments/01_policy_control/configs/base.yaml experiments/01_policy_control/README.md experiments/01_policy_control/CLAIM.md experiments/01_policy_control/EXPERIMENT.md
git diff --check
```

Expected: all exit 0; the secret query prints nothing; size is at most 7,544 MiB; the
implementation diff, untracked-path scan, and whitespace check print nothing. `audit_references` supplies
the tracked-checkout/model scan; `analyze` has already replayed every complete shard.

- [ ] Generate the bounded reports and all five deterministic plots through the
reviewed CLI, never by manual editing:

```text
UV_CACHE_DIR=.cache/uv uv run python -m experiments.01_policy_control.run --config experiments/01_policy_control/configs/frozen.yaml --p3-gate experiments/01_policy_control/configs/p3-gate.yaml --phase report --manifest experiments/01_policy_control/protocol/confirmation/seed-manifest.json --output-dir experiments/01_policy_control/results --headless
```

Expected: exit 0 without MuJoCo import; atomically replace only the reviewed Task 12
Markdown placeholders, create the five named SVGs plus `artifact-digests.json`, and
report the stack-level conclusion, every rejection, promoted stacks, and deduplicated
wire strings without a general or representation-only claim. An exact reissue
validates-and-skips every output.

```bash
git add experiments/01_policy_control/protocol/confirmation/artifact-digests.json experiments/01_policy_control/protocol/confirmation/plots/recovery-vs-latency.svg experiments/01_policy_control/protocol/confirmation/plots/tracking-error-vs-rate.svg experiments/01_policy_control/protocol/confirmation/plots/joint-jerk.svg experiments/01_policy_control/protocol/confirmation/plots/action-age.svg experiments/01_policy_control/protocol/confirmation/plots/timeline.svg experiments/01_policy_control/RESULTS.md experiments/01_policy_control/INTERFACE_FINDINGS.md
git commit -m "docs: report experiment 01 decision"
git status --porcelain=v1 --untracked-files=all
```

Expected: the final status prints nothing. Any tracked or untracked residue leaves the
phase unsealed and prevents runtime authority.

Never stage `experiments/01_policy_control/results/`.

## Self-review

- Coverage: P3/safety, all six stacks, exact kinematics/P5/P6, timing/safe hold/events, scenario fairness, metrics/domains, pilot/freeze, inference/gates/plots, atomic CLI/resume/resources/report all map to Tasks 1-15.
- Type check: representation is string; `run_episode` returns `RolloutRecord`; `ReplayResult` includes `rollout_id`; fixture cutoff is 2650; evidence arrays use byte/value equality.
- Placeholder check: `rg -n -i 'T[B]D|T[O]DO|implement la[t]er|fill in detai[l]s|similar to tas[k]|appropriate erro[r]' docs/superpowers/plans/2026-08-22-p4-policy-control-boundary.md` must return no matches.
- Ownership: every implementer task and every live-evidence phase is serial; Task 4
  explicitly depends on Task 3. No `reflect/` edit exists.

Plan complete. Execute task-by-task with subagent-driven development and retain review gates, especially the hard no-live-pilot boundary before Task 13.

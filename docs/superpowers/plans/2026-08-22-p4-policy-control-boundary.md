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

**Files:** Create `experiments/__init__.py`, `experiments/01_policy_control/__init__.py`, `experiments/01_policy_control/src/__init__.py`, `experiments/01_policy_control/src/contracts.py`, `experiments/01_policy_control/configs/base.yaml`, `experiments/01_policy_control/tests/test_contracts.py`.

**Interfaces:** Define before use: `CommandStack(P1..P6)`, `FaultKind(NONE,DROP,OUT_OF_ORDER,STATIONARY_CONTROL)`, frozen `ArmConfig`, `ControllerConfig`, `TimingConfig`, `ResourceConfig`, `ExperimentConfig`, `Condition`, `Scenario`, `PolicyInput`, `ExecutorState`, `ClampReport`, `EpisodeMetrics`, `SeedMetrics`, `ShardSpec`; `load_config(Path)->ExperimentConfig`, `canonical_json_bytes`, `sha256_file`. `PolicyInput` contains `Observation`, `SkillSpec`, response time, policy period, initial q, initial-target IK q. `ExecutorState` contains active ID, latched q, P5 previous velocity/planner reference/enabled.

- [ ] **RED test**

```python
def test_exact_base() -> None:
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
git add experiments/__init__.py experiments/01_policy_control/__init__.py experiments/01_policy_control/src/__init__.py experiments/01_policy_control/src/contracts.py experiments/01_policy_control/configs/base.yaml experiments/01_policy_control/tests/test_contracts.py
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

Return copies; clamp booleans use actual pre-clamp exceedance. Run `MUJOCO_GL=disable ... pytest .../test_arm.py -q`; expected PASS.

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

- [ ] RED: stage order base, two PD, two IK, two P5 smoothness, final-four; counts `{P1:164,P2:164,P3:164,P4:164,P5:188,P6:164}`, total `1008`; all ties pick base order; every survivor shares selected PD/IK; P1 failure returns `INCONCLUSIVE/STOPPED`; final four evaluated once.
- [ ] GREEN: every create-only manifest binds predecessor/config/implementation/parameter hashes and sorted episodes. Base fixes survivors. Candidate feasible only with all fixed-survivor episodes. Score equals mean 3 conditions per `(stack,seed)`, then 4 seeds per stack, then survivors equally. Non-base failures invalidate candidate, never alter survivors. Reuse selected baseline hashes. P5 scalar uses P5 only. Final four run 26 conditions once and cannot tune. Enforce two revisions.
- [ ] Before implementation run: `UV_CACHE_DIR=.cache/uv uv run pytest experiments/01_policy_control/tests/test_pilot_selection.py -q`

Expected: FAIL because pilot APIs are absent.

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

- [ ] RED: exact SHA/PCG64 seed; 10,000 resamples; adjusted 99% endpoints; equality passes `-.10/+.10` and absolute budgets; P1/control failure inconclusive; promotion maximum two in upper-bound/P1-P6 tie order; P1+P2 produces `("JOINT_POSITION",)`; repeated SVG bytes equal.

Run: `UV_CACHE_DIR=.cache/uv uv run pytest experiments/01_policy_control/tests/test_inference.py experiments/01_policy_control/tests/test_plots.py -q`

Expected: FAIL because inference/plot APIs are absent.
- [ ] GREEN: sort paired complete seeds, resample count with replacement, nearest-rank endpoints, no imputation. Implement pooled recovery/clamp/saturation and two-stage jerk/discontinuity p95. Superior then noninferior ranking, P1 self upper 0, absolute gates, exact SUPPORTED/NOT_SUPPORTED/INCONCLUSIVE. Stable-first wire string deduplication.
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

**Interfaces:** `iter_manifest(Path)->Iterator[ShardSpec]`, `publish_or_validate_skip`, `run_shard`, `validate_phase`, `analyze_phase`, `freeze_protocol`, `generate_confirmation_manifest`, `write_report`. Single CLI: `--config --p3-gate --phase pilot|freeze|confirmation|analyze|report [--manifest PATH] --output-dir --headless [--shard-id] [--list-shards] [--stage revision|base|pd_60_6|pd_100_10|ik_0_001|ik_0_05|p5_0_01|p5_0_04|final_four] [--prepare-manifest PATH] [--bind-preregistration PATH] [--dry-run] [--max-episodes]`. `--stage revision --prepare-manifest` is the sole no-predecessor case and atomically writes the protocol revision plus pilot seed partition; every later prepare consumes the validated predecessor named by `--manifest`. Preparation never runs physics; without it, pilot/confirmation execute exactly one shard. `--bind-preregistration` is confirmation-only: it requires the seed and protocol manifests to be tracked at clean `HEAD`, then atomically writes a canonical binding containing that 40-hex commit and both Git-blob/content hashes. `--list-shards` validates the named manifest and prints its current-stage shard IDs one per line in canonical order without importing MuJoCo or creating output. With `--max-episodes N`, it requires `N` to equal the stage's declared episode count and lists exactly those shards; a validated killed-P5 stage may return an empty list. It cannot be combined with `--shard-id` or evidence execution.

- [ ] RED artifact test:

```python
assert publish_or_validate_skip(RECORD,destination,SPEC)=="published"
assert publish_or_validate_skip(RECORD,destination,SPEC)=="validated-and-skipped"
artifact=validate_rollout(destination); replay=replay_rollout(destination)
assert replay.rollout_id==destination.name
assert replay.events==artifact.events and replay.observations==artifact.observations
assert replay.frames[-1].state==replay.final_state
```

Also corrupt a byte/extra file/temporary dir and require refusal; verify sorted root-relative manifest iterator and exact `--list-shards` output; dry-run no MuJoCo/output; evidence requires exact complete shard and headless. Confirmation execution requires the sibling `preregistration-binding.json`, verifies that its 40-hex commit contains byte-identical seed/protocol manifests, and records that commit in every shard completion manifest.

Run: `UV_CACHE_DIR=.cache/uv uv run pytest experiments/01_policy_control/tests/test_artifacts_cli.py -q`

Expected: collection FAIL with missing `artifacts`.

- [ ] GREEN artifacts: absent output uses `RolloutWriter.write`, then size, `validate_rollout`, `replay_rollout`. Existing output validates exact file/artifact/protocol/source/scenario/condition hashes, metadata, events, observation/action/reference bytes, and terminal replay; never rewrites. Phase/shard manifests use `O_EXCL`, fsync, absent rename. `ReplayResult` fields are exactly rollout_id/events/observations/frames/final_state.
- [ ] GREEN CLI: safety/P3 gate precedes local imports; root-contain all paths. Dry-run prints canonical sorted JSON. Freeze validates all pilot artifacts and writes config plus external digest (no self digest). Confirmation generator requires frozen protocol/new RNG. Analyze/report never import physics. Report atomically replaces only the reviewed Task 12 placeholder report bytes, and an exact reissue validates-and-skips; it writes the two Markdown reports and five canonical SVGs named in Task 15. Reports preserve the bounded stack-level claim.
- [ ] Add exact Make target invoking root-relative base config, P3 gate, base manifest, ignored results, required `SHARD`.
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
UV_CACHE_DIR=.cache/uv uv run python -m experiments.01_policy_control.run --config experiments/01_policy_control/configs/base.yaml --p3-gate experiments/01_policy_control/configs/p3-gate.yaml --phase pilot --manifest experiments/01_policy_control/protocol/pilot-r1/base-manifest.json --output-dir experiments/01_policy_control/results --headless --shard-id P1:base:000 --max-episodes 3 --dry-run
```

Expected: all exit 0; the two preparation commands publish only small manifests without MuJoCo, and the final dry-run prints exactly three sorted episodes without creating results.
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
  P4_SHARD_TEXT="$(UV_CACHE_DIR=.cache/uv uv run python -m experiments.01_policy_control.run --config experiments/01_policy_control/configs/base.yaml --p3-gate experiments/01_policy_control/configs/p3-gate.yaml --phase pilot --manifest "$P4_MANIFEST_PATH" --output-dir experiments/01_policy_control/results --headless --list-shards --max-episodes "$P4_EPISODE_COUNT")" || return 1
  if [[ -n "$P4_SHARD_TEXT" ]]; then
    while IFS= read -r P4_SHARD_ID; do
      MUJOCO_GL=disable UV_CACHE_DIR=.cache/uv uv run python -m experiments.01_policy_control.run --config experiments/01_policy_control/configs/base.yaml --p3-gate experiments/01_policy_control/configs/p3-gate.yaml --phase pilot --manifest "$P4_MANIFEST_PATH" --output-dir experiments/01_policy_control/results --headless --shard-id "$P4_SHARD_ID" --max-episodes "$P4_EPISODE_COUNT" || return 1
    done <<< "$P4_SHARD_TEXT"
  fi
}
```

Expected: the listing validates exact stage identity/counts and imports no MuJoCo.
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

Expected: P1 base/final-four failure stops; all later preparation refuses a failed
predecessor. The final-four manifest contains one shard per surviving stack/seed, each
with 26 episodes and the selected complete configuration hash. Exact maximum remains
1,008 episodes and 6,300 simulated seconds; reused evaluations are not re-executed.

- [ ] Validate all pilot artifacts and create the small digests/decision without
running physics:

```text
UV_CACHE_DIR=.cache/uv uv run python -m experiments.01_policy_control.run --config experiments/01_policy_control/configs/base.yaml --p3-gate experiments/01_policy_control/configs/p3-gate.yaml --phase analyze --manifest experiments/01_policy_control/protocol/pilot-r1/final-four-manifest.json --output-dir experiments/01_policy_control/results --headless
```

Expected: exit 0 and atomically create only `stage-digests.json` and
`pilot-decision.json` after validating exact 164/188/1,008 counts, reuse hashes,
survivors, shared PD/IK, P5 selection or killed disposition, and one-shot final four.

- [ ] Commit every pilot-stage manifest and its derived evidence before Freeze:

```bash
git add experiments/01_policy_control/protocol/pilot-r1/base-manifest.json experiments/01_policy_control/protocol/pilot-r1/pd_60_6-manifest.json experiments/01_policy_control/protocol/pilot-r1/pd_100_10-manifest.json experiments/01_policy_control/protocol/pilot-r1/ik_0_001-manifest.json experiments/01_policy_control/protocol/pilot-r1/ik_0_05-manifest.json experiments/01_policy_control/protocol/pilot-r1/p5_0_01-manifest.json experiments/01_policy_control/protocol/pilot-r1/p5_0_04-manifest.json experiments/01_policy_control/protocol/pilot-r1/final-four-manifest.json experiments/01_policy_control/protocol/pilot-r1/stage-digests.json experiments/01_policy_control/protocol/pilot-r1/pilot-decision.json
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

```text
UV_CACHE_DIR=.cache/uv uv run python -m experiments.01_policy_control.run --config experiments/01_policy_control/configs/base.yaml --p3-gate experiments/01_policy_control/configs/p3-gate.yaml --phase freeze --manifest experiments/01_policy_control/protocol/pilot-r1/final-four-manifest.json --output-dir experiments/01_policy_control/results --headless
```

Expected: exit 0 after validating every committed pilot manifest/shard, P1 disposition, counts/reuse hashes, shared PD/IK, P5 scalar, thresholds and P1 smoothness. Config does not self-hash; separate digest hashes exact bytes. Commit only:

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

- [ ] Preflight the full 7,544 MiB ceiling. Define and invoke this exact serial zsh
executor for the 27-episode first-four-seed shards and 26-episode remaining shards:

```zsh
run_p4_confirmation_count() {
  local P4_EPISODE_COUNT="$1"
  local P4_SHARD_TEXT
  P4_SHARD_TEXT="$(UV_CACHE_DIR=.cache/uv uv run python -m experiments.01_policy_control.run --config experiments/01_policy_control/configs/frozen.yaml --p3-gate experiments/01_policy_control/configs/p3-gate.yaml --phase confirmation --manifest experiments/01_policy_control/protocol/confirmation/seed-manifest.json --output-dir experiments/01_policy_control/results --headless --list-shards --max-episodes "$P4_EPISODE_COUNT")" || return 1
  while IFS= read -r P4_SHARD_ID; do
    MUJOCO_GL=disable UV_CACHE_DIR=.cache/uv uv run python -m experiments.01_policy_control.run --config experiments/01_policy_control/configs/frozen.yaml --p3-gate experiments/01_policy_control/configs/p3-gate.yaml --phase confirmation --manifest experiments/01_policy_control/protocol/confirmation/seed-manifest.json --output-dir experiments/01_policy_control/results --headless --shard-id "$P4_SHARD_ID" --max-episodes "$P4_EPISODE_COUNT" || return 1
  done <<< "$P4_SHARD_TEXT"
}
run_p4_confirmation_count 27
run_p4_confirmation_count 26
```

Expected: the first four seeds use 27 episodes including the stationary control and
all later seeds use 26; each manifest-derived shard runs exactly once. Maximum remains
836 paired bundles, 5,016 rollouts, 31,350 simulated seconds, and 5,016 MiB plus
256 MiB. Exact reissue validates-and-skips; corruption stops.
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
git diff --check
```

Expected: all exit 0; the secret query prints nothing; size is at most 7,544 MiB; the
implementation diff and whitespace check print nothing. `audit_references` supplies
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
```

Never stage `experiments/01_policy_control/results/`.

## Self-review

- Coverage: P3/safety, all six stacks, exact kinematics/P5/P6, timing/safe hold/events, scenario fairness, metrics/domains, pilot/freeze, inference/gates/plots, atomic CLI/resume/resources/report all map to Tasks 1-15.
- Type check: representation is string; `run_episode` returns `RolloutRecord`; `ReplayResult` includes `rollout_id`; fixture cutoff is 2650; evidence arrays use byte/value equality.
- Placeholder check: `rg -n -i 'T[B]D|T[O]DO|implement la[t]er|fill in detai[l]s|similar to tas[k]|appropriate erro[r]' docs/superpowers/plans/2026-08-22-p4-policy-control-boundary.md` must return no matches.
- Ownership: every implementer task and every live-evidence phase is serial; Task 4
  explicitly depends on Task 3. No `reflect/` edit exists.

Plan complete. Execute task-by-task with subagent-driven development and retain review gates, especially the hard no-live-pilot boundary before Task 13.

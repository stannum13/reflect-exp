# P4 Policy-to-Controller Boundary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build Experiment 01: a deterministic, simulation-only 3R moving-target comparison of P1–P6 command stacks, with immutable pilot/confirmation evidence and a mechanical P4 promotion decision.

**Architecture:** Keep the experiment self-contained under `experiments/01_policy_control`; it consumes P3’s locked MuJoCo/source evidence and only uses existing `reflect` contracts for canonical artifacts, virtual time, events, replay, and safety. Freeze the YAML/API contract before parallel implementation, then integrate serially through a deterministic runner whose live pilot, freeze, and confirmation lifecycle never reruns or overwrites evidence.

**Tech Stack:** CPython 3.11.13; NumPy 2.x; PyYAML 6.x; PyArrow 21.x; pytest 9.x; P3-approved locked MuJoCo 3.x; existing `reflect` rollout, clock, event, replay, and safety APIs.

## Global Constraints

- P4 is execution-blocked until P3 is complete: complete P2 audit, P3-approved locked MuJoCo M2 smoke, source/license/compatibility outputs, and physical/remote execution disabled.
- Use only the exact P3-approved MuJoCo package; do not install/import Mink, MuJoCo MPC, Menagerie, mjctrl, Rerun, MoveIt, ros2_control, cuRobo, ROS 2, CUDA, VLA models, datasets, or training code.
- Keep all P4 arm/controller/task/metrics/plots in `experiments/01_policy_control`; do not merge toy implementation details into `reflect`.
- The inline 3R arm uses links `(0.30, 0.25, 0.20)` m, joint limits `[-2.70,2.70]` rad, torque range `[-12,12]` Nm, damping `0.10`, zero gravity, timestep `0.002` s, and a 500 Hz loop.
- All stacks use the same `1.5 rad/s` per-joint slew limiter, PD pair selected globally from `(80,8)`, `(60,6)`, `(100,10)`, and torque/joint/reference bounds that fail closed and log clamps.
- Use only `VirtualClock` for experimental decisions; no sleep or wall-clock latency decision. Run latency-sensitive pilot and confirmation shards serially.
- Preserve existing `ActionRepresentation`; stack identity is `ActionChunk.metadata["stack_id"]`. All chunks use response-delivery generated/valid times, `dt_s=policy_period_s`, expiry `delivery + ceil(2.5P)`, and half-open validity.
- Every evidence-bearing run is headless, simulation-only, exactly one declared shard, max 60 wall minutes/shard, max 1 MiB serialized rollout, create-only, and validate-and-skip only on exact hash identity.
- Pilot has at most two revisions and eight paired seeds/revision; its first four tune and its final four are used once only for selected-vector evaluation. Confirmation seeds are generated only after Freeze.
- Confirmation has 32 scenario seeds, 24 core conditions plus two probes for all seeds, stationary negative control for first four seeds, 10,000 paired bootstrap resamples, Bonferroni-adjusted 99% intervals, at most two promoted stacks, and declared maximum 7,544 MiB under the 10 GiB phase ceiling.
- P4 reports stack-level, not representation-only, causality; `SUPPORTED`, `NOT_SUPPORTED`, and `INCONCLUSIVE` use the frozen thresholds and never substitute a new stack after failure.

---

## File map and ownership

| Path | Responsibility | Ownership wave |
| --- | --- | --- |
| `experiments/__init__.py`, `experiments/01_policy_control/__init__.py` | importable experiment package | serial API freeze |
| `experiments/01_policy_control/configs/base.yaml` | all constants, candidate orders, schemas, limits, named RNG roots | serial API freeze |
| `experiments/01_policy_control/src/arm.py` | inline MJCF, 3R simulation, FK/Jacobian, scenario feasibility, PD/slew clamps | parallel arm worker |
| `experiments/01_policy_control/src/representations.py` | P1–P6 emission/decoding, IK/interpolation/MPC/residual executor state | parallel representation worker |
| `experiments/01_policy_control/src/timing.py` | request/response queue, cutoff, faults, chunk lifecycle/event ordering | parallel timing worker |
| `experiments/01_policy_control/src/evaluate.py` | episodes, metrics, pilot selection, bootstrap, gates, SVGs | second-wave evaluation worker |
| `experiments/01_policy_control/run.py` | config/manifest validation, one-shard CLI, create-only publication/resume | second-wave integration worker |
| `experiments/01_policy_control/{README,CLAIM,EXPERIMENT,RESULTS,INTERFACE_FINDINGS}.md` | bounded claim, reproducibility, final evidence report | orchestrator only |
| `experiments/01_policy_control/tests/test_*.py` | isolated contract, integration, CLI, lifecycle tests | same owner as source except integration |
| `Makefile` | `exp01` one-shard target | integration worker |

### Task 1: Gate P4, freeze local APIs/configuration, and create the Draft skeleton

**Files:**
- Create: `experiments/__init__.py`, `experiments/01_policy_control/__init__.py`, `experiments/01_policy_control/configs/base.yaml`, `experiments/01_policy_control/{README.md,CLAIM.md,EXPERIMENT.md,RESULTS.md,INTERFACE_FINDINGS.md}`
- Create: `experiments/01_policy_control/src/__init__.py`, `experiments/01_policy_control/tests/test_config.py`

**Interfaces:** Consumes P3 complete report/source hashes and `reflect.safety.SafetyConfig`. Produces immutable `ExperimentConfig`, `CommandStack` IDs `P1`…`P6`, condition IDs, all finite candidate sequences, and `require_p3_gate(config) -> None`; later tasks import only these names.

- [ ] **Step 1: Write failing configuration/gate tests**

```python
def test_base_config_has_exact_six_stacks_and_frozen_candidate_orders() -> None:
    cfg = load_base_config(BASE)
    assert cfg.stack_ids == ("P1", "P2", "P3", "P4", "P5", "P6")
    assert cfg.pd_candidates == ((80.0, 8.0), (60.0, 6.0), (100.0, 10.0))
    assert cfg.ik_damping_candidates == (0.01, 0.001, 0.05)
    assert cfg.mpc_smoothness_candidates == (0.02, 0.01, 0.04)
    assert cfg.dt_s == 0.002 and cfg.episode_s == 6.25

def test_execution_refuses_missing_p3_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gate, "p3_is_complete", lambda: False)
    with pytest.raises(P4GateError, match="P3"):
        require_p3_gate(load_base_config(BASE))
```

- [ ] **Step 2: Prove RED**

Run: `UV_CACHE_DIR=.cache/uv uv run pytest experiments/01_policy_control/tests/test_config.py -q`

Expected: collection fails because the experiment package/config loader does not exist.

- [ ] **Step 3: Implement the frozen Draft contract**

Create a strict loader that rejects unknown/missing YAML keys and nonfinite values. Put in `base.yaml`: arm constants; `policy_hz=(5,10,20)`; core latencies `(0,100,300,700)` ms; one/two-move paths; two named fault probes; 2.5P expiry; cut-off equation; target/recovery limits; candidate orders; 8 pilot seed generation procedure; 64 candidate confirmation seed procedure; exact thresholds; all artifact caps; and fixed source/P3 hash fields required at execution. `require_p3_gate` must run the complete offline source audit, validate the recorded P3 compatibility/MuJoCo smoke hashes, and call `SafetyConfig.from_mapping(os.environ).require_simulation_only()`.

- [ ] **Step 4: Run GREEN and commit the contract**

Run:

```text
UV_CACHE_DIR=.cache/uv uv run pytest experiments/01_policy_control/tests/test_config.py -q
UV_CACHE_DIR=.cache/uv uv run python -m reflect.safety check
git diff --check
```

Expected: PASS; safety output says `simulation_only: true`.

Commit:

```bash
git add experiments/__init__.py experiments/01_policy_control
git commit -m "feat: freeze experiment 01 configuration contract"
```

### Task 2: Implement the deterministic arm, analytic geometry, and scenarios

**Files:**
- Create: `experiments/01_policy_control/src/arm.py`
- Create: `experiments/01_policy_control/tests/test_arm.py`

**Interfaces:** Consumes `ExperimentConfig`. Produces `ArmConfig`, `PlanarArm`, `ClampReport`, `Scenario`, `forward_kinematics(q)->np.ndarray`, `jacobian(q)->np.ndarray`, `generate_scenario(seed, cfg)->Scenario`, `bounded_pd(q_ref,q,dq,previous_ref,cfg)->tuple[np.ndarray,np.ndarray,ClampReport]`.

- [ ] **Step 1: Write failing geometry/scenario tests**

```python
def test_analytic_fk_and_jacobian_match_mujoco_and_finite_difference() -> None:
    arm = PlanarArm(load_base_config(BASE).arm)
    q = np.array([0.35, -0.70, 0.35])
    np.testing.assert_allclose(forward_kinematics(q), arm.eef_site_xy(q), atol=1e-10)
    np.testing.assert_allclose(jacobian(q), centred_difference(forward_kinematics, q), atol=1e-6)

def test_scenario_is_seeded_reachable_and_bounded() -> None:
    scenario = generate_scenario(7, load_base_config(BASE))
    assert scenario == generate_scenario(7, load_base_config(BASE))
    assert scenario.proposal_count <= 32
    assert all(0.30 <= np.linalg.norm(x) <= 0.70 for x in scenario.all_targets)
```

- [ ] **Step 2: Prove RED**

Run: `UV_CACHE_DIR=.cache/uv uv run pytest experiments/01_policy_control/tests/test_arm.py -q`

Expected: collection fails because `src.arm` does not exist.

- [ ] **Step 3: Implement exact dynamics boundaries**

Build the inline MJCF string with named third-tip site and exact model values. Implement analytic 2x3 FK/Jacobian from the three link lengths; 12-iteration feasibility absolute IK using base `lambda=0.01`, posture `[.35,-.70,.35]`, `clip_norm(.10)`, and internal `[-2.55,2.55]` clamp. Generate immutable scenario records with PCG64 named substreams, compass directions, fixed t=2/t=4 paths, rejection recording, and ascending candidate seed consumption. Implement per-joint slew then common PD/torque clamps; every clamp returns named count/boolean fields.

- [ ] **Step 4: Run GREEN and commit**

Run:

```text
UV_CACHE_DIR=.cache/uv uv run pytest experiments/01_policy_control/tests/test_arm.py -q
UV_CACHE_DIR=.cache/uv uv run pytest tests/test_safety.py -q
git diff --check
```

Expected: PASS, including headless MuJoCo construction.

Commit: `git add experiments/01_policy_control/src/arm.py experiments/01_policy_control/tests/test_arm.py && git commit -m "feat: add deterministic experiment arm"`

### Task 3: Implement P1–P6 chunk emission and executor semantics

**Files:**
- Create: `experiments/01_policy_control/src/representations.py`
- Create: `experiments/01_policy_control/tests/test_representations.py`

**Interfaces:** Consumes Task 1 config, Task 2 geometry, `reflect.types.{ActionChunk,ActionRepresentation,ControlReference,Observation,SkillSpec}`. Produces `CommandStack`, `PolicyInput`, `ExecutorState`, `emit_chunk(stack,input,cfg)->ActionChunk`, `reference_for_tick(stack,chunk,q,dq,time_ns,state,cfg)->tuple[ControlReference,ExecutorState,ClampReport]`.

- [ ] **Step 1: Write failing value-domain/lifecycle tests**

```python
@pytest.mark.parametrize("stack,shape,wire", [
    (CommandStack.P1, (1,3), "JOINT_POSITION"), (CommandStack.P2, (81,3), "JOINT_POSITION"),
    (CommandStack.P3, (1,2), "EEF_TRAJECTORY"), (CommandStack.P4, (81,2), "EEF_TRAJECTORY"),
    (CommandStack.P5, (1,2), "MPC_GOAL"), (CommandStack.P6, (1,3), "BOUNDED_RESIDUAL"),
])
def test_emitted_chunk_has_exact_shape_metadata_and_immutable_actions(stack, shape, wire):
    chunk = emit_chunk(stack, policy_input(period_s=.01), CFG)
    assert chunk.actions.shape == shape and chunk.representation.value == wire
    assert chunk.metadata["stack_id"] == stack.value and not chunk.actions.flags.writeable
    assert chunk.expires_at_ns - chunk.valid_from_ns == 25_000_000

def test_p5_velocity_history_resets_only_on_expiry_safe_hold():
    state = ExecutorState.initial(CommandStack.P5)
    _, state, _ = reference_for_tick(CommandStack.P5, valid_p5_chunk(), Q, DQ, 0, state, CFG)
    assert np.any(state.qdot_previous != 0)
    assert state.after_valid_replacement().qdot_previous is state.qdot_previous
    assert np.array_equal(state.after_safe_hold().qdot_previous, np.zeros(3))
```

- [ ] **Step 2: Prove RED**

Run: `UV_CACHE_DIR=.cache/uv uv run pytest experiments/01_policy_control/tests/test_representations.py -q`

Expected: collection fails because `src.representations` does not exist.

- [ ] **Step 3: Implement each specified executor exactly**

Emit P1 absolute IK; P2 straight XY/12-solve knots with `H=ceil(.8/P)+1`; P3 one XY target/differential IK; P4 XY knots/differential IK; P5 79 ordered candidates (zero plus magnitudes `.25,.75,1.50` and normalized lexicographic directions), ten 20ms steps and dimensionless specified objective; P6 minimum-jerk nominal plus component-clipped residual. Implement the shared absolute/differential IK formulas, closed-interval knot interpolation, half-open chunk validity, and read-only issued references. Preserve P5 `qdot_previous` on valid replacement/rejection, update atomically only at 50Hz planner ticks, reset exactly on expiry safe hold, and process coincident delivery before planner tick.

- [ ] **Step 4: Run GREEN and commit**

Run:

```text
UV_CACHE_DIR=.cache/uv uv run pytest experiments/01_policy_control/tests/test_representations.py -q
UV_CACHE_DIR=.cache/uv uv run pytest tests/test_types.py -q
git diff --check
```

Expected: PASS; hand-calculated 4cm/6cm fixtures choose moving feasible MPC candidate over hold.

Commit: `git add experiments/01_policy_control/src/representations.py experiments/01_policy_control/tests/test_representations.py && git commit -m "feat: add policy controller command stacks"`

### Task 4: Implement deterministic scheduling, faults, and event lifecycle

**Files:**
- Create: `experiments/01_policy_control/src/timing.py`
- Create: `experiments/01_policy_control/tests/test_timing.py`

**Interfaces:** Consumes `VirtualClock`, `ExecutionEventType`, chunks from Task 3. Produces `FaultKind`, `TimingCondition`, `PolicyRequest`, `ScheduledResponse`, `DeliveryBatch`, `last_request_time_ns`, `schedule_response(request,condition)->ScheduledResponse|None`, `deliver_due(now_ns,queue,last_accepted_observation_id)->DeliveryBatch`.

- [ ] **Step 1: Write failing ordering/fault tests**

```python
def test_zero_latency_delivery_is_responded_then_accepted_on_same_tick():
    batch = deliver_due(0, queue_with_request(0, latency_ms=0), -1)
    assert [e.event_type.value for e in batch.events] == ["POLICY_RESPONDED", "CHUNK_ACCEPTED"]

def test_out_of_order_and_expired_have_canonical_dispositions():
    assert deliver_due(30, queue_old_observation(), 9).disposition == "out_of_order"
    assert deliver_due(25, queue_expiring_at(25), -1).disposition == "expired"

def test_cutoff_keeps_all_non_dropped_expiry_inside_episode():
    assert last_request_time_ns(6_250_000_000, 700_000_000, 200_000_000, 10_000_000) == 5_340_000_000
```

- [ ] **Step 2: Prove RED**

Run: `UV_CACHE_DIR=.cache/uv uv run pytest experiments/01_policy_control/tests/test_timing.py -q`

Expected: collection fails because `src.timing` does not exist.

- [ ] **Step 3: Implement the nine-step 2ms loop contract**

Use `(delivery_time_ns,request_sequence)` heap order and cutoff `end-L-D-ceil(2.5P)`. At each tick: movement; one policy/telemetry observation when coincident; schedule; delivery; `POLICY_RESPONDED` then stale/expired disposition or acceptance; replace only still-valid old chunk; decode/hold; step; decimated 10ms telemetry; advance. Implement dropped response, forced out-of-order delay `D=P+2ms`, expiry, replacement, source-age metrics, stop cutoff, pending-drop declaration, empty final queue, and safe-hold latching current q/zero dq. Never create an observation twice.

- [ ] **Step 4: Run GREEN and commit**

Run: `UV_CACHE_DIR=.cache/uv uv run pytest experiments/01_policy_control/tests/test_timing.py tests/test_clock.py tests/test_events.py -q`

Expected: PASS for 0/100/300/700ms and all probes.

Commit: `git add experiments/01_policy_control/src/timing.py experiments/01_policy_control/tests/test_timing.py && git commit -m "feat: add deterministic experiment timing"`

### Task 5: Integrate episodes, metrics, immutable rollout evidence, and analysis

**Files:**
- Create: `experiments/01_policy_control/src/evaluate.py`, `experiments/01_policy_control/tests/test_evaluate.py`

**Interfaces:** Consumes Tasks 2–4 and `RolloutWriter`, `validate_rollout`, `replay_rollout`. Produces `run_episode(stack,condition,scenario,cfg)->RolloutRecord`, `EpisodeMetrics`, `SeedMetrics`, `aggregate_seed_metrics(records)->SeedMetrics`, `select_pilot(records)->PilotSelection`, `paired_bootstrap(seed_metrics,resamples=10_000)->BootstrapDecision`, `apply_gate(decision,frozen)->PromotionDecision`, `write_svg_plots(aggregate,out)->tuple[Path,...]`.

- [ ] **Step 1: Write failing metrics/decision tests**

```python
def test_recovery_is_dwell_based_and_timeout_is_censored():
    assert recovery_time(errors=[.02] * 50, move_ns=0, dt_s=.002) == pytest.approx(.10)
    assert recovery_time(errors=[.03] * 1000, move_ns=0, dt_s=.002) == 2.0

def test_global_pilot_tie_and_promotion_are_mechanical():
    assert select_pilot(fixture_scores()).pd == (80.0, 8.0)
    promotion = apply_gate(fixture_confirmation(), frozen_config())
    assert promotion.promoted_stacks == ("P2", "P1")
    assert promotion.promoted_wire_representations == ("JOINT_POSITION",)
```

- [ ] **Step 2: Prove RED**

Run: `UV_CACHE_DIR=.cache/uv uv run pytest experiments/01_policy_control/tests/test_evaluate.py -q`

Expected: collection fails because `src.evaluate` does not exist.

- [ ] **Step 3: Implement measurement and all mechanical choices**

Accumulate 500Hz metrics and decimate telemetry at 100Hz. Implement recovery, source/action age, error, jerk, discontinuity, saturation/clamp, negative-control, missing-data, nearest-rank p95, and equal seed weights. Implement base survivor qualification; global PD then global IK reuse; P5-only smoothness; all-infeasible/anchor STOP; final-four one-shot rule; exact 60/164 non-P5 and 188 P5 maxima. Implement deterministic paired PCG64 bootstrap seed from frozen hash; all thresholds, classifications, ranking/ties, two-stack cap, and wire deduplication. Write exactly five deterministic labelled SVGs and report data without rerunning physics.

- [ ] **Step 4: Run GREEN and commit**

Run: `UV_CACHE_DIR=.cache/uv uv run pytest experiments/01_policy_control/tests/test_evaluate.py -q`

Expected: PASS, including equality boundaries, 99% intervals, and `SUPPORTED`/`NOT_SUPPORTED`/`INCONCLUSIVE` fixtures.

Commit: `git add experiments/01_policy_control/src/evaluate.py experiments/01_policy_control/tests/test_evaluate.py && git commit -m "feat: add experiment evaluation and gates"`

### Task 6: Build the one-shard CLI, manifests, and create-only resume path

**Files:**
- Create: `experiments/01_policy_control/run.py`, `experiments/01_policy_control/tests/test_run.py`
- Modify: `Makefile`

**Interfaces:** Consumes all prior tasks. Produces `python -m experiments.01_policy_control.run --config CONFIG [--seed SEED] [--output-dir DIR] [--dry-run] [--max-episodes N] [--headless] [--phase pilot|confirmation|analyze] [--shard-id STACK:CONFIGURATION:SEED]`, `resolve_shard`, `publish_or_validate_skip`, and `make exp01 SHARD=P1:base:000`.

- [ ] **Step 1: Write failing CLI/resume tests**

```python
def test_evidence_run_requires_one_headless_declared_shard(cli):
    assert cli("--phase", "pilot").exit_code == 2
    assert cli("--phase", "pilot", "--headless", "--shard-id", "P1:base:000").exit_code == 0

def test_existing_exact_artifact_skips_and_mismatch_refuses(cli, artifact):
    assert cli(*artifact.argv).stdout.endswith("validated-and-skipped\n")
    artifact.tamper("metrics.json")
    assert cli(*artifact.argv).exit_code != 0
```

- [ ] **Step 2: Prove RED**

Run: `UV_CACHE_DIR=.cache/uv uv run pytest experiments/01_policy_control/tests/test_run.py -q`

Expected: collection fails because `run.py` does not exist.

- [ ] **Step 3: Implement bounded publication**

Validate config/P3/safety before simulation. `--dry-run` prints the sorted manifest without MuJoCo; `--max-episodes` is smoke-only unless exactly the selected shard count. Build protocol/seed/artifact manifests with config/code/P2/P3/scenario/condition hashes. Use `RolloutWriter`; before reuse, call `validate_rollout`, replay, and compare all identity hashes/files/size; only exact matches skip. Refuse interrupted/extra/missing/tampered destinations. Publish one completion manifest only after every episode. Add Make target that rejects empty `SHARD` and invokes the headless one-shard command.

- [ ] **Step 4: Run GREEN and commit**

Run:

```text
UV_CACHE_DIR=.cache/uv uv run pytest experiments/01_policy_control/tests/test_run.py tests/test_rollout.py tests/test_replay.py -q
UV_CACHE_DIR=.cache/uv uv run python -m experiments.01_policy_control.run --config experiments/01_policy_control/configs/base.yaml --dry-run --phase pilot --shard-id P1:base:000
git diff --check
```

Expected: PASS; dry run prints only deterministic manifest JSON.

Commit: `git add experiments/01_policy_control/run.py experiments/01_policy_control/tests/test_run.py Makefile && git commit -m "feat: add bounded experiment runner"`

### Task 7: Review and complete Draft integration before live measurement

**Files:**
- Modify: `experiments/01_policy_control/{README.md,CLAIM.md,EXPERIMENT.md}`
- Create: `experiments/01_policy_control/tests/test_integration.py`

**Interfaces:** Consumes complete implementation. Produces validated Draft declaration only, never an empirical claim.

- [ ] **Step 1: Write failing whole-stack smoke tests**

```python
@pytest.mark.parametrize("stack", ["P1", "P2", "P3", "P4", "P5", "P6"])
def test_each_stack_writes_replayable_zero_latency_smoke(stack, tmp_path):
    path = run_one_smoke(stack, tmp_path)
    validate_rollout(path)
    assert replay_rollout(path).valid
```

- [ ] **Step 2: Prove RED, then implement only integration wiring**

Run: `UV_CACHE_DIR=.cache/uv uv run pytest experiments/01_policy_control/tests/test_integration.py -q`

Expected: FAIL until the final runner-to-artifact wiring is complete. Add exact Draft constraints/cannot-claim text and source seam statement; do not write results.

- [ ] **Step 3: Execute full review gate and commit**

Run:

```text
UV_CACHE_DIR=.cache/uv uv run pytest -q
UV_CACHE_DIR=.cache/uv uv lock --check
UV_CACHE_DIR=.cache/uv uv run python -m reflect.safety check
UV_CACHE_DIR=.cache/uv uv run python scripts/audit_references.py --require-complete
git diff --check
```

Expected: every command exits zero. Have an independent reviewer inspect protocol ordering, scope, shared-contract compatibility, deterministic tests, and prohibited imports. Only after reviewed PASS, commit: `git add experiments/01_policy_control && git commit -m "test: validate experiment 01 draft integration"`.

### Task 8: Run the serial pilot and publish its immutable selection evidence

**Files:**
- Create: `experiments/01_policy_control/results/pilot/<revision>/...`
- Modify: `experiments/01_policy_control/RESULTS.md`

**Interfaces:** Consumes reviewed Task 7 implementation. Produces create-only pilot protocol/seed/artifact manifests, all rollout dirs, aggregate, bootstrap, decision, plots, and explicit pilot dispositions.

- [ ] **Step 1: Generate pilot manifest and validate bounded schedule**

Run: `UV_CACHE_DIR=.cache/uv uv run python -m experiments.01_policy_control.run --config experiments/01_policy_control/configs/base.yaml --phase pilot --dry-run --headless --shard-id P1:base:000`

Expected: emits a hash-bound manifest with eight seeds, the three ordered tuning cells, 24 core plus two probes final-four cells, and declared maxima 1,008 episodes/6,300 seconds/1,008 MiB per revision.

- [ ] **Step 2: Run only declared shards serially**

For each sorted manifest shard, run `make exp01 SHARD=<exact-id>`; wait for completion and validate its completion manifest before the next shard. Do not parallelize, alter configuration, or rerun a published destination. Stop immediately on P1 base/selected/final-four kill, resource cap breach, invalid artifact, or second revision exhaustion; record `INCONCLUSIVE`/`STOPPED`.

- [ ] **Step 3: Select and evaluate exactly once, then commit evidence**

Run analysis after all selected-vector shards validate. Verify PD, IK, P5-only smoothness feasibility/reuse/ties and one-shot final-four evaluation, then append measured pilot facts only to `RESULTS.md`. Run `UV_CACHE_DIR=.cache/uv uv run pytest -q` and artifact-size/hash/replay validation. Commit artifacts/report separately from implementation: `git add experiments/01_policy_control/results/pilot experiments/01_policy_control/RESULTS.md && git commit -m "data: record experiment 01 pilot"`.

### Task 9: Freeze reviewed pilot selection and generate confirmation manifest

**Files:**
- Create: `experiments/01_policy_control/configs/frozen.yaml`, `experiments/01_policy_control/results/confirmation/seed-manifest.json`

**Interfaces:** Consumes exact pilot evidence. Produces immutable frozen hash binding implementation commit/clean tree, P2/P3 evidence, MuJoCo artifact, all equations/configs/thresholds, exclusions/seeds/scores/ties, and confirmation RNG/count.

- [ ] **Step 1: Write failing freeze validator test**

```python
def test_frozen_config_binds_pilot_and_generates_32_new_valid_scenarios(tmp_path):
    frozen = freeze(pilot_manifest(), implementation_sha="a" * 40, output=tmp_path)
    assert frozen.confirmation_seed_count == 32
    assert frozen.hash == load_frozen(tmp_path / "frozen.yaml").hash
    assert frozen.confirmation_root not in pilot_manifest().rng_roots
```

- [ ] **Step 2: Prove RED, implement, then verify**

Run focused test; expected FAIL before freeze module is added to the runner/evaluator. Generate 64 ascending candidate seeds after freeze only, retain exactly 32 valid scenarios, and record all rejected candidates. Refuse confirmation if fewer than 32 or hash/version/clean-tree evidence differs. Run focused test plus `UV_CACHE_DIR=.cache/uv uv run pytest -q`, `uv lock --check`, safety/source audits, and `git diff --check`.

- [ ] **Step 3: Commit freeze-only evidence**

Commit: `git add experiments/01_policy_control/configs/frozen.yaml experiments/01_policy_control/results/confirmation/seed-manifest.json experiments/01_policy_control/tests/test_evaluate.py experiments/01_policy_control/run.py && git commit -m "data: freeze experiment 01 confirmation protocol"`.

### Task 10: Run confirmation, enforce promotion gate, and publish final report

**Files:**
- Create: `experiments/01_policy_control/results/confirmation/...`
- Modify: `experiments/01_policy_control/{RESULTS.md,INTERFACE_FINDINGS.md,CLAIM.md,EXPERIMENT.md}`

**Interfaces:** Consumes Task 9 only. Produces final validated `decision.json`, 5 SVGs, aggregates/bootstrap/artifact manifests, result classification, at-most-two configurations and stable wire deduplication.

- [ ] **Step 1: Run the immutable confirmation schedule serially**

Use only frozen-manifest shard IDs. Per surviving stack execute the 26 condition episodes for all 32 seeds plus the stationary control only for seeds 0–3; each confirmation shard has 26 or 27 episodes, at most 168.75 simulated seconds. Validate every existing artifact before skip and every new artifact before publication. Refuse the phase before start unless remaining artifact budget covers 5,016 MiB plus 256 MiB confirmation allowance and retained pilot maximum.

- [ ] **Step 2: Generate final decision/report from validated artifacts**

Run:

```text
UV_CACHE_DIR=.cache/uv uv run python -m experiments.01_policy_control.run --config experiments/01_policy_control/configs/frozen.yaml --phase analyze --headless --shard-id P1:selected:000
UV_CACHE_DIR=.cache/uv uv run pytest -q
UV_CACHE_DIR=.cache/uv uv lock --check
UV_CACHE_DIR=.cache/uv uv run python -m reflect.safety check
UV_CACHE_DIR=.cache/uv uv run python scripts/audit_references.py --require-complete
git diff --check
```

Expected: analysis only reads/revalidates artifacts; it writes five deterministic SVGs, exact bootstrap/decision manifests, and reports either `SUPPORTED`, `NOT_SUPPORTED`, or `INCONCLUSIVE`. It must apply all equality-inclusive thresholds, negative control invalidation, P1 STOP, adjusted interval ranking, and two-stack/wire deduplication.

- [ ] **Step 3: Independent final review and evidence/report commits**

Review all config/code/source/artifact hashes, replay every rollout, check no prohibited import or remote/physical execution, check artifact total <= 7,544 MiB, and verify reports make only the bounded stack-level claim and explicitly list rejected stacks. Commit generated evidence first, then report only:

```bash
git add experiments/01_policy_control/results/confirmation
git commit -m "data: record experiment 01 confirmation"
git add experiments/01_policy_control/RESULTS.md experiments/01_policy_control/INTERFACE_FINDINGS.md experiments/01_policy_control/CLAIM.md experiments/01_policy_control/EXPERIMENT.md
git commit -m "docs: report experiment 01 boundary decision"
```

## Self-review

- Spec coverage: Tasks 1–6 cover P3 gate, local arm, all P1–P6 semantics, exact virtual timing/fault/event rules, canonical artifacts/resume, metrics, pilot search, freeze, bootstrap, gates, and documentation. Tasks 8–10 cover the required reviewed live lifecycle, resource bounds, final report, and promotion. No P4 requirement is assigned to unbounded or concurrent measurement.
- Placeholder scan: this plan fixes exact file names, commands, constants, task interfaces, commits, and review gates; it contains no deferred implementation marker.
- Type consistency: `Scenario` originates in `arm.py`; `ActionChunk`/`ControlReference` originate in `representations.py`; timing only schedules them; `run_episode` returns the existing `RolloutRecord`; runner publication always uses `RolloutWriter`/`validate_rollout`; all later tasks use these exact names.

Plan complete and saved to `docs/superpowers/plans/2026-08-22-p4-policy-control-boundary.md`. Two execution options:

1. Subagent-Driven (recommended) - dispatch a fresh subagent per task, review between tasks, fast iteration.

2. Inline Execution - execute tasks in this session using executing-plans, batch execution with checkpoints.

Which approach?

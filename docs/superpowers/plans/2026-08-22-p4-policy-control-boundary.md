# P4 Policy-to-Controller Boundary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Build deterministic simulation-only Experiment 01, compare P1-P6, and publish a mechanical P4 decision.

**Architecture:** Experiment-local code owns arm, controller, timing, evidence and analysis. Existing reflect contracts are consumed unchanged. Freeze evidence/config APIs before parallel work; run all latency evidence serially from immutable manifests.

**Tech Stack:** Python 3.11.13, NumPy, PyYAML, PyArrow, pytest, P3-locked MuJoCo, reflect rollout/replay/clock/events/safety.

## Global Constraints

- Execution is blocked until P3 evidence passes: complete P2 audit, P3 report hash, locked MuJoCo version/artifact hash, physical_deployment_allowed=false, remote_enabled=false.
- No ROS, CUDA, VLA, Mink, MJPC, Menagerie, mjctrl, remote, physical execution, copied upstream source, or shared reflect implementation change.
- Arm: links .30/.25/.20m, limits [-2.70,2.70], damping .10, torque [-12,12], gravity zero, D=.002, 500Hz.
- Chunks retain existing string-valued ActionRepresentation; metadata stack_id; delivery validity and expiry delivery+ceil(2.5P).
- Evidence runs: headless, one shard, <=60 minutes, <=1MiB/rollout, create-only and exact validated resume. Raw results are ignored/local; commits contain only code/config/protocol/report/digest files.

## Files and dependencies

1 contracts.py/configs/base.yaml/test_contracts.py; 2 arm.py/test_arm.py; 3 representations.py/test_p1_p4.py; 4 same source/test_p5.py; 5 same source/test_p6.py; 6 timing.py/test_timing.py; 7 evaluate.py/test_episode_metrics.py; 8 evaluate.py/test_pilot.py; 9 evaluate.py/test_inference.py/test_plots.py; 10 run.py/test_manifest_cli.py/Makefile; 11 frozen.yaml/protocol/report digests.

Task 1 is serial. Tasks 2 and 3 can be parallel after 1. Tasks 4 and 5 can be parallel after 3. Tasks 6-11 are serial.

### Task 1: P3 gate and API freeze

**Files:** Create experiments/__init__.py, experiments/01_policy_control/__init__.py, contracts.py, configs/base.yaml, src/__init__.py, tests/test_contracts.py.

**Interfaces:** P3GateEvidence(p2_lock_hash:str,p3_report_hash:str,mujoco_version:str,mujoco_artifact_hash:str,physical_deployment_allowed:bool,remote_enabled:bool); ExperimentConfig; load_config(path:Path)->ExperimentConfig; require_p3_gate(evidence:P3GateEvidence)->None.

- [ ] **Step 1: RED**

    def test_gate_rejects_remote_or_unhashed_evidence():
        e=P3GateEvidence("a"*64,"b"*64,"3.3.0","c"*64,False,False)
        assert require_p3_gate(e) is None
        with pytest.raises(P4GateError): require_p3_gate(dataclasses.replace(e,remote_enabled=True))

Run: UV_CACHE_DIR=.cache/uv uv run pytest experiments/01_policy_control/tests/test_contracts.py -q. Expected: import error.

- [ ] **Step 2: GREEN**

    def require_p3_gate(e:P3GateEvidence)->None:
        if e.physical_deployment_allowed or e.remote_enabled: raise P4GateError("simulation-only")
        audit_references_complete(); verify_sha256(Path("RUN_REPORT.md"),e.p3_report_hash)
        verify_mujoco_lock(e.mujoco_version,e.mujoco_artifact_hash)

Strict YAML loader rejects missing/extra/nonfinite values; config contains all arm/condition/candidate/threshold/resource/seed constants. Run focused test, safety, source audit, diff check. Commit: git add experiments/__init__.py experiments/01_policy_control/__init__.py experiments/01_policy_control/contracts.py experiments/01_policy_control/configs/base.yaml experiments/01_policy_control/tests/test_contracts.py; git commit -m "feat: freeze P4 gate and contracts".

### Task 2: Kinematics, simulation, and scenarios

**Files:** Create src/arm.py, tests/test_arm.py.

**Interfaces:** forward_kinematics(q:NDArray)->NDArray; jacobian(q:NDArray)->NDArray; absolute_ik(target:NDArray,q0:NDArray,damping:float)->NDArray; Scenario; generate_scenario(seed:int,cfg:ExperimentConfig)->Scenario; bounded_pd(...)->tuple[NDArray,NDArray,ClampReport].

- [ ] **Step 1: RED**

    def test_fixed_ik_and_geometry():
        q=np.array([.35,-.70,.35])
        np.testing.assert_allclose(jacobian(q),finite_difference_fk(q),atol=1e-6)
        assert generate_scenario(7,CFG)==generate_scenario(7,CFG)

Run focused pytest; expected import error.

- [ ] **Step 2: GREEN**

    def absolute_ik(target,q0,damping):
        q=q0.copy()
        for _ in range(12): q=np.clip(q+clip_norm(pinv(jacobian(q),damping)@(target-forward_kinematics(q))+.05*nullspace(jacobian(q),damping)@(POSTURE-q),.10),-2.55,2.55)
        return q

Implement inline MJCF, PCG64 scenario streams, 32-proposal rejection, slew/PD/torque clamps. Run focus and safety tests. Commit exact source/test files.

### Task 3: P1-P4 representation unit

**Files:** Create src/representations.py, tests/test_p1_p4.py.

**Interfaces:** CommandStack; PolicyInput; ExecutorState; emit_chunk(stack:CommandStack,input:PolicyInput,cfg:ExperimentConfig)->ActionChunk; reference_for_tick(...)->tuple[ControlReference,ExecutorState,ClampReport].

- [ ] **Step 1: RED/GREEN**

    def test_p2_wire_shape_and_immutable_values():
        c=emit_chunk(CommandStack.P2,fixture_input(.01),CFG)
        assert c.representation.value=="JOINT_POSITION" and c.actions.shape==(81,3)
        assert not c.actions.flags.writeable

Implement P1/P2 absolute IK, P3/P4 differential IK and exact interpolation. Run focus plus tests/test_types.py. Commit exact source/test files.

### Task 4: P5 MPC unit

**Files:** Modify src/representations.py; create tests/test_p5.py.

**Interfaces:** mpc_reference(target:NDArray,q:NDArray,state:ExecutorState,cfg:ExperimentConfig)->tuple[NDArray,ExecutorState].

- [ ] **Step 1: RED/GREEN**

    def test_p5_transition_order():
        s=ExecutorState.p5_initial(); _,s=mpc_reference(TARGET,Q,s,CFG)
        assert np.any(s.qdot_previous)
        assert np.array_equal(s.after_expiry().qdot_previous,np.zeros(3))

Implement 79 ordered candidates, normalized 10-step cost, tie first, 50Hz update, accept/reject/replacement preservation, expiry reset, later acceptance, coincident delivery-before-planner. Run focus; commit exact files.

### Task 5: P6 residual unit

**Files:** Modify src/representations.py; create tests/test_p6.py.

- [ ] **Step 1: RED/GREEN**

    def test_residual_uses_initial_nominal_and_bounds():
        assert np.max(np.abs(emit_chunk(CommandStack.P6,fixture_input(.1),CFG).actions))<=.25

Implement minimum-jerk initial nominal plus stale-target residual, no live target. Run focus; commit exact files.

### Task 6: Timing and lifecycle unit

**Files:** Create src/timing.py, tests/test_timing.py.

**Interfaces:** TimingCondition; PolicyRequest; schedule_response; deliver_due; last_request_tick(end_tick:int,latency_tick:int,extra_tick:int,period_tick:int)->int.

- [ ] **Step 1: RED/GREEN**

    def test_cutoff_and_value_immutability():
        assert last_request_tick(3125,350,52,25)==2500
        assert issued_hashes_after_later_delivery()==issued_hashes_before_later_delivery()

Implement priority queue, 0/100/300/700 latency, faults, event order, valid-only replacement, expired clear/direct acceptance, safe-hold/no-reference, one policy/telemetry observation, and empty terminal queue. Run focus plus clock/events. Commit exact files.

### Task 7: Episode and metrics unit

**Files:** Create src/evaluate.py, tests/test_episode_metrics.py.

**Interfaces:** run_episode(...)->RolloutRecord; recovery_time; nearest_rank_p95; aggregate_seed_metrics.

- [ ] **Step 1: RED/GREEN**

    def test_censor_percentile_and_control():
        assert recovery_time([.03]*1000)==2.0
        assert nearest_rank_p95([1,2,3,4,5])==5
        assert negative_control_valid([.02]*2375)

Implement 500Hz metrics/100Hz telemetry, dwell/censor, missing invalidation, clamp/saturation/jerk/discontinuity aggregation. Run focus/replay. Commit exact files.

### Task 8: Staged pilot selection unit

**Files:** Modify evaluate.py; create tests/test_pilot.py.

**Interfaces:** PilotManifest; iter_base; iter_pd; iter_ik; iter_p5; iter_final_four; select_pilot.

- [ ] **Step 1: RED/GREEN**

    def test_stages_are_hashed_and_final_four_once():
        assert [x.stage for x in iter_staged_pilot(FIXTURE)]==["base","pd","ik","p5","final_four"]

Create-only hashed manifests run base qualification then PD then selected-PD IK then selected-shared P5 smoothness then one-shot final four. Enforce 164 non-P5/188 P5/max 1008. Driver: python -m experiments.01_policy_control.run --phase pilot --stage base --manifest PATH --headless --shard-id ID. Run only next stage after prior manifest validation. Commit code/tests only.

### Task 9: Inference, gates, plots

**Files:** Modify evaluate.py; create tests/test_inference.py, tests/test_plots.py.

- [ ] **Step 1: RED/GREEN**

    def test_equality_and_wire_dedup():
        d=apply_gate(FIXTURE_EQUAL,FROZEN)
        assert d.promoted_stacks==("P2","P1")
        assert d.promoted_wire_representations==("JOINT_POSITION",)

Implement PCG64 SHA256 bootstrap seed, 10000 resamples, Bonferroni 99%, negative/missing rules, classifications, five deterministic SVGs. Run focused tests; commit files.

### Task 10: Manifests, publication, CLI

**Files:** Create run.py, tests/test_manifest_cli.py; modify Makefile.

- [ ] **Step 1: RED/GREEN**

    def test_exact_resume_and_replay():
        assert publish_or_validate_skip(FIXTURE,TMP)=="published"
        assert publish_or_validate_skip(FIXTURE,TMP)=="validated-and-skipped"

Implement sorted manifest iterator, RolloutWriter/validate_rollout/replay_rollout; ReplayResult fields are events, observations, frames, final_state (not valid). Commands: make exp01 SHARD=P1:base:000; python -m experiments.01_policy_control.run --phase confirmation --frozen-config configs/frozen.yaml --seed-manifest PATH --headless --shard-id ID; python -m experiments.01_policy_control.run --phase analyze --frozen-config configs/frozen.yaml --headless --shard-id ID. Run focus/full/lock/safety/audit/diff; commit exact files.

### Task 11: Reviewed freeze, confirmation, and report

**Files:** Create configs/frozen.yaml and small protocol/seed/decision/report digest artifacts.

- [ ] **Step 1:** Only after full tests and independent Draft review PASS, freeze clean implementation SHA, P2/P3 hashes, equations/candidates/pilot hashes/thresholds; generate unseen 32-scenario manifest after freeze. No source edit after pilot.
- [ ] **Step 2:** Serially run 26/27 episode confirmation shards; analyze artifacts only; enforce 5016 rollouts, 31350 seconds, 5272MiB confirmation, 7544MiB phase, P1 STOP and two-stack promotion. Commit only frozen config/protocol/report/digests, never local raw results.

## Self-review

Tasks cover P3 gate, six stacks, timing, safe hold, artifacts, metrics, staged pilot, inference, CLI, freeze and report. Before execution run rg -n -i 'TODO|TBD|implement later|fill in details' this plan and git diff --check; declared public interfaces are used consistently.

Plan complete and saved to docs/superpowers/plans/2026-08-22-p4-policy-control-boundary.md. Execute via subagent-driven development or inline executing-plans.

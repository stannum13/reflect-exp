# Reflect-Lite Systems Research Program
## Atomic claim searches, public-source integration, and Unitree R1 transfer

**Use this file as the root research specification and autonomous Codex brief for one repository.**

- **Primary development machine:** Apple MacBook Pro, M2 Max
- **Primary local substrate:** native MuJoCo + CPU-friendly Python
- **Optional remote substrate:** Ubuntu x86-64 + NVIDIA GPU
- **Target embodiment:** Unitree R1
- **Architectural inspiration:** Flexion Reflect v0/v1 and its real-to-sim-to-real collaboration with Niantic Spatial and NVIDIA
- **Verified public-source inventory date:** 2026-08-22
- **Default safety mode:** simulation only; physical deployment disabled

---

# 0. Codex operating brief

You are Codex operating autonomously in the repository governed by this file. Read the entire specification before modifying source.

## 0.1 Immediate objective

Create the smallest working repository in which the atomic experiments can be run independently and later composed. Reuse approved public implementations through the source registry rather than recreating mature code, but do not turn upstream repositories into hidden architectural commitments.

## 0.2 Workspace behavior

1. Inspect the current directory and Git status.
2. If it is an existing non-empty repository, preserve all user work and adapt this specification to its layout.
3. If it is an empty directory, initialize one repository named `reflect-architecture`.
4. Never create one repository per experiment.
5. Create the worktree/branch layout from Section 5 only when it does not conflict with existing branches or worktrees.
6. Never run destructive Git commands or discard dirty changes.
7. Do not push unless `ALLOW_PUSH=1`.

## 0.3 First autonomous pass

Complete these deliverables in order:

```text
P0  safety defaults and .env.example
P1  root package, rollout schema, and test harness
P2  public-source registry and metadata-only audit
P3  Experiment 00 source/compatibility report
P4  runnable Experiment 01 synthetic-policy baseline
P5  runnable Experiment 02 broker invariants
P6  pure-Python Experiments 04 and 05 baselines
P7  small Experiment 06 dataset/ranking baseline
P8  Experiment 03 recovery integration
P9  Unitree R1 source/mapping audit without deployment
P10 reports, exact commands, and next-run instructions
```

A blocked GPU or Unitree phase must not block local-independent work.

## 0.4 Autonomy policy

Do not ask routine implementation questions. Inspect source, make conservative reversible assumptions, record them in `docs/ASSUMPTIONS.md`, and continue. Stop a particular operation only for missing authorization, destructive risk, credentials, physical-robot communication, or an irreducibly ambiguous safety decision.

When a dependency fails:

1. preserve the exact command and error;
2. try at most one materially different resolution;
3. classify it as local, remote, reference-only, or deferred;
4. continue with independent work.

## 0.5 Scope control

Do not implement a generalized platform when a 100-line experiment can answer the claim. Do not add a VLA, world model, ROS 2, Isaac Sim, or a database merely because one may eventually be useful. Each addition must be justified by the current experiment's `CLAIM.md` and pass its gate.

## 0.6 Completion behavior

Before ending any autonomous pass:

- run relevant tests;
- inspect the diff;
- verify no secrets or large binary artifacts were added;
- verify physical deployment remains disabled;
- write `RUN_REPORT.md`;
- list exact reproducible commands;
- identify one highest-value next bounded action;
- make atomic commits when safe and configured.

---

# 1. Program intent

Build a small experimental program that can answer where the interfaces in a Reflect-style physical-AI hierarchy should live:

```text
mission / language reasoning                         event-driven, ~0.1–2 Hz
            ↓ SemanticGoal / SkillSpec
persistent semantic world state                     event-driven, ~1–10 Hz
            ↓ grounded entities + preconditions
skill router: general policy / specialist skill     ~2–30 Hz
            ↓ ActionChunk / ControlReference
reactive executor / trajectory layer                ~20–200 Hz
            ↓ q*, dq*, x*, constraints
MPC / IK / operational-space control                ~50–500 Hz
            ↓ controller reference
PID / impedance / whole-body controller             ~500–5000 Hz
            ↓
robot or simulator
```

The objective is **not** to reproduce Flexion Reflect end to end.

The objective is to run bounded experiments that establish:

1. what a slow learned policy should emit;
2. how asynchronous action chunks should be reconciled with ongoing execution;
3. which failures should be handled locally versus semantically;
4. what state should persist between agent and policy calls;
5. how geometric, topological, semantic, and belief layers of a digital twin should be separated;
6. whether learned physical prediction improves action selection beyond world-model-free baselines;
7. whether the resulting contracts survive transfer to a Unitree R1.

A negative result is valid. The program succeeds by producing defensible architectural decisions, not by forcing every component to appear useful.

---

# 2. Research questions and bounded claims

| ID | Question | Bounded claim sought |
|---|---|---|
| Q1 | What should a slow policy emit? | On a fixed toy task, representation X provides a better tracking/reactivity/latency trade-off than representations Y and Z. |
| Q2 | How should action chunks be executed? | Under a specified latency distribution, protocol X improves perturbation recovery without unacceptable discontinuity. |
| Q3 | What wakes each layer? | Observable failure signatures can be mapped to continue, refresh, retrigger, escalate, or abort with measurable benefit. |
| Q4 | What should persist? | A specified memory composition reduces stale-state and repeated-observation errors on a controlled task suite. |
| Q5 | How should environment knowledge be encoded? | Separating geometry, topology, semantics, and live belief improves valid planning under specified world mutations. |
| Q6 | Does a learned world model help? | On a candidate-ranking benchmark, model X reduces held-out selection regret relative to heuristic and reactive baselines. |
| Q7 | Are specialist skills useful? | On a specified contact regime, dispatching to a specialist skill improves reliability enough to justify heterogeneous policies. |
| Q8 | Do interfaces transfer to R1? | Previously selected contracts remain operational on the R1 simulation stack without redesigning every layer. |
| Q9 | Does the hierarchy compose? | The integrated system improves long-horizon recovery over simpler ablations on one fixed mission. |
| Q10 | Does site reconstruction help? | A reconstructed deployment scene reduces a measured visual/deployment gap relative to generic simulation on one task. |

Do not broaden any result into a general claim about robotics, VLAs, world models, or humanoids.

---

# 3. Non-goals

This program is not initially solving:

- general humanoid intelligence;
- general dexterous manipulation;
- building-scale SLAM;
- end-to-end language-to-torque control;
- foundation-model pretraining;
- a universal robotics middleware;
- a production-grade ROS 2 stack;
- general world modelling;
- photorealistic real-to-sim reconstruction as a prerequisite;
- whole-system formal verification;
- autonomous physical deployment;
- benchmarking every available VLA or policy.

Do not let an attractive public repository turn one bounded experiment into a platform rewrite.

---

# 4. Compute and safety envelope

## 4.1 Local M2 Max

Use the Mac for:

- Git and Codex;
- native MuJoCo;
- small CPU experiments;
- Apple MPS only when an existing package supports it cleanly;
- policy/control interface tests;
- memory and semantic-twin experiments;
- small learned dynamics models;
- analysis, plots, replay, and reports;
- remote job orchestration.

Do **not** spend time installing:

- CUDA;
- NVIDIA drivers;
- Isaac Sim or Isaac Lab locally;
- a Linux-only GPU stack on macOS;
- a heavyweight ROS 2 deployment merely to run a toy experiment.

## 4.2 Optional remote GPU worker

Use a remote Ubuntu x86-64 NVIDIA machine only when an experiment genuinely requires:

- Unitree MJLab training;
- large-scale parallel RL;
- VLA or foundation world-model inference/training;
- Isaac Sim/Isaac Lab;
- CUDA-only planners such as cuRobo or Hydrax/MJX configurations.

Detect remote availability from explicit environment variables. Never probe arbitrary SSH hosts.

## 4.3 Physical robot

Set:

```text
PHYSICAL_DEPLOYMENT_ALLOWED=false
```

No autonomous Codex run may:

- connect to a physical R1;
- publish Unitree DDS motor messages;
- execute SDK2 control on a non-loopback interface;
- enable low-level motor mode;
- infer that a discovered network interface is safe.

Physical deployment requires a separate human-reviewed protocol.

## 4.4 Current R1 mapping warning

Treat the open Unitree MJLab issue reporting an R1 simulator-to-motor-slot mismatch as an unresolved safety concern until the current checked-out source is audited:

- <https://github.com/unitreerobotics/unitree_rl_mjlab/issues/52>

The issue reports 24 simulated actuators versus 27 low-level motor slots, with gaps at slots 14, 20, and 21. Do not assume either the report or current upstream is correct; derive and test the mapping from source. Physical output stays disabled regardless.

## 4.5 Networked inference warning

Never expose an upstream policy server directly to an untrusted network. In particular:

- bind experimental inference to loopback or a private authenticated tunnel;
- pin and inspect the exact LeRobot/OpenPI revision;
- reject unsafe or opaque serialization before production use;
- validate dimensions, timestamps, validity windows, and finite values on both sides;
- keep safety-critical control local even if inference is remote.

---

# 5. One repository, multiple worktrees

## 5.1 Branch topology

```text
main
│
├── exp/00-source-audit
├── exp/01-policy-control
├── exp/02-action-chunks
├── exp/03-recovery
├── exp/04-memory
├── exp/05-semantic-twin
├── exp/06-world-model
├── exp/07-specialist-skill
├── exp/08-unitree-r1
├── exp/10-r2s2r
└── integration/mini-reflect
```

## 5.2 Suggested filesystem

```text
~/work/
├── reflect-architecture/          # main checkout
├── wt-source-audit/
├── wt-policy-control/
├── wt-action-chunks/
├── wt-recovery/
├── wt-memory/
├── wt-semantic-twin/
├── wt-world-model/
├── wt-specialist-skill/
├── wt-unitree-r1/
├── wt-r2s2r/
└── wt-integration/
```

## 5.3 Setup commands

```bash
git clone <THIS_REPOSITORY_URL> reflect-architecture
cd reflect-architecture

git worktree add ../wt-source-audit      -b exp/00-source-audit
git worktree add ../wt-policy-control    -b exp/01-policy-control
git worktree add ../wt-action-chunks     -b exp/02-action-chunks
git worktree add ../wt-recovery          -b exp/03-recovery
git worktree add ../wt-memory            -b exp/04-memory
git worktree add ../wt-semantic-twin     -b exp/05-semantic-twin
git worktree add ../wt-world-model       -b exp/06-world-model
git worktree add ../wt-specialist-skill  -b exp/07-specialist-skill
git worktree add ../wt-unitree-r1        -b exp/08-unitree-r1
git worktree add ../wt-r2s2r             -b exp/10-r2s2r
git worktree add ../wt-integration       -b integration/mini-reflect
```

Each Codex session works in exactly one worktree. It must not modify sibling worktrees or merge itself into `main`.

---

# 6. Repository layout

```text
reflect-architecture/
├── RESEARCH_PROGRAM.md
├── pyproject.toml
├── Makefile
├── .env.example
├── .gitignore
│
├── reflect/
│   ├── __init__.py
│   ├── types.py
│   ├── clock.py
│   ├── events.py
│   ├── validation.py
│   ├── metrics.py
│   └── rollout.py
│
├── experiments/
│   ├── 00_source_audit/
│   ├── 01_policy_control/
│   ├── 02_action_chunks/
│   ├── 03_recovery/
│   ├── 04_memory/
│   ├── 05_semantic_twin/
│   ├── 06_world_model/
│   ├── 07_specialist_skill/
│   ├── 08_unitree_r1/
│   ├── 09_mini_reflect/
│   └── 10_r2s2r/
│
├── references/
│   ├── repos.yaml
│   ├── repos.lock.yaml
│   ├── papers.md
│   ├── licenses.md
│   └── patches/
│
├── external/                       # gitignored sparse reference clones
├── scripts/
│   ├── fetch_reference.py
│   ├── audit_references.py
│   ├── create_worktrees.sh
│   ├── collect_results.py
│   └── remote/
│
├── assets/
├── results/
├── docs/
└── tests/
```

Only stable, experimentally validated contracts belong in `reflect/`. Simulator environments, policy implementations, memory benchmarks, and planners remain experiment-local until evidence justifies promotion.

---

# 7. Public-source integration policy

## 7.1 Reuse modes

Every public project must be assigned exactly one mode:

| Mode | Meaning |
|---|---|
| `DIRECT_DEPENDENCY` | Installed or linked at runtime because its implementation is integral to the experiment. |
| `ADAPTER_DEPENDENCY` | Used behind a thin project-local adapter; upstream API may change. |
| `SPARSE_REFERENCE` | Only selected directories/files are fetched for study or small attributed adaptation. |
| `REMOTE_ONLY` | CUDA/Linux-heavy; used only on the explicit remote worker. |
| `PAPER_AND_CODE_REFERENCE` | Architecture/evaluation reference; not installed in the core path. |
| `DEFERRED` | Relevant later, but intentionally excluded until an earlier gate passes. |

Do not clone every repository during bootstrap.

## 7.2 Pinning and provenance

For every fetched repository record:

- URL;
- default branch at discovery;
- resolved commit SHA;
- retrieval date;
- license/SPDX identifier when discoverable;
- selected paths;
- experiments using it;
- local modifications or copied snippets;
- upstream paper/project link;
- compatibility status on macOS and remote Linux.

`references/repos.lock.yaml` must contain resolved SHAs. Experiments must never depend silently on floating `main`.

## 7.3 Licensing

Before copying or modifying code:

1. inspect the repository-level license;
2. inspect per-model/per-asset licenses;
3. preserve notices and attribution;
4. avoid copying copyleft code into the core package without explicit review;
5. prefer adapters or separate processes when license boundaries are unclear;
6. record every adapted source file in `references/patches/ATTRIBUTION.md`.

A GitHub URL is not a license grant.

## 7.4 Fetch strategy

- Use shallow sparse checkouts for reference repositories.
- Use package installation only for direct dependencies.
- Use submodules only when a fixed upstream runtime dependency is unavoidable.
- Keep `external/` gitignored.
- Do not fetch model checkpoints larger than 2 GB unless `ALLOW_LARGE_MODELS=1`.
- Do not fetch CUDA-only repositories on the Mac unless only source inspection is needed.

## 7.5 Required fetch tool

Implement:

```bash
python scripts/fetch_reference.py --name lerobot
python scripts/fetch_reference.py --experiment 02_action_chunks
python scripts/fetch_reference.py --all-metadata-only
python scripts/audit_references.py
```

The fetch tool must:

- read `references/repos.yaml`;
- resolve a revision to a SHA;
- sparse-clone only selected paths when possible;
- refuse missing/unknown licenses unless explicitly marked `REFERENCE_ONLY`;
- write `repos.lock.yaml`;
- never overwrite a dirty existing clone;
- support `--metadata-only`;
- print expected disk use when known.

---

# 8. Initial public repository registry

Codex should create `references/repos.yaml` from the following registry, verify every path against the current pinned revision, and update paths rather than assuming this document remains current forever.

```yaml
verified_at: 2026-08-22
large_model_downloads_default: false
physical_deployment_default: false

repositories:
  # ------------------------------------------------------------------
  # PRIMARY LOCAL PHYSICS / CONTROL
  # ------------------------------------------------------------------
  - name: mujoco
    url: https://github.com/google-deepmind/mujoco
    mode: DIRECT_DEPENDENCY
    experiments: [01_policy_control, 02_action_chunks, 03_recovery, 06_world_model]
    selected_paths: [python, model, sample, test]
    use: Native macOS physics and exact rollout ground truth.
    caveat: Prefer the published Python package; source clone is mainly for examples and model semantics.

  - name: mujoco_mpc
    url: https://github.com/google-deepmind/mujoco_mpc
    mode: SPARSE_REFERENCE
    experiments: [01_policy_control, 06_world_model]
    selected_paths:
      - python/mujoco_mpc
      - python/mujoco_mpc/demos/predictive_sampling
      - mjpc/planners
      - mjpc/tasks
    use: Predictive Sampling, iLQG, CEM/gradient planner structure, spline controls, cost/task interfaces.
    caveat: Research prototype; do not present as a production safety layer.

  - name: mujoco_menagerie
    url: https://github.com/google-deepmind/mujoco_menagerie
    mode: SPARSE_REFERENCE
    experiments: [01_policy_control, 06_world_model]
    selected_paths:
      - panda
      - franka_emika_panda
      - universal_robots_ur5e
      - README.md
    use: Reusable MuJoCo robot assets where per-model licenses permit.
    caveat: Verify exact directory names and each model's license before use.

  - name: mink
    url: https://github.com/kevinzakka/mink
    mode: ADAPTER_DEPENDENCY
    experiments: [01_policy_control]
    selected_paths: [mink, examples, tests]
    use: Differential IK, task stacks, velocity limits, and collision-aware control on MuJoCo.
    caveat: Use behind a thin adapter; do not make every experiment depend on it.

  - name: mjctrl
    url: https://github.com/kevinzakka/mjctrl
    mode: SPARSE_REFERENCE
    experiments: [01_policy_control]
    selected_paths: [*.py, README.md]
    use: Compact pedagogical implementations of differential IK, null-space, and operational-space control.
    caveat: Adapt small algorithms with attribution; retain project-local tests.

  - name: hydrax
    url: https://github.com/vincekurtz/hydrax
    mode: REMOTE_ONLY
    experiments: [06_world_model]
    selected_paths: [hydrax, examples, tests]
    use: JAX/MJX Predictive Sampling, MPPI, CEM, MTP, risk-sensitive and randomized sampling MPC.
    caveat: CUDA/JAX-heavy; optional direct-physics-planning comparison only after the ranking gate.

  - name: curobo
    url: https://github.com/NVlabs/curobo
    mode: REMOTE_ONLY
    experiments: [01_policy_control, 08_unitree_r1]
    selected_paths: [src/curobo, examples, docs]
    use: CUDA motion generation, IK, collision checking, and trajectory optimization reference.
    caveat: Do not confuse high-rate reactive reaching with full contact-dynamics manipulation planning.

  - name: moveit2
    url: https://github.com/moveit/moveit2
    mode: PAPER_AND_CODE_REFERENCE
    experiments: [01_policy_control, 08_unitree_r1]
    selected_paths: [moveit_ros/moveit_servo, moveit_core, moveit_planners]
    use: Production-shaped motion planning and streaming servo boundaries.
    caveat: Do not add ROS 2 to the toy experiments solely to reproduce this architecture.

  - name: ros2_control
    url: https://github.com/ros-controls/ros2_control
    mode: PAPER_AND_CODE_REFERENCE
    experiments: [01_policy_control, 08_unitree_r1]
    selected_paths: [controller_interface, hardware_interface, controller_manager]
    use: Multi-rate controller lifecycle and chained-controller architecture reference.

  - name: ros2_controllers
    url: https://github.com/ros-controls/ros2_controllers
    mode: PAPER_AND_CODE_REFERENCE
    experiments: [01_policy_control, 08_unitree_r1]
    selected_paths: [pid_controller, joint_trajectory_controller, admittance_controller]
    use: Reference semantics for PID, trajectories, and compliant control.

  - name: mujoco_ros2_control
    url: https://github.com/moveit/mujoco_ros2_control
    mode: DEFERRED
    experiments: [08_unitree_r1]
    selected_paths: [mujoco_ros2_control, README.md]
    use: Later ROS 2/MuJoCo bridge reference if production integration requires it.

  # ------------------------------------------------------------------
  # ACTION CHUNKS, VLAs, IMITATION POLICIES
  # ------------------------------------------------------------------
  - name: act
    url: https://github.com/tonyzhaozh/act
    mode: SPARSE_REFERENCE
    experiments: [02_action_chunks, 07_specialist_skill]
    selected_paths:
      - policy.py
      - imitate_episodes.py
      - sim_env.py
      - detr
    use: Action-chunk representation, temporal ensembling, and compact imitation baseline.
    caveat: Do not import the full ALOHA stack into the toy executor.

  - name: lerobot
    url: https://github.com/huggingface/lerobot
    mode: SPARSE_REFERENCE
    experiments: [02_action_chunks, 07_specialist_skill, 08_unitree_r1]
    selected_paths:
      - src/lerobot/async_inference
      - src/lerobot/policies/rtc
      - docs/source/async.mdx
      - docs/source/rtc.mdx
      - docs/source/inference.mdx
      - src/lerobot/policies/act
      - src/lerobot/policies/smolvla
    use: Async policy server/client, action queue, latency tracking, RTC, ACT, and SmolVLA adapters.
    caveat: Pin a reviewed commit; do not expose the upstream server to untrusted networks or inherit serialization blindly.

  - name: openpi
    url: https://github.com/Physical-Intelligence/openpi
    mode: SPARSE_REFERENCE
    experiments: [02_action_chunks, 08_unitree_r1]
    selected_paths:
      - packages/openpi-client/src/openpi_client/action_chunk_broker.py
      - packages/openpi-client
      - scripts/serve_policy.py
      - src/openpi/policies
      - examples
    use: Small action-chunk broker, policy client/server boundary, and model-serving interface reference.
    caveat: Full models are remote-GPU heavy; initially reuse only the client-side contracts.

  - name: diffusion_policy
    url: https://github.com/real-stanford/diffusion_policy
    mode: SPARSE_REFERENCE
    experiments: [06_world_model, 07_specialist_skill]
    selected_paths:
      - diffusion_policy/env/pusht
      - diffusion_policy/dataset/pusht_image_dataset.py
      - diffusion_policy/env_runner/pusht_image_runner.py
      - diffusion_policy/config/task/pusht_image.yaml
    use: Push-T environment/data organization and a strong receding-horizon policy comparison.
    caveat: Reuse task/evaluation ideas before attempting the full training stack.

  # ------------------------------------------------------------------
  # RECOVERY / ORCHESTRATION
  # ------------------------------------------------------------------
  - name: behaviortree_cpp
    url: https://github.com/BehaviorTree/BehaviorTree.CPP
    mode: SPARSE_REFERENCE
    experiments: [03_recovery, 09_mini_reflect]
    selected_paths: [include/behaviortree_cpp, examples, tests]
    use: Interruptible asynchronous actions, reactive fallback, typed ports, and logging semantics.
    caveat: Use as a semantic reference first; a Python state machine is sufficient for the atomic experiment.

  - name: navigation2
    url: https://github.com/ros-navigation/navigation2
    mode: SPARSE_REFERENCE
    experiments: [03_recovery, 09_mini_reflect]
    selected_paths: [nav2_bt_navigator, nav2_behavior_tree, nav2_behaviors]
    use: Context-specific recovery, retry, replanning, and behavior-tree orchestration patterns.
    caveat: Navigation recovery patterns are analogies, not proof for manipulation.

  # ------------------------------------------------------------------
  # MEMORY / SCENE GRAPHS / DIGITAL TWINS
  # ------------------------------------------------------------------
  - name: spark_dsg
    url: https://github.com/MIT-SPARK/Spark-DSG
    mode: DEFERRED
    experiments: [04_memory, 05_semantic_twin]
    selected_paths: [spark_dsg, python, tests]
    use: Dynamic scene-graph data structure and Python bindings after the minimal schema is validated.
    caveat: Do not make the pure-Python memory benchmark depend on this initially.

  - name: hydra_scene_graph
    url: https://github.com/MIT-SPARK/Hydra
    mode: PAPER_AND_CODE_REFERENCE
    experiments: [04_memory, 05_semantic_twin, 10_r2s2r]
    selected_paths: [src, include, config, python]
    use: Incremental hierarchical 3D scene graphs spanning geometry, places, rooms, and objects.
    caveat: Heavy ROS/Ubuntu integration; reference architecture before installation.

  - name: kimera
    url: https://github.com/MIT-SPARK/Kimera
    mode: PAPER_AND_CODE_REFERENCE
    experiments: [05_semantic_twin, 10_r2s2r]
    selected_paths: [README.md]
    use: Index into the metric-semantic mapping lineage underlying scene-graph systems.

  - name: conceptgraphs
    url: https://github.com/concept-graphs/concept-graphs
    mode: DEFERRED
    experiments: [04_memory, 05_semantic_twin, 10_r2s2r]
    selected_paths:
      - conceptgraph/slam
      - conceptgraph/scenegraph
      - scripts
      - README.md
    use: Open-vocabulary object-centric 3D graphs and language descriptors.
    caveat: CUDA and perception dependencies are substantial; use only after the hand-authored graph contract works.

  - name: rerun
    url: https://github.com/rerun-io/rerun
    mode: DEFERRED
    experiments: [01_policy_control, 02_action_chunks, 03_recovery, 04_memory, 05_semantic_twin]
    selected_paths: [rerun_py, examples/python]
    use: Optional time-synchronized multimodal logging and visual replay.
    caveat: Optional telemetry remains disabled; GitHub NOASSERTION blocks importing, installing, or using the adapter until separately approved.

  - name: openusd
    url: https://github.com/PixarAnimationStudios/OpenUSD
    mode: DEFERRED
    experiments: [05_semantic_twin, 10_r2s2r]
    selected_paths: [pxr/usd, extras, docs]
    use: Durable scene hierarchy, typed geometry/state, and relationships for the geometric twin.
    caveat: USD is not the live robot belief state; optional export/import must not block the benchmark.

  - name: ifcopenshell
    url: https://github.com/IfcOpenShell/IfcOpenShell
    mode: DEFERRED
    experiments: [05_semantic_twin, 10_r2s2r]
    selected_paths: [src/ifcopenshell-python, examples, docs]
    use: Optional IFC/BIM import into the durable building layer.
    caveat: Review LGPL and component licenses; keep it behind an adapter or separate process when appropriate.

  - name: ifcopenshell_test_files
    url: https://github.com/IfcOpenShell/files
    mode: SPARSE_REFERENCE
    experiments: [05_semantic_twin]
    selected_paths: [ifc]
    use: Public miniature IFC fixtures when licensing and size permit.

  # ------------------------------------------------------------------
  # WORLD MODELS / PREDICTIVE CONTROL
  # ------------------------------------------------------------------
  - name: tdmpc2
    url: https://github.com/nicklashansen/tdmpc2
    mode: PAPER_AND_CODE_REFERENCE
    experiments: [06_world_model]
    selected_paths: [tdmpc2, cfgs, datasets]
    use: Control-centric latent dynamics, value/reward models, and online trajectory optimization reference.
    caveat: Benchmark-oriented and GPU-heavy; do not make it the first implementation.

  - name: dino_wm
    url: https://github.com/gaoyuezhou/dino_wm
    mode: SPARSE_REFERENCE
    experiments: [06_world_model]
    selected_paths: [models, planning, env, conf, plan.py]
    use: Closest public structure for frozen visual features plus action-conditioned latent prediction and CEM planning.
    caveat: Legacy environment dependencies; adapt planning/evaluation ideas rather than reproducing everything first.

  - name: vjepa2
    url: https://github.com/facebookresearch/vjepa2
    mode: REMOTE_ONLY
    experiments: [06_world_model]
    selected_paths: [app/vjepa_droid, configs, src, notebooks]
    use: Foundation-pretrained visual latent and action-conditioned planning reference.
    caveat: GPU-oriented and not the minimal baseline; macOS dependency friction is expected.

  - name: lawam
    url: https://github.com/RLinf/LaWAM
    mode: REMOTE_ONLY
    experiments: [06_world_model, 09_mini_reflect]
    selected_paths: [latent_action_model, starVLA, deployment, examples/LIBERO, examples/Robotwin]
    use: Latent subgoal conditioning and amortized action generation rather than brute-force online search.
    caveat: Large training stack; architectural comparison, not overnight dependency.

  - name: libero
    url: https://github.com/Lifelong-Robot-Learning/LIBERO
    mode: DEFERRED
    experiments: [07_specialist_skill, 09_mini_reflect]
    selected_paths: [libero, benchmark_scripts]
    use: Later manipulation generalization benchmark adapter.
    caveat: Older dependencies and broad scope; do not use before toy claims are resolved.

  # ------------------------------------------------------------------
  # UNITREE R1 AND UNITREE-SPECIFIC LEARNED SYSTEMS
  # ------------------------------------------------------------------
  - name: unitree_rl_mjlab
    url: https://github.com/unitreerobotics/unitree_rl_mjlab
    mode: REMOTE_ONLY
    experiments: [07_specialist_skill, 08_unitree_r1]
    selected_paths: [src, scripts, simulate, deploy, doc, README.md]
    use: Primary official R1 MuJoCo/RL/Train-Play-Sim2Real substrate.
    caveat: Pin SHA, reproduce official baseline unchanged, and audit issue #52 mapping before any deployment path.

  - name: unitree_mujoco
    url: https://github.com/unitreerobotics/unitree_mujoco
    mode: PAPER_AND_CODE_REFERENCE
    experiments: [08_unitree_r1]
    selected_paths: [simulate, simulate_python, unitree_robots, example]
    use: Unitree simulator messaging and sim2sim deployment reference.
    caveat: Discover current R1 support from source; do not infer it from support for other Unitree models.

  - name: unitree_sdk2
    url: https://github.com/unitreerobotics/unitree_sdk2
    mode: PAPER_AND_CODE_REFERENCE
    experiments: [08_unitree_r1]
    selected_paths: [include, example, thirdparty]
    use: Static inspection of physical message contracts and motor indexing.
    caveat: Never execute physical communication in autonomous runs.

  - name: unifolm_vla
    url: https://github.com/unitreerobotics/unifolm-vla
    mode: REMOTE_ONLY
    experiments: [07_specialist_skill, 08_unitree_r1, 09_mini_reflect]
    selected_paths: [deployment/model_server, experiments, prepare_data, src/unifolm_vla]
    use: Unitree-specific VLA training, data conversion, inference, and deployment architecture reference.
    caveat: Existing demonstrations/data may target G1 rather than R1; do not claim direct R1 compatibility.

  - name: unifolm_wma
    url: https://github.com/unitreerobotics/unifolm-world-model-action
    mode: REMOTE_ONLY
    experiments: [06_world_model, 08_unitree_r1, 09_mini_reflect]
    selected_paths: [configs, examples, external, prepare_data, scripts, src/unifolm_wma, unitree_deploy]
    use: Unitree-specific world-model/action architecture and deployment reference.
    caveat: Inspect embodiment assumptions; use as a comparison, not a required base.

  # ------------------------------------------------------------------
  # REMOTE ISAAC / R2S2R FUTURE BRANCH
  # ------------------------------------------------------------------
  - name: isaac_sim
    url: https://github.com/isaac-sim/IsaacSim
    mode: REMOTE_ONLY
    experiments: [10_r2s2r]
    selected_paths: [source, apps, tools, README.md]
    use: Remote RTX simulation, rendering, sensors, and reconstructed-scene evaluation.
    caveat: Never install on the M2 Max; verify current supported host requirements.

  - name: isaac_lab
    url: https://github.com/isaac-sim/IsaacLab
    mode: REMOTE_ONLY
    experiments: [10_r2s2r]
    selected_paths: [source, scripts, apps, docs]
    use: Remote RL/domain-randomization and deployment-scene experiments.

  - name: isaac_launchable
    url: https://github.com/isaac-sim/isaac-launchable
    mode: DEFERRED
    experiments: [10_r2s2r]
    selected_paths: [README.md, docker, scripts]
    use: Optional preconfigured remote/browser launch path to reduce Isaac setup work.

  - name: isaac_lab_arena
    url: https://github.com/isaac-sim/IsaacLab-Arena
    mode: DEFERRED
    experiments: [10_r2s2r]
    selected_paths: [source, scripts, docs]
    use: Optional standardized evaluation-environment structure.
```

Repositories not listed here require a short justification and registry entry before use.

---

# 9. Source-use matrix

| Experiment | Start by reusing | Study but do not require | Explicitly defer |
|---|---|---|---|
| 00 Source audit | Git, GitHub metadata, registry script | all selected paths | model checkpoints |
| 01 Policy/control | MuJoCo, Mink or local IK, small `mjctrl` ideas | MJPC, MoveIt Servo, ros2_control | cuRobo unless remote comparison is needed |
| 02 Action chunks | project-local broker; ACT/LeRobot/OpenPI selected files | RTC paper and LeRobot implementation | full large VLA training |
| 03 Recovery | small Python state machine | BehaviorTree.CPP, Nav2 | full ROS 2 orchestration |
| 04 Memory | Python dataclasses + SQLite/JSONL | Spark-DSG, Hydra, ConceptGraphs | online 3D mapping |
| 05 Semantic twin | NetworkX/simple graph; optional USD/IFC adapter | Hydra, OpenUSD, IfcOpenShell | photorealistic reconstruction |
| 06 World model | custom toy Push-T; exact MuJoCo; small MLP | DINO-WM, TD-MPC2, V-JEPA2, LaWAM | direct latent MPC until ranking gate |
| 07 Specialist skill | existing toy task; Unitree MJLab only remotely | Diffusion Policy, Unitree VLA/WMA | insertion before pushing works |
| 08 R1 transfer | official `unitree_rl_mjlab` unchanged | Unitree MuJoCo/SDK2 source contracts | physical robot |
| 09 Integration | validated local interfaces only | Reflect/SayCan/VoxPoser lineage | adding new primitives during integration |
| 10 R2S2R | remote Isaac only after earlier gates | Flexion/Niantic method, Hydra/ConceptGraphs | blocking the core program on reconstruction |

---

# 10. Shared contracts

Implement only the stable minimum in `reflect/types.py`.

## 10.1 Semantic goal

```python
@dataclass(frozen=True)
class SemanticGoal:
    goal_id: str
    entity_ids: tuple[str, ...]
    objective: str
    constraints: tuple["Constraint", ...]
    success_predicate: "Predicate"
```

## 10.2 Skill specification

```python
@dataclass(frozen=True)
class SkillSpec:
    skill_id: str
    skill_type: str
    target_entities: tuple[str, ...]
    target_pose: "Pose | None"
    constraints: tuple["Constraint", ...]
    success_predicate: "Predicate"
    timeout_s: float
    retry_budget: int
```

## 10.3 Observation

```python
@dataclass(frozen=True)
class Observation:
    sequence_id: int
    source_time_ns: int
    received_time_ns: int
    robot_state: "RobotState"
    object_beliefs: tuple["ObjectBelief", ...]
    current_skill_id: str | None
    current_phase: str | None
```

## 10.4 Action chunk

```python
@dataclass(frozen=True)
class ActionChunk:
    chunk_id: str
    skill_id: str
    source_observation_id: int
    source_observation_time_ns: int
    generated_time_ns: int
    valid_from_ns: int
    expires_at_ns: int
    dt_s: float
    actions: np.ndarray
    representation: str
    expected_phase: str | None
    metadata: Mapping[str, Any]
```

Candidate representations:

```text
JOINT_POSITION
JOINT_DELTA
JOINT_VELOCITY
EEF_DELTA
EEF_TRAJECTORY
MPC_GOAL
BOUNDED_RESIDUAL
```

Experiment 01 decides which representations advance. The enum must not imply they are equivalent.

## 10.5 Control reference

```python
@dataclass(frozen=True)
class ControlReference:
    source_chunk_id: str
    time_ns: int
    q_ref: np.ndarray | None
    dq_ref: np.ndarray | None
    eef_ref: np.ndarray | None
    feedforward: np.ndarray | None
    controller_mode: str
```

## 10.6 Object belief

```python
@dataclass
class ObjectBelief:
    entity_id: str
    label: str
    pose: np.ndarray | None
    pose_confidence: float
    state: dict[str, Any]
    state_confidence: float
    last_seen_ns: int
    provenance: tuple[str, ...]
```

## 10.7 Scene relation

```python
@dataclass(frozen=True)
class SceneRelation:
    subject_id: str
    predicate: str
    object_id: str
    confidence: float
    observed_at_ns: int
    provenance: tuple[str, ...]
```

## 10.8 Skill status and recovery

```python
class SkillState(Enum):
    IDLE = "idle"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    ABORTED = "aborted"

class RecoveryDecision(Enum):
    CONTINUE = "continue"
    REFRESH = "refresh"
    RETRIGGER = "retrigger"
    ESCALATE = "escalate"
    ABORT = "abort"
```

## 10.9 World-model prediction

```python
@dataclass(frozen=True)
class WorldModelPrediction:
    observation_id: int
    candidate_id: str
    horizon_s: float
    predicted_progress: float
    predicted_success_probability: float
    predicted_failure_probabilities: Mapping[str, float]
    predicted_state: np.ndarray | None
    predicted_latent: np.ndarray | None
    uncertainty: float | None
    inference_ms: float
```

## 10.10 Execution events

At minimum:

```text
OBSERVATION_RECEIVED
POLICY_REQUESTED
POLICY_RESPONDED
CHUNK_ACCEPTED
CHUNK_REJECTED_EXPIRED
CHUNK_REJECTED_OUT_OF_ORDER
CHUNK_REPLACED
ACTION_EXECUTED
PROGRESS_UPDATED
SKILL_STALLED
SKILL_RETRIGGERED
SKILL_ESCALATED
SKILL_SUCCEEDED
SKILL_FAILED
MEMORY_UPDATED
SEMANTIC_REPLAN
WORLD_MODEL_PREDICTED
WORLD_MODEL_SELECTED
SAFETY_REJECTED
```

All events contain monotonic timestamps, rollout ID, sequence ID, component, config hash, and relevant object/skill IDs.

---

# 11. Standard experiment contract

Every experiment directory must contain:

```text
README.md
CLAIM.md
EXPERIMENT.md
RESULTS.md
INTERFACE_FINDINGS.md
configs/
src/
tests/
results/
```

`CLAIM.md` must include:

```markdown
## Hypothesis

## What this experiment can establish

## What this experiment cannot establish

## Independent variable

## Controlled variables

## Baselines

## Primary metric

## Secondary metrics

## Perturbation distribution

## Kill condition

## Advance condition

## Public source reused

## Public source studied but not imported
```

Every `RESULTS.md` must end with:

```markdown
## Claim tested

## Result
SUPPORTED / NOT_SUPPORTED / INCONCLUSIVE

## Evidence

## What we can claim

## What we cannot claim

## Interface implication

## Unitree R1 implication

## Next experiment justified by this result

## Experiments not justified by this result
```

No result may be marked `SUPPORTED` without actual measurements saved under `results/`.

---

# 12. Experiment 00 — Public-source audit and compatibility map

## Claim search

Determine which public implementations are sufficiently compatible, licensed, maintained, and narrow enough to accelerate this program without becoming the program.

## Hypothesis

A curated set of sparse references and two or three actual dependencies will reduce implementation time more than wholesale adoption of a large robotics stack.

## Can establish

- current repository paths and revisions;
- local/remote compatibility;
- usable source seams;
- license and maintenance blockers;
- whether a source is suitable as dependency, adapter, reference, or deferral.

## Cannot establish

- that an upstream component is production-safe;
- that a paper's reported result reproduces locally;
- that a repository interface will remain stable.

## Tasks

1. Create `references/repos.yaml` from Section 8.
2. Resolve every current default branch and commit SHA.
3. Fetch metadata and licenses without cloning source first.
4. Verify every selected path.
5. Mark missing paths rather than guessing replacements.
6. Create sparse clones only for Experiments 01–03 first.
7. Run minimal import/build smoke tests where inexpensive.
8. Record disk, platform, Python, compiler, and GPU requirements.
9. Create a compatibility matrix:

```text
WORKS_LOCAL_M2
WORKS_LOCAL_CPU_WITH_PATCH
SOURCE_REFERENCE_ONLY
REMOTE_GPU_REQUIRED
REMOTE_LINUX_REQUIRED
LICENSE_REVIEW_REQUIRED
STALE_OR_ARCHIVED
PATH_CHANGED
NOT_EVALUATED
```

10. Generate `docs/SOURCE_MAP.md`, explaining which exact upstream directories map to which local experiment.

## Required automated checks

- every registry URL resolves;
- every resolved revision is a full SHA;
- every selected path either exists or is marked missing;
- every direct/adaptor dependency has a license record;
- no dirty external clone is overwritten;
- no source is copied into `reflect/` without attribution metadata;
- no large model is downloaded by default.

## Primary output

```text
references/repos.lock.yaml
references/licenses.md
docs/SOURCE_MAP.md
experiments/00_source_audit/results/compatibility.csv
```

## Kill condition

Do not spend more than one materially different install attempt on a nonessential repository. Reclassify it as reference/deferred and continue.

## Advance condition

Experiments 01–03 can run from a clean M2 environment using only approved dependencies and pinned sparse references.

---

# 13. Experiment 01 — Policy-to-controller semantic boundary

## Claim search

Determine what a slow learned or semantic policy should command when a faster conventional controller remains responsible for stable execution.

## Hypothesis

On a moving-target arm task, Cartesian/MPC goals or bounded residuals may tolerate policy latency better than raw joint-target chunks, while full learned trajectories may react faster but create more discontinuity.

## Can establish

The relative trade-offs among command representations on one small, controlled arm task.

## Cannot establish

- the universally correct VLA action space;
- performance on contact-rich humanoid manipulation;
- superiority of learned versus classical planning.

## Minimal setup

```text
Apple M2 Max
native MuJoCo
2- or 3-DoF planar arm
500 Hz simulated low-level loop
5–20 Hz synthetic slow policy
moving target
```

Begin with a deterministic synthetic policy. A neural policy is deliberately excluded so model quality does not confound the interface question.

## Public source use

### Reuse directly

- `google-deepmind/mujoco` Python package.
- `kevinzakka/mink` only if differential IK integration remains small.

### Inspect/adapt with attribution

- `kevinzakka/mjctrl`: compact IK/OSC algorithms.
- `google-deepmind/mujoco_mpc/python/mujoco_mpc/demos/predictive_sampling`: planner/task loop.
- `google-deepmind/mujoco_mpc/mjpc/planners`: planner semantics.

### Study only

- MoveIt Servo and `ros2_control` controller chaining.
- cuRobo motion generation.

Do not add ROS 2 or CUDA to this experiment.

## Task

The arm must track an end-effector target. During selected rollouts, move the target after motion begins.

## Command variants

### P1 — Joint target

```text
slow policy → q_target → PD
```

### P2 — Joint trajectory

```text
slow policy → q[t:t+H] → interpolation/executor → PD
```

### P3 — Cartesian target

```text
slow policy → EEF pose → differential IK or local MPC → PD
```

### P4 — Cartesian trajectory

```text
slow policy → EEF path → IK/trajectory layer → PD
```

### P5 — MPC objective

```text
slow policy → target + constraints + success condition → predictive controller → PD
```

### P6 — Bounded residual

```text
classical nominal reference + bounded policy residual → PD
```

## Timing conditions

- policy rate: 5, 10, 20 Hz;
- controller rate: 500 Hz;
- latency: 0, 100, 300, 700 ms;
- one dropped update;
- one late out-of-order response;
- target moved once and twice.

## Controlled variables

- same target trajectories;
- same dynamics;
- same low-level gains;
- same policy information;
- same limits and perturbation seeds;
- equivalent nominal speed where possible.

## Primary metric

```text
recovery time after target displacement
```

## Secondary metrics

- final target error;
- mean and p95 tracking error;
- observation-to-action age;
- joint jerk proxy;
- controller saturation;
- command discontinuity;
- unsafe/clamped commands;
- compute latency.

## Required plots

1. recovery time versus policy latency;
2. tracking error versus policy rate;
3. jerk versus command representation;
4. p95 action age;
5. representative timeline with target, policy updates, control references, and executed motion.

## Kill condition

If a representation cannot be made dimensionally valid and stable with one straightforward controller implementation, mark it unsuitable for this task rather than building a new control stack.

## Advance condition

Advance no more than two representations to Experiment 02. Record why the others were rejected.

## Interface finding sought

Choose the default value domain for `ActionChunk.representation` and determine whether `SkillSpec → MPC goal` or `Policy → trajectory` is the cleaner seam for the next experiment.

---

# 14. Experiment 02 — Temporal action-chunk execution

## Claim search

Determine how new action predictions should modify the unexecuted future while the robot remains in motion.

## Hypothesis

Receding-prefix and asynchronous replacement should improve reaction time over open-loop chunks, but naive immediate replacement will increase discontinuity; overlap-aware replacement should recover much of the reactivity without the jerk.

## Can establish

A latency/reactivity/smoothness trade-off for action-chunk protocols under a fixed task and policy output distribution.

## Cannot establish

- that a particular VLA is physically intelligent;
- that an RTC approximation reproduces the exact RTC algorithm;
- that asynchronous inference is safe on real hardware.

## Public source use

### Reuse or adapt narrowly

- ACT `policy.py` and temporal-ensembling logic as action-chunk lineage.
- LeRobot:
  - `src/lerobot/async_inference/robot_client.py`;
  - `src/lerobot/async_inference/policy_server.py`;
  - `src/lerobot/async_inference/configs.py`;
  - `src/lerobot/policies/rtc/action_queue.py`;
  - `src/lerobot/policies/rtc/latency_tracker.py`;
  - `src/lerobot/policies/rtc/modeling_rtc.py`;
  - async/RTC docs.
- OpenPI:
  - `packages/openpi-client/src/openpi_client/action_chunk_broker.py`.

### Use policy adapters only after synthetic tests pass

- LeRobot ACT;
- SmolVLA through LeRobot;
- OpenPI client pointing at an explicitly configured remote server.

Do not expose any policy server publicly. Do not inherit deserialization or trust assumptions without review.

## Setup

Reuse the selected action representation and environment from Experiment 01. Use the same deterministic fake policy for the main comparison.

## Variants

### A — Open loop

Observe once, produce a chunk, execute the entire chunk.

### B — Receding prefix

Produce a chunk, execute the first `K` actions, discard the rest, re-observe.

### C — Temporal ensemble

Combine overlapping predictions by age-weighted averaging.

### D — Latest-valid replacement

Newest valid chunk replaces all unexecuted future actions.

### E — Asynchronous safe-prefix execution

Continue a valid current prefix while a new proposal is computed; replace only after validation.

### F — Overlap and blend

Blend the overlapping unexecuted region while preserving already issued actions.

### G — RTC-style future conditioning

If a compatible flow policy is available, test the real RTC implementation. Otherwise implement a clearly labelled approximation that conditions or projects the new prefix toward the committed future.

## Runtime invariants

- expired chunks are never executed;
- older observations cannot supersede newer ones;
- action queues are bounded;
- every chunk has an explicit validity interval;
- actions are finite and dimensionally valid;
- already executed actions are immutable;
- policy timeout leads to safe hold, not indefinite stale execution;
- a virtual monotonic clock is used in tests;
- network messages are authenticated/private in any remote run.

## Perturbations

- target moves during inference;
- inference takes 50, 150, 300, 700 ms;
- a response is dropped;
- an old response arrives after a newer one;
- policy server pauses temporarily;
- two valid chunks imply different strategies;
- one chunk contains a discontinuous target.

## Primary metric

```text
perturbation recovery success under the pre-registered latency distribution
```

## Secondary metrics

- completion time;
- action age p50/p95/p99;
- executor idle fraction;
- chunk replacement count;
- invalidated actions;
- jerk and command discontinuity;
- policy-request rate;
- queue overrun count;
- timeout/safe-hold activations.

## Required output

`ACTION_EXECUTION_DECISION.md` must choose:

```text
OPEN_LOOP
RECEDING_PREFIX
TEMPORAL_ENSEMBLE
LATEST_VALID
ASYNC_SAFE_PREFIX
OVERLAP_BLEND
RTC_COMPATIBLE
```

It may choose separate protocols for deterministic trajectories and flow policies.

## Kill condition

Do not train a large VLA to rescue a broken broker. The synthetic-policy execution invariants must pass first.

## Advance condition

A protocol improves perturbation recovery over open loop without exceeding the pre-registered jerk, age, and timeout limits.

---

# 15. Experiment 03 — Event-triggered recovery and semantic escalation

## Claim search

Determine which observable failures should cause local continuation, action refresh, skill retrigger, semantic replanning, or safe abort.

## Hypothesis

A small transparent hierarchy will outperform both “always retry locally” and “always wake the semantic agent,” because failures occur at different abstraction levels.

## Can establish

A useful mapping from controlled failure signatures to recovery levels on one toy manipulation task.

## Cannot establish

- a universal recovery taxonomy;
- VLM reasoning quality;
- physical safety certification.

## Public source use

### Study/adapt

- BehaviorTree.CPP asynchronous action and reactive-fallback semantics.
- Nav2 `nav2_bt_navigator`, `nav2_behavior_tree`, and `nav2_behaviors` recovery patterns.
- Flexion Reflect v1 descriptions of local motion recovery versus mission-agent replanning.
- Inner Monologue-style structured feedback to a high-level planner.

Implement the atomic experiment as a small Python state machine. Do not add C++/ROS 2 until there is a measured reason.

## Recovery decisions

```text
CONTINUE
REFRESH
RETRIGGER
ESCALATE
ABORT
```

Meaning:

- `CONTINUE`: controller/current policy can absorb the error;
- `REFRESH`: remaining future is stale; request new actions without resetting the skill;
- `RETRIGGER`: semantic skill remains valid, but execution state/action history must reset;
- `ESCALATE`: precondition or strategy is invalid; return to mission planner;
- `ABORT`: unsafe or retry budget exhausted.

## Progress monitor inputs

- goal error;
- recent goal-error derivative;
- target displacement since source observation;
- target/object existence;
- reachability predicate;
- action age;
- controller saturation;
- time in skill;
- retry count;
- recent safety rejections;
- semantic precondition validity.

## Test injections

| Injection | Expected default response |
|---|---|
| small continuous target shift | continue or refresh |
| large but reachable target shift | retrigger |
| target removed | escalate |
| new blocker invalidates approach | escalate |
| stale action chunk | refresh/retrigger |
| policy progress stalls | retrigger |
| repeated retrigger failures | escalate/abort |
| action exceeds safety envelope | abort |
| instruction changes | escalate immediately |

The expected response is a hypothesis, not a hard-coded correctness label. Evaluate task outcome and decision cost.

## Baselines

```text
R0 no recovery
R1 always refresh
R2 always retrigger
R3 always semantic replan
R4 threshold-based hierarchy
```

## Metrics

- eventual success;
- first-attempt success;
- recovery latency;
- unnecessary refreshes;
- unnecessary retriggers;
- unnecessary semantic replans;
- missed escalations;
- actions executed after failure onset;
- retry count;
- infinite-loop rate;
- total task time.

## Required artifact

`RECOVERY_POLICY.md` must contain an empirical table:

```text
observed signature → selected recovery level → confidence → outcome
```

## Kill condition

Do not train a learned failure classifier until the heuristic hierarchy has a measured confusion pattern and enough labelled episodes.

## Advance condition

The hierarchy beats both local-only and semantic-only recovery on eventual success or intervention cost without creating loops.

---

# 16. Experiment 04 — Robot memory decomposition

## Claim search

Determine which forms of memory are useful to a hierarchical robot agent under stale, occluded, and changing state.

## Hypothesis

A semantic object graph plus episodic event log will outperform either a vector-only memory or stateless observation, while confidence/staleness is necessary to avoid confidently acting on obsolete poses.

## Can establish

Task-relevant query and decision performance for several memory structures in a synthetic environment.

## Cannot establish

- real perception quality;
- building-scale mapping performance;
- that one database is optimal for production.

## Public source use

### Start local and minimal

- Python dataclasses;
- SQLite or DuckDB for events;
- NetworkX or a small typed adjacency structure;
- JSON snapshots;
- optional Rerun adapter for temporal visualization.

### Study before adopting

- Spark-DSG Python/data model;
- Hydra hierarchy and update semantics;
- ConceptGraphs object identity, embeddings, and relations.

Do not install Hydra/ConceptGraphs before the hand-authored benchmark proves the interface useful.

## Memory layers

### Fast state

Recent seconds of observations, robot state, actions, and controller events. Ring buffer; not durable truth.

### Episodic event log

Append-only skill attempts, outcomes, failures, interventions, and world changes.

### Semantic object graph

Stable entity IDs, classes, affordances, operational states, and typed relations.

### Geometric state

Metric pose, covariance/confidence, bounds, frames, and last update.

### Embedding index

Optional retrieval aid attached to stable entity/event IDs. Never authoritative by itself.

## Synthetic environment

- five rooms;
- six doors;
- ten objects;
- two valves;
- two tools;
- one charger;
- one restricted room;
- one robot.

## Relations

```text
IN
ON
NEAR
BLOCKS
CONNECTS
HELD_BY
REACHABLE
RESTRICTED_BY
OBSERVED_AT
```

## Events

- object moves while unobserved;
- object is temporarily occluded;
- door opens/closes;
- pose becomes stale;
- task attempt fails;
- duplicate labels appear;
- contradictory observation arrives;
- room becomes restricted;
- object is picked up or placed;
- instruction references an earlier encounter.

## Architectures

```text
M0 current observation only
M1 recent-state buffer
M2 episodic event log only
M3 semantic graph only
M4 semantic graph + episodic log
M5 M4 + confidence/staleness
M6 M5 + embeddings
```

## Benchmark queries

- Where is Valve 3?
- When was it last observed?
- Is its remembered pose safe to use?
- Did we already try opening it?
- Why did the last attempt fail?
- Which valve is reachable without entering a restricted area?
- What changed since the last Room 2 visit?
- Which object blocks the route to Pump 1?
- Which similarly labelled object was actually manipulated?
- Which observations conflict, and what remains unknown?

## Primary metric

```text
correct task-relevant answer/decision rate under changed and stale state
```

## Secondary metrics

- stale-belief action rate;
- wrong-identity rate;
- repeated-observation requests;
- failure-explanation accuracy;
- query latency;
- stored bytes;
- context facts passed to the planner;
- confidence calibration.

## Required output

`MEMORY_ARCHITECTURE_DECISION.md` must state what belongs in:

```text
FAST_STATE
EPISODIC_LOG
SEMANTIC_GRAPH
GEOMETRIC_STATE
EMBEDDING_INDEX
LEARNED_LATENT
```

## Kill condition

If embeddings do not improve ambiguous retrieval over lexical/typed queries, remove them from the runtime path.

## Advance condition

A memory composition measurably reduces stale/wrong decisions and unnecessary scans without overwhelming the planner context.

---

# 17. Experiment 05 — Semantic digital twin and building planner

## Claim search

Determine how durable geometry, topology, semantics, operational state, and current belief should be separated for language-grounded planning.

## Hypothesis

A four-layer representation—geometry, topology, semantics, and live belief—will replan correctly under world changes more often than geometry-only or semantics-without-confidence representations.

## Can establish

The representational value of these layers on a small hand-authored building and task set.

## Cannot establish

- mapping from raw sensors;
- BIM interoperability at industrial scale;
- photorealistic simulation value;
- general natural-language grounding.

## Public source use

### Minimal implementation

- typed Python records;
- NetworkX or equivalent for topology;
- simple 2D metric planner;
- memory interface from Experiment 04.

### Optional adapters after core benchmark works

- OpenUSD for durable scene hierarchy/geometry export;
- IfcOpenShell for IFC import;
- Spark-DSG for runtime graph representation.

### Architectural references

- Hydra/Kimera hierarchical scene graphs;
- ConceptGraphs open-vocabulary object graphs;
- Flexion/Niantic/NVIDIA R2S2R separation of visual representation and collision geometry.

## Four required layers

### Geometry

Metric poses, coordinate frames, bounds, meshes/occupancy, collision geometry.

### Topology

Rooms, corridors, door connectivity, traversability, containment, route costs.

### Semantics

Identity, class, aliases, affordances, policies, restrictions, task-relevant properties.

### Live belief

Current operational state, confidence, timestamp, provenance, visibility, and uncertainty.

Do not store all four as a single untyped dictionary.

## Tiny building

```text
Building
└── Floor1
    ├── Lobby
    ├── CorridorA
    ├── PumpRoom
    ├── ElectricalRoom
    └── RestrictedLab
```

Include doors, pumps, valves, chargers, inspection points, tools, and one movable blocker.

## Missions

1. Inspect the nearest coolant valve without entering a restricted room.
2. Reach Pump 2, but recharge first if estimated battery is insufficient.
3. Inspect Valve 7; if Door 3 is unavailable, use another route.
4. Find a safe location for a carried tool.
5. Replan after a room becomes restricted during execution.

## Dynamic events

- door opens/closes;
- room restriction changes;
- asset operational state changes;
- asset pose becomes stale;
- movable object blocks a route;
- topology edge becomes unavailable;
- battery estimate changes;
- instruction changes.

## Ablations

```text
T0 geometry only
T1 geometry + topology
T2 T1 + semantics
T3 T2 + live belief/confidence
T4 T3 + episodic history
```

## Metrics

- mission success;
- route length/cost;
- forbidden-region violations;
- invalid affordance choices;
- replanning latency;
- stale-belief failures;
- semantic query count;
- geometry query count;
- context size sent to optional LLM planner.

## Optional LLM agent

Implement a deterministic rule-based planner first. An LLM may be added only as a structured tool caller behind:

```text
ALLOW_EXTERNAL_LLM=1
```

It receives compact query results, not the whole twin.

## Required output

`TWIN_ARCHITECTURE_DECISION.md` must answer:

- what belongs in BIM/IFC;
- what belongs in USD/geometric twin;
- what belongs in the runtime scene graph;
- what belongs only in live belief;
- which facts are authoritative versus inferred;
- how stale geometry/state is represented;
- what the semantic agent is allowed to query and mutate.

## Kill condition

Do not implement a dense 3D reconstruction or SLAM pipeline. If USD/IFC setup becomes a blocker, preserve the adapter interface and complete the experiment with native structures.

## Advance condition

T3 or T4 materially reduces invalid plans under dynamic events compared with T0–T2.

---

# 18. Experiment 06 — Learned world-model candidate ranking

## Claim search

Determine whether learned future prediction adds action-selection value beyond a reactive policy, a simple progress heuristic, and exact short simulator rollouts.

## Hypothesis

A compact learned state-dynamics model may approximate simulator-based ranking cheaply in-distribution, while a visual latent model may generalize goals but will only be useful if its candidate ordering—not just prediction loss—is accurate.

## Can establish

Whether small learned predictors improve candidate ranking and selection regret on a fixed planar pushing benchmark.

## Cannot establish

- that world models improve general manipulation;
- that latent MPC is production ready;
- that image prediction quality implies action utility;
- that a model trained in one simulator transfers to the real R1.

## Public source use

### Reuse

- MuJoCo for exact rollout ground truth;
- optionally Diffusion Policy's Push-T environment/data conventions;
- small PyTorch models.

### Inspect/adapt

- DINO-WM `planning/`, `models/`, `plan.py`, and config structure;
- TD-MPC2 model/planner organization;
- V-JEPA2 action-conditioned application structure;
- LaWAM latent-action/subgoal architecture;
- Hydrax only for a later exact-physics planner comparison.

### Explicitly defer

- large V-JEPA checkpoints;
- direct latent CEM/MPPI;
- giant video-generation world models;
- online robot learning.

## Environment

A planar pushing world with:

- controllable end-effector or robot disk;
- movable object with pose;
- target pose;
- optional wall/obstacle;
- randomized mass/friction/geometry;
- exact simulator outcome.

## Candidate set

At each selected state generate `K = 8` meaningful one-second trajectories:

- direct push;
- push left edge;
- push right edge;
- push from below;
- diagonal push;
- retreat/reposition then push;
- slow conservative push;
- hold/no-op.

Candidate generation must be deterministic from seed. Candidates should represent distinct physical strategies rather than eight Gaussian perturbations of one trajectory.

## Selectors

### W0 — Random

Uniform candidate.

### W1 — Hand-designed progress heuristic

Object-target distance, orientation error, collision penalty, and action cost.

### W2 — Exact simulator rollout

Upper-bound model-based selector using the actual simulator.

### W3 — Non-dynamics progress classifier

Current state + action summary → progress/success/failure.

### W4 — Learned privileged-state dynamics

Current robot/object state + full candidate chunk → predicted future state/progress/failure.

### W5 — Compact observation-latent dynamics

Encoded observation + action chunk → future latent + progress/failure heads.

Optional visual version uses 64×64 rendering and a small frozen CNN. Do not download a foundation encoder by default.

## Dataset rules

- include successful, failed, collision, no-op, and recovery trajectories;
- split by rollout/scene seed, never adjacent frames;
- keep held-out friction, mass, geometry, and obstacle distributions;
- record candidate outcomes, not only executed policy data;
- preserve source simulator/config SHA.

## Primary metrics

### Rank correlation

```text
Spearman(predicted candidate order, actual candidate order)
```

### Selection regret

```text
actual cost(model-selected candidate) - actual cost(best available candidate)
```

Lower is better.

## Secondary metrics

- top-1 candidate accuracy;
- pairwise ordering accuracy;
- future-state error;
- progress/success calibration;
- failure precision/recall;
- held-out friction/mass/geometry performance;
- inference p50/p95;
- model size;
- uncertainty versus error.

## Hard gate

If W4/W5 do not beat W1 on held-out selection regret and remain within the runtime latency budget:

```text
STOP WORLD-MODEL AUTHORITY
```

Retain them only for offline analysis if informative.

## Conditional extension

Only after the gate passes, test:

```text
policy produces 8 meaningful chunks
        ↓
world model ranks them
        ↓
executor validates selected chunk
        ↓
execute short prefix
```

Do not implement arbitrary latent action search yet.

## Required decision

`WORLD_MODEL_DECISION.md` must choose exactly one:

```text
NOT_USEFUL_YET
OFFLINE_ANALYSIS_ONLY
SHADOW_OBSERVER
FAILURE_CRITIC
CANDIDATE_SELECTOR
LATENT_SUBGOAL_MODEL_WORTH_TESTING
DIRECT_PLANNER_WORTH_TESTING
```

The choice must be based on held-out ranking, regret, calibration, and latency—not visual plausibility.

---

# 19. Experiment 07 — Specialist learned physical skill

## Claim search

Determine whether a heterogeneous motion layer—general reactive policy plus a specialist contact skill—improves reliability enough to justify maintaining multiple policy classes.

## Hypothesis

A specialist planar-pushing policy will outperform a general/scripted action policy under contact variation, while the general policy remains useful for approach, repositioning, and task breadth.

## Can establish

The value of specialist dispatch on one contact regime and one embodiment.

## Cannot establish

- that RL is always preferable for contact;
- that one specialist generalizes across all objects;
- that insertion or dexterity has been solved;
- that a VLA and RL skill will compose on hardware without additional control work.

## Public source use

### Local/toy branch

- reuse the planar pushing task and metrics from Experiment 06;
- optionally use Diffusion Policy Push-T conventions as a policy baseline;
- use an existing compact PPO/SAC implementation only if already available and well maintained.

### Remote Unitree branch

- reuse `unitree_rl_mjlab` task/config/training conventions;
- inspect `unifolm-vla` for Unitree policy server/data conventions;
- inspect `unifolm-world-model-action` for learned-prediction/action interfaces;
- do not fork the Unitree RL implementation into a new framework.

## Task sequence

### Phase A — Local contact benchmark

```text
general scripted/reactive policy
vs
specialist learned push policy
vs
general policy with specialist dispatch
```

### Phase B — Remote R1 simulation, only after Experiment 08 baseline

Use a stable or supported stance. Expose a large tabletop object and planar goal. Keep privileged object state initially.

## Specialist interface

```python
class SpecialistSkill(Protocol):
    def reset(self, observation: Observation, spec: SkillSpec) -> None: ...
    def propose(self, observation: Observation) -> ActionChunk: ...
    def status(self) -> SkillStatus: ...
    def abort(self, reason: str) -> None: ...
```

The mission agent sees only:

```text
PUSH(object_id, target_region, constraints)
```

It does not see reward terms, policy state, or raw training observations.

## Training observations

Start privileged:

- joint/base state;
- hand-object relative state;
- object-target relative pose;
- previous action;
- optional contact proxy.

Later visual observations are a separate ablation.

## Actions

Controller-compatible joint targets, joint deltas, or a validated upper-body target representation from Experiments 01/08. Do not make the high-level specialist emit raw motor torque.

## Reward terms

Keep separately logged:

- object progress;
- final goal accuracy;
- useful contact;
- upright/stability;
- smoothness;
- joint-limit penalty;
- excessive velocity/effort proxy;
- fall/unsafe termination;
- completion bonus.

## Randomization

- object pose;
- object mass and friction;
- table friction;
- object geometry scale;
- action delay;
- controller tracking error;
- mild external perturbation;
- held-out ranges distinct from training.

## Baselines

```text
S0 scripted general policy
S1 receding reactive general policy
S2 specialist learned push
S3 general approach → specialist contact
S4 specialist with retrigger/escalation
```

## Metrics

- first-attempt success;
- held-out success;
- eventual success after retrigger;
- object final-pose error;
- cycle time;
- unsafe/stability terminations;
- policy inference time;
- data/compute required;
- number of task-specific assumptions;
- dispatch errors.

## Kill condition

If the specialist does not beat the strong reactive/scripted baseline under held-out contact variation, do not keep it merely because it is learned.

## Advance condition

S3 or S4 demonstrates a reliability or intervention advantage large enough to justify the additional policy/runtime complexity.

## Required output

`SPECIALIST_SKILL_DECISION.md` must choose:

```text
NO_SPECIALIST_REQUIRED
SPECIALIST_ONLY_FOR_CONTACT
SPECIALIST_AS_FALLBACK
SPECIALIST_AS_PRIMARY_SKILL
INSUFFICIENT_EVIDENCE
```

---

# 20. Experiment 08 — Unitree R1 embodiment transfer

## Claim search

Determine whether the interfaces selected by Experiments 01–07 transfer to the official Unitree R1 simulation/training/deployment substrate without being redesigned around the humanoid.

## Hypothesis

`SkillSpec`, timestamped `ActionChunk`, bounded action validity, refresh/retrigger/escalation, and specialist dispatch should survive embodiment transfer even if the selected action representation and controller adapter change.

## Can establish

The portability of explicit runtime contracts to the R1 simulation stack.

## Cannot establish

- real-hardware safety;
- general R1 manipulation;
- walking/manipulation integration at production quality;
- direct compatibility of G1-targeted VLA/WMA models with R1.

## Primary public source

Use the current pinned official repository:

- <https://github.com/unitreerobotics/unitree_rl_mjlab>

Relevant top-level directories currently include:

```text
src/
scripts/
simulate/
deploy/
doc/
```

Discover current internal paths from the pinned SHA; do not rely on remembered command names.

Supporting references:

- <https://github.com/unitreerobotics/unitree_mujoco>
- <https://github.com/unitreerobotics/unitree_sdk2>
- <https://github.com/unitreerobotics/unifolm-vla>
- <https://github.com/unitreerobotics/unifolm-world-model-action>

`unitree_sdk2` is for static contract inspection only during autonomous work.

## Compute topology

```text
M2 Max
├── code, tests, logs, analysis
├── source/mapping audit
└── remote job orchestration

Remote Ubuntu + NVIDIA GPU
├── official R1 MJLab train/play
├── bounded RL smoke runs
├── ONNX export/inference
└── custom R1 simulation experiment

Physical R1
└── not accessed
```

## Phase 0 — Source and safety audit

Create:

```text
experiments/08_unitree_r1/docs/R1_SOURCE_MAP.md
experiments/08_unitree_r1/docs/R1_JOINT_MAPPING_AUDIT.md
experiments/08_unitree_r1/results/r1_joint_mapping_manifest.yaml
experiments/08_unitree_r1/tests/test_r1_joint_mapping.py
```

The manifest must map every simulated actuator to the expected SDK motor slot, including:

- canonical joint name;
- MJCF joint and actuator;
- simulator index;
- SDK joint name and motor slot;
- skipped physical slots;
- command/state sign;
- position offset;
- lower/upper limits;
- effort limit;
- gains;
- source file/symbol.

Tests:

- exact joint-name coverage;
- no duplicate indices/slots;
- explicit skipped slots;
- zero and one-hot mappings;
- random bounded round trip;
- left/right arm isolation;
- waist/head/leg isolation;
- observation order equals training order;
- action order equals deployment order.

If upstream has fixed issue #52, document the source/commit and retain regression tests.

## Phase 1 — Reproduce official baseline unchanged

Before adding custom code:

1. list registered R1 tasks;
2. load one official R1 config;
3. reset and step one environment;
4. play an existing checkpoint or run a bounded training smoke;
5. save and reload a checkpoint;
6. export ONNX if supported;
7. compare framework and ONNX inference on recorded observations;
8. inspect simulation-deployment path through loopback only.

Record exact commands, revisions, dependency versions, and return codes.

## Phase 2 — Thin adapter

Add only a thin adapter between shared contracts and the official R1 action/observation interface:

```text
R1ObservationAdapter
R1ActionChunkAdapter
R1SafeHoldAdapter
R1SkillStatusAdapter
```

Do not modify official actuator parameters, DDS contracts, FSMs, or low-level policies unless a verified issue requires a project-local patch.

## Phase 3 — Minimal task

Use a stable or supported manipulation stance and one large tabletop object.

Task:

```text
reach toward and push a large object toward a planar target
```

Clearly label two modes when feasible:

```text
SUPPORTED_OR_FIXED_UPPER_BODY
FREE_BASE_OR_EXISTING_STANDING_SUBSTRATE
```

Success in the supported mode is not whole-body humanoid success.

## Transferred ablations

```text
U0 official baseline only
U1 open-loop ActionChunk
U2 selected reactive action protocol
U3 U2 + refresh/retrigger
U4 U3 + semantic escalation event
U5 U4 + specialist push, if Experiment 07 passed
U6 U5 + shadow world-model ranking, if Experiment 06 passed
```

## Metrics

- contract validation failures;
- R1 task success;
- perturbation recovery;
- stance/stability failures;
- action age;
- target discontinuity;
- retrigger latency;
- simulator loop rate;
- ONNX parity;
- mapping-test status;
- amount of embodiment-specific code;
- shared-interface changes required.

## Kill condition

Stop custom task work if the official baseline, mapping audit, or observation/action order cannot be reproduced confidently. Do not compensate by patching many layers at once.

## Advance condition

At least the selected action protocol and recovery interface run in R1 simulation with no redesign of mission/memory contracts and with bounded embodiment-specific adapters.

## Required output

`R1_TRANSFER_DECISION.md` must list:

- contracts transferred unchanged;
- contracts adapted only at the edge;
- contracts invalidated by the humanoid;
- whole-body-control assumptions exposed;
- physical deployment blockers;
- exact next supervised deployment gate.

---

# 21. Experiment 09 — Mini-Reflect integration

## Claim search

Determine whether independently validated components compose into a useful hierarchical system on one mission, and identify which layer contributes which gains.

## Hypothesis

A hierarchy with semantic memory, skill-level planning, reactive action execution, local retriggering, and semantic replanning will outperform monolithic/open-loop execution under structured perturbations. A world model will only help if its candidate-ranking gate passed.

## Can establish

Component contribution and interaction on one controlled long-horizon mission.

## Cannot establish

- general autonomy;
- production deployment;
- general language understanding;
- superiority of Reflect as a universal architecture.

## Integration rule

This worktree consumes validated interfaces. It may not invent a new generic framework to avoid integrating them.

If two experiments produced incompatible interfaces:

1. document the conflict;
2. implement the smallest explicit adapter;
3. rerun the relevant atomic regression;
4. do not silently choose one and rewrite the other.

## Architecture

```text
MissionAgent
     ↓ SemanticGoal
SemanticMemory / Twin Queries
     ↓ grounded SkillSpec
SkillRouter
 ┌─────────────────┬──────────────────┐
 │ general policy  │ specialist skill │
 └────────┬────────┴────────┬─────────┘
          ↓ ActionChunk(s)
Optional progress/world-model critic or selector
          ↓ validated ActionChunk
ReactiveExecutor
          ↓ ControlReference
MPC / IK / trajectory layer where selected
          ↓
PD / impedance / whole-body controller
```

Feedback:

```text
small continuous error             → controller/current policy
future invalidated                 → refresh
same skill locally recoverable     → retrigger
semantic precondition invalid      → semantic replan
unsafe                             → abort
```

## Mission

```text
Find the requested object and push it into the target zone.
If access is blocked, clear the blocker first.
Verify the final state.
```

Optional second instruction during rollout:

```text
Stop the current attempt, place/leave the object safely, and use the other target.
```

## Agent variants

### Deterministic baseline

Rule-based planner over typed tools and predicates.

### Optional language planner

LLM/VLM tool caller only when `ALLOW_EXTERNAL_LLM=1`. It may invoke structured tools but may not produce raw actions.

## Tools

```text
look()
find(label_or_query)
get_state(entity_id)
get_constraints(entity_id)
run_skill(skill_spec)
verify(predicate)
abort_skill(reason)
safe_hold()
```

## Ablation ladder

```text
A open-loop skill execution
B A + receding action refresh
C B + async/overlap action replacement
D C + local retrigger
E D + persistent semantic memory
F E + semantic replanning
G F + specialist contact skill
H G + simple progress/failure critic
I G + learned world-model veto
J G + learned world-model candidate selector
```

Run only branches justified by prior experiment gates.

## Perturbation suite

- target moves slightly;
- target moves substantially;
- blocker introduced;
- blocker removed;
- target disappears;
- stale memory;
- inference delay;
- stale/out-of-order chunk;
- skill stall;
- contact result differs from expectation;
- instruction changes;
- mild base disturbance in R1 mode where safe in simulation.

## Primary metrics

- end-to-end mission success;
- eventual success after recovery;
- progress before first incorrect decision;
- unrecoverable/intervention episodes.

## Layer metrics

### Agent

- correct tool/skill selection;
- verification compliance;
- repeated failed calls;
- semantic replan correctness;
- instruction-change response latency.

### Memory/twin

- entity grounding;
- stale-state detection;
- wrong-object actions;
- unnecessary observations.

### Motion/execution

- skill success;
- action age;
- perturbation recovery;
- chunk discontinuity;
- retrigger success.

### World model

- false veto;
- missed failure;
- candidate-selection regret;
- episodes uniquely recovered due to selection.

### Runtime

- p95/p99 component latency;
- expired chunks;
- queue overruns;
- safe-hold activations;
- process failures.

## Kill condition

Do not introduce a new major component during integration. When integration exposes a missing capability, record a new bounded experiment proposal rather than implementing it invisibly.

## Advance condition

The full hierarchy improves recovery or intervention cost over simpler ablations, and attribution is possible from logs.

## Required output

`ARCHITECTURE_DECISIONS.md` must answer exactly:

1. What does the mission agent emit?
2. What does the semantic memory/twin expose?
3. What does the general policy emit?
4. What does a specialist skill emit?
5. What does the executor own?
6. What does MPC/IK own?
7. What does PID/impedance/whole-body control own?
8. What triggers continue, refresh, retrigger, replan, and abort?
9. What state persists, and where?
10. Does a learned world model add measured runtime value?
11. Which interfaces transferred to R1 unchanged?
12. Which production gaps remain?

---

# 22. Experiment 10 — Deferred real-to-sim-to-real site experiment

## Claim search

Determine whether reconstructing the actual deployment environment reduces site-specific visual or geometric adaptation needs relative to generic or manually modelled simulation.

## Hypothesis

A metric reconstructed static scene with aligned visual and collision representations will reduce site-specific visual discrepancy and policy adaptation cost, but only for aspects actually represented and calibrated.

## Can establish

A measured benefit of site reconstruction on one deployment scene and task.

## Cannot establish

- general manipulation sim-to-real;
- perfect dynamics transfer;
- that Gaussian splats should represent dynamic collision bodies;
- that navigation results automatically transfer to humanoid manipulation.

## Prerequisites

Do not run until:

- Experiments 01–05 have stable contracts;
- at least one perceptive policy exists;
- the remote RTX host is available;
- Isaac Sim/Isaac Lab current requirements are verified;
- a generic and manually modelled baseline exists;
- real data collection is authorized.

## Public source use

- Flexion/Niantic/NVIDIA R2S2R blog and methodology;
- remote `isaac-sim/IsaacSim`;
- remote `isaac-sim/IsaacLab`;
- optional `isaac-launchable` to reduce remote setup;
- Hydra/ConceptGraphs for scene-graph/perception references;
- OpenUSD for scene composition;
- Unitree R1 explicit dynamic asset/control interface.

## Compute topology

Isaac runs remotely on supported RTX Linux. The M2 Max is the control plane and optional remote-view client.

## Representation separation

```text
static metric visual representation
        +
aligned static collision mesh
        +
explicit dynamic robot/object assets
        +
runtime semantic/belief overlay
```

Do not treat a visual reconstruction as authoritative dynamic physics.

## Ablations

```text
R0 generic synthetic environment
R1 manually modelled real cell
R2 reconstructed visual scene + manual collision geometry
R3 jointly aligned visual representation + reconstructed collision mesh
R4 R3 + measured domain randomization
R5 R4 + small amount of real adaptation data
```

## Task

Choose one already-working perceptive task, preferably reach/push rather than insertion. Keep action/controller architecture fixed.

## Gap registry

For every mismatch record:

- parameter;
- real measurement/status;
- simulator nominal;
- training range;
- held-out range;
- measurement method;
- expected sensitivity;
- evidence/provenance.

Include:

- camera intrinsics/extrinsics;
- frame/timestamp offset;
- exposure, white balance, blur;
- object-pose error;
- depth/segmentation error;
- robot tracking error;
- action/observation delay;
- mass/friction/contact geometry;
- static reconstruction alignment.

## Metrics

- real/sim feature discrepancy;
- pose-estimation error;
- task success in held-out simulation;
- real task success under staged evaluation;
- real demonstrations required;
- interventions required;
- time/data to adapt to scene changes;
- sim-real success gap;
- failure class distribution.

## Kill condition

If reconstruction does not improve a pre-registered visual/geometric metric over the manual twin, do not retain it merely for visual appeal.

## Advance condition

R3/R4/R5 measurably reduces adaptation data, interventions, or real/sim gap relative to R0/R1.

## Required output

`R2S2R_DECISION.md` must choose:

```text
NOT_JUSTIFIED
USE_FOR_VISUAL_EVALUATION
USE_FOR_SITE_SPECIFIC_TRAINING
USE_FOR_GEOMETRIC_VALIDATION
USE_AS_FULL_R2S2R_STAGE
INSUFFICIENT_EVIDENCE
```

---

# 23. Sim-to-real methodology for the Unitree branch

This methodology is mandatory even if the current work is simulation-only.

## Stage 0 — Source, units, frames, and indexing

Before policy evaluation:

- pin source SHAs;
- audit R1 joint/motor mapping;
- audit observation order;
- audit action order;
- audit units, signs, offsets, limits, gains, and normalization;
- establish named coordinate frames;
- record simulator/control rates;
- verify timestamps use monotonic clocks;
- verify every exported model carries an observation/action schema version.

A high benchmark score is irrelevant if policy and deployment joint order differ.

## Stage 1 — Nominal train/play regression

- train or load the official baseline;
- run deterministic playback seeds;
- record checkpoint SHA/hash;
- check finite observations/actions;
- check action-limit violations;
- record observation/action distributions;
- preserve videos and event traces where inexpensive.

## Stage 2 — Held-out simulation

Separate:

```text
nominal parameters
training randomization
held-out stress randomization
future real measurements
```

Initial registry:

- actuator gain and damping;
- tracking error;
- command delay;
- observation delay;
- controller jitter;
- mass/inertia;
- ground and object friction;
- contact geometry/margin;
- object pose error;
- camera pose error;
- external pushes;
- dropped observations/actions.

Do not choose enormous arbitrary ranges. Mark each range as measured, specified, estimated, or unknown.

## Stage 3 — Export/runtime parity

For ONNX or another runtime format:

- run the same recorded observations through training and deployment runtimes;
- compare outputs numerically;
- verify preprocessing and normalization;
- verify action scaling and clipping;
- verify joint ordering;
- measure p50/p95 inference latency;
- reject malformed or nonfinite input;
- test fallback on runtime failure.

## Stage 4 — Sim2sim through loopback

When the Unitree deployment bridge supports simulator messaging, run only through:

```text
lo
localhost
127.0.0.1
```

The deployment guard must reject every other interface while `PHYSICAL_DEPLOYMENT_ALLOWED=false`.

Record every state/message mapping. Treat this as a deployment-contract test, not just a motion demo.

## Stage 5 — Cross-engine validation when available

Where practical, compare:

- MJLab training simulation;
- Unitree MuJoCo/simulation deployment path;
- optional remote Isaac environment later.

The objective is not identical trajectories. It is to reveal policies that depend on one simulator's contact, timing, or observation artifacts.

## Stage 6 — Shadow hardware mode

Document, but do not autonomously execute:

- receive real observations;
- compute policy actions;
- run safety validation;
- log actions;
- publish no motor commands.

Compare policy proposals with teleoperation, current controller behavior, and observed future states.

## Stage 7 — Human-supervised physical gates

Future deployment requires:

- mapping audit manually approved;
- physical emergency stop;
- secured/suspended or otherwise safe setup;
- reduced position/velocity/effort limits;
- local watchdog;
- explicit safe hold/damping mode;
- command expiry;
- operator takeover;
- staged joint-group and skill activation;
- post-run inspection;
- rollback procedure.

No Codex prompt can authorize this stage by itself.

## Stage 8 — Failure-driven real-to-sim loop

For each future real failure:

1. assign the likely layer: perception, memory, semantics, policy, controller, timing, mapping, dynamics, or runtime;
2. preserve raw evidence;
3. reproduce it in simulation or replay;
4. add it to held-out evaluation before training on it;
5. modify only the relevant component or uncertainty range;
6. rerun regression and ablations;
7. pass staged gates again.

Do not respond to every failure by widening all domain-randomization ranges.

---

# 24. Rollout, dataset, and event format

Every experiment should produce:

```text
results/<experiment>/<run_id>/
├── metadata.json
├── config.json
├── metrics.json
├── events.jsonl
├── observations.npz or observations.parquet
├── actions.parquet
├── candidates.parquet               # when applicable
├── memory_snapshots.jsonl            # when applicable
├── video.mp4                         # optional
└── summary.md
```

## Required metadata

- experiment ID and claim revision;
- Git SHA;
- dirty-diff hash or clean status;
- public-source lockfile hash;
- OS/architecture;
- CPU/GPU;
- Python and dependency versions;
- seed;
- simulator and task config hash;
- model/checkpoint hashes;
- action/observation schema versions;
- wall-clock and monotonic start/end times;
- status: pass, fail, blocked, interrupted.

## Candidate data

World-model and planner experiments must preserve:

```text
state/observation ID
candidate ID
candidate source
full candidate chunk or compressed reference
predicted score/outcome
actual simulator score/outcome
selected flag
execution flag
```

## Replay

Implement one command:

```bash
python -m reflect.rollout replay results/<experiment>/<run_id>
```

Replay must reconstruct:

- observations/events in timestamp order;
- chunk acceptance/rejection;
- current skill/mission state;
- recovery decisions;
- semantic-memory mutations;
- world-model rankings;
- executed control references.

It need not rerun physics unless explicitly requested.

---

# 25. Standard metrics

Use a shared vocabulary while preserving experiment-specific metrics.

## Runtime

- policy latency p50/p95/p99;
- observation-to-action age p50/p95/p99;
- executor idle fraction;
- missed deadline count;
- expired chunk count;
- queue overrun count;
- safe-hold activations.

## Physical/task

- first-attempt success;
- eventual success;
- final task error;
- cycle time;
- perturbation recovery;
- controller saturation;
- command jerk/discontinuity;
- safety rejection count.

## Recovery

- decision confusion matrix;
- recovery latency;
- unnecessary retrigger/replan;
- missed escalation;
- retry count;
- infinite-loop rate.

## Memory/semantics

- entity identity accuracy;
- stale-belief error;
- wrong-object action;
- semantic query correctness;
- repeated-observation requests;
- context size;
- provenance coverage.

## World model

- candidate rank correlation;
- selection regret;
- top-1 accuracy;
- pairwise ranking accuracy;
- calibration;
- OOD degradation;
- model exploitation events;
- inference latency and size.

## Integration

- end-to-end mission success;
- progress before first incorrect decision;
- interventions/unrecoverable episodes;
- episodes recovered by each layer;
- code/interface changes per embodiment.

---

# 26. Common perturbation taxonomy

Assign every perturbation and failure one primary category:

```text
PERCEPTION
STATE_ESTIMATION
MEMORY_STALENESS
SEMANTIC_GROUNDING
TASK_PRECONDITION
POLICY_LATENCY
POLICY_STALENESS
ACTION_DISCONTINUITY
CONTROLLER_TRACKING
CONTACT_DYNAMICS
SIMULATOR_MISMATCH
RUNTIME_FAILURE
MAPPING_OR_INDEXING
SAFETY_LIMIT
INSTRUCTION_CHANGE
```

A failure may have contributing categories, but one primary category is required for attribution.

---

# 27. Makefile and entry points

Provide root targets:

```makefile
make install-local
make test
make source-audit
make exp01
make exp02
make exp03
make exp04
make exp05
make exp06
make exp07-smoke
make exp08-audit
make exp09
make exp10-plan
make collect-results
make replay RUN=<path>
make remote-check
make remote-exp07
make remote-exp08
```

Every experiment must also expose one Python command with explicit config:

```bash
python -m experiments.01_policy_control.run --config configs/base.yaml
```

Commands must support:

```text
--seed
--output-dir
--dry-run
--max-episodes
--headless
```

Remote scripts must be bounded, resumable, and retrieve artifacts automatically.

---

# 28. Codex worktree rules

Every autonomous Codex agent must follow these rules.

1. Work in the assigned worktree only.
2. Do not create another Git repository.
3. Do not modify sibling worktrees.
4. Do not merge into `main`.
5. Do not push unless `ALLOW_PUSH=1`.
6. Do not reset, clean, or discard user changes.
7. Keep experiment-specific logic under its experiment directory.
8. Do not create broad shared abstractions merely because another experiment might need them.
9. If a shared contract appears wrong, document it in `INTERFACE_FINDINGS.md` and make the smallest backward-compatible change required.
10. Use public code only through the source policy and lockfile.
11. Pin all upstream revisions.
12. Preserve attribution and licenses.
13. Do not download large checkpoints by default.
14. Do not install Isaac Sim on macOS.
15. Do not contact a physical Unitree.
16. Do not expose an inference server publicly.
17. Use deterministic seeds.
18. Run tests before and after a change.
19. Never fabricate results.
20. Mark unavailable results explicitly:

```text
NOT_RUN
BLOCKED_LOCAL_PLATFORM
BLOCKED_REMOTE_GPU
BLOCKED_SIMULATOR
BLOCKED_DATA
BLOCKED_LICENSE
FAILED_GATE
```

21. A negative result is acceptable.
22. Stop expanding implementation once the bounded claim is answered.
23. Make atomic commits when Git identity is configured.
24. At completion list exact changed files, commands, tests, and results.

---

# 29. Interface-promotion process

Experiment branches do not merge their entire local design into `reflect/`.

At experiment completion:

1. identify any interface that was required by measured results;
2. propose the smallest promotion commit;
3. include compatibility tests;
4. document alternatives rejected;
5. cherry-pick or merge the promotion separately from experiment implementation;
6. keep toy environments, plots, and task-specific code local.

Examples of promotable artifacts:

- timestamp/expiry semantics for `ActionChunk`;
- a small `RecoveryDecision` enum;
- provenance/staleness fields on `ObjectBelief`;
- rollout event schema;
- world-model candidate prediction schema.

Examples that should usually remain local:

- 2-link arm environment;
- hand-tuned cost weights;
- synthetic five-room building;
- one PPO reward;
- plotting scripts;
- experiment-specific thresholds.

---

# 30. Program execution order

## Parallel first wave

Run independently:

```text
00 source audit
01 policy/control boundary
04 memory decomposition
05 semantic twin
06 world-model candidate ranking
```

## Dependent second wave

```text
01 → 02 action chunks
02 → 03 recovery
06 → optional world-model authority
06/07/08 → R1-specific predictive/specialist branches
```

## Integration wave

```text
validated 02 + 03 + 04 + 05 + optional 06/07
                    ↓
              09 mini-Reflect
                    ↓
              08 R1 transfer
```

Experiment 08 can begin its official baseline and mapping audit in parallel, but custom hierarchy transfer should consume selected interfaces rather than inventing them.

## Deferred deployment wave

```text
09 stable perceptive hierarchy
        +
remote Isaac host
        +
authorized site capture
        ↓
10 R2S2R
```

---

# 31. Stop/go decision tree

```text
Does synthetic slow-policy → controller execution work?
    no  → fix contract; do not add VLA
    yes
     ↓
Does receding/async execution beat open loop under latency?
    no  → retain simplest protocol
    yes → promote protocol
     ↓
Does hierarchical recovery beat always-local/always-agent?
    no  → simplify recovery
    yes → promote event contract
     ↓
Does persistent memory reduce stale/wrong decisions?
    no  → retain stateless/latest observation baseline
    yes → promote only useful memory layers
     ↓
Does semantic/twin layering improve dynamic planning?
    no  → keep simpler graph
    yes → preserve layer separation
     ↓
Does learned prediction beat heuristic candidate ranking?
    no  → no runtime world-model authority
    yes → test critic/selector, not direct planner first
     ↓
Does specialist skill beat strong reactive baseline?
    no  → no heterogeneous skill cost
    yes → dispatch through typed SkillSpec
     ↓
Do contracts transfer to R1 simulation?
    no  → identify embodiment-specific seam
    yes → integrate; still no autonomous hardware
```

---

# 32. Final architecture decisions

At program completion create `docs/ARCHITECTURE_DECISIONS.md` and make one evidence-based choice in each category.

## Mission-agent output

```text
FREE_FORM_LANGUAGE
SEMANTIC_GOAL
STRUCTURED_SKILL_SPEC
BEHAVIOR_PROGRAM
```

## General-policy output

```text
JOINT_ACTIONS
JOINT_ACTION_CHUNK
EEF_ACTION_CHUNK
MPC_GOAL
BOUNDED_RESIDUAL
STRUCTURED_SUBGOAL
```

## Controller ownership

State what remains owned by:

- action executor;
- trajectory generator;
- MPC/IK;
- PID/impedance;
- whole-body controller;
- hardware controller.

## Recovery ownership

Give measured triggers for:

```text
CONTINUE
REFRESH
RETRIGGER
ESCALATE
ABORT
```

## Memory composition

Select required stores:

```text
FAST_STATE
EPISODIC_LOG
SEMANTIC_GRAPH
GEOMETRIC_TWIN
EMBEDDING_INDEX
LEARNED_LATENT
```

## Digital-twin composition

State what belongs in:

```text
IFC/BIM
USD/GEOMETRY
TOPOLOGICAL_GRAPH
SEMANTIC_GRAPH
LIVE_BELIEF
EVENT_LOG
```

## World-model role

Choose exactly one:

```text
DO_NOT_USE
OFFLINE_ANALYSIS_ONLY
SHADOW_OBSERVER
FAILURE_CRITIC
CANDIDATE_SELECTOR
LATENT_SUBGOAL_MODEL
DIRECT_PLANNER
```

## Embodiment transfer

List:

- shared contracts transferred unchanged;
- edge adapters;
- R1-specific controller assumptions;
- unresolved sim-to-real risks;
- physical deployment blockers.

---

# 33. Initial research and implementation index

Create `references/papers.md` with this categorized reading/index list. Verify titles, publication versions, and current code links when the source audit runs.

## Hierarchical autonomy and agent/skill boundaries

- Flexion Reflect v0 — <https://flexion.ai/news/flexion-reflect-v0-towards-generalizable-robot-autonomy>
- Flexion Reflect v1 — <https://flexion.ai/news/flexion-reflect-v1.0>
- SayCan — <https://say-can.github.io/>
- Code as Policies — <https://code-as-policies.github.io/>
- VoxPoser — <https://voxposer.github.io/>
- Inner Monologue — <https://inner-monologue.github.io/>

Use these to study agent-to-skill/tool boundaries, affordance grounding, verification feedback, and semantic replanning. Do not treat them as direct motor-runtime implementations.

## Action chunks and reactive execution

- ACT: Learning Fine-Grained Bimanual Manipulation with Low-Cost Hardware — <https://arxiv.org/abs/2304.13705>
- Real-Time Execution of Action Chunking Flow Policies — <https://arxiv.org/abs/2506.07339>
- ACT code — <https://github.com/tonyzhaozh/act>
- LeRobot async/RTC code — <https://github.com/huggingface/lerobot>
- OpenPI action broker/client — <https://github.com/Physical-Intelligence/openpi>

## Classical and predictive control

- MuJoCo MPC — <https://github.com/google-deepmind/mujoco_mpc>
- STORM: An Integrated Framework for Fast Joint-Space Model-Predictive Control for Reactive Manipulation — <https://proceedings.mlr.press/v164/bhardwaj22a.html>
- cuRobo — <https://github.com/NVlabs/curobo>
- MoveIt 2 — <https://github.com/moveit/moveit2>
- ros2_control — <https://github.com/ros-controls/ros2_control>

## Recovery and orchestration

- BehaviorTree.CPP — <https://github.com/BehaviorTree/BehaviorTree.CPP>
- Nav2 — <https://github.com/ros-navigation/navigation2>
- Reflect v1 recovery discussion — <https://flexion.ai/news/flexion-reflect-v1.0>
- Inner Monologue — <https://inner-monologue.github.io/>

## Memory and spatial semantics

- 3D Dynamic Scene Graphs — <https://arxiv.org/abs/2002.06289>
- Hydra: A Real-time Spatial Perception System for 3D Scene Graph Construction and Optimization — <https://arxiv.org/abs/2201.13360>
- Hydra code — <https://github.com/MIT-SPARK/Hydra>
- Spark-DSG — <https://github.com/MIT-SPARK/Spark-DSG>
- Kimera — <https://github.com/MIT-SPARK/Kimera>
- ConceptGraphs — <https://arxiv.org/abs/2309.16650>
- ConceptGraphs code — <https://github.com/concept-graphs/concept-graphs>

## Digital twins and R2S2R

- Flexion/Niantic Spatial/NVIDIA R2S2R — <https://flexion.ai/news/niantic-spatial-flexion-and-nvidia-closing-the-sim2real-gap-for-humanoids>
- OpenUSD — <https://github.com/PixarAnimationStudios/OpenUSD>
- IfcOpenShell — <https://github.com/IfcOpenShell/IfcOpenShell>
- Isaac Sim — <https://github.com/isaac-sim/IsaacSim>
- Isaac Lab — <https://github.com/isaac-sim/IsaacLab>

## Learned world models and predictive action systems

- TD-MPC2: Scalable, Robust World Models for Continuous Control — <https://arxiv.org/abs/2310.16828>
- TD-MPC2 code — <https://github.com/nicklashansen/tdmpc2>
- DINO-WM: World Models on Pre-trained Visual Features enable Zero-shot Planning — <https://arxiv.org/abs/2411.04983>
- DINO-WM code — <https://github.com/gaoyuezhou/dino_wm>
- V-JEPA 2 — <https://arxiv.org/abs/2506.09985>
- V-JEPA2 code — <https://github.com/facebookresearch/vjepa2>
- DayDreamer: World Models for Physical Robot Learning — <https://arxiv.org/abs/2206.14176>
- LaWAM code/project — <https://github.com/RLinf/LaWAM>
- Diffusion Policy — <https://diffusion-policy.cs.columbia.edu/>
- Diffusion Policy code — <https://github.com/real-stanford/diffusion_policy>

## Unitree embodiment

- Unitree RL MJLab — <https://github.com/unitreerobotics/unitree_rl_mjlab>
- Unitree MuJoCo — <https://github.com/unitreerobotics/unitree_mujoco>
- Unitree SDK2 — <https://github.com/unitreerobotics/unitree_sdk2>
- UnifoLM VLA — <https://github.com/unitreerobotics/unifolm-vla>
- UnifoLM World Model Action — <https://github.com/unitreerobotics/unifolm-world-model-action>

---

# 34. Maturity and evidence labels

Every external component and internal result receives one label:

```text
PRODUCTION_DEPLOYED_DOCUMENTED
PRODUCTION_SHAPED_REFERENCE
REAL_HARDWARE_RESEARCH
SIMULATION_RESEARCH
LOCALLY_REPRODUCED_M2
REMOTELY_REPRODUCED_GPU
LOCALLY_INTEGRATED
UNITREE_R1_SIM_REPRODUCED
PHYSICAL_R1_NOT_VALIDATED
UNVERIFIED
```

Do not call a project production-ready solely because it has a polished repository or real-robot video.

`docs/MATURITY_LEDGER.md` must record:

- project/component;
- evidence label;
- evidence source;
- supported embodiment/task;
- license;
- compute requirements;
- local reproduction status;
- known failure modes;
- role in this program.

---

# 35. Autonomous-run completion report

Each worktree produces `OVERNIGHT_REPORT.md` or `RUN_REPORT.md` containing:

## Executive result

What works, what failed, and whether the claim was supported.

## Environment

- workspace;
- branch;
- upstream/source SHAs;
- machine;
- dependency versions.

## Commands

Exact commands executed.

## Tests

Pass/fail/skip counts and failures.

## Results

Only actual metrics, with artifact paths.

## Public-source use

- repositories fetched;
- selected files/directories;
- license/provenance status;
- local adaptations;
- upstream issues encountered.

## Interface findings

What should be promoted, adapted, or discarded.

## Blockers

Use explicit status values.

## Highest-value next action

One concrete command or bounded experiment.

## Safety

Confirm:

- no physical motor messages;
- no non-loopback deployment connection;
- no public inference server;
- no secrets committed;
- no unreviewed large model downloaded.

---

# 36. Program success criterion

The program succeeds when it can draw this architecture with experimentally justified arrows:

```text
mission
  │
  ▼
semantic planner
  │ experimentally selected contract
  ▼
SkillSpec
  │
  ▼
general policy / specialist skill
  │ experimentally selected representation
  ▼
ActionChunk / MPC goal / residual
  │ experimentally selected temporal protocol
  ▼
reactive executor
  │ experimentally selected recovery triggers
  ▼
trajectory / MPC / IK
  │
  ▼
PID / impedance / whole-body control
```

with an independently justified world-state stack:

```text
recent state
+
episodic events
+
semantic object graph
+
geometric/topological twin
+
live confidence/provenance
```

and one evidence-based decision about whether learned future prediction belongs as:

```text
nothing
an offline diagnostic
a shadow observer
a failure critic
a candidate selector
a latent subgoal model
a direct planner
```

The desired output is not one impressive demo. It is a set of defensible decisions about:

- what each layer knows;
- what each layer emits;
- the clock rate of each layer;
- what wakes each layer;
- what persists between calls;
- where learned prediction helps;
- which contracts survive Unitree R1 transfer;
- what remains too unsafe or immature for physical deployment.

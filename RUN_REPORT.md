# P1 Run Report

## Executive result

The deterministic simulation-only shared rollout harness passed the bounded P1 gate.

## Evidence base

- Implementation/evidence-base Git SHA: `d24ab0d7c0c1ae8779f5430c50f98eb0d41c76b7`
- Report provenance: commands below were rerun against the current checkout; the SHA
  intentionally names the pre-report implementation commit because a report cannot
  contain the hash of a commit that includes itself.
- Durable state: `p1: complete`, `p2: in_progress`, `current_pass: 2`.
- Working tree observed during report generation: `clean`

## Lock and tests

```text
UV_CACHE_DIR=.cache/uv uv lock --check
(no output; exit 0)

UV_CACHE_DIR=.cache/uv uv run pytest -q
........................................................................ [ 33%]
........................................................................ [ 67%]
......................................................................   [100%]
214 passed in 2.33s
```

## Fixture and replay

```text
python scripts/write_p1_fixture.py --output-dir <TEMP_ROOT_A>
<TEMP_ROOT_A>/p1-fixture

python -m reflect.rollout replay <TEMP_ROOT_A>/p1-fixture
{"event_count":6,"final_skill_state":"succeeded","frame_count":6,"rollout_id":"p1-fixture"}

python scripts/write_p1_fixture.py --output-dir <TEMP_ROOT_B>
<TEMP_ROOT_B>/p1-fixture
```

The two independently generated fixture directories had identical SHA-256 hashes
for every file:

- `actions.parquet`: `0b475b6ea0781ecb1dbd3fb98acc1228bd0c13aad0da880dae60b4989f75332b`
- `config.json`: `0978bd7772089464e74be70a78c93e434216650e1737193d688485634df3224c`
- `events.jsonl`: `a76192575c3dcadf8f84da30459b9647ee69bad5bf0d13a382019aedbe7a60fe`
- `metadata.json`: `ebd639fd66627cc03404aee790f43adcb16950d0c6bded4fb32cec01c527a790`
- `metrics.json`: `14dc951baf7efec7c9c14b7e759a5c9b0535c249d23e3738855f5873ed88a6fc`
- `observations.npz`: `8cc1610201cf96b200be98c0a98c54b16bcec47c3510c1f3eea6ac8a7d4842b6`
- `summary.md`: `d7cf34d2bad567048f3e0562457bd8c7058bc4446a3697426203c9fbf274bc12`

## Safety checks

```text
make safety-check
{"simulation_only": true, "remote_enabled": false}

PHYSICAL_DEPLOYMENT_ALLOWED=true REFLECT_REMOTE_ENABLED=0 make safety-check
exit 2: make: *** [safety-check] Error 1

PHYSICAL_DEPLOYMENT_ALLOWED=true python scripts/write_p1_fixture.py --output-dir <TEMP_ROOT_PHYSICAL>
exit 1: reflect.safety.SafetyViolation: physical deployment is disabled for this program
```

The physical fixture negative control failed before `<TEMP_ROOT_PHYSICAL>/p1-fixture`
was created. Remote execution remained disabled.

## Repository boundary

- `git diff --check`: exit 0, no whitespace errors.
- Forbidden tracked-path query: empty.
- Unapproved files larger than 100 MiB: none.

## Scope and limitations

- This is deterministic synthetic artifact/replay evidence; no physics was run.
- Replay reduces saved events and does not rerun physics.
- No network or external source was used by the fixture or replay commands.
- P2 source auditing and empirical experiments have not run.
- The added `scripts/write_p1_report.py` is a documented plan-file-list omission,
  authorized as the narrow mechanism needed to regenerate this report.
- `tests/test_run_state.py` was narrowly updated after the mandated manifest
  transition exposed its stale P1-in-progress assertion; no other run-state test
  was changed.

## Highest-value next bounded action

Run the P2 public-source audit and freeze the approved source registry before any
experiment code or empirical claims.

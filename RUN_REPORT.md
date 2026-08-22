# P1 Run Report

## Executive result

The deterministic simulation-only shared rollout harness passed the bounded P1 gate.

## Evidence base

- Implementation/evidence-base Git SHA: `9c31d48ed55242bf54061bc485aa28799d942717`
- Report provenance: commands below were rerun against the current checkout; the SHA
  intentionally names the pre-report implementation commit because a report cannot
  contain the hash of a commit that includes itself.
- Durable state: `p1: complete`, `p2: in_progress`, `current_pass: 2`.
- Working tree observed during report generation: `clean`
- Fixture provenance mode: `repository`.
- Fixture Git SHA: `9c31d48ed55242bf54061bc485aa28799d942717`.
- Fixture source registry artifact: `references/bootstrap-tools.yaml`
  with SHA-256 `ecb46f43ae4ed7e1006570eecbc4c5632809ca92719452b6d2c3ecc2be476151`.
- Fixture model hashes: `{}`
  because no model or checkpoint was used.

## Lock and tests

```text
UV_CACHE_DIR=.cache/uv uv lock --check
stdout:
(empty)
stderr:
Resolved 10 packages in 3ms
exit: 0

UV_CACHE_DIR=.cache/uv uv run pytest -q
........................................................................ [ 32%]
........................................................................ [ 65%]
........................................................................ [ 98%]
....                                                                     [100%]
220 passed in 4.79s
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
- `config.json`: `44089c047cb48ec317b59415a85d36665e2b31bfe0c1033970be397028f4dad2`
- `events.jsonl`: `79f6accce88b8d4592cd2bee8a67c4faf2a243581ba6a2c11134bf4f5165dab1`
- `metadata.json`: `daab3f5b9dd560eaeff85915c4066db7f9615324ee9b12792b0ac973475de2a2`
- `metrics.json`: `14dc951baf7efec7c9c14b7e759a5c9b0535c249d23e3738855f5873ed88a6fc`
- `observations.npz`: `8cc1610201cf96b200be98c0a98c54b16bcec47c3510c1f3eea6ac8a7d4842b6`
- `summary.md`: `973fb76a10691256c01ee34e4f561331bd0e7d91856d79ae01ca66506a124bd1`

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

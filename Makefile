UV := UV_CACHE_DIR=.cache/uv uv
P1_OUTPUT_DIR ?= results/bootstrap
P1_FIXTURE_METADATA := $(P1_OUTPUT_DIR)/p1-fixture/metadata.json

.PHONY: install-local test safety-check p0-report p1-fixture p1-check replay source-metadata-audit source-audit exp01

install-local:
	$(UV) sync --locked --python 3.11.13

test:
	$(UV) run pytest -q

safety-check:
	$(UV) run python -m reflect.safety check

p0-report:
	$(UV) run python scripts/write_p0_report.py

$(P1_FIXTURE_METADATA):
	$(UV) run python scripts/write_p1_fixture.py --output-dir $(P1_OUTPUT_DIR) --reuse-existing

p1-fixture: $(P1_FIXTURE_METADATA)
	$(UV) run python scripts/write_p1_fixture.py --output-dir $(P1_OUTPUT_DIR) --reuse-existing

p1-check: test p1-fixture
	$(UV) run python -m reflect.rollout replay $(P1_OUTPUT_DIR)/p1-fixture

replay:
	@test -n "$(RUN)" || (echo "RUN is required" >&2; exit 2)
	$(UV) run python -m reflect.rollout replay "$(RUN)"

source-metadata-audit:
	$(UV) run python scripts/fetch_reference.py --all-metadata-only
	$(UV) run python scripts/audit_references.py --require-complete

source-audit:
	$(UV) run python scripts/audit_references.py --require-complete
	$(UV) run python -m experiments.00_source_audit.run --config experiments/00_source_audit/configs/base.yaml --headless

exp01:
	@test -n "$(SHARD)" || { echo "SHARD is required" >&2; exit 2; }
	MUJOCO_GL=disable UV_CACHE_DIR=.cache/uv uv run python -m experiments.01_policy_control.run --config experiments/01_policy_control/configs/base.yaml --p3-gate experiments/01_policy_control/configs/p3-gate.yaml --phase pilot --manifest experiments/01_policy_control/protocol/pilot-r1/base-manifest.json --output-dir experiments/01_policy_control/results --headless --shard-id "$(SHARD)" --max-episodes 3

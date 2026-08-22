UV := UV_CACHE_DIR=.cache/uv uv

.PHONY: install-local test safety-check p0-report p1-fixture p1-check replay

install-local:
	$(UV) sync --locked --python 3.11.13

test:
	$(UV) run pytest -q

safety-check:
	$(UV) run python -m reflect.safety check

p0-report:
	$(UV) run python scripts/write_p0_report.py

p1-fixture:
	$(UV) run python scripts/write_p1_fixture.py --output-dir results/bootstrap

p1-check: test p1-fixture
	$(UV) run python -m reflect.rollout replay results/bootstrap/p1-fixture

replay:
	@test -n "$(RUN)" || (echo "RUN is required" >&2; exit 2)
	$(UV) run python -m reflect.rollout replay "$(RUN)"

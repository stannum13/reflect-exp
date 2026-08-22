UV := UV_CACHE_DIR=.cache/uv uv

.PHONY: install-local test safety-check p0-report replay

install-local:
	$(UV) sync --locked --python 3.11.13

test:
	$(UV) run pytest -q

safety-check:
	$(UV) run python -m reflect.safety check

p0-report:
	$(UV) run python scripts/write_p0_report.py

replay:
	@test -n "$(RUN)" || (echo "RUN is required" >&2; exit 2)
	$(UV) run python -m reflect.rollout replay "$(RUN)"

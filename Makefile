UV := UV_CACHE_DIR=.cache/uv uv

.PHONY: install-local test safety-check p0-report

install-local:
	$(UV) sync --locked --python 3.11.13

test:
	$(UV) run pytest -q

safety-check:
	PHYSICAL_DEPLOYMENT_ALLOWED=false REFLECT_REMOTE_ENABLED=0 $(UV) run python -m reflect.safety check

p0-report:
	$(UV) run python scripts/write_p0_report.py

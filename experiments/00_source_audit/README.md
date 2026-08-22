# Experiment 00 — Source compatibility

This experiment converts the immutable P2 source lock and bounded operation fragments
into deterministic compatibility, license, source-map, maturity, and interface reports.
It performs no broad build, model download, viewer launch, remote execution, or physical
deployment.

Dry-run the command surface:

```bash
uv run python -m experiments.00_source_audit.run \
  --config experiments/00_source_audit/configs/base.yaml --dry-run --headless
```

The live audit remains gated on a complete P2 lock and the frozen operation manifest.

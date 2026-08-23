# Reproducibility Fix Report

## Defect

The committed reconstruction script imported Pillow to rasterize PNG figures. Pillow was available in the authoring interpreter but was not a declared project dependency, so the project environment failed with `ModuleNotFoundError: No module named 'PIL'`.

## Fix

`reconstruct_analysis.py` now uses only the Python standard library. It reconstructs canonical CSV/JSON data, `RESULTS.md`, the evidence artifacts, and both SVG figures. The existing publication PNGs remain frozen, non-authoritative companions: they are hash-authenticated when present but are intentionally excluded from clean reconstruction and from its byte-stability claim.

## Verification

Red test (project environment): `uv run pytest results/indicative-twin-hierarchy-synthesis/test_reconstruct.py -q` failed before the fix because the reconstruction subprocess imported Pillow.

Green test (project environment): the same command passed after the fix. The test verifies byte-for-byte agreement across two absent clean reconstruction targets for canonical data, SVG, report, evidence manifest, and checksum file, and verifies no PNG is produced by a clean reconstruction.

`SHA256SUMS` authenticates every substantive artifact in the publication directory, including the retained PNG companions and the evidence manifest. The canonical reconstruction claim applies only to the standard-library outputs described above.

# Verification evidence — 2026-11-08

## End-to-end result

**PASS**: the synthetic source PDF completed parsing → metric geometry → headless Blender → previews/clay → geometric QA → final Cycles renders → GLB optimization/validation → production website build. The run ended with `pipeline_complete`, exit code 0 and `outputs/demo-001/run-status.json` containing `passed: true`.

Actual final command (a clean temporary dependency installation avoided slow reads in the existing workspace dependencies; source files and lockfile were identical):

```sh
PYTHONPYCACHEPREFIX=/tmp/aav-pycache /tmp/aav-validation-env/bin/python -m pipelines.run \
  --input outputs/demo-001/original.pdf --output outputs/demo-001 --clay \
  --site-root /tmp/aav-site-dependencies \
  --site-assets /tmp/aav-site-dependencies/public/project
```

The original synthetic PDF was generated with `python -m pipelines.pdf.synthetic`. The standard fresh-checkout equivalent is:

```sh
uv sync --locked
npm --prefix site ci
uv run python -m pipelines.run --demo --output outputs/demo-001 --clay --site-assets site/public/project
```

`--site-root` is an optional frontend checkout override, not a production dependency. Built assets and generated project files were copied back into `site/dist/` and `site/public/project/` for local review.

## Automated checks

| Check | Actual result |
| --- | --- |
| pytest | 27 passed in 1.50 s; five upstream PyMuPDF/SWIG deprecation warnings |
| Ruff | All checks passed |
| Node model tests | 2 passed; preservation of bounds/identifiers and rejection of corrupt GLB |
| TypeScript + Vite | Build passed, 592 modules; final build 1.67 s |
| Geometry/image QA | 113 checks passed; default tolerance 0.002 m |
| Maximum measured bounding-coordinate error | 0.0000002371 m in this controlled fixture |
| Orthographic wall mask overlap | IoU 0.9010523, threshold 0.90; metric mesh checks are stricter |
| Khronos glTF Validator | 0 errors, 0 warnings |
| Three.js GLTFLoader | 13 meshes, 504 vertices; expected identifiers retained |
| GLB optimization | 24,740 → 21,836 bytes; lossless resource deduplication only |
| Render device | Apple M4 GPU, Metal, Blender 4.5.9 LTS |
| Final images | Exterior/interior/axonometric, 960 × 720, 64 Cycles samples |
| Preview and clay | Three views each, 480 × 360, 12 samples |

The tests cover scanned PDF candidate extraction and review blocking, calibration tampering, annotations without drawn evidence, invalid polygons/heights/hosts, missing and duplicate IDs, unverified geometry, source digest/coordinate mismatch, topology/volume tampering and the mocked Responses API contract.

## Browser review

Actual in-app browser at `http://127.0.0.1:5174/` loaded the production GLB. Verified model-loaded state, visible nonblank WebGL rendering, all four gallery image elements loaded at intrinsic width 960, wall visibility, floor selection, reset activated with Enter and no browser errors/warnings in the inspected log. A real orthographic camera overzoom bug was found and corrected; the fixed view was visually inspected.

At 390 × 844, the model remained visible and the page had no horizontal overflow. The roof toggle is disabled because the test drawing specifies no roof. Screenshot evidence: `outputs/browser/mobile.png`. The initial missing-manifest error recovered through the retry control after assets became available. This was a browser smoke test, not a comprehensive cross-browser suite. A later browser-control session interruption prevented additional screenshot capture; it did not invalidate the completed checks.

## Reproducibility and limitations

The successful run regenerated existing output from the same PDF without duplicate objects. `provenance.json` records the source/geometry hashes, code hashes, revision, lockfiles, render settings and output hashes. Generated artifacts and logs are intentionally outside Git; this report preserves their measured results.

The optional MCP test independently passed create/read/move/save/safe-mode checks (see BLENDER_MCP.md). Actual OpenAI API connectivity remains **untested** because no API key was supplied. Arbitrary drawing semantics and scanned-to-final geometry are **not automatically validated**: they require human-reviewed geometry. CPU code path is implemented but the full run used Metal. Texture-rich photorealistic interiors, joinery and furniture are not claimed by the simplified pavilion demo.

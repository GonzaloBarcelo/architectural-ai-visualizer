# MVP verification — 2026-11-09

| Check | Result |
| --- | --- |
| pytest | 74 passed (new: approve flow, description upload/limit, missing key, selection cache, tolerant furniture, room naming, viewpoint, finishes conversion/cache) |
| Ruff check / format | clean |
| Node GLB tests | 2 passed |
| TypeScript + Vite | build passed |
| Real PDF via HTTP | EA_01_MOD_1.pdf: interpretation 1.1 s (cache), approve → Blender 88.6 s, 518/518 QA, 3 renders + GLB returned 200 |
| UI | Headless Chrome screenshots of upload, review and results inspected; headless minimum width is 500 px, so a true 390 px check was not possible |

The material-description path was tested with mocked OpenAI responses and a hand-written palette rendered in Blender; no live finishes call was made.

---

# Real PDF conceptual run — 2026-11-09

EA_01_MOD.pdf received two live OpenAI responses. First call used 5,284 tokens; second, vector-anchored call used 9,213 tokens. Both failed review: incorrect geometry, units and scale. They are NOT successful automatic reconstruction evidence.

A separately identified assisted correction used filled vector polygons from the PDF, a printed 1:50 scale cross-checked against the 3.36 m dimension, 2.7 m assumed wall height, and an approximate slab. It retained facade gaps without modeling lintels, sills or joinery; balcony boundaries and interior camera region are conceptual. No claim of complete room reconstruction or architectural accuracy.

Real Blender run 2066bd98e6994019a2092a8f4f35b418 succeeded: 383 QA checks, three renders, GLB with 53 meshes/1,404 vertices, Khronos 0 errors/0 warnings and successful Three.js load. QA verifies consistency with the corrected input, not fidelity of OpenAI interpretation. Private source/results remain excluded from Git. The original AI response is preserved separately from edited geometry and can be compared in the browser. No deployment.

---

# Web workflow verification — 2026-11-09

**PASS**: upload PDF in the actual browser → review scale/floor/elements → validate → generate with real Blender → load newly generated renders and GLB in the same page. No deployment or publication.

| Boundary / check | Actual evidence |
| --- | --- |
| Python suite | 55 passed in 3.74 s; six upstream deprecation warnings (PyMuPDF/SWIG and Starlette TestClient/httpx) |
| Ruff | All checks passed |
| Node GLB tests | 2 passed |
| TypeScript / Vite | Production build passed, 594 modules |
| Browser upload | Synthetic original.pdf uploaded via the file chooser; actual local API and PDF extraction |
| Review gate | Generation disabled before confirmation; clearing W1 height produces `Falta una altura positiva, en metros` |
| Saved state | Restored the confirmed draft after server restart/page reload; retry succeeded |
| Full browser generation | Project c59064b78b7545d6aaa108c3e3d6af57, run f82d29f75b85471999a5786d3531fca9: succeeded |
| Geometry / image QA | All 110 checks passed; mask IoU 0.9998794, unchanged minimum 0.90; metric tolerance remains 0.002 m |
| Khronos / Three.js | 0 validator errors, 0 warnings; 13 meshes, 504 vertices, source IDs preserved |
| Renders | Actual exterior, interior, axonometric; 960 × 720, 64 Cycles samples |
| Results in browser | New project API URLs requested with 200; `data-model-loaded=true`; four gallery image elements have intrinsic width 960; no errors/warnings in inspected console |
| Layout | Current 658 px viewport has document width 658, no horizontal overflow; rendered GLB visually inspected |
| General-PDF path | A second synthetic PDF without the special annotated convention starts with no entities or scale; generation returns 422 before review |
| Manual draft + real renderer | Explicitly supplied the second test plan's known scale, floor, four walls and slab through the review API; two renders and valid GLB generated, 45 QA checks pass, IoU 0.9998538 |
| No rooms | The manual plan has no rooms; exterior/axonometric served successfully, no invented interior render (404) |

The browser test exercised the complete UI with the annotated synthetic fixture. The second general-PDF test exercised the real HTTP API and Blender with explicitly entered test measurements; it was not an automatic semantic interpretation or a real client plan. Rendering used Blender 4.5.9 / Metal on this Mac. Screenshot: `outputs/browser/web-flow.png`. Local logs/state: `outputs/web-tests.log`, `outputs/web-server.log`, `outputs/web-projects/`, `outputs/web-generic-smoke/result.json`; generated/private artifacts remain ignored by Git.

The first browser attempt was blocked by orthographic QA (IoU 0.88696). Investigation found display-gamma conversion and denoising expanding thin mask edges. The QA render now uses Raw linear output with denoising disabled; reference rasterization samples pixel centres. The fix retains the original IoU threshold and all independent metric checks. The failed run remains preserved alongside the successful retry.

Additional regression tests cover incomplete/unconfirmed geometry, thickness mismatch, stale revisions, duplicate running jobs, renderer failure/retry, interrupted jobs on startup, persisted review, cross-origin/Host rejection, corrupt files, artifact allowlisting, stale result invalidation and distinct result URLs on regeneration. API unit tests inject an explicit fake renderer; the two end-to-end runs above use real Blender.

Validation used fresh locked dependencies in `/tmp/aav-validation-env` and `/tmp/aav-site-dependencies` to avoid unusually slow existing workspace dependency reads. Identical frontend sources/build are copied back to `site/dist`. The normal fresh-checkout commands are documented in README. Live OpenAI vision, multi-floor web projects and broad real-plan accuracy remain outside these verified results.

---

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

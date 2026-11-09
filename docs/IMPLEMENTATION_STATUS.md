# Extension: conceptual OpenAI interpretation

Web opt-in PDF interpretation through Responses structured outputs is implemented. Server-side key required; default model gpt-4.1, configurable via OPENAI_MODEL. Proposed contours/dimensions and assumptions enter the editor; explicit conceptual acceptance preserves inferred provenance while allowing generation. All geometric QA remains enabled. No image enhancement endpoint. No publication.

Validation: 59 Python tests pass (including mocked OpenAI proposal and strict-versus-conceptual gating), TypeScript/Vite build passes. Live OpenAI interpretation and EA_01_MOD.pdf reconstruction remain unverified because OPENAI_API_KEY is absent. Earlier claims of exclusively local processing apply only when the user does not choose OpenAI interpretation.

---

# Implementation status — 2026-11-09

A working controlled first iteration is delivered. The full synthetic pipeline ran successfully through the production website build. The general-purpose interpretation of new drawings remains review-dependent. Git branch: `codex/architectural-pipeline`.

| Step | Scope | Status | Executed evidence and limitations |
| --- | --- | --- | --- |
| 1 | Environment | COMPLETED | macOS arm64, Python 3.12.16, uv 0.13.7, Node 24.13.0, Git/gh/Codex; official checksum-verified Blender 4.5.9 LTS; Metal GPU detected in outputs/environment.json |
| 2 | OpenAI access | BLOCKED | Codex authenticated through ChatGPT; .env.example and Responses adapter implemented/tested with mock. Live API request awaits OPENAI_API_KEY; no invented connectivity claim |
| 3 | Repository | COMPLETED | Existing empty GitHub repo linked; feature branch, AGENTS.md, private output exclusions, atomic commits |
| 4 | Python dependencies | COMPLETED | uv.lock; clean locked installation; 55 pytest tests passed and Ruff clean |
| 5 | Skills | COMPLETED | Six original project skills; all passed quick_validate; official resources/provenance in REFERENCES.md |
| 6 | Blender MCP | COMPLETED | Pinned optional package 2.2.7, isolated real create/measure/move/save/safe-mode smoke passed; workspace config prepared. Native tools require reopening a trusted Codex session and starting the GUI addon |
| 7 | PDF geometry | COMPLETED | Vector/text/annotation extraction, raster candidates and strict source-linked schema; synthetic PDF yields 6 walls, 3 rooms, 3 doors, 3 windows. Arbitrary/scanned semantics require reviewed geometry; live vision untested |
| 8 | Blender modeling | COMPLETED | Headless scene.blend regenerated; measured mesh matches source within 0.002 m tolerance; no invented roof |
| 9 | Rendering | COMPLETED | Clay/preview/final Cycles presets run; 3 final 960×720 WebP renders inspected, settings recorded. Materials/opening solids simplified |
| 10 | QA | COMPLETED | 113 metric/mesh/orthographic/image checks passed, negative tampering tests pass; not a construction certification or exhaustive collision solver |
| 11 | GLB | COMPLETED | 24,740→21,836 bytes lossless optimization; Khronos 0 errors/warnings; Three.js loads 13 source-linked meshes |
| 12 | Website | COMPLETED | React/TS/R3F/Drei + local FastAPI PDF upload, visual review and background Blender jobs; actual browser full-flow passed; production build passed |
| 13 | Sites | COMPLETED | Historical static viewer saved as version 1; current web API workflow runs locally only. No deployment or publication. Local review on 127.0.0.1:5174 |

## Web workflow completion

Upload and extraction, page/scale review, manual contour editing, numeric properties, per-element confirmations, missing-data validation, progress polling, revision-bound generation, local persistence and recovery, render gallery and GLB downloads are implemented. No measurements are invented for generic PDFs. One page and one floor per web project; room contours are optional and needed for an interior render.

Real browser upload/review/generation produced three renders and a GLB with 110 passing QA checks. A second general-convention test PDF was reviewed through the API and generated two renders/GLB with 45 passing QA checks. Full Python suite: 55 passed; Node: 2 passed; Ruff and TypeScript/Vite passed. The mask gamma/denoising defect discovered in the real run was fixed without relaxing tolerances. See TEST_RESULTS.md for exact evidence and limitations.

The previous evidence below records the initial CLI delivery, followed by this web extension.

## Completion evidence

- `outputs/end-to-end.log`: final `pipeline_complete`, exit 0.
- `outputs/demo-001/run-status.json`: passed.
- `outputs/demo-001/`: original.pdf, evidence, geometry.json, geometry-review.json, scene.blend, three render sets, quality-report.json, model.glb, manifest.json, provenance.json and stage logs.
- `outputs/pytest.log`: 27 passed; Node model tests: 2 passed.
- `outputs/demo-001/site-build.log`: TypeScript/Vite build success.
- `outputs/browser/mobile.png`: actual 390×844 WebGL review.
- `outputs/mcp-smoke/mcp-report.json`: optional MCP operations and safe mode passed.
- `outputs/sites-review.tar.gz`: saved static Sites review archive, no deployment.

Generated artifacts stay outside Git. Summarized results and actual invocation details are preserved in TEST_RESULTS.md. Local cached dependency reads became unusually slow after the interrupted session; final validation used fresh locked Python/Node dependencies in temporary directories, with the same application source. The resulting build is copied back to site/dist.

## Remaining work and next iteration

Provide an OpenAI API key to test live semantic proposals. A real authorized PDF is still needed to evaluate broader plan conventions. The source measurement/entity review interface is now implemented. Future work includes per-page transforms, richer window/door assemblies, reviewed PBR finishes and additional camera controls. CPU end-to-end rendering and broader browser coverage remain additional validation. Cloud orchestration, cloud storage and Agents API workflows are intentionally not implemented. Local persistent project storage is implemented.

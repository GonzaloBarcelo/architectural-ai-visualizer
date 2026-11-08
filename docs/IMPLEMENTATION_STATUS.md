# Implementation status — 2026-11-08

A working controlled first iteration is delivered. The full synthetic pipeline ran successfully through the production website build. The general-purpose interpretation of new drawings remains review-dependent. Git branch: `codex/architectural-pipeline`.

| Step | Scope | Status | Executed evidence and limitations |
| --- | --- | --- | --- |
| 1 | Environment | COMPLETED | macOS arm64, Python 3.12.16, uv 0.13.7, Node 24.13.0, Git/gh/Codex; official checksum-verified Blender 4.5.9 LTS; Metal GPU detected in outputs/environment.json |
| 2 | OpenAI access | BLOCKED | Codex authenticated through ChatGPT; .env.example and Responses adapter implemented/tested with mock. Live API request awaits OPENAI_API_KEY; no invented connectivity claim |
| 3 | Repository | COMPLETED | Existing empty GitHub repo linked; feature branch, AGENTS.md, private output exclusions, atomic commits |
| 4 | Python dependencies | COMPLETED | uv.lock; clean locked installation; 27 pytest tests passed and Ruff clean |
| 5 | Skills | COMPLETED | Six original project skills; all passed quick_validate; official resources/provenance in REFERENCES.md |
| 6 | Blender MCP | COMPLETED | Pinned optional package 2.2.7, isolated real create/measure/move/save/safe-mode smoke passed; workspace config prepared. Native tools require reopening a trusted Codex session and starting the GUI addon |
| 7 | PDF geometry | COMPLETED | Vector/text/annotation extraction, raster candidates and strict source-linked schema; synthetic PDF yields 6 walls, 3 rooms, 3 doors, 3 windows. Arbitrary/scanned semantics require reviewed geometry; live vision untested |
| 8 | Blender modeling | COMPLETED | Headless scene.blend regenerated; measured mesh matches source within 0.002 m tolerance; no invented roof |
| 9 | Rendering | COMPLETED | Clay/preview/final Cycles presets run; 3 final 960×720 WebP renders inspected, settings recorded. Materials/opening solids simplified |
| 10 | QA | COMPLETED | 113 metric/mesh/orthographic/image checks passed, negative tampering tests pass; not a construction certification or exhaustive collision solver |
| 11 | GLB | COMPLETED | 24,740→21,836 bytes lossless optimization; Khronos 0 errors/warnings; Three.js loads 13 source-linked meshes |
| 12 | Website | COMPLETED | React/TS/R3F/Drei, production build passed; actual desktop/mobile WebGL smoke; camera bug corrected and verified |
| 13 | Sites | COMPLETED | Static compatibility verified, source/archive saved as version 1. No deployment, no publication URL. Local review running on 127.0.0.1:5174 |

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

Provide an OpenAI API key to test live semantic proposals. A real authorized PDF is still needed to evaluate broader plan conventions. Add a review interface for source measurements and entities, per-page transforms, richer window/door assemblies, reviewed PBR finishes and additional camera controls. CPU end-to-end rendering and broader browser coverage remain additional validation. Cloud orchestration, persistent storage and Agents API workflows are intentionally not implemented.

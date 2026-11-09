# DWG input — 2026-11-09 (Claude Code, branch `feature/dwg-input`)

Users can now start a project from a **PDF, DWG or DXF**. A DWG is converted to DXF on this machine and read deterministically with ezdxf. **One** OpenAI call (medium reasoning) answers only the doubts the drawing leaves open, by item id. The existing review, approval, Blender, QA and GLB stages are reused unchanged. The PDF flow is unchanged: all of its tests still pass.

| Area | Implementation | Evidence |
| --- | --- | --- |
| Upload | Picker and server accept `.pdf/.dwg/.dxf` up to 50 MiB. The content is checked (`%PDF-`, `AC10xx`, DXF header) and the format is shown | `test_dwg_api.py`: wrong content → 415; DXF read without a converter |
| Conversion | `pipelines/cad/convert.py`: ODA File Converter preferred, LibreDWG `dwg2dxf` accepted, local only. If neither is installed the UI shows a Spanish error with installation steps | LibreDWG 0.14 installed with Homebrew; converts the AutoCAD 2018 (AC1032) test file in 0.1 s, with warnings about unstable dynamic-block classes |
| Units | `$INSUNITS`; if missing, inferred from wall thickness, extents and dimensions, and the source is always recorded and shown. Declared units that contradict the drawing stop the reading; ambiguous ones are never guessed | Unit tests: mm, inferred mm, contradictory metres, ambiguous |
| Plans | Wall geometry is clustered into drawn plans; with several, the user picks one from a numbered overview | `test_several_plans_wait_for_the_users_choice` |
| Layers | Every layer of the table is inventoried: role, how its name matched (pattern or near spelling, e.g. `a.venatana` → VENTANA), off/frozen state, contents in and outside the plan, and use. Off/frozen and demolition layers are never read. The inventory is shown in the review | Real file: 47 layers listed, 13 with geometry in the plan, all accounted for |
| Walls | Solid and patterned hatches, closed outlines and line pairs on wall layers, kept only if thinner than 0.6 m. Snapped to 0.1 mm and split into convex pieces (no ring walls, no sliver triangles) | Real file: 41 wall pieces from `a.secció` and `a.sombrea sección` |
| Openings | Gaps between facing wall ends with free space on both faces. Kind from block or layer names, swing side from the arc, stacked gaps merged. Unnamed carpentry in a gap becomes a doubt | Real file: 3 doors named (`BB - Puerta Dinamica 1 HOJA`), 8 unnamed window blocks and 3 carpentry gaps sent as doubts |
| Furniture | Block inserts, with dynamic `*U` blocks resolved to their source name and hidden visibility states skipped. Footprint in the insert frame, front from rotation and mirroring. The back is checked against the walls by the kind's side rule. Bed and sofa blocks that also draw nightstands, a rug or a table are split into pieces; an L-sofa becomes modules facing into the L | Unit tests for rotation, mirroring, corner wardrobes and composites |
| Rooms | Spaces enclosed by walls and kept openings, named by the TEXT/MTEXT inside. Floor finish from hatch pattern (`ANSI37` → tile; unknown patterns asked) | Real file: 6 rooms, 5 named from the drawing and 1 by the AI ("Vestidor") |
| Doubts → AI | Compact JSON of unresolved items plus a labelled 1024 px plan image. Strict `responses.parse` schema with answers by id, `effort=medium`, `store=False`, cached by model, prompt version and payload hash, audited in `ai-audit/`. No doubts → no call. Missing key or failure → items stay pending and approval is blocked until the user answers them | `test_dwg_ai.py`: zero calls without doubts, AI failure, missing key, cache hit, ids only, user answers |
| Review | DWG rendered locally on the left; the interpretation on the right with front arrows and pending items in red. The panel shows source, converter, SHA-256, units and their source, AI tokens, cost and time, and the verified / AI / user / pending lists with handles and layers | Live UI data checked through the API |
| Provenance | `Source.format/converter` and `Evidence.cad` (handles, layers, block, reading: verified/inferred/user). `pipelines.run` re-hashes the DWG; run status, provenance and manifest record format, hash and converter | Live `run-status.json` and `manifest.json` below |
| Viewer | HTML is served with `no-cache` and the lazy 3D viewer reloads once if a rebuild replaced its chunk. This fixes "Failed to fetch dynamically imported module …/Viewer-*.js" | `test_html_is_never_cached_but_assets_may_be`. The user's open page was kept working by serving the previous chunk too |

## Live verification — the test DWG in `dwg_test/` (real client drawing, not in Git)

Final run with the final code: project `035d40f6f142497db122c81d7dd0a8e0`, gpt-5.4 with a real key on the user's server (127.0.0.1:5174).

- **Converter:** LibreDWG dwg2dxf 0.14. ODA File Converter is not installed on this machine.
- **Units:** metres from `$INSUNITS = 6`. The plan is 9.70 × 10.17 m; the deterministic reading takes 0.44 s.
- **Readings** (verified from the DWG / inferred by the AI / missing):

  | Element | Verified | Inferred | Missing |
  | --- | --- | --- | --- |
  | Wall pieces | 41 | 0 | 0 |
  | Doors | 3 | 4 (2 sliding bathroom doors, 2 glazed balcony and gallery doors) | 0 |
  | Windows | 0 | 4 | 0 |
  | Rooms | 5 | 1 | 0 |
  | Furniture items | 6 (2 beds, 2 wardrobes, 2 sofa modules) | 34 classifications | 0 |

  The furniture classifications place 27 pieces and mark 7 as not furniture (hob, sink, two pillars, two low walls, one block outside the plan). 33 pieces are placed in total. The shower screen gap was answered "not an opening".
- **Doubts sent (47):**
  - 34 blocks or block pieces;
  - 9 carpentry gaps;
  - 2 unnamed rooms;
  - 1 layer (`a.projecció`, answered: not walls);
  - 1 hatch pattern (`ANSI31`, answered: wood).

  All answers are recorded in `cad-reading.json`. Each one checked against the drawing looks right: showers, toilets, basins and wardrobes with fronts away from their walls; kitchen modules with the hob and sink folded into the counter; fridge; peninsula with stools; dining set; nightstands, rug and coffee table from the composite blocks.
- **AI cost and time:** 1 call, 8,122 input + 8,279 output tokens (7,187 reasoning), **$0.145** at $2.50 / $15.00 per 1M tokens. The call took 120 s and upload to review took **126 s**. The PDF baseline is about $1.19 and about 20 min (1,141 s) per interpretation.
- **Generation:** approval to delivery in 372 s at 1600 px / 160 samples.
  - **QA 477/477.**
  - Renders: exterior, axonometric, and interiors of the living-dining-kitchen, Habitación 02, Habitación 01 and Baño 01.
  - GLB: 478 KB, served with HTTP 200.
  - `run-status.json`: `source_format: dwg`, SHA-256 `46053497…`, `converter: LibreDWG dwg2dxf 0.14`.
- **Visual inspection:** walls, openings and orientation match the plan. Beds have their headboards on the east walls with a nightstand and lamp each side; the L-sofa sits on its rug with the coffee table; the balcony and gallery have glazed doors; the entrance door is on the east party wall.

Earlier live attempts on the same file, each of which led to a fix:

| Attempt | Tokens | Cost | Call time | What it showed |
| --- | --- | --- | --- | --- |
| No image | 6.2k in / 10.7k out | $0.177 | 199 s | Balcony read as a window |
| With image | 7.4k in / 10.8k out | $0.180 | 188 s | Balcony and gallery correctly read as glazed doors, so the image became the default |
| After the wall snap changed the payload | 7.2k in / 12.5k out | $0.205 | 212 s | — |

- **Blender gate:** one preview QA failed 231/233 with sliver cap triangles on two complex walls. The fix was convex wall pieces; QA tolerances were not changed.
- **Composite blocks:** one complete run (477/477) still showed a 2.0 m bed (nightstands included) and a 2.4 × 2.7 m sofa (rug included). This is now fixed.
- **Total live AI spend in this session:** about $0.71.

## Not done / limits

- Tested on **one** real DWG with LibreDWG only. ODA File Converter (the preferred converter) is supported in code but untested here. LibreDWG warns about unstable dynamic-block classes on AutoCAD 2018 files.
- The model's answers vary between runs on secondary details (sliding vs casement windows; once the free-standing L-sofa's front). The deterministic reading does not vary.
- The labelled image is on by default because it fixed two openings on this one drawing (+1.2k input tokens). That is a sample of one.
- The `a.venatana` and `a.ventana` lines are read with a window role but end up unused: they are outer frame lines and room outlines, and the windows themselves come from the blocks in the wall gaps.
- The distributor and the living room form one room, because they are separated only by a carpentry screen with no wall gap; this is noted in the review. The balcony and gallery are outside the walls and are not modelled; their washing machine is dropped.
- Heights (2.70 m walls, 2.10/2.20 m doors, 1.20 m windows on 0.90 m sills) and the 0.20 m slab remain assumptions listed in the review. DWG attributes for heights are not read yet.
- Only one floor per project, and the plan must be orthogonal enough for gap detection (rotated walls are supported in code, not live-tested).
- Validation: Python 112 passed (80 pre-existing + 32 new), Ruff check and format clean, Node 2 passed, TypeScript/Vite build passed. No push, no deployment.

---

# Fidelity iteration — 2026-11-09 (Claude Code)

Goal: read the blueprint much more closely (walls, openings, furniture, bathrooms), orient
furniture logically, and render in an elegant, minimal-luxury style. API usage is not a
constraint in this phase.

| Area | Implementation | Evidence |
| --- | --- | --- |
| Furniture from the PDF | `pipelines/web/furniture.py` reads exact footprints from the white masks CAD exports put behind furniture blocks, plus closed furniture strokes (kitchen runs). Sub-parts merge (pillows into beds), rugs never swallow sofas, facade joinery is excluded | EA_01_MOD_1.pdf: 27 candidates: wardrobes, beds, nightstands, shower trays, basins, toilets, dining set, rug, sofa, bar |
| Opening evidence | Per gap: dashed swing arcs, joinery lines, facade contact, width. Door styles: hinged / sliding / glazed; window styles: casement / fixed | Unit tests + visual check on the plan |
| Floors per room | Light parallel hatching → wood; two-way fine grid → tile | Real plan: living + bedrooms = wood, both bathrooms = tile |
| AI calls | 3 calls, `reasoning.effort = high`, PDF + overview + 2×2 zoomed tiles with a PDF-point grid: (1) walls/openings with evidence, (2) furniture kind + front for every candidate, extras only for drawn pieces without a candidate, (3) self-review over an overlay of the assembled result (arrows show each piece's front) returning corrections. Each step cached by its exact inputs | See live result below |
| Orientation | Deterministic check after the AI: beds/sofas/wardrobes/counters/toilets/basins must back onto a wall (short vs long side by type), chairs/stools face their table; corrections are listed as assumptions. Footprints are stored as back-left, back-right, front-right, front-left | Unit tests; dry run corrected deliberately wrong bed fronts |
| Models | `furnish.py`: ~30 oriented, detailed parametric models (upholstered beds with headboard and cushions, walnut nightstands with brass lamps, wardrobes with reveals and pulls, sofas with cushions, stone coffee/dining tables with pendant, kitchen with stone worktop, hob, sink, wall units, wall-hung toilets, floating vanities with vessel basins and mirrors, shower trays with glass screens and rain heads, plants, lamps) | Every kind builds valid geometry in tests |
| Joinery | Windows: black aluminium frames, mullions, glass, stone sills. Doors: oak casing, leaf, brass lever or pull; glazed balcony doors | Visual |
| Style | Default palette: warm-white lime plaster, natural European oak, light travertine baths, Calacatta marble, walnut, ivory bouclé, white linen, sage accents, brushed brass, matt black. Subtle procedural grain (stripped for GLB). The description overrides any of 10 slots | Visual |
| Renders | Exterior, axonometric and one interior per main room (up to 4): ceiling and warm area lights only for interior shots; camera stands on the hero piece's front (foot of the bed, facing sofa/vanity), never inside furniture, framed within its room. Server renders at 1600 px / 160 samples | Dry run: 518/518 QA, 6 renders |

## Live result — EA_01_MOD_1.pdf through the running server (gpt-5.4, real key)

Project `36a71a6c173b4500913d1de5b4d5ba3f`, description: oak floor, warm-white walls, white marble worktop, travertine baths, brushed brass, bouclé sofa.

| Call | Tokens (reasoning) | Result |
| --- | --- | --- |
| 1. Walls + openings | 42,309 (18,541) | 52 walls; facade windows casement, balcony/gallery doors glazed, interior doors hinged. The v4 error (hall wardrobes read as door G11) is gone. Doubts listed in Spanish |
| 2. Furniture | 53,445 (15,497) | All 27 candidates labelled: beds face left (headboards on the wall with the nightstands), wardrobes, showers, basins, toilets, dining set, rug, sofa, fridge; hob recognised as part of the worktop; extras: coffee table, kitchen worktop run, washing machine |
| 3. Self-review | 66,786 (26,876) | Glazed openings → sliding, gallery window G21 added, G1 removed as open passage, two strips reclassified as fixed elements |
| Finishes | small | 10 slots matching the description |

Interpretation took 1,141 s (three high-reasoning calls, ~162k tokens). Draft: 62 walls, 5 doors, 5 windows, 5 rooms with floors (3 wood, 2 tile), 24 furniture pieces, 0 validation issues. Approved → Blender 444 s at 1600 px / 160 samples: **539/539 QA**, 6 renders (exterior, axonometric, living, both bedrooms, bathroom), 414 KB GLB, all served 200.

Known limits: the washing machine in the gallery was dropped (gallery is outside the modelled floor); the review removed G1, so Habitación 01 opens through a passage instead of a leaf; a description asking for oak everywhere yields very uniform wood; finishes and furniture are illustrative. Only one real blueprint has been tested.

---

# MVP González Cardona — 2026-11-09

Three-step studio flow implemented: **1. Upload PDF (+ optional material description) → 2. Review the AI interpretation side by side with the original → 3. Blender renders + GLB.** The only user inputs are the PDF and the optional description (≤1000 characters). Branding: González Cardona Arquitectura.

| Area | Status | Evidence / limitation |
| --- | --- | --- |
| AI plan interpretation | DONE | `grounded.py`: OpenAI (default `gpt-5.4`) selects wall/opening candidates extracted from PDF vectors and proposes furniture; geometry is never free-drawn by the model. Selections cached in `outputs/web-projects/ai-cache/selection-*.json` by PDF SHA-256 + model + prompt version; assembly re-runs with current code at zero token cost |
| Robust assembly | DONE | Implausible furniture is omitted and recorded as an assumption instead of failing the whole interpretation; chairs may tuck under tables. Door gaps close room boundaries; rooms are named from the plan's own text labels |
| Material description | DONE (mock-tested) | `materials.py`: separate text-only OpenAI call → typed `finishes` (walls, floor, doors, furniture wood, upholstery, ceramic) applied in Blender; cached by description. Without a key, default finishes are used and the review page says so. **Live call not executed in this session (no key in the agent shell)** |
| Review step | DONE | Original PDF and AI overlay side by side (stacked on narrow screens), element counts, named rooms, finish swatches, assumptions, “Aprobar y generar renders”, re-interpret, editable description. Manual editor kept under “Edición avanzada” |
| Approval | DONE | `POST /api/projects/{id}/approve` confirms the conceptual draft (status stays `inferred`), validates and queues Blender, revision-guarded |
| Blender | DONE | Interior camera searches the most open view inside the largest room (`viewpoint.py`); wide doors (>1.3 m) render glazed; chairs at seat height; QA expected bounds account for openings spanning a whole host footprint (tolerance unchanged, 2 mm) |

## Real blueprint result (blueprints_test/EA_01_MOD_1.pdf, CASA JPM 1:50)

Through the HTTP API on an isolated server (port 5180): upload with description → interpretation in 1.1 s from the cached gpt-5.4 selection (26,943 tokens originally, 2 attempts; 0 new tokens) → 61 walls, 5 doors, 4 windows, 1 slab, 5 named rooms (Salón - Comedor - Cocina, Habitación 01/02, Baño 01/02), 19 furniture pieces, 0 validation issues → approve → Blender succeeded in 88.6 s, **518/518 QA checks**, exterior/interior/axonometric renders and a 155 KB GLB served. A separate direct run with a hand-written test palette verified that finishes reach the renders.

Previously this same response failed: the furniture validator rejected chairs overlapping the dining table, and QA rejected door lintels. Both were fixed in code without relaxing tolerances.

## Not verified / remaining

- Only one real blueprint was available; other drawing conventions (scans, line-only walls, several scales or floors per PDF) remain unsupported by the grounded assembler and fall back to manual editing.
- Live OpenAI calls (new PDFs, finishes) were not executed in this session; the user's local server has the key.
- Heights (2.70 m walls, 2.10 m doors, 0.90/1.20 m windows) are assumptions listed in the review. Furniture/finishes are illustrative.
- Python 74 passed, Ruff clean, Node 2 passed, TypeScript/Vite build passed. No deployment.

---

# Automatic interpretation and source comparison

New uploads automatically request OpenAI interpretation when the local server has a key. A private cache keyed by PDF digest, model and prompt version avoids repeated API calls; the original AI proposal and token usage are retained alongside the editable draft. The web compares the original PDF and proposed geometry side by side (stacked on narrow screens).

Live EA_01_MOD.pdf attempt: OpenAI gpt-4.1 returned 21 entities using 2,149 input tokens (1,920 cached) and 3,135 output tokens: 5,284 total. This proposal FAILED geometric review: wrong scale/contours, inconsistent wall thickness, missing slab thickness and invalid room polygon. It was not rendered or presented as successful reconstruction.

The next prompt includes actual vector polygon coordinates and text positions (57 filled candidates in this document), plus the explicit PDF scale conversion. This revision awaits a server restart and live validation. No perfect reconstruction or globally minimum token consumption is claimed. Automated suite: 60 passed, including upload-to-AI and identical-PDF cache reuse; frontend build and Ruff pass. No deployment.

---

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

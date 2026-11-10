# Agent guide: adding features to the Architectural AI Visualizer

The guide is current as of v1.0.0 (2026-11-10). Read it before you change anything. It covers:
- what the app does;
- how the code is organised;
- the contracts you must not break;
- how to add the most common kinds of feature;
- how to verify your work;
- the mistakes that cost time while building v1.

`AGENTS.md` holds the binding rules. This guide explains them and adds the practical detail.

---

## 1. What the app does

The app is a local web app built for the architecture studio **González Cardona**. Users go through these steps:

1. **Upload** a floor plan as **PDF, DWG or DXF**, with an optional free-text description of materials.
2. **DWG/DXF only.** The drawing is converted and read on the machine, with no AI. The user may pick one of several drawn plans. Next comes the **reading check**: the user confirms what the program read before any AI call.
3. **AI interpretation.**
   - **PDF:** three OpenAI calls that label the PDF's vector geometry.
   - **DWG:** one OpenAI call that answers only the "doubts" the drawing leaves open.
4. **Review.** The user sees the original next to the interpretation. The two views are linked and can be panned and zoomed. The user can answer pending items, edit by hand, change the materials text or change the location, then approve.
5. **Generation.** Approval runs headless **Blender** to build the model, run QA, render the views (exterior, axonometric, interiors) and export a GLB.
6. **Optional illustrative AI enhancement** of each render (OpenAI image edits). Originals are always kept.

Everything runs locally: there is no cloud storage and no database. Production runs in a **Docker container** on `http://127.0.0.1:5174`.

## 2. Rules you must follow (from AGENTS.md, explained)

- **The uploaded drawing is authoritative.**
  - Geometry and dimensions come from the drawing's vectors or entities, never from an AI's imagination.
  - The AI only **selects or labels** candidates the program found, or answers doubts **by id**.
  - If something is unknown, it **stops at review**. Never fill it in silently.
- **Verified vs inferred vs missing.** Every element carries a status:
  - `verified` means read from the drawing;
  - `inferred` means answered by the AI, deduced by a rule, or an assumed height;
  - `missing` (or pending) means nobody has resolved it.
  - Keep this distinction in the data and in the UI.
- **Provenance.** Preserve what each element came from:
  - **PDF:** source page and coordinates.
  - **DWG:** DXF handles, layers, block name and converter.
  - **Every run:** the source SHA-256, the configuration and the code revision.
- **Client drawings are private.**
  - Never commit, publish or upload PDF, DWG or DXF files to anything except the OpenAI calls described here. That includes renders derived from them and client names or addresses in docs or tests.
  - `blueprints/`, `blueprints_test/`, `dwg_test/`, `outputs/` and `.env` are ignored by Git. Keep it that way.
  - **Tests use synthetic fixtures only.**
- **Production is deterministic headless Blender.** Blender MCP and vision are optional extras.
- **Git:**
  - Use feature branches and atomic commits.
  - **Never force-push.** Don't push unless the user asks.
  - Record real evidence and unfinished work in `docs/IMPLEMENTATION_STATUS.md`. Add newest entries on top, with measured numbers, not claims.

## 3. Working safely on this machine

- **The repo folder is shared.** Several agent sessions and the user may work in it at once.
  - **Never `git checkout`, `switch`, `reset` or `checkout -b` there.** It moves everyone's HEAD, and peers then commit onto the wrong branch.
  - Create a worktree instead: `git worktree add <scratch>/wt -b feature/x master`, and work, test and build there.
  - Run `ListAgents` at the start, and coordinate with peers through `SendMessage`.
- **The app the user runs is the Docker container `gonzalez-cardona`** on 127.0.0.1:5174 (see §9). It runs a copy of the code baked into the image, so editing files never disturbs it.
  - If you run the native server with `--reload`, any save under `pipelines/` restarts it. The restart waits for (and then interrupts) the job in progress, and startup marks busy projects as `failed/interrupted`.
  - Before restarting or replacing a running server, check that no project is `queued`, `running` or `extracting` (`GET /api/projects`).
- **Test servers.** Use another port (for example 5181) with your own `--data-dir`, never the shared `outputs/web-projects`.
- **Slow environment.** The project folder is in **iCloud**, so `.venv` inside it can be extremely slow (a server start once hung for minutes).
  - Use `UV_PROJECT_ENVIRONMENT=$HOME/.venvs/architectural-ai-visualizer`, or a throwaway env in `/tmp`. During v1, `/tmp/aav-validation-env` with `PYTHONPYCACHEPREFIX=/tmp/aav-pycache` was used.
  - Build the site in a copy outside iCloud (e.g. `/tmp/aav-site-dependencies`), then copy `dist/` back.
- **Billed API calls.**
  - Ask before running paid calls in bulk.
  - The user's key lives in `.env` and inside the running container's environment. Never print it, log it or commit it, and never inspect process environments for secrets.

## 4. Architecture at a glance

```
upload (PDF | DWG | DXF)
  │
  ├─ PDF ─ pipelines/pdf/extract.py        vectors, text, page images (display ≤ 4×, analysis 1.5×)
  │        pipelines/web/grounded.py       3 OpenAI calls: walls+openings → furniture → cross-check review
  │        pipelines/web/furniture.py      candidates, opening evidence, floor finishes from PDF vectors
  │
  └─ DWG ─ pipelines/cad/convert.py        DWG → DXF locally (ODA File Converter or LibreDWG dwg2dxf)
           pipelines/cad/read.py           deterministic reading: units, plans, walls, openings, rooms, blocks
           pipelines/web/dwg.py            draft + doubts; after the user's reading check, ONE OpenAI call
  │
  ▼
review draft (pipelines/web/review.py: Draft)  ── user review in site/src/Workflow.tsx
  │  approve → validate_draft() → Geometry (pipelines/geometry/schema.py, metres, provenance)
  ▼
pipelines/run.py ── Blender (pipelines/blender/build_scene.py + furnish.py + viewpoint.py)
                 ── QA (pipelines/quality/check.py) ── renders ── GLB (site/scripts/*.mjs)
                 ── optional enhancement (pipelines/postprocess/*) ── manifest.json
  ▼
site (React/Vite/R3F): gallery, 3D viewer, review workflow
```

**The web server is `pipelines/web/server.py`** (FastAPI).
- **Network:** it listens on loopback only (`LocalBoundary` rejects any other `Host` or `Origin`).
- **Storage:** one folder per project under the data dir, holding `project.json`, `source.*`, `evidence/`, `ai-audit/` and `runs/<id>/`. An AI cache is shared across projects in `<data-dir>/ai-cache/`.
- **Jobs:** they run on a **single-worker** `ThreadPoolExecutor`, so jobs queue one at a time.

### Module map

| Path | Role |
| --- | --- |
| `pipelines/common.py` | Paths, `write_json`, `sha256`, `blender_bin()`, `revision()` (`AAV_REVISION` when Git is absent), `MODELS` + `model_for(purpose)` |
| `pipelines/pdf/extract.py` | PDF evidence: vectors, text blocks, display PNG (≤ 4×, ≤ 8000 px), 1.5× raster for line detection |
| `pipelines/web/grounded.py` | PDF interpretation: candidate catalog, labelled images, `Calls` (OpenAI wrapper with cache, audit, budget retry), `propose()` |
| `pipelines/web/furniture.py` | `FurnitureKind`, `HEIGHTS`, orientation rules (`resolve_front`), furniture candidates, floor finishes |
| `pipelines/web/materials.py` | Description of materials → 10 finish slots (one low-effort call) |
| `pipelines/web/review.py` | `Draft` model (review coordinates), `validate_draft()` → `Geometry` + issues |
| `pipelines/cad/config.py` | **CAD vocabulary in one place:** layer roles, block synonyms → furniture kinds, hatch → floor finish |
| `pipelines/cad/convert.py` | Converter discovery and DWG → DXF |
| `pipelines/cad/read.py` | Units (incl. mislabelled), plan clustering, wall layers inferred by geometry, walls/gaps/openings/rooms/blocks, clipping to the chosen plan, convex wall pieces |
| `pipelines/cad/render.py` | DXF region → PNG (ezdxf + matplotlib Agg) |
| `pipelines/web/dwg.py` | `prepared()`, `propose()` (reading + doubts + optional AI + `assemble`), `Sheet` (metres ↔ review cm), `exclusive()`, `plan_sheet()`, `overview()` |
| `pipelines/geometry/schema.py` | **The contract with Blender:** `Geometry`, walls, openings, rooms, furniture, finishes and evidence. Strict validation (e.g. walls may not overlap > 1e-5 m²) |
| `pipelines/run.py` | Transactional run: source check, Blender build, preview QA, renders, final QA, GLB, manifest, enhancement |
| `pipelines/blender/build_scene.py` | Runs **inside Blender**: prisms, opening booleans, materials/palette, lights, cameras, renders, class masks |
| `pipelines/blender/furnish.py` | ~30 parametric furniture models built from oriented footprints (no bpy import; testable) |
| `pipelines/blender/viewpoint.py` | Interior camera search (pure Python) |
| `pipelines/quality/check.py` | QA: metric checks on evaluated meshes (2 mm tolerance), mesh validity, render exposure |
| `pipelines/postprocess/` | `location.py` (location from drawing text), `prompt.py` (prompt from `docs/PROMPT_STYLE.md`), `enhance.py` (image edits, cache, retry), `fidelity.py` (drift check) |
| `site/src/Workflow.tsx` | The 3-step UI: upload, reading check, review, materials, location, approval, progress panel |
| `site/src/ZoomPane.tsx` | Linked pan/zoom panes (view stored relative to pane width) |
| `site/src/App.tsx`, `Viewer.tsx` | Branding, gallery and the R3F 3D viewer |
| `site/scripts/*.mjs` | GLB optimisation and validation (run by `pipelines/run.py` with Node) |
| `Dockerfile`, `compose.yaml`, `.env.example` | Container (see §9) |

Older, still-present paths:
- `pipelines/web/ai.py` and `pipelines/pdf/vision.py`: legacy CLI `--vision` proposals.
- `agents/` and `.codex/`: optional Blender MCP setup.
- `.agents/skills/`: skill notes from the original design.

## 5. Project lifecycle (status and stage)

`project.json` has a coarse `status` and a finer `stage`. `stage_since` records when the stage started, and `activity` holds the current AI step or image for the progress panel.

| Status | Stages |
| --- | --- |
| `extracting` | `extracting` (PDF), `reading_dwg` |
| `running` | `interpreting`, `resolving` (applying user answers), `materials`, `enhancing` (rerun only) |
| `review` | `choose_plan` (DWG with several plans), **`reading_check`** (DWG, before AI), `review` |
| `queued` / `running` | `queued`, `validating_geometry`, `modeling`, `preview_qa`, `rendering`, `final_qa`, `exporting`, `enhancing` |
| `succeeded` | `completed` |
| `failed` | `extraction_failed`, `generation_failed`, `interrupted` |

`BUSY = {queued, running, extracting}`. While a project is busy, `check_revision()` refuses changes (409), and so does a stale `revision`.

### HTTP API (all under `/api`)

| Method and path | Purpose |
| --- | --- |
| `GET /health`, `GET /projects`, `GET /projects/{id}` | Status and listing (`detail` also returns `enhance_server`) |
| `POST /projects` | Upload (`file`, `description`). Content is checked: `%PDF-`, `AC10xx`, DXF header |
| `POST /projects/{id}/plan` | DWG: choose a plan (allowed from `choose_plan` or `reading_check`) |
| `POST /projects/{id}/confirm-reading` | DWG: confirm the reading → doubts AI call |
| `PUT /projects/{id}/answers` | DWG: user answers to pending items (no AI) |
| `POST /projects/{id}/interpret` | Re-run the interpretation (PDF: 3 calls; DWG: reading + doubts) |
| `PUT /projects/{id}/draft`, `POST /validate` | Manual edits and validation |
| `PUT /projects/{id}/description` | Materials text → finishes |
| `PUT /projects/{id}/location` | Location used by the enhancement |
| `POST /projects/{id}/approve` | Approve the AI interpretation → generation (`enhance` flag) |
| `POST /projects/{id}/generate` | Generate from a manually completed draft |
| `POST /projects/{id}/enhance` | «Mejorar de nuevo»: rerun only the enhancement |
| `GET /projects/{id}/files/{name}` | Allow-listed files: page images, overview, manifest, model, renders (incl. `renders/enhanced/`) |

## 6. Data contracts you must respect

- **Review coordinates (`Draft`).**
  - **PDF:** PDF points on page 1.
  - **DWG:** "sheet" units of **1 cm, y pointing down** (`dwg.Sheet`, `SHEET_UNIT = 0.01`).
  - `validate_draft()` turns either into metres. An entity outside the page is an error.
- **Furniture footprints** are 4-point polygons ordered **back-left, back-right, front-right, front-left**. That order encodes orientation, and the UI draws the front arrow from it.
  - The name is `"<kind> / <display name>"`, and `kind` comes from `FurnitureKind`.
  - Heights come from `HEIGHTS`. Wall-backed kinds face away from the wall, and chairs face the table (`resolve_front`).
- **Openings** belong to a host wall.
  - In DWG drafts each opening has its own host wall of exactly the opening's footprint (`host<gap id>`), and Blender cuts the opening band out of it.
  - Openings inside longer walls keep their exact width.
- **Geometry schema** (`schema.py`) is strict: hole-free polygons, no overlapping walls (> 1e-5 m²), openings inside their hosts, matching floor elevations. If it rejects a draft, fix the producer; don't loosen the schema.
- **Run outputs** (`runs/<id>/`):
  - `manifest.json`: renders, model, finishes, source, enhancement;
  - `run-status.json`, `provenance.json`, `quality-report.json`;
  - `views.json`: one entry per render view;
  - `renders/<view>.webp`, plus `renders/enhanced/` for the AI enhancement and `masks/` for the class masks it uses;
  - `model.glb`.
  - Render ids match `exterior|axonometric|interior(-[2-9])?`. If you add views, update the allowlist regex in `server.py`.
- **Site packages** only ever get originals and synthetic assets (`strip_for_site`, `copy_site_renders`).

## 7. AI calls

All AI calls use **OpenAI structured outputs** (`client.responses.parse(..., text_format=<Pydantic model>)`, `store=False`).
- **Don't add LangChain** for this. Its structured output wraps the same feature and wouldn't solve the real issue seen so far, which was the output-token budget.
- **Answers are always ids or labels**, never coordinates.

| Call | Where | Model setting | Effort / budget | Typical cost and time |
| --- | --- | --- | --- | --- |
| PDF selection, furniture, review (3 sequential) | `grounded.propose` | `OPENAI_PLAN_MODEL` | high / 32k (retry 64k) | ≈ $1.19, 15–20 min |
| DWG doubts (1) | `dwg.resolve` | `OPENAI_DWG_MODEL` | medium / 32k (retry 64k) | $0.15–0.30, 2–6 min |
| Materials → finishes | `materials.propose_finishes` | `OPENAI_MATERIALS_MODEL` | low / 2k | < $0.01 |
| Render enhancement (per view, ≤ 2 tries) | `postprocess/enhance.py` | `OPENAI_IMAGE_MODEL` (+ `_QUALITY`) | image edit | ≈ $0.07 per call; ≈ $0.65 per project |
| CLI `--vision` (legacy) | `pdf/vision.py` | `OPENAI_VISION_MODEL` | — | not used by the web app |

Shared behaviour (`grounded.Calls`):
- **Cache:** on-disk, `ai-cache/<step>-<sha256(model + prompt version + inputs)>.json`. Bump the step's `PROMPT_VERSION` whenever you change its prompt or schema.
- **Audit:** one record per call in `<project>/ai-audit/`.
- **Retry:** an answer cut off by the output budget is retried once with double the budget, up to 64k. Other failures report status, incomplete reason, refusal and tokens (`unanswered()`).
- **Progress:** reported through `Calls.progress`, which feeds the UI's step list.
- **No key or failed call:**
  - **DWG:** the doubts stay pending for the user; the deterministic reading never fails because of the AI.
  - **PDF:** the review shows a Spanish error with "Reintentar".
  - **Enhancement:** the originals are kept.

Things that change a cache key in a non-obvious way:
- **The DWG doubts key includes the PNG of the labelled plan.** That image is drawn with the platform's fonts, so the same drawing gets different keys on macOS and in the Linux container.

## 8. Configuration (environment)

Set these in `.env` for the container, or in the shell for a native server.

| Variable | Default | Meaning |
| --- | --- | --- |
| `OPENAI_API_KEY` | — | Required for every AI step |
| `OPENAI_PLAN_MODEL`, `OPENAI_DWG_MODEL`, `OPENAI_MATERIALS_MODEL` | `gpt-5.4` | Text models per purpose (`OPENAI_MODEL` is a shared fallback) |
| `OPENAI_VISION_MODEL` | `gpt-4.1` | Legacy CLI only |
| `OPENAI_IMAGE_MODEL`, `OPENAI_IMAGE_QUALITY`, `OPENAI_IMAGE_COMPLEXITY` | `gpt-image-2.5-sunburst`, `high`, — | Render enhancement |
| `AAV_ENHANCE`, `AAV_ENHANCE_AXONOMETRIC` | `1`, `1` | Enhancement switches |
| `AAV_DWG_IMAGE` | `1` | Attach the labelled plan image to the DWG doubts call |
| `AAV_RENDER_RESOLUTION`, `AAV_RENDER_SAMPLES` | 1600 / 160 (container `.env`: 1200 / 64) | Render quality |
| `BLENDER_BIN`, `ODA_FILE_CONVERTER`, `DWG2DXF` | auto-detected | Tool paths |
| `AAV_REVISION` | Git commit | Code revision when Git is absent (baked into the image) |

## 9. Running, building, shipping

**Native:**
```sh
uv sync --locked
cd site && npm ci && npm run build && cd ..
UV_PROJECT_ENVIRONMENT="$HOME/.venvs/architectural-ai-visualizer" uv run python -m pipelines.web.server --port 5174
```

**Docker** (what the user runs):
```sh
docker build --platform linux/amd64 --build-arg AAV_REVISION=$(git rev-parse --short HEAD) \
  -t gonzalez-cardona/visualizer:latest .
docker rm -f gonzalez-cardona
docker run -d --name gonzalez-cardona --platform linux/amd64 --env-file .env \
  -p 127.0.0.1:5174:5174 -v aav-data:/data --restart unless-stopped gonzalez-cardona/visualizer:latest
```

- **x86-64 only:** Blender publishes only x86-64 Linux builds, so the image is `linux/amd64`. On Apple Silicon it runs emulated and renders on the CPU, about 13 min per project at 1200/64. The native app on Metal is much faster.
- **Editing `.env`:** recreate the container (`rm` + `run`); a restart doesn't re-read the file.
- **Data:** projects live in the `aav-data` volume.
- **Port:** keep the same port inside and outside, because the server rejects other `Host` values.
- **What the image contains:** fonts (needed to draw DWG sheets), LibreDWG 0.14 compiled from source, Node 24, Blender 4.5.9 and the locked Python environment. The `.dockerignore` keeps `.env`, outputs and client drawings out.

**Git:**
- `master` holds the released code, and `v1.0.0` is the first tag.
- GitHub's default branch may still be `codex/architectural-pipeline`; the user changes that on GitHub.
- End commit messages with the attribution line the session asks for.

## 10. How to add common features

**New furniture kind**
1. Add the kind to `FurnitureKind` and a height to `HEIGHTS` in `pipelines/web/furniture.py`. Add it to `WALL_BACKED` or `FACES_TABLE` if one applies.
2. Add a model to `MODELS` in `pipelines/blender/furnish.py`. Build it in the local frame of the ordered footprint. `tests/test_furnishing.py` checks that every kind builds.
3. Add DWG block-name synonyms in `pipelines/cad/config.py` (`BLOCK_SYNONYMS`), plus a Spanish label in `furnitureKinds` in `Workflow.tsx`.
4. Mention the kind in the PDF furniture prompt if the AI should be able to choose it, and bump `FURNITURE_VERSION`.

**New CAD convention (layer or block names, hatch patterns)**
- Edit **only** `pipelines/cad/config.py`.
- Layer naming isn't standard across offices:
  - wall layers are inferred from geometry when no name matches (`read.inferred_wall_layers`);
  - unknown wall-like layers next to walls become doubts.
- Prefer improving those general mechanisms over adding one office's names.
- Add a synthetic case to `tests/dxf_fixture.py` and `tests/test_dwg_reading.py`.

**New pipeline or AI step**
1. Put the logic in a module under `pipelines/`. Use `grounded.Calls` for OpenAI: you get the cache, audit, retry and progress for free.
2. Give it a `PROMPT_VERSION`, a strict Pydantic schema, answers by id, and a deterministic fallback when the call fails.
3. Wire it into `server.py` as a job on `projects.executor`, with its own `stage`. Report progress through `activity`.
4. Add the stage to `stages` (and `busyStates` if needed) in `Workflow.tsx`. Check that startup recovery in `Projects.__init__` handles an interruption sensibly.
5. Test with a mock client keyed by `text_format` (see `tests/test_dwg_ai.py`, `tests/test_ai_calls.py`).

**New review or UI capability**
- The review lives in `site/src/Workflow.tsx`; reusable pieces go in their own component (as `ZoomPane.tsx` does).
- Keep Spanish copy. Keep verified, inferred and pending visibly different.
- Pass `check` or a mode flag rather than duplicating panels (see `CadPanel`).

**New render view**
1. Add it in `build_scene.py` (cameras and `views.json`).
2. Extend the render allowlist regex in `server.py`.
3. Make QA (`check.py`) require it through `views.json`.
4. The prompt in `postprocess/prompt.py` handles view types (`interior`, `exterior`, `axonometric`).

## 11. Verifying your work

**Required before you report done:**
```sh
uv run ruff check . && uv run ruff format --check pipelines tests
uv run pytest            # 153 tests at v1.0.0; synthetic fixtures only
cd site && npm run build && npm test
```

- **What each test file covers:**
  - **PDF route:** `test_web_api.py` (API flow), `test_grounded.py` (interpretation), `test_furniture_reading.py`.
  - **DWG:** `test_dwg_reading.py`, `test_dwg_ai.py`, `test_dwg_api.py`.
  - **Rendering and AI:** `test_furnishing.py` and `test_viewpoint_finishes.py` (Blender-side Python), `test_enhancement*.py`, `test_ai_calls.py` (budget retry), `test_container.py` (env settings).
- **Geometry changes:** run a real Blender generation as well. QA must pass, and it is strict (it caught degenerate faces from angled walls).
  - Run `pipelines.run.run()` on an approved geometry. Natively at 960 px / 64 samples it takes about 1 min.
- **UI changes:** look at the result in a real browser. During v1, headless Chrome was driven over the DevTools protocol from a Node script (Node 24 has a built-in `WebSocket`).
  - Kill leftover Chrome processes between runs. A stale tab on the debug port kept showing an old project, because navigating to a URL that differs only after `#` doesn't reload the page.
- **Live end-to-end:** use a test server on another port with its own data dir. Copy `ai-cache/` into it to reuse paid answers.
  - PDF answers are keyed by the PDF hash.
  - DWG answers are only reused on the same platform (see §7).
- **Docker changes:** rebuild the image and run the exact README command, then check `/api/health`, the page, the model variables and an end-to-end run.
- **Record what you measured** (counts, QA results, tokens, cost, time) in `docs/IMPLEMENTATION_STATUS.md`, plus what you could *not* verify.

## 12. Lessons from v1 (don't repeat these)

- **AI output budget.** A DWG with 113 doubts spent the whole 16k-token budget on reasoning and returned nothing ("No structured doubts returned"). Size budgets for large inputs and keep the retry.
- **CAD entities can span plans.** One wall hatch covered two drawn plans and dragged the other plan's walls off the sheet. All geometry is now clipped to the chosen plan's area.
- **Angled walls.**
  - Cutting walls into convex pieces and snapping each one separately left sub-millimetre overlaps the schema rejects. Pieces are now `exclusive()`.
  - Rounding could repeat a corner, which breaks Blender meshes. `Sheet.polygon` drops repeats.
  - Opening cutters coplanar with a rotated host's faces broke Blender's exact boolean. Full-footprint cutters now overshoot.
- **Mislabelled units are common** (a plan drawn in metres saved as mm). They're inferred when exactly one unit fits, and flagged for the user. When none fits, the reading stops.
- **Raster resolutions.** The PDF display image and the line-detection raster are separate on purpose: the Hough thresholds are tuned at 1.5×.
- **Rendering details.**
  - `will-change: transform` makes Chrome scale a cached bitmap (blurry zoom).
  - The slim Docker base image had no fonts, which broke DWG sheet drawing.
  - `git` doesn't exist in the image (revision crash).
- **Servers and jobs.**
  - Never edit `pipelines/` under a `--reload` server while a job runs.
  - Never replace the container while a project is busy.
- **Client data.** Synthetic examples only in code and tests. A real street address and a project name had to be scrubbed before the first push.

## 13. Known limits and open work

- **Tested drawings:** few real ones (2 PDFs, 3 DWGs). ODA File Converter is supported but untested; only LibreDWG was used.
- **One floor per project.** Heights (2.70 m walls, door and window sizes, 0.20 m slab) are assumptions shown in the review; DWG height attributes aren't read yet.
- **Exterior enhancement** is usually rejected by the drift check, because the model enlarges the building. The original is shown.
- **Container rendering** is CPU-only under emulation on Apple Silicon.
- **Speed:** PDF interpretation takes about 20 min (3 high-reasoning calls in sequence).
- **Cost ideas not yet tried:** medium effort for PDF, `gpt-5.4-mini`, and reading CAD layers that some PDFs keep.

## 14. Other documents

- `AGENTS.md`: binding rules.
- `README.md`: running natively and with Docker.
- `docs/ARCHITECTURE.md`: design decisions.
- `docs/IMPLEMENTATION_STATUS.md`: evidence log, newest first.
- `docs/USER_GUIDE.md`: the studio's guide, in Spanish.
- `docs/PROMPT_STYLE.md`: the studio's master style prompt for the enhancement. It's read at runtime; don't rewrite it.
- `docs/BLENDER_MCP.md`, `docs/SITES_DEPLOYMENT.md`, `docs/REFERENCES.md`, `docs/TEST_RESULTS.md`, `docs/PROJECT_HANDOFF.md`: older background notes.

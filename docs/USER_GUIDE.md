# User guide

## Setup and demo

Install Python through uv (`uv python install 3.12`), Blender 4.5 LTS from its official distribution, and Node.js. Run `uv sync --locked` and `npm --prefix site ci`. No OpenAI API account is needed for deterministic local work.

```sh
uv run python -m pipelines.run --demo --output outputs/demo-001 --clay --site-assets site/public/project
npm --prefix site run dev
```

The demo is synthetic test data. Output includes original PDF, evidence images/JSON, geometry, review, editable Blender scene, preview/clay/final renders, QA report, GLB, manifest and provenance. The gallery WebP files are under `outputs/demo-001/renders/`. Final renders default to 960 × 720 and 64 Cycles samples. Increase `--resolution 1920 --samples 256` for a larger presentation; use `--device cpu` to avoid GPU dependence.

## Existing PDF

Use only a PDF you are authorized to process:

```sh
uv run python -m pipelines.run --input plan.pdf --output outputs/my-project
```

If automatic verification is unavailable, inspect `outputs/my-project/run-status.json`, which points to retained evidence under `.run-*`. Review every wall, room, opening, scale and elevation. The full geometry schema can be exported with:

```sh
uv run python -c 'import json; from pipelines.geometry.schema import Geometry; print(json.dumps(Geometry.model_json_schema(), indent=2))' > outputs/geometry-schema.json
```

A reviewed geometry file must contain source PDF digest/page count, original coordinates, a consistent metric transform and explicit `verified` evidence. Run again with `--geometry reviewed.json`. Marking an unknown value verified is not a substitute for obtaining that measurement.

For optional AI observations, export `OPENAI_API_KEY`, optionally `OPENAI_MODEL`, and add `--vision`. This explicitly sends the PDF to the OpenAI API and can incur API usage. API output never changes the verification status automatically. The template `.env.example` is not loaded automatically.

## Stages and diagnostics

- `uv run python scripts/diagnose.py --probe-blender --output outputs/environment.json` checks versions, packages and renderer devices without printing secrets.
- `uv run python -m pipelines.pdf.extract --input plan.pdf --output outputs/review` extracts evidence alone.
- `uv run python -m pipelines.quality.check --geometry outputs/demo-001/geometry.json --output outputs/demo-001` reruns QA against captured evaluated meshes and images.
- `node site/scripts/validate-model.mjs outputs/demo-001/model.glb` validates GLB and Three.js loading.
- `npm --prefix site run build` builds static `site/dist/`; `npm --prefix site run preview` previews that production build locally.

On failure, read `run-status.json` and the indicated stage log. A failed rerun can coexist with an older successful delivery; the latest run status governs whether the new attempt passed. Generated artifacts are excluded from Git. Do not force-add private PDFs or client assets to a public repository.

## Viewer

Use the Exterior, Axonométrica and Planta controls; orbit/zoom/pan with the pointer or the camera buttons. Select a floor, toggle walls, and reset camera/visibility. Roof controls are disabled when no roof is specified. Interior gallery renders are available; an interactive interior preset is shown only when explicit camera metadata is supplied. Clicking an architectural mesh reveals its source identifier. Downloads contain only the model or rendered image, never the source PDF.

The web app is a presentation viewer. PDF ingestion and validation run through the CLI; browser upload, editing, cloud jobs and persistent storage are intentionally outside this iteration.

`--site-root path/to/site` selects another identical frontend source checkout for building/export validation. The normal default is the repository's `site/`; this option is useful when staging a clean installation or preparing an isolated review package.

# Interpretación conceptual con OpenAI

El botón **Interpretar PDF con OpenAI** envía el PDF a la API y consume tokens. Requiere `OPENAI_API_KEY` en el entorno del servidor; no introduzcas la clave en el chat ni la guardes en Git. `OPENAI_MODEL` permite elegir un modelo con visión y salidas estructuradas (predeterminado: `gpt-4.1`). Reinicia el servidor después de configurar las variables.

Después de subir el PDF, pulsa el botón de interpretación. Revisa los contornos propuestos, las medidas y la lista editable de supuestos. El modelo propone alturas cuando no están documentadas; los acabados siguen siendo ilustrativos. Pulsa **Aceptar propuesta y supuestos para generar**, después **Comprobar datos** y **Generar renders y 3D**. La aceptación no convierte las inferencias en medidas verificadas. Una geometría incoherente sigue bloqueando Blender y requiere corrección en el editor.

La propuesta admite una planta por ejecución y PDFs de hasta 20 MiB. Cada clic inicia una petición facturable (sin reintentos automáticos), limitada a 16.000 tokens de salida; el consumo se conserva en el proyecto. No se garantiza interpretación correcta de cualquier plano. Los renders proceden de Blender y comparten geometría con el GLB; no hay mejora de imágenes con IA implementada.

La integración está probada con respuestas simuladas; falta validar una petición real con credenciales y revisar la fidelidad de EA_01_MOD.pdf. La API recibe el documento; `store=False` no equivale a prometer retención cero por el proveedor.

---

# Guía del flujo web — 2026-11-09

1. Instala las dependencias con `uv sync --locked` y `npm --prefix site ci`. Compila con `npm --prefix site run build`.
2. Inicia `uv run python -m pipelines.web.server --port 5174` y abre http://127.0.0.1:5174/#new-project.
3. Pulsa **Subir plano PDF**. Límite: 50 MiB y 50 páginas. Selecciona la página; esta versión modela una página y una planta por proyecto.
4. Usa **Marcar cota** sobre dos extremos de una distancia conocida, introduce los metros y confirma. Introduce y confirma la elevación de la planta. Puedes introducir puntos con el teclado en coordenadas del PDF.
5. Selecciona el tipo de elemento y dibuja su contorno por vértices; pulsa **Cerrar contorno**. Para rectángulos vectoriales puedes activar los candidatos y seleccionar uno. Un candidato no acredita que sea un muro. Los planos escaneados se pueden trazar sobre su imagen.
6. Revisa cada muro, losa, habitación, puerta, ventana o cubierta. Completa altura, espesor, cota inferior y muro anfitrión cuando proceda. Los muros parten de la elevación de planta. La losa/cubierta tiene su propia cota inferior absoluta. Las puertas/ventanas usan altura del borde inferior sobre planta. Confirma cada elemento. No añadas datos que no conozcas.
7. Guarda para continuar después. Marca la confirmación final y pulsa **Comprobar datos**. Los mensajes identifican el elemento o medida que falta o es incoherente. Cambiar escala o contornos exige volver a confirmar.
8. Pulsa **Generar renders y 3D**. Verás extracción, modelado, comprobaciones, render y exportación. La revisión queda bloqueada mientras trabaja. Puedes recargar la página: el proceso continúa en el servidor.
9. Al terminar, pulsa **Ver renders y 3D**. Puedes descargar el GLB y las imágenes. Una habitación delimitada habilita el render interior; sin habitaciones se generan exterior y axonometría. No se inventa una cubierta.

Los archivos, revisiones y resultados quedan en `outputs/web-projects/<id>/`, excluidos de Git. El selector **Proyecto local** recupera los proyectos guardados. Si el servidor se interrumpe, el borrador se conserva y puedes reintentar. Los resultados de una revisión anterior no se sirven como la nueva entrega. El servidor escucha únicamente en este equipo; no necesita API key. No publiques esta carpeta.

El flujo ofrece revisión manual de planos generales: no promete reconstrucción semántica automática de cualquier PDF. Los acabados, puertas y cristales son simplificados. Para planos de varias plantas, crea proyectos separados o utiliza la geometría revisada por CLI.

---

# Uso avanzado por CLI

## Setup and demo

Install Python through uv (`uv python install 3.12`), Blender 4.5 LTS from its official distribution, and Node.js. Run `uv sync --locked` and `npm --prefix site ci`. No OpenAI API account is needed for deterministic local work.

```sh
uv run python -m pipelines.run --demo --output outputs/demo-001 --clay --site-assets site/public/project
uv run python -m pipelines.web.server --port 5174
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

The viewer and PDF workflow share the local FastAPI server. Static Vite preview serves only the presentation; use the Python server for upload, review and generation. Cloud jobs and cloud storage are not implemented.

`--site-root path/to/site` selects another identical frontend source checkout for building/export validation. The normal default is the repository's `site/`; this option is useful when staging a clean installation or preparing an isolated review package.

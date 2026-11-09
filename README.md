# Architectural AI Visualizer — González Cardona

**MVP:** sube un plano PDF (+ descripción opcional de materiales) → revisa la interpretación de la IA junto al original → Blender genera renders y modelo 3D. Ver [guía rápida](docs/USER_GUIDE.md) y [estado](docs/IMPLEMENTATION_STATUS.md). Requiere `OPENAI_API_KEY` en el entorno del servidor.

Pipeline local y reproducible: **PDF → geometría métrica → Blender → QA → renders → GLB → visor web**.

La primera versión demuestra un plano sintético con perímetro de 10 × 7 m, seis muros, tres habitaciones, tres puertas y tres ventanas. La geometría se obtiene de los rectángulos dibujados y de sus anotaciones explícitas; no se carga un modelo oculto dentro del PDF. Los planos arbitrarios producen evidencia y una solicitud de revisión, no una reconstrucción supuestamente exacta.

## Ejecutar

Requisitos: Python 3.12–3.13, uv, Node.js 22.12+ y Blender 4.5 LTS. En macOS, Blender se detecta en `/Applications/Blender.app`; en otros sistemas, debe estar en PATH o en `BLENDER_BIN`.

```sh
uv sync --locked
npm --prefix site ci
npm --prefix site run build
uv run python -m pipelines.web.server --port 5174
```

Abre **http://127.0.0.1:5174/#new-project**. Sube el PDF, marca una cota conocida, revisa los contornos y completa las medidas. Confirma cada elemento y pulsa **Comprobar datos → Generar renders y 3D**. El servidor ejecuta Blender en segundo plano y muestra el resultado validado en el visor y la galería. Los borradores y resultados se conservan en `outputs/web-projects/`. No publica ni envía el PDF a servicios externos.

La revisión web admite una página y una planta por proyecto. En planos generales debes identificar los elementos: la detección de trazos no determina automáticamente muros, alturas o huecos. Para un render interior, delimita al menos una habitación. Las medidas desconocidas bloquean la generación.

Para crear también la demostración sintética del visor:

```sh
uv run python -m pipelines.run --demo --output outputs/demo-001 --clay --site-assets site/public/project
```

Para un PDF autorizado:

```sh
uv run python -m pipelines.run --input path/to/plan.pdf --output outputs/project-id
```

Un plano sin suficientes referencias verificadas se detiene con código 2. La ruta de la carpeta de revisión aparece en `run-status.json`. Después de revisar la evidencia y completar las medidas, puede suministrarse `--geometry reviewed.json`, usando el esquema de `pipelines/geometry/schema.py` y el SHA-256 del PDF original.

`--vision` habilita expresamente el envío del PDF a OpenAI Responses API para obtener propuestas semánticas. Requiere `OPENAI_API_KEY`; sus resultados no aprueban geometría. La conexión real no está validada si no hay credenciales. `.env.example` es una plantilla; exporta las variables en tu shell.

## Estructura

```text
pipelines/pdf/        extracción vectorial, raster y propuestas de visión
pipelines/geometry/   esquema Pydantic, referencias y normalización
pipelines/blender/    extrusión, huecos, materiales, cámaras, Cycles y GLB
pipelines/quality/    comparación independiente de malla, planta e imágenes
pipelines/web/        API local, revisión visual, trabajos y resultados persistidos
pipelines/run.py      orquestación transaccional y procedencia
site/                 React, TypeScript, Vite, Three.js, R3F y Drei
agents/               MCP Blender opcional, aislado y comprobado
.agents/skills/       seis workflows específicos del proyecto
scripts/              diagnóstico del entorno
tests/                pruebas de geometría, PDF, visión y QA
docs/                 arquitectura, guía y evidencia de ejecución
outputs/              artefactos generados privados, excluidos de Git
```

## Comprobar

```sh
uv run pytest -q
uv run ruff check .
npm --prefix site test
npm --prefix site run build
```

Consulta [resultados](docs/TEST_RESULTS.md), [estado de los 13 pasos](docs/IMPLEMENTATION_STATUS.md), [guía de uso](docs/USER_GUIDE.md), [arquitectura](docs/ARCHITECTURE.md) e [integración Sites](docs/SITES_DEPLOYMENT.md).

Los acabados son ilustrativos. Los huecos se respetan, pero las hojas de puerta y cristales son sólidos simplificados; no son detalles constructivos. No se añade una cubierta si el plano no la especifica. La demo no certifica fidelidad sobre planos reales ni sustituye su revisión profesional.

# Planos DWG / DXF

Además del PDF, puedes subir el plano en **DWG** (AutoCAD) o **DXF**. El dibujo se lee en este equipo. La IA solo recibe un resumen breve de lo que el programa no ha podido resolver solo, sin el archivo: una lista en texto y una imagen pequeña del plano con números. La lectura tarda unos segundos y la consulta a la IA 3–4 minutos (unos 0,20 $).

1. **Sube el plano.** Elige el `.dwg` o `.dxf` (máx. 50 MB). Verás el formato junto al nombre. La descripción de materiales funciona igual que con PDF.
2. **Elige la planta** si el dibujo contiene varias. El programa muestra una vista numerada de todas.
3. **Revisa.** A la izquierda tienes el dibujo DWG tal como está en el archivo; a la derecha, la interpretación. Debajo, el panel «Lectura del DWG» muestra:
   - la fuente, el conversor y su versión, y la huella SHA-256 del archivo;
   - las unidades, y si se leyeron del archivo (`$INSUNITS`) o se dedujeron;
   - las fichas de la IA: tokens de entrada y salida y coste estimado.

   Las lecturas aparecen separadas en cuatro grupos:
   - **Leído del DWG**: tomado directamente de capas, bloques y textos.
   - **Resuelto por la IA**: dudas que ha contestado la IA.
   - **Indicado por ti**: lo que has respondido tú.
   - **Pendiente**: lo que nadie ha resuelto todavía. Aparece en rojo sobre el plano.

   Mientras quede algo pendiente, no se puede aprobar. Elige la respuesta en cada punto y pulsa **Aplicar respuestas** (no gasta tokens). «No es mobiliario» y «Sin hueco» sirven para descartar un elemento.
4. **Aprueba y genera** como con el PDF.

## Instalar el conversor DWG → DXF

DWG es un formato cerrado; el programa lo convierte a DXF en este equipo, nunca en la nube.

- **ODA File Converter** (recomendado, gratuito): descárgalo de opendesign.com (*ODA File Converter*) e instálalo en `/Applications`. En Linux necesita un entorno gráfico o `xvfb-run`. Si está en otra ruta, indica `ODA_FILE_CONVERTER=/ruta/ODAFileConverter` al arrancar el servidor.
- **LibreDWG** (alternativa, código abierto): `brew install libredwg` en macOS, o `apt install libredwg-tools` en Linux. Lee bien hasta AutoCAD 2018, aunque avisa de algunos objetos dinámicos. Ruta propia: `DWG2DXF=/ruta/dwg2dxf`.

El programa usa ODA si está instalado y, si no, LibreDWG. Si falta un conversor, la web lo dice. También puedes exportar el DXF desde tu programa de CAD y subirlo directamente.

## Cómo preparar el DWG para la mejor lectura

- **Unidades:** define `UNITS`/`$INSUNITS` (mm, cm o m). Si no están definidas, se deducen del grosor de los muros, del tamaño y de las cotas, y se avisa. Si las declaradas no encajan con el dibujo, el plano se rechaza.
- **Espacio modelo:** se lee solo el espacio modelo, nunca las presentaciones. El cajetín y los rótulos lejanos quedan fuera porque se mira solo la planta. Si hay varias plantas dibujadas, se te pregunta cuál usar.
- **Capas:** se leen todas, también las apagadas, que se listan pero no se usan. El nombre se compara sin acentos ni mayúsculas, y se admiten erratas cercanas: `a.venatana` se lee como ventanas y se indica en la lista de capas. Nombres que funcionan:
  - Muros: `MUROS`, `TABIQUES`, `A-WALL`, `CERRAMIENTO`, `FABRICA`, «sección»/`a.secció` (muros cortados), `PILARES`. Mejor con sombreado sólido o polilíneas cerradas; también sirven pares de líneas paralelas.
  - Puertas: `PUERTAS`, `A-DOOR`. Ventanas: `VENTANAS`, `A-GLAZ`. Carpintería sin distinguir: `CARPINTERIA`.
  - Mobiliario: `MOBILIARIO`, `MUEBLES`, `a.moble`/`a.mobles`, `A-FURN`, `SANITARIOS`.
  - Ignoradas: cotas, `DIM`, `HABITABILIDAD`, cajetín, ejes y `DEMOLICION`. Los textos del cajetín dentro de la planta sí nombran estancias.
- **Bloques:** el nombre decide el tipo cuando es claro: `CAMA`/`LLIT`, `INODORO`/`WC`, `LAVABO`, `DUCHA`, `BAÑERA`, `SOFA`, `MESA`, `SILLA`, `ARMARIO`/`ARMARI`, `COCINA`/`ENCIMERA`, `NEVERA`, `LAVADORA`, `PUERTA`, `VENTANA` (la lista completa está en `pipelines/cad/config.py`). Los nombres sin significado (`A$C…`, bloques dinámicos `*U…`) se consultan a la IA. Para orientar las piezas se usan el giro y la simetría de la inserción. Además se comprueba que el respaldo apoye en un muro: el cabecero de la cama, la trasera del armario.
- **Huecos:** una puerta o ventana se reconoce por el hueco entre dos extremos de muro y la carpintería que hay dentro. Con un arco de giro dibujado, es abatible. Una carpintería sin hueco en el muro (una mampara, por ejemplo) no se modela y se avisa.
- **Estancias:** se nombran con el TEXT/MTEXT que hay dentro de cada recinto cerrado. El pavimento sale del rayado (`ANSI37`/`NET` → baldosa). Los rayados desconocidos se consultan a la IA o quedan «desconocido».

Los archivos se guardan en `outputs/web-projects/<id>/`, junto con el DXF convertido, el registro de conversión, la lectura (`cad-reading.json`) y la auditoría de la IA (`ai-audit/`). Nada de esto entra en Git. Variables opcionales del servidor: `AAV_DWG_IMAGE=0` quita la imagen de la consulta y `OPENAI_MODEL` cambia el modelo.

---

# Guía rápida — González Cardona (MVP)

1. **Sube el plano.** Abre http://127.0.0.1:5174/, elige el PDF (una planta, escala impresa como 1:50) y, si quieres, describe materiales: *“suelo de roble natural, paredes blanco roto, muebles de nogal, sofá de lino gris”*. Pulsa **Interpretar plano**. El PDF se envía a OpenAI.
2. **Revisa.** A la izquierda el plano original; a la derecha la interpretación de la IA (muros, puertas, ventanas, estancias y muebles). Comprueba estancias, materiales y supuestos. Puedes cambiar la descripción y pulsar **Actualizar materiales** sin volver a interpretar el plano. Si algo no encaja: **Volver a interpretar** o **Edición avanzada**.
3. **Genera.** Pulsa **Aprobar y generar renders**. Blender crea renders exterior, interior y axonometría, y el modelo 3D (GLB), visibles debajo y descargables.

**Qué revisar en el paso 2.** Los muebles salen del propio dibujo del PDF (contorno exacto); la IA decide qué es cada pieza y hacia dónde mira. En la vista de la IA, la flecha rosa de cada mueble señala su frente: pies de la cama, asiento del sofá, puertas del armario, frente del lavabo. Si la IA se equivoca, el sistema corrige automáticamente las piezas que deben apoyarse en un muro y las sillas (miran a su mesa), y lo anota en «Supuestos y dudas». Cada estancia muestra su pavimento leído del rayado (madera / baldosa).

**Renders.** Exterior, axonometría y un interior por estancia principal (hasta 4), con techo y luz cálida sólo en las vistas interiores. Estilo por defecto: lujo minimalista (roble natural, mármol Calacatta, travertino en baños, nogal, bouclé marfil, latón cepillado, carpintería negra). La descripción de materiales sustituye cualquiera de esos acabados.

La interpretación hace tres llamadas a OpenAI con razonamiento alto (muros y huecos, muebles y orientación, autorrevisión sobre el resultado dibujado); tarda varios minutos la primera vez. Un mismo PDF no vuelve a consumir tokens: la interpretación queda en caché. `#project=<id>` en la URL abre un proyecto concreto. Requisitos del servidor: `OPENAI_API_KEY` (y opcionalmente `OPENAI_MODEL`, por defecto `gpt-5.4`).

---

# Envío automático y comparación

Al subir un PDF, el servidor lo interpreta con OpenAI automáticamente si dispone de OPENAI_API_KEY. El aviso junto a la carga identifica el uso de la API. El PDF original aparece a la izquierda y la propuesta editable a la derecha; en pantallas estrechas se apilan. Los contornos son inferencias y requieren revisión.

La interpretación se reutiliza localmente para el mismo PDF, modelo y versión del prompt. El botón Interpretar recupera esa caché si existe; cambiar medidas en el editor no consume tokens. Los archivos y la caché permanecen en outputs/web-projects, fuera de Git. El consumo depende del documento y del modelo, no tiene un mínimo garantizado. La petición incluye coordenadas vectoriales y posiciones del texto para ayudar a localizar elementos. No se garantiza una interpretación perfecta.

---

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

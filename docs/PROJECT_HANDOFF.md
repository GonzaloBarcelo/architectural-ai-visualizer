# Architectural AI Visualizer — estado para continuar

Actualizado: 2026-11-09. Idioma del usuario: español.

## Objetivo y restricciones

Automatizar PDF arquitectónico → interpretación OpenAI → revisión visible junto al PDF → Blender → renders y GLB. El usuario autoriza enviar planos a OpenAI y consumo de tokens, solicita evitar llamadas duplicadas y acepta supuestos conceptuales visibles/editables. No publicar ni desplegar. No compartir PDFs privados ni claves en Git/chat. No prometer fidelidad perfecta.

## Repositorio y ejecución local

- Ruta: `/Users/gonzalobarcelo/Documents/workspace/MG-renders/architectural-ai-visualizer`.
- GitHub: `https://github.com/GonzaloBarcelo/architectural-ai-visualizer.git`.
- Rama: `codex/architectural-pipeline`.
- Web/API: `http://127.0.0.1:5174/` (FastAPI, loopback).
- Python validado: `/tmp/aav-validation-env/bin/python`. Dependencias frontend: `/tmp/aav-site-dependencies`. Son instalaciones temporales para evitar lecturas lentas de las dependencias originales del workspace.
- Arranque seguro del usuario: `/tmp/aav-validation-env/bin/python /Users/gonzalobarcelo/Documents/workspace/MG-renders/architectural-ai-visualizer/.tmp/start-with-key.py`.
- El lanzador pide la clave con getpass y usa `--reload`; conserva la clave solo en el entorno del proceso. NO inspeccionar el entorno de procesos para recuperar secretos. Los cambios en pipelines reinician el proceso: no editar backend durante una interpretación/render en curso.
- En un checkout nuevo: `uv sync --locked`, `npm --prefix site ci`, `npm --prefix site run build`, configurar OPENAI_API_KEY en el entorno y arrancar `uv run python -m pipelines.web.server`.

## Documento real de prueba

- PDF privado: `/Users/gonzalobarcelo/Downloads/EA_01_MOD.pdf`.
- Proyecto local principal: `e962045dcfad47d5a2722e1d1fd86d09`.
- Una página, plano vectorial, escala impresa 1:50. Vivienda con habitaciones, baños, salón/cocina, balcón y galería.
- Los resultados viven en `outputs/web-projects/<id>/`; están ignorados por Git.

## Arquitectura y decisiones

- `pipelines/pdf/extract.py`: PyMuPDF + raster; conversión recursiva de Point/Quad para evitar error JSON en planos reales.
- `pipelines/web/grounded.py`: NUEVO intérprete que calcula escala, enumera polígonos rellenos y huecos candidatos; OpenAI selecciona IDs/clasifica huecos y propone muebles. No genera coordenadas arbitrarias de muros.
- `pipelines/web/ai.py`: intérprete anterior y extracción de contexto vectorial. Se conserva para pruebas/referencia; el servidor importa ahora grounded.propose.
- `pipelines/web/review.py`: esquema Draft, validación y conversión a geometría. Conceptual conserva evidencia inferred, no verified.
- `pipelines/web/server.py`: extracción y OpenAI al subir, cola local, caché por hash/modelo/versión, revisiones optimistas, archivos permitidos, protección Host/Origin. `ai_interpretation` conserva respuesta original separada del borrador editable. Versión actual de caché: grounded-v3.
- `pipelines/geometry/schema.py`: geometría con furniture y modo conceptual explícito. El modo estricto sigue bloqueando inferencias.
- `pipelines/blender/build_scene.py`: modelado determinista; los huecos se cortan por booleanos dejando dinteles/antepechos. `furnish.py`: muebles paramétricos de presentación con procedencia inferred; se exportan a GLB.
- `site/src/Workflow.tsx`: original y propuesta en paralelo, selector para ver respuesta OpenAI sin corregir, propiedades/supuestos editables, progreso. `App.tsx` carga el manifiesto del proyecto.

## Evidencia anterior y limitaciones

Dos llamadas anteriores de gpt-4.1 fallaron interpretación (5.284 y 9.213 tokens): geometría/escala/unidades incoherentes. Nunca presentarlas como reconstrucción automática exitosa.

El run `2066bd98e6994019a2092a8f4f35b418` produjo tres renders y GLB después de una corrección asistida manual: 383 checks y GLB válido. Le faltaban dinteles, antepechos y carpinterías. NO usarlo como prueba del nuevo flujo automático.

El nuevo ensamblador admite PDF de una página con escala impresa única y polígonos rellenos. No resuelve de forma general planos escaneados, muros dibujados solo con líneas o varias escalas. El perímetro de suelo se aproxima por cierre geométrico. Muebles/acabados son propuestas conceptuales. Su representación paramétrica no es un catálogo de interiorismo fotorrealista.

## Validación al iniciar esta continuación

60 pruebas anteriores pasan. Tres nuevas pruebas de selección de candidatos, escala y conservación de huecos pasan. Frontend compila. Prueba real del intérprete grounded iniciada tras reinicio autorizado del usuario; falta registrar resultado y verificar Blender/GLB/browser.

## Estado MVP (2026-11-09, sesión Claude Code)

Flujo de 3 pasos y marca González Cardona implementados. El plano EA_01_MOD_1.pdf genera renders/GLB (518 QA) desde la selección gpt-5.4 en caché (`outputs/web-projects/ai-cache/selection-*.json`). Materiales por descripción: módulo `pipelines/web/materials.py`, probado con mocks; falta una llamada real. Detalle en IMPLEMENTATION_STATUS.md.

## Trabajo pendiente inmediato (histórico)

1. Consultar GET `/api/projects/e962045dcfad47d5a2722e1d1fd86d09`.
2. Inspeccionar `ai-grounded-response.json` (respuesta y uso reales) si el ensamblaje falla. No reutilizar corrección manual como si fuese automática.
3. Resolver errores generales del ensamblador/candidatos con pruebas; preservar trazabilidad y no rebajar QA para obtener éxito.
4. Validar propuesta con validate_draft antes de aceptar; revisar visualmente superposición, puertas/ventanas y muebles.
5. Ejecutar generación real y verificar renders/GLB en navegador.
6. Actualizar este archivo con resultados concretos, ejecutar pruebas relevantes y subir commits sin PDFs ni secretos.

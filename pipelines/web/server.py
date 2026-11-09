"""Loopback-only PDF review API and local production web server. No cloud or database.

Run: uv run python -m pipelines.web.server --port 5174
"""

import argparse
import json
import logging
import os
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import uvicorn
from fastapi import FastAPI, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from pipelines.cad.convert import convert
from pipelines.cad.convert import label as converter_label
from pipelines.common import ROOT, sha256, write_json
from pipelines.pdf.extract import extract
from pipelines.postprocess import enhance as enhancement
from pipelines.postprocess import location as places
from pipelines.run import run
from pipelines.web import dwg
from pipelines.web.grounded import propose
from pipelines.web.materials import MAX_DESCRIPTION, propose_finishes
from pipelines.web.review import Draft, draft_from_extraction, validate_draft

log = logging.getLogger(__name__)

MAX_UPLOAD = 50 * 1024**2
BUSY = {"queued", "running", "extracting"}
AI_STEPS = ("selection", "furniture", "review")
DWG_STEPS = ("reading", "doubts")
DWG_STEP_LABELS = ["Lectura del DWG", "Consulta de dudas a la IA"]
# Accepted sources: extension → format. Content is checked too (magic bytes / DXF header).
SOURCES = {".pdf": "pdf", ".dwg": "dwg", ".dxf": "dxf"}
ID_PATTERN = re.compile(r"^[a-f0-9]{32}$")


def timestamp():
    return datetime.now(UTC).isoformat()


class Revision(BaseModel):
    revision: int = Field(ge=0)


class SaveDraft(Revision):
    draft: Draft


class Description(Revision):
    description: str = Field(default="", max_length=MAX_DESCRIPTION)


class Approve(Revision):
    # "Mejorar renders con IA": illustrative OpenAI enhancement after the Blender renders.
    enhance: bool = True


class LocationEdit(Revision):
    text: str = Field(default="", max_length=300)


class Interpret(Revision):
    # DWG only: attach the labelled low-resolution plan image to the doubts call (None: default).
    image: bool | None = None


class PlanChoice(Revision):
    plan: int = Field(ge=0, le=50)


class CadAnswers(Revision):
    # Item id → answer fields (same shape as the AI answers, e.g. {"kind": ..., "front": ...}).
    answers: dict[str, dict] = Field(default_factory=dict, max_length=300)


def source_matches(fmt, head):
    """Content check of the first upload chunk for the declared format."""
    if fmt == "pdf":
        return head.startswith(b"%PDF-")
    if fmt == "dwg":
        return re.fullmatch(rb"AC10\d\d", head[:6]) is not None
    text = head[:4096]
    if text.startswith(b"AutoCAD Binary DXF"):
        return True
    try:
        decoded = text.decode("latin-1")
    except UnicodeDecodeError:
        return False
    return re.match(r"\s*(999\s*\n.*\n\s*)?0\s*\r?\nSECTION", decoded) is not None


class SiteFiles(StaticFiles):
    """Hashed /assets files may be cached; HTML never is, so a reload after a site rebuild always
    gets the index that references the current chunks (no stale "dynamically imported module")."""

    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        if response.headers.get("content-type", "").startswith("text/html"):
            response.headers["Cache-Control"] = "no-cache"
        return response


class LocalBoundary:
    """Reject foreign Hosts/Origins and cap bodies before multipart parsing consumes them."""

    def __init__(self, app, port):
        self.app = app
        self.hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = dict(scope["headers"])
        host = headers.get(b"host", b"").decode("latin1")
        origin = headers.get(b"origin", b"").decode("latin1")
        if host not in self.hosts or (origin and origin != "http://" + host):
            return await JSONResponse(
                {"detail": "Solo se permiten peticiones desde esta web local."}, status_code=403
            )(scope, receive, send)
        maximum = MAX_UPLOAD + 1024 * 1024 if scope["path"] == "/api/projects" else 2 * 1024 * 1024
        try:
            declared = int(headers.get(b"content-length", b"0"))
        except ValueError:
            declared = maximum + 1
        if declared > maximum:
            return await JSONResponse(
                {"detail": "El archivo supera el límite de 50 MiB."}, status_code=413
            )(scope, receive, send)
        received = 0

        async def limited_receive():
            nonlocal received
            message = await receive()
            received += len(message.get("body", b""))
            if received > maximum:
                raise HTTPException(413, "El cuerpo de la petición supera el límite permitido.")
            return message

        await self.app(scope, limited_receive, send)


class Projects:
    def __init__(self, root, site_dir, runner):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.site_dir = Path(site_dir).resolve()
        self.runner = runner
        self.lock = threading.RLock()
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="aav-worker")
        for path in self.root.glob("*/project.json"):
            try:
                value = json.loads(path.read_text())
                if value.get("status") in BUSY:
                    value.update(
                        status="failed",
                        stage="interrupted",
                        error="El servidor se interrumpió. Revisa el borrador y vuelve a generar; si no llegó a extraerse, vuelve a subir el PDF.",
                    )
                    self.save(value)
            except (OSError, ValueError, KeyError):
                continue

    def folder(self, ident):
        if not ID_PATTERN.fullmatch(ident):
            raise HTTPException(404, "Proyecto no encontrado.")
        return self.root / ident

    def get(self, ident):
        path = self.folder(ident) / "project.json"
        if not path.is_file():
            raise HTTPException(404, "Proyecto no encontrado.")
        return json.loads(path.read_text())

    def save(self, state):
        state["updated_at"] = timestamp()
        # When the stage changes, remember since when, so the UI can show elapsed time.
        if (state.get("stage_since") or {}).get("stage") != state.get("stage"):
            state["stage_since"] = {"stage": state.get("stage"), "at": state["updated_at"]}
            state["activity"] = None
        write_json(self.folder(state["id"]) / "project.json", state)
        return state

    def update(self, ident, **changes):
        with self.lock:
            state = self.get(ident)
            state.update(changes)
            self.save(state)

    def raw(self, ident):
        return json.loads((self.folder(ident) / "evidence/extraction.json").read_text())

    def check_revision(self, state, revision):
        if state["revision"] != revision:
            raise HTTPException(
                409,
                "El borrador ha cambiado en otra pestaña. Recarga el proyecto antes de continuar.",
            )
        if state["status"] in BUSY:
            raise HTTPException(409, "El proyecto está procesándose. Espera a que termine.")

    def ingest(self, ident):
        if self.get(ident).get("source_format", "pdf") != "pdf":
            return self.ingest_cad(ident)
        try:
            self.update(ident, status="extracting", stage="extracting")
            folder = self.folder(ident)
            raw = extract(folder / "source.pdf", folder / "evidence")
            state = self.get(ident)
            pages = []
            for page in raw["pages"]:
                candidates = []
                for drawing in page["drawings"]:
                    # A path bounding box is NOT geometry. Offer only actual drawn rectangles.
                    for item_index, item in enumerate(drawing["items"]):
                        if item[0] == "re":
                            x0, y0, x1, y1 = item[1]
                            if x1 - x0 > 1 and y1 - y0 > 1:
                                candidates.append(
                                    {
                                        "id": f"{drawing['index']}-{item_index}",
                                        "polygon": [[x0, y1], [x1, y1], [x1, y0], [x0, y0]],
                                        "label": f"Contorno {drawing['index'] + 1}",
                                    }
                                )
                pages.append(
                    {
                        "page": page["page"],
                        "width": page["size_points"][0],
                        "height": page["size_points"][1],
                        "image_url": f"/api/projects/{ident}/files/page-{page['page']}.png",
                        "type": page["type"],
                        "dimensions": page["dimensions"],
                        "candidates": candidates[:500],
                    }
                )
            draft = draft_from_extraction(raw, ident, Path(state["filename"]).stem)
            _, issues = validate_draft(draft, raw, ident)
            self.update(
                ident,
                status="review",
                stage="review",
                pages=pages,
                draft=draft,
                issues=issues,
                error=None,
                location=self.detect_location(ident),
            )
            self.update(ident, status="running", stage="interpreting")
            self.interpret(ident)
        except Exception as exc:
            log.exception("Local project operation failed")
            self.update(ident, status="failed", stage="extraction_failed", error=str(exc)[:3000])

    def ingest_cad(self, ident):
        """Convert a DWG locally, find its drawn plans and, with a single plan, read it."""
        try:
            self.update(ident, status="extracting", stage="reading_dwg")
            state = self.get(ident)
            folder = self.folder(ident)
            evidence = folder / "evidence"
            evidence.mkdir(exist_ok=True)
            path = folder / state["source_file"]
            converter = None
            if state["source_format"] == "dwg":
                dxf, converter = convert(path, evidence)
            else:
                dxf = path
            source = {
                "filename": state["filename"][:200],
                "sha256": sha256(path),
                "page_count": 1,
                "format": state["source_format"],
                "converter": converter_label(converter),
            }
            write_json(
                evidence / "cad-source.json",
                {**source, "dxf": dxf.name, "dxf_sha256": sha256(dxf)},
            )
            png, plans = dwg.overview(dxf)
            (evidence / "overview.png").write_bytes(png)
            self.update(
                ident, dxf_file=str(dxf.relative_to(folder)), cad_source=source, plans=plans
            )
            self.update(ident, location=self.detect_location(ident))
            if len(plans) > 1:
                self.update(ident, status="review", stage="choose_plan", error=None)
                return
            self.prepare_plan(ident, 0)
        except Exception as exc:
            log.exception("DWG reading failed")
            self.update(ident, status="failed", stage="extraction_failed", error=str(exc)[:3000])

    def prepare_plan(self, ident, index):
        """Render the chosen plan as the review sheet, then read and interpret it."""
        folder = self.folder(ident)
        state = self.get(ident)
        png, (width, height), _, _ = dwg.plan_sheet(folder / state["dxf_file"], index)
        (folder / "evidence" / "page-1.png").write_bytes(png)
        write_json(
            folder / "evidence/extraction.json",
            {
                "source": state["cad_source"],
                "cad": {"plan_index": index, "dxf": state["dxf_file"]},
                "pages": [
                    {
                        "page": 1,
                        "size_points": [width, height],
                        "type": state["source_format"],
                        "text": "",
                        "drawings": [],
                        "text_blocks": [],
                    }
                ],
            },
        )
        page = {
            "page": 1,
            "width": width,
            "height": height,
            "image_url": f"/api/projects/{ident}/files/page-1.png",
            "type": state["source_format"],
            "dimensions": [],
            "candidates": [],
        }
        draft = Draft(title=Path(state["filename"]).stem[:200] or "Proyecto").model_dump()
        self.update(
            ident,
            pages=[page],
            plan_index=index,
            draft=draft,
            issues=[],
            status="running",
            stage="interpreting",
            error=None,
        )
        self.interpret_cad(ident)

    def interpret_cad(self, ident, call_ai=True):
        """Deterministic DWG reading plus at most one AI call for its doubts."""
        try:
            state = self.get(ident)
            folder = self.folder(ident)
            attempts = {}

            def progress(step):
                attempts[step] = attempts.get(step, 0) + 1
                index = DWG_STEPS.index(step) + 1
                log.info("Project %s: DWG step %s/2 (%s)", ident, index, step)
                self.update(
                    ident,
                    activity={
                        "step": index,
                        "total": len(DWG_STEPS),
                        "label": step,
                        "labels": DWG_STEP_LABELS,
                        "started_at": timestamp(),
                        "attempt": attempts[step],
                    },
                )

            stored = None
            if not call_ai and (folder / "cad-ai.json").is_file():
                stored = json.loads((folder / "cad-ai.json").read_text())
            draft, summary, ai = dwg.propose(
                folder / state["dxf_file"],
                state["cad_source"],
                state.get("plan_index", 0),
                cache_dir=self.root / "ai-cache",
                audit_dir=folder / "ai-audit",
                progress=progress,
                user_answers=state.get("cad_answers"),
                stored_ai=stored,
                call_ai=call_ai,
                image=state.get("ai_image"),
            )
            draft["title"] = Path(state["filename"]).stem[:200] or draft["title"]
            write_json(folder / "cad-ai.json", ai)
            write_json(folder / "cad-reading.json", summary)
            write_json(folder / "ai-interpretation.json", draft)
            with self.lock:
                state = self.get(ident)
                state.update(
                    draft=draft,
                    cad=summary,
                    ai_usage={"plan": summary["ai"]},
                    ai_interpretation=draft,
                    revision=state["revision"] + 1,
                    error=None,
                    ai_error_type=None,
                )
                state.pop("manifest_url", None)
                self.save(state)
            if (self.get(ident).get("description") or "").strip():
                self.update(ident, stage="materials")
            self.apply_finishes(ident)
        except Exception as exc:
            log.exception("DWG interpretation failed")
            self.update(
                ident,
                status="review",
                stage="review",
                error="No se pudo leer el plano DWG/DXF ("
                + type(exc).__name__
                + ": "
                + str(exc)[:600]
                + ").",
                ai_error_type=type(exc).__name__,
            )

    def interpret(self, ident):
        if self.get(ident).get("source_format", "pdf") != "pdf":
            return self.interpret_cad(ident)
        try:
            raw = self.raw(ident)
            cache = self.root / "ai-cache"
            attempts = {}

            def progress(step):
                attempts[step] = attempts.get(step, 0) + 1
                index = AI_STEPS.index(step) + 1 if step in AI_STEPS else 0
                log.info("Project %s: AI step %s/%s (%s)", ident, index, len(AI_STEPS), step)
                activity = {
                    "step": index,
                    "total": len(AI_STEPS),
                    "label": step,
                    "started_at": timestamp(),
                    "attempt": attempts[step],
                }
                self.update(ident, activity=activity)

            draft, usage = propose(
                self.folder(ident) / "source.pdf", raw, cache_dir=cache, progress=progress
            )
            draft["title"] = Path(self.get(ident)["filename"]).stem[:200] or draft["title"]
            write_json(self.folder(ident) / "ai-interpretation.json", draft)
            with self.lock:
                state = self.get(ident)
                state.update(
                    draft=draft,
                    ai_usage={"plan": usage},
                    ai_interpretation=draft,
                    revision=state["revision"] + 1,
                    error=None,
                    ai_error_type=None,
                )
                state.pop("manifest_url", None)
                self.save(state)
            if (self.get(ident).get("description") or "").strip():
                self.update(ident, stage="materials")
            self.apply_finishes(ident)
        except Exception as exc:
            log.exception("AI interpretation failed")
            missing_key = "OPENAI_API_KEY" in str(exc)
            self.update(
                ident,
                status="review",
                stage="review",
                error=(
                    "La interpretación automática necesita OPENAI_API_KEY en el servidor."
                    if missing_key
                    else "No se pudo interpretar el plano con OpenAI ("
                    + type(exc).__name__
                    + ": "
                    + str(exc)[:400]
                    + "). Puedes reintentarlo o usar la edición manual."
                ),
                ai_error_type=type(exc).__name__,
            )

    def apply_finishes(self, ident):
        """Turn the client's optional description into render finishes on the current draft."""
        state = self.get(ident)
        description = state.get("description") or ""
        notes, usage, error = [], None, None
        try:
            finishes, notes, usage = propose_finishes(description, self.root / "ai-cache")
        except Exception as exc:
            log.exception("Finish proposal failed")
            finishes = {}
            error = "No se pudieron interpretar los materiales; se usan acabados por defecto."
            if "OPENAI_API_KEY" in str(exc):
                error = "Los materiales necesitan OPENAI_API_KEY; se usan acabados por defecto."
        with self.lock:
            state = self.get(ident)
            draft = state.get("draft")
            if draft:
                keep = [a for a in draft.get("assumptions", []) if not a.startswith("Acabados")]
                summary = (
                    ["Acabados ilustrativos según la descripción del cliente: " + description]
                    if finishes
                    else [
                        "Acabados: paleta del estudio, lujo minimalista (roble, mármol, latón, bouclé)."
                    ]
                )
                draft.update(
                    finishes=finishes,
                    assumptions=(keep + summary + [f"Acabados — {n}" for n in notes])[:100],
                )
                if error:
                    draft["assumptions"].append("Acabados: " + error)
                state["draft"] = draft
                state["revision"] += 1
            state.update(status="review", stage="review", finishes_error=error)
            state.setdefault("ai_usage", {})
            if isinstance(state["ai_usage"], dict):
                state["ai_usage"]["finishes"] = usage
            _, issues = validate_draft(draft, self.raw(ident), ident) if draft else (None, [])
            state["issues"] = issues
            state.pop("manifest_url", None)
            self.save(state)

    def detect_location(self, ident):
        """Location read from the drawing's own text; never fails the caller."""
        try:
            return enhancement.detect(self.folder(ident), self.get(ident))
        except Exception:
            log.exception("Location detection failed")
            return places.missing()

    def location_of(self, ident):
        """Stored location; projects created before this feature are read once, lazily."""
        with self.lock:
            state = self.get(ident)
            if state.get("location") is None and state.get("pages"):
                state["location"] = self.detect_location(ident)
                self.save(state)
            return state.get("location") or places.missing()

    def record_enhancement(self, state, output):
        try:
            summary = json.loads((output / "manifest.json").read_text()).get("enhancement")
        except (OSError, ValueError):
            summary = None
        if summary:
            state["enhancement"] = summary
            usage = state.get("ai_usage") if isinstance(state.get("ai_usage"), dict) else {}
            state["ai_usage"] = {**usage, "enhancement": enhancement.usage_of(summary)}

    def enhance_options(self, ident, state):
        folder = self.folder(ident)
        return {
            "location": self.location_of(ident),
            "description": state.get("description") or "",
            "cache_dir": self.root / "ai-cache",
            "audit_dir": folder / "ai-audit",
        }

    def activity(self, ident):
        return lambda payload: self.update(ident, activity=payload)

    def enhance_job(self, ident):
        """«Mejorar de nuevo»: only the enhancement step, on the delivered renders."""
        folder = self.folder(ident)
        state = self.get(ident)
        output = folder / state["result"]
        try:
            enhancement.safe_run(
                output,
                progress=self.activity(ident),
                force=True,
                **self.enhance_options(ident, state),
            )
        except Exception:
            log.exception("Enhancement rerun failed")
        with self.lock:
            state = self.get(ident)
            self.record_enhancement(state, output)
            base = (state.get("manifest_url") or "").split("&e=")[0]
            state.update(
                status="succeeded",
                stage="completed",
                error=None,
                manifest_url=f"{base}&e={uuid4().hex[:8]}" if base else None,
            )
            self.save(state)

    def finishes_job(self, ident):
        try:
            self.apply_finishes(ident)
        except Exception as exc:
            log.exception("Finish update failed")
            self.update(ident, status="review", stage="review", error=str(exc)[:500])

    def generate(self, ident, geometry, revision):
        folder = self.folder(ident)
        try:
            self.update(ident, status="running", stage="modeling", error=None)
            # Unique run directories preserve prior results; a new revision cannot expose old output as new.
            output = folder / "runs" / uuid4().hex
            approved = folder / f"approved-{revision}.json"
            write_json(approved, geometry.model_dump())
            state = self.get(ident)
            enhance = bool(state.get("enhance", True)) and enhancement.enabled_by_env()
            args = SimpleNamespace(
                input=folder / self.get(ident).get("source_file", "source.pdf"),
                output=output,
                demo=False,
                geometry=approved,
                vision=False,
                device="auto",
                resolution=1600,
                samples=160,
                clay=False,
                site_assets=None,
                site_root=self.site_dir,
                progress=lambda stage: self.update(ident, stage=stage),
                activity=self.activity(ident),
                enhance=enhance,
                enhancement=self.enhance_options(ident, state),
            )
            self.runner(args)
            status = json.loads((output / "run-status.json").read_text())
            if not status.get("passed") or not (output / "manifest.json").is_file():
                raise ValueError("La generación no produjo una entrega validada.")
            with self.lock:
                state = self.get(ident)
                self.record_enhancement(state, output)
                state.update(
                    status="succeeded",
                    stage="completed",
                    error=None,
                    result=str(output.relative_to(folder)),
                    manifest_url=f"/api/projects/{ident}/files/manifest.json?v={output.name}",
                    result_revision=revision,
                )
                self.save(state)
        except Exception as exc:
            log.exception("Local project operation failed")
            self.update(ident, status="failed", stage="generation_failed", error=str(exc)[:3000])


def create_app(
    data_dir=ROOT / "outputs/web-projects", site_dir=ROOT / "site", pipeline_runner=None, port=5174
):
    package_log = logging.getLogger("pipelines")
    if not package_log.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        package_log.addHandler(handler)
        package_log.setLevel(logging.INFO)
    projects = Projects(data_dir, site_dir, pipeline_runner or run)

    @asynccontextmanager
    async def lifespan(app):
        yield
        projects.executor.shutdown(wait=True, cancel_futures=True)

    app = FastAPI(
        title="Architectural AI Visualizer — Local",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.projects = projects
    app.add_middleware(LocalBoundary, port=port)

    @app.get("/api/health")
    def health():
        return {"status": "ok", "local_only": True}

    @app.get("/api/projects")
    def listing():
        with projects.lock:
            states = [json.loads(p.read_text()) for p in projects.root.glob("*/project.json")]
        keys = ["id", "filename", "status", "stage", "error", "updated_at", "source_format"]
        return {
            "projects": [
                {k: s.get(k) for k in keys}
                for s in sorted(states, key=lambda s: s["updated_at"], reverse=True)
            ]
        }

    @app.post("/api/projects", status_code=202)
    async def upload(file: UploadFile, description: str = Form(default="")):
        filename = Path((file.filename or "plano.pdf").replace("\\", "/")).name[:200]
        suffix = Path(filename).suffix.lower()
        if suffix not in SOURCES:
            raise HTTPException(415, "Selecciona un plano en PDF, DWG o DXF.")
        fmt = SOURCES[suffix]
        stored = f"source{suffix}"
        if len(description) > MAX_DESCRIPTION:
            raise HTTPException(422, f"La descripción admite hasta {MAX_DESCRIPTION} caracteres.")
        ident = uuid4().hex
        folder = projects.folder(ident)
        folder.mkdir()
        size = 0
        label = {"pdf": "El PDF", "dwg": "El DWG", "dxf": "El DXF"}[fmt]
        try:
            with (folder / stored).open("wb") as stream:
                while chunk := await file.read(1024 * 1024):
                    if size == 0 and not source_matches(fmt, chunk):
                        raise HTTPException(
                            415, f"El contenido no es un archivo {fmt.upper()} válido."
                        )
                    size += len(chunk)
                    if size > MAX_UPLOAD:
                        raise HTTPException(413, f"{label} supera el límite de 50 MiB.")
                    stream.write(chunk)
            if size == 0:
                raise HTTPException(415, f"{label} está vacío.")
        except Exception:
            (folder / stored).unlink(missing_ok=True)
            folder.rmdir()
            raise
        finally:
            await file.close()
        with projects.lock:
            state = projects.save(
                {
                    "id": ident,
                    "filename": filename,
                    "description": description.strip(),
                    "source_format": fmt,
                    "source_file": stored,
                    "status": "extracting",
                    "stage": "extracting" if fmt == "pdf" else "reading_dwg",
                    "revision": 0,
                    "pages": [],
                    "draft": None,
                    "issues": [],
                    "error": None,
                }
            )
            projects.executor.submit(projects.ingest, ident)
        return state

    @app.get("/api/projects/{ident}")
    def detail(ident: str):
        projects.location_of(ident)
        with projects.lock:
            return {**projects.get(ident), "enhance_server": enhancement.enabled_by_env()}

    @app.put("/api/projects/{ident}/location")
    def edit_location(ident: str, body: LocationEdit):
        """The user's correction of the detected location (illustrative context only)."""
        previous = projects.location_of(ident)
        with projects.lock:
            state = projects.get(ident)
            projects.check_revision(state, body.revision)
            text = body.text.strip()
            if text and previous.get("status") != "missing" and text == previous.get("text"):
                return state
            state["location"] = places.user_location(text, previous)
            # The location never changes geometry: a delivered result stays valid.
            current = state.get("result_revision") == state["revision"]
            state["revision"] += 1
            if current:
                state["result_revision"] = state["revision"]
            return projects.save(state)

    @app.post("/api/projects/{ident}/enhance", status_code=202)
    def enhance_again(ident: str, body: Revision):
        """«Mejorar de nuevo»: rerun only the AI enhancement on the delivered renders."""
        with projects.lock:
            state = projects.get(ident)
            projects.check_revision(state, body.revision)
            if state["status"] != "succeeded" or state.get("result_revision") != state["revision"]:
                raise HTTPException(409, "No hay renders terminados de esta revisión que mejorar.")
            if not enhancement.enabled_by_env():
                raise HTTPException(409, "La mejora con IA está desactivada en este servidor.")
            state.update(status="running", stage="enhancing", error=None)
            projects.save(state)
            projects.executor.submit(projects.enhance_job, ident)
            return state

    @app.put("/api/projects/{ident}/draft")
    def save_draft(ident: str, body: SaveDraft):
        with projects.lock:
            state = projects.get(ident)
            projects.check_revision(state, body.revision)
            if not state.get("pages"):
                raise HTTPException(409, "Primero debe completarse la extracción del PDF.")
            draft = body.draft.model_dump()
            _, issues = validate_draft(draft, projects.raw(ident), ident)
            state.update(
                draft=draft,
                revision=state["revision"] + 1,
                status="review",
                stage="review",
                issues=issues,
                error=None,
            )
            state.pop("manifest_url", None)
            return projects.save(state)

    @app.post("/api/projects/{ident}/interpret", status_code=202)
    def interpret_project(ident: str, body: Interpret):
        with projects.lock:
            state = projects.get(ident)
            projects.check_revision(state, body.revision)
            if not state.get("pages"):
                raise HTTPException(409, "Primero debe completarse la extracción del PDF.")
            pdf = state.get("source_format", "pdf") == "pdf"
            if pdf and (projects.folder(ident) / "source.pdf").stat().st_size > 20 * 1024**2:
                raise HTTPException(413, "OpenAI admite aquí PDF de hasta 20 MiB.")
            state.update(status="running", stage="interpreting", error=None)
            if not pdf:
                state["ai_image"] = body.image
            projects.save(state)
            projects.executor.submit(projects.interpret, ident)
            return state

    @app.post("/api/projects/{ident}/plan", status_code=202)
    def choose_plan(ident: str, body: PlanChoice):
        """DWG with several drawn plans: the user picks the one to model."""
        with projects.lock:
            state = projects.get(ident)
            projects.check_revision(state, body.revision)
            if state.get("source_format", "pdf") == "pdf" or not state.get("plans"):
                raise HTTPException(409, "Este proyecto no tiene plantas DWG que elegir.")
            if body.plan >= len(state["plans"]):
                raise HTTPException(422, "La planta elegida no existe en el dibujo.")
            state.update(status="extracting", stage="reading_dwg", error=None, cad_answers={})
            projects.save(state)
            projects.executor.submit(projects.prepare_plan, ident, body.plan)
            return state

    @app.put("/api/projects/{ident}/answers", status_code=202)
    def answer_doubts(ident: str, body: CadAnswers):
        """The user's answers to pending DWG readings; applied without any AI call."""
        with projects.lock:
            state = projects.get(ident)
            projects.check_revision(state, body.revision)
            cad = state.get("cad")
            if not cad:
                raise HTTPException(409, "Este proyecto no tiene lecturas DWG pendientes.")
            types = {i["id"]: i["type"] for i in cad.get("pending", [])}
            stored = dict(state.get("cad_answers") or {})
            for ident_item, value in body.answers.items():
                kind = types.get(ident_item)
                if kind is None:
                    raise HTTPException(422, f"{ident_item}: no es una lectura pendiente.")
                field, model = dwg.ANSWER_TYPES[kind]
                try:
                    answer = model.model_validate({**value, "id": ident_item}).model_dump()
                except ValueError as exc:
                    raise HTTPException(422, f"{ident_item}: respuesta no válida.") from exc
                stored.setdefault(field, [])
                stored[field] = [a for a in stored[field] if a["id"] != ident_item] + [answer]
            state.update(cad_answers=stored, status="running", stage="resolving", error=None)
            projects.save(state)
            projects.executor.submit(projects.interpret_cad, ident, False)
            return state

    @app.post("/api/projects/{ident}/validate")
    def validate(ident: str, body: Revision):
        with projects.lock:
            state = projects.get(ident)
            projects.check_revision(state, body.revision)
            if not state.get("pages"):
                raise HTTPException(409, "Primero debe completarse la extracción del PDF.")
            _, issues = validate_draft(state.get("draft"), projects.raw(ident), ident)
            state["issues"] = issues
            return projects.save(state)

    @app.put("/api/projects/{ident}/description", status_code=202)
    def update_description(ident: str, body: Description):
        with projects.lock:
            state = projects.get(ident)
            projects.check_revision(state, body.revision)
            if not state.get("draft"):
                raise HTTPException(409, "Primero debe completarse la extracción del PDF.")
            state.update(
                description=body.description.strip(),
                status="running",
                stage="materials",
                error=None,
            )
            projects.save(state)
            projects.executor.submit(projects.finishes_job, ident)
            return state

    @app.post("/api/projects/{ident}/approve", status_code=202)
    def approve(ident: str, body: Approve):
        """Explicit user approval of the AI interpretation, then Blender generation."""
        with projects.lock:
            state = projects.get(ident)
            projects.check_revision(state, body.revision)
            draft = state.get("draft")
            if not draft or not draft.get("conceptual"):
                raise HTTPException(
                    409, "No hay una interpretación de la IA que aprobar; usa la edición manual."
                )
            blocking = [p for p in (state.get("cad") or {}).get("pending", []) if p["blocking"]]
            if blocking:
                raise HTTPException(
                    409,
                    f"Quedan {len(blocking)} lecturas del DWG sin resolver. Resuélvelas en "
                    "«Pendiente» (o márcalas como no modeladas) antes de aprobar.",
                )
            draft["calibration"]["confirmed"] = True
            draft["floor"]["confirmed"] = True
            for entity in draft["entities"]:
                entity["confirmed"] = True
            draft["complete"] = True
            geometry, issues = validate_draft(draft, projects.raw(ident), ident)
            if issues:
                state["issues"] = issues
                projects.save(state)
                raise HTTPException(
                    422, {"message": "La interpretación no es coherente.", "issues": issues}
                )
            revision = state["revision"] + 1
            state.update(
                draft=draft,
                revision=revision,
                status="queued",
                stage="queued",
                error=None,
                issues=[],
                enhance=body.enhance,
            )
            state.pop("manifest_url", None)
            projects.save(state)
            projects.executor.submit(projects.generate, ident, geometry, revision)
            return state

    @app.post("/api/projects/{ident}/generate", status_code=202)
    def generate(ident: str, body: Revision):
        with projects.lock:
            state = projects.get(ident)
            projects.check_revision(state, body.revision)
            if not state.get("draft"):
                raise HTTPException(422, {"message": "El plano necesita revisión.", "issues": []})
            geometry, issues = validate_draft(state["draft"], projects.raw(ident), ident)
            if issues:
                state["issues"] = issues
                projects.save(state)
                raise HTTPException(
                    422,
                    {
                        "message": "Completa y confirma los datos antes de generar.",
                        "issues": issues,
                    },
                )
            state.update(status="queued", stage="queued", error=None, issues=[])
            state.pop("manifest_url", None)
            projects.save(state)
            projects.executor.submit(projects.generate, ident, geometry, body.revision)
            return state

    @app.get("/api/projects/{ident}/files/{filename:path}")
    def files(ident: str, filename: str):
        with projects.lock:
            state = projects.get(ident)
        folder = projects.folder(ident)
        if filename == "source.pdf":
            return FileResponse(
                folder / "source.pdf", media_type="application/pdf", filename=state["filename"]
            )
        if filename == "overview.png" and state.get("plans"):
            return FileResponse(
                folder / "evidence/overview.png", headers={"Cache-Control": "no-store"}
            )
        page_match = re.fullmatch(r"page-([1-9][0-9]?)\.png", filename)
        if page_match:
            if int(page_match[1]) > len(state.get("pages", [])):
                raise HTTPException(404, "Página no encontrada.")
            return FileResponse(
                folder / "evidence" / filename, headers={"Cache-Control": "no-store"}
            )
        allowed = {
            "manifest.json",
            "model.glb",
            "geometry.json",
            "quality-report.json",
            "scene.blend",
        }
        render = re.fullmatch(
            r"renders/(enhanced/)?(exterior|axonometric|interior(-[2-9])?)\.webp", filename
        )
        # While only the enhancement reruns, the delivered result stays viewable.
        delivered = state["status"] == "succeeded" or (
            state["status"] == "running" and state.get("stage") == "enhancing"
        )
        if (
            (filename not in allowed and not render)
            or not delivered
            or not state.get("result")
            or state.get("result_revision") != state["revision"]
        ):
            raise HTTPException(404, "Resultado no disponible o pendiente de nueva validación.")
        path = folder / state["result"] / filename
        if not path.is_file():
            raise HTTPException(404, "Este recurso no fue generado para el proyecto.")
        return FileResponse(path, headers={"Cache-Control": "no-store"})

    # Mounted last; /api routes never fall through to arbitrary filesystem paths.
    dist = Path(site_dir) / "dist"
    if dist.is_dir():
        app.mount("/", SiteFiles(directory=dist, html=True), name="web")
    return app


def configured_app():
    return create_app(
        Path(os.environ["AAV_DATA_DIR"]),
        Path(os.environ["AAV_SITE_ROOT"]),
        port=int(os.environ["AAV_PORT"]),
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=5174)
    parser.add_argument("--data-dir", type=Path, default=ROOT / "outputs/web-projects")
    parser.add_argument("--site-root", type=Path, default=ROOT / "site")
    parser.add_argument(
        "--reload",
        action="store_true",
        help="Local development reload; retains API key in parent process",
    )
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("Use a local port from 1024 to 65535.")
    if not (args.site_root / "dist/index.html").is_file():
        parser.error("Build the web app first: npm --prefix site run build")
    os.environ.update(
        AAV_DATA_DIR=str(args.data_dir.resolve()),
        AAV_SITE_ROOT=str(args.site_root.resolve()),
        AAV_PORT=str(args.port),
    )
    uvicorn.run(
        "pipelines.web.server:configured_app"
        if args.reload
        else create_app(args.data_dir, args.site_root, port=args.port),
        factory=args.reload,
        reload=args.reload,
        reload_dirs=[str(ROOT / "pipelines")] if args.reload else None,
        host="127.0.0.1",
        port=args.port,
        workers=1,
    )


if __name__ == "__main__":
    main()

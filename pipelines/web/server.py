"""Loopback-only PDF review API and local production web server. No cloud or database.

Run: uv run python -m pipelines.web.server --port 5174
"""

import argparse
import json
import logging
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import uvicorn
from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from pipelines.common import ROOT, write_json
from pipelines.pdf.extract import extract
from pipelines.run import run
from pipelines.web.review import Draft, draft_from_extraction, validate_draft

log = logging.getLogger(__name__)

MAX_UPLOAD = 50 * 1024**2
BUSY = {"queued", "running", "extracting"}
ID_PATTERN = re.compile(r"^[a-f0-9]{32}$")


def timestamp():
    return datetime.now(UTC).isoformat()


class Revision(BaseModel):
    revision: int = Field(ge=0)


class SaveDraft(Revision):
    draft: Draft


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
            )
        except Exception as exc:
            log.exception("Local project operation failed")
            self.update(ident, status="failed", stage="extraction_failed", error=str(exc)[:3000])

    def generate(self, ident, geometry, revision):
        folder = self.folder(ident)
        try:
            self.update(ident, status="running", stage="modeling", error=None)
            # Unique run directories preserve prior results; a new revision cannot expose old output as new.
            output = folder / "runs" / uuid4().hex
            approved = folder / f"approved-{revision}.json"
            write_json(approved, geometry.model_dump())
            args = SimpleNamespace(
                input=folder / "source.pdf",
                output=output,
                demo=False,
                geometry=approved,
                vision=False,
                device="auto",
                resolution=960,
                samples=64,
                clay=False,
                site_assets=None,
                site_root=self.site_dir,
                progress=lambda stage: self.update(ident, stage=stage),
            )
            self.runner(args)
            status = json.loads((output / "run-status.json").read_text())
            if not status.get("passed") or not (output / "manifest.json").is_file():
                raise ValueError("La generación no produjo una entrega validada.")
            self.update(
                ident,
                status="succeeded",
                stage="completed",
                error=None,
                result=str(output.relative_to(folder)),
                manifest_url=f"/api/projects/{ident}/files/manifest.json?v={output.name}",
                result_revision=revision,
            )
        except Exception as exc:
            log.exception("Local project operation failed")
            self.update(ident, status="failed", stage="generation_failed", error=str(exc)[:3000])


def create_app(
    data_dir=ROOT / "outputs/web-projects", site_dir=ROOT / "site", pipeline_runner=None, port=5174
):
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
        keys = ["id", "filename", "status", "stage", "error", "updated_at"]
        return {
            "projects": [
                {k: s.get(k) for k in keys}
                for s in sorted(states, key=lambda s: s["updated_at"], reverse=True)
            ]
        }

    @app.post("/api/projects", status_code=202)
    async def upload(file: UploadFile):
        filename = Path((file.filename or "plano.pdf").replace("\\", "/")).name[:200]
        if not filename.lower().endswith(".pdf"):
            raise HTTPException(415, "Selecciona un archivo PDF.")
        ident = uuid4().hex
        folder = projects.folder(ident)
        folder.mkdir()
        size = 0
        try:
            with (folder / "source.pdf").open("wb") as stream:
                while chunk := await file.read(1024 * 1024):
                    if size == 0 and not chunk.startswith(b"%PDF-"):
                        raise HTTPException(415, "El contenido no es un documento PDF válido.")
                    size += len(chunk)
                    if size > MAX_UPLOAD:
                        raise HTTPException(413, "El PDF supera el límite de 50 MiB.")
                    stream.write(chunk)
            if size == 0:
                raise HTTPException(415, "El PDF está vacío.")
        except Exception:
            (folder / "source.pdf").unlink(missing_ok=True)
            folder.rmdir()
            raise
        finally:
            await file.close()
        with projects.lock:
            state = projects.save(
                {
                    "id": ident,
                    "filename": filename,
                    "status": "extracting",
                    "stage": "extracting",
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
        with projects.lock:
            return projects.get(ident)

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
            "renders/exterior.webp",
            "renders/interior.webp",
            "renders/axonometric.webp",
        }
        if (
            filename not in allowed
            or state["status"] != "succeeded"
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
        app.mount("/", StaticFiles(directory=dist, html=True), name="web")
    return app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=5174)
    parser.add_argument("--data-dir", type=Path, default=ROOT / "outputs/web-projects")
    parser.add_argument("--site-root", type=Path, default=ROOT / "site")
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("Use a local port from 1024 to 65535.")
    if not (args.site_root / "dist/index.html").is_file():
        parser.error("Build the web app first: npm --prefix site run build")
    uvicorn.run(
        create_app(args.data_dir, args.site_root, port=args.port),
        host="127.0.0.1",
        port=args.port,
        workers=1,
    )


if __name__ == "__main__":
    main()

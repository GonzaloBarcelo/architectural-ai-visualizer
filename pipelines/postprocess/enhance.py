"""Illustrative AI enhancement of finished Blender renders (OpenAI image edits).

Runs after all renders passed QA. Every view is edited independently (small concurrency),
checked for geometric drift against its original and, if it drifted, retried once with a
stricter prompt; a second failure keeps the original. Failures never fail the run: the
original renders are always delivered. Enhanced images are illustrative only and never feed
back into geometry, dimensions or the GLB.

CLI (no Blender; reuses the renders of a finished project):
    python -m pipelines.postprocess.enhance outputs/web-projects/<id> [--force]
"""

import argparse
import base64
import hashlib
import io
import json
import logging
import os
import shutil
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from PIL import Image

from pipelines.common import ROOT, write_json
from pipelines.postprocess import fidelity as F
from pipelines.postprocess.location import describe, from_dxf, from_pdf, missing
from pipelines.postprocess.prompt import PROMPT_VERSION, compose, master_style, view_type

log = logging.getLogger(__name__)

DEFAULT_MODEL = "gpt-image-2.5-sunburst"
# USD per 1M tokens (text input, image input, image output), Standard tier, from
# https://developers.openai.com/api/docs/pricing, checked 2026-11-09. Longest prefix wins.
PRICES = {
    "gpt-image-2": (5.0, 8.0, 30.0),
    "gpt-image-1.5": (5.0, 8.0, 32.0),
    "chatgpt-image": (5.0, 8.0, 30.0),
}
LABEL = "Imagen mejorada con IA · ilustrativa"
REJECTED = "mejora rechazada: deriva geométrica"
NOTICES = {
    "disabled": "Mejora con IA desactivada: se muestran los renders originales de Blender.",
    "unavailable": "La mejora con IA necesita OPENAI_API_KEY en el servidor; se muestran los "
    "renders originales de Blender.",
    "failed": "La mejora con IA no se pudo completar; se muestran los renders originales de "
    "Blender.",
    "partial": "Algunas imágenes no se mejoraron (deriva geométrica o error); en ellas se "
    "muestra el render original de Blender.",
    "rejected": "La IA alteró la geometría en todas las imágenes (deriva geométrica); se "
    "muestran los renders originales de Blender.",
    "completed": "Imágenes mejoradas con IA a partir de los renders de Blender: ilustrativas, "
    "no sustituyen a la geometría del plano.",
}


def enabled_by_env():
    """Server-wide switch: AAV_ENHANCE=0 disables the enhancement step."""
    return os.getenv("AAV_ENHANCE", "1").strip().lower() not in ("0", "false", "no", "off")


@dataclass
class Settings:
    model: str = field(default_factory=lambda: os.getenv("OPENAI_IMAGE_MODEL", DEFAULT_MODEL))
    quality: str = field(default_factory=lambda: os.getenv("OPENAI_IMAGE_QUALITY", "high"))
    complexity: str | None = field(
        default_factory=lambda: os.getenv("OPENAI_IMAGE_COMPLEXITY") or None
    )
    concurrency: int = 3
    timeout: float = 300.0
    axonometric: bool = field(
        default_factory=lambda: os.getenv("AAV_ENHANCE_AXONOMETRIC", "1") != "0"
    )
    upscale: bool = True
    threshold: float = F.THRESHOLD
    max_shift: float = F.MAX_SHIFT


def price(model):
    key = max((k for k in PRICES if model.startswith(k)), key=len, default="gpt-image-2")
    return PRICES[key]


def cost_of(model, usage):
    """Estimated USD of one image edit from its reported token usage."""
    if not usage:
        return None
    text_in, image_in, image_out = price(model)
    details = usage.get("input_tokens_details") or {}
    out_details = usage.get("output_tokens_details") or {}
    text = details.get("text_tokens")
    image = details.get("image_tokens")
    if text is None and image is None:
        text, image = 0, usage.get("input_tokens", 0)
    output_image = out_details.get("image_tokens", usage.get("output_tokens", 0))
    output_text = out_details.get("text_tokens", 0) if out_details else 0
    total = (text or 0) * text_in + (image or 0) * image_in + output_image * image_out
    total += output_text * text_in
    return round(total / 1e6, 4)


def supports_input_fidelity(model):
    # Documented for gpt-image-1.5 (and the retired gpt-image-1); the gpt-image-2 family
    # always processes inputs at high fidelity and the parameter must be omitted.
    return model.startswith("gpt-image-1") and "mini" not in model


RETRYABLE = ("APITimeoutError", "APIConnectionError", "RateLimitError", "InternalServerError")


class Enhancer:
    def __init__(
        self,
        output,
        location=None,
        description="",
        settings=None,
        client=None,
        cache_dir=None,
        audit_dir=None,
        progress=None,
        force=False,
    ):
        self.output = Path(output)
        self.location = location or missing()
        self.description = description or ""
        self.settings = settings or Settings()
        self.client = client
        self.cache_dir = Path(cache_dir) if cache_dir else None
        self.audit_dir = Path(audit_dir) if audit_dir else self.output / "ai-audit"
        self.progress = progress
        self.force = force
        self.lock = threading.Lock()
        self.state = {}

    # --- OpenAI call with cache --------------------------------------------------------------

    def key(self, prompt, png, size, style_sha):
        s = self.settings
        head = ":".join(
            [s.model, PROMPT_VERSION, style_sha, s.quality, s.complexity or "", size, prompt]
        )
        return hashlib.sha256(head.encode() + b"\0" + png).hexdigest()

    def edit(self, png, prompt, size, key):
        """(PNG bytes, meta) of one edit; cached on disk by the exact inputs."""
        s = self.settings
        cached = self.cache_dir / f"enhance-{key}.png" if self.cache_dir else None
        if cached and cached.is_file() and not self.force:
            meta = json.loads(cached.with_suffix(".json").read_text())
            return cached.read_bytes(), {**meta, "cache_hit": True, "cost_usd_new": 0.0}
        if self.client is None:
            from openai import OpenAI

            self.client = OpenAI(timeout=s.timeout, max_retries=0)
        kwargs = {
            "model": s.model,
            "image": ("render.png", png, "image/png"),
            "prompt": prompt,
            "size": size,
            "quality": s.quality,
            "output_format": "png",
            "n": 1,
            "timeout": s.timeout,
        }
        if supports_input_fidelity(s.model):
            kwargs["input_fidelity"] = "high"
        if s.complexity:
            kwargs["extra_body"] = {"complexity": s.complexity}
        started = time.monotonic()
        for attempt in (1, 2):
            try:
                response = self.client.images.edit(**kwargs)
                break
            except Exception as exc:  # one retry for transient errors only
                if attempt == 2 or type(exc).__name__ not in RETRYABLE:
                    raise
                log.warning("Image edit %s; retrying once", type(exc).__name__)
                time.sleep(3)
        data = response.data[0].b64_json
        if not data:
            raise ValueError("La API no devolvió ninguna imagen.")
        out = base64.b64decode(data)
        usage = response.usage.model_dump() if getattr(response, "usage", None) else None
        cost = cost_of(s.model, usage)
        meta = {
            "model": s.model,
            "size": size,
            "quality": s.quality,
            "complexity": s.complexity,
            "usage": usage,
            "cost_usd": cost,
            "seconds": round(time.monotonic() - started, 1),
            "attempts": attempt,
            "created": getattr(response, "created", None),
        }
        if cached:
            cached.parent.mkdir(parents=True, exist_ok=True)
            cached.write_bytes(out)
            write_json(cached.with_suffix(".json"), meta)
        return out, {**meta, "cache_hit": False, "cost_usd_new": cost or 0.0}

    # --- progress ----------------------------------------------------------------------------

    def report(self, views, started_at):
        if not self.progress:
            return
        with self.lock:
            done = sorted(i for i, v in self.state.items() if v.get("finished"))
            active = sorted(i for i, v in self.state.items() if not v.get("finished"))
            total = len(views)
            current = min(total, len(done) + 1)
            payload = {
                "kind": "enhance",
                "step": current,
                "total": total,
                "label": f"Mejora con IA · imagen {current} de {total}",
                "labels": [v["label"] for v in views],
                "done": done,
                "active": active,
                "seconds": {str(i): v["seconds"] for i, v in self.state.items() if "seconds" in v},
                "item_started": {
                    str(i): v["started_at"] for i, v in self.state.items() if "started_at" in v
                },
                "started_at": started_at,
            }
        try:
            self.progress(payload)
        except Exception:  # progress is cosmetic; never break the step
            log.exception("Enhancement progress callback failed")

    # --- one view ----------------------------------------------------------------------------

    def process(self, index, view, render, geometry, style, views, started_at):
        s = self.settings
        with self.lock:
            self.state[index] = {"started_at": now()}
        self.report(views, started_at)
        t0 = time.monotonic()
        record = {"id": render["id"], "label": render["label"], "attempts": []}
        try:
            original = Image.open(self.output / render["url"]).convert("RGB")
            mask_path = self.output / "masks" / f"{render['id']}.png"
            mask = Image.open(mask_path) if mask_path.is_file() else None
            plan = F.canvas_plan(*original.size, s.model)
            buffer = io.BytesIO()
            F.pad(original, plan).save(buffer, format="PNG")
            png = buffer.getvalue()
            size = "{}x{}".format(*plan["canvas"])
            accepted = restored = None
            for strict in (False, True):
                composed = compose(view, geometry, self.location, self.description, strict, style)
                key = self.key(composed["prompt"], png, size, style[1])
                out, meta = self.edit(png, composed["prompt"], size, key)
                result = Image.open(io.BytesIO(out))
                returned = list(result.size)
                restored, resampled = F.crop(result, plan, original.size)
                report = F.compare(original, restored, mask, s.threshold, s.max_shift)
                attempt = {
                    **meta,
                    "strict": strict,
                    "cache_key": key,
                    "prompt": composed["prompt"],
                    "prompt_sections": composed["sections"],
                    "canvas": plan,
                    "returned_size": returned,
                    "output_size": list(original.size),
                    "resampled_to_render_size": resampled,
                    "fidelity": report,
                }
                record["attempts"].append(attempt)
                self.audit(render["id"], attempt)
                if report["passed"]:
                    accepted = restored
                    break
            target = self.output / "renders" / "enhanced" / f"{render['id']}.webp"
            rejected = self.output / "enhancement" / "rejected" / f"{render['id']}.webp"
            target.unlink(missing_ok=True)
            rejected.unlink(missing_ok=True)
            if accepted is not None:
                target.parent.mkdir(parents=True, exist_ok=True)
                accepted.save(target, quality=92, method=6)
                record["status"] = "accepted"
            else:
                # Kept for inspection only; never served or shown.
                rejected.parent.mkdir(parents=True, exist_ok=True)
                restored.save(rejected, quality=90, method=4)
                record.update(status="rejected", notice=REJECTED)
            last = record["attempts"][-1]
            record.update(
                fidelity=last["fidelity"]["score"],
                fidelity_report=last["fidelity"],
                returned_size=last["returned_size"],
                output_size=last["output_size"],
                upscaled=last["resampled_to_render_size"],
            )
        except Exception as exc:
            log.exception("Enhancement of %s failed", render["id"])
            record.update(status="failed", error=f"{type(exc).__name__}: {str(exc)[:300]}")
        record["seconds"] = round(time.monotonic() - t0, 1)
        record["cost_usd"] = round(sum(a.get("cost_usd") or 0 for a in record["attempts"]), 4)
        record["cost_usd_new"] = round(
            sum(a.get("cost_usd_new") or 0 for a in record["attempts"]), 4
        )
        record["cache_hit"] = bool(record["attempts"]) and all(
            a.get("cache_hit") for a in record["attempts"]
        )
        with self.lock:
            self.state[index].update(finished=True, seconds=record["seconds"])
        self.report(views, started_at)
        return record

    def audit(self, ident, attempt):
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        write_json(
            self.audit_dir / f"enhance-{ident}-{stamp}.json",
            {
                "step": "enhance",
                "view": ident,
                "prompt_version": PROMPT_VERSION,
                "location": {k: self.location.get(k) for k in ("text", "source", "status")},
                **{k: v for k, v in attempt.items() if k != "canvas"},
                "canvas": attempt.get("canvas"),
            },
        )

    # --- whole project -----------------------------------------------------------------------

    def run(self):
        started = time.monotonic()
        started_at = now()
        manifest = json.loads((self.output / "manifest.json").read_text())
        views = {v["id"]: v for v in read_views(self.output)}
        geometry = json.loads((self.output / "geometry.json").read_text())
        style = master_style()
        jobs, records = [], []
        for render in manifest["renders"]:
            view = {**views.get(render["id"], {}), "id": render["id"], "label": render["label"]}
            if view_type(view) == "axonometric" and not self.settings.axonometric:
                records.append(
                    {
                        "id": render["id"],
                        "label": render["label"],
                        "status": "skipped",
                        "attempts": [],
                    }
                )
                continue
            jobs.append((view, render))
        if self.client is None and not os.getenv("OPENAI_API_KEY"):
            return finish(self, manifest, records, "unavailable", started, started_at, style)
        listed = [r for _, r in jobs]
        with ThreadPoolExecutor(max_workers=max(1, self.settings.concurrency)) as pool:
            futures = [
                pool.submit(self.process, i, v, r, geometry, style, listed, started_at)
                for i, (v, r) in enumerate(jobs)
            ]
            records += [f.result() for f in futures]
        order = {r["id"]: i for i, r in enumerate(manifest["renders"])}
        records.sort(key=lambda r: order.get(r["id"], 99))
        statuses = {r["status"] for r in records if r["status"] != "skipped"}
        if "accepted" in statuses:
            status = "completed" if statuses == {"accepted"} else "partial"
        else:
            status = "rejected" if "rejected" in statuses else "failed" if statuses else "completed"
        return finish(self, manifest, records, status, started, started_at, style)


def now():
    return datetime.now(UTC).isoformat()


def read_views(output):
    path = Path(output) / "views.json"
    return json.loads(path.read_text()) if path.is_file() else []


def location_summary(location):
    place, fallback = describe(location)
    loc = location or {}
    return {
        "text": loc.get("text") or None,
        "street": loc.get("street"),
        "city": loc.get("city"),
        "region": loc.get("region"),
        "country": loc.get("country"),
        "source": loc.get("source"),
        "confidence": loc.get("confidence"),
        "status": loc.get("status"),
        "used_in_prompt": place,
        "fallback": fallback,
    }


def finish(enhancer, manifest, records, status, started, started_at, style):
    s = enhancer.settings
    by_id = {r["id"]: r for r in records}
    for render in manifest["renders"]:
        render.pop("enhanced_url", None)
        record = by_id.get(render["id"])
        if record is None:
            render.pop("enhancement", None)
            continue
        render["enhancement"] = {
            "status": record["status"],
            "fidelity": record.get("fidelity"),
            "cost_usd": record.get("cost_usd"),
            "seconds": record.get("seconds"),
            "attempts": len(record.get("attempts", [])),
            "notice": record.get("notice"),
        }
        if record["status"] == "accepted":
            render["enhanced_url"] = f"renders/enhanced/{render['id']}.webp"
    for render in manifest["renders"]:
        if "enhanced_url" not in render:  # no stale image from an earlier run stays around
            (enhancer.output / "renders" / "enhanced" / f"{render['id']}.webp").unlink(
                missing_ok=True
            )
    summary = {
        "status": status,
        "notice": NOTICES[status],
        "label": LABEL,
        "illustrative": True,
        "model": s.model,
        "quality": s.quality,
        "prompt_version": PROMPT_VERSION,
        "style_sha256": style[1],
        "location": location_summary(enhancer.location),
        "images": sum(1 for r in records if r["status"] != "skipped"),
        "accepted": sum(1 for r in records if r["status"] == "accepted"),
        "rejected": sum(1 for r in records if r["status"] == "rejected"),
        "failed": sum(1 for r in records if r["status"] == "failed"),
        "skipped": sum(1 for r in records if r["status"] == "skipped"),
        "cost_usd": round(sum(r.get("cost_usd") or 0 for r in records), 4),
        "cost_usd_new": round(sum(r.get("cost_usd_new") or 0 for r in records), 4),
        "seconds": round(time.monotonic() - started, 1),
        "started_at": started_at,
        "finished_at": now(),
        "threshold": s.threshold,
        "max_shift_percent": s.max_shift,
    }
    manifest["enhancement"] = summary
    write_json(enhancer.output / "manifest.json", manifest)
    write_json(
        enhancer.output / "enhancement.json",
        {**summary, "settings": asdict(s), "views": records},
    )
    return summary


def mark(output, status, location=None, error=None, settings=None):
    """Record a step that did not run (disabled) or crashed, keeping the originals shown."""
    output = Path(output)
    path = output / "manifest.json"
    if not path.is_file():
        return None
    enhancer = Enhancer(output, location, settings=settings)
    manifest = json.loads(path.read_text())
    try:
        style = master_style()
    except OSError:
        style = ("", None)
    for render in manifest["renders"]:
        (output / "renders" / "enhanced" / f"{render['id']}.webp").unlink(missing_ok=True)
    summary = finish(enhancer, manifest, [], status, time.monotonic(), now(), style)
    if error:
        summary["error"] = error[:300]
        manifest = json.loads(path.read_text())
        manifest["enhancement"]["error"] = summary["error"]
        write_json(path, manifest)
    return summary


def safe_run(output, enabled=True, **options):
    """Enhancement that never raises: on any problem the originals stay the shown images."""
    if not enabled:
        return mark(output, "disabled", options.get("location"))
    try:
        return Enhancer(output, **options).run()
    except Exception as exc:
        log.exception("AI enhancement failed; originals are delivered")
        try:
            return mark(output, "failed", options.get("location"), f"{type(exc).__name__}: {exc}")
        except Exception:
            log.exception("Could not record the enhancement failure")
            return {"status": "failed", "notice": NOTICES["failed"]}


def strip_for_site(manifest):
    """Manifest copy for a site package: originals only (enhanced images never leave)."""
    clean = json.loads(json.dumps(manifest))
    clean.pop("enhancement", None)
    for render in clean.get("renders", []):
        render.pop("enhanced_url", None)
        render.pop("enhancement", None)
    return clean


# --- CLI -------------------------------------------------------------------------------------


def resolve(path):
    """(run output, location, description, audit dir, cache dir, project state path or None)."""
    path = Path(path).resolve()
    state_path = path / "project.json"
    if state_path.is_file():
        state = json.loads(state_path.read_text())
        if state.get("status") != "succeeded" or not state.get("result"):
            raise ValueError("El proyecto no tiene renders terminados.")
        output = path / state["result"]
        location = state.get("location") or detect(path, state)
        return (
            output,
            location,
            state.get("description") or "",
            path / "ai-audit",
            path.parent / "ai-cache",
            state_path,
        )
    if (path / "manifest.json").is_file():
        stored = path / "enhancement-input.json"
        options = json.loads(stored.read_text()) if stored.is_file() else {}
        location = options.get("location")
        if location is None and (path / "evidence/extraction.json").is_file():
            location = from_pdf(json.loads((path / "evidence/extraction.json").read_text()))
        return (
            path,
            location,
            options.get("description", ""),
            path / "ai-audit",
            ROOT / "outputs/ai-cache",
            None,
        )
    raise ValueError(f"{path}: no es un proyecto web ni una carpeta de resultados.")


def detect(folder, state):
    """Location of a web project from its stored evidence (PDF text or DWG/DXF entities)."""
    try:
        if state.get("source_format", "pdf") == "pdf":
            raw = json.loads((folder / "evidence/extraction.json").read_text())
            return from_pdf(raw, state.get("filename"))
        return from_dxf(folder / state["dxf_file"], state.get("filename"))
    except (OSError, ValueError, KeyError):
        log.exception("Location detection failed")
        return missing()


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("project", type=Path, help="Web project folder or a run output folder")
    p.add_argument("--force", action="store_true", help="Ignore the cache (new billed calls)")
    p.add_argument("--model", help=f"Image model (default OPENAI_IMAGE_MODEL or {DEFAULT_MODEL})")
    p.add_argument("--quality", help="low | medium | high | xhigh | max (model permitting)")
    p.add_argument("--no-axonometric", action="store_true", help="Skip the axonometric view")
    p.add_argument("--concurrency", type=int, default=3)
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        output, location, description, audit, cache, state_path = resolve(args.project)
    except (OSError, ValueError) as exc:
        print(f"enhance: {exc}", file=sys.stderr)
        return 2
    settings = Settings(concurrency=max(1, min(args.concurrency, 6)))
    if args.model:
        settings.model = args.model
    if args.quality:
        settings.quality = args.quality
    if args.no_axonometric:
        settings.axonometric = False

    def progress(payload):
        print(
            json.dumps(
                {
                    "event": "progress",
                    "label": payload["label"],
                    "done": payload["done"],
                    "active": payload["active"],
                }
            ),
            flush=True,
        )

    summary = safe_run(
        output,
        location=location,
        description=description,
        settings=settings,
        cache_dir=cache,
        audit_dir=audit,
        progress=progress,
        force=args.force,
    )
    if state_path is not None and summary:
        update_state(state_path, summary, location)
    detail = (
        json.loads((output / "enhancement.json").read_text())
        if (output / "enhancement.json").is_file()
        else {}
    )
    for view in detail.get("views", []):
        print(
            json.dumps(
                {
                    k: view.get(k)
                    for k in (
                        "id",
                        "status",
                        "fidelity",
                        "seconds",
                        "cost_usd",
                        "cache_hit",
                        "upscaled",
                    )
                },
                ensure_ascii=False,
            )
        )
    print(
        json.dumps(
            {
                "event": "enhancement_complete",
                **{
                    k: summary.get(k)
                    for k in (
                        "status",
                        "model",
                        "accepted",
                        "rejected",
                        "failed",
                        "cost_usd",
                        "cost_usd_new",
                        "seconds",
                    )
                },
                "location": summary.get("location", {}).get("used_in_prompt"),
            },
            ensure_ascii=False,
        )
    )
    return 0


def update_state(state_path, summary, location):
    """Store the summary in a web project (only when the server is not working on it)."""
    state = json.loads(state_path.read_text())
    if state.get("status") in ("queued", "running", "extracting"):
        return
    state["enhancement"] = summary
    state.setdefault("location", location)
    if isinstance(state.get("ai_usage"), dict) or state.get("ai_usage") is None:
        state["ai_usage"] = {**(state.get("ai_usage") or {}), "enhancement": usage_of(summary)}
    if state.get("manifest_url"):
        base = state["manifest_url"].split("&e=")[0]
        state["manifest_url"] = f"{base}&e={int(time.time())}"
    state["updated_at"] = now()
    write_json(state_path, state)


def usage_of(summary):
    return {
        k: summary.get(k)
        for k in (
            "status",
            "model",
            "images",
            "accepted",
            "rejected",
            "failed",
            "cost_usd",
            "cost_usd_new",
            "seconds",
            "finished_at",
        )
    }


def copy_site_renders(output, destination):
    """Originals only: enhanced client renders never enter a site package."""
    shutil.copytree(
        Path(output) / "renders",
        Path(destination) / "renders",
        dirs_exist_ok=True,
        ignore=shutil.ignore_patterns("enhanced"),
    )


if __name__ == "__main__":
    sys.exit(main())

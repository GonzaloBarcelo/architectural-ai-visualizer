"""Transactional PDF/DWG → geometry → Blender → QA → GLB → portable website pipeline."""

import argparse
import json
import logging
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image

from pipelines.common import ROOT, blender_bin, revision, sha256, write_json
from pipelines.geometry.normalize import ReviewRequired, normalize
from pipelines.geometry.schema import Geometry
from pipelines.pdf.extract import extract
from pipelines.pdf.synthetic import create

log = logging.getLogger("aav")
CAD_SUFFIXES = {".dwg": "dwg", ".dxf": "dxf"}


def cad_source(path):
    """Source record of a DWG/DXF input: its own SHA-256 (the drawing is one sheet)."""
    return {
        "filename": path.name,
        "sha256": sha256(path),
        "page_count": 1,
        "format": CAD_SUFFIXES[path.suffix.lower()],
    }


def execute(command, log_file, cwd=ROOT):
    log.info(json.dumps({"event": "command", "executable": str(command[0]), "log": str(log_file)}))
    with log_file.open("w") as stream:
        result = subprocess.run(
            check=False,
            args=[str(x) for x in command],
            cwd=cwd,
            stdout=stream,
            stderr=subprocess.STDOUT,
        )
    if result.returncode:
        tail = log_file.read_text(errors="replace")[-3000:]
        raise RuntimeError(f"Command failed ({result.returncode}); see {log_file.name}:\n{tail}")


def source_check(g, raw):
    if (
        g.source.sha256 != raw["source"]["sha256"]
        or g.source.page_count != raw["source"]["page_count"]
    ):
        raise ValueError("Reviewed geometry does not match this source SHA-256/page count.")
    if g.source.format != raw["source"].get("format", "pdf"):
        raise ValueError("Reviewed geometry was read from a different source format.")
    t = g.transform
    for key in ["walls", "openings", "rooms", "furniture", "slabs", "roofs", "outdoor_areas"]:
        for item in getattr(g, key):
            if item.evidence.page > g.source.page_count:
                raise ValueError(f"{item.id}: source page out of range")
            pts = item.evidence.pdf_coordinates
            if len(pts) != len(item.polygon):
                raise ValueError(f"{item.id}: source coordinates required for each polygon vertex")
            for (px, py), (x, y) in zip(pts, item.polygon):
                if (
                    max(
                        abs((px - t.origin_pdf[0]) * t.metres_per_point - x),
                        abs((t.origin_pdf[1] - py) * t.metres_per_point - y),
                    )
                    > 0.002
                ):
                    raise ValueError(
                        f"{item.id}: metric geometry conflicts with source coordinates"
                    )


def render_views(output):
    path = output / "views.json"
    if path.is_file():
        return json.loads(path.read_text())
    return [
        {"id": "exterior", "label": "Exterior"},
        {"id": "interior", "label": "Interior"},
        {"id": "axonometric", "label": "Axonometría"},
    ]


def web_manifest(g, output):
    inspection = json.loads((output / "scene-inspection.json").read_text())
    objs = inspection["objects"]
    lo = [min(x["bbox_min"][i] for x in objs) for i in range(3)]
    hi = [max(x["bbox_max"][i] for x in objs) for i in range(3)]
    manifest = {
        "project_id": g.project_id,
        "title": g.title,
        "synthetic": g.synthetic,
        "conceptual": g.conceptual,
        "assumptions": g.assumptions,
        "units": "m",
        "model_url": "model.glb",
        "renders": [
            {"id": v["id"], "label": v["label"], "url": f"renders/{v['id']}.webp"}
            for v in render_views(output)
            if (output / f"renders/{v['id']}.webp").exists()
        ],
        "floors": [f.model_dump(exclude={"evidence"}) for f in g.floors],
        "quality": {"passed": True},
        "bounds": {"min": [lo[0], lo[2], -hi[1]], "max": [hi[0], hi[2], -lo[1]]},
        "source_sha256": g.source.sha256,
        "source": {
            "format": g.source.format,
            "sha256": g.source.sha256,
            "converter": g.source.converter,
        },
        "material_note": "Acabados ilustrativos; geometría procedente del plano.",
        "finishes": {k: v.model_dump() for k, v in g.finishes.items()},
        "has_roof": bool(g.roofs),
    }
    write_json(output / "manifest.json", manifest)


def publish_local_assets(output, destination):
    # Explicit local export; only derived presentation assets are copied, never the PDF.
    # AI-enhanced images never enter a site package (originals only).
    from pipelines.postprocess.enhance import copy_site_renders, strip_for_site

    destination.mkdir(parents=True, exist_ok=True)
    shutil.copy2(output / "model.glb", destination / "model.glb")
    write_json(
        destination / "manifest.json",
        strip_for_site(json.loads((output / "manifest.json").read_text())),
    )
    copy_site_renders(output, destination)


def enhance_step(args, output, raw, source):
    """Optional illustrative AI enhancement of the delivered renders; never fails the run."""
    from pipelines.postprocess import enhance, location

    options = dict(getattr(args, "enhancement", None) or {})
    try:
        if "location" not in options:
            if source.suffix.lower() == ".dxf":
                options["location"] = location.from_dxf(source, source.name)
            elif "pages" in raw:
                options["location"] = location.from_pdf(raw, getattr(args.input, "name", None))
            else:
                options["location"] = location.missing()
        write_json(
            output / "enhancement-input.json",
            {k: options.get(k) for k in ("location", "description")},
        )
    except Exception:
        log.exception("Location for the enhancement could not be read")
        options["location"] = location.missing()
    options.setdefault("cache_dir", output.parent / "ai-cache")
    options.setdefault("audit_dir", output / "ai-audit")
    return enhance.safe_run(
        output, enabled=bool(args.enhance), progress=getattr(args, "activity", None), **options
    )


def run(args):
    from pipelines.quality.check import check

    progress = getattr(args, "progress", lambda stage: None)
    progress("extracting")
    output = args.output.resolve()
    site_root = args.site_root.resolve()
    output.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix=".run-", dir=output))
    try:
        cad = bool(args.input) and args.input.suffix.lower() in CAD_SUFFIXES
        target = work / "original.pdf"
        if args.demo:
            create(target)
        else:
            if not args.input or not args.input.is_file():
                raise ValueError(
                    "Provide --input an existing PDF, or --demo for synthetic test data."
                )
            target = work / ("original" + (args.input.suffix.lower() if cad else ".pdf"))
            shutil.copy2(args.input, target)
        if cad:
            # DWG/DXF geometry is read and reviewed in the web flow; here its hash is re-checked.
            if not args.geometry:
                raise ValueError("A DWG/DXF source needs reviewed geometry (--geometry).")
            raw = {"source": cad_source(target)}
        else:
            raw = extract(work / "original.pdf", work / "evidence")
        if args.vision and not cad:
            from pipelines.pdf.vision import interpret

            interpret(work / "original.pdf", work)
        if args.geometry:
            g = Geometry.model_validate_json(args.geometry.read_text()).require_verified()
            g.project_id = output.name
        else:
            g = normalize(raw, output.name)
        progress("validating_geometry")
        source_check(g, raw)
        write_json(work / "geometry.json", g.model_dump())
        write_json(
            work / "geometry-review.json",
            {
                "passed": True,
                "synthetic": g.synthetic,
                "conceptual": g.conceptual,
                "assumptions": g.assumptions,
                "missing_information": g.missing_information,
                "source_sha256": g.source.sha256,
                "method": "explicit annotated test drawing"
                if g.synthetic
                else "user supplied reviewed geometry; semantics require human responsibility",
            },
        )
        blender = [
            blender_bin(),
            "-b",
            "--factory-startup",
            "--python-exit-code",
            "1",
            "--python",
            ROOT / "pipelines/blender/build_scene.py",
            "--",
            "--geometry",
            work / "geometry.json",
            "--output",
            work,
            "--device",
            args.device,
            "--resolution",
            str(args.resolution),
            "--samples",
            str(args.samples),
        ]
        progress("modeling")
        execute(
            blender + ["--stage", "build"] + (["--clay"] if args.clay else []),
            work / "blender-build.log",
        )
        progress("preview_qa")
        qa = check(g, work, include_renders=False)
        if not qa["passed"]:
            raise ValueError(
                "Critical geometry/preview QA failed; inspect quality-report.json. Final export blocked."
            )
        progress("rendering")
        execute(blender + ["--stage", "final"], work / "blender-final.log")
        for path in (work / "renders").glob("*.png"):
            Image.open(path).convert("RGB").save(path.with_suffix(".webp"), quality=95, method=6)
        progress("final_qa")
        qa = check(g, work, include_renders=True)
        if not qa["passed"]:
            raise ValueError(
                "Final render QA failed; delivery blocked. Inspect quality-report.json."
            )
        progress("exporting")
        execute(
            [
                "node",
                site_root / "scripts/optimize-model.mjs",
                work / "model.raw.glb",
                work / "model.glb",
            ],
            work / "glb-optimization.log",
        )
        execute(
            ["node", site_root / "scripts/validate-model.mjs", work / "model.glb"],
            work / "glb-validation.log",
        )
        web_manifest(g, work)
        code_files = [
            p for folder in ["pipelines", "scripts"] for p in (ROOT / folder).rglob("*.py")
        ]
        write_json(
            work / "provenance.json",
            {
                "source_sha256": g.source.sha256,
                "source_format": g.source.format,
                "converter": g.source.converter,
                "geometry_sha256": sha256(work / "geometry.json"),
                "schema_version": g.schema_version,
                "revision": revision(),
                "source_code_sha256": {
                    str(p.relative_to(ROOT)): sha256(p) for p in sorted(code_files)
                },
                "lockfiles": {
                    str(p.relative_to(ROOT)): sha256(p)
                    for p in [ROOT / "uv.lock", ROOT / "site/package-lock.json"]
                    if p.exists()
                },
                "render_config": json.loads((work / "render-config.json").read_text()),
                "artifacts": {
                    str(p.relative_to(work)): sha256(p)
                    for p in work.rglob("*")
                    if p.is_file() and not p.name.endswith(".log")
                },
            },
        )
        # Replace only our known generated artifacts after complete successful validation.
        for path in work.iterdir():
            dest = output / path.name
            if path.is_dir():
                if dest.exists():
                    shutil.rmtree(dest)
                shutil.move(str(path), dest)
            else:
                path.replace(dest)
        work.rmdir()
        if args.site_assets:
            publish_local_assets(output, args.site_assets.resolve())
            execute(["npm", "run", "build"], output / "site-build.log", site_root)
        write_json(
            output / "run-status.json",
            {
                "passed": True,
                "source_sha256": g.source.sha256,
                "source_format": g.source.format,
                "converter": g.source.converter,
            },
        )
        # The originals are delivered above; the illustrative enhancement can only add to them.
        if getattr(args, "enhance", None) is not None:
            progress("enhancing")
            enhance_step(args, output, raw, output / target.name)
        progress("completed")
        return output
    except Exception as exc:
        write_json(
            work / "geometry-review.json",
            {
                "passed": False,
                "error": str(exc),
                "action": "Inspect evidence and supply verified measurements/geometry; rerun after correction.",
            },
        )
        write_json(
            output / "run-status.json",
            {"passed": False, "error": str(exc), "review_directory": str(work)},
        )
        log.error(
            json.dumps(
                {"event": "pipeline_failed", "review_directory": str(work), "error": str(exc)}
            )
        )
        raise


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input", type=Path)
    p.add_argument("--demo", action="store_true", help="Generate explicitly synthetic test PDF")
    p.add_argument("--output", type=Path, required=True)
    p.add_argument(
        "--geometry", type=Path, help="Human reviewed metric geometry tied to input hash"
    )
    p.add_argument(
        "--vision",
        action="store_true",
        help="Explicitly authorize sending this PDF to OpenAI for unverified semantic proposals",
    )
    p.add_argument("--device", choices=["auto", "cpu", "gpu"], default="auto")
    p.add_argument("--resolution", type=int, default=960)
    p.add_argument("--samples", type=int, default=64)
    p.add_argument("--clay", action="store_true")
    p.add_argument(
        "--enhance",
        action="store_const",
        const=True,
        default=None,
        help="After delivery, send the renders to the OpenAI image-edit API for an illustrative "
        "enhancement (needs OPENAI_API_KEY; originals are always kept)",
    )
    p.add_argument(
        "--site-assets",
        type=Path,
        help="Explicit local web asset destination, followed by npm run build",
    )
    p.add_argument(
        "--site-root",
        type=Path,
        default=ROOT / "site",
        help="Frontend source checkout; defaults to repository site/",
    )
    args = p.parse_args()
    if args.resolution < 128 or args.resolution > 4096 or args.samples < 1 or args.samples > 4096:
        p.error("resolution must be 128-4096 and samples 1-4096")
    if args.demo and args.input:
        p.error("Use either --demo or --input")
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    try:
        result = run(args)
    except (ValueError, RuntimeError, OSError, ReviewRequired) as exc:
        print(f"Pipeline stopped: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"event": "pipeline_complete", "output": str(result)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())

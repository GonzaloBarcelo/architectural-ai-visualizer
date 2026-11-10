"""Extract raw PDF evidence and raster candidates. No candidate is automatically verified."""

import argparse
import re
from pathlib import Path

import cv2
import numpy as np
import pymupdf as fitz

from pipelines.common import sha256, write_json

DISPLAY_MAX_PX = 8000


def coords(value):
    if isinstance(value, (fitz.Point, fitz.Rect, fitz.Quad)):
        return [coords(item) for item in value]
    if isinstance(value, (list, tuple)):
        return [coords(item) for item in value]
    if isinstance(value, dict):
        return {key: coords(item) for key, item in value.items()}
    return value


def extract(path: Path, output: Path):
    if path.stat().st_size > 50 * 1024**2:
        raise ValueError("PDF exceeds 50 MiB; split the document before processing.")
    output.mkdir(parents=True, exist_ok=True)
    doc = fitz.open(path)
    if doc.needs_pass:
        raise ValueError("Encrypted PDF: provide an authorized unlocked copy.")
    if not 1 <= len(doc) <= 50:
        raise ValueError("PDF must contain 1-50 pages; split large documents.")
    pages = []
    for pi, page in enumerate(doc):
        drawings = []
        for i, d in enumerate(page.get_drawings()):
            drawings.append(
                {
                    "index": i,
                    "rect": list(d["rect"]),
                    "fill": d["fill"],
                    "color": d["color"],
                    "width": d["width"],
                    "closed": d["closePath"],
                    "items": [[coords(v) for v in item] for item in d["items"]],
                }
            )
        annotations = []
        for a in page.annots() or []:
            annotations.append(
                {
                    "type": a.type[1],
                    "rect": list(a.rect + (a.rect_delta or (0, 0, 0, 0))),
                    "vertices": coords(a.vertices),
                    "content": a.info.get("content", ""),
                }
            )
        if page.rect.width * page.rect.height > 20_000_000:
            raise ValueError("Page size exceeds raster safety limit; resize before processing.")
        # Review image: sharp enough to zoom into a large sheet (≈ 4×, capped at 8000 px).
        # Line detection below keeps its own 1.5× raster, whose thresholds are tuned in pixels.
        sharp = min(4.0, DISPLAY_MAX_PX / max(page.rect.width, page.rect.height))
        page.get_pixmap(matrix=fitz.Matrix(sharp, sharp), alpha=False, annots=False).save(
            output / f"page-{pi + 1}.png"
        )
        pix = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5), alpha=False, annots=False)
        img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, 3)
        gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
        edges = cv2.Canny(gray, 60, 160)
        lines = cv2.HoughLinesP(edges, 1, np.pi / 180, 80, minLineLength=40, maxLineGap=8)
        text = page.get_text()
        pages.append(
            {
                "page": pi + 1,
                "size_points": [page.rect.width, page.rect.height],
                "type": "vector" if drawings else "scanned" if page.get_images() else "text",
                "text": text,
                "dimensions": re.findall(r"\b\d+(?:[.,]\d+)?\s*(?:mm|cm|m)\b", text),
                "text_blocks": page.get_text("blocks"),
                "drawings": drawings,
                "annotations": annotations,
                "raster_candidates": (
                    [] if lines is None else (lines[:, 0, :] / 1.5).round(3).tolist()
                ),
                "raster_status": "inferred; no architectural semantics or scale verified",
            }
        )
    result = {
        "source": {"filename": path.name, "sha256": sha256(path), "page_count": len(doc)},
        "pages": pages,
        "synthetic_marker": doc.metadata.get("title") == "AAV synthetic test drawing v1",
    }
    doc.close()
    write_json(output / "extraction.json", result)
    return result


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--input", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    extract(args.input, args.output)

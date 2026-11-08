"""Generate a labeled test drawing. Geometry is drawn, not embedded as a hidden model."""

import argparse
from pathlib import Path

import pymupdf as fitz

# Fixture definition only. The parser never imports this module.
COLORS = {
    "wall": (0.2, 0.2, 0.2),
    "slab": (0.86, 0.84, 0.8),
    "room": (0.93, 0.94, 0.9),
    "door": (0.6, 0.3, 0.1),
    "window": (0.1, 0.5, 0.8),
}


def create(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = fitz.open()
    page = doc.new_page(width=842, height=720)
    page.insert_text((50, 38), "ATELIER / 001     SYNTHETIC TEST DATA", fontsize=19)
    page.insert_text(
        (50, 61),
        "Procedural validation pavilion - not a real building or construction document",
        fontsize=10,
    )
    page.insert_text(
        (50, 83),
        "AAV TEST DRAWING v1 | SCALE 1:50 | units m | floor F0 elevation 0.00 m",
        fontsize=10,
    )
    scale = 72 / 0.0254 / 50
    ox, oy = 95.0, 540.0

    def point(x, y):
        return (ox + x * scale, oy - y * scale)

    def rect(kind, ident, xy, extra):
        x0, y0, x1, y1 = xy
        r = fitz.Rect(*point(x0, y1), *point(x1, y0))
        page.draw_rect(r, color=COLORS[kind], fill=COLORS[kind], width=0.5)
        annot = page.add_rect_annot(r)
        annot.set_border(width=0)
        annot.set_info(
            title="AAV synthetic fixture", content=f"AAV|{kind}|{ident}|floor=F0|{extra}"
        )
        annot.update()

    rect("slab", "S0", (0, 0, 10, 7), "elevation=-0.20|thickness=0.20")
    for ident, xy, name in [
        ("R1", (0.2, 0.2, 5, 6.8), "Living"),
        ("R2", (5.2, 0.2, 9.8, 3.4), "Studio"),
        ("R3", (5.2, 3.6, 9.8, 6.8), "Bedroom"),
    ]:
        rect("room", ident, xy, "name=" + name)
        cx, cy = (xy[0] + xy[2]) / 2, (xy[1] + xy[3]) / 2
        page.insert_text(point(cx - 0.5, cy), name.upper(), fontsize=12)
    for ident, xy in [
        ("W1", (0, 0, 10, 0.2)),
        ("W2", (0, 6.8, 10, 7)),
        ("W3", (0, 0.2, 0.2, 6.8)),
        ("W4", (9.8, 0.2, 10, 6.8)),
        ("W5", (5, 0.2, 5.2, 6.8)),
        ("W6", (5.2, 3.4, 9.8, 3.6)),
    ]:
        rect("wall", ident, xy, "elevation=0|height=2.80|thickness=0.20")
    for kind, ident, xy, wall, sill, h in [
        ("door", "D1", (1.1, 0, 2.1, 0.2), "W1", 0, 2.2),
        ("door", "D2", (5, 1.2, 5.2, 2.2), "W5", 0, 2.2),
        ("door", "D3", (7, 3.4, 8, 3.6), "W6", 0, 2.2),
        ("window", "N1", (2, 6.8, 4, 7), "W2", 0.9, 1.5),
        ("window", "N2", (9.8, 4.5, 10, 6.2), "W4", 0.9, 1.5),
        ("window", "N3", (9.8, 1, 10, 2.6), "W4", 0.9, 1.5),
    ]:
        rect(kind, ident, xy, f"wall={wall}|sill={sill}|height={h}")
    # Explicit calibration line and endpoints, visible on the drawing.
    a, b = point(0, -0.5), point(10, -0.5)
    page.draw_line(a, b, color=(0, 0, 0), width=0.7)
    for x, y in (a, b):
        page.draw_line((x, y - 4), (x, y + 4), color=(0, 0, 0))
    page.insert_text((a[0] + 235, a[1] - 6), "10.00 m", fontsize=11)
    annot = page.add_line_annot(a, b)
    annot.set_info(content="AAV|measurement|M1|value=10.00")
    annot.set_border(width=0)
    annot.update()
    page.insert_text(
        (50, 620),
        "All walls: H=2.80 m / T=0.20 m. Slab: -0.20 to 0.00 m. No roof specified.",
        fontsize=10,
    )
    page.insert_text(
        (50, 640),
        "Doors: H=2.20 m. Windows: sill=0.90 m / H=1.50 m. Opening extents are drawn.",
        fontsize=10,
    )
    page.insert_text(
        (50, 660),
        "Colored rectangles and annotations explicitly label every test element; scale is checked against 10.00 m.",
        fontsize=9,
    )
    doc.set_metadata({"title": "AAV synthetic test drawing v1", "subject": "SYNTHETIC TEST DATA"})
    doc.save(path)
    doc.close()
    return path


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--output", type=Path, required=True)
    create(p.parse_args().output)

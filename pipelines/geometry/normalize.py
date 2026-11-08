"""Normalize explicitly annotated synthetic drawings; arbitrary plans require review."""

import math

from pipelines.geometry.schema import Geometry


class ReviewRequired(ValueError):
    pass


def normalize(raw, project_id):
    if not raw["synthetic_marker"] or len(raw["pages"]) != 1:
        raise ReviewRequired(
            "Architectural semantics, scale and heights require review. Inspect extraction.json and page PNGs; supply --geometry reviewed.json tied to the PDF SHA-256. Optional --vision proposes semantics, never approves them."
        )
    page = raw["pages"][0]
    if "AAV TEST DRAWING v1" not in page["text"] or page["type"] != "vector":
        raise ReviewRequired(
            "Synthetic signature or vector evidence missing; manual review required."
        )
    tags = []
    for a in page["annotations"]:
        parts = a["content"].split("|")
        if len(parts) >= 4 and parts[0] == "AAV":
            tags.append((parts[1], parts[2], dict(p.split("=", 1) for p in parts[3:]), a))
    measures = [t for t in tags if t[0] == "measurement"]
    if len(measures) != 1 or len(measures[0][3]["vertices"] or []) != 2:
        raise ReviewRequired(
            "Exactly one explicit calibration reference required for this test format."
        )
    _, mid, mp, ma = measures[0]
    endpoints = ma["vertices"]
    factor = float(mp["value"]) / math.dist(*endpoints)
    if abs(factor - 0.0254 / 72 * 50) > 1e-7:
        raise ReviewRequired("Calibration conflicts with printed 1:50 scale.")
    # Find a matching actual filled rectangle; annotations alone cannot fabricate geometry.
    matched = []
    for kind, ident, props, annot in tags:
        if kind == "measurement":
            continue
        r = annot["rect"]
        candidates = [
            d
            for d in page["drawings"]
            if d["fill"]
            and any(item[0] == "re" for item in d["items"])
            and max(abs(a - b) for a, b in zip(d["rect"], r)) < 0.02
        ]
        if len(candidates) != 1:
            raise ReviewRequired(f"{ident}: annotation must match exactly one drawn rectangle")
        matched.append((kind, ident, props, candidates[0]))
    slab = next((x for x in matched if x[0] == "slab"), None)
    if slab is None:
        raise ReviewRequired("Missing slab/origin reference")
    ox, _, _, oy = slab[3]["rect"]

    def ev(points, note, primitive=None):
        return {
            "page": 1,
            "primitive": primitive,
            "pdf_coordinates": points,
            "note": note,
            "status": "verified",
            "confidence": 1.0,
        }

    data = {
        "schema_version": "1.0",
        "project_id": project_id,
        "title": "Pabellón de estudio · 001",
        "synthetic": True,
        "source": raw["source"],
        "transform": {"metres_per_point": factor, "origin_pdf": [ox, oy]},
        "floors": [
            {
                "id": "F0",
                "name": "Planta baja",
                "elevation": 0,
                "evidence": ev([], "Printed floor F0 elevation 0.00 m"),
            }
        ],
        "walls": [],
        "openings": [],
        "rooms": [],
        "slabs": [],
        "roofs": [],
        "outdoor_areas": [],
        "measurements": [
            {
                "id": mid,
                "value_m": float(mp["value"]),
                "endpoints_pdf": endpoints,
                "evidence": ev(endpoints, "Explicit 10.00 m calibration line"),
            }
        ],
        "assumptions": [],
        "missing_information": [],
    }
    for kind, ident, props, d in matched:
        x0, y0, x1, y1 = d["rect"]
        pts = [(x0, y1), (x1, y1), (x1, y0), (x0, y0)]
        poly = [(round((x - ox) * factor, 6), round((oy - y) * factor, 6)) for x, y in pts]
        item = {
            "id": ident,
            "floor_id": props["floor"],
            "polygon": poly,
            "evidence": ev(
                pts, "Drawn extent + explicit test annotation; synthetic only", d["index"]
            ),
        }
        if kind in ("wall", "slab", "roof", "outdoor"):
            item.update(elevation=float(props["elevation"]), thickness=float(props["thickness"]))
            if kind == "wall":
                item["height"] = float(props["height"])
            data[
                {"wall": "walls", "slab": "slabs", "roof": "roofs", "outdoor": "outdoor_areas"}[
                    kind
                ]
            ].append(item)
        elif kind in ("door", "window"):
            item.update(
                kind=kind,
                wall_id=props["wall"],
                sill=float(props["sill"]),
                height=float(props["height"]),
            )
            data["openings"].append(item)
        elif kind == "room":
            item["name"] = props["name"]
            data["rooms"].append(item)
        else:
            raise ReviewRequired(f"Unsupported semantic tag: {kind}")
    return Geometry.model_validate(data).require_verified()

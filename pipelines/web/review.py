"""Convert an explicitly reviewed, PDF-coordinate draft into the metric pipeline schema."""

import math
from typing import Literal

from pydantic import Field, ValidationError
from shapely.geometry import Polygon

from pipelines.geometry.normalize import ReviewRequired, normalize
from pipelines.geometry.schema import (
    CadReference,
    Finish,
    FinishKey,
    FloorFinish,
    Geometry,
    OpeningStyle,
    Point,
    Strict,
)


class Calibration(Strict):
    points: list[Point] = Field(default_factory=list, max_length=2)
    metres: float | None = None
    confirmed: bool = False


class FloorDraft(Strict):
    name: str = Field(default="Planta 1", max_length=120)
    elevation: float | None = None
    confirmed: bool = False


class ElementDraft(Strict):
    id: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")
    kind: Literal["wall", "slab", "room", "door", "window", "roof", "furniture"]
    polygon: list[Point] = Field(default_factory=list, max_length=200)
    height: float | None = None
    thickness: float | None = None
    elevation: float | None = None
    sill: float | None = None
    wall_id: str | None = None
    name: str | None = Field(default=None, max_length=120)
    style: OpeningStyle | None = None
    finish: FloorFinish | None = None
    cad: CadReference | None = None  # DWG/DXF provenance (handles, layers, block, reading)
    confirmed: bool = False


class Draft(Strict):
    conceptual: bool = False
    assumptions: list[str] = Field(default_factory=list, max_length=100)
    finishes: dict[FinishKey, Finish] = Field(default_factory=dict)
    page: int = Field(default=1, ge=1)
    title: str = Field(default="Proyecto", max_length=200)
    calibration: Calibration = Field(default_factory=Calibration)
    floor: FloorDraft = Field(default_factory=FloorDraft)
    entities: list[ElementDraft] = Field(default_factory=list, max_length=300)
    complete: bool = False


def draft_from_extraction(raw, project_id, title):
    draft = Draft(title=title).model_dump()
    try:
        g = normalize(raw, project_id)
    except (ReviewRequired, ValueError, KeyError):
        return draft
    measurement = g.measurements[0]
    draft["calibration"] = {
        "points": measurement.endpoints_pdf,
        "metres": measurement.value_m,
        "confirmed": False,
    }
    draft["floor"] = {
        "name": g.floors[0].name,
        "elevation": g.floors[0].elevation,
        "confirmed": False,
    }
    for key, kind in [
        ("walls", "wall"),
        ("slabs", "slab"),
        ("rooms", "room"),
        ("roofs", "roof"),
        ("openings", None),
    ]:
        for item in getattr(g, key):
            data = item.model_dump()
            entity = {
                "id": item.id,
                "kind": kind or data["kind"],
                "polygon": item.evidence.pdf_coordinates,
                "confirmed": False,
            }
            entity.update(
                {
                    k: data[k]
                    for k in ["height", "thickness", "elevation", "sill", "wall_id", "name"]
                    if k in data
                }
            )
            draft["entities"].append(entity)
    return Draft.model_validate(draft).model_dump()


def validate_draft(value, raw, project_id):
    issues = []

    def issue(path, message):
        issues.append({"path": path, "message": message})

    try:
        d = Draft.model_validate(value)
    except ValidationError as exc:
        return None, [
            {"path": ".".join(map(str, e["loc"])), "message": e["msg"]} for e in exc.errors()
        ]
    if not 1 <= d.page <= len(raw["pages"]):
        return None, [{"path": "page", "message": "Selecciona una página existente del PDF."}]
    page = raw["pages"][d.page - 1]
    width, height = page["size_points"]

    def on_page(points):
        return all(0 <= x <= width and 0 <= y <= height for x, y in points)

    if not d.title.strip():
        issue("title", "Introduce un nombre para el proyecto.")
    cal = d.calibration
    factor = None
    if len(cal.points) != 2 or math.dist(*cal.points) < 1:
        issue(
            "calibration.points", "Marca dos extremos distintos de una cota conocida en el plano."
        )
    elif not on_page(cal.points):
        issue("calibration.points", "La referencia de escala debe estar dentro de la página.")
    elif cal.metres is None or cal.metres <= 0:
        issue(
            "calibration.metres", "Introduce la longitud real positiva de la referencia, en metros."
        )
    else:
        factor = cal.metres / math.dist(*cal.points)
    if not cal.confirmed:
        issue(
            "calibration.confirmed",
            "Confirma la escala contrastándola con una medida del documento.",
        )
    if d.floor.elevation is None:
        issue(
            "floor.elevation",
            "Indica la elevación de la planta en metros; usa 0 solo si es tu referencia verificada.",
        )
    if not d.floor.confirmed:
        issue("floor.confirmed", "Confirma la elevación de la planta.")
    if not d.complete:
        issue(
            "complete",
            "Confirma que has revisado los elementos y que no faltan datos para este modelo.",
        )
    kinds = [e.kind for e in d.entities]
    for kind, label in [("wall", "muro"), ("slab", "suelo o losa")]:
        if kind not in kinds:
            issue("entities", f"Delimita al menos un {label} sobre el plano.")
    ids = [e.id for e in d.entities]
    if len(ids) != len(set(ids)):
        issue("entities", "Los identificadores de los elementos deben ser únicos.")
    for e in d.entities:
        prefix = f"entities.{e.id}"
        if not e.confirmed:
            issue(prefix + ".confirmed", f"Revisa y confirma {e.id}.")
        if len(e.polygon) < 3 or not on_page(e.polygon):
            issue(
                prefix + ".polygon",
                "Dibuja un contorno de al menos tres puntos dentro de la página.",
            )
            continue
        poly = Polygon(e.polygon)
        if not poly.is_valid or poly.area < 0.01:
            issue(
                prefix + ".polygon",
                "El contorno está cruzado o no tiene superficie; vuelve a dibujarlo.",
            )
        if e.kind in ["wall", "door", "window", "furniture"] and (
            e.height is None or e.height <= 0
        ):
            issue(prefix + ".height", "Falta una altura positiva, en metros.")
        if e.kind in ["wall", "slab", "roof"] and (e.thickness is None or e.thickness <= 0):
            issue(prefix + ".thickness", "Falta un espesor positivo, en metros.")
        if e.kind in ["slab", "roof"] and e.elevation is None:
            issue(prefix + ".elevation", "Indica la cota inferior del elemento, en metros.")
        if e.kind in ["door", "window"]:
            if e.sill is None or e.sill < 0:
                issue(
                    prefix + ".sill",
                    "Indica una altura de antepecho no negativa (0 para una puerta a nivel de suelo).",
                )
            if e.wall_id not in [w.id for w in d.entities if w.kind == "wall"]:
                issue(prefix + ".wall_id", "Selecciona el muro que contiene este hueco.")
            # The boolean cutter supports rectangular opening footprints, including rotated ones.
            if poly.is_valid and poly.symmetric_difference(
                poly.minimum_rotated_rectangle
            ).area > max(0.01, poly.area * 0.001):
                issue(
                    prefix + ".polygon",
                    "El hueco debe tener un contorno rectangular que atraviese el espesor del muro.",
                )
        if e.kind == "room" and not (e.name or "").strip():
            issue(prefix + ".name", "Introduce el nombre de la estancia.")
        if factor and poly.is_valid and e.kind == "wall" and e.thickness and poly.area > 0:
            rect = poly.minimum_rotated_rectangle
            if poly.symmetric_difference(rect).area < max(0.01, poly.area * 0.001):
                pts = list(rect.exterior.coords)
                short = min(math.dist(pts[i], pts[i + 1]) for i in range(4)) * factor
                if abs(short - e.thickness) > max(0.01, e.thickness * 0.02):
                    issue(
                        prefix + ".thickness",
                        f"El contorno mide {short:.3f} m de espesor; revisa la escala, el dibujo o el espesor indicado.",
                    )
    if issues:
        return None, issues
    assert factor is not None
    all_points = [p for e in d.entities for p in e.polygon]
    ox = min(p[0] for p in all_points)
    oy = max(p[1] for p in all_points)

    cad_source = raw["source"].get("format", "pdf") != "pdf"

    def evidence(points, note, cad=None):
        if cad_source:
            note = note.replace("sobre el PDF", "sobre el dibujo DWG/DXF")
        return {
            "page": d.page,
            "pdf_coordinates": points,
            "note": "Propuesta conceptual aceptada; valores inferidos. " + note
            if d.conceptual
            else note,
            "status": "inferred" if d.conceptual else "verified",
            "confidence": 0.5 if d.conceptual else 1,
            **({"cad": cad.model_dump()} if cad else {}),
        }

    data = {
        "conceptual": d.conceptual,
        "assumptions": d.assumptions,
        "finishes": {k: v.model_dump() for k, v in d.finishes.items()},
        "project_id": project_id,
        "title": d.title.strip(),
        "synthetic": raw.get("synthetic_marker", False),
        "source": raw["source"],
        "transform": {"metres_per_point": factor, "origin_pdf": [ox, oy]},
        "floors": [
            {
                "id": "F0",
                "name": d.floor.name,
                "elevation": d.floor.elevation,
                "evidence": evidence([], "Elevación confirmada explícitamente en la revisión web."),
            }
        ],
        "measurements": [
            {
                "id": "calibration-1",
                "value_m": cal.metres,
                "endpoints_pdf": cal.points,
                "evidence": evidence(
                    cal.points, "Referencia de escala confirmada en la revisión web."
                ),
            }
        ],
        "walls": [],
        "slabs": [],
        "rooms": [],
        "furniture": [],
        "roofs": [],
        "openings": [],
    }
    for e in d.entities:
        item = {
            "id": e.id,
            "floor_id": "F0",
            "polygon": [((x - ox) * factor, (oy - y) * factor) for x, y in e.polygon],
            "evidence": evidence(
                e.polygon,
                "Contorno y dimensiones revisados y confirmados por el usuario sobre el PDF.",
                e.cad,
            ),
        }
        if e.kind in ["wall", "slab", "roof"]:
            item.update(
                elevation=d.floor.elevation if e.kind == "wall" else e.elevation,
                thickness=e.thickness,
            )
            if e.kind == "wall":
                item["height"] = e.height
            data[{"wall": "walls", "slab": "slabs", "roof": "roofs"}[e.kind]].append(item)
        elif e.kind == "furniture":
            item.update(name=e.name or "Mueble conceptual", height=e.height)
            data["furniture"].append(item)
        elif e.kind == "room":
            item.update(name=e.name, floor_finish=e.finish)
            data["rooms"].append(item)
        else:
            item.update(kind=e.kind, sill=e.sill, height=e.height, wall_id=e.wall_id, style=e.style)
            data["openings"].append(item)
    try:
        geometry = Geometry.model_validate(data).require_verified()
        # Openings must span the host's thickness, and cannot overlap one another.
        for op in geometry.openings:
            host = next(w for w in geometry.walls if w.id == op.wall_id)
            poly = Polygon(op.polygon)
            wall = Polygon(host.polygon)
            # Both ends across the short opening axis must reach the wall boundary.
            rect = poly.minimum_rotated_rectangle
            points = list(rect.exterior.coords)
            short = min(math.dist(points[i], points[i + 1]) for i in range(4))
            if short < host.thickness - 0.002:
                issue(
                    f"entities.{op.id}.polygon", "El hueco debe atravesar todo el espesor del muro."
                )
            if wall.intersection(poly).area < poly.area - 0.00001:
                issue(f"entities.{op.id}.polygon", "El hueco debe quedar dentro del muro.")
        for i, op in enumerate(geometry.openings):
            for other in geometry.openings[i + 1 :]:
                if (
                    op.wall_id == other.wall_id
                    and min(op.sill + op.height, other.sill + other.height)
                    > max(op.sill, other.sill)
                    and Polygon(op.polygon).intersection(Polygon(other.polygon)).area > 1e-6
                ):
                    issue(f"entities.{op.id}.polygon", "Dos huecos se solapan en el mismo muro.")
        return (None, issues) if issues else (geometry, [])
    except ValueError as exc:
        issue("geometry", str(exc))
        return None, issues

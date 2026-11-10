"""Deterministic reading of a DXF floor plan (model space only). No AI.

Everything here is computed from the drawing: units, the drawn plans, wall polygons, wall gaps
and the carpentry inside them, block inserts with their transformed footprints and orientation,
room outlines closed by the walls, room labels and floor hatches. Whatever the drawing does not
settle is returned as a *doubt* for one later AI call or for the user; nothing is guessed here.
Coordinates are metres in the drawing's world frame (x right, y up).
"""

import hashlib
import math
import re
import statistics
from collections import Counter
from itertools import pairwise

import ezdxf
import shapely
from ezdxf import bbox as ebbox
from ezdxf import disassemble, recover
from ezdxf import path as epath
from shapely import affinity
from shapely.geometry import LineString, Point, Polygon
from shapely.geometry.polygon import orient
from shapely.ops import split, unary_union
from shapely.validation import make_valid

GRID = 0.0001  # metres: wall geometry is snapped to 0.1 mm (QA tolerance is 2 mm)
# ezdxf raises these on proxy, unsupported or malformed entities; such entities are skipped.
CAD_ERRORS = (
    ezdxf.DXFError,
    ValueError,
    TypeError,
    AttributeError,
    KeyError,
    IndexError,
    ZeroDivisionError,
)

from pipelines.cad import config as C

UNITS = {
    1: ("in", 0.0254),
    2: ("ft", 0.3048),
    4: ("mm", 0.001),
    5: ("cm", 0.01),
    6: ("m", 1.0),
    14: ("dm", 0.1),
}
SKIP_TYPES = {
    "TEXT",
    "MTEXT",
    "ATTRIB",
    "ATTDEF",
    "DIMENSION",
    "ARC_DIMENSION",
    "LARGE_RADIAL_DIMENSION",
    "POINT",
    "LEADER",
    "MULTILEADER",
    "MLEADER",
    "TOLERANCE",
    "VIEWPORT",
    "IMAGE",
    "PDFUNDERLAY",
    "DWFUNDERLAY",
    "DGNUNDERLAY",
    "OLE2FRAME",
    "ACAD_TABLE",
    "XLINE",
    "RAY",
}
PLAN_TITLE = re.compile(r"PLANTA|PLANO|NIVEL|\bPISO\b|FLOOR|LEVEL|SOTANO|ATICO|\bPIS\b")


def load(path):
    try:
        return ezdxf.readfile(str(path))
    except ezdxf.DXFStructureError:
        doc, _ = recover.readfile(str(path))
        return doc


def parts(geom):
    if geom is None or geom.is_empty:
        return []
    if geom.geom_type == "Polygon":
        return [geom]
    return [p for g in getattr(geom, "geoms", []) for p in parts(g)]


def inside(geom, area):
    """Polygons of ``geom`` within the plan area. One CAD entity (a hatch or polyline) can span
    several drawn plans; only the part over the chosen plan belongs to it."""
    if area.contains(geom):
        return [geom]
    return [p for p in parts(valid(geom).intersection(area)) if p.area > 1e-4]


def segment_inside(a, b, area):
    """The part of segment a–b within the plan area, or None."""
    line = LineString([a, b]).intersection(area)
    if line.is_empty or line.geom_type != "LineString" or line.length < 1e-3:
        return None
    (ax, ay), (bx, by) = line.coords[0], line.coords[-1]
    return (ax, ay), (bx, by)


def valid(polygon):
    return unary_union(parts(make_valid(polygon))) if not polygon.is_valid else polygon


def mean_width(p):
    return 2 * p.area / p.length if p.length else 0.0


def short_id(prefix, *values):
    text = ":".join(str(v) for v in values)
    return prefix + hashlib.sha1(text.encode()).hexdigest()[:6]


def rounded(coords, digits=3):
    return [[round(x, digits), round(y, digits)] for x, y in coords]


# --- Raw entity geometry (drawing units) -------------------------------------------------


def _polygon(points):
    pts = [(p[0], p[1]) for p in points]
    if len(pts) < 3:
        return []
    return [p for p in parts(valid(Polygon(pts))) if p.area > 0]


def entity_polygons(e, tolerance):
    """Closed areas drawn by an entity: hatch regions (even-odd) and closed outlines."""
    kind = e.dxftype()
    if kind == "HATCH":
        shape = None
        for boundary in epath.from_hatch(e):
            for ring in _polygon(list(boundary.flattening(tolerance))):
                shape = ring if shape is None else shape.symmetric_difference(ring)
        return parts(shape)
    if kind in ("LWPOLYLINE", "POLYLINE"):
        try:
            points = list(epath.make_path(e).flattening(tolerance))
        except (TypeError, ValueError, AttributeError):
            return []
        if len(points) < 3:
            return []
        length = sum(points[i].distance(points[i + 1]) for i in range(len(points) - 1))
        if e.is_closed or points[0].distance(points[-1]) <= 0.01 * length:
            return _polygon(points)
        return []
    if kind in ("SOLID", "TRACE"):
        v = [e.dxf.vtx0, e.dxf.vtx1, e.dxf.vtx3, e.dxf.vtx2]
        return _polygon(v)
    if kind == "CIRCLE":
        c = e.dxf.center
        return [Point(c.x, c.y).buffer(e.dxf.radius, 24)]
    return []


def entity_segments(e, tolerance):
    """Straight segments of lines and open polylines (for parallel-line walls)."""
    kind = e.dxftype()
    if kind == "LINE":
        a, b = e.dxf.start, e.dxf.end
        return [((a.x, a.y), (b.x, b.y))]
    if kind in ("LWPOLYLINE", "POLYLINE"):
        try:
            points = list(epath.make_path(e).flattening(tolerance))
        except (TypeError, ValueError, AttributeError):
            return []
        return [
            ((points[i].x, points[i].y), (points[i + 1].x, points[i + 1].y))
            for i in range(len(points) - 1)
        ]
    return []


def entity_box(e):
    if e.dxftype() in ("PDFUNDERLAY", "DWFUNDERLAY", "DGNUNDERLAY", "ACAD_TABLE", "VIEWPORT"):
        return None
    try:
        b = ebbox.extents([e], fast=True)
    except CAD_ERRORS:
        return None
    if not b.has_data:
        return None
    return (b.extmin.x, b.extmin.y, b.extmax.x, b.extmax.y)


def text_of(e):
    try:
        value = e.plain_text() if e.dxftype() == "MTEXT" else e.dxf.text
    except CAD_ERRORS:
        return ""
    return re.sub(r"\\[A-Za-z][^;]*;|[{}]", "", value or "").strip()


# --- Units and plans ---------------------------------------------------------------------


def hidden_layers(doc):
    """Layers switched off or frozen: not part of the drawing as shown, so never read."""
    out = set()
    for layer in doc.layers:
        try:
            if layer.is_off() or layer.is_frozen():
                out.add(layer.dxf.name)
        except CAD_ERRORS:
            continue
    return out


def wall_layer(layer, extra=(), excluded=()):
    return layer not in excluded and (layer in extra or C.layer_role(layer) == "wall")


def raw_walls(doc, extra=(), excluded=()):
    """Wall-layer polygons in drawing units, before scale is known."""
    msp = doc.modelspace()
    excluded = set(excluded) | hidden_layers(doc)
    extents = ebbox.extents([e for e in msp if wall_layer(e.dxf.layer, extra, excluded)], fast=True)
    size = max(extents.size.x, extents.size.y) if extents.has_data else 1.0
    tolerance = max(size, 1e-6) / 20000
    out = []
    for e in msp:
        if e.dxftype() == "INSERT" or not wall_layer(e.dxf.layer, extra, excluded):
            continue
        out.extend(entity_polygons(e, tolerance))
    return out, tolerance


THIN_SHARE = 0.03  # a wall is thinner than 3 % of the whole drawing (any unit)
INFERRED_SHARE = 0.3  # layers with at least this share of the best layer's thin area


def inferred_wall_layers(doc):
    """Wall layers chosen by geometry when no layer is named as walls.

    Layer naming is not standard between offices. When no layer matches the wall vocabulary,
    the layers whose solid fills and closed outlines are mostly thin (walls, not rooms or
    furniture) are used instead; they are reported as inferred and checked by the user.
    """
    if raw_walls(doc)[0]:
        return []
    hidden = hidden_layers(doc)
    shapes = [
        e
        for e in doc.modelspace()
        if e.dxf.layer not in hidden
        and e.dxftype() in ("HATCH", "LWPOLYLINE", "POLYLINE")
        and C.layer_role(e.dxf.layer) not in ("ignored", "furniture", "door", "window", "carpentry")
        and not (e.dxftype() == "HATCH" and not e.dxf.solid_fill)
    ]
    extents = ebbox.extents(shapes, fast=True)
    if not extents.has_data:
        return []
    size = max(extents.size.x, extents.size.y) or 1.0
    tolerance = size / 20000
    thin = Counter()
    for e in shapes:
        for p in entity_polygons(e, tolerance):
            if p.area > 0 and mean_width(p) <= size * THIN_SHARE:
                thin[e.dxf.layer] += p.area * (2 if e.dxftype() == "HATCH" else 1)
    if not thin:
        return []
    best = thin.most_common(1)[0][1]
    return sorted(layer for layer, area in thin.items() if area >= INFERRED_SHARE * best)


def detect_units(doc, wall_polygons=None, dimensions=None):
    """Metres per drawing unit and where that came from. Never guessed silently."""
    if wall_polygons is None:
        wall_polygons, _ = raw_walls(doc)
    widths = [mean_width(p) for p in wall_polygons if p.area > 0]
    width = statistics.median(widths) if widths else None
    union = unary_union(wall_polygons) if wall_polygons else None
    size = None
    if union is not None and not union.is_empty:
        x0, y0, x1, y1 = union.bounds
        size = max(x1 - x0, y1 - y0)
    if dimensions is None:
        dimensions = []
        for d in doc.modelspace().query("DIMENSION"):
            try:
                value = d.get_measurement()
            except CAD_ERRORS:
                value = None
            if isinstance(value, (int, float)) and value > 0:
                dimensions.append(value)
    dim = statistics.median(dimensions) if dimensions else None

    def plausible(factor):
        checks = []
        if width:
            checks.append(0.03 <= width * factor <= 0.7)
        if size:
            checks.append(2 <= size * factor <= 400)
        if dim:
            checks.append(0.03 <= dim * factor <= 60)
        return all(checks) if checks else False

    code = doc.header.get("$INSUNITS", 0)
    candidates = [(n, f) for n, f in [("mm", 0.001), ("cm", 0.01), ("m", 1.0)] if plausible(f)]
    evidence = [f"grosor medio de muro {width:.4g}" if width else None]
    evidence += [f"tamaño {size:.4g}" if size else None]
    evidence += [f"{len(dimensions)} cotas (mediana {dim:.4g})" if dim else None]
    found = ", ".join(e for e in evidence if e)
    if code in UNITS:
        name, factor = UNITS[code]
        if (width or size) and not plausible(factor) and len(candidates) == 1:
            # A common mislabel (e.g. a plan drawn in metres saved as mm). The geometry fits
            # exactly one unit: use it, say so, and let the user check it in the review.
            right, right_factor = candidates[0]
            return {
                "name": right,
                "metres_per_unit": right_factor,
                "source": f"inferidas: el archivo declara {name} ($INSUNITS = {code}), pero "
                f"{found} (unidades del dibujo) solo son coherentes con {right}. Compruébalo.",
                "inferred": True,
                "declared": name,
            }
        if (width or size) and not plausible(factor):
            described = ", ".join(
                f"{label} {value * factor:.3f} m"
                for label, value in [("grosor típico de muro", width), ("tamaño", size)]
                if value
            )
            raise ValueError(
                f"Las unidades declaradas en el dibujo ($INSUNITS = {name}) no son coherentes "
                f"con su geometría ({described}). Corrige las unidades del archivo (comando "
                "UNITS) y vuelve a subirlo."
            )
        return {
            "name": name,
            "metres_per_unit": factor,
            "source": f"$INSUNITS = {code} ({name}) declarado en el archivo",
            "inferred": False,
        }
    if len(candidates) == 1:
        name, factor = candidates[0]
        return {
            "name": name,
            "metres_per_unit": factor,
            "source": "inferidas: $INSUNITS sin definir; "
            + found
            + f" (unidades del dibujo) solo son coherentes con {name}",
            "inferred": True,
        }
    raise ValueError(
        "No se pueden determinar las unidades del dibujo: $INSUNITS no está definido y el "
        "tamaño del dibujo es ambiguo. Define las unidades (comando UNITS) y vuelve a subirlo."
    )


def scaled(geom, factor):
    return affinity.scale(geom, factor, factor, origin=(0, 0)) if factor != 1 else geom


def plan_name(texts, bounds, index):
    x0, y0, x1, y1 = bounds
    near = []
    for t in texts:
        value = C.normalise(t["text"])
        if PLAN_TITLE.search(value) and x0 - 4 <= t["x"] <= x1 + 4 and y0 - 4 <= t["y"] <= y1 + 4:
            inside = x0 <= t["x"] <= x1 and y0 <= t["y"] <= y1
            near.append((inside, Point(t["x"], t["y"]).distance(Point(x0, y0)), t["text"][:80]))
    return min(near)[2] if near else f"Dibujo {index + 1}"


def all_texts(doc, factor):
    out = []
    hidden = hidden_layers(doc)
    for e in doc.modelspace():
        if e.dxf.layer in hidden:
            continue
        kind = e.dxftype()
        if kind in ("TEXT", "MTEXT"):
            items = [(e, text_of(e))]
        elif kind == "INSERT":
            items = [(a, a.dxf.text) for a in getattr(e, "attribs", [])]
        else:
            continue
        for source, value in items:
            if not value or not value.strip():
                continue
            p = source.dxf.insert
            out.append(
                {
                    "text": value.strip(),
                    "x": p.x * factor,
                    "y": p.y * factor,
                    "handle": e.dxf.handle,
                    "layer": e.dxf.layer,
                }
            )
    return out


def detect_plans(doc, units, extra=(), excluded=()):
    """Separate drawings in model space (several plans/floors), largest first."""
    polygons, _ = raw_walls(doc, extra, excluded)
    factor = units["metres_per_unit"]
    walls = [
        p
        for p in (scaled(p, factor) for p in polygons)
        if mean_width(p) <= C.WALL_MAX_MEAN_WIDTH and p.area > 1e-4
    ]
    if not walls:
        layers = sorted({e.dxf.layer for e in doc.modelspace()})
        raise ValueError(
            "No se han encontrado muros en el DWG. Las capas de muros deben llamarse como "
            "MUROS, TABIQUES, A-WALL o «sección» (ver docs/USER_GUIDE.md). Capas del dibujo: "
            + ", ".join(layers[:40])
        )
    blob = unary_union([w.buffer(C.PLAN_CLUSTER_DISTANCE / 2) for w in walls])
    texts = all_texts(doc, factor)
    plans = []
    for component in sorted(parts(blob), key=lambda p: -p.area):
        inside = [w for w in walls if component.contains(w.representative_point())]
        area = sum(w.area for w in inside)
        x0, y0, x1, y1 = unary_union(inside).bounds
        if area < 0.5 or min(x1 - x0, y1 - y0) < 2:
            continue
        bounds = [round(v, 3) for v in (x0, y0, x1, y1)]
        plans.append(
            {
                "index": len(plans),
                "bounds": bounds,
                "size_m": [round(x1 - x0, 2), round(y1 - y0, 2)],
                "wall_area_m2": round(area, 2),
                "name": plan_name(texts, bounds, len(plans)),
            }
        )
    if not plans:
        raise ValueError("Los muros encontrados no forman ninguna planta reconocible.")
    return plans


# --- Gaps between wall ends ---------------------------------------------------------------


def _edges(walls):
    out = []
    for poly in parts(walls):
        for ring in [poly.exterior, *poly.interiors]:
            coords = list(ring.coords)
            for a, b in pairwise(coords):
                if C.GAP_DEPTH[0] <= math.dist(a, b) <= C.GAP_DEPTH[1]:
                    out.append((a, b))
    return out


def gap_rect(origin, axis, normal, across, along):
    """Rectangle spanning ``across`` on the width axis and ``along`` on the depth axis."""
    (ox, oy), (ux, uy), (nx, ny) = origin, axis, normal

    def at(s, t):
        return (ox + ux * s + nx * t, oy + uy * s + ny * t)

    (s0, s1), (t0, t1) = across, along
    return Polygon([at(s0, t0), at(s1, t0), at(s1, t1), at(s0, t1)])


def find_gaps(walls):
    """Openings in the wall: rectangles between two facing wall ends (jambs) with free space on
    both faces of the wall. Niches (a wall behind) and gaps between unrelated walls are dropped."""
    found = []
    edges = _edges(walls)
    probe = walls.buffer(0.001)
    for i, (a1, b1) in enumerate(edges):
        length1 = math.dist(a1, b1)
        tx, ty = (b1[0] - a1[0]) / length1, (b1[1] - a1[1]) / length1  # along the jamb (depth)
        wx, wy = -ty, tx  # across the opening (width)
        for a2, b2 in edges[i + 1 :]:
            length2 = math.dist(a2, b2)
            vx, vy = (b2[0] - a2[0]) / length2, (b2[1] - a2[1]) / length2
            if abs(tx * vy - ty * vx) > 0.03:
                continue
            d = (a2[0] - a1[0]) * wx + (a2[1] - a1[1]) * wy
            if not C.GAP_WIDTH[0] <= abs(d) <= C.GAP_WIDTH[1]:
                continue
            s2 = sorted(
                (
                    (a2[0] - a1[0]) * tx + (a2[1] - a1[1]) * ty,
                    (b2[0] - a1[0]) * tx + (b2[1] - a1[1]) * ty,
                )
            )
            lo, hi = max(0.0, s2[0]), min(length1, s2[1])
            if hi - lo < max(C.GAP_DEPTH[0], 0.6 * min(length1, length2)):
                continue
            # Width axis runs from jamb 1 to jamb 2; depth axis along the jambs.
            sign = 1 if d > 0 else -1
            axis, normal = (wx * sign, wy * sign), (tx, ty)
            width, depth = abs(d), hi - lo
            rect = gap_rect(a1, axis, normal, (0, width), (lo, hi))
            if walls.intersection(rect.buffer(-0.003, join_style=2)).area > 0.02 * rect.area:
                continue
            frame = {"origin": a1, "axis": axis, "normal": normal}

            def point(s, t, frame=frame):
                (ox, oy), (ux, uy), (nx, ny) = frame["origin"], frame["axis"], frame["normal"]
                return Point(ox + ux * s + nx * t, oy + uy * s + ny * t)

            middle = (lo + hi) / 2
            jambs = probe.contains(point(-0.02, middle)) and probe.contains(
                point(width + 0.02, middle)
            )
            # Both faces free: something to pass through, not a recess backed by a wall.
            faces = [point(width * f, lo - 0.05) for f in (0.25, 0.5, 0.75)]
            faces += [point(width * f, hi + 0.05) for f in (0.25, 0.5, 0.75)]
            if not jambs or any(probe.contains(p) for p in faces):
                continue
            found.append(
                {
                    "width": width,
                    "depth": depth,
                    "rect": rect,
                    **frame,
                    "across": (0, width),
                    "along": (lo, hi),
                }
            )
    kept = []
    for gap in sorted(found, key=lambda g: g["width"]):
        if any(
            gap["rect"].intersection(k["rect"]).area > 0.2 * min(gap["rect"].area, k["rect"].area)
            for k in kept
        ):
            continue
        kept.append(gap)
    return kept


def project(gap, point):
    (ox, oy), (ux, uy), (nx, ny) = gap["origin"], gap["axis"], gap["normal"]
    return (point[0] - ox) * ux + (point[1] - oy) * uy, (point[0] - ox) * nx + (point[1] - oy) * ny


def merge_stacked(gaps, walls):
    """A stepped jamb splits one opening into two gaps stacked through the wall: join them."""
    used = set()
    for a in gaps:
        if id(a) in used or not (a["blocks"] or a["loose"]):
            continue
        for b in gaps:
            if b is a or id(b) in used or b["blocks"] or b["loose"]:
                continue
            if a["rect"].intersection(b["rect"]).length < 0.4 * min(a["width"], b["width"]):
                continue
            pts = [project(a, p) for p in list(b["rect"].exterior.coords)[:-1]]
            across_b = (min(p[0] for p in pts), max(p[0] for p in pts))
            along_b = (min(p[1] for p in pts), max(p[1] for p in pts))
            if (
                abs(
                    abs(
                        project(
                            a, (a["origin"][0] + b["normal"][0], a["origin"][1] + b["normal"][1])
                        )[1]
                    )
                    - 1
                )
                > 0.03
            ):
                continue  # not parallel
            across = (max(a["across"][0], across_b[0]), min(a["across"][1], across_b[1]))
            along = (min(a["along"][0], along_b[0]), max(a["along"][1], along_b[1]))
            if across[1] - across[0] < 0.45 or along[1] - along[0] > C.GAP_DEPTH[1]:
                continue
            rect = gap_rect(a["origin"], a["axis"], a["normal"], across, along)
            if walls.intersection(rect.buffer(-0.003, join_style=2)).area > 0.02 * rect.area:
                continue
            a.setdefault("merged_rects", []).append(b["rect"])
            a.update(
                rect=rect,
                across=across,
                along=along,
                width=across[1] - across[0],
                depth=along[1] - along[0],
            )
            a.setdefault("merged", []).append(b["id"])
            used.add(id(b))
    return [g for g in gaps if id(g) not in used]


# --- Blocks --------------------------------------------------------------------------------


def block_display_name(doc, insert):
    """Block name; anonymous dynamic-block references (*U…) resolve to their source block."""
    name = insert.dxf.name
    if not name.startswith("*"):
        return name
    try:
        record = doc.blocks.get(name).block_record
        if record.has_xdata("AcDbBlockRepBTag"):
            for code, value in record.get_xdata("AcDbBlockRepBTag"):
                if code == 1005:
                    source = doc.entitydb.get(value)
                    if source is not None and source.dxf.hasattr("name"):
                        return source.dxf.name
    except CAD_ERRORS:
        return name
    return name


def block_content(doc, insert):
    block = doc.blocks.get(insert.dxf.name)
    if block is None:
        return {}
    counts = Counter(e.dxftype() for e in block)
    return dict(sorted(counts.items()))


def _arc(e, factor):
    """Arc centre, radius and mid-point in world metres (mirrored arcs live in a flipped OCS)."""
    ocs, c, r = e.ocs(), e.dxf.center, e.dxf.radius
    start, end = e.dxf.start_angle, e.dxf.end_angle
    mid = math.radians((start + end + (360 if end < start else 0)) / 2)
    centre = ocs.to_wcs(c)
    point = ocs.to_wcs((c.x + r * math.cos(mid), c.y + r * math.sin(mid), c.z))
    return {
        "center": (centre.x * factor, centre.y * factor),
        "radius": r * factor,
        "mid": (point.x * factor, point.y * factor),
        "handle": e.dxf.handle,
    }


def insert_geometry(insert, factor):
    """Oriented footprint (metres), arcs and front direction of a block reference."""
    rotation = math.radians(insert.dxf.rotation)
    ix, iy = insert.dxf.insert.x, insert.dxf.insert.y
    cos, sin = math.cos(-rotation), math.sin(-rotation)
    local, arcs, types, outlines = [], [], Counter(), []
    try:
        entities = list(disassemble.recursive_decompose([insert]))
    except CAD_ERRORS:
        entities = []
    shapes = []
    for e in entities:
        if e.dxf.get("invisible", 0):
            continue  # hidden visibility states of dynamic blocks
        kind = e.dxftype()
        types[kind] += 1
        if kind in SKIP_TYPES or kind == "INSERT":
            continue
        if kind == "ARC":
            arcs.append(_arc(e, factor))
        outline = _outline(e, factor)
        if outline is not None:
            outlines.append(outline)
        shapes.append(e)
    try:
        for primitive in disassemble.to_primitives(shapes):
            for v in primitive.vertices():
                dx, dy = v.x - ix, v.y - iy
                local.append((dx * cos - dy * sin, dx * sin + dy * cos))
    except CAD_ERRORS:
        local = []
    if len(local) < 2:
        return None
    xs, ys = [p[0] for p in local], [p[1] for p in local]
    corners = [(min(xs), min(ys)), (max(xs), min(ys)), (max(xs), max(ys)), (min(xs), max(ys))]
    cos, sin = math.cos(rotation), math.sin(rotation)
    world = [
        ((x * cos - y * sin + ix) * factor, (x * sin + y * cos + iy) * factor) for x, y in corners
    ]
    rect = Polygon(world)
    if not rect.is_valid or rect.area <= 0:
        return None
    front = insert.matrix44().transform_direction((0, -1, 0))
    norm = math.hypot(front.x, front.y) or 1
    return {
        "rect": rect,
        "insert": (ix * factor, iy * factor),
        "front": (front.x / norm, front.y / norm),
        "arcs": arcs,
        "types": dict(types),
        "mirrored": insert.dxf.xscale * insert.dxf.yscale < 0,
        "rotation": round(insert.dxf.rotation % 360, 1),
        "outlines": outlines,
    }


def _outline(e, factor):
    """Closed shape drawn inside a block (closed polyline or wipeout mask), world metres."""
    kind = e.dxftype()
    try:
        if kind == "WIPEOUT":
            points = [(v.x, v.y) for v in e.boundary_path_wcs()]
        elif kind in ("LWPOLYLINE", "POLYLINE"):
            path = list(epath.make_path(e).flattening(0.002 / factor))
            closed = getattr(e, "closed", False) or getattr(e, "is_closed", False)
            if len(path) < 4 or not (closed or path[0].distance(path[-1]) <= 1e-6 / factor):
                return None
            points = [(v.x, v.y) for v in path]
        else:
            return None
    except CAD_ERRORS:
        return None
    shapes = _polygon([(x * factor, y * factor) for x, y in points])
    return max(shapes, key=lambda p: p.area) if shapes else None


def components(outlines, min_side=0.25, min_area=0.06):
    """Distinct objects drawn in a block: an inner contour of the same object (a frame line
    covering most of it) is dropped; a smaller object drawn on top of another is kept."""
    shapes = [
        p
        for p in outlines
        if p.area >= min_area and sides_m(p.minimum_rotated_rectangle)[0] >= min_side
    ]
    kept = []
    for p in sorted(shapes, key=lambda p: -p.area):
        if any(p.intersection(q).area > 0.9 * p.area and p.area >= 0.8 * q.area for q in kept):
            continue
        kept.append(p)
    return kept


def split_composite(b, kind):
    """Bed/sofa blocks that also draw nightstands, a rug or a table: the main piece keeps the
    named kind (an L-shaped sofa becomes straight modules facing into the L); the other pieces
    are returned for classification. Returns (main pieces, other pieces) or None."""
    parts_ = components(b["outlines"])
    if kind not in ("bed_double", "bed_single", "sofa") or len(parts_) < 2:
        return None
    if kind == "sofa":  # a rug drawn around the sofa is not the sofa
        containers = [
            c for c in parts_ if any(c.contains(o.buffer(-0.01)) for o in parts_ if o is not c)
        ]
        candidates = [c for c in parts_ if not any(c is k for k in containers)] or parts_
    else:
        candidates = parts_
    main = max(candidates, key=lambda p: p.area)
    # Pieces mostly inside the main one (pillows, cushions) are part of it, not separate objects.
    others = [c for c in parts_ if c is not main and c.intersection(main).area < 0.5 * c.area]
    if not others:
        return None
    box = main.minimum_rotated_rectangle
    if main.area >= 0.8 * box.area:
        return [(box, None)], others
    notch = box.difference(main)
    centre = notch.centroid if not notch.is_empty else box.centroid
    pieces = []
    for piece in convex_pieces(main):
        rect = piece.minimum_rotated_rectangle
        if sides_m(rect)[0] < 0.3:
            continue
        c = rect.centroid
        dx, dy = centre.x - c.x, centre.y - c.y
        norm = math.hypot(dx, dy) or 1
        pieces.append((rect, (dx / norm, dy / norm)))
    return (pieces, others) if pieces else None


def sides_m(rect):
    coords = list(rect.exterior.coords)
    lengths = sorted(math.dist(a, b) for a, b in pairwise(coords))
    return lengths[0], lengths[-1]


# --- Rooms ----------------------------------------------------------------------------------

AREA_LINE = re.compile(r"(?i)^(sup\b|sup\.|superficie|s\s*[:=]|[\d.,\s]+m2?$|[\d.,\s]+m²$)")
STREET = re.compile(r"^(CALLE|C/|AVENIDA|AVDA|PLAZA|PASEO|CARRER|AV\.|TRAVESIA|RONDA)\b")


def room_lines(text):
    for line in re.split(r"\\P|\n", text):
        line = line.strip()
        if (
            len(line) >= 3
            and re.search(r"[A-Za-zÁÉÍÓÚáéíóúÑñÇçÀÈÒàèò]{3}", line)
            and not AREA_LINE.match(line)
        ):
            yield line[:80]


def find_rooms(walls, closures, texts, hatches):
    """Spaces enclosed by walls and closed openings, named by the text inside them."""
    closed = unary_union([walls, *closures])
    closed = closed.buffer(0.03, join_style=2).buffer(-0.03, join_style=2)
    rooms = [
        Polygon(ring).simplify(0.005)
        for p in parts(closed)
        for ring in p.interiors
        if Polygon(ring).area > 1.0
    ]
    rooms.sort(key=lambda r: (-round(r.centroid.y, 1), r.centroid.x))
    records = []
    for room in rooms:
        labels = []
        for t in texts:
            if room.contains(Point(t["x"], t["y"])):
                for line in room_lines(t["text"]):
                    if not STREET.match(C.normalise(line)):
                        labels.append((room.centroid.distance(Point(t["x"], t["y"])), line, t))
                    break
        labels.sort(key=lambda item: item[0])
        record = {
            "id": short_id("R", round(room.centroid.x, 1), round(room.centroid.y, 1)),
            "polygon": room,
            "name": labels[0][1] if labels else None,
            "name_handle": labels[0][2]["handle"] if labels else None,
            "name_layer": labels[0][2]["layer"] if labels else None,
            "other_labels": [label for _, label, _ in labels[1:]],
            "finish": None,
            "pattern": None,
            "finish_handle": None,
        }
        best = 0.0
        for pattern, area, handle in hatches:
            cover = room.intersection(area).area / room.area
            if cover >= 0.5 and cover > best:
                best = cover
                record.update(pattern=pattern, finish_handle=handle, finish=C.hatch_finish(pattern))
        records.append(record)
    return records


def split_rings(polygon):
    """Cut a wall polygon with holes into hole-free pieces (the schema forbids ring walls)."""
    pending, done = [polygon], []
    while pending:
        p = pending.pop()
        if not p.interiors:
            done.append(p)
            continue
        hole = Polygon(p.interiors[0]).representative_point()
        x0, y0, x1, y1 = p.bounds
        pieces = parts(split(p, LineString([(x0 - 1, hole.y), (x1 + 1, hole.y)])))
        if len(pieces) <= 1:
            pieces = parts(split(p, LineString([(hole.x, y0 - 1), (hole.x, y1 + 1)])))
        if len(pieces) <= 1:
            done.append(Polygon(p.exterior))
            continue
        pending.extend(pieces)
    return done


def convex_pieces(polygon, limit=60):
    """Split a wall outline at its reflex corners into convex pieces. Large orthogonal outlines
    make Blender's ear-clipping emit zero-area cap triangles; convex pieces never do."""
    pending, done = [polygon], []
    while pending:
        p = orient(pending.pop(), 1.0)
        coords = list(p.exterior.coords)[:-1]
        n = len(coords)
        reflex = None
        for i in range(n):
            a, b, c = coords[i - 1], coords[i], coords[(i + 1) % n]
            if (b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0]) < -1e-9:
                reflex = (a, b, c)
                break
        if reflex is None or len(done) + len(pending) >= limit:
            done.append(p)
            continue
        a, b, c = reflex
        x0, y0, x1, y1 = p.bounds
        reach = 2 * math.hypot(x1 - x0, y1 - y0)
        pieces = []
        for (fx, fy), (tx, ty) in ((a, b), (c, b)):  # extend either edge through the corner
            length = math.dist((fx, fy), (tx, ty)) or 1
            dx, dy = (tx - fx) / length, (ty - fy) / length
            ray = LineString([b, (b[0] + dx * reach, b[1] + dy * reach)])
            pieces = [q for q in parts(split(p, ray)) if q.area > 1e-6]
            if len(pieces) > 1:
                break
        if len(pieces) <= 1:
            done.append(p)
            continue
        pending.extend(t for q in pieces for t in tidy(q))
    return [t for q in done for t in tidy(q)]


def tidy(polygon):
    """Valid, spike-free polygonal parts (splits and simplification can leave zero-width spikes)."""
    snapped = shapely.set_precision(polygon, GRID)  # collapses nanometre slivers and spikes
    cleaned = make_valid(snapped.simplify(0.0005)).buffer(0)
    return [Polygon(q.exterior) for q in parts(cleaned) if q.area > 1e-6]


# --- Reading -------------------------------------------------------------------------------


def opening_name(name):
    if C.matches(name, C.DOOR_BLOCKS):
        return "door"
    if C.matches(name, C.WINDOW_BLOCKS):
        return "window"
    return None


def gap_for_block(block, gaps):
    """The gap a door/window block sits in: hinge (arc centre) or insertion point at a jamb,
    or a block spanning most of the opening width. Furniture blocks never qualify."""
    if C.furniture_kind([block["block"], block.get("raw_block")], 1.0):
        return None
    best, score = None, None
    for g in gaps:
        inter = block["rect"].intersection(g["rect"]).area
        if inter < 0.15 * g["rect"].area:
            continue  # touching or a sliver overlap: a neighbouring piece, not this opening's
        pts = [project(g, p) for p in list(block["rect"].exterior.coords)[:-1]]
        span = min(max(p[0] for p in pts), g["width"]) - max(min(p[0] for p in pts), 0)
        if span < 0.5 * g["width"]:
            continue
        anchors = [a["center"] for a in block["arcs"]] or [block["insert"]]
        distance = min(g["rect"].distance(Point(a)) for a in anchors)
        value = (distance, -inter / g["rect"].area)
        if score is None or value < score:
            best, score = g, value
    # An unnamed block far from the jambs only counts when it actually sits in the gap.
    if (
        best is not None
        and score[0] > 0.3
        and opening_name(block["block"]) is None
        and block["rect"].intersection(best["rect"]).area
        < 0.5 * min(block["rect"].area, best["rect"].area)
    ):
        return None
    return best


def read_plan(doc, plan, units, extra_walls=(), excluded_walls=()):
    """Deterministic reading of one plan; returns geometry, facts and doubts (metres)."""
    factor = units["metres_per_unit"]
    msp = doc.modelspace()
    x0, y0, x1, y1 = plan["bounds"]
    margin = C.PLAN_MARGIN
    region = (x0 - margin, y0 - margin, x1 + margin, y1 + margin)
    area = shapely.box(*region)
    _, tolerance = raw_walls(doc, extra_walls, excluded_walls)
    notes = []

    entities, boxes = [], {}
    hidden = hidden_layers(doc)
    elsewhere = Counter()
    for e in msp:
        if e.dxf.layer in hidden:
            continue
        b = entity_box(e)
        if b is None:
            continue
        b = tuple(v * factor for v in b)
        if b[2] < region[0] or b[0] > region[2] or b[3] < region[1] or b[1] > region[3]:
            elsewhere[e.dxf.layer] += 1
            continue
        entities.append(e)
        boxes[e.dxf.handle] = b

    # Walls: cut geometry on wall layers, thin enough to be a wall (floors are wider).
    pieces, segments = [], []
    for e in entities:
        layer = e.dxf.layer
        if e.dxftype() == "INSERT" or not wall_layer(layer, extra_walls, excluded_walls):
            continue
        limit = C.WALL_MAX_MEAN_WIDTH
        if e.dxftype() == "HATCH" and not e.dxf.solid_fill:
            limit = C.PATTERN_WALL_MAX_MEAN_WIDTH
        polygons = entity_polygons(e, tolerance)
        for p in polygons:
            p = scaled(p, factor)
            if p.area > 1e-4 and mean_width(p) <= limit:
                pieces += [(q, e.dxf.handle, layer) for q in inside(p, area)]
        if polygons:
            continue  # closed outlines are walls already; only loose lines form line pairs
        for a, b in entity_segments(e, tolerance):
            kept = segment_inside(
                (a[0] * factor, a[1] * factor), (b[0] * factor, b[1] * factor), area
            )
            if kept:
                segments.append((*kept, e.dxf.handle, layer))
    pieces += line_pair_walls(segments)
    if not pieces:
        raise ValueError("La planta elegida no contiene muros legibles.")
    walls = unary_union([p for p, _, _ in pieces])
    walls = walls.buffer(0.002, join_style=2).buffer(-0.002, join_style=2)
    walls = unary_union([p.simplify(0.003) for p in parts(walls) if p.area > 1e-4])
    walls = shapely.set_precision(walls, GRID)

    gaps = []
    for g in find_gaps(walls):
        c = g["rect"].centroid
        g.update(id=short_id("G", round(c.x, 2), round(c.y, 2)), blocks=[], loose=[], arcs=[])
        gaps.append(g)

    texts = [
        t
        for t in all_texts(doc, factor)
        if region[0] <= t["x"] <= region[2] and region[1] <= t["y"] <= region[3]
    ]

    blocks, annotations = [], Counter()
    for e in entities:
        if e.dxftype() != "INSERT" or C.layer_role(e.dxf.layer) == "ignored":
            continue
        name = block_display_name(doc, e)
        geometry = insert_geometry(e, factor)
        if geometry is None:
            continue
        if (
            C.matches(name, C.ANNOTATION_BLOCKS)
            or "DIMENSION" in geometry["types"]
            or not set(geometry["types"]) - SKIP_TYPES - {"CIRCLE", "INSERT"}
        ):
            annotations[e.dxf.layer] += 1
            continue
        attributes = {a.dxf.tag: a.dxf.text for a in getattr(e, "attribs", []) if a.dxf.text}
        blocks.append(
            {
                "handle": e.dxf.handle,
                "layer": e.dxf.layer,
                "block": name,
                "raw_block": e.dxf.name,
                "attributes": attributes,
                "content": block_content(doc, e),
                **geometry,
            }
        )
    if annotations:
        notes.append(
            f"{sum(annotations.values())} bloques de anotación ignorados (cotas, símbolos, círculos)."
        )

    # Blocks and loose carpentry inside each gap are the evidence of an opening.
    furniture_blocks, orphans = [], []
    for b in blocks:
        g = gap_for_block(b, gaps)
        if g is not None:
            g["blocks"].append(b)
        elif opening_name(b["block"]):
            orphans.append(b)
        else:
            furniture_blocks.append(b)
    stray = []
    for e in entities:
        role = C.layer_role(e.dxf.layer)
        if e.dxftype() == "INSERT" or role not in ("door", "window", "carpentry"):
            continue
        b = boxes[e.dxf.handle]
        shape = (
            Polygon([(b[0], b[1]), (b[2], b[1]), (b[2], b[3]), (b[0], b[3])])
            if b[2] > b[0] and b[3] > b[1]
            else LineString([(b[0], b[1]), (b[2], b[3])])
        )
        host = next((g for g in gaps if g["rect"].buffer(0.06, join_style=2).contains(shape)), None)
        if host is not None:
            host["loose"].append({"handle": e.dxf.handle, "layer": e.dxf.layer, "role": role})
        elif max(b[2] - b[0], b[3] - b[1]) >= 0.45 and min(b[2] - b[0], b[3] - b[1]) <= 0.12:
            stray.append((e.dxf.handle, e.dxf.layer, shape))
    for e in entities:
        if e.dxftype() != "ARC":
            continue
        arc = _arc(e, factor)
        for g in gaps:
            if 0.5 * g["width"] <= arc["radius"] <= 1.1 * g["width"] and g["rect"].buffer(
                0.15
            ).contains(Point(arc["center"])):
                g["arcs"].append(arc)
    gaps = merge_stacked(gaps, walls)
    for g in gaps:
        g["opening"] = classify_gap(g)

    occupied = unary_union([walls, *[g["rect"] for g in gaps]])
    outline = occupied.buffer(1.5, join_style=2).buffer(-1.5, join_style=2)
    outer = unary_union([Polygon(p.exterior) for p in parts(outline)])
    for g in gaps:
        g["on_facade"] = g["rect"].buffer(0.05).intersects(outer.boundary)
    for handle, layer, shape in stray:
        if outer.buffer(-0.3).intersects(shape):
            notes.append(
                f"Carpintería {handle} ({layer}) sin hueco en un muro (p. ej. mampara o "
                "cerramiento ligero): no se modela."
            )

    for o in orphans:
        o["candidates"] = [
            g["id"] for g in gaps if g["opening"] is None and g["rect"].distance(o["rect"]) < 1.0
        ]

    # Floor hatches (wider than walls) give finishes; preliminary rooms give context.
    hatches = []
    for e in entities:
        if e.dxftype() != "HATCH" or e.dxf.solid_fill or C.layer_role(e.dxf.layer) == "ignored":
            continue
        for shape in (scaled(p, factor) for p in entity_polygons(e, tolerance)):
            if mean_width(shape) > C.PATTERN_WALL_MAX_MEAN_WIDTH:
                hatches += [(e.dxf.pattern_name, q, e.dxf.handle) for q in inside(shape, area)]
    rooms = find_rooms(walls, closures(gaps), texts, hatches)

    # Furniture: block references, plus closed outlines drawn on furniture layers.
    furniture = []
    for b in furniture_blocks:
        short, long = sides_m(b["rect"])
        if short < 0.12 or long > 8 or b["rect"].area > 25:
            notes.append(
                f"Bloque «{b['block']}» ({b['handle']}) fuera de rango de mueble: ignorado."
            )
            continue
        if b["rect"].intersection(walls).area > 0.5 * b["rect"].area:
            notes.append(f"Bloque «{b['block']}» ({b['handle']}) sobre los muros: ignorado.")
            continue
        kind = C.furniture_kind([b["block"], b["raw_block"], *b["attributes"].values()], short)
        base = {
            "handle": b["handle"],
            "layer": b["layer"],
            "block": b["block"],
            "attributes": b["attributes"],
            "content": b["content"],
            "mirrored": b["mirrored"],
            "rotation": b["rotation"],
        }
        split = split_composite(b, kind)
        if split is None:
            furniture.append(
                {
                    **base,
                    "id": "B" + b["handle"],
                    "rect": b["rect"],
                    "front": b["front"],
                    "kind": kind,
                }
            )
            continue
        mains, others = split
        for k, (rect, front) in enumerate(mains):
            furniture.append(
                {
                    **base,
                    "id": "B" + b["handle"] + (f"-m{k + 1}" if k else ""),
                    "rect": rect,
                    "front": front or b["front"],
                    "fixed_front": front is not None,
                    "kind": C.furniture_kind([b["block"], b["raw_block"]], sides_m(rect)[0]),
                }
            )
        for k, shape in enumerate(others, start=1):
            furniture.append(
                {
                    **base,
                    "id": f"B{b['handle']}-p{k}",
                    "block": f"{b['block']} (pieza {k})",
                    "part_of": b["block"],
                    "content": {"outline": 1},
                    "rect": shape.minimum_rotated_rectangle,
                    "front": b["front"],
                    "kind": None,
                }
            )
        notes.append(
            f"Bloque «{b['block']}» ({b['handle']}) dibuja varias piezas: {len(mains)} de "
            f"{kind} y {len(others)} más para clasificar."
        )
    outlines = []
    for e in entities:
        if (
            e.dxftype() not in ("LWPOLYLINE", "POLYLINE")
            or C.layer_role(e.dxf.layer) != "furniture"
        ):
            continue
        for p in entity_polygons(e, tolerance):
            rect = scaled(p, factor).minimum_rotated_rectangle
            if rect.geom_type != "Polygon":
                continue
            short, long = sides_m(rect)
            if short >= 0.2 and long <= 8:
                outlines.append((rect, e))
    for rect, e in sorted(outlines, key=lambda item: -item[0].area):
        # Same object as a block (covers most of it) → skip; a piece inside a big block stays.
        if any(
            rect.intersection(f["rect"]).area > 0.8 * rect.area and rect.area > 0.5 * f["rect"].area
            for f in furniture
        ):
            continue
        if rect.intersection(walls).area > 0.5 * rect.area:
            continue
        furniture.append(
            {
                "id": "P" + e.dxf.handle,
                "handle": e.dxf.handle,
                "layer": e.dxf.layer,
                "block": None,
                "attributes": {},
                "content": {e.dxftype(): 1},
                "rect": rect,
                "front": (0.0, -1.0),
                "mirrored": False,
                "rotation": 0.0,
                "kind": None,
            }
        )

    # Layers with wall-like geometry that are not named as walls.
    suspects = {}
    for e in entities:
        layer = e.dxf.layer
        if e.dxftype() == "INSERT" or C.layer_role(layer) is not None:
            continue
        if wall_layer(layer, extra_walls, excluded_walls) or layer in excluded_walls:
            continue
        if e.dxftype() == "HATCH" and not e.dxf.solid_fill:
            continue
        for p in entity_polygons(e, tolerance):
            p = scaled(p, factor)
            if p.area < 0.01 or mean_width(p) > C.WALL_MAX_MEAN_WIDTH or p.distance(walls) > 0.05:
                continue
            entry = suspects.setdefault(layer, {"area": 0.0, "handles": [], "shapes": []})
            entry["area"] += p.area
            entry["handles"].append(e.dxf.handle)
            entry["shapes"].append(p)
    suspect_layers = [
        {
            "id": short_id("L", layer),
            "layer": layer,
            "area_m2": round(v["area"], 3),
            "count": len(v["handles"]),
            "handles": v["handles"][:50],
            "bounds": [round(c, 2) for c in unary_union(v["shapes"]).bounds],
        }
        for layer, v in sorted(suspects.items())
        if v["area"] >= 0.05
    ]

    wall_records = []
    for poly in parts(walls):
        for piece in split_rings(poly):
            if piece.area < 0.005:
                continue
            if piece.interiors:
                notes.append("Un muro en anillo no pudo dividirse; revisa su contorno.")
            sources = [(h, layer) for p, h, layer in pieces if p.intersects(piece.buffer(-0.002))]
            wall_records.append(
                {
                    "polygon": Polygon(piece.exterior),
                    "handles": sorted({h for h, _ in sources})[:200],
                    "layers": sorted({layer for _, layer in sources})[:20],
                }
            )
    wall_records.sort(key=lambda w: (-round(w["polygon"].centroid.y, 1), w["polygon"].centroid.x))

    labelled = {id(t) for r in rooms for t in texts if r["polygon"].contains(Point(t["x"], t["y"]))}
    for t in texts:
        if id(t) in labelled:
            continue
        line = next(room_lines(t["text"]), None)
        if (
            line
            and not STREET.match(C.normalise(line))
            and not PLAN_TITLE.search(C.normalise(line))
            and outer.buffer(1.5).contains(Point(t["x"], t["y"]))
        ):
            notes.append(f"Rótulo «{line}» fuera de un recinto cerrado por muros: no se modela.")

    slab_parts = sorted(parts(outline), key=lambda p: -p.area)
    if len(slab_parts) > 1:
        notes.append("El perímetro de la planta no es único; se usa el recinto mayor.")
    slab = Polygon(slab_parts[0].exterior).simplify(0.02)

    inventory = layer_inventory(
        doc,
        entities,
        elsewhere,
        hidden,
        {
            "walls": wall_records,
            "gaps": gaps,
            "furniture": furniture,
            "rooms": rooms,
            "suspects": suspect_layers,
            "annotations": annotations,
            "hatches": hatches,
            "texts": texts,
        },
        extra_walls,
    )
    for row in inventory:
        if row["match"] and row["match"].startswith("parecido"):
            notes.append(
                f"Capa «{row['layer']}» leída como {ROLE_NAMES[row['role']]} "
                f"(nombre {row['match']})."
            )
        if row["status"] == "sin uso" and row["in_plan"]:
            count = sum(row["in_plan"].values())
            reason = (
                "su nombre no indica muros, huecos ni mobiliario"
                if row["role"] is None
                else f"capa de {ROLE_NAMES[row['role']]}, pero ningún elemento está en un hueco "
                "de muro ni forma una pieza"
            )
            notes.append(
                f"Capa «{row['layer']}»: {count} elementos en la planta sin uso ({reason})."
            )
    return {
        "layers": inventory,
        "units": units,
        "plan": plan,
        "region": region,
        "walls": wall_records,
        "wall_union": walls,
        "gaps": gaps,
        "orphans": orphans,
        "furniture": furniture,
        "rooms": rooms,
        "hatches": hatches,
        "suspect_layers": suspect_layers,
        "texts": texts,
        "slab": slab,
        "notes": notes,
    }


ROLE_NAMES = {
    "wall": "muros",
    "door": "puertas",
    "window": "ventanas",
    "carpentry": "carpintería",
    "furniture": "mobiliario",
    "ignored": "anotación (ignorada)",
    None: "sin función",
}


def layer_inventory(doc, entities, elsewhere, hidden, found, extra_walls=()):
    """Every layer of the drawing: role, how its name matched, state, contents and use."""
    in_plan = {}
    for e in entities:
        in_plan.setdefault(e.dxf.layer, Counter())[e.dxftype()] += 1
    used = {}

    def mark(layer, what):
        if layer:
            used.setdefault(layer, set()).add(what)

    for w in found["walls"]:
        for layer in w["layers"]:
            mark(layer, "muros")
    for g in found["gaps"]:
        for b in g["blocks"]:
            mark(b["layer"], "huecos")
        for item in g["loose"]:
            mark(item["layer"], "huecos")
    for f in found["furniture"]:
        mark(f["layer"], "mobiliario")
    rooms = found["rooms"]
    for r in rooms:
        mark(r["name_layer"], "rótulos de estancia")
    finish_handles = {r["finish_handle"] for r in rooms if r["finish_handle"]}
    for e in entities:
        if e.dxf.handle in finish_handles:
            mark(e.dxf.layer, "pavimentos")
    for s in found["suspects"]:
        mark(s["layer"], "duda: ¿muros?")
    for layer, n in found["annotations"].items():
        mark(layer, f"{n} anotaciones ignoradas")
    names = {layer.dxf.name for layer in doc.layers} | set(in_plan) | set(elsewhere)
    rows = []
    for name in sorted(names, key=lambda n: (n not in in_plan, C.normalise(n))):
        role, how = C.layer_match(name)
        if name in extra_walls:
            role, how = "wall", "confirmado en la revisión"
        uses = sorted(used.get(name, set()))
        if name in hidden:
            status = "apagada o congelada"
        elif uses:
            status = "usada"
        elif role == "ignored":
            status = "ignorada"
        elif name in in_plan:
            status = "sin uso"
        else:
            status = "vacía en la planta"
        rows.append(
            {
                "layer": name,
                "role": role,
                "match": how,
                "status": status,
                "used": uses,
                "in_plan": dict(sorted(in_plan.get(name, Counter()).items())),
                "elsewhere": elsewhere.get(name, 0),
            }
        )
    return rows


def closures(gaps, kinds=None):
    """Gaps that bound rooms: openings (or doubtful carpentry) and narrow passages."""
    out = []
    for g in gaps:
        drawn = (g["opening"]["kind"] or "doubt") if g["opening"] else None
        kind = (kinds or {}).get(g["id"], drawn)
        if kind in ("door", "window", "doubt") or (kind is None and g["width"] <= 1.3):
            out.append(g["rect"])
            out.extend(g.get("merged_rects", []))
    return out


def classify_gap(g):
    """Opening kind/style when the drawing names it; a doubt when only carpentry is drawn."""
    named = [(opening_name(b["block"]), b) for b in g["blocks"]]
    named = [(k, b) for k, b in named if k]
    roles = {item["role"] for item in g["loose"]} | {C.layer_role(b["layer"]) for b in g["blocks"]}
    arcs = [a for b in g["blocks"] for a in b["arcs"]] + g["arcs"]
    handles = [b["handle"] for b in g["blocks"]] + [i["handle"] for i in g["loose"]]
    layers = sorted({b["layer"] for b in g["blocks"]} | {i["layer"] for i in g["loose"]})
    block = next((b["block"] for _, b in named), g["blocks"][0]["block"] if g["blocks"] else None)
    if not handles:
        return None  # open passage: nothing drawn in the gap
    kind = (
        named[0][0]
        if named
        else ("door" if "door" in roles else "window" if "window" in roles else None)
    )
    record = {
        "kind": kind,
        "style": None,
        "status": "verified" if kind else "doubt",
        "handles": handles[:50],
        "layers": layers,
        "block": block,
        "has_arc": bool(arcs),
        "detail": None,
        "swing": None,
    }
    texts = [block or "", *layers]
    if kind == "door":
        if any(C.matches(t, C.POCKET) for t in texts):
            record["style"], record["detail"] = "sliding", "Corredera empotrada (casoneto)"
        elif any(C.matches(t, C.SLIDING) for t in texts):
            record["style"] = "sliding"
        elif arcs:
            record["style"] = "hinged"
            record["swing"] = swing_side(g, arcs[0])
        else:
            record["style"] = "hinged"
            record["detail"] = "Puerta sin arco de giro dibujado: abatible supuesta"
    elif kind == "window":
        if any(C.matches(t, C.SLIDING) for t in texts):
            record["style"] = "sliding"
        elif any(C.matches(t, C.FIXED) for t in texts):
            record["style"] = "fixed"
        else:
            record["style"] = "casement"
            record["detail"] = "Ventana practicable supuesta (el bloque no indica el tipo)"
    return record


def swing_side(g, arc):
    """Hinge jamb and the face of the wall the leaf opens to, from the swing arc."""
    hinge, _ = project(g, arc["center"])
    _, side = project(g, arc["mid"])
    middle = sum(g["along"]) / 2
    return {
        "hinge": "start" if hinge < g["width"] / 2 else "end",
        "opens_to": [round(v, 3) for v in arc["mid"]],
        "face": "normal" if side > middle else "reverse",
    }


def line_pair_walls(segments):
    """Walls drawn as two parallel lines: a rectangle between each facing pair."""
    low, high = C.WALL_LINE_PAIR
    out = []
    usable = [s for s in segments if math.dist(s[0], s[1]) >= 0.2]
    for i, (a1, b1, h1, l1) in enumerate(usable):
        length = math.dist(a1, b1)
        ux, uy = (b1[0] - a1[0]) / length, (b1[1] - a1[1]) / length
        nx, ny = -uy, ux
        for a2, b2, h2, l2 in usable[i + 1 :]:
            length2 = math.dist(a2, b2)
            vx, vy = (b2[0] - a2[0]) / length2, (b2[1] - a2[1]) / length2
            if abs(ux * vy - uy * vx) > 0.02:
                continue
            d = (a2[0] - a1[0]) * nx + (a2[1] - a1[1]) * ny
            if not low <= abs(d) <= high:
                continue
            s = sorted(
                (
                    (a2[0] - a1[0]) * ux + (a2[1] - a1[1]) * uy,
                    (b2[0] - a1[0]) * ux + (b2[1] - a1[1]) * uy,
                )
            )
            lo, hi = max(0.0, s[0]), min(length, s[1])
            if hi - lo < 0.2:
                continue
            rect = gap_rect(a1, (ux, uy), (nx, ny), (lo, hi), (0, d) if d > 0 else (d, 0))
            out.append((rect, h1, l1))
            out.append((rect, h2, l2))
    return out

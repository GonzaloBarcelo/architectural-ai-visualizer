"""Source-anchored furniture, opening evidence and floor finishes read from PDF vectors.

Furniture footprints come from the drawing itself (white masks behind furniture blocks and
closed furniture strokes). The AI only classifies a candidate and says which side is its
front; a deterministic pass then checks that orientation against the walls.
"""

import math
from typing import Literal

from pydantic import BaseModel, Field
from shapely.geometry import LineString, Point, Polygon, box
from shapely.ops import polygonize, unary_union

FurnitureKind = Literal[
    "bed_double",
    "bed_single",
    "nightstand",
    "wardrobe",
    "dresser",
    "desk",
    "shelving",
    "sofa",
    "armchair",
    "coffee_table",
    "side_table",
    "rug",
    "tv_unit",
    "sideboard",
    "dining_set",
    "dining_table",
    "chair",
    "stool",
    "kitchen_counter",
    "kitchen_island",
    "fridge",
    "toilet",
    "bidet",
    "washbasin",
    "shower",
    "bathtub",
    "washing_machine",
    "plant",
    "floor_lamp",
    "not_furniture",
]
Side = Literal["up", "down", "left", "right"]

HEIGHTS = {
    "bed_double": 1.1,
    "bed_single": 1.1,
    "nightstand": 0.5,
    "wardrobe": 2.4,
    "dresser": 0.8,
    "desk": 0.75,
    "shelving": 2.0,
    "sofa": 0.8,
    "armchair": 0.8,
    "coffee_table": 0.38,
    "side_table": 0.5,
    "rug": 0.012,
    "tv_unit": 0.45,
    "sideboard": 0.75,
    "dining_set": 0.85,
    "dining_table": 0.76,
    "chair": 0.85,
    "stool": 0.95,
    "kitchen_counter": 2.2,
    "kitchen_island": 0.92,
    "fridge": 2.1,
    "toilet": 1.0,
    "bidet": 0.42,
    "washbasin": 2.0,
    "shower": 2.0,
    "bathtub": 0.55,
    "washing_machine": 0.85,
    "plant": 1.4,
    "floor_lamp": 1.6,
}
# Kinds whose back must stand against a wall, and which side of the box is the back.
WALL_BACKED = {
    "bed_double": "short",
    "bed_single": "short",
    "nightstand": "any",
    "wardrobe": "long",
    "dresser": "long",
    "desk": "long",
    "shelving": "long",
    "sofa": "long",
    "tv_unit": "long",
    "sideboard": "long",
    "kitchen_counter": "long",
    "fridge": "any",
    "toilet": "short",
    "bidet": "short",
    "washbasin": "long",
    "bathtub": "long",
    "washing_machine": "any",
}
FACES_TABLE = {"chair", "stool"}
TABLES = {"dining_table", "dining_set", "kitchen_island", "kitchen_counter", "desk"}
SIDES: dict[str, tuple[float, float]] = {
    "up": (0, -1),
    "down": (0, 1),
    "left": (-1, 0),
    "right": (1, 0),
}


class FurnitureLabel(BaseModel):
    candidate: str
    kind: FurnitureKind
    name: str = Field(description="Short Spanish name, e.g. 'Cama doble 150'")
    front: Side = Field(description="Image direction the usable front faces")


class ExtraFurniture(BaseModel):
    kind: FurnitureKind
    name: str
    x0: float
    y0: float
    x1: float
    y1: float
    front: Side


class FurnitureSelection(BaseModel):
    labels: list[FurnitureLabel]
    extras: list[ExtraFurniture]
    notes: list[str]


def _lines(drawing):
    out = []
    for item in drawing["items"]:
        if item[0] == "l":
            out.append(LineString([item[1], item[2]]))
        elif item[0] == "c":
            out.append(LineString([item[1], item[2], item[3], item[4]]))
        elif item[0] == "re":
            a, b, c, e = item[1]
            out.append(LineString([(a, b), (c, b), (c, e), (a, e), (a, b)]))
        elif item[0] == "qu":
            q = item[1]
            out.append(LineString([q[0], q[1], q[3], q[2], q[0]]))
    return [ln for ln in out if ln.length > 0]


def _grey(colour, value, tol=0.012):
    return bool(colour) and all(abs(c - value) < tol for c in colour)


def stroke_styles(page):
    """Group stroked (unfilled) drawings by colour/width; returns {(grey, width): [lines]}."""
    groups = {}
    for d in page["drawings"]:
        colour = d.get("color")
        if d.get("fill") or not colour or max(colour) - min(colour) > 0.03:
            continue
        key = (round(colour[0], 2), round(d.get("width") or 0, 2))
        groups.setdefault(key, []).extend(_lines(d))
    return groups


def furniture_strokes(page):
    """The most frequent mid-grey fine stroke is the furniture/fixture layer in CAD exports."""
    groups = {k: v for k, v in stroke_styles(page).items() if 0.15 < k[0] < 0.4 and 0.2 <= k[1]}
    if not groups:
        return []
    curved = {
        k: sum(1 for ln in v if len(ln.coords) > 2) for k, v in groups.items()
    }  # fixtures (toilets, basins, hobs) contain curves; dimension/hatch layers do not
    key = max(groups, key=lambda k: (curved[k], len(groups[k])))
    return groups[key]


def oriented_box(shape):
    env = shape.envelope
    rect = shape.minimum_rotated_rectangle
    coords = list(rect.exterior.coords)
    edge = max(
        (LineString(coords[i : i + 2]) for i in range(4)),
        key=lambda e: e.length,
    )
    (x0, y0), (x1, y1) = edge.coords
    angle = abs(math.degrees(math.atan2(y1 - y0, x1 - x0))) % 90
    # CAD furniture is nearly always orthogonal; snap unless clearly rotated.
    return env if min(angle, 90 - angle) < 8 or env.area <= 1.25 * shape.area else rect


def furniture_candidates(page, walls, factor):
    """Return {id: Polygon} of furniture footprints in PDF points, read from the drawing."""
    if walls.is_empty:
        return {}
    outline = walls.buffer(1.5 / factor, join_style=2).buffer(-1.5 / factor, join_style=2)
    parts = [outline] if outline.geom_type == "Polygon" else list(outline.geoms)
    interior = unary_union([Polygon(p.exterior) for p in parts])
    core = interior.buffer(-0.25 / factor)
    shapes = []
    for d in page["drawings"]:
        fill = d.get("fill")
        if not fill or min(fill) < 0.97:
            continue
        faces = list(polygonize(unary_union(_lines(d))))
        if faces:
            shape = unary_union(faces).buffer(0)
            if shape.area * factor**2 > 0.005:
                shapes.append(shape)

    def mergeable(a, b):
        overlap = a.intersection(b).area
        small, large = sorted((a, b), key=lambda p: p.area)
        if overlap > 0.85 * small.area:
            # Sub-parts merge into small containers (pillows in a bed), never into rugs.
            return large.area * factor**2 < 4
        return overlap > 0.3 * small.area

    clusters = []
    for shape in sorted(shapes, key=lambda p: -p.area):
        for i, cluster in enumerate(clusters):
            if mergeable(cluster, shape):
                clusters[i] = unary_union([cluster, shape])
                break
        else:
            clusters.append(shape)
    # Furniture drawn only with strokes (kitchen runs, tables inside rugs).
    small = unary_union([c for c in clusters if c.area * factor**2 < 4] or [Polygon()])
    faces = [
        f
        for f in polygonize(unary_union(furniture_strokes(page) or [LineString()]))
        if f.area * factor**2 > 0.08
    ]
    for face in sorted(faces, key=lambda f: -f.area):
        if face.intersection(small).area < 0.3 * face.area and interior.covers(face):
            clusters.append(face)
            small = unary_union([small, face])
    result = []
    for cluster in clusters:
        rect = oriented_box(cluster)
        coords = list(rect.exterior.coords)
        width = min(math.dist(coords[i], coords[i + 1]) for i in range(4)) * factor
        if width < 0.2 or not interior.buffer(0.2 / factor).covers(rect):
            continue
        if rect.intersection(walls).area > 0.5 * rect.area:
            continue
        if rect.intersection(core).area < 0.5 * rect.area:
            continue  # window joinery and sills inside the facade band
        if any(rect.intersection(r).area > 0.9 * min(rect.area, r.area) for r in result):
            continue
        result.append(rect)
    result.sort(key=lambda r: (round(r.bounds[1] / 20), r.bounds[0]))
    return {f"F{i}": r for i, r in enumerate(result)}


def _angle_bucket(line):
    (x0, y0), (x1, y1) = line.coords[0], line.coords[-1]
    return round(math.degrees(math.atan2(y1 - y0, x1 - x0)) / 15) % 12


def _dashed(styles):
    """Dashed-arc layers (door swings): mostly short segments pointing in many directions."""
    out = []
    for lines in styles.values():
        short = [ln for ln in lines if ln.length < 4]
        arcs = len({_angle_bucket(ln) for ln in short}) >= 8
        if len(lines) > 10 and len(short) > 0.6 * len(lines) and arcs:
            out.extend(short)
    return out


def opening_evidence(page, gaps, walls, factor):
    """Facts per gap that distinguish doors from windows: swing arcs, joinery, facade."""
    styles = stroke_styles(page)
    dashed = _dashed(styles)
    curves = [ln for ln in furniture_strokes(page) if len(ln.coords) > 2]
    outline = walls.buffer(1.5 / factor, join_style=2).buffer(-1.5 / factor, join_style=2)
    parts = [outline] if outline.geom_type == "Polygon" else list(outline.geoms)
    exterior = unary_union([Polygon(p.exterior) for p in parts]).boundary
    joinery = [
        ln
        for (grey, width), lines in styles.items()
        if 0.15 < grey < 0.4 and width < 0.3
        for ln in lines
    ]
    evidence = {}
    for ident, gap in gaps.items():
        shape = gap["shape"]
        x0, y0, x1, y1 = shape.bounds
        width = max(x1 - x0, y1 - y0)
        near = shape.buffer(width * 1.05)
        angles = {_angle_bucket(ln) for ln in dashed if ln.intersects(near)}
        evidence[ident] = {
            "width_m": round(width * factor, 2),
            "door_swing_arc": len(angles) >= 4,
            "joinery_lines_inside": sum(1 for ln in joinery if ln.within(shape.buffer(0.5))),
            "on_facade": shape.buffer(0.15 / factor).intersects(exterior),
            "curved_strokes_nearby": sum(1 for c in curves if c.intersects(near)),
        }
    return evidence


def floor_finishes(page, rooms, factor):
    """Tiles are a two-way grid of fine dark lines; wood boards are light parallel hatching."""
    styles = stroke_styles(page)
    finishes = {}
    for ident, room in rooms.items():
        inner = room.buffer(-0.05 / factor)
        grid = {"h": 0, "v": 0}
        boards = 0.0
        for (grey, width), lines in styles.items():
            for ln in lines:
                piece = ln.intersection(inner)
                if piece.length * factor < 0.15:
                    continue
                (x0, y0), (x1, y1) = ln.coords[0], ln.coords[-1]
                axis = "h" if abs(y1 - y0) < 0.5 else "v" if abs(x1 - x0) < 0.5 else None
                if grey < 0.4 and width < 0.2 and axis:
                    grid[axis] += 1
                elif grey >= 0.6 and axis:
                    boards += piece.length * factor
        area = room.area * factor**2
        if min(grid.values()) >= 3:
            finishes[ident] = "tile"
        elif boards > 0.8 * area:
            finishes[ident] = "wood"
    return finishes


def _sides(rect):
    """Four (name, segment) sides of an axis-aligned/rotated rectangle by outward direction."""
    coords = list(rect.exterior.coords)[:4]
    cx, cy = rect.centroid.coords[0]
    out = {}
    for i in range(4):
        a, b = coords[i], coords[(i + 1) % 4]
        mx, my = (a[0] + b[0]) / 2 - cx, (a[1] + b[1]) / 2 - cy
        name = max(SIDES, key=lambda s: mx * SIDES[s][0] + my * SIDES[s][1])
        out[name] = LineString([a, b])
    return out


OPPOSITE = {"up": "down", "down": "up", "left": "right", "right": "left"}


def side_clearance(segment, walls, factor):
    """Distance (m) from the middle 60% of a side to the walls; corners do not count."""
    middle = LineString(
        [segment.interpolate(0.2, normalized=True), segment.interpolate(0.8, normalized=True)]
    )
    return middle.distance(walls) * factor


def wall_contacts(rect, walls, factor, tolerance=0.12):
    return [s for s, seg in _sides(rect).items() if side_clearance(seg, walls, factor) <= tolerance]


def resolve_front(kind, rect, front, walls, tables, factor):
    """Check the AI's front against the walls/tables; return (front, note or None)."""
    sides = _sides(rect)
    if kind in FACES_TABLE and tables:
        centre = rect.centroid
        target = min(tables, key=lambda t: t.distance(centre))
        if target.distance(centre) * factor < 1.2:
            tx, ty = target.centroid.x - centre.x, target.centroid.y - centre.y
            best = max(SIDES, key=lambda s: tx * SIDES[s][0] + ty * SIDES[s][1])
            return best, None if best == front else f"silla girada hacia la mesa ({best})"
        return front, None
    rule = WALL_BACKED.get(kind)
    if not rule:
        return front, None
    clearance = {s: side_clearance(seg, walls, factor) for s, seg in sides.items()}
    lengths = {s: seg.length for s, seg in sides.items()}
    back = OPPOSITE[front]
    if clearance[back] <= 0.12:
        return front, None
    touching = [s for s in sides if clearance[s] <= 0.12]
    if rule != "any":
        shortest = min(lengths.values())
        wanted = [
            s
            for s in touching
            if (abs(lengths[s] - shortest) < 1e-6) == (rule == "short")
            or abs(max(lengths.values()) - shortest) < 1e-6
        ]
        touching = wanted or touching
    if not touching:
        return front, None
    # Prefer a wall side on the same axis the AI chose, then the longest contact.
    touching.sort(key=lambda s: (s not in (back, front), -lengths[s]))
    new_back = touching[0]
    return OPPOSITE[
        new_back
    ], f"respaldo apoyado en el muro ({new_back}), frente hacia {OPPOSITE[new_back]}"


def ordered_polygon(rect, front):
    """Corners as [back-left, back-right, front-right, front-left] in PDF points."""
    sides = _sides(rect)
    fx, fy = SIDES[front]
    back = sides[OPPOSITE[front]]
    front_seg = sides[front]
    (ax, ay), (bx, by) = back.coords
    # Order the back edge so that (back[1]-back[0]) x front-direction keeps a fixed handedness.
    if (bx - ax) * fy - (by - ay) * fx < 0:
        (ax, ay), (bx, by) = (bx, by), (ax, ay)
    (cx, cy), (dx, dy) = front_seg.coords
    if math.dist((bx, by), (cx, cy)) > math.dist((bx, by), (dx, dy)):
        (cx, cy), (dx, dy) = (dx, dy), (cx, cy)
    return [[ax, ay], [bx, by], [cx, cy], [dx, dy]]


def extra_box(extra):
    x0, x1 = sorted((extra.x0, extra.x1))
    y0, y1 = sorted((extra.y0, extra.y1))
    return box(x0, y0, x1, y1)


def room_of(point, rooms):
    p = Point(point)
    return next((name for name, poly in rooms if poly.contains(p)), None)

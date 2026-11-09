"""Prompt for the illustrative AI enhancement of one Blender render.

Sections, in order: the studio's master style (docs/PROMPT_STYLE.md, verbatim), the location,
a brief of this view built from the approved geometry, the client's materials, the precedence
rule and, always last, the hard constraints. Precedence: approved geometry > client materials >
master style. The location steers light, vegetation and the view outside only.
"""

import hashlib
import math
import re
import unicodedata
from collections import Counter

from shapely.geometry import Polygon

from pipelines.common import ROOT
from pipelines.postprocess.location import describe

PROMPT_VERSION = "enhance-v1"
STYLE_PATH = ROOT / "docs/PROMPT_STYLE.md"

KINDS = {
    "bed_double": ("double bed", "double beds"),
    "bed_single": ("single bed", "single beds"),
    "nightstand": ("nightstand", "nightstands"),
    "wardrobe": ("wardrobe", "wardrobes"),
    "dresser": ("chest of drawers", "chests of drawers"),
    "desk": ("desk", "desks"),
    "shelving": ("shelving unit", "shelving units"),
    "sofa": ("sofa", "sofas"),
    "armchair": ("armchair", "armchairs"),
    "coffee_table": ("coffee table", "coffee tables"),
    "side_table": ("side table", "side tables"),
    "rug": ("rug", "rugs"),
    "tv_unit": ("TV unit", "TV units"),
    "sideboard": ("sideboard", "sideboards"),
    "dining_set": ("dining table with its chairs", "dining tables with their chairs"),
    "dining_table": ("dining table", "dining tables"),
    "chair": ("chair", "chairs"),
    "stool": ("stool", "stools"),
    "kitchen_counter": (
        "kitchen run (base units, worktop, hob and sink, wall units where shown)",
        "kitchen runs",
    ),
    "kitchen_island": ("kitchen island", "kitchen islands"),
    "fridge": ("fridge", "fridges"),
    "toilet": ("wall-hung toilet", "toilets"),
    "bidet": ("bidet", "bidets"),
    "washbasin": ("vanity with basin and mirror", "vanities with basin"),
    "shower": ("walk-in shower with glass screen", "showers"),
    "bathtub": ("bathtub", "bathtubs"),
    "washing_machine": ("washing machine", "washing machines"),
    "plant": ("plant", "plants"),
    "floor_lamp": ("floor lamp", "floor lamps"),
}
ROOM_TYPES = [
    (r"sal[oó]n|estar|living", "living room"),
    (r"comedor|dining", "dining area"),
    (r"cocina|kitchen", "kitchen"),
    (r"dormitorio|habitaci[oó]n|alcoba|bedroom", "bedroom"),
    (r"ba[nñ]o|aseo|bath", "bathroom"),
    (r"estudio|despacho|study", "study"),
    (r"vestidor", "dressing room"),
    (r"distribuidor|pasillo|recibidor|hall", "hallway"),
    (r"galer[ií]a|lavadero", "utility gallery"),
    (r"terraza|balc[oó]n", "terrace"),
]
FLOORS = {"wood": "wood", "tile": "tile", "stone": "stone"}
CLIMATE = {
    "continental": "a dry continental Mediterranean climate: clear, crisp air and strong "
    "contrast; vegetation such as plane trees, holm oaks, olive trees, cypresses, lavender "
    "and rosemary",
    "mediterranean_coast": "a coastal Mediterranean climate: soft, slightly hazy luminous air; "
    "vegetation such as olive and citrus trees, stone pines, palms, bougainvillea and agaves",
    "south": "a hot southern Spanish climate: intense golden light; vegetation such as orange "
    "and olive trees, palms, jacarandas and jasmine",
    "atlantic": "a humid Atlantic climate: softer, more diffuse light with mild clouds; "
    "vegetation such as oaks, chestnuts, camellias, hydrangeas and green lawns",
    "subtropical": "a subtropical island climate: bright, clear light; vegetation such as "
    "Canary palms, dragon trees, succulents and bougainvillea",
}
HARD_CONSTRAINTS = """HARD CONSTRAINTS (highest priority; they override everything above):
- Keep the exact camera position, lens, perspective, framing and crop of the input image. The
  result must stay pixel-aligned with the input: every edge where it is now.
- Keep the geometry exactly: every wall, floor, ceiling line, room proportion and every opening
  (windows, doors) at the same position and size. Do not open, close, widen or move anything.
- Keep the furniture exactly: same number of pieces, same positions, sizes, outlines and
  orientation. Restyle their surfaces only. Do not add, remove, move or resize any furniture,
  rug, lamp or floor plant.
- No new walls, windows, doors, columns, beams, niches, steps, mouldings or rooms. Do not add a
  roof or ceiling where the image has none.
- No people, animals, text, lettering, signage, logos, watermarks or frames."""
STRICT = """STRICT RETRY: a previous attempt drifted from the input geometry. This time change
ONLY materials, textures, lighting and what is seen outside the windows. Trace every line of
the input image: each edge, corner and silhouette must stay at the same pixel position. When in
doubt, leave that part exactly as it is."""


def master_style():
    """(verbatim text, sha256) of the studio's style prompt, read at runtime."""
    data = STYLE_PATH.read_bytes()
    return data.decode("utf-8"), hashlib.sha256(data).hexdigest()


def _fold(text):
    return "".join(
        c for c in unicodedata.normalize("NFD", text.lower()) if unicodedata.category(c) != "Mn"
    )


def view_type(view):
    ident = view["id"]
    if ident == "exterior":
        return "exterior"
    if ident == "axonometric":
        return "axonometric"
    return "interior" if ident.startswith("interior") else "other"


def room_for(view, geometry):
    rooms = geometry.get("rooms", [])
    if view.get("room_id"):
        hit = next((r for r in rooms if r["id"] == view["room_id"]), None)
        if hit:
            return hit
    name = view.get("label", "").split("·", 1)[-1].strip()
    return next((r for r in rooms if r["name"].strip() == name), None)


def room_type(name):
    folded = _fold(name or "")
    types = [label for pattern, label in ROOM_TYPES if re.search(pattern, folded)]
    if len(types) > 1:
        return "open-plan " + ", ".join(types[:-1]) + " and " + types[-1]
    return types[0] if types else "room"


def furniture_kind(item):
    return item["name"].split(" / ")[0].strip()


def room_furniture(room, geometry):
    """Furniture of the approved geometry whose footprint centre lies in this room."""
    shape = Polygon(room["polygon"])
    found = []
    for item in geometry.get("furniture", []):
        if item.get("floor_id") != room.get("floor_id"):
            continue
        if shape.buffer(0.05).contains(Polygon(item["polygon"]).centroid):
            found.append(item)
    return found


def furniture_list(items):
    counts = Counter(furniture_kind(i) for i in items)
    parts = []
    for kind, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])):
        one, many = KINDS.get(kind, (kind.replace("_", " "), kind.replace("_", " ") + "s"))
        parts.append(f"{n} {one if n == 1 else many}")
    return parts


def _in_view(point, camera):
    if not camera or not camera.get("position") or not camera.get("forward"):
        return True
    px, py = camera["position"][:2]
    fx, fy = camera["forward"][:2]
    dx, dy = point[0] - px, point[1] - py
    norm = math.hypot(fx, fy) * math.hypot(dx, dy)
    if norm == 0:
        return True
    lens, sensor = camera.get("lens") or 17, camera.get("sensor") or 36
    half = math.atan(sensor / 2 / lens) + math.radians(6)
    return math.acos(max(-1, min(1, (fx * dx + fy * dy) / norm))) <= half


def room_openings(room, geometry, camera=None):
    """Openings in the walls of this room, optionally restricted to the camera's field of view."""
    shape = Polygon(room["polygon"])
    found = []
    for op in geometry.get("openings", []):
        if op.get("floor_id") != room.get("floor_id"):
            continue
        poly = Polygon(op["polygon"])
        if poly.distance(shape) <= 0.3 and _in_view(poly.centroid.coords[0], camera):
            found.append(op)
    return found


def openings_list(items):
    counts = Counter((o["kind"], o.get("style") or "") for o in items)
    parts = []
    for (kind, style), n in sorted(counts.items()):
        noun = kind + ("s" if n > 1 else "")
        parts.append(f"{n} {noun}" + (f" ({style})" if style else ""))
    return parts


def finish_name(geometry, slot):
    value = (geometry.get("finishes") or {}).get(slot)
    return value.get("name") if isinstance(value, dict) else None


def interior_brief(view, geometry):
    room = room_for(view, geometry)
    if room is None:
        return (
            "VIEW: interior photograph. Keep exactly the furniture, openings and surfaces that "
            "are visible in the input image; add nothing."
        )
    kind = room_type(room["name"])
    pieces = furniture_list(room_furniture(room, geometry))
    camera = view.get("camera")
    openings = openings_list(room_openings(room, geometry, camera))
    floor = room.get("floor_finish")
    floor_text = FLOORS.get(floor, "the same floor as the input image")
    named = finish_name(geometry, "tile" if floor in ("tile", "stone") else "floor")
    lines = [
        f"VIEW: interior photograph of the {kind} «{room['name']}» of this dwelling.",
        "Furniture actually present in this room (from the approved plan; the image may show "
        "only part of it): "
        + ("; ".join(pieces) + "." if pieces else "none. Keep the room free of furniture."),
        (
            "No other furniture exists in this room: do not add sofas, chairs, tables, beds, "
            "cabinets, rugs, floor lamps or floor plants that are not in the input image."
        ),
        f"Floor finish: {floor_text}" + (f" ({named})." if named else "."),
        "Openings in this room"
        + (" within the camera's field of view" if camera else "")
        + ": "
        + (", ".join(openings) if openings else "none")
        + ". Keep those in the image exactly as drawn; do not add any.",
        (
            "Small accessories on existing surfaces (books, a vase, a ceramic bowl, cushions, a "
            "throw) and at most one framed artwork on a blank wall are allowed."
        ),
    ]
    return "\n".join(lines)


def exterior_brief(geometry):
    roofless = not geometry.get("roofs")
    return "\n".join(
        [
            (
                "VIEW: exterior view of the building model. The master style above is written for "
                "interiors; apply its materials, colour palette, light and photographic quality to "
                "the facades instead."
            ),
            "Keep the massing, wall heights, every opening, the roofline and the silhouette "
            "exactly as in the image."
            + (
                " The model is shown as an open cut-away without a roof: keep it open, do not "
                "add a roof, upper floors or neighbouring buildings attached to it."
                if roofless
                else ""
            ),
            (
                "The plain studio ground may become a believable ground-level context for the "
                "location (paving, low garden planting), kept low and in the background, never "
                "touching, covering or extending the walls."
            ),
        ]
    )


AXONOMETRIC_BRIEF = """VIEW: axonometric cut-away of the dwelling. Light enhancement only:
improve material realism (wood, plaster, stone, textiles) and soft late-afternoon lighting. Keep
the cut-away clean: the cut tops of the walls stay flat, clean and uniform, the background stays
a plain neutral studio backdrop, and nothing is added inside or around the model."""


def view_brief(view, geometry):
    kind = view_type(view)
    if kind == "interior":
        return interior_brief(view, geometry)
    if kind == "exterior":
        return exterior_brief(geometry)
    if kind == "axonometric":
        return AXONOMETRIC_BRIEF
    return "VIEW: keep everything visible in the input image exactly in place."


def location_block(location):
    place, fallback = describe(location)
    loc = location or {}
    lines = [
        (
            "LOCATION (use it only for climate, light, vegetation and what is seen outside; never "
            "change the building because of it):"
        ),
        f"The residence is located in {place}"
        + (" (generic: the exact location is unknown)." if fallback else "."),
    ]
    lat = loc.get("latitude")
    if lat is not None and not fallback:
        lines.append(
            f"Light: late afternoon at about {abs(lat):.0f}° {'N' if lat >= 0 else 'S'}: a low "
            "sun (roughly 15–25° above the horizon) from the west, warm and raking, with long "
            "soft shadows, consistent with this latitude."
        )
    else:
        lines.append(
            "Light: late-afternoon sun appropriate to a Spanish latitude: low, warm and raking, "
            "with long soft shadows."
        )
    climate = CLIMATE.get(loc.get("climate") or "")
    if climate and not fallback:
        lines.append(f"Climate and vegetation: {climate}.")
    else:
        lines.append(
            "Climate and vegetation: Mediterranean, with olive trees, cypresses and lavender."
        )
    city = loc.get("city") if not fallback else None
    if loc.get("setting") == "urban" and city:
        lines.append(
            f"Outside the windows: the urban context of {city}: facing residential buildings "
            "of a typical street of the city, street trees and sky, seen from the dwelling's "
            "floor level; no landmarks, no legible signs."
        )
    elif loc.get("setting") == "rural":
        lines.append(
            "Outside the windows: a garden and open landscape typical of the region; no "
            "buildings close to the windows."
        )
    else:
        lines.append(
            "Outside the windows: a calm, believable residential context and sky; no landmarks "
            "and no legible signs."
        )
    return "\n".join(lines)


def materials_block(description, geometry):
    description = (description or "").strip()
    if not description:
        return None
    applied = [
        f"{slot}: {name}"
        for slot in ("floor", "walls", "tile", "stone", "furniture_wood", "upholstery", "metal")
        if (name := finish_name(geometry, slot))
    ]
    return "\n".join(
        [
            "CLIENT MATERIALS (they replace the master style's palette for these surfaces):",
            f"«{description}»",
            "As applied in the 3D model: " + "; ".join(applied) + "." if applied else "",
        ]
    ).strip()


PRECEDENCE = """PRECEDENCE: (1) the geometry, layout and furniture of the input image and the
view brief, (2) the client's materials, (3) the master style. Where the master style suggests
furniture, rugs, plants, lamps or decoration that is not in the input image (for example olive
trees, large rugs or table lamps), ignore that suggestion."""


def compose(view, geometry, location=None, description="", strict=False, style=None):
    """Prompt for one view: {prompt, sections, version, style_sha256, location_fallback}."""
    text, digest = style or master_style()
    sections = [
        ("master_style", text),
        ("location", location_block(location)),
        ("view", view_brief(view, geometry)),
    ]
    materials = materials_block(description, geometry)
    if materials:
        sections.append(("client_materials", materials))
    sections.append(("precedence", PRECEDENCE))
    if strict:
        sections.append(("strict", STRICT))
    sections.append(("hard_constraints", HARD_CONSTRAINTS))
    return {
        "prompt": "\n\n".join(body for _, body in sections),
        "sections": [name for name, _ in sections],
        "version": PROMPT_VERSION,
        "style_sha256": digest,
        "location_fallback": describe(location)[1],
    }

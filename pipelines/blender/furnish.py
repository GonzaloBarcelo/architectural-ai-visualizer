"""Detailed, oriented, explicitly illustrative furniture (no external assets, no bpy import).

Each furniture footprint arrives as [back-left, back-right, front-right, front-left] in metres,
so every piece is modelled in a local frame: u along the back edge (0..W), v from the back
(0) to the front (D), z up from the floor. Footprints come from the PDF; the models are
presentation only and carry inferred provenance.
"""

import math


def _frame(polygon):
    (bx0, by0), (bx1, by1), _, (fx0, fy0) = polygon[:4]
    width = math.hypot(bx1 - bx0, by1 - by0)
    depth = math.hypot(fx0 - bx0, fy0 - by0)
    u = ((bx1 - bx0) / width, (by1 - by0) / width)
    v = ((fx0 - bx0) / depth, (fy0 - by0) / depth)
    return (bx0, by0), u, v, width, depth


def furnish(data, floors, prism, palette):
    """Build every furniture item. `palette(key)` returns a shared material."""
    for item in data.get("furniture", []):
        kind = item["name"].split(" / ")[0]
        z = next(f["elevation"] for f in data["floors"] if f["id"] == item["floor_id"])
        origin, u, v, W, D = _frame(item["polygon"])
        collection = floors[item["floor_id"]]
        count = [0]

        def world(a, b, origin=origin, u=u, v=v):
            return (origin[0] + u[0] * a + v[0] * b, origin[1] + u[1] * a + v[1] * b)

        def tag(obj, item=item):
            obj["presentation_id"] = item["id"]
            obj["floor_id"] = item["floor_id"]
            obj["kind"] = "furniture"
            obj["verification_status"] = "inferred"
            obj["source_sha256"] = data["source"]["sha256"]
            return obj

        def box(
            name, a0, b0, a1, b1, z0, h, mat, item=item, z=z, collection=collection, count=count
        ):
            if a1 - a0 <= 1e-4 or b1 - b0 <= 1e-4 or h <= 1e-4:
                return None
            count[0] += 1
            poly = [world(a0, b0), world(a1, b0), world(a1, b1), world(a0, b1)]
            return tag(prism(f"{item['id']} / {name}", poly, z + z0, h, collection, palette(mat)))

        def disc(
            name,
            ca,
            cb,
            ra,
            rb,
            z0,
            h,
            mat,
            n=28,
            item=item,
            z=z,
            collection=collection,
            count=count,
        ):
            if ra <= 1e-4 or rb <= 1e-4 or h <= 1e-4:
                return None
            count[0] += 1
            poly = [
                world(
                    ca + ra * math.cos(2 * math.pi * k / n), cb + rb * math.sin(2 * math.pi * k / n)
                )
                for k in range(n)
            ]
            return tag(prism(f"{item['id']} / {name}", poly, z + z0, h, collection, palette(mat)))

        build = MODELS.get(kind, _generic)
        build(box, disc, W, D)
        if count[0] == 0:
            _generic(box, disc, W, D)


# ---------------------------------------------------------------- bedroom


def _bed(box, disc, W, D, single=False):
    hb = 0.08
    box("plinth", 0.08, hb + 0.06, W - 0.08, D - 0.08, 0, 0.12, "black")
    box("base", 0, hb, W, D, 0.12, 0.26, "upholstery")
    box("mattress", 0.03, hb + 0.02, W - 0.03, D - 0.03, 0.38, 0.18, "bedding")
    box("duvet", -0.01, hb + 0.55, W + 0.01, D + 0.01, 0.5, 0.1, "bedding")
    box("throw", -0.015, D - 0.55, W + 0.015, D - 0.2, 0.6, 0.02, "accent")
    pillows = (
        [(0.1, W - 0.1)] if single or W < 1.2 else [(0.08, W / 2 - 0.04), (W / 2 + 0.04, W - 0.08)]
    )
    for i, (a0, a1) in enumerate(pillows):
        box(f"pillow {i}", a0, hb + 0.06, a1, hb + 0.42, 0.56, 0.14, "bedding")
        box(f"cushion {i}", a0 + 0.1, hb + 0.36, a1 - 0.1, hb + 0.5, 0.56, 0.18, "accent")
    box("headboard", -0.04, 0, W + 0.04, hb, 0.12, 1.05, "upholstery")


def bed_double(box, disc, W, D):
    _bed(box, disc, W, D)


def bed_single(box, disc, W, D):
    _bed(box, disc, W, D, single=True)


def nightstand(box, disc, W, D):
    box("body", 0.01, 0.0, W - 0.01, D, 0.16, 0.34, "furniture_wood")
    box("drawer line", 0.03, D - 0.002, W - 0.03, D + 0.002, 0.33, 0.006, "black")
    box("top", 0, 0, W, D, 0.5, 0.025, "stone")
    box("plinth", 0.08, 0.06, W - 0.08, D - 0.06, 0, 0.16, "metal")
    _lamp(disc, W / 2, D * 0.45, 0.525, 0.12)


def _lamp(disc, a, b, z0, r):
    disc("lamp base", a, b, r * 0.5, r * 0.5, z0, 0.03, "metal")
    disc("lamp stem", a, b, 0.012, 0.012, z0 + 0.03, 0.3, "metal")
    disc("lamp shade", a, b, r, r, z0 + 0.3, 0.2, "lampshade")


def wardrobe(box, disc, W, D):
    box("plinth", 0.02, 0, W - 0.02, D - 0.05, 0, 0.08, "black")
    box("body", 0, 0, W, D, 0.08, 2.32, "doors")
    leaves = max(1, round(W / 0.5))
    for i in range(1, leaves):
        a = W * i / leaves
        box(f"reveal {i}", a - 0.003, D - 0.004, a + 0.003, D + 0.001, 0.1, 2.28, "black")
    for i in range(leaves):
        a = W * (i + 0.5) / leaves + (0.18 if i % 2 == 0 else -0.18) * W / leaves
        box(f"pull {i}", a - 0.008, D, a + 0.008, D + 0.025, 0.85, 0.45, "metal")


def dresser(box, disc, W, D):
    box("plinth", 0.05, 0.05, W - 0.05, D - 0.05, 0, 0.1, "black")
    box("body", 0, 0, W, D, 0.1, 0.62, "furniture_wood")
    for i in range(1, 3):
        box(f"drawer {i}", 0.02, D - 0.002, W - 0.02, D + 0.002, 0.1 + 0.62 * i / 3, 0.006, "black")
    box("top", 0, 0, W, D, 0.72, 0.03, "stone")
    disc("vase", W * 0.25, D / 2, 0.06, 0.06, 0.75, 0.3, "ceramic")


def desk(box, disc, W, D):
    box("top", 0, 0, W, D, 0.71, 0.04, "furniture_wood")
    box("left panel", 0, 0.02, 0.04, D - 0.02, 0, 0.71, "furniture_wood")
    box("right panel", W - 0.04, 0.02, W, D - 0.02, 0, 0.71, "furniture_wood")
    _lamp(disc, W * 0.85, D * 0.35, 0.75, 0.1)


def shelving(box, disc, W, D):
    for a0, a1 in [(0, 0.03), (W - 0.03, W)]:
        box("side", a0, 0, a1, D, 0, 2.0, "furniture_wood")
    for k in range(6):
        box(f"shelf {k}", 0.03, 0, W - 0.03, D, k * 0.39, 0.025, "furniture_wood")
    for k in range(1, 5):
        box(
            f"books {k}",
            0.1 + (k % 2) * W * 0.3,
            0.02,
            0.1 + (k % 2) * W * 0.3 + W * 0.25,
            D - 0.05,
            k * 0.39 + 0.025,
            0.24,
            "accent" if k % 2 else "bedding",
        )


# ---------------------------------------------------------------- living


def sofa(box, disc, W, D, arms=True):
    arm = 0.16 if arms else 0
    back = min(0.24, D * 0.28)
    box("plinth", 0.06, 0.05, W - 0.06, D - 0.05, 0, 0.08, "black")
    box("base", 0, 0, W, D, 0.08, 0.32, "upholstery")
    box("back", 0, 0, W, back, 0.4, 0.4, "upholstery")
    if arms:
        box("arm left", 0, 0, arm, D, 0.4, 0.22, "upholstery")
        box("arm right", W - arm, 0, W, D, 0.4, 0.22, "upholstery")
    seats = max(1, round((W - 2 * arm) / 0.85))
    span = (W - 2 * arm) / seats
    for i in range(seats):
        a0 = arm + i * span
        box(
            f"seat cushion {i}",
            a0 + 0.01,
            back,
            a0 + span - 0.01,
            D - 0.02,
            0.4,
            0.12,
            "upholstery",
        )
        box(
            f"back cushion {i}",
            a0 + 0.02,
            back,
            a0 + span - 0.02,
            back + 0.16,
            0.52,
            0.36,
            "upholstery",
        )
    if W > 1.3:
        box(
            "throw pillow left",
            arm + 0.08,
            back + 0.12,
            arm + 0.5,
            back + 0.26,
            0.52,
            0.34,
            "accent",
        )
        box(
            "throw pillow right",
            W - arm - 0.5,
            back + 0.12,
            W - arm - 0.08,
            back + 0.26,
            0.52,
            0.34,
            "bedding",
        )


def armchair(box, disc, W, D):
    sofa(box, disc, W, D)


def coffee_table(box, disc, W, D):
    box("base", W * 0.2, D * 0.2, W * 0.8, D * 0.8, 0, 0.32, "furniture_wood")
    box("top", 0, 0, W, D, 0.32, 0.05, "stone")
    box("book 1", W * 0.15, D * 0.25, W * 0.15 + 0.28, D * 0.25 + 0.22, 0.37, 0.03, "black")
    box(
        "book 2",
        W * 0.15 + 0.02,
        D * 0.25 + 0.01,
        W * 0.15 + 0.26,
        D * 0.25 + 0.2,
        0.4,
        0.025,
        "bedding",
    )
    disc("bowl", W * 0.7, D * 0.5, 0.11, 0.11, 0.37, 0.06, "metal")


def side_table(box, disc, W, D):
    r = min(W, D) / 2
    disc("base", W / 2, D / 2, r * 0.6, r * 0.6, 0, 0.03, "metal")
    disc("stem", W / 2, D / 2, 0.025, 0.025, 0.03, 0.45, "metal")
    disc("top", W / 2, D / 2, r, r, 0.48, 0.03, "stone")


def rug(box, disc, W, D):
    box("rug", 0, 0, W, D, 0, 0.012, "rug")


def tv_unit(box, disc, W, D):
    box("console", 0, 0, W, D, 0.22, 0.36, "furniture_wood")
    for i in range(1, 3):
        a = W * i / 3
        box(f"reveal {i}", a - 0.003, D - 0.002, a + 0.003, D + 0.002, 0.24, 0.32, "black")
    screen = min(W * 0.8, 1.65)
    box("tv", W / 2 - screen / 2, 0.0, W / 2 + screen / 2, 0.04, 0.95, screen * 0.5625, "screen")
    disc("vase", W * 0.15, D / 2, 0.07, 0.07, 0.58, 0.32, "ceramic")


def sideboard(box, disc, W, D):
    dresser(box, disc, W, D)


# ---------------------------------------------------------------- dining


def _table(box, disc, a0, b0, a1, b1, pendant=True):
    w, d = a1 - a0, b1 - b0
    box("table top", a0, b0, a1, b1, 0.72, 0.04, "stone")
    box("leg left", a0 + 0.12, b0 + d * 0.3, a0 + 0.2, b1 - d * 0.3, 0, 0.72, "furniture_wood")
    box("leg right", a1 - 0.2, b0 + d * 0.3, a1 - 0.12, b1 - d * 0.3, 0, 0.72, "furniture_wood")
    box(
        "stretcher",
        a0 + 0.2,
        (b0 + b1) / 2 - 0.03,
        a1 - 0.2,
        (b0 + b1) / 2 + 0.03,
        0.12,
        0.05,
        "furniture_wood",
    )
    disc("vase", (a0 + a1) / 2, (b0 + b1) / 2, 0.08, 0.08, 0.76, 0.22, "ceramic")
    if pendant:
        ca, cb = (a0 + a1) / 2, (b0 + b1) / 2
        disc("pendant cable", ca, cb, 0.006, 0.006, 1.85, 0.85, "black")
        disc("pendant", ca, cb, min(0.25, w * 0.2), min(0.25, d * 0.4), 1.65, 0.2, "lampshade")


def _chair(box, disc, a0, b0, a1, b1, facing):
    """A chair inside [a0,a1]x[b0,b1] whose front faces `facing` (+1: +v, -1: -v)."""
    for la, lb in [
        (a0 + 0.03, b0 + 0.03),
        (a1 - 0.05, b0 + 0.03),
        (a0 + 0.03, b1 - 0.05),
        (a1 - 0.05, b1 - 0.05),
    ]:
        box("chair leg", la, lb, la + 0.02, lb + 0.02, 0, 0.45, "black")
    box("chair seat", a0, b0, a1, b1, 0.45, 0.06, "upholstery")
    if facing > 0:
        box("chair back", a0, b0, a1, b0 + 0.05, 0.51, 0.36, "furniture_wood")
    else:
        box("chair back", a0, b1 - 0.05, a1, b1, 0.51, 0.36, "furniture_wood")


def dining_set(box, disc, W, D):
    """Table with chairs on both long (u) edges; chairs drawn tucked are pulled out a little."""
    chair = 0.46
    if D > 1.25:
        tb0, tb1 = chair * 0.7, D - chair * 0.7
    else:
        tb0, tb1 = min(0.12, D * 0.15), max(D - 0.12, D * 0.85)
    _table(box, disc, 0.04, tb0, W - 0.04, tb1)
    n = max(1, int((W - 0.2) / 0.6))
    for i in range(n):
        ca = 0.1 + (W - 0.2) * (i + 0.5) / n
        _chair(box, disc, ca - 0.22, tb0 - chair + 0.12, ca + 0.22, tb0 + 0.12, 1)
        _chair(box, disc, ca - 0.22, tb1 - 0.12, ca + 0.22, tb1 + chair - 0.12, -1)


def dining_table(box, disc, W, D):
    _table(box, disc, 0, 0, W, D)


def chair(box, disc, W, D):
    # Back at v=0; front (the sitter's knees) at v=D, towards the table.
    _chair(box, disc, 0.02, 0.02, W - 0.02, D - 0.02, 1)


def stool(box, disc, W, D):
    r = min(W, D) / 2 * 0.85
    disc("base", W / 2, D / 2, r * 0.8, r * 0.8, 0, 0.02, "metal")
    disc("stem", W / 2, D / 2, 0.025, 0.025, 0.02, 0.68, "metal")
    disc("ring", W / 2, D / 2, r * 0.7, r * 0.7, 0.3, 0.015, "metal")
    disc("seat", W / 2, D / 2, r, r, 0.7, 0.06, "upholstery")
    box("back", W / 2 - r * 0.8, 0, W / 2 + r * 0.8, 0.05, 0.76, 0.2, "furniture_wood")


# ---------------------------------------------------------------- kitchen


def kitchen_counter(box, disc, W, D):
    d = min(D, 0.65)
    box("toe kick", 0, 0, W, d - 0.07, 0, 0.1, "black")
    box("base units", 0, 0, W, d - 0.02, 0.1, 0.76, "doors")
    units = max(1, round(W / 0.6))
    for i in range(1, units):
        a = W * i / units
        box(f"reveal {i}", a - 0.002, d - 0.024, a + 0.002, d - 0.018, 0.12, 0.72, "black")
    box("handle rail", 0, d - 0.02, W, d - 0.005, 0.8, 0.015, "metal")
    box("worktop", -0.005, 0, W + 0.005, d + 0.02, 0.86, 0.03, "stone")
    box("splashback", 0, 0, W, 0.015, 0.89, 0.6, "stone")
    if W > 1.0:
        box("hob", W * 0.55, d * 0.15, W * 0.55 + 0.6, d * 0.15 + 0.5, 0.89, 0.006, "black")
    if W > 1.8:
        box("sink", W * 0.18, d * 0.2, W * 0.18 + 0.5, d * 0.2 + 0.4, 0.887, 0.006, "black")
        disc("tap", W * 0.18 + 0.25, d * 0.12, 0.018, 0.018, 0.89, 0.32, "metal")
    box("wall units", 0, 0, W, 0.35, 1.5, 0.75, "doors")
    box("under-cabinet light", 0.02, 0.05, W - 0.02, 0.3, 1.49, 0.01, "lampshade")


def kitchen_island(box, disc, W, D):
    box("toe kick", 0.08, 0.08, W - 0.08, D - 0.08, 0, 0.1, "black")
    box("body", 0.03, 0.03, W - 0.03, D - 0.03, 0.1, 0.78, "doors")
    box("worktop", 0, 0, W, D, 0.88, 0.04, "stone")
    box("waterfall left", 0, 0, 0.04, D, 0, 0.88, "stone")
    box("waterfall right", W - 0.04, 0, W, D, 0, 0.88, "stone")


def fridge(box, disc, W, D):
    box("column", 0, 0, W, D, 0, 2.1, "doors")
    box("reveal", 0.01, D - 0.002, W - 0.01, D + 0.002, 1.3, 0.006, "black")
    box("handle", W - 0.08, D, W - 0.06, D + 0.03, 0.9, 0.6, "metal")


def washing_machine(box, disc, W, D):
    box("body", 0, 0, W, D, 0, 0.85, "ceramic")
    disc("door", W / 2, D, 0.18, 0.012, 0.25, 0.36, "black")


# ---------------------------------------------------------------- bathroom


def toilet(box, disc, W, D):
    cistern = min(0.2, D * 0.3)
    box("concealed cistern", -0.02, 0, W + 0.02, cistern, 0, 1.12, "tile")
    box("flush plate", W / 2 - 0.12, cistern, W / 2 + 0.12, cistern + 0.01, 0.95, 0.16, "metal")
    rb = (D - cistern) / 2 * 0.95
    ra = min(W / 2 * 0.9, 0.19)
    disc("bowl", W / 2, cistern + rb, ra, rb, 0.24, 0.17, "ceramic")
    disc("seat", W / 2, cistern + rb, ra, rb, 0.41, 0.03, "ceramic")


def bidet(box, disc, W, D):
    toilet(box, disc, W, D)


def washbasin(box, disc, W, D):
    vanity = min(D, 0.5)
    box("vanity", 0, 0, W, vanity, 0.45, 0.36, "furniture_wood")
    box("drawer line", 0.03, vanity - 0.002, W - 0.03, vanity + 0.002, 0.65, 0.005, "black")
    box("top", 0, 0, W, vanity, 0.81, 0.03, "stone")
    disc(
        "vessel basin",
        W / 2,
        vanity * 0.55,
        min(0.22, W * 0.35),
        min(0.17, vanity * 0.32),
        0.84,
        0.13,
        "ceramic",
    )
    disc("tap", W / 2, 0.06, 0.016, 0.016, 0.84, 0.3, "metal")
    mirror = min(W * 0.85, 1.0)
    box(
        "mirror frame",
        W / 2 - mirror / 2 - 0.015,
        0,
        W / 2 + mirror / 2 + 0.015,
        0.025,
        1.08,
        0.83,
        "metal",
    )
    box("mirror", W / 2 - mirror / 2, 0.025, W / 2 + mirror / 2, 0.03, 1.095, 0.8, "mirror")
    box("led strip", W / 2 - mirror / 2, 0.0, W / 2 + mirror / 2, 0.02, 1.06, 0.012, "lampshade")


def shower(box, disc, W, D):
    box("tray", 0, 0, W, D, 0, 0.035, "stone")
    box("drain", W * 0.1, D * 0.45, W * 0.9, D * 0.45 + 0.03, 0.035, 0.002, "metal")
    box("glass screen", 0, D - 0.012, W * 0.6, D, 0.035, 1.97, "glass")
    box("screen profile", 0, D - 0.016, W * 0.6, D + 0.004, 1.98, 0.025, "metal")
    disc("rain head", W / 2, D / 2, 0.15, 0.15, 2.2, 0.012, "metal")
    disc("arm", W / 2, 0.05, 0.012, 0.012, 2.2, 0.06, "metal")
    box("niche", W * 0.3, 0, W * 0.7, 0.02, 1.1, 0.3, "accent")


def bathtub(box, disc, W, D):
    rim = 0.08
    box("bottom", 0, 0, W, D, 0, 0.12, "ceramic")
    box("rim back", 0, 0, W, rim, 0.12, 0.43, "ceramic")
    box("rim front", 0, D - rim, W, D, 0.12, 0.43, "ceramic")
    box("rim left", 0, rim, rim, D - rim, 0.12, 0.43, "ceramic")
    box("rim right", W - rim, rim, W, D - rim, 0.12, 0.43, "ceramic")
    disc("spout", W - 0.25, 0.04, 0.02, 0.02, 0.55, 0.25, "metal")


# ---------------------------------------------------------------- decor


def plant(box, disc, W, D):
    r = min(W, D) / 2
    disc("pot", W / 2, D / 2, r * 0.7, r * 0.7, 0, 0.42, "stone")
    for k, (scale, z0) in enumerate([(0.9, 0.42), (1.0, 0.7), (0.8, 1.0), (0.5, 1.25)]):
        disc(f"foliage {k}", W / 2, D / 2, r * scale, r * scale, z0, 0.3, "plant")


def floor_lamp(box, disc, W, D):
    r = min(W, D) / 2
    disc("base", W / 2, D / 2, r * 0.6, r * 0.6, 0, 0.025, "metal")
    disc("stem", W / 2, D / 2, 0.012, 0.012, 0.025, 1.3, "metal")
    disc("shade", W / 2, D / 2, r, r, 1.3, 0.3, "lampshade")


def _generic(box, disc, W, D):
    box("body", 0, 0, W, D, 0, 0.75, "furniture_wood")


MODELS = {
    name: fn
    for name, fn in globals().items()
    if callable(fn) and not name.startswith("_") and name not in {"furnish", "math"}
}

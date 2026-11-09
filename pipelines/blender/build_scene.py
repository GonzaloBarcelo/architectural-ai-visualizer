"""Deterministic Blender 4.5 entrypoint. Run through Blender, not system Python.

blender -b --factory-startup --python-exit-code 1 --python pipelines/blender/build_scene.py --
  --geometry outputs/demo-001/geometry.json --output outputs/demo-001 --stage build
"""

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path

import bmesh
import bpy
from mathutils import Vector
from mathutils.geometry import tessellate_polygon


def dump(path, data):
    path.write_text(json.dumps(data, indent=2) + "\n")


def material(
    name, color, roughness=0.6, metallic=0.0, transmission=0.0, emission=0.0, texture=None
):
    mat = bpy.data.materials.new(name)
    mat.diffuse_color = (*color, 1)
    mat.use_nodes = True
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    bsdf = nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = (*color, 1)
    bsdf.inputs["Roughness"].default_value = roughness
    bsdf.inputs["Metallic"].default_value = metallic
    bsdf.inputs["Transmission Weight"].default_value = transmission
    if emission:
        bsdf.inputs["Emission Color"].default_value = (*color, 1)
        bsdf.inputs["Emission Strength"].default_value = emission
    if texture:
        # Subtle procedural grain/veining; stripped before GLB export (viewer keeps base colour).
        coords = nodes.new("ShaderNodeTexCoord")
        mapping = nodes.new("ShaderNodeMapping")
        links.new(coords.outputs["Object"], mapping.inputs["Vector"])
        if texture == "wood":
            # Straight, fine grain: stretched noise reads as quiet oak/walnut grain.
            mapping.inputs["Scale"].default_value = (0.6, 0.6, 18.0)
            pattern = nodes.new("ShaderNodeTexNoise")
            pattern.inputs["Scale"].default_value = 6
            pattern.inputs["Detail"].default_value = 6
            pattern.inputs["Distortion"].default_value = 0.4
        elif texture == "stone":
            mapping.inputs["Scale"].default_value = (2.0, 2.0, 2.0)
            pattern = nodes.new("ShaderNodeTexNoise")
            pattern.inputs["Scale"].default_value = 3.5
            pattern.inputs["Detail"].default_value = 12
            pattern.inputs["Distortion"].default_value = 0.6
        else:  # fabric
            mapping.inputs["Scale"].default_value = (60.0, 60.0, 60.0)
            pattern = nodes.new("ShaderNodeTexNoise")
            pattern.inputs["Scale"].default_value = 4
            pattern.inputs["Detail"].default_value = 2
        links.new(mapping.outputs["Vector"], pattern.inputs["Vector"])
        ramp = nodes.new("ShaderNodeValToRGB")
        spread = {"wood": 0.09, "stone": 0.06, "fabric": 0.04}[texture]
        ramp.color_ramp.elements[0].color = (*[c * (1 - spread) for c in color], 1)
        ramp.color_ramp.elements[1].color = (*[min(1, c * (1 + spread)) for c in color], 1)
        links.new(pattern.outputs["Fac"], ramp.inputs["Fac"])
        links.new(ramp.outputs["Color"], bsdf.inputs["Base Color"])
    return mat


def srgb(hex_colour):
    values = [int(hex_colour[i : i + 2], 16) / 255 for i in (1, 3, 5)]
    return tuple(v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4 for v in values)


# Elegant, minimal luxury defaults; a client description overrides the matching keys.
PALETTE = {
    "walls": ("Enlucido de cal blanco cálido", "#ECE7DF", 0.9, {}),
    "floor": ("Roble europeo natural", "#B48D64", 0.42, {"texture": "wood"}),
    "tile": ("Travertino claro pulido", "#D8CCBA", 0.28, {"texture": "stone"}),
    "doors": ("Roble claro mate", "#C7AE8C", 0.5, {"texture": "wood"}),
    "joinery": ("Aluminio negro mate", "#1D1D1D", 0.38, {"metallic": 0.6}),
    "furniture_wood": ("Nogal americano", "#5B3D29", 0.42, {"texture": "wood"}),
    "upholstery": ("Bouclé marfil", "#E4DCCF", 0.95, {"texture": "fabric"}),
    "stone": ("Mármol Calacatta", "#ECE8E2", 0.18, {"texture": "stone"}),
    "ceramic": ("Cerámica blanca", "#F3F2EE", 0.12, {}),
    "metal": ("Latón cepillado", "#B08E52", 0.32, {"metallic": 1.0}),
    "bedding": ("Lino blanco", "#F1EEE8", 0.92, {"texture": "fabric"}),
    "accent": ("Lino salvia", "#8C957F", 0.9, {"texture": "fabric"}),
    "rug": ("Lana greige", "#CBC1B1", 0.98, {"texture": "fabric"}),
    "black": ("Negro grafito", "#202020", 0.35, {}),
    "screen": ("Pantalla negra", "#0C0C0C", 0.08, {}),
    "glass": ("Vidrio extraclaro", "#E8F0F0", 0.02, {"transmission": 1.0}),
    "mirror": ("Espejo", "#DDE2E2", 0.02, {"metallic": 1.0}),
    "plant": ("Follaje", "#4A6440", 0.7, {}),
    "lampshade": ("Luz cálida", "#FFE3BE", 0.9, {"emission": 3.0}),
}


def make_palette(finishes):
    cache = {}

    def palette(key):
        if key not in cache:
            name, hex_colour, rough, extra = PALETTE[key]
            f = finishes.get(key)
            if f:  # client finish: keep the default texture/metal character of the slot
                name, colour, rough = f["name"], tuple(f["color"]), f["roughness"]
            else:
                colour = srgb(hex_colour)
            cache[key] = material(f"{name} / proposal", colour, rough, **extra)
        return cache[key]

    return palette


def prism(name, polygon, z, height, collection, mat=None):
    # Enforce CCW, triangulate caps for concave polygons.
    polygon = list(polygon)
    area = sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(polygon, polygon[1:] + polygon[:1]))
    if area < 0:
        polygon.reverse()
    n = len(polygon)
    verts = [(x, y, z) for x, y in polygon] + [(x, y, z + height) for x, y in polygon]
    cap = [Vector((x, y, 0)) for x, y in polygon]
    faces = []
    for tri in tessellate_polygon([cap]):
        idx = [
            v if isinstance(v, int) else min(range(n), key=lambda i: (cap[i] - v).length)
            for v in tri
        ]
        faces.append(tuple(reversed(idx)))
        faces.append(tuple(i + n for i in idx))
    faces.extend((i, (i + 1) % n, (i + 1) % n + n, i + n) for i in range(n))
    mesh = bpy.data.meshes.new(name + "_mesh")
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    collection.objects.link(obj)
    if mat:
        obj.data.materials.append(mat)
    return obj


def tag(obj, item, kind, sha):
    obj["id"] = item["id"]
    obj["source_id"] = item["id"]
    obj["floor_id"] = item["floor_id"]
    obj["kind"] = kind
    obj["source_sha256"] = sha
    obj["verification_status"] = item["evidence"]["status"]


def aim(obj, target):
    obj.rotation_euler = (Vector(target) - obj.location).to_track_quat("-Z", "Y").to_euler()


def camera(scene, name, pos, target, ortho=None):
    data = bpy.data.cameras.new(name)
    obj = bpy.data.objects.new(name, data)
    scene.collection.objects.link(obj)
    obj.location = pos
    aim(obj, target)
    data.clip_start = 0.02
    data.clip_end = 10000
    data.lens = 40
    if ortho:
        data.type = "ORTHO"
        data.ortho_scale = ortho
    return obj


def choose_device(scene, requested):
    scene.cycles.device = "CPU"
    detected = []
    if requested != "cpu":
        prefs = bpy.context.preferences.addons["cycles"].preferences
        for kind in ["METAL", "OPTIX", "CUDA", "HIP", "ONEAPI"]:
            try:
                prefs.compute_device_type = kind
                prefs.get_devices()
                devices = [d for d in prefs.devices if d.type == kind]
                if devices:
                    for d in prefs.devices:
                        d.use = d.type == kind
                    scene.cycles.device = "GPU"
                    detected = [d.name for d in devices]
                    break
            except (TypeError, RuntimeError):
                continue
    if requested == "gpu" and not detected:
        raise RuntimeError(
            "GPU requested but no supported Cycles GPU was detected; use --device cpu."
        )
    return {"device": scene.cycles.device, "devices": detected}


def inspect(scene, output):
    objects = []
    deps = bpy.context.evaluated_depsgraph_get()
    for obj in scene.objects:
        if obj.type != "MESH" or "source_id" not in obj:
            continue
        ev = obj.evaluated_get(deps)
        mesh = ev.to_mesh()
        mesh.calc_loop_triangles()
        vertices = [list(ev.matrix_world @ v.co) for v in mesh.vertices]
        triangles = [list(t.vertices) for t in mesh.loop_triangles]
        bm = bmesh.new()
        bm.from_mesh(mesh)
        bm.transform(ev.matrix_world)
        volume = bm.calc_volume(signed=True)
        objects.append(
            {
                "id": obj["source_id"],
                "kind": obj["kind"],
                "floor_id": obj["floor_id"],
                "bbox_min": [min(v[i] for v in vertices) for i in range(3)],
                "bbox_max": [max(v[i] for v in vertices) for i in range(3)],
                "volume": volume,
                "vertices": vertices,
                "triangles": triangles,
                "non_manifold_edges": sum(not e.is_manifold for e in bm.edges),
                "degenerate_faces": sum(f.calc_area() < 1e-10 for f in bm.faces),
            }
        )
        bm.free()
        ev.to_mesh_clear()
    dump(
        output / "scene-inspection.json",
        {
            "units": scene.unit_settings.length_unit,
            "scale_length": scene.unit_settings.scale_length,
            "blender_version": bpy.app.version_string,
            "objects": objects,
        },
    )


def frame(polygon):
    """Centre, unit axis along the wall, unit axis across it, length and thickness."""
    p = [Vector((x, y)) for x, y in polygon]
    edges = [p[(i + 1) % len(p)] - p[i] for i in range(len(p))]
    along = max(edges, key=lambda e: e.length)
    across = min(edges, key=lambda e: e.length)
    centre = sum(p, Vector((0, 0))) / len(p)
    return centre, along.normalized(), across.normalized(), along.length, across.length


def joinery(op, host, collection, palette, sha):
    """Presentation frames, leaves, glass and sills inside a source opening."""
    c, a, b, length, depth = frame(op["polygon"])
    z0 = host["elevation"] + op["sill"]
    height = op["height"]
    style = op.get("style") or ("hinged" if op["kind"] == "door" else "casement")

    def piece(name, u0, u1, t0, t1, bottom, top, key):
        if u1 - u0 <= 1e-4 or t1 - t0 <= 1e-4 or top - bottom <= 1e-4:
            return
        poly = [c + a * u + b * t for u, t in [(u0, t0), (u1, t0), (u1, t1), (u0, t1)]]
        obj = prism(
            f"{op['id']} / {name}",
            [tuple(v) for v in poly],
            z0 + bottom,
            top - bottom,
            collection,
            palette(key),
        )
        obj["presentation_id"] = op["id"]
        obj["floor_id"] = op["floor_id"]
        obj["kind"] = "joinery"
        obj["verification_status"] = "inferred"
        obj["source_sha256"] = sha

    L, T, H = length / 2, depth / 2, height
    f = 0.055  # profile width
    glazed = op["kind"] == "window" or style == "glazed"
    if glazed:
        t0, t1 = -min(0.04, T), min(0.04, T)
        piece("frame left", -L, -L + f, t0, t1, 0, H, "joinery")
        piece("frame right", L - f, L, t0, t1, 0, H, "joinery")
        piece("frame head", -L, L, t0, t1, H - f, H, "joinery")
        piece("frame sill", -L, L, t0, t1, 0, f, "joinery")
        leaves = 2 if length > 0.9 else 1
        for i in range(1, leaves):
            u = -L + length * i / leaves
            piece(f"mullion {i}", u - f / 2, u + f / 2, t0, t1, f, H - f, "joinery")
        piece("glass", -L + f, L - f, -0.006, 0.006, f, H - f, "glass")
        if op["kind"] == "window" and op["sill"] > 0:
            piece("interior sill", -L - 0.03, L + 0.03, -T - 0.035, -T + 0.02, -0.03, 0, "stone")
            piece("exterior sill", -L - 0.03, L + 0.03, T - 0.02, T + 0.04, -0.04, 0, "stone")
    else:
        casing = 0.06
        piece("jamb left", -L, -L + casing * 0.4, -T - 0.012, T + 0.012, 0, H, "doors")
        piece("jamb right", L - casing * 0.4, L, -T - 0.012, T + 0.012, 0, H, "doors")
        piece("head", -L, L, -T - 0.012, T + 0.012, H - casing * 0.4, H, "doors")
        leaf = (-L + casing * 0.4 + 0.004, L - casing * 0.4 - 0.004)
        piece("leaf", leaf[0], leaf[1], -0.02, 0.02, 0.008, H - casing * 0.4 - 0.004, "doors")
        if style == "sliding":
            piece("pull", leaf[1] - 0.06, leaf[1] - 0.04, -0.022, 0.022, 0.85, 1.25, "metal")
        else:
            for side in (-1, 1):
                piece(
                    f"handle {side}",
                    leaf[1] - 0.16,
                    leaf[1] - 0.04,
                    side * 0.02,
                    side * 0.065,
                    1.0,
                    1.022,
                    "metal",
                )
            piece("rose", leaf[1] - 0.075, leaf[1] - 0.04, -0.03, 0.03, 0.98, 1.04, "metal")


def finish_rooms(data, floors, palette, sha):
    """Main floor over the slab, then per-room finishes read from the plan hatching."""

    def layer(ident, polygon, floor_id, height, key):
        z = next(f["elevation"] for f in data["floors"] if f["id"] == floor_id)
        obj = prism(ident + " / floor", polygon, z, height, floors[floor_id], palette(key))
        obj["presentation_id"] = ident
        obj["floor_id"] = floor_id
        obj["kind"] = "floor_finish"
        obj["verification_status"] = "inferred"
        obj["source_sha256"] = sha

    for slab in data["slabs"]:
        layer(slab["id"], slab["polygon"], slab["floor_id"], 0.004, "floor")
    for room in data["rooms"]:
        if room.get("floor_finish") in ("tile", "stone"):
            layer(room["id"], room["polygon"], room["floor_id"], 0.007, "tile")


HERO = [
    "bed_double",
    "bed_single",
    "sofa",
    "dining_set",
    "dining_table",
    "washbasin",
    "bathtub",
    "kitchen_counter",
    "desk",
]


def focus_piece(room, furniture, inside):
    """The piece a photographer would frame in this room, by type priority then size."""
    pieces = []
    for f in furniture:
        xs = [p[0] for p in f["polygon"]]
        ys = [p[1] for p in f["polygon"]]
        kind = f["name"].split(" / ")[0]
        if kind in HERO and inside((sum(xs) / len(xs), sum(ys) / len(ys)), room["polygon"]):
            size = (max(xs) - min(xs)) * (max(ys) - min(ys))
            pieces.append((HERO.index(kind), -size, f["polygon"]))
    return min(pieces)[2] if pieces else None


def interiors(scene, data, top, collection, palette):
    """One camera per main room, plus ceiling and warm lights visible only inside."""
    from viewpoint import area, best_view, inside

    if not data["rooms"]:
        return
    ceiling_mat = material("Techo enlucido", srgb("#F1EEE9"), 0.9)
    for slab in data["slabs"]:
        obj = prism("Ceiling / " + slab["id"], slab["polygon"], top, 0.12, collection, ceiling_mat)
        obj["interior_only"] = True
        obj.hide_render = True
    for room in data["rooms"]:
        xs = [p[0] for p in room["polygon"]]
        ys = [p[1] for p in room["polygon"]]
        light = bpy.data.lights.new("Ceiling light / " + room["id"], "AREA")
        light.shape = "RECTANGLE"
        light.size = max(0.3, (max(xs) - min(xs)) * 0.5)
        light.size_y = max(0.3, (max(ys) - min(ys)) * 0.5)
        light.energy = 9 * area(room["polygon"])
        light.color = (1.0, 0.84, 0.68)
        obj = bpy.data.objects.new("Ceiling light / " + room["id"], light)
        collection.objects.link(obj)
        obj.location = (sum(xs) / len(xs), sum(ys) / len(ys), top - 0.02)
        obj["interior_only"] = True
        obj.hide_render = True
    rooms = sorted(data["rooms"], key=lambda r: area(r["polygon"]), reverse=True)
    rooms = [r for r in rooms if area(r["polygon"]) >= 2.5][:4]
    for i, room in enumerate(rooms):
        same = room["floor_id"]
        small = area(room["polygon"]) < 6
        hero = focus_piece(room, data.get("furniture", []), inside)
        found = best_view(
            [room["polygon"]],
            [w["polygon"] for w in data["walls"] if w["floor_id"] == same],
            [
                f["polygon"]
                for f in data.get("furniture", [])
                if f["floor_id"] == same and f["height"] < 1.5
            ],
            clearance=0.3,
            tall=[
                f["polygon"]
                for f in data.get("furniture", [])
                if f["floor_id"] == same and f["height"] >= 1.5
            ],
            focus=hero,
        )
        if not found:
            continue
        (x, y), angle = found
        z = next(f["elevation"] for f in data["floors"] if f["id"] == same)
        eye = z + min(1.45, (top - z) * 0.54)
        target = (x + 3 * math.cos(angle), y + 3 * math.sin(angle), eye - 0.3)
        name = "interior" if i == 0 else f"interior-{i + 1}"
        cam = camera(scene, name, (x, y, eye), target)
        cam.data.lens = 14 if small else 17
        cam["view_label"] = "Interior · " + room["name"]
        cam["view_order"] = 2 + i
        cam["exposure"] = -0.2


def build(data, output):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.unit_settings.system = "METRIC"
    scene.unit_settings.length_unit = "METERS"
    scene.unit_settings.scale_length = 1
    architecture = bpy.data.collections.new("Architecture / verified")
    scene.collection.children.link(architecture)
    presentation = bpy.data.collections.new("Presentation / non architectural")
    scene.collection.children.link(presentation)
    floors = {}
    for f in data["floors"]:
        c = bpy.data.collections.new(f["id"] + " / " + f["name"])
        architecture.children.link(c)
        floors[f["id"]] = c
    sys.path.insert(0, str(Path(__file__).parent))
    palette = make_palette(data.get("finishes") or {})
    mats = {
        "wall": palette("walls"),
        "slab": material("Forjado", srgb("#BDB6AA"), 0.8),
        "roof": material("Roof mineral", (0.4, 0.4, 0.38)),
        "outdoor": material("Outdoor stone", (0.4, 0.39, 0.34)),
        # Source opening volumes stay for QA/GLB but are replaced by joinery in renders.
        "door": material("Opening volume", (0.85, 0.9, 0.9), 0.05, transmission=1.0),
        "window": material("Opening volume", (0.85, 0.9, 0.9), 0.05, transmission=1.0),
    }
    walls = {}
    sha = data["source"]["sha256"]
    for key, kind in [
        ("walls", "wall"),
        ("slabs", "slab"),
        ("roofs", "roof"),
        ("outdoor_areas", "outdoor"),
    ]:
        for item in data.get(key, []):
            obj = prism(
                item["id"],
                item["polygon"],
                item["elevation"],
                item["height"] if kind == "wall" else item["thickness"],
                floors[item["floor_id"]],
                mats[kind],
            )
            tag(obj, item, kind, sha)
            if kind == "wall":
                walls[item["id"]] = (obj, item)
    for op in data["openings"]:
        wall, host = walls[op["wall_id"]]
        # Extend cutter across wall thickness only; exact opening width remains authoritative.
        p = [Vector((x, y)) for x, y in op["polygon"]]
        edges = [p[(i + 1) % len(p)] - p[i] for i in range(len(p))]
        short = min(edges, key=lambda e: e.length).normalized()
        center = sum(p, Vector((0, 0))) / len(p)
        cutpoly = [list(v + short * (0.015 if (v - center).dot(short) > 0 else -0.015)) for v in p]
        cutter = prism(
            "_cut_" + op["id"],
            cutpoly,
            host["elevation"] + op["sill"],
            op["height"],
            floors[op["floor_id"]],
        )
        mod = wall.modifiers.new("Opening " + op["id"], "BOOLEAN")
        mod.operation = "DIFFERENCE"
        mod.solver = "EXACT"
        mod.object = cutter
        bpy.context.view_layer.objects.active = wall
        bpy.ops.object.modifier_apply(modifier=mod.name)
        bpy.data.objects.remove(cutter, do_unlink=True)
        obj = prism(
            op["id"],
            op["polygon"],
            host["elevation"] + op["sill"],
            op["height"],
            floors[op["floor_id"]],
            mats[op["kind"]],
        )
        tag(obj, op, op["kind"], sha)
        obj.hide_render = True
        joinery(op, host, floors[op["floor_id"]], palette, sha)
    from furnish import furnish

    furnish(data, floors, prism, palette)
    finish_rooms(data, floors, palette, sha)
    for room in data["rooms"]:
        obj = bpy.data.objects.new(room["id"] + " / " + room["name"], None)
        floors[room["floor_id"]].objects.link(obj)
        tag(obj, room, "room", sha)
    pts = [(x, y, s["elevation"]) for s in data["slabs"] for x, y in s["polygon"]]
    lo = [min(v[i] for v in pts) for i in range(3)]
    hi = [max(v[i] for v in pts) for i in range(3)]
    hi[2] = max(w["elevation"] + w["height"] for w in data["walls"])
    center = [(lo[i] + hi[i]) / 2 for i in range(3)]
    extent = max(hi[0] - lo[0], hi[1] - lo[1], hi[2] - lo[2])
    cx, cy, _ = center
    ext = camera(
        scene,
        "exterior",
        (cx + extent * 1.05, cy - extent * 1.3, hi[2] + extent * 0.7),
        (cx, cy, hi[2] * 0.38),
    )
    ext["view_label"], ext["view_order"] = "Exterior", 0
    axo = camera(
        scene,
        "axonometric",
        (cx + extent, cy - extent, hi[2] + extent * 1.2),
        (cx, cy, hi[2] * 0.35),
        extent * 1.55,
    )
    axo["view_label"], axo["view_order"] = "Axonometría", 1
    interiors(scene, data, hi[2], presentation, palette)
    pad = extent * 0.08
    bounds = [lo[0] - pad, lo[1] - pad, hi[0] + pad, hi[1] + pad]
    size = max(bounds[2] - bounds[0], bounds[3] - bounds[1])
    bounds = [cx - size / 2, cy - size / 2, cx + size / 2, cy + size / 2]
    top = camera(scene, "topdown", (cx, cy, hi[2] + extent), (cx, cy, 0), size)
    top.rotation_euler = (0, 0, 0)
    dump(output / "topdown-config.json", {"bounds": bounds, "resolution": 512})
    ground = prism(
        "Studio ground",
        [
            (-extent * 20, -extent * 20),
            (extent * 20, -extent * 20),
            (extent * 20, extent * 20),
            (-extent * 20, extent * 20),
        ],
        lo[2] - 0.08,
        0.05,
        presentation,
        material("Backdrop", (0.64, 0.62, 0.57), 0.85),
    )
    ground["kind"] = "presentation"
    world = bpy.data.worlds.new("Daylight")
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs[0].default_value = (0.72, 0.81, 1, 1)
    world.node_tree.nodes["Background"].inputs[1].default_value = 0.45
    scene.world = world
    light = bpy.data.lights.new("Soft sun", "SUN")
    light.energy = 2.5
    light.angle = math.radians(18)
    obj = bpy.data.objects.new("Soft sun", light)
    presentation.objects.link(obj)
    obj.rotation_euler = (math.radians(25), math.radians(-28), math.radians(-25))
    area = bpy.data.lights.new("Sky fill", "AREA")
    area.energy = 1100
    area.shape = "DISK"
    area.size = extent * 0.8
    obj = bpy.data.objects.new("Sky fill", area)
    presentation.objects.link(obj)
    obj.location = (cx, cy, hi[2] + extent * 0.7)
    aim(obj, center)
    scene.render.engine = "CYCLES"
    scene.cycles.seed = 42
    scene.cycles.use_animated_seed = False
    scene.cycles.use_denoising = True
    scene.render.image_settings.file_format = "PNG"
    scene.render.film_transparent = False
    scene.view_settings.view_transform = "AgX"
    scene["source_sha256"] = sha
    scene["geometry_sha256"] = hashlib.sha256((output / "geometry.json").read_bytes()).hexdigest()
    return scene


def views(scene):
    """Render cameras in presentation order with their gallery labels."""
    cams = [o for o in scene.objects if o.type == "CAMERA" and "view_label" in o]
    return sorted(cams, key=lambda o: o["view_order"])


def render_views(scene, output, preset, config):
    folder = output / ("renders" if preset == "final" else preset)
    folder.mkdir(exist_ok=True)
    scene.render.resolution_x = config["resolution"][0]
    scene.render.resolution_y = config["resolution"][1]
    scene.render.resolution_percentage = 100
    scene.cycles.samples = config["samples"]
    scene.view_layers[0].material_override = None
    if preset == "clay":
        scene.view_layers[0].material_override = material("QA clay", (0.65, 0.65, 0.65))
    for cam in views(scene):
        inside = cam.name.startswith("interior")
        # Ceilings and interior lights exist only for interior photographs.
        for obj in scene.objects:
            if obj.get("interior_only"):
                obj.hide_render = not inside
        scene.view_settings.exposure = cam.get("exposure", 0.0)
        scene.camera = cam
        scene.render.filepath = str(folder / (cam.name + ".png"))
        bpy.ops.render.render(write_still=True)
    for obj in scene.objects:
        if obj.get("interior_only"):
            obj.hide_render = True
    scene.view_settings.exposure = 0.0
    scene.view_layers[0].material_override = None
    dump(
        output / "views.json",
        [{"id": c.name, "label": c["view_label"]} for c in views(scene)],
    )


def render_top(scene, output):
    scene.camera = bpy.data.objects["topdown"]
    scene.render.resolution_x = scene.render.resolution_y = 512
    scene.render.resolution_percentage = 100
    scene.cycles.samples = 8
    scene.render.filepath = str(output / "orthographic-top.png")
    bpy.ops.render.render(write_still=True)
    hidden = {obj.name: obj.hide_render for obj in scene.objects}
    for obj in scene.objects:
        if obj.type == "MESH":
            obj.hide_render = obj.get("kind") != "wall"
    mask = bpy.data.materials.new("QA emission")
    mask.use_nodes = True
    nodes = mask.node_tree.nodes
    nodes.clear()
    out = nodes.new("ShaderNodeOutputMaterial")
    emit = nodes.new("ShaderNodeEmission")
    emit.inputs[0].default_value = (1, 1, 1, 1)
    mask.node_tree.links.new(emit.outputs[0], out.inputs["Surface"])
    scene.view_layers[0].material_override = mask
    bg = scene.world.node_tree.nodes["Background"]
    old = bg.inputs[0].default_value[:]
    bg.inputs[0].default_value = (0, 0, 0, 1)
    # QA measures silhouette coverage, not display brightness. sRGB conversion and
    # denoising expand thin white edges across the 50% threshold on a black mask.
    old_transform = scene.view_settings.view_transform
    old_denoising = scene.cycles.use_denoising
    old_samples = scene.cycles.samples
    scene.view_settings.view_transform = "Raw"
    scene.cycles.use_denoising = False
    scene.cycles.samples = 64
    scene.render.filepath = str(output / "topdown-mask.png")
    bpy.ops.render.render(write_still=True)
    scene.view_layers[0].material_override = None
    scene.view_settings.view_transform = old_transform
    scene.cycles.use_denoising = old_denoising
    scene.cycles.samples = old_samples
    bg.inputs[0].default_value = old
    for name, value in hidden.items():
        bpy.data.objects[name].hide_render = value


def export_glb(scene, output):
    # glTF carries constant PBR factors; drop procedural colour links so the viewer keeps
    # each material's base colour instead of a white fallback.
    for mat in bpy.data.materials:
        if not mat.use_nodes:
            continue
        bsdf = mat.node_tree.nodes.get("Principled BSDF")
        if bsdf is None:
            continue
        for link in list(bsdf.inputs["Base Color"].links):
            mat.node_tree.links.remove(link)
        bsdf.inputs["Base Color"].default_value = mat.diffuse_color
    bpy.ops.object.select_all(action="DESELECT")
    for obj in scene.objects:
        if ("source_id" in obj or "presentation_id" in obj) and not obj.get("interior_only"):
            obj.select_set(True)
    bpy.ops.export_scene.gltf(
        filepath=str(output / "model.raw.glb"),
        export_format="GLB",
        use_selection=True,
        export_extras=True,
        export_yup=True,
        export_apply=True,
        export_cameras=False,
        export_lights=False,
    )


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--geometry", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--stage", choices=["build", "final", "export"], default="build")
    p.add_argument("--device", choices=["auto", "cpu", "gpu"], default="auto")
    p.add_argument("--resolution", type=int, default=960)
    p.add_argument("--samples", type=int, default=64)
    p.add_argument("--clay", action="store_true")
    args = p.parse_args(sys.argv[sys.argv.index("--") + 1 :])
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    data = json.loads(args.geometry.read_text())
    for key in [
        "floors",
        "walls",
        "openings",
        "slabs",
        "roofs",
        "rooms",
        "measurements",
        "outdoor_areas",
    ]:
        allowed = (
            {"verified", "inferred"}
            if data.get("conceptual") and data.get("assumptions")
            else {"verified"}
        )
        if any(v["evidence"]["status"] not in allowed for v in data.get(key, [])):
            raise ValueError("Unverified geometry cannot be modeled as a final scene")
    if data.get("missing_information"):
        raise ValueError("Missing information blocks scene generation")
    config = {
        "engine": "CYCLES",
        "seed": 42,
        "device_requested": args.device,
        "preview": {"resolution": [480, 360], "samples": 12},
        "clay": {"resolution": [480, 360], "samples": 12},
        "final": {
            "resolution": [args.resolution, round(args.resolution * 0.75)],
            "samples": args.samples,
        },
        "materials": "Presentation finishes are illustrative, not inferred source specifications.",
    }
    if args.stage == "build":
        scene = build(data, output)
        config.update(choose_device(scene, args.device))
        dump(output / "render-config.json", config)
        inspect(scene, output)
        bpy.ops.wm.save_as_mainfile(filepath=str(output / "scene.blend"))
        render_views(scene, output, "preview", config["preview"])
        if args.clay:
            render_views(scene, output, "clay", config["clay"])
        render_top(scene, output)
    else:
        report = json.loads((output / "quality-report.json").read_text())
        if not report.get("passed"):
            raise ValueError("QA failed; final rendering/export blocked")
        bpy.ops.wm.open_mainfile(filepath=str(output / "scene.blend"))
        scene = bpy.context.scene
        current = hashlib.sha256(args.geometry.read_bytes()).hexdigest()
        if scene.get("geometry_sha256") != current or report.get("geometry_sha256") != current:
            raise ValueError("Geometry changed since scene generation; rebuild and rerun QA")
        config.update(choose_device(scene, args.device))
        dump(output / "render-config.json", config)
        if args.stage == "final":
            render_views(scene, output, "final", config["final"])
        export_glb(scene, output)
    print("AAV_STAGE_COMPLETE=" + args.stage)


if __name__ == "__main__":
    main()

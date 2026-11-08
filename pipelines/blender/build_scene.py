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


def material(name, color, roughness=0.6, metallic=0.0, transmission=0.0):
    mat = bpy.data.materials.new(name)
    mat.diffuse_color = (*color, 1)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = (*color, 1)
    bsdf.inputs["Roughness"].default_value = roughness
    bsdf.inputs["Metallic"].default_value = metallic
    bsdf.inputs["Transmission Weight"].default_value = transmission
    return mat


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
    mats = {
        "wall": material("Lime plaster", (0.79, 0.77, 0.70), 0.82),
        "slab": material("Warm limestone", (0.47, 0.44, 0.36), 0.75),
        "roof": material("Roof mineral", (0.4, 0.4, 0.38)),
        "outdoor": material("Outdoor stone", (0.4, 0.39, 0.34)),
        "door": material("Oak / visualization finish", (0.29, 0.14, 0.055), 0.42),
        "window": material("Architectural glass", (0.68, 0.84, 0.87), 0.08, transmission=0.88),
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
    camera(
        scene,
        "exterior",
        (cx + extent * 1.05, cy - extent * 1.3, hi[2] + extent * 0.7),
        (cx, cy, hi[2] * 0.38),
    )
    camera(
        scene,
        "axonometric",
        (cx + extent, cy - extent, hi[2] + extent * 1.2),
        (cx, cy, hi[2] * 0.35),
        extent * 1.55,
    )
    if data["rooms"]:
        room = data["rooms"][0]
        xs = [p[0] for p in room["polygon"]]
        ys = [p[1] for p in room["polygon"]]
        # Interior cameras supported for rectangular rooms. Camera placement never adds structure.
        z = next(f["elevation"] for f in data["floors"] if f["id"] == room["floor_id"]) + min(
            1.5, hi[2] * 0.55
        )
        pos = (min(xs) + (max(xs) - min(xs)) * 0.18, min(ys) + (max(ys) - min(ys)) * 0.15, z)
        target = ((min(xs) + max(xs)) * 0.5, max(ys), z * 0.9)
        camera(scene, "interior", pos, target).data.lens = 20
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
    for name in ["exterior", "interior", "axonometric"]:
        if name not in bpy.data.objects:
            continue
        scene.camera = bpy.data.objects[name]
        scene.render.filepath = str(folder / (name + ".png"))
        bpy.ops.render.render(write_still=True)
    scene.view_layers[0].material_override = None


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
    bpy.ops.object.select_all(action="DESELECT")
    for obj in scene.objects:
        if "source_id" in obj:
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
        if any(v["evidence"]["status"] != "verified" for v in data.get(key, [])):
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

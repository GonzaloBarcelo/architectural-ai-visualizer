"""Independent metric and raster checks on evaluated Blender meshes, never metadata alone.

Inputs: validated Geometry and scene-inspection.json captured from evaluated world meshes.
Outputs: quality-report.json and source-topdown-mask.png. Nonzero CLI status blocks delivery.
"""

import argparse
import json
from collections import Counter
from pathlib import Path

import numpy as np
from PIL import Image
from shapely import contains_xy
from shapely.geometry import Point, Polygon
from shapely.ops import unary_union

from pipelines.common import sha256, write_json
from pipelines.geometry.schema import Geometry


def _projected_mesh(vertices, triangles):
    pieces = []
    for t in triangles:
        p = Polygon(vertices[t, :2])
        if p.is_valid and p.area > 1e-10:
            pieces.append(p)
    return unary_union(pieces)


def _mesh_facts(obj):
    vertices = np.asarray(obj["vertices"], dtype=float)
    triangles = np.asarray(obj["triangles"], dtype=int)
    if vertices.ndim != 2 or vertices.shape[1] != 3 or not np.isfinite(vertices).all():
        raise ValueError("invalid or non-finite mesh vertices")
    if triangles.ndim != 2 or triangles.shape[1] != 3 or len(triangles) == 0:
        raise ValueError("missing triangular mesh faces")
    if triangles.min() < 0 or triangles.max() >= len(vertices):
        raise ValueError("triangle references absent vertex")
    pts = vertices[triangles]
    crosses = np.cross(pts[:, 1] - pts[:, 0], pts[:, 2] - pts[:, 0])
    degenerate = int(np.count_nonzero(np.linalg.norm(crosses, axis=1) < 1e-10))
    signed_volume = float(
        np.einsum("ij,ij->i", pts[:, 0], np.cross(pts[:, 1], pts[:, 2])).sum() / 6
    )
    edges = Counter()
    directed = Counter()
    for a, b, c in triangles:
        for i, j in ((a, b), (b, c), (c, a)):
            edges[tuple(sorted((int(i), int(j))))] += 1
            directed[(int(i), int(j))] += 1
    non_manifold = sum(count != 2 for count in edges.values())
    winding_errors = sum(directed[(a, b)] != directed[(b, a)] for a, b in edges)
    return {
        "vertices": vertices,
        "triangles": triangles,
        "min": vertices.min(axis=0),
        "max": vertices.max(axis=0),
        "volume": signed_volume,
        "degenerate": degenerate,
        "non_manifold": non_manifold,
        "winding_errors": winding_errors,
        "footprint": _projected_mesh(vertices, triangles),
    }


def _inside_mesh(point, vertices, triangles):
    """Ray parity against evaluated triangles; deduplicate shared-edge intersections."""
    direction = np.array([1.0, 0.371390676, 0.173205081])
    direction /= np.linalg.norm(direction)
    pts = vertices[triangles]
    edge1, edge2 = pts[:, 1] - pts[:, 0], pts[:, 2] - pts[:, 0]
    h = np.cross(direction, edge2)
    det = np.einsum("ij,ij->i", edge1, h)
    usable = np.abs(det) > 1e-10
    inverse = np.zeros_like(det)
    inverse[usable] = 1 / det[usable]
    offset = np.asarray(point) - pts[:, 0]
    u = inverse * np.einsum("ij,ij->i", offset, h)
    q = np.cross(offset, edge1)
    v = inverse * (q @ direction)
    t = inverse * np.einsum("ij,ij->i", edge2, q)
    hits = t[usable & (u >= -1e-8) & (v >= -1e-8) & (u + v <= 1 + 1e-8) & (t > 1e-8)]
    distances = np.unique(np.round(hits, 7))
    return bool(len(distances) % 2)


def _raster_polygon(polygons, bounds, resolution):
    lo_x, lo_y, hi_x, hi_y = bounds
    if hi_x <= lo_x or hi_y <= lo_y:
        raise ValueError("Invalid orthographic bounds")
    # Compare pixel centres, matching Blender's thresholded orthographic projection.
    # Inclusive rounded fillPoly boundaries can exaggerate narrow walls by a full pixel.
    x = lo_x + (np.arange(resolution) + 0.5) * (hi_x - lo_x) / resolution
    y = hi_y - (np.arange(resolution) + 0.5) * (hi_y - lo_y) / resolution
    xx, yy = np.meshgrid(x, y)
    source = unary_union([Polygon(p) for p in polygons])
    return contains_xy(source, xx, yy).astype(np.uint8) * 255


def check(geometry: Geometry, output: Path, include_renders=True, tolerance_m=0.002):
    """Run fail-closed checks. Tolerances are metric, volume-relative, and pixel-aware."""
    output = Path(output)
    checks = []
    errors = []

    def record(name, passed, **details):
        checks.append({"name": name, "passed": bool(passed), **details})
        if not passed:
            errors.append(name)

    try:
        geometry.require_verified()
        record("source_geometry_verified", True)
    except ValueError as exc:
        record("source_geometry_verified", False, detail=str(exc))
    try:
        scene = json.loads((output / "scene-inspection.json").read_text())
    except (OSError, ValueError) as exc:
        scene = {"objects": []}
        record("scene_inspection_available", False, detail=str(exc))
    record(
        "metric_scene_units",
        scene.get("units") == "METERS" and abs(scene.get("scale_length", 0) - 1) < 1e-9,
    )
    expected = {}
    walls = {w.id: w for w in geometry.walls}
    for kind, items in [
        ("wall", geometry.walls),
        ("slab", geometry.slabs),
        ("roof", geometry.roofs),
        ("outdoor", geometry.outdoor_areas),
        ("opening", geometry.openings),
    ]:
        for item in items:
            polygon = Polygon(item.polygon)
            if kind == "wall":
                bottom, height = item.elevation, item.height
                removed = sum(
                    Polygon(op.polygon).intersection(polygon).area * op.height
                    for op in geometry.openings
                    if op.wall_id == item.id
                )
                volume = polygon.area * height - removed
                # An opening covering the whole footprint (e.g. a door infill host) removes a
                # full horizontal band; the remaining solid's bounds shrink accordingly.
                bands = sorted(
                    (op.sill, op.sill + op.height)
                    for op in geometry.openings
                    if op.wall_id == item.id
                    and Polygon(op.polygon).buffer(tolerance_m).covers(polygon)
                )
                low, high = 0.0, height
                for start, end in bands:
                    if start <= low + tolerance_m:
                        low = max(low, end)
                for start, end in reversed(bands):
                    if end >= high - tolerance_m:
                        high = min(high, start)
                bottom, height = bottom + low, high - low
            elif kind == "opening":
                bottom, height = walls[item.wall_id].elevation + item.sill, item.height
                volume = polygon.area * height
            else:
                bottom, height = item.elevation, item.thickness
                volume = polygon.area * height
            minx, miny, maxx, maxy = polygon.bounds
            expected[item.id] = {
                "item": item,
                "kind": item.kind if kind == "opening" else kind,
                "polygon": polygon,
                "volume": volume,
                "min": np.array([minx, miny, bottom]),
                "max": np.array([maxx, maxy, bottom + height]),
            }
    actual_list = scene.get("objects", [])
    ids = [item.get("id") for item in actual_list]
    actual = {item.get("id"): item for item in actual_list}
    record(
        "stable_object_identifiers",
        len(ids) == len(set(ids)) and set(actual) == set(expected),
        expected=sorted(expected),
        actual=sorted(str(x) for x in actual),
        missing=sorted(set(expected) - set(actual)),
        unexpected=sorted(str(x) for x in set(actual) - set(expected)),
    )
    mesh_by_id = {}
    actual_footprints = []
    source_footprints = []
    for ident, exp in expected.items():
        obj = actual.get(ident)
        if obj is None:
            continue
        record(
            f"{ident}:source_link",
            obj.get("kind") == exp["kind"] and obj.get("floor_id") == exp["item"].floor_id,
        )
        try:
            mesh = _mesh_facts(obj)
        except (KeyError, ValueError, IndexError, TypeError) as exc:
            record(f"{ident}:valid_mesh", False, detail=str(exc))
            continue
        mesh_by_id[ident] = mesh
        error = float(
            max(np.max(np.abs(mesh["min"] - exp["min"])), np.max(np.abs(mesh["max"] - exp["max"])))
        )
        record(
            f"{ident}:location_and_dimensions",
            error <= tolerance_m,
            max_error_m=error,
            expected_min=exp["min"].tolist(),
            expected_max=exp["max"].tolist(),
            measured_min=mesh["min"].tolist(),
            measured_max=mesh["max"].tolist(),
        )
        # Cross-check serialized bounding metadata against actual vertices as well.
        bound_error = float(
            max(
                np.max(np.abs(mesh["min"] - obj["bbox_min"])),
                np.max(np.abs(mesh["max"] - obj["bbox_max"])),
            )
        )
        record(
            f"{ident}:inspection_bounds_consistent",
            bound_error <= tolerance_m,
            max_error_m=bound_error,
        )
        volume_error = abs(mesh["volume"] - exp["volume"])
        volume_tolerance = max(1e-5, exp["volume"] * 0.002)
        record(
            f"{ident}:volume_and_openings",
            volume_error <= volume_tolerance,
            expected_m3=exp["volume"],
            measured_m3=mesh["volume"],
            tolerance_m3=volume_tolerance,
        )
        record(
            f"{ident}:inspection_volume_consistent",
            abs(mesh["volume"] - obj["volume"]) <= volume_tolerance,
        )
        record(
            f"{ident}:closed_consistent_normals",
            mesh["non_manifold"] == 0
            and mesh["winding_errors"] == 0
            and mesh["volume"] > 0
            and mesh["degenerate"] == 0,
            non_manifold_edges=mesh["non_manifold"],
            winding_errors=mesh["winding_errors"],
            degenerate_faces=mesh["degenerate"],
        )
        polygon_error = float(mesh["footprint"].symmetric_difference(exp["polygon"]).area)
        area_tolerance = max(1e-5, exp["polygon"].length * tolerance_m)
        record(
            f"{ident}:projected_source_polygon",
            polygon_error <= area_tolerance,
            symmetric_difference_m2=polygon_error,
            tolerance_m2=area_tolerance,
        )
        if exp["kind"] in ("wall", "slab", "roof", "outdoor"):
            actual_footprints.append(mesh["footprint"])
            source_footprints.append(exp["polygon"])
    footprint_error = (
        unary_union(actual_footprints).symmetric_difference(unary_union(source_footprints)).area
    )
    record(
        "overall_building_footprint",
        bool(actual_footprints)
        and footprint_error <= tolerance_m * unary_union(source_footprints).length,
        symmetric_difference_m2=float(footprint_error),
    )
    # Verify the actual boolean void at each source opening, independently of volume.
    for opening in geometry.openings:
        host = mesh_by_id.get(opening.wall_id)
        if host is None:
            continue
        polygon = Polygon(opening.polygon)
        center = np.array(polygon.representative_point().coords[0])
        samples_xy = [center]
        for vertex in opening.polygon:
            candidate = center * 0.7 + np.array(vertex) * 0.3
            if polygon.contains(Point(candidate)):
                samples_xy.append(candidate)
        base = walls[opening.wall_id].elevation + opening.sill
        occupied = sum(
            _inside_mesh(
                [*point, base + opening.height * fraction], host["vertices"], host["triangles"]
            )
            for point in samples_xy
            for fraction in (0.2, 0.5, 0.8)
        )
        record(
            f"{opening.id}:host_wall_void_at_source_position",
            occupied == 0,
            occupied_samples=occupied,
            sample_count=len(samples_xy) * 3,
        )
    # Detect overlapping declared openings (would otherwise double-subtract wall volume).
    for i, opening in enumerate(geometry.openings):
        for other in geometry.openings[i + 1 :]:
            if opening.wall_id != other.wall_id:
                continue
            overlap_height = min(opening.sill + opening.height, other.sill + other.height) - max(
                opening.sill, other.sill
            )
            overlap_area = Polygon(opening.polygon).intersection(Polygon(other.polygon)).area
            record(
                f"{opening.id}/{other.id}:no_opening_overlap",
                overlap_height <= tolerance_m or overlap_area <= tolerance_m**2,
            )
    if include_renders or (output / "topdown-mask.png").exists():
        try:
            config = json.loads((output / "topdown-config.json").read_text())
            resolution = int(config["resolution"])
            expected_mask = _raster_polygon(
                [w.polygon for w in geometry.walls], config["bounds"], resolution
            )
            Image.fromarray(expected_mask).save(output / "source-topdown-mask.png")
            actual_mask = np.asarray(Image.open(output / "topdown-mask.png").convert("L")) > 127
            if actual_mask.shape != expected_mask.shape:
                raise ValueError("Orthographic render dimensions mismatch")
            source = expected_mask > 127
            intersection = np.count_nonzero(source & actual_mask)
            union = np.count_nonzero(source | actual_mask)
            iou = float(intersection / union) if union else 0.0
            record(
                "orthographic_source_overlay",
                iou >= 0.90,
                iou=iou,
                minimum_iou=0.90,
                note="Pixel raster tolerance; metric mesh checks are independently stricter.",
            )
            border = np.concatenate(
                [actual_mask[0], actual_mask[-1], actual_mask[:, 0], actual_mask[:, -1]]
            )
            record("orthographic_no_clipping", not bool(border.any()))
        except (OSError, ValueError, KeyError) as exc:
            record("orthographic_source_overlay", False, detail=str(exc))
    required = (
        [
            output / "renders" / f"{name}.webp"
            for name in (["exterior", "axonometric"] + (["interior"] if geometry.rooms else []))
        ]
        if include_renders
        else []
    )
    optional = sorted((output / "preview").glob("*.png")) + sorted((output / "clay").glob("*.png"))
    for image_path in required + optional:
        label = str(image_path.relative_to(output))
        try:
            image = Image.open(image_path).convert("RGB")
            pixels = np.asarray(image, dtype=float) / 255
            luminance = pixels @ np.array([0.2126, 0.7152, 0.0722])
            std = float(luminance.std())
            mean = float(luminance.mean())
            spread = float(np.percentile(luminance, 99) - np.percentile(luminance, 1))
            record(
                f"{label}:nonblank_exposure",
                std > 0.025 and spread > 0.1 and 0.025 < mean < 0.98 and min(image.size) >= 128,
                luminance_std=std,
                mean=mean,
                percentile_range=spread,
                size=list(image.size),
            )
        except (OSError, ValueError) as exc:
            record(f"{label}:nonblank_exposure", False, detail=str(exc))
    report = {
        "schema_version": "1.0",
        "passed": not errors,
        "source_sha256": geometry.source.sha256,
        "geometry_sha256": sha256(output / "geometry.json")
        if (output / "geometry.json").exists()
        else None,
        "tolerance_m": tolerance_m,
        "checks": checks,
        "errors": errors,
        "limitations": [
            "Render exposure tests are heuristics; aesthetic quality still requires visual review.",
            "Top-down mask tests projection and framing, not invisible internal faces.",
            "Solid topology, volume and footprint checks do not prove arbitrary 3D collision freedom.",
            "Human-verified input geometry is trusted; this report does not certify construction accuracy.",
        ],
    }
    write_json(output / "quality-report.json", report)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--geometry", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--skip-renders", action="store_true")
    parser.add_argument("--tolerance-m", type=float, default=0.002)
    args = parser.parse_args()
    result = check(
        Geometry.model_validate_json(args.geometry.read_text()),
        args.output,
        not args.skip_renders,
        args.tolerance_m,
    )
    print(json.dumps({"passed": result["passed"], "errors": result["errors"]}, indent=2))
    raise SystemExit(0 if result["passed"] else 2)

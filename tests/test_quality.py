from copy import deepcopy

import numpy as np
import pytest

from pipelines.common import write_json
from pipelines.geometry.schema import Geometry
from pipelines.quality.check import _mesh_facts, _raster_polygon, check


def cube_object(ident, kind, floor_id, lower, upper):
    x, y, z = lower
    a, b, c = upper
    vertices = [
        [x, y, z],
        [a, y, z],
        [a, b, z],
        [x, b, z],
        [x, y, c],
        [a, y, c],
        [a, b, c],
        [x, b, c],
    ]
    triangles = [
        [0, 2, 1],
        [0, 3, 2],
        [4, 5, 6],
        [4, 6, 7],
        [0, 1, 5],
        [0, 5, 4],
        [1, 2, 6],
        [1, 6, 5],
        [2, 3, 7],
        [2, 7, 6],
        [3, 0, 4],
        [3, 4, 7],
    ]
    return {
        "id": ident,
        "kind": kind,
        "floor_id": floor_id,
        "vertices": vertices,
        "triangles": triangles,
        "bbox_min": lower,
        "bbox_max": upper,
        "volume": (a - x) * (b - y) * (c - z),
        "non_manifold_edges": 0,
        "degenerate_faces": 0,
    }


def simple_scene(geometry):
    data = geometry.model_dump()
    data["openings"] = []
    data["rooms"] = []
    simplified = Geometry.model_validate(data)
    objects = []
    for kind, items in [("wall", simplified.walls), ("slab", simplified.slabs)]:
        for item in items:
            p = np.asarray(item.polygon)
            z = item.elevation
            height = item.height if kind == "wall" else item.thickness
            lower = [*p.min(axis=0).tolist(), z]
            upper = [*p.max(axis=0).tolist(), z + height]
            objects.append(cube_object(item.id, kind, item.floor_id, lower, upper))
    return simplified, {"units": "METERS", "scale_length": 1, "objects": objects}


def test_independent_mesh_math_detects_winding():
    obj = cube_object("cube", "wall", "F0", [0, 0, 0], [1, 2, 3])
    facts = _mesh_facts(obj)
    assert facts["volume"] == pytest.approx(6)
    assert facts["non_manifold"] == 0
    assert facts["winding_errors"] == 0
    obj["triangles"][0].reverse()
    assert _mesh_facts(obj)["winding_errors"] > 0


def test_valid_metric_scene_passes(geometry, tmp_path):
    geo, scene = simple_scene(geometry)
    write_json(tmp_path / "scene-inspection.json", scene)
    result = check(geo, tmp_path, include_renders=False)
    assert result["passed"], result["errors"]


@pytest.mark.parametrize(
    "mutation", ["vertices", "bbox", "volume", "missing", "unexpected", "scale", "winding"]
)
def test_tampered_scene_cannot_pass_qa(geometry, tmp_path, mutation):
    geo, scene = simple_scene(geometry)
    if mutation == "vertices":
        for point in scene["objects"][0]["vertices"]:
            point[0] += 0.1
    elif mutation == "bbox":
        scene["objects"][0]["bbox_min"][0] += 0.1
    elif mutation == "volume":
        scene["objects"][0]["volume"] += 1
    elif mutation == "missing":
        scene["objects"].pop()
    elif mutation == "unexpected":
        extra = deepcopy(scene["objects"][0])
        extra["id"] = "unexpected-wall"
        scene["objects"].append(extra)
    elif mutation == "scale":
        scene["scale_length"] = 0.01
    elif mutation == "winding":
        scene["objects"][0]["triangles"][0].reverse()
    write_json(tmp_path / "scene-inspection.json", scene)
    result = check(geo, tmp_path, include_renders=False)
    assert not result["passed"]
    assert result["errors"]


def test_missing_render_evidence_blocks_delivery(geometry, tmp_path):
    geo, scene = simple_scene(geometry)
    write_json(tmp_path / "scene-inspection.json", scene)
    result = check(geo, tmp_path, include_renders=True)
    assert not result["passed"]
    assert "orthographic_source_overlay" in result["errors"]


def test_narrow_wall_raster_uses_pixel_coverage_without_edge_expansion():
    # 20 cm wall at 10 cm/pixel: exactly two columns and eighty rows.
    polygon = [[1, 1], [1.2, 1], [1.2, 9], [1, 9]]
    mask = _raster_polygon([polygon], [0, 0, 10, 10], 100)
    expected = np.zeros((100, 100), dtype=np.uint8)
    expected[10:90, 10:12] = 255
    np.testing.assert_array_equal(mask, expected)

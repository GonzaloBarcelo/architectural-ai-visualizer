import math

from shapely.geometry import Polygon

from pipelines.blender.furnish import furnish


def test_parametric_furniture_parts_are_valid_and_keep_inferred_identity():
    parts = []

    def prism(name, polygon, z, height, collection, material):
        assert len(polygon) == 4
        assert Polygon(polygon).is_valid and Polygon(polygon).area > 0
        assert math.isfinite(z) and height > 0
        obj = {}
        parts.append((name, obj))
        return obj

    data = {
        "source": {"sha256": "a" * 64},
        "floors": [{"id": "F0", "elevation": 0}],
        "furniture": [
            {
                "id": kind,
                "name": kind + " / test",
                "floor_id": "F0",
                "polygon": [(0, 0), (2, 0), (2, 1), (0, 1)],
                "height": 1,
            }
            for kind in ["bed", "sofa", "table", "chair", "kitchen", "sanitary", "cabinet"]
        ],
    }
    furnish(data, {"F0": "collection"}, prism, lambda name, *args: name)
    assert len(parts) > 20
    assert {obj["presentation_id"] for _, obj in parts} == {
        item["id"] for item in data["furniture"]
    }
    assert all(obj["verification_status"] == "inferred" for _, obj in parts)

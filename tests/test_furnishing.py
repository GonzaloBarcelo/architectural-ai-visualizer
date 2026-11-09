import math

from shapely.geometry import Polygon

from pipelines.blender.furnish import MODELS, furnish
from pipelines.web.furniture import HEIGHTS


def test_every_furniture_kind_builds_valid_oriented_parts_with_inferred_identity():
    parts = []

    def prism(name, polygon, z, height, collection, material):
        assert len(polygon) >= 4
        assert Polygon(polygon).is_valid and Polygon(polygon).area > 0
        assert math.isfinite(z) and height > 0
        obj = {"name": name}
        parts.append(obj)
        return obj

    kinds = [k for k in HEIGHTS if k != "not_furniture"]
    assert set(kinds) <= set(MODELS)
    data = {
        "source": {"sha256": "a" * 64},
        "floors": [{"id": "F0", "elevation": 0}],
        "furniture": [
            {
                "id": kind,
                "name": kind + " / test",
                "floor_id": "F0",
                # Rotated footprint: back edge along y, front facing -x.
                "polygon": [(2, 0), (2, 1.6), (0, 1.6), (0, 0)],
                "height": HEIGHTS[kind],
            }
            for kind in kinds
        ],
    }
    furnish(data, {"F0": "collection"}, prism, lambda key: key)
    assert {obj["presentation_id"] for obj in parts} == set(kinds)
    assert all(obj["verification_status"] == "inferred" for obj in parts)
    assert len(parts) > 4 * len(kinds)


def test_headboard_sits_on_the_back_edge():
    parts = {}

    def prism(name, polygon, z, height, collection, material):
        parts[name.split(" / ")[1]] = polygon
        return {}

    data = {
        "source": {"sha256": "a" * 64},
        "floors": [{"id": "F0", "elevation": 0}],
        "furniture": [
            {
                "id": "bed",
                "name": "bed_double / Cama",
                "floor_id": "F0",
                "polygon": [(0, 2), (1.5, 2), (1.5, 0), (0, 0)],  # back at y=2, front y=0
                "height": 1.1,
            }
        ],
    }
    furnish(data, {"F0": "c"}, prism, lambda key: key)
    assert min(y for _, y in parts["headboard"]) > 1.9

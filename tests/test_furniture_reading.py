"""Furniture read from PDF vectors, orientation checks and floor finishes."""

import pytest
from shapely.geometry import Polygon, box
from shapely.ops import unary_union

from pipelines.web import furniture as F

FACTOR = 50 * 0.0254 / 72  # 1:50, metres per PDF point


def walls_around(x0, y0, x1, y1, t=12):
    return unary_union(
        [
            box(x0 - t, y0 - t, x1 + t, y0),
            box(x0 - t, y1, x1 + t, y1 + t),
            box(x0 - t, y0, x0, y1),
            box(x1, y0, x1 + t, y1),
        ]
    )


def mask(index, x0, y0, x1, y1):
    corners = [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]
    return {
        "index": index,
        "fill": [1.0, 1.0, 1.0],
        "color": [1.0, 1.0, 1.0],
        "width": 0,
        "items": [["l", corners[i], corners[(i + 1) % 4]] for i in range(4)]
        + [["l", corners[0], corners[2]]],  # CAD masks are triangulated
    }


def test_candidates_are_exact_mask_footprints_and_skip_facade_joinery():
    # A window opening in the bottom wall holds joinery within the wall thickness.
    walls = walls_around(0, 0, 400, 300).difference(box(300, 300, 360, 312))
    page = {
        "drawings": [
            mask(0, 100, 0.5, 185, 113),  # bed 1.5 x 2.0 m against the top wall
            mask(1, 120, 10, 165, 30),  # pillow inside the bed merges into it
            mask(2, 300, 300, 360, 312),  # window joinery in the facade band
        ]
    }
    candidates = F.furniture_candidates(page, walls, FACTOR)
    assert len(candidates) == 1
    (rect,) = candidates.values()
    assert rect.bounds == pytest.approx((100, 0.5, 185, 113))


def test_wall_backed_furniture_orientation_is_corrected_to_the_wall():
    walls = walls_around(0, 0, 400, 300)
    bed = box(100, 0, 185, 113)  # headboard touches the top wall
    front, note = F.resolve_front("bed_double", bed, "up", walls, [], FACTOR)
    assert front == "down" and note
    assert F.resolve_front("bed_double", bed, "down", walls, [], FACTOR) == ("down", None)


def test_chairs_face_their_table():
    walls = walls_around(0, 0, 400, 300)
    table = box(150, 100, 250, 160)
    chair = box(185, 165, 210, 190)  # below the table
    front, _ = F.resolve_front("chair", chair, "down", walls, [table], FACTOR)
    assert front == "up"


def test_ordered_polygon_puts_back_edge_first_and_front_last():
    rect = box(0, 0, 100, 50)
    poly = F.ordered_polygon(rect, "down")  # front faces +y (down in the image)
    back = {tuple(poly[0]), tuple(poly[1])}
    front = {tuple(poly[2]), tuple(poly[3])}
    assert back == {(0, 0), (100, 0)} and front == {(0, 50), (100, 50)}
    assert Polygon(poly).is_valid


def test_floor_finishes_distinguish_wood_hatch_from_tile_grid():
    wood = box(0, 0, 100, 100)
    bath = box(200, 0, 300, 100)
    hatch = [
        {
            "color": [0.78, 0.78, 0.79],
            "width": 0.24,
            "items": [["l", [0, y], [100, y]] for y in range(5, 100, 5)],
        },
    ]
    grid = [
        {
            "color": [0.26, 0.26, 0.26],
            "width": 0.12,
            "items": [["l", [200, y], [300, y]] for y in range(10, 100, 10)]
            + [["l", [x, 0], [x, 100]] for x in range(210, 300, 10)],
        },
    ]
    finishes = F.floor_finishes({"drawings": hatch + grid}, {"Salón": wood, "Baño": bath}, FACTOR)
    assert finishes == {"Salón": "wood", "Baño": "tile"}

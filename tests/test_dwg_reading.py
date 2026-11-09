"""Deterministic DWG/DXF reading on synthetic ezdxf fixtures (no AI, no converter)."""

import math

import ezdxf
import pytest
from dxf_fixture import build
from shapely.geometry import Polygon

from pipelines.cad import config as C
from pipelines.cad import read as R
from pipelines.web import dwg
from pipelines.web.review import validate_draft

SOURCE = {
    "filename": "flat.dwg",
    "sha256": "b" * 64,
    "page_count": 1,
    "format": "dwg",
    "converter": "Test converter 1.0",
}


def reading(path):
    doc = R.load(path)
    units = R.detect_units(doc)
    plan = R.detect_plans(doc, units)[0]
    return R.read_plan(doc, plan, units)


def entities(draft, kind):
    return [e for e in draft["entities"] if e["kind"] == kind]


def raw_for(summary):
    sheet = summary["sheet"]
    return {
        "source": SOURCE,
        "pages": [{"page": 1, "size_points": [sheet["width"], sheet["height"]]}],
    }


def confirm(draft):
    draft["calibration"]["confirmed"] = draft["floor"]["confirmed"] = draft["complete"] = True
    for e in draft["entities"]:
        e["confirmed"] = True
    return draft


def test_units_come_from_insunits_and_are_recorded(tmp_path):
    doc = R.load(build(tmp_path / "mm.dxf"))
    units = R.detect_units(doc)
    assert units["metres_per_unit"] == 0.001 and units["name"] == "mm"
    assert "$INSUNITS" in units["source"] and not units["inferred"]


def test_missing_insunits_are_inferred_from_walls_extents_and_dimensions(tmp_path):
    units = R.detect_units(R.load(build(tmp_path / "unitless.dxf", insunits=0)))
    assert units["metres_per_unit"] == 0.001 and units["inferred"]
    assert "inferidas" in units["source"] and "cotas" in units["source"]


def test_declared_units_that_contradict_the_drawing_stop(tmp_path):
    doc = R.load(build(tmp_path / "wrong.dxf", insunits=6))  # metres declared, mm drawn
    with pytest.raises(ValueError, match="no son coherentes"):
        R.detect_units(doc)


def test_ambiguous_units_are_never_guessed(tmp_path):
    doc = ezdxf.new()
    doc.header["$INSUNITS"] = 0
    with pytest.raises(ValueError, match="unidades"):
        R.detect_units(doc, wall_polygons=[], dimensions=[])


def test_wall_polygons_have_thickness_and_no_holes(tmp_path):
    r = reading(build(tmp_path / "flat.dxf"))
    union = r["wall_union"]
    expected = sum((x1 - x0) * (y1 - y0) for x0, y0, x1, y1 in __import__("dxf_fixture").WALLS)
    assert union.area == pytest.approx(expected * 1e-6, rel=1e-3)
    assert all(not w["polygon"].interiors for w in r["walls"])
    assert all("MUROS" in w["layers"] and w["handles"] for w in r["walls"])


def test_walls_from_parallel_lines_and_ring_walls_split(tmp_path):
    doc = ezdxf.new()
    doc.header["$INSUNITS"] = 4
    msp = doc.modelspace()
    # A closed ring of walls drawn as one outline with a hole (outer and inner contour).
    hatch = msp.add_hatch(dxfattribs={"layer": "A-WALL"})
    hatch.paths.add_polyline_path([(0, 0), (5000, 0), (5000, 4000), (0, 4000)], is_closed=True)
    hatch.paths.add_polyline_path(
        [(200, 200), (4800, 200), (4800, 3800), (200, 3800)], is_closed=True
    )
    # An interior partition drawn as two parallel lines.
    msp.add_line((2500, 200), (2500, 3800), dxfattribs={"layer": "TABIQUES"})
    msp.add_line((2600, 200), (2600, 3800), dxfattribs={"layer": "TABIQUES"})
    path = tmp_path / "ring.dxf"
    doc.saveas(path)
    r = reading(path)
    assert len(r["walls"]) >= 2 and all(not w["polygon"].interiors for w in r["walls"])
    partition = Polygon([(2.5, 0.2), (2.6, 0.2), (2.6, 3.8), (2.5, 3.8)])
    assert r["wall_union"].intersection(partition).area == pytest.approx(partition.area, rel=1e-3)
    assert len(r["rooms"]) == 2


def test_openings_take_width_and_host_from_the_wall_gap(tmp_path):
    r = reading(build(tmp_path / "flat.dxf"))
    openings = {g["opening"]["kind"]: g for g in r["gaps"] if g["opening"]}
    door, window = openings["door"], openings["window"]
    assert door["width"] == pytest.approx(0.8) and door["depth"] == pytest.approx(0.1)
    assert door["opening"]["style"] == "hinged" and door["opening"]["status"] == "verified"
    assert door["opening"]["swing"]["hinge"] in ("start", "end")
    assert window["width"] == pytest.approx(1.2) and window["depth"] == pytest.approx(0.2)
    assert window["on_facade"] and not door["on_facade"]
    # Host by geometric contact: wall material just beyond both jambs.
    for g in (door, window):
        jambs = g["rect"].buffer(0.01).intersection(r["wall_union"]).area
        assert jambs > 0


def test_block_inserts_map_to_kind_ordered_polygon_and_front(tmp_path):
    path = build(tmp_path / "flat.dxf")
    draft, summary, _ = dwg.propose(path, SOURCE, call_ai=False)
    furniture = {e["name"].split(" / ")[0]: e for e in entities(draft, "furniture")}
    # Sheet: centimetres, y down, origin 1.5 m outside the plan's top-left corner.
    bed = furniture["bed_double"]["polygon"]
    assert [p[0] for p in bed[:2]] == [170, 170]  # back (headboard) on the west wall x = 0.2 m
    assert [p[0] for p in bed[2:]] == [370, 370]  # foot towards the room (+x)
    assert sorted(p[1] for p in bed) == [280, 280, 430, 430]  # y 1.2 … 2.7 m
    # Mirrored (xscale -1) and rotated 90°: back on the partition, footprint flipped.
    toilet = furniture["toilet"]["polygon"]
    assert [p[0] for p in toilet[:2]] == [460, 460]
    assert all(p[0] == pytest.approx(529) for p in toilet[2:])
    assert sorted(p[1] for p in toilet) == [250, 250, 290, 290]  # y 2.6 … 3.0 m
    assert furniture["toilet"]["cad"]["block"] == "INODORO"
    assert furniture["toilet"]["cad"]["reading"] == "verified"
    assert not summary["pending"]


def test_resolve_front_corrects_a_block_drawn_with_another_convention(tmp_path):
    doc = ezdxf.new()
    doc.header["$INSUNITS"] = 4
    bed = doc.blocks.new("CAMA_90")
    bed.add_lwpolyline([(0, 0), (900, 0), (900, 2000), (0, 2000)], close=True)
    msp = doc.modelspace()
    for x0, y0, x1, y1 in __import__("dxf_fixture").WALLS:
        msp.add_lwpolyline(
            [(x0, y0), (x1, y0), (x1, y1), (x0, y1)], close=True, dxfattribs={"layer": "MUROS"}
        )
    # Insert so that the local -y "front" points at the north wall: the back floats free.
    msp.add_blockref("CAMA_90", (1100, 3800), dxfattribs={"rotation": 180, "layer": "MUEBLES"})
    msp.add_text("Dormitorio", dxfattribs={"insert": (500, 600), "height": 100})
    msp.add_text("Baño", dxfattribs={"insert": (4500, 1500), "height": 100})
    path = tmp_path / "turned.dxf"
    doc.saveas(path)
    draft, _summary, _ = dwg.propose(path, SOURCE, call_ai=False)
    bed = next(e for e in entities(draft, "furniture") if e["name"].startswith("bed_single"))
    back = bed["polygon"][:2]
    assert all(abs(p[1] - (5.5 - 3.8) * 100) < 0.5 for p in back)  # back on the north wall
    assert "orientación corregida" in bed["cad"]["detail"]


def test_doubts_payload_lists_only_unresolved_items_with_context(tmp_path):
    r = reading(build(tmp_path / "flat.dxf", unknown=True))
    payload = dwg.doubts(r)
    assert [i["type"] for i in payload["items"]] == ["furniture"]
    item = payload["items"][0]
    assert item["block"] == "XYZ123" and item["layer"] == "MOBILIARIO"
    assert item["id"].startswith("B") and item["room"] == "Baño"
    assert item["bbox"] == [5.0, 0.6, 5.6, 1.2] and item["size"] == [0.6, 0.6]
    assert item["content"] == {"CIRCLE": 1, "LWPOLYLINE": 1}
    assert {k["kind"] for k in payload["context"]["known_furniture"]} == {"bed_double", "toilet"}
    assert len(str(payload)) < 4000


def test_draft_validates_into_dwg_geometry_with_provenance(tmp_path):
    draft, summary, _ = dwg.propose(build(tmp_path / "flat.dxf"), SOURCE, call_ai=False)
    geometry, issues = validate_draft(confirm(draft), raw_for(summary), "p1")
    assert not issues, issues
    assert geometry.source.format == "dwg" and geometry.source.converter == "Test converter 1.0"
    assert {o.kind for o in geometry.openings} == {"door", "window"}
    door = next(o for o in geometry.openings if o.kind == "door")
    assert door.evidence.cad.block == "PUERTA_80" and door.evidence.cad.handles
    host = next(w for w in geometry.walls if w.id == door.wall_id)
    assert host.thickness == pytest.approx(0.1)
    xs = [p[0] for p in door.polygon]
    assert max(xs) - min(xs) == pytest.approx(0.1, abs=1e-6)
    ys = [p[1] for p in door.polygon]
    assert max(ys) - min(ys) == pytest.approx(0.8, abs=1e-6)
    assert all(math.isfinite(v) for w in geometry.walls for p in w.polygon for v in p)
    assert {r.name for r in geometry.rooms} == {"Dormitorio", "Baño"}


def test_several_drawn_plans_are_listed_for_the_user(tmp_path):
    doc = R.load(build(tmp_path / "two.dxf", copies=2))
    plans = R.detect_plans(doc, R.detect_units(doc))
    assert sorted(p["name"] for p in plans) == ["PLANTA 1", "PLANTA 2"]
    assert all(p["size_m"] == [6.0, 4.0] for p in plans)


def test_layer_and_block_vocabulary_is_configurable_in_one_place():
    assert C.layer_role("a.secció") == "wall" and C.layer_role("A-WALL") == "wall"
    assert C.layer_role("B-Carpinterias") == "carpentry" and C.layer_role("A-GLAZ") == "window"
    assert C.layer_role("04_Cotas") == "ignored"
    assert C.furniture_kind(["llit 140"], 2.0) == "bed_double"
    assert C.furniture_kind(["CAMA_90"], 0.9) == "bed_single"
    assert C.furniture_kind(["WC suspendido"], 0.4) == "toilet"
    assert C.furniture_kind(["armari 38"], 0.5) == "wardrobe"
    assert C.furniture_kind(["A$C3183f432"], 0.4) is None
    assert C.hatch_finish("ANSI37") == "tile" and C.hatch_finish("ANSI31") is None


def test_run_rechecks_the_dwg_hash_and_format(tmp_path):
    from pipelines.common import sha256
    from pipelines.run import cad_source, source_check

    dwg_file = tmp_path / "source.dwg"
    dwg_file.write_bytes(b"AC1032 synthetic")
    source = {**SOURCE, "sha256": sha256(dwg_file)}
    draft, summary, _ = dwg.propose(build(tmp_path / "flat.dxf"), source, call_ai=False)
    geometry, issues = validate_draft(confirm(draft), {**raw_for(summary), "source": source}, "p")
    assert not issues
    source_check(geometry, {"source": cad_source(dwg_file)})
    dwg_file.write_bytes(b"AC1032 changed")
    with pytest.raises(ValueError, match="SHA-256"):
        source_check(geometry, {"source": cad_source(dwg_file)})
    dxf_file = tmp_path / "source.dxf"
    dxf_file.write_bytes(b"AC1032 synthetic")
    with pytest.raises(ValueError, match="format"):
        source_check(geometry, {"source": cad_source(dxf_file)})


def test_corner_wardrobe_backs_onto_its_long_side_not_the_wall_at_its_end(tmp_path):
    doc = ezdxf.new()
    doc.header["$INSUNITS"] = 4
    wardrobe = doc.blocks.new("ARMARIO_100")  # 0.5 × 1.0 m; insert convention: front local -y
    wardrobe.add_lwpolyline([(0, 0), (500, 0), (500, 1000), (0, 1000)], close=True)
    msp = doc.modelspace()
    for x0, y0, x1, y1 in __import__("dxf_fixture").WALLS:
        msp.add_lwpolyline(
            [(x0, y0), (x1, y0), (x1, y1), (x0, y1)], close=True, dxfattribs={"layer": "MUROS"}
        )
    # In the north-west corner: its local back (+y, a short end) and its long west side both
    # touch walls. A wardrobe stands on its long side, so it must face east.
    msp.add_blockref("ARMARIO_100", (200, 2800), dxfattribs={"layer": "MUEBLES"})
    msp.add_text("Dormitorio", dxfattribs={"insert": (1500, 1500), "height": 100})
    msp.add_text("Baño", dxfattribs={"insert": (4500, 1500), "height": 100})
    path = tmp_path / "corner.dxf"
    doc.saveas(path)
    draft, summary, _ = dwg.propose(path, SOURCE, call_ai=False)
    item = next(e for e in entities(draft, "furniture") if e["name"].startswith("wardrobe"))
    back, front = item["polygon"][:2], item["polygon"][2:]
    assert all(p[0] == pytest.approx(170) for p in back)  # west wall face x = 0.2 m
    assert all(p[0] == pytest.approx(220) for p in front)
    assert not summary["pending"]


def test_complex_wall_outlines_split_into_valid_convex_pieces():
    # An orthogonal outline like a real wall poché, with nanometre noise on its vertices.
    outline = Polygon(
        [
            (0, 0),
            (6, 0),
            (6, 4),
            (5.8, 4),
            (5.8, 0.2),
            (3.1, 0.2),
            (3.1, 1.0 + 1e-9),
            (3.0, 1.0),
            (3.0, 0.2),
            (0.2, 0.2),
            (0.2, 3.8),
            (2, 3.8),
            (2, 4),
            (0, 4),
        ]
    )
    pieces = [c for t in R.tidy(outline) for c in R.convex_pieces(t)]
    assert len(pieces) > 1
    assert all(p.is_valid and p.area > 0 and p.equals(p.convex_hull) for p in pieces)
    assert sum(p.area for p in pieces) == pytest.approx(outline.area, rel=1e-4)

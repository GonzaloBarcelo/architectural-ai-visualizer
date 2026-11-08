import math
from copy import deepcopy

import pymupdf
import pytest
from pydantic import ValidationError
from shapely.geometry import Polygon

from pipelines.geometry.normalize import ReviewRequired, normalize
from pipelines.geometry.schema import Geometry
from pipelines.pdf.extract import extract


def test_synthetic_extracts_actual_drawn_metric_geometry(geometry, parsed):
    assert parsed["pages"][0]["type"] == "vector"
    assert len(geometry.walls) == 6
    assert len(geometry.rooms) == 3
    assert sum(o.kind == "window" for o in geometry.openings) == 3
    assert sum(o.kind == "door" for o in geometry.openings) == 3
    assert Polygon(geometry.slabs[0].polygon).area == pytest.approx(70, abs=0.0001)
    assert geometry.walls[0].height == 2.8
    assert geometry.walls[0].thickness == 0.2
    assert geometry.transform.metres_per_point == pytest.approx(0.0254 / 72 * 50)
    assert len(geometry.source.sha256) == 64
    assert all(w.evidence.primitive is not None for w in geometry.walls)


def test_changed_calibration_blocks_metric_output(parsed):
    changed = deepcopy(parsed)
    a = next(a for a in changed["pages"][0]["annotations"] if "|measurement|" in a["content"])
    a["content"] = a["content"].replace("10.00", "12.00")
    with pytest.raises(ReviewRequired, match="Calibration conflicts"):
        normalize(changed, "bad-scale")


def test_annotation_without_drawn_evidence_is_rejected(parsed):
    changed = deepcopy(parsed)
    changed["pages"][0]["drawings"][0]["rect"][0] += 5
    with pytest.raises(ReviewRequired, match="drawn rectangle"):
        normalize(changed, "fabricated-annotation")


def test_scanned_pdf_produces_candidates_and_requires_review(tmp_path, parsed):
    source = pymupdf.open(tmp_path / "original.pdf")
    pix = source[0].get_pixmap()
    scan = pymupdf.open()
    page = scan.new_page(width=842, height=720)
    page.insert_image(page.rect, stream=pix.tobytes("png"))
    target = tmp_path / "scan.pdf"
    scan.save(target)
    source.close()
    scan.close()
    raw = extract(target, tmp_path / "scan-evidence")
    assert raw["pages"][0]["type"] == "scanned"
    assert raw["pages"][0]["raster_candidates"]
    with pytest.raises(ReviewRequired, match="require review"):
        normalize(raw, "scan")


@pytest.mark.parametrize(
    "mutation",
    [
        "negative_height",
        "self_intersecting",
        "unknown_wall",
        "outside_host",
        "duplicate_id",
        "scale_mismatch",
        "nan",
    ],
)
def test_invalid_geometry_cannot_enter_modeling(geometry, mutation):
    data = geometry.model_dump()
    if mutation == "negative_height":
        data["walls"][0]["height"] = -1
    elif mutation == "self_intersecting":
        data["walls"][0]["polygon"] = [(0, 0), (2, 2), (0, 2), (2, 0)]
    elif mutation == "unknown_wall":
        data["openings"][0]["wall_id"] = "absent"
    elif mutation == "outside_host":
        data["openings"][0]["polygon"] = [(30, 30), (31, 30), (31, 31), (30, 31)]
    elif mutation == "duplicate_id":
        data["walls"][1]["id"] = data["walls"][0]["id"]
    elif mutation == "scale_mismatch":
        data["measurements"][0]["value_m"] += 1
    elif mutation == "nan":
        data["walls"][0]["height"] = math.nan
    with pytest.raises(ValidationError):
        Geometry.model_validate(data)


def test_unverified_and_missing_geometry_stops_delivery(geometry):
    geometry.walls[0].evidence.status = "inferred"
    with pytest.raises(ValueError, match="Review required"):
        geometry.require_verified()
    geometry.walls[0].evidence.status = "verified"
    geometry.missing_information.append("Roof elevation not measured")
    with pytest.raises(ValueError, match="Roof elevation"):
        geometry.require_verified()

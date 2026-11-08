"""A reviewed web draft must provide actual measurements before modeling."""

from copy import deepcopy

import pytest
from shapely.geometry import Polygon

from pipelines.run import source_check
from pipelines.web.review import draft_from_extraction, validate_draft


def confirmed_draft(raw):
    draft = draft_from_extraction(raw, "web-test", "Reviewed pavilion")
    draft["calibration"]["confirmed"] = True
    draft["floor"]["confirmed"] = True
    for item in draft["entities"]:
        item["confirmed"] = True
    draft["complete"] = True
    return draft


def test_prepopulated_synthetic_draft_requires_explicit_review(parsed):
    draft = draft_from_extraction(parsed, "web-test", "Test pavilion")
    assert draft["entities"]
    assert not draft["complete"]
    assert not draft["calibration"]["confirmed"]
    assert not draft["floor"]["confirmed"]
    assert all(not item["confirmed"] for item in draft["entities"])
    geometry, issues = validate_draft(draft, parsed, "web-test")
    assert geometry is None
    assert issues


def test_confirmed_draft_preserves_metric_source_geometry(parsed):
    geometry, issues = validate_draft(confirmed_draft(parsed), parsed, "web-test")
    assert issues == []
    assert geometry is not None
    geometry.require_verified()
    source_check(geometry, parsed)
    assert Polygon(geometry.slabs[0].polygon).area == pytest.approx(70, abs=0.0001)
    assert len(geometry.walls) == 6
    assert len(geometry.openings) == 6
    assert len(geometry.rooms) == 3
    assert geometry.source.sha256 == parsed["source"]["sha256"]


def test_arbitrary_plan_does_not_invent_scale_height_or_semantics(parsed):
    raw = deepcopy(parsed)
    raw["synthetic_marker"] = False
    draft = draft_from_extraction(raw, "web-test", "Unrecognized plan")
    assert draft["entities"] == []
    assert draft["calibration"]["metres"] is None
    assert draft["floor"]["elevation"] is None
    geometry, issues = validate_draft(draft, raw, "web-test")
    assert geometry is None
    assert issues


@pytest.mark.parametrize(
    "mutation",
    [
        "missing_height",
        "unconfirmed_wall",
        "unconfirmed_scale",
        "missing_scale",
        "coincident_scale_points",
        "outside_page",
        "unknown_page",
        "duplicate_id",
        "unknown_host",
        "thickness_conflict",
        "incomplete_review",
        "self_intersection",
    ],
)
def test_invalid_or_unreviewed_draft_never_becomes_verified(parsed, mutation):
    draft = confirmed_draft(parsed)
    wall = next(item for item in draft["entities"] if item["kind"] == "wall")
    if mutation == "missing_height":
        wall["height"] = None
    elif mutation == "unconfirmed_wall":
        wall["confirmed"] = False
    elif mutation == "unconfirmed_scale":
        draft["calibration"]["confirmed"] = False
    elif mutation == "missing_scale":
        draft["calibration"]["metres"] = None
    elif mutation == "coincident_scale_points":
        draft["calibration"]["points"][1] = draft["calibration"]["points"][0]
    elif mutation == "outside_page":
        wall["polygon"][0] = [-100, -100]
    elif mutation == "unknown_page":
        draft["page"] = 999
    elif mutation == "duplicate_id":
        draft["entities"][1]["id"] = draft["entities"][0]["id"]
    elif mutation == "unknown_host":
        opening = next(i for i in draft["entities"] if i["kind"] == "door")
        opening["wall_id"] = "not-a-wall"
    elif mutation == "thickness_conflict":
        wall["thickness"] = 1.8
    elif mutation == "incomplete_review":
        draft["complete"] = False
    elif mutation == "self_intersection":
        wall["polygon"] = [[100, 100], [200, 200], [100, 200], [200, 100]]
    geometry, issues = validate_draft(draft, parsed, "web-test")
    assert geometry is None
    assert issues
    assert all(isinstance(i["path"], str) and i["message"] for i in issues)


def test_manual_review_of_unrecognized_plan_can_reach_geometry(parsed):
    # Reuse known source coordinates as if explicitly traced by the reviewer.
    manual = confirmed_draft(parsed)
    raw = deepcopy(parsed)
    raw["synthetic_marker"] = False
    geometry, issues = validate_draft(manual, raw, "manually-reviewed")
    assert issues == []
    assert geometry is not None
    assert geometry.synthetic is False
    source_check(geometry, raw)


def test_rooms_are_optional_and_never_invented(parsed):
    draft = confirmed_draft(parsed)
    draft["entities"] = [i for i in draft["entities"] if i["kind"] != "room"]
    geometry, issues = validate_draft(draft, parsed, "no-rooms")
    assert issues == []
    assert geometry is not None
    assert geometry.rooms == []

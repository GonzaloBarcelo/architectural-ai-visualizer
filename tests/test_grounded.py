import pytest

from pipelines.web.grounded import Selection, assemble, catalog
from pipelines.web.review import validate_draft


def fixture_raw():
    rects = [
        (20, 20, 30, 220),
        (210, 20, 220, 220),
        (30, 20, 210, 30),
        (30, 210, 90, 220),
        (130, 210, 210, 220),
    ]
    drawings = []
    for i, (x, y, z, w) in enumerate(rects):
        p = [[x, y], [z, y], [z, w], [x, w]]
        drawings.append(
            {
                "index": i,
                "fill": [0.2, 0.2, 0.2],
                "items": [["l", p[j], p[(j + 1) % 4]] for j in range(4)],
            }
        )
    return {
        "source": {"filename": "test.pdf", "sha256": "a" * 64, "page_count": 1},
        "pages": [
            {
                "page": 1,
                "size_points": [300, 300],
                "text": "Scale 1:50",
                "drawings": drawings,
                "text_blocks": [],
            }
        ],
    }


def test_grounded_selection_keeps_source_geometry_and_opening_hosts():
    raw = fixture_raw()
    factor, walls, gaps = catalog(raw)
    assert factor == pytest.approx(50 * 0.0254 / 72)
    gap = next(k for k, v in gaps.items() if v["shape"].bounds == (90, 210, 130, 220))
    selected = Selection(
        wall_ids=list(walls),
        openings=[{"candidate": gap, "kind": "window"}],
        furniture=[
            {"name": "Mesa", "kind": "table", "x": 110, "y": 110, "width": 0.8, "depth": 0.8}
        ],
        uncertainties=[],
    )
    draft = assemble(raw, selected, factor, walls, gaps)
    draft["complete"] = True
    draft["calibration"]["confirmed"] = True
    draft["floor"]["confirmed"] = True
    for e in draft["entities"]:
        e["confirmed"] = True
    geometry, issues = validate_draft(draft, raw, "test")
    assert not issues, issues
    assert len(geometry.openings) == 1
    assert len(geometry.furniture) == 1
    assert geometry.openings[0].sill == 0.9
    assert geometry.walls[-1].height - geometry.openings[0].sill - geometry.openings[
        0
    ].height == pytest.approx(0.6)
    assert geometry.rooms


def test_unknown_scale_is_not_invented():
    raw = fixture_raw()
    raw["pages"][0]["text"] = "No scale"
    with pytest.raises(ValueError, match="escala"):
        catalog(raw)


def test_model_cannot_invent_wall_identifier():
    raw = fixture_raw()
    factor, walls, gaps = catalog(raw)
    selection = Selection(wall_ids=["imaginary"], openings=[], furniture=[], uncertainties=[])
    with pytest.raises(ValueError, match="desconocido"):
        assemble(raw, selection, factor, walls, gaps)


def mock_client(selection, calls):
    from types import SimpleNamespace

    from pipelines.web.furniture import FurnitureSelection
    from pipelines.web.grounded import Review

    empty = FurnitureSelection(labels=[], extras=[], notes=[])
    answers = {
        "Selection": selection,
        "FurnitureSelection": empty,
        "Review": Review(furniture=empty, opening_changes=[], findings=["Sin cambios"]),
    }

    def parse(**kwargs):
        calls.append(kwargs)
        value = answers[kwargs["text_format"].__name__]
        return SimpleNamespace(output_parsed=value, id=f"resp-{len(calls)}", usage=None)

    return SimpleNamespace(responses=SimpleNamespace(parse=parse))


def test_selection_is_cached_by_pdf_and_reassembled_without_new_calls(tmp_path, monkeypatch):
    import pymupdf

    from pipelines.web.grounded import propose

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    raw = fixture_raw()
    _, walls, _ = catalog(raw)
    folder = tmp_path / "project"
    folder.mkdir()
    path = folder / "source.pdf"
    with pymupdf.open() as document:
        document.new_page(width=300, height=300)
        document.save(path)
    selection = Selection(wall_ids=list(walls), openings=[], furniture=[], uncertainties=[])
    calls = []
    draft, usage = propose(path, raw, mock_client(selection, calls), cache_dir=tmp_path / "cache")
    # Walls/openings, furniture and self-review: three billed calls, none stored.
    assert [c["text_format"].__name__ for c in calls] == [
        "Selection",
        "FurnitureSelection",
        "Review",
    ]
    assert all(c["store"] is False for c in calls)
    assert any("Sin cambios" in a for a in draft["assumptions"])
    assert not usage["cache_hit"] and draft["conceptual"]
    other = tmp_path / "other"
    other.mkdir()
    (other / "source.pdf").write_bytes(path.read_bytes())
    # Same PDF digest in another project: no key, no client, no API call.
    again, usage = propose(other / "source.pdf", raw, cache_dir=tmp_path / "cache")
    assert usage["cache_hit"] and again["entities"] == draft["entities"]


def test_furniture_collisions_are_omitted_not_fatal_and_chairs_may_tuck_under_tables():
    raw = fixture_raw()
    factor, walls, gaps = catalog(raw)
    furniture = [
        {"name": "Mesa", "kind": "table", "x": 120, "y": 110, "width": 1.2, "depth": 0.8},
        {"name": "Silla", "kind": "chair", "x": 120, "y": 120, "width": 0.45, "depth": 0.45},
        {"name": "Sofá", "kind": "sofa", "x": 120, "y": 110, "width": 1.8, "depth": 0.9},
        {"name": "Fuera", "kind": "bed", "x": 5, "y": 5, "width": 1.5, "depth": 2},
    ]
    selection = Selection(wall_ids=list(walls), openings=[], furniture=furniture, uncertainties=[])
    draft = assemble(raw, selection, factor, walls, gaps)
    names = [e["name"] for e in draft["entities"] if e["kind"] == "furniture"]
    assert names == ["dining_table / Mesa", "chair / Silla"]
    omitted = [a for a in draft["assumptions"] if a.startswith("Mueble omitido")]
    assert len(omitted) == 2


def test_rooms_are_named_from_plan_text():
    raw = fixture_raw()
    raw["pages"][0]["text_blocks"] = [[90, 100, 150, 120, "Salón - Cocina\nSup. 26.43 m2", 0, 0]]
    factor, walls, gaps = catalog(raw)
    selection = Selection(wall_ids=list(walls), openings=[], furniture=[], uncertainties=[])
    draft = assemble(raw, selection, factor, walls, gaps)
    rooms = [e for e in draft["entities"] if e["kind"] == "room"]
    assert rooms and rooms[0]["name"] == "Salón - Cocina"

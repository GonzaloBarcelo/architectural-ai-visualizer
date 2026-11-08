import json

import pymupdf as fitz

from pipelines.pdf.extract import coords, extract


def test_nested_quad_points_preserve_coordinates():
    quad = fitz.Quad((1, 2), (5, 2), (1, 6), (5, 6))
    value = coords({"items": [("qu", quad)], "vertices": [fitz.Point(2, 3)]})
    assert json.loads(json.dumps(value))["items"][0][1] == [[1, 2], [5, 2], [1, 6], [5, 6]]
    assert value["vertices"] == [[2, 3]]


def test_vector_quad_pdf_extraction_is_json_serializable(tmp_path):
    source = tmp_path / "quad.pdf"
    with fitz.open() as doc:
        page = doc.new_page()
        page.draw_quad(fitz.Quad((50, 50), (150, 55), (55, 150), (155, 155)))
        doc.save(source)
    output = tmp_path / "evidence"
    raw = extract(source, output)
    assert any(
        item[0] == "qu" for drawing in raw["pages"][0]["drawings"] for item in drawing["items"]
    )
    assert json.loads((output / "extraction.json").read_text()) == json.loads(json.dumps(raw))

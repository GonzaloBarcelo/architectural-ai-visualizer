from types import SimpleNamespace

import pytest

from pipelines.web.ai import AIPlan, propose
from pipelines.web.review import draft_from_extraction, validate_draft


def test_ai_draft_is_inferred_until_explicit_concept_acceptance(parsed, tmp_path):
    draft = draft_from_extraction(parsed, "ai-test", "Test")
    entities = []
    for item in draft["entities"]:
        entities.append(
            {
                key: item.get(key)
                for key in [
                    "id",
                    "kind",
                    "height",
                    "thickness",
                    "elevation",
                    "sill",
                    "wall_id",
                    "name",
                ]
            }
            | {"polygon": [{"x": x, "y": y} for x, y in item["polygon"]]}
        )
    points = draft["calibration"]["points"]
    plan = AIPlan(
        title="Concept",
        page=1,
        scale_start={"x": points[0][0], "y": points[0][1]},
        scale_end={"x": points[1][0], "y": points[1][1]},
        scale_metres=draft["calibration"]["metres"],
        floor_elevation=0,
        assumptions=["Altura conceptual"],
        entities=entities,
    )
    calls = []

    def parse(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(output_parsed=plan, id="mock-response", usage=None)

    path = tmp_path / "input.pdf"
    path.write_bytes(b"%PDF-test")
    value, usage = propose(
        path, parsed, client=SimpleNamespace(responses=SimpleNamespace(parse=parse))
    )
    assert calls[0]["store"] is False
    assert calls[0]["max_output_tokens"] == 16000
    assert value["conceptual"] and not value["complete"]
    assert validate_draft(value, parsed, "ai-test")[0] is None
    value["complete"] = True
    value["floor"]["confirmed"] = True
    value["calibration"]["confirmed"] = True
    for e in value["entities"]:
        e["confirmed"] = True
    geometry, issues = validate_draft(value, parsed, "ai-test")
    assert not issues, issues
    assert geometry.conceptual and geometry.walls[0].evidence.status == "inferred"
    geometry.require_verified()
    geometry.conceptual = False
    with pytest.raises(ValueError):
        geometry.require_verified()
    assert usage["response_id"] == "mock-response"


def test_ai_without_key_never_sends_pdf(monkeypatch, tmp_path):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        propose(tmp_path / "absent.pdf", {})

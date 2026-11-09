"""The single OpenAI call for DWG doubts, with a mock client keyed by text_format."""

import json
from types import SimpleNamespace

from dxf_fixture import build

from pipelines.web import dwg

SOURCE = {
    "filename": "flat.dwg",
    "sha256": "c" * 64,
    "page_count": 1,
    "format": "dwg",
    "converter": "Test converter 1.0",
}


def mock_client(answers, calls, fail=False):
    def parse(**kwargs):
        calls.append(kwargs)
        if fail:
            raise ConnectionError("network down")
        value = answers[kwargs["text_format"].__name__]
        usage = SimpleNamespace(
            model_dump=lambda: {
                "input_tokens": 3000,
                "output_tokens": 1200,
                "output_tokens_details": {"reasoning_tokens": 900},
                "input_tokens_details": {"cached_tokens": 0},
            }
        )
        return SimpleNamespace(output_parsed=value, id=f"resp-{len(calls)}", usage=usage)

    return SimpleNamespace(responses=SimpleNamespace(parse=parse))


def resolution(item_id, kind="washing_machine"):
    return dwg.Resolution(
        furniture=[
            dwg.FurnitureAnswer(id=item_id, kind=kind, name="Lavadora", front="left"),
            dwg.FurnitureAnswer(id="Bnot-an-item", kind="sofa", name="Inventado", front="up"),
        ],
        fronts=[],
        openings=[],
        orphans=[],
        rooms=[],
        layers=[],
        hatches=[],
        notes=["Bloque cuadrado con tambor: lavadora."],
    )


def unknown_id(path):
    from pipelines.cad import read as R

    doc = R.load(path)
    units = R.detect_units(doc)
    payload = dwg.doubts(R.read_plan(doc, R.detect_plans(doc, units)[0], units))
    return payload["items"][0]["id"]


def test_no_doubts_make_no_call(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    calls = []
    _draft, summary, ai = dwg.propose(
        build(tmp_path / "flat.dxf"),
        SOURCE,
        cache_dir=tmp_path / "cache",
        audit_dir=tmp_path / "audit",
        client=mock_client({}, calls),
    )
    assert calls == [] and not ai["called"] and ai["error"] is None
    assert summary["doubts"] == [] and summary["pending"] == []
    assert summary["ai"]["usage"]["cost_usd"] == 0


def test_one_medium_call_answers_by_id_and_is_inferred(tmp_path):
    path = build(tmp_path / "flat.dxf", unknown=True)
    item = unknown_id(path)
    calls = []
    draft, summary, _ai = dwg.propose(
        path,
        SOURCE,
        cache_dir=tmp_path / "cache",
        audit_dir=tmp_path / "audit",
        client=mock_client({"Resolution": resolution(item)}, calls),
    )
    assert len(calls) == 1
    call = calls[0]
    assert call["store"] is False and call["reasoning"] == {"effort": "medium"}
    assert call["text_format"] is dwg.Resolution
    payload = json.loads(call["input"][0]["content"][0]["text"])
    assert [i["id"] for i in payload["items"]] == [item]
    assert all(c["type"] == "input_text" for c in call["input"][0]["content"])  # no image
    machine = [e for e in draft["entities"] if e["name"] == "washing_machine / Lavadora"]
    assert len(machine) == 1 and machine[0]["cad"]["reading"] == "inferred"
    # Geometry comes from the block, never from the model.
    xs = sorted(p[0] for p in machine[0]["polygon"])
    assert xs[0] == 650 and xs[-1] == 710
    assert not any("Inventado" in (e.get("name") or "") for e in draft["entities"])
    assert summary["counts"]["furniture"]["inferred"] == 1 and not summary["pending"]
    usage = summary["ai"]["usage"]
    assert usage == {
        "input": 3000,
        "output": 1200,
        "reasoning": 900,
        "cached_input": 0,
        "cost_usd": 0.0255,
    }
    assert list((tmp_path / "audit").glob("doubts-resp-1.json"))


def test_cache_hit_makes_no_second_call(tmp_path):
    path = build(tmp_path / "flat.dxf", unknown=True)
    item = unknown_id(path)
    calls = []
    client = mock_client({"Resolution": resolution(item)}, calls)
    first, _, _ = dwg.propose(
        path, SOURCE, cache_dir=tmp_path / "cache", audit_dir=tmp_path / "a", client=client
    )
    again, _summary, ai = dwg.propose(
        path, SOURCE, cache_dir=tmp_path / "cache", audit_dir=tmp_path / "a", client=client
    )
    assert len(calls) == 1
    assert ai["cache_hit"] and not ai["called"]
    assert again["entities"] == first["entities"]


def test_ai_failure_keeps_the_reading_and_leaves_doubts_to_the_user(tmp_path):
    path = build(tmp_path / "flat.dxf", unknown=True)
    calls = []
    draft, summary, ai = dwg.propose(
        path,
        SOURCE,
        cache_dir=tmp_path / "cache",
        audit_dir=tmp_path / "audit",
        client=mock_client({}, calls, fail=True),
    )
    assert len(calls) == 1 and "ConnectionError" in ai["error"]
    assert [p["type"] for p in summary["pending"]] == ["furniture"]
    assert summary["pending"][0]["blocking"]
    assert {e["kind"] for e in draft["entities"]} >= {"wall", "door", "window", "room", "furniture"}
    assert summary["counts"]["furniture"]["missing"] == 1


def test_missing_key_is_not_fatal(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    _draft, summary, ai = dwg.propose(build(tmp_path / "flat.dxf", unknown=True), SOURCE)
    assert "OPENAI_API_KEY" in ai["error"] and summary["pending"]


def test_user_answers_resolve_pending_items_without_a_call(tmp_path):
    path = build(tmp_path / "flat.dxf", unknown=True)
    item = unknown_id(path)
    stored = {
        "model": "x",
        "called": False,
        "cache_hit": False,
        "error": "sin clave",
        "image": False,
        "resolution": None,
        "usage": dwg.usage_summary(None),
    }
    answers = {
        "furniture": [{"id": item, "kind": "not_furniture", "name": "Símbolo", "front": "any"}]
    }
    _draft, summary, _ = dwg.propose(
        path, SOURCE, user_answers=answers, stored_ai=stored, call_ai=False
    )
    assert not summary["pending"]
    assert any(i["status"] == "user" for i in summary["items"])


def test_optional_labelled_image_is_attached_when_enabled(tmp_path):
    path = build(tmp_path / "flat.dxf", unknown=True)
    item = unknown_id(path)
    calls = []
    dwg.propose(
        path,
        SOURCE,
        cache_dir=tmp_path / "cache",
        audit_dir=tmp_path / "audit",
        client=mock_client({"Resolution": resolution(item)}, calls),
        image=True,
    )
    parts = calls[0]["input"][0]["content"]
    assert [p["type"] for p in parts] == ["input_text", "input_image"]
    assert parts[1]["image_url"].startswith("data:image/png;base64,")

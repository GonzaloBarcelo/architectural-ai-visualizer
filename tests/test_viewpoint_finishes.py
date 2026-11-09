import math

import pytest

from pipelines.blender.viewpoint import best_view, inside, ray
from pipelines.geometry.schema import Finish
from pipelines.web.materials import Palette, propose_finishes, srgb_to_linear, to_finishes


def rect(x0, y0, x1, y1):
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


def test_interior_view_looks_down_the_long_axis_from_inside_the_room():
    room = rect(0, 0, 8, 3)
    walls = [
        rect(-0.2, -0.2, 8.2, 0),
        rect(-0.2, 3, 8.2, 3.2),
        rect(-0.2, 0, 0, 3),
        rect(8, 0, 8.2, 3),
    ]
    (x, y), angle = best_view([room], walls)
    assert inside((x, y), room)
    # Most open direction is along x, not into the near long walls.
    assert abs(math.cos(angle)) > 0.9
    assert ray((x, y), angle, [(a, b) for w in walls for a, b in zip(w, w[1:] + w[:1])]) > 4


def test_viewpoint_keeps_clear_of_furniture():
    room = rect(0, 0, 6, 6)
    sofa = rect(0, 0, 3, 3)
    (x, y), _ = best_view([room], [], [sofa])
    assert not inside((x, y), sofa)


def test_palette_converts_srgb_hex_to_linear_and_validates():
    palette = Palette(
        finishes=[
            {"surface": "floor", "name": "Roble", "hex_srgb": "#808080", "roughness": 0.5},
            {"surface": "walls", "name": "Mal", "hex_srgb": "verde", "roughness": 0.5},
            {"surface": "doors", "name": "Lacado", "hex_srgb": "ffffff", "roughness": 3},
        ],
        notes=[],
    )
    finishes = to_finishes(palette)
    assert set(finishes) == {"floor", "doors"}
    assert finishes["floor"]["color"][0] == pytest.approx(srgb_to_linear(128 / 255), abs=1e-4)
    assert finishes["doors"]["roughness"] == 1
    with pytest.raises(ValueError):
        Finish(name="x", color=(2, 0, 0), roughness=0.5)


def test_empty_description_never_calls_api_and_finishes_are_cached(tmp_path, monkeypatch):
    from types import SimpleNamespace

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert propose_finishes("  ", tmp_path) == ({}, [], None)
    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        propose_finishes("Paredes blancas", tmp_path)
    calls = []
    palette = Palette(
        finishes=[{"surface": "walls", "name": "Blanco", "hex_srgb": "#f4f1ea", "roughness": 0.8}],
        notes=["Sin textura"],
    )

    def parse(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(output_parsed=palette, usage=None)

    client = SimpleNamespace(responses=SimpleNamespace(parse=parse))
    finishes, _notes, _ = propose_finishes("Paredes blancas", tmp_path, client)
    assert calls[0]["store"] is False and finishes["walls"]["name"] == "Blanco"
    cached = propose_finishes("Paredes blancas", tmp_path)
    assert cached[0] == finishes and cached[2]["cache_hit"] and len(calls) == 1

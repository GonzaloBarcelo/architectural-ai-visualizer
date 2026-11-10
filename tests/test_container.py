"""Settings the Docker image relies on: baked revision, missing Git and render quality."""

import subprocess

from pipelines import common
from pipelines.web.server import render_setting


def test_baked_revision_wins_and_missing_git_never_crashes(monkeypatch):
    monkeypatch.setenv("AAV_REVISION", "abc1234")
    assert common.revision() == {"commit": "abc1234", "dirty": False}

    def no_git(*args, **kwargs):
        raise FileNotFoundError("git")

    monkeypatch.delenv("AAV_REVISION")
    monkeypatch.setattr(subprocess, "run", no_git)
    assert common.revision() == {"commit": "unknown", "dirty": False}


def test_render_quality_comes_from_the_environment_and_is_clamped(monkeypatch):
    monkeypatch.delenv("AAV_RENDER_SAMPLES", raising=False)
    assert render_setting("AAV_RENDER_SAMPLES", 160, 8, 4096) == 160
    monkeypatch.setenv("AAV_RENDER_SAMPLES", "64")
    assert render_setting("AAV_RENDER_SAMPLES", 160, 8, 4096) == 64
    monkeypatch.setenv("AAV_RENDER_SAMPLES", "1")
    assert render_setting("AAV_RENDER_SAMPLES", 160, 8, 4096) == 8
    monkeypatch.setenv("AAV_RENDER_SAMPLES", "lots")
    assert render_setting("AAV_RENDER_SAMPLES", 160, 8, 4096) == 160


def test_each_ai_purpose_has_its_own_model_setting(monkeypatch):
    for variable, _ in common.MODELS.values():
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    assert common.model_for("plan") == "gpt-5.4"
    assert common.model_for("vision") == "gpt-4.1"
    monkeypatch.setenv("OPENAI_MODEL", "shared-model")
    assert common.model_for("dwg") == "shared-model"
    monkeypatch.setenv("OPENAI_DWG_MODEL", "dwg-model")
    assert common.model_for("dwg") == "dwg-model"
    assert common.model_for("materials") == "shared-model"

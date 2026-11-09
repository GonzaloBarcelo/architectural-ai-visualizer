"""Local API review gates, job isolation and failure recovery (no Blender subprocesses)."""

import json
import time
from pathlib import Path
from threading import Event

import pytest
from fastapi.testclient import TestClient

from pipelines.common import write_json
from pipelines.pdf.synthetic import create
from pipelines.web.server import create_app

BASE_URL = "http://127.0.0.1:5174"


def wait_project(client, project_id, states=("review", "failed", "succeeded")):
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        response = client.get(f"/api/projects/{project_id}")
        assert response.status_code == 200, response.text
        result = response.json()
        if result["status"] in states:
            return result
        time.sleep(0.01)
    pytest.fail(f"Project did not reach {states}: {result}")


def upload(client, path, filename="drawing.pdf"):
    response = client.post(
        "/api/projects", files={"file": (filename, path.read_bytes(), "application/pdf")}
    )
    assert response.status_code in (201, 202), response.text
    return wait_project(client, response.json()["id"], ("review", "failed"))


def confirm(project):
    draft = project["draft"]
    draft["calibration"]["confirmed"] = True
    draft["floor"]["confirmed"] = True
    for item in draft["entities"]:
        item["confirmed"] = True
    draft["complete"] = True
    return draft


def approve(client, project):
    response = client.put(
        f"/api/projects/{project['id']}/draft",
        json={"draft": confirm(project), "revision": project["revision"]},
    )
    assert response.status_code == 200, response.text
    return response.json()


def successful_runner(args):
    """Only replace expensive rendering; exercise real uploads, drafts and job worker."""
    if getattr(args, "progress", None):
        args.progress("test-rendering")
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    write_json(
        out / "manifest.json",
        {
            "project_id": out.name,
            "title": "Reviewed",
            "synthetic": True,
            "units": "m",
            "model_url": "model.glb",
            "renders": [],
            "floors": [],
            "quality": {"passed": True},
        },
    )
    write_json(out / "run-status.json", {"passed": True})
    (out / "model.glb").write_bytes(b"test-GLB-not-for-browser")
    return out


@pytest.fixture
def pdf(tmp_path):
    return create(tmp_path / "upload.pdf")


@pytest.fixture
def setup_paths(tmp_path):
    data = tmp_path / "private-projects"
    site = tmp_path / "site"
    (site / "dist").mkdir(parents=True)
    (site / "dist/index.html").write_text("<html>local</html>")
    return data, site


@pytest.fixture
def client(setup_paths):
    data, site = setup_paths
    with TestClient(
        create_app(data, site, pipeline_runner=successful_runner), base_url=BASE_URL
    ) as c:
        yield c


def test_upload_review_validation_generation_and_result(client, pdf):
    project = upload(client, pdf)
    assert project["status"] == "review"
    assert project["issues"]
    assert project["pages"]
    assert client.get(project["pages"][0]["image_url"]).status_code == 200
    route = f"/api/projects/{project['id']}"
    assert (
        client.post(route + "/generate", json={"revision": project["revision"]}).status_code == 422
    )
    approved = approve(client, project)
    assert approved["revision"] > project["revision"]
    validation = client.post(route + "/validate", json={"revision": approved["revision"]})
    assert validation.status_code == 200, validation.text
    assert validation.json()["issues"] == []
    response = client.post(route + "/generate", json={"revision": approved["revision"]})
    assert response.status_code == 202, response.text
    finished = wait_project(client, project["id"], ("succeeded", "failed"))
    assert finished["status"] == "succeeded", finished.get("error")
    assert client.get(finished["manifest_url"]).status_code == 200
    listing = client.get("/api/projects").json()["projects"]
    assert project["id"] in {item["id"] for item in listing}


def test_old_revision_cannot_overwrite_draft_or_generate(client, pdf):
    project = upload(client, pdf)
    approved = approve(client, project)
    route = f"/api/projects/{project['id']}"
    assert (
        client.put(
            route + "/draft", json={"draft": approved["draft"], "revision": project["revision"]}
        ).status_code
        == 409
    )
    assert (
        client.post(route + "/generate", json={"revision": project["revision"]}).status_code == 409
    )
    draft = approved["draft"]
    next(item for item in draft["entities"] if item["kind"] == "wall")["confirmed"] = False
    updated = client.put(route + "/draft", json={"draft": draft, "revision": approved["revision"]})
    assert updated.status_code == 200
    assert (
        client.post(route + "/generate", json={"revision": updated.json()["revision"]}).status_code
        == 422
    )


def test_running_job_prevents_edits_and_duplicate_generation(setup_paths, pdf):
    started, release = Event(), Event()
    captured = []

    def blocked_runner(args):
        captured.append(Path(args.geometry).read_text())
        started.set()
        assert release.wait(5), "test worker was never released"
        assert Path(args.geometry).read_text() == captured[0]
        return successful_runner(args)

    data, site = setup_paths
    with TestClient(create_app(data, site, pipeline_runner=blocked_runner), base_url=BASE_URL) as c:
        project = approve(c, upload(c, pdf))
        route = f"/api/projects/{project['id']}"
        try:
            assert (
                c.post(route + "/generate", json={"revision": project["revision"]}).status_code
                == 202
            )
            assert started.wait(5)
            assert (
                c.post(route + "/generate", json={"revision": project["revision"]}).status_code
                == 409
            )
            assert (
                c.put(
                    route + "/draft",
                    json={"draft": project["draft"], "revision": project["revision"]},
                ).status_code
                == 409
            )
        finally:
            release.set()
        assert wait_project(c, project["id"], ("succeeded", "failed"))["status"] == "succeeded"


def test_failed_render_is_actionable_and_can_be_retried(setup_paths, pdf):
    attempts = []

    def flaky_runner(args):
        attempts.append(1)
        if len(attempts) == 1:
            raise RuntimeError("Renderer unavailable for test")
        return successful_runner(args)

    data, site = setup_paths
    with TestClient(create_app(data, site, pipeline_runner=flaky_runner), base_url=BASE_URL) as c:
        project = approve(c, upload(c, pdf))
        route = f"/api/projects/{project['id']}"
        assert (
            c.post(route + "/generate", json={"revision": project["revision"]}).status_code == 202
        )
        failed = wait_project(c, project["id"], ("failed",))
        assert "Renderer unavailable" in failed["error"]
        assert not failed.get("manifest_url")
        assert c.post(route + "/generate", json={"revision": failed["revision"]}).status_code == 202
        assert wait_project(c, project["id"], ("succeeded", "failed"))["status"] == "succeeded"
        assert len(attempts) == 2


def test_cross_origin_and_rebinding_requests_are_rejected(client, pdf):
    hostile = client.post(
        "/api/projects",
        files={"file": ("plan.pdf", pdf.read_bytes(), "application/pdf")},
        headers={"Origin": "https://untrusted.example"},
    )
    assert hostile.status_code == 403
    assert client.get("/api/projects", headers={"Host": "attacker.example"}).status_code in (
        400,
        403,
    )
    allowed = client.get("/api/projects", headers={"Origin": BASE_URL})
    assert allowed.status_code == 200


def test_private_file_allowlist_and_upload_filename_do_not_escape_storage(client, pdf, setup_paths):
    project = upload(client, pdf, "../../outside.pdf")
    data, _ = setup_paths
    assert not (data.parent / "outside.pdf").exists()
    assert "/" not in project["filename"]
    assert client.get(f"/api/projects/{project['id']}/files/state.json").status_code == 404
    assert (
        client.get(f"/api/projects/{project['id']}/files/../../pyproject.toml").status_code == 404
    )
    assert client.get("/api/projects/not-a-project").status_code == 404


def test_corrupt_pdf_never_enters_review_or_generation(client):
    response = client.post(
        "/api/projects", files={"file": ("broken.pdf", b"%PDF-1.4\ncorrupt", "application/pdf")}
    )
    if response.status_code in (201, 202):
        project = wait_project(client, response.json()["id"], ("failed",))
        assert project["error"]
        assert (
            client.post(
                f"/api/projects/{project['id']}/validate", json={"revision": project["revision"]}
            ).status_code
            == 409
        )
    else:
        assert response.status_code in (400, 415, 422)


def test_saved_review_survives_server_restart(setup_paths, pdf):
    data, site = setup_paths
    with TestClient(
        create_app(data, site, pipeline_runner=successful_runner), base_url=BASE_URL
    ) as c:
        saved = approve(c, upload(c, pdf))
    with TestClient(
        create_app(data, site, pipeline_runner=successful_runner), base_url=BASE_URL
    ) as c:
        restored = c.get(f"/api/projects/{saved['id']}").json()
        assert restored["revision"] == saved["revision"]
        assert restored["draft"] == saved["draft"]
        assert restored["status"] == "review"


def test_result_is_invalidated_by_edits_and_each_run_has_a_distinct_url(client, pdf):
    approved = approve(client, upload(client, pdf))
    route = f"/api/projects/{approved['id']}"
    client.post(route + "/generate", json={"revision": approved["revision"]})
    first = wait_project(client, approved["id"], ("succeeded",))
    client.post(route + "/generate", json={"revision": approved["revision"]})
    second = wait_project(client, approved["id"], ("succeeded",))
    assert first["manifest_url"] != second["manifest_url"]
    assert first["result"] != second["result"]
    draft = second["draft"]
    draft["complete"] = False
    saved = client.put(route + "/draft", json={"revision": second["revision"], "draft": draft})
    assert saved.status_code == 200
    assert not saved.json().get("manifest_url")
    assert client.get(second["manifest_url"]).status_code == 404
    assert client.get(route + "/files/model.glb").status_code == 404


def test_interrupted_job_is_recoverable_on_restart(setup_paths, pdf):
    data, site = setup_paths
    with TestClient(
        create_app(data, site, pipeline_runner=successful_runner), base_url=BASE_URL
    ) as c:
        project = approve(c, upload(c, pdf))
        c.app.state.projects.update(project["id"], status="running", stage="rendering")
    with TestClient(
        create_app(data, site, pipeline_runner=successful_runner), base_url=BASE_URL
    ) as c:
        route = f"/api/projects/{project['id']}"
        recovered = c.get(route).json()
        assert recovered["status"] == "failed"
        assert recovered["stage"] == "interrupted"
        assert recovered["draft"] == project["draft"]
        assert (
            c.post(route + "/generate", json={"revision": recovered["revision"]}).status_code == 202
        )
        assert wait_project(c, project["id"], ("succeeded",))["status"] == "succeeded"


def test_interrupted_enhancement_rerun_keeps_the_delivered_renders(setup_paths, pdf):
    data, site = setup_paths
    with TestClient(
        create_app(data, site, pipeline_runner=successful_runner), base_url=BASE_URL
    ) as c:
        project = approve(c, upload(c, pdf))
        route = f"/api/projects/{project['id']}"
        assert (
            c.post(route + "/generate", json={"revision": project["revision"]}).status_code == 202
        )
        wait_project(c, project["id"], ("succeeded",))
        c.app.state.projects.update(project["id"], status="running", stage="enhancing")
    with TestClient(
        create_app(data, site, pipeline_runner=successful_runner), base_url=BASE_URL
    ) as c:
        recovered = c.get(route).json()
        assert recovered["status"] == "succeeded" and recovered["stage"] == "completed"
        assert "interrumpió" in recovered["error"]
        assert c.get(route + "/files/model.glb").status_code == 200


def ai_draft(raw):
    from pipelines.web.review import draft_from_extraction

    draft = draft_from_extraction(raw, "test", "Concept")
    draft.update(conceptual=True, assumptions=["Test assumption"])
    return draft


def test_upload_with_description_interprets_applies_finishes_and_approves(
    tmp_path, pdf, monkeypatch
):
    calls, finish_calls = [], []

    def fake_propose(path, raw, cache_dir=None, progress=None):
        calls.append(cache_dir)
        progress("furniture")
        state = json.loads((path.parent / "project.json").read_text())
        assert state["stage"] == "interpreting"
        assert state["activity"]["step"] == 2 and state["activity"]["total"] == 3
        assert state["stage_since"]["stage"] == "interpreting"
        return ai_draft(raw), {"model": "test", "usage": {"total_tokens": 10}}

    def fake_finishes(description, cache_dir):
        finish_calls.append(description)
        finish = {"name": "Roble", "color": (0.3, 0.2, 0.1), "roughness": 0.5}
        return {"floor": finish}, ["Textura no modelada"], {"total_tokens": 3}

    monkeypatch.setattr("pipelines.web.server.propose", fake_propose)
    monkeypatch.setattr("pipelines.web.server.propose_finishes", fake_finishes)
    with TestClient(
        create_app(tmp_path / "projects", tmp_path / "site", successful_runner), base_url=BASE_URL
    ) as client:
        response = client.post(
            "/api/projects",
            files={"file": ("plan.pdf", pdf.read_bytes(), "application/pdf")},
            data={"description": "  Suelo de roble natural  "},
        )
        assert response.status_code == 202, response.text
        project = wait_project(client, response.json()["id"], ("review", "failed"))
        deadline = time.monotonic() + 5
        while project["stage"] != "review" or "finishes" not in (project.get("ai_usage") or {}):
            assert time.monotonic() < deadline, project
            time.sleep(0.01)
            project = client.get(f"/api/projects/{project['id']}").json()
        assert project["description"] == "Suelo de roble natural"
        assert finish_calls == ["Suelo de roble natural"]
        assert calls and calls[0].name == "ai-cache"
        assert project["draft"]["finishes"]["floor"]["name"] == "Roble"
        assert project["ai_interpretation"]["assumptions"] == ["Test assumption"]
        assert any("roble" in a for a in project["draft"]["assumptions"])
        stale = client.post(
            f"/api/projects/{project['id']}/approve", json={"revision": project["revision"] - 1}
        )
        assert stale.status_code == 409
        approved = client.post(
            f"/api/projects/{project['id']}/approve", json={"revision": project["revision"]}
        )
        assert approved.status_code == 202, approved.text
        done = wait_project(client, project["id"], ("succeeded", "failed"))
        assert done["status"] == "succeeded", done
        assert done["draft"]["complete"] and all(e["confirmed"] for e in done["draft"]["entities"])
        assert client.get(done["manifest_url"]).status_code == 200


def test_approve_requires_ai_interpretation_and_coherent_geometry(tmp_path, pdf, monkeypatch):
    monkeypatch.setattr(
        "pipelines.web.server.propose", lambda *a, **k: (_ for _ in ()).throw(ValueError("x"))
    )
    with TestClient(
        create_app(tmp_path / "projects", tmp_path / "site", successful_runner), base_url=BASE_URL
    ) as client:
        project = upload(client, pdf)
        assert "OpenAI" in project["error"]
        response = client.post(
            f"/api/projects/{project['id']}/approve", json={"revision": project["revision"]}
        )
        assert response.status_code == 409


def test_missing_key_reports_actionable_error(tmp_path, pdf, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(
        "pipelines.web.server.propose",
        lambda *a, **k: (_ for _ in ()).throw(ValueError("OPENAI_API_KEY missing")),
    )
    with TestClient(
        create_app(tmp_path / "projects", tmp_path / "site", successful_runner), base_url=BASE_URL
    ) as client:
        project = upload(client, pdf)
        assert project["status"] == "review"
        assert "OPENAI_API_KEY" in project["error"]


def test_description_is_length_limited(client, pdf):
    response = client.post(
        "/api/projects",
        files={"file": ("plan.pdf", pdf.read_bytes(), "application/pdf")},
        data={"description": "x" * 1001},
    )
    assert response.status_code == 422


def test_html_is_never_cached_but_assets_may_be(setup_paths):
    data, site = setup_paths
    (site / "dist/assets").mkdir()
    (site / "dist/assets/Viewer-abc123.js").write_text("export default 1")
    with TestClient(
        create_app(data, site, pipeline_runner=successful_runner), base_url=BASE_URL
    ) as c:
        page = c.get("/")
        assert page.status_code == 200 and page.headers["cache-control"] == "no-cache"
        chunk = c.get("/assets/Viewer-abc123.js")
        assert chunk.status_code == 200 and "cache-control" not in chunk.headers

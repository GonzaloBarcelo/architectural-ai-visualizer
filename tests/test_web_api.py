"""Local API review gates, job isolation and failure recovery (no Blender subprocesses)."""

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

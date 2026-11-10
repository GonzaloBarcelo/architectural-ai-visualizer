"""DWG upload → review → answers → approve → generation, with the converter mocked."""

import json
import shutil
from pathlib import Path

import pytest
from dxf_fixture import build
from fastapi.testclient import TestClient
from test_web_api import BASE_URL, successful_runner, wait_project

from pipelines.cad.convert import MISSING, ConverterMissing
from pipelines.geometry.schema import Geometry
from pipelines.web import server

FAKE_DWG = b"AC1032" + b"\0" * 2048  # content only has to look like a DWG; conversion is mocked


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    data, site = tmp_path / "projects", tmp_path / "site"
    (site / "dist").mkdir(parents=True)
    (site / "dist/index.html").write_text("<html>local</html>")
    runs = []

    def runner(args):
        runs.append(args)
        return successful_runner(args)

    def factory(fixture):
        def fake_convert(dwg, output_dir, converter=None, timeout=300):
            assert Path(dwg).name == "source.dwg"
            target = Path(output_dir) / "source.dxf"
            shutil.copy(fixture, target)
            return target, {"name": "LibreDWG dwg2dxf", "version": "0.14"}

        monkeypatch.setattr(server, "convert", fake_convert)
        return TestClient(server.create_app(data, site, pipeline_runner=runner), base_url=BASE_URL)

    return factory, runs


def upload(client, content=FAKE_DWG, name="plano.dwg", description=""):
    response = client.post(
        "/api/projects",
        files={"file": (name, content, "application/octet-stream")},
        data={"description": description},
    )
    assert response.status_code == 202, response.text
    return wait_project(client, response.json()["id"], ("review", "failed"))


def test_dwg_upload_review_answer_approve_and_generate(app, tmp_path):
    factory, runs = app
    with factory(build(tmp_path / "flat.dxf", unknown=True)) as client:
        project = upload(client)
        assert project["status"] == "review", project.get("error")
        assert project["source_format"] == "dwg" and project["source_file"] == "source.dwg"
        # Middle step: the deterministic reading waits for the user before any AI call.
        assert project["stage"] == "reading_check"
        cad = project["cad"]
        assert cad["converter"] == "LibreDWG dwg2dxf 0.14"
        assert cad["units"]["source"].startswith("$INSUNITS")
        assert cad["ai"]["called"] is False and cad["ai"]["error"] is None
        assert cad["ai"]["items"] == len(cad["doubts"]) > 0
        assert client.get(project["pages"][0]["image_url"]).status_code == 200
        route = f"/api/projects/{project['id']}"
        early = {"revision": project["revision"]}
        assert client.post(route + "/approve", json=early).status_code == 409
        assert client.put(route + "/answers", json={**early, "answers": {}}).status_code == 409
        confirmed = client.post(route + "/confirm-reading", json=early)
        assert confirmed.status_code == 202, confirmed.text
        assert client.post(route + "/confirm-reading", json=early).status_code == 409  # stale
        project = wait_project(client, project["id"], ("review", "failed"))
        assert project["stage"] == "review" and project["reading_confirmed"] is True
        cad = project["cad"]
        assert "OPENAI_API_KEY" in cad["ai"]["error"]  # no key: doubts left to the user
        refused = client.post(route + "/approve", json={"revision": project["revision"]})
        assert refused.status_code == 409 and "sin resolver" in refused.text
        item = cad["pending"][0]["id"]
        bad = client.put(
            route + "/answers", json={"revision": project["revision"], "answers": {"nope": {}}}
        )
        assert bad.status_code == 422
        answered = client.put(
            route + "/answers",
            json={
                "revision": project["revision"],
                "answers": {item: {"kind": "washing_machine", "name": "Lavadora", "front": "left"}},
            },
        )
        assert answered.status_code == 202, answered.text
        project = wait_project(client, project["id"], ("review", "failed"))
        assert project["cad"]["pending"] == []
        assert project["cad"]["counts"]["furniture"]["user"] == 1
        approved = client.post(route + "/approve", json={"revision": project["revision"]})
        assert approved.status_code == 202, approved.text
        finished = wait_project(client, project["id"], ("succeeded", "failed"))
        assert finished["status"] == "succeeded", finished.get("error")
    args = runs[-1]
    assert args.input.name == "source.dwg"
    geometry = Geometry.model_validate_json(Path(args.geometry).read_text())
    assert geometry.source.format == "dwg"
    assert geometry.source.converter == "LibreDWG dwg2dxf 0.14"
    assert geometry.source.sha256 == __import__("hashlib").sha256(FAKE_DWG).hexdigest()
    machine = next(f for f in geometry.furniture if f.name.startswith("washing_machine"))
    assert machine.evidence.cad.reading == "user"


def test_dxf_is_read_directly_without_a_converter(app, tmp_path):
    factory, _ = app
    fixture = build(tmp_path / "flat.dxf")
    with factory(fixture) as client:
        project = upload(client, fixture.read_bytes(), "plano.dxf")
        assert project["status"] == "review", project.get("error")
        assert project["cad"]["converter"] is None and project["cad"]["pending"] == []
        assert project["cad"]["counts"]["doors"]["verified"] == 1


def test_wrong_content_and_type_are_rejected(app, tmp_path):
    factory, _ = app
    with factory(build(tmp_path / "flat.dxf")) as client:
        for name, content in [("plano.dwg", b"%PDF-1.7 not a dwg"), ("plano.dxf", b"hello")]:
            response = client.post(
                "/api/projects", files={"file": (name, content, "application/octet-stream")}
            )
            assert response.status_code == 415, response.text
        response = client.post("/api/projects", files={"file": ("plano.zip", b"PK", "x")})
        assert response.status_code == 415 and "DWG" in response.json()["detail"]


def test_missing_converter_gives_a_spanish_instruction(tmp_path, monkeypatch):
    def missing(*_args, **_kwargs):
        raise ConverterMissing(MISSING)

    monkeypatch.setattr(server, "convert", missing)
    site = tmp_path / "site"
    (site / "dist").mkdir(parents=True)
    (site / "dist/index.html").write_text("<html></html>")
    app = server.create_app(tmp_path / "data", site, pipeline_runner=successful_runner)
    with TestClient(app, base_url=BASE_URL) as client:
        project = upload(client)
    assert project["status"] == "failed"
    assert "ODA File Converter" in project["error"] and "LibreDWG" in project["error"]


def test_several_plans_wait_for_the_users_choice(app, tmp_path):
    factory, _ = app
    with factory(build(tmp_path / "two.dxf", copies=2)) as client:
        project = upload(client)
        assert project["stage"] == "choose_plan" and len(project["plans"]) == 2
        assert client.get(f"/api/projects/{project['id']}/files/overview.png").status_code == 200
        response = client.post(
            f"/api/projects/{project['id']}/plan", json={"revision": project["revision"], "plan": 1}
        )
        assert response.status_code == 202, response.text
        project = wait_project(client, project["id"], ("review", "failed"))
        assert project["status"] == "review" and project["plan_index"] == 1
        assert project["stage"] == "reading_check" and project["cad"]["plan"]["index"] == 1
        # From the reading check the user can still switch to the other plan.
        response = client.post(
            f"/api/projects/{project['id']}/plan", json={"revision": project["revision"], "plan": 0}
        )
        assert response.status_code == 202, response.text
        project = wait_project(client, project["id"], ("review", "failed"))
        assert project["stage"] == "reading_check" and project["cad"]["plan"]["index"] == 0
        assert json.loads(json.dumps(project["draft"]))["entities"]

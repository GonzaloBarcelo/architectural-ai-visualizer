"""AI enhancement through the local API: location edit, approval option, «Mejorar de nuevo»."""

import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from pipelines.common import write_json
from pipelines.web.server import create_app
from tests.test_enhancement import scene
from tests.test_web_api import BASE_URL, ai_draft, wait_project


def test_api_location_edit_approval_option_and_enhance_again(tmp_path, pdf, monkeypatch):
    seen, reruns = [], []

    def runner(args):
        seen.append(SimpleNamespace(enhance=args.enhance, location=args.enhancement["location"]))
        out = args.output
        (out / "renders/enhanced").mkdir(parents=True, exist_ok=True)
        scene(320, 240).save(out / "renders/interior.webp")
        scene(320, 240).save(out / "renders/enhanced/interior.webp")
        args.progress("enhancing")
        args.activity({"label": "Mejora con IA · imagen 1 de 1", "step": 1, "total": 1})
        write_json(
            out / "manifest.json",
            {
                "project_id": "x",
                "title": "T",
                "model_url": "model.glb",
                "floors": [],
                "quality": {"passed": True},
                "renders": [
                    {
                        "id": "interior",
                        "label": "Interior",
                        "url": "renders/interior.webp",
                        "enhanced_url": "renders/enhanced/interior.webp",
                    }
                ],
                "enhancement": {
                    "status": "completed" if args.enhance else "disabled",
                    "cost_usd": 0.5,
                    "seconds": 12.0,
                },
            },
        )
        write_json(out / "run-status.json", {"passed": True})
        return out

    def fake_safe_run(output, progress=None, force=False, **options):
        reruns.append((force, options["location"]["city"]))
        progress({"label": "Mejora con IA · imagen 1 de 1", "step": 1, "total": 1})
        manifest = json.loads((output / "manifest.json").read_text())
        manifest["enhancement"] = {"status": "completed", "cost_usd": 0.25, "seconds": 9.0}
        write_json(output / "manifest.json", manifest)

    monkeypatch.setattr(
        "pipelines.web.server.propose",
        lambda path, raw, cache_dir=None, progress=None: (ai_draft(raw), {}),
    )
    monkeypatch.setattr("pipelines.web.server.enhancement.safe_run", fake_safe_run)
    monkeypatch.delenv("AAV_ENHANCE", raising=False)
    with TestClient(
        create_app(tmp_path / "p", tmp_path / "site", runner), base_url=BASE_URL
    ) as client:
        response = client.post(
            "/api/projects", files={"file": ("plan.pdf", pdf.read_bytes(), "application/pdf")}
        )
        ident = response.json()["id"]
        project = wait_project(client, ident, ("review",))
        while project["stage"] != "review":
            project = client.get(f"/api/projects/{ident}").json()
        route = f"/api/projects/{ident}"
        assert project["location"]["status"] == "missing"  # synthetic plan has no address
        assert project["enhance_server"] is True

        edited = client.put(
            route + "/location",
            json={"revision": project["revision"], "text": "Calle Mayor 1, 28013 Madrid"},
        )
        assert edited.status_code == 200, edited.text
        edited = edited.json()
        assert (
            edited["location"]["status"] == "user" and edited["revision"] == project["revision"] + 1
        )

        off = client.post(
            route + "/approve", json={"revision": edited["revision"], "enhance": False}
        )
        assert off.status_code == 202, off.text
        done = wait_project(client, ident, ("succeeded", "failed"))
        assert seen[-1].enhance is False and done["enhance"] is False
        assert done["enhancement"]["status"] == "disabled"

        on = client.post(route + "/approve", json={"revision": done["revision"]})
        assert on.status_code == 202
        done = wait_project(client, ident, ("succeeded", "failed"))
        assert seen[-1].enhance is True and seen[-1].location["city"] == "Madrid"
        assert done["ai_usage"]["enhancement"]["cost_usd"] == 0.5
        assert client.get(route + "/files/renders/enhanced/interior.webp").status_code == 200
        assert client.get(route + "/files/renders/enhanced/../x.webp").status_code == 404

        # A location edit after delivery keeps the result valid (geometry is unchanged).
        moved = client.put(
            route + "/location",
            json={"revision": done["revision"], "text": "Plaza Mayor, 37002 Salamanca"},
        )
        moved = moved.json()
        assert moved["result_revision"] == moved["revision"]
        assert client.get(moved["manifest_url"]).status_code == 200

        stale = client.post(route + "/enhance", json={"revision": moved["revision"] - 1})
        assert stale.status_code == 409
        again = client.post(route + "/enhance", json={"revision": moved["revision"]})
        assert again.status_code == 202 and again.json()["stage"] == "enhancing"
        final = wait_project(client, ident, ("succeeded",))
        assert reruns == [(True, "Salamanca")]
        assert final["enhancement"]["cost_usd"] == 0.25
        assert final["manifest_url"] != moved["manifest_url"]

        monkeypatch.setenv("AAV_ENHANCE", "0")
        blocked = client.post(route + "/enhance", json={"revision": final["revision"]})
        assert blocked.status_code == 409 and "desactivada" in blocked.json()["detail"]
        regen = client.post(route + "/approve", json={"revision": final["revision"]})
        assert regen.status_code == 202
        wait_project(client, ident, ("succeeded",))
        assert seen[-1].enhance is False


@pytest.fixture
def pdf(tmp_path):
    from pipelines.pdf.synthetic import create

    return create(tmp_path / "upload.pdf")

"""AI enhancement: prompt, location, canvas round trip, fidelity and a mocked OpenAI client.

Everything here is synthetic: no client drawing, no network, no API key.
"""

import base64
import io
import json
import threading
import time
from types import SimpleNamespace

import cv2
import ezdxf
import numpy as np
import pytest
from PIL import Image

from pipelines.common import write_json
from pipelines.postprocess import enhance as E
from pipelines.postprocess import fidelity as F
from pipelines.postprocess import location as L
from pipelines.postprocess import prompt as P

STYLE = ("## Synthetic master style\nWarm minimal light.\n", "f" * 64)


def square(x0, y0, x1, y1):
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]


def geometry(roofs=()):
    def item(ident, polygon, **extra):
        return {"id": ident, "floor_id": "F0", "polygon": polygon, **extra}

    return {
        "rooms": [
            item("room0", square(0, 0, 4, 3), name="Dormitorio principal", floor_finish="wood"),
            item("room1", square(4, 0, 6, 3), name="Baño 01", floor_finish="tile"),
        ],
        "furniture": [
            item("f1", square(1, 1, 2.6, 2.9), name="bed_double / Cama doble", height=0.5),
            item("f2", square(0.2, 2.4, 0.7, 2.9), name="nightstand / Mesilla", height=0.5),
            item("f3", square(2.8, 2.4, 3.3, 2.9), name="nightstand / Mesilla", height=0.5),
            item("f4", square(4.5, 2.4, 5.0, 2.9), name="toilet / Inodoro", height=0.4),
        ],
        "openings": [
            item("w1", square(1.5, -0.1, 2.7, 0.1), kind="window", style="casement", wall_id="x"),
            item("d1", square(3.9, 1.0, 4.1, 1.8), kind="door", style="hinged", wall_id="y"),
        ],
        "roofs": list(roofs),
        "finishes": {
            "floor": {"name": "Roble natural"},
            "tile": {"name": "Travertino"},
            "walls": {"name": "Cal blanca"},
        },
    }


MADRID = L.user_location("Calle Mayor 1, 28013 Madrid")
BEDROOM = {"id": "interior", "label": "Interior · Dormitorio principal", "room_id": "room0"}


# --- Prompt -------------------------------------------------------------------------------------


def test_master_style_is_included_verbatim_and_read_from_the_studio_file():
    text, digest = P.master_style()
    assert P.STYLE_PATH.name == "PROMPT_STYLE.md"
    composed = P.compose(BEDROOM, geometry(), MADRID, "")
    assert composed["prompt"].startswith(text)
    assert composed["style_sha256"] == digest and len(digest) == 64
    assert composed["version"] == P.PROMPT_VERSION


def test_hard_constraints_come_last_even_on_the_strict_retry():
    for strict in (False, True):
        composed = P.compose(BEDROOM, geometry(), MADRID, "roble", strict=strict, style=STYLE)
        assert composed["prompt"].endswith(P.HARD_CONSTRAINTS)
        assert composed["sections"][-1] == "hard_constraints"
        assert ("strict" in composed["sections"]) is strict


def test_precedence_geometry_then_client_materials_then_master_style():
    composed = P.compose(BEDROOM, geometry(), MADRID, "suelo de nogal oscuro", style=STYLE)
    order = composed["sections"]
    assert order.index("master_style") < order.index("view") < order.index("client_materials")
    assert order.index("client_materials") < order.index("precedence")
    text = composed["prompt"]
    assert "«suelo de nogal oscuro»" in text and "replace the master style's palette" in text
    assert "(1) the geometry" in text and "(2) the client's materials" in text
    assert "(3) the master style" in text
    without = P.compose(BEDROOM, geometry(), MADRID, "", style=STYLE)
    assert "client_materials" not in without["sections"]


def present(text):
    return next(x for x in text.splitlines() if x.startswith("Furniture actually present"))


def test_interior_brief_lists_only_the_furniture_of_that_room():
    text = P.compose(BEDROOM, geometry(), MADRID, "", style=STYLE)["prompt"]
    assert "1 double bed" in present(text) and "2 nightstands" in present(text)
    assert "toilet" not in present(text)
    assert "bedroom «Dormitorio principal»" in text
    assert "Floor finish: wood (Roble natural)" in text
    assert "1 window (casement)" in text and "1 door (hinged)" in text
    bath = {"id": "interior-2", "label": "Interior · Baño 01"}  # matched by label (old runs)
    text = P.compose(bath, geometry(), MADRID, "", style=STYLE)["prompt"]
    brief = text.split("VIEW:")[1].split("PRECEDENCE")[0]
    assert "1 wall-hung toilet" in present(brief) and "bed" not in present(brief)
    assert "tile (Travertino)" in brief


def test_camera_field_of_view_limits_the_listed_openings():
    view = {
        **BEDROOM,
        "camera": {"position": [2, 2.5, 1.4], "forward": [0, -1, -0.1], "lens": 17, "sensor": 36},
    }
    brief = P.view_brief(view, geometry())
    assert "1 window (casement)" in brief and "door" not in brief.split("Openings")[1]


def test_exterior_and_axonometric_briefs_protect_massing_and_cut_away():
    ext = P.view_brief({"id": "exterior", "label": "Exterior"}, geometry())
    assert "do not add a roof" in ext and "roofline" in ext
    assert "same size and at exactly the same position" in ext and "no trees" in ext
    assert "blinds" in P.HARD_CONSTRAINTS and "borders around the image" in P.HARD_CONSTRAINTS
    assert "do not add a roof" not in P.view_brief({"id": "exterior"}, geometry(roofs=[{}]))
    axo = P.view_brief({"id": "axonometric", "label": "Axonometría"}, geometry())
    assert "Light enhancement only" in axo and "cut-away clean" in axo


def test_location_block_uses_latitude_climate_and_falls_back_only_when_missing():
    block = P.location_block(MADRID)
    assert "Calle Mayor, Madrid, Comunidad de Madrid, España" in block
    assert "40° N" in block and "continental" in block and "urban context of Madrid" in block
    assert "never change the building" in block
    fallback = P.compose(BEDROOM, geometry(), L.missing(), "", style=STYLE)
    assert fallback["location_fallback"] and L.FALLBACK in fallback["prompt"]


# --- Location -----------------------------------------------------------------------------------


def raw_pdf(*blocks):
    return {
        "pages": [
            {
                "page": 1,
                "text_blocks": [
                    [10.0 * i, 20.0, 10.0 * i + 50, 40.0, text, i, 0]
                    for i, text in enumerate(blocks)
                ],
            }
        ]
    }


def test_labelled_title_block_address_is_verified_with_its_source_block():
    raw = raw_pdf(
        "Salón\nSup. 20.00 m2\n",
        "CALLE DEL PEZ\n",
        "Emplazamiento:\nAvda. del Puerto, 12, 3º\n46021 Valencia\n",
        "Promotor:\nSINTÉTICO S.L.\n",
    )
    loc = L.from_pdf(raw, "plano.pdf")
    assert loc["status"] == "verified" and loc["confidence"] >= 0.9
    assert loc["street"] == "Avenida del Puerto" and loc["city"] == "Valencia"
    assert loc["postal_code"] == "46021" and loc["region"] == "Comunitat Valenciana"
    assert loc["country"] == "España" and "region" in loc["derived"]
    assert loc["source"]["page"] == 1 and loc["source"]["block"] == 2
    assert loc["nearby_streets"] == ["Calle del Pez"]
    assert "SINTÉTICO" not in loc["text"]


def test_plan_street_label_plus_filename_city_is_only_inferred():
    loc = L.from_pdf(raw_pdf("CALLE DE LA LUNA\n", "1.20\n"), "MAD_Proyecto.pdf")
    assert loc["street"] == "Calle de la Luna" and loc["city"] == "Madrid"
    assert loc["confidence"] < 0.6 and loc["city_source"]["kind"] == "filename"
    hint = L.from_filename("MAD_OlivoVerde.pdf")
    assert hint["street"] == "Calle Olivo Verde" and hint["city"] == "Madrid"
    assert L.from_pdf(raw_pdf(), "MAD_OlivoVerde.pdf")["status"] == "inferred"


def test_missing_location_is_never_invented():
    loc = L.from_pdf(raw_pdf("Salón\nSup. 20.00 m2\n", "3.36\n2.15\n"), "plano.pdf")
    assert loc["status"] == "missing" and loc["city"] is None and loc["text"] == ""
    assert L.describe(loc) == (L.FALLBACK, True)
    cleared = L.user_location("   ")
    assert cleared["status"] == "missing" and cleared["cleared_by_user"]
    edited = L.user_location("Calle Mayor 1, 28013 Madrid", loc)
    assert edited["status"] == "user" and edited["city"] == "Madrid"


def test_dxf_title_block_in_paper_space_gives_the_entity_handle(tmp_path):
    doc = ezdxf.new()
    doc.modelspace().add_text("CALLE DEL SOL", dxfattribs={"layer": "a.textos"})
    layout = doc.layouts.new("Lámina 1")
    mtext = layout.add_mtext(
        "Situación:\\PC/ Mayor, 5\\P28013 Madrid", dxfattribs={"layer": "a.cajetín"}
    )
    path = tmp_path / "plano.dxf"
    doc.saveas(path)
    loc = L.from_dxf(path, "plano.dxf")
    assert loc["status"] == "verified" and loc["city"] == "Madrid"
    assert loc["source"]["kind"] == "dwg" and loc["source"]["handle"] == mtext.dxf.handle
    assert loc["source"]["layout"] == "Lámina 1"
    assert loc["nearby_streets"] == ["Calle del Sol"]


def test_dxf_split_label_and_missing(tmp_path):
    doc = ezdxf.new()
    msp = doc.modelspace()
    msp.add_text("Dirección:")
    msp.add_text("Carrer de Mallorca, 100")
    msp.add_text("08029 Barcelona")
    path = tmp_path / "a.dxf"
    doc.saveas(path)
    loc = L.from_dxf(path)
    assert loc["city"] == "Barcelona" and loc["street"] == "Carrer de Mallorca"
    empty = ezdxf.new()
    empty.modelspace().add_text("1.20")
    empty.saveas(tmp_path / "b.dxf")
    assert L.from_dxf(tmp_path / "b.dxf")["status"] == "missing"


# --- Canvas ----------------------------------------------------------------------------------


def noise(width, height, seed=0):
    rng = np.random.default_rng(seed)
    return Image.fromarray(rng.integers(0, 256, (height, width, 3), dtype=np.uint8))


@pytest.mark.parametrize("size", [(1600, 1200), (1000, 750), (777, 1301), (3000, 900)])
def test_pad_and_crop_round_trip_is_pixel_exact_on_flexible_models(size):
    image = noise(*size)
    plan = F.canvas_plan(*size, "gpt-image-2.5-sunburst")
    cw, ch = plan["canvas"]
    assert cw % 16 == 0 and ch % 16 == 0 and max(cw, ch) / min(cw, ch) <= 3
    padded = F.pad(image, plan)
    assert padded.size == (cw, ch)
    _, _, w, h = plan["content"]
    assert abs(w / h - size[0] / size[1]) < 0.01  # never stretched
    restored, resampled = F.crop(padded, plan, (w, h))
    assert not resampled or plan["scale"] != 1
    scaled = image if plan["scale"] == 1 else image.resize((w, h), Image.LANCZOS)
    assert np.array_equal(np.asarray(restored), np.asarray(scaled))
    if plan["scale"] == 1 and max(size) / min(size) <= 3:
        assert plan["canvas"] == [-(-size[0] // 16) * 16, -(-size[1] // 16) * 16]
    assert F.canvas_plan(1600, 1200, "gpt-image-2")["content"] == [0, 0, 1600, 1200]


def test_fixed_size_models_pad_to_the_closest_supported_size():
    image = noise(1600, 1200)
    plan = F.canvas_plan(1600, 1200, "gpt-image-1.5")
    assert plan["canvas"] == [1536, 1024] and plan["content"][2:] == [1365, 1024]
    padded = F.pad(image, plan)
    content, _ = F.crop(padded, plan, plan["content"][2:])
    scaled = image.resize(tuple(plan["content"][2:]), Image.LANCZOS)
    assert np.array_equal(np.asarray(content), np.asarray(scaled))
    back, resampled = F.crop(padded, plan, (1600, 1200))
    assert back.size == (1600, 1200) and resampled


# --- Fidelity ---------------------------------------------------------------------------------


def scene(width=960, height=720, seed=1):
    """A synthetic interior: wall edges, a window, a bed, a nightstand, shading."""
    rng = np.random.default_rng(seed)
    a = np.full((height, width, 3), 236, np.uint8)
    a[: height // 5] = (220, 215, 208)
    cv2.line(a, (0, height // 5), (width, height // 5 + 30), (150, 140, 130), 3)
    cv2.line(a, (width * 2 // 3, 0), (width * 2 // 3, height), (170, 160, 150), 3)
    cv2.rectangle(a, (width // 8, height // 4), (width // 3, height // 2), (120, 140, 170), -1)
    cv2.rectangle(a, (width // 8, height // 4), (width // 3, height // 2), (60, 50, 40), 6)
    cv2.rectangle(a, (width // 3, height // 2), (width * 3 // 4, height - 60), (200, 190, 175), -1)
    cv2.rectangle(a, (width // 3, height // 2), (width * 3 // 4, height - 60), (90, 80, 70), 4)
    cv2.rectangle(
        a, (width * 4 // 5, height // 2), (width - 30, height * 2 // 3), (140, 110, 80), -1
    )
    a = a.astype(float) + rng.normal(0, 2, a.shape)
    return Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))


def test_fidelity_passes_identical_and_recoloured_images():
    original = scene()
    assert F.compare(original, original)["score"] == 1.0
    a = np.asarray(original).astype(float)
    recoloured = Image.fromarray(np.clip(a[:, :, [2, 0, 1]] * 0.8 + 30, 0, 255).astype(np.uint8))
    report = F.compare(original, recoloured)
    assert report["passed"], report


def test_fidelity_fails_shifted_and_warped_images():
    original = scene()
    w, h = original.size
    shifted = original.transform(original.size, Image.AFFINE, (1, 0, -0.025 * w, 0, 1, 0))
    report = F.compare(original, shifted)
    assert not report["passed"] and report["tile_shift_percent"] > F.MAX_SHIFT, report
    src = np.float32([[0, 0], [w, 0], [w, h], [0, h]])
    dst = np.float32([[0.05 * w, 0], [w, 0.04 * h], [0.95 * w, h], [0, 0.96 * h]])
    warped = Image.fromarray(
        cv2.warpPerspective(
            np.asarray(original),
            cv2.getPerspectiveTransform(src, dst),
            (w, h),
            borderMode=cv2.BORDER_REFLECT,
        )
    )
    report = F.compare(original, warped)
    assert not report["passed"], report


def test_mask_silhouettes_take_part_when_available():
    original = scene()
    mask = np.zeros((720, 960, 3), np.uint8)
    mask[360:660, 320:720, 2] = 255  # the bed, furniture class
    report = F.compare(original, original, Image.fromarray(mask))
    assert report["mask"] and report["components"]["mask_recall"] == 1.0


# --- Enhancer with a mock OpenAI client -------------------------------------------------------


class FakeImages:
    def __init__(self, transform=None, fail=None, delay=0.0):
        self.transform = transform or (lambda im: im)
        self.fail = fail
        self.delay = delay
        self.calls = []
        self.lock = threading.Lock()
        self.active = self.peak = 0

    def edit(self, **kwargs):
        with self.lock:
            self.calls.append(kwargs)
            self.active += 1
            self.peak = max(self.peak, self.active)
        try:
            time.sleep(self.delay)
            if self.fail:
                raise self.fail
            image = Image.open(io.BytesIO(kwargs["image"][1])).convert("RGB")
            buffer = io.BytesIO()
            self.transform(image).save(buffer, format="PNG")
            usage = SimpleNamespace(
                model_dump=lambda: {
                    "input_tokens": 1500,
                    "output_tokens": 6000,
                    "total_tokens": 7500,
                    "input_tokens_details": {"text_tokens": 1000, "image_tokens": 500},
                    "output_tokens_details": {"image_tokens": 6000, "text_tokens": 0},
                }
            )
            return SimpleNamespace(
                data=[SimpleNamespace(b64_json=base64.b64encode(buffer.getvalue()).decode())],
                usage=usage,
                created=1,
            )
        finally:
            with self.lock:
                self.active -= 1


def fake_client(**kwargs):
    return SimpleNamespace(images=FakeImages(**kwargs))


def project(tmp_path, ids=("exterior", "axonometric", "interior", "interior-2")):
    out = tmp_path / "run"
    (out / "renders").mkdir(parents=True)
    labels = {"exterior": "Exterior", "axonometric": "Axonometría"}
    renders = []
    for i, ident in enumerate(ids):
        scene(640, 480, seed=i).save(out / "renders" / f"{ident}.webp", quality=95)
        renders.append(
            {
                "id": ident,
                "label": labels.get(ident, "Interior · Dormitorio principal"),
                "url": f"renders/{ident}.webp",
            }
        )
    write_json(
        out / "manifest.json",
        {
            "project_id": "x",
            "title": "T",
            "renders": renders,
            "model_url": "model.glb",
            "floors": [],
            "quality": {"passed": True},
        },
    )
    write_json(out / "views.json", [{"id": r["id"], "label": r["label"]} for r in renders])
    write_json(out / "geometry.json", geometry())
    return out


def recolour(image):
    a = np.asarray(image).astype(float)
    return Image.fromarray(np.clip(a * 0.85 + 25, 0, 255).astype(np.uint8))


def run(out, client, tmp_path, **kwargs):
    settings = kwargs.pop("settings", None) or E.Settings(model="gpt-image-2.5-sunburst")
    return E.Enhancer(
        out,
        MADRID,
        "roble",
        settings=settings,
        client=client,
        cache_dir=tmp_path / "cache",
        audit_dir=tmp_path / "audit",
        **kwargs,
    ).run()


def test_enhancement_writes_images_manifest_fields_audit_and_cost(tmp_path):
    out = project(tmp_path)
    client = fake_client(transform=recolour)
    events = []
    summary = run(out, client, tmp_path, progress=events.append)
    assert summary["status"] == "completed" and summary["accepted"] == 4
    manifest = json.loads((out / "manifest.json").read_text())
    for render in manifest["renders"]:
        assert render["url"] == f"renders/{render['id']}.webp"  # original kept
        assert render["enhanced_url"] == f"renders/enhanced/{render['id']}.webp"
        assert (out / render["enhanced_url"]).is_file()
        assert Image.open(out / render["enhanced_url"]).size == (640, 480)
        assert render["enhancement"]["status"] == "accepted"
        assert render["enhancement"]["fidelity"] >= F.THRESHOLD
    info = manifest["enhancement"]
    assert info["model"] == "gpt-image-2.5-sunburst" and info["prompt_version"] == P.PROMPT_VERSION
    assert info["style_sha256"] == P.master_style()[1]
    assert info["location"]["city"] == "Madrid" and info["label"] == E.LABEL
    # 1000 text × $5 + 500 image × $8 + 6000 output × $30 per million tokens, four images.
    assert info["cost_usd"] == pytest.approx(4 * 0.189, abs=1e-4)
    call = client.images.calls[0]
    canvas = F.canvas_plan(640, 480, "gpt-image-2.5-sunburst")["canvas"]
    assert canvas == [944, 704]  # below the API's minimum pixel count: scaled up, same aspect
    assert call["size"] == "944x704" and call["quality"] == "high" and call["n"] == 1
    assert "input_fidelity" not in call and call["prompt"].endswith(P.HARD_CONSTRAINTS)
    audits = list((tmp_path / "audit").glob("enhance-*.json"))
    assert len(audits) == 4
    record = json.loads(audits[0].read_text())
    assert {"model", "prompt", "size", "seconds", "usage", "cost_usd", "fidelity"} <= set(record)
    assert events[-1]["done"] == [0, 1, 2, 3] and "imagen" in events[-1]["label"]
    detail = json.loads((out / "enhancement.json").read_text())
    assert detail["views"][0]["returned_size"] == [944, 704] and detail["views"][0]["upscaled"]


def test_cache_hit_avoids_new_calls_and_force_reruns(tmp_path):
    out = project(tmp_path, ids=("interior",))
    client = fake_client(transform=recolour)
    run(out, client, tmp_path)
    again = run(out, client, tmp_path)
    assert len(client.images.calls) == 1 and again["cost_usd_new"] == 0
    detail = json.loads((out / "enhancement.json").read_text())
    assert detail["views"][0]["cache_hit"]
    run(out, client, tmp_path, force=True)
    assert len(client.images.calls) == 2


def test_views_run_concurrently_up_to_the_limit(tmp_path):
    out = project(tmp_path, ids=("exterior", "interior", "interior-2", "interior-3", "interior-4"))
    client = fake_client(transform=recolour, delay=0.3)
    settings = E.Settings(model="gpt-image-2.5-sunburst", concurrency=3)
    started = time.monotonic()
    run(out, client, tmp_path, settings=settings)
    assert client.images.peak == 3
    assert time.monotonic() - started < 5 * 0.3


def test_api_failure_keeps_the_originals_and_never_raises(tmp_path):
    out = project(tmp_path, ids=("interior",))
    (out / "renders/enhanced").mkdir()
    (out / "renders/enhanced/interior.webp").write_bytes(b"stale")
    client = fake_client(fail=RuntimeError("boom"))
    summary = E.safe_run(
        out, location=MADRID, client=client, cache_dir=tmp_path / "c", audit_dir=tmp_path / "a"
    )
    assert summary["status"] == "failed" and summary["failed"] == 1
    manifest = json.loads((out / "manifest.json").read_text())
    render = manifest["renders"][0]
    assert render["url"] == "renders/interior.webp" and "enhanced_url" not in render
    assert not (out / "renders/enhanced/interior.webp").exists()
    assert "originales" in manifest["enhancement"]["notice"]


def test_geometric_drift_retries_strictly_once_then_keeps_the_original(tmp_path):
    out = project(tmp_path, ids=("interior",))

    def drift(image):
        w, _ = image.size
        return image.transform(image.size, Image.AFFINE, (1, 0, -0.03 * w, 0, 1, 0))

    client = fake_client(transform=drift)
    summary = run(out, client, tmp_path)
    assert summary["status"] == "rejected" and len(client.images.calls) == 2
    assert "STRICT RETRY" in client.images.calls[1]["prompt"]
    assert client.images.calls[1]["prompt"].endswith(P.HARD_CONSTRAINTS)
    render = json.loads((out / "manifest.json").read_text())["renders"][0]
    assert "enhanced_url" not in render
    assert render["enhancement"]["notice"] == E.REJECTED == "mejora rechazada: deriva geométrica"
    assert (out / "enhancement/rejected/interior.webp").is_file()


def test_missing_key_or_disabled_step_keeps_originals(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    out = project(tmp_path, ids=("interior",))
    assert E.safe_run(out, location=MADRID)["status"] == "unavailable"
    assert (
        "OPENAI_API_KEY" in json.loads((out / "manifest.json").read_text())["enhancement"]["notice"]
    )
    assert E.safe_run(out, enabled=False)["status"] == "disabled"


def test_axonometric_can_be_skipped_and_site_copies_drop_enhancements(tmp_path):
    out = project(tmp_path, ids=("axonometric", "interior"))
    settings = E.Settings(model="gpt-image-2.5-sunburst", axonometric=False)
    summary = run(out, fake_client(transform=recolour), tmp_path, settings=settings)
    assert summary["skipped"] == 1 and summary["accepted"] == 1
    manifest = json.loads((out / "manifest.json").read_text())
    clean = E.strip_for_site(manifest)
    assert "enhancement" not in clean and all("enhanced_url" not in r for r in clean["renders"])
    E.copy_site_renders(out, tmp_path / "site")
    assert not (tmp_path / "site/renders/enhanced").exists()
    assert (tmp_path / "site/renders/interior.webp").is_file()


def test_cost_estimate_uses_the_model_prices():
    usage = {
        "input_tokens_details": {"text_tokens": 2000, "image_tokens": 1000},
        "output_tokens_details": {"image_tokens": 4000},
    }
    assert E.cost_of("gpt-image-2.5-sunburst", usage) == pytest.approx(0.138)
    assert E.cost_of("gpt-image-1.5", usage) == pytest.approx(0.146)
    assert E.supports_input_fidelity("gpt-image-1.5")
    assert not E.supports_input_fidelity("gpt-image-2.5-sunburst")


def test_cli_reenhances_a_finished_web_project_without_blender(tmp_path, monkeypatch):
    folder = tmp_path / "projects" / ("a" * 32)
    out = project(folder, ids=("interior",))
    write_json(
        folder / "project.json",
        {
            "id": "a" * 32,
            "status": "succeeded",
            "result": str(out.relative_to(folder)),
            "description": "roble",
            "location": MADRID,
            "manifest_url": "/m.json?v=1",
            "revision": 3,
            "result_revision": 3,
            "updated_at": "x",
        },
    )
    client = fake_client(transform=recolour)
    monkeypatch.setattr(E.Enhancer, "__init__", _with_client(E.Enhancer.__init__, client))
    assert E.main([str(folder)]) == 0
    state = json.loads((folder / "project.json").read_text())
    assert state["enhancement"]["accepted"] == 1 and state["ai_usage"]["enhancement"]["cost_usd"]
    assert state["manifest_url"].startswith("/m.json?v=1&e=")
    assert (folder / "ai-audit").is_dir() and (tmp_path / "projects/ai-cache").is_dir()


def _with_client(init, client):
    def patched(self, *args, **kwargs):
        kwargs["client"] = client
        init(self, *args, **kwargs)

    return patched

"""Shared filesystem, provenance and executable discovery helpers."""

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n")
    temp.replace(path)


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def blender_bin():
    candidates = [
        os.getenv("BLENDER_BIN"),
        shutil.which("blender"),
        "/Applications/Blender.app/Contents/MacOS/Blender",
        str(Path.home() / "Applications/Blender.app/Contents/MacOS/Blender"),
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return str(candidate)
    raise RuntimeError("Blender not found. Install Blender 4.5 LTS or set BLENDER_BIN.")


# OpenAI text/vision models, one setting per purpose (see .env.example). Each falls back to
# OPENAI_MODEL and then to the default; the image-edit model is OPENAI_IMAGE_MODEL (enhance.py).
MODELS = {
    "plan": ("OPENAI_PLAN_MODEL", "gpt-5.4"),  # PDF plan reading (3 calls)
    "dwg": ("OPENAI_DWG_MODEL", "gpt-5.4"),  # DWG doubts (1 call)
    "materials": ("OPENAI_MATERIALS_MODEL", "gpt-5.4"),  # client materials → finishes
    "vision": ("OPENAI_VISION_MODEL", "gpt-4.1"),  # CLI --vision proposals (legacy)
}


def model_for(purpose):
    variable, default = MODELS[purpose]
    return (os.getenv(variable) or os.getenv("OPENAI_MODEL") or default).strip()


def revision():
    # Container images have no Git checkout: the commit is baked in at build time.
    baked = os.getenv("AAV_REVISION", "").strip()
    if baked:
        return {"commit": baked, "dirty": False}
    try:
        result = subprocess.run(
            check=False, args=["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True
        )
        dirty = subprocess.run(
            check=False,
            args=["git", "status", "--porcelain"],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
    except OSError:
        return {"commit": "unknown", "dirty": False}
    return {"commit": result.stdout.strip() or "uncommitted", "dirty": bool(dirty.stdout.strip())}

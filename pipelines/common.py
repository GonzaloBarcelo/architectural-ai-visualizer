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


def revision():
    result = subprocess.run(
        check=False, args=["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True
    )
    dirty = subprocess.run(
        check=False, args=["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True
    )
    return {"commit": result.stdout.strip() or "uncommitted", "dirty": bool(dirty.stdout.strip())}

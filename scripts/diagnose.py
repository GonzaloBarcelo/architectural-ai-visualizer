"""Emit a credential-free JSON environment report; optional Blender capability probe."""

import argparse
import importlib.metadata
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pipelines.common import blender_bin, write_json


def report(probe=False):
    tools = {}
    for name in ["git", "gh", "uv", "node", "npm", "codex"]:
        path = shutil.which(name) or (
            f"/opt/homebrew/bin/{name}" if Path(f"/opt/homebrew/bin/{name}").exists() else None
        )
        tools[name] = {"path": path}
        if path:
            cmd = [path, "--version"]
            proc = subprocess.run(check=False, args=cmd, capture_output=True, text=True, timeout=15)
            tools[name]["version"] = (
                proc.stdout.splitlines()[0] if proc.stdout else proc.stderr[:200]
            )
    try:
        path = blender_bin()
        tools["blender"] = {"path": path}
        if probe:
            expr = "import bpy,json; p=bpy.context.preferences.addons['cycles'].preferences; p.get_devices(); print('CAPABILITIES='+json.dumps({'version':bpy.app.version_string,'devices':[{'name':d.name,'type':d.type} for d in p.devices]}))"
            p = subprocess.run(
                check=False,
                args=[path, "-b", "--factory-startup", "--python-expr", expr],
                capture_output=True,
                text=True,
                timeout=60,
            )
            tools["blender"]["returncode"] = p.returncode
            for line in p.stdout.splitlines():
                if line.startswith("CAPABILITIES="):
                    tools["blender"].update(json.loads(line.split("=", 1)[1]))
    except RuntimeError as e:
        tools["blender"] = {"error": str(e)}
    packages = {}
    for name in [
        "openai",
        "pymupdf",
        "opencv-python-headless",
        "shapely",
        "numpy",
        "pydantic",
        "pillow",
        "pytest",
        "ruff",
    ]:
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            packages[name] = None
    return {
        "os": platform.platform(),
        "architecture": platform.machine(),
        "python": sys.version,
        "tools": tools,
        "packages": packages,
        "openai_key_present": bool(os.getenv("OPENAI_API_KEY")),
        "essential_available": sys.version_info >= (3, 12)
        and all(packages.values())
        and "path" in tools["blender"]
        and bool(tools["node"]["path"]),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    parser.add_argument("--probe-blender", action="store_true")
    args = parser.parse_args()
    result = report(args.probe_blender)
    if args.output:
        write_json(args.output, result)
    print(json.dumps(result, indent=2))

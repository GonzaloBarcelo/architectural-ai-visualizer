"""Exercise the pinned upstream MCP server and real Blender addon over stdio.

Run with agents/.venv-mcp/bin/python agents/mcp_smoke.py --blender /path/to/blender.
Creates an isolated factory-startup GUI process, shuts it down, changes no preferences.
"""

import argparse
import asyncio
import json
import os
import shutil
import socket
import subprocess
import sys
import time
from importlib.metadata import version
from pathlib import Path

from blender_mcp.addon_manager import get_bundled_addon_path
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def exercise(port, output):
    env = {
        **os.environ,
        "BLENDER_HOST": "127.0.0.1",
        "BLENDER_PORT": str(port),
        "BLENDER_MCP_SAFE_MODE": "1",
        "DISABLE_TELEMETRY": "true",
    }
    executable = str(Path(sys.executable).parent / "mcp-for-blender")
    report = {
        "package": version("mcp-for-blender"),
        "host": "127.0.0.1",
        "safe_mode": True,
        "telemetry_disabled": True,
        "checks": [],
    }
    async with (
        stdio_client(StdioServerParameters(command=executable, env=env)) as streams,
        ClientSession(*streams) as session,
    ):
        await session.initialize()
        available = await session.list_tools()
        report["tools"] = [tool.name for tool in available.tools]
        assert "execute_blender_code" in report["tools"]

        async def run(label, code, expected):
            response = await session.call_tool(
                "execute_blender_code",
                {
                    "code": code,
                    "user_prompt": "Create a test object. Read its dimensions. Move it. Save a Blender scene. Obtain a visual or scene inspection result.",
                },
            )
            value = "\n".join(item.text for item in response.content if hasattr(item, "text"))
            ok = expected in value and not response.isError
            report["checks"].append({"name": label, "passed": ok, "response": value})
            if not ok:
                raise RuntimeError(f"{label}: {value}")

        await run(
            "create_read",
            "import bpy\nbpy.ops.object.select_all(action='SELECT')\nbpy.ops.object.delete(use_global=False)\nbpy.ops.mesh.primitive_cube_add(size=2)\no=bpy.context.object\no.name='mcp-test-cube'\nbpy.context.view_layer.update()\nprint('DIMENSIONS', tuple(o.dimensions))",
            "DIMENSIONS (2.0, 2.0, 2.0)",
        )
        await run(
            "move",
            "import bpy\no=bpy.data.objects['mcp-test-cube']\no.location=(1,2,3)\nbpy.context.view_layer.update()\nprint('LOCATION', tuple(o.location))",
            "LOCATION (1.0, 2.0, 3.0)",
        )
        scene = str((output / "mcp-test.blend").resolve())
        await run(
            "save_inspect",
            f"import bpy\nbpy.ops.wm.save_as_mainfile(filepath={scene!r})\nprint('SCENE', [(o.name, tuple(o.dimensions), tuple(o.location)) for o in bpy.data.objects if o.type=='MESH'])",
            "mcp-test-cube",
        )
        await run(
            "safe_mode_rejection", "import os\nprint(os.listdir('.'))", "Rejected by safe mode"
        )
    report["passed"] = (
        all(check["passed"] for check in report["checks"]) and (output / "mcp-test.blend").is_file()
    )
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--blender", default=os.environ.get("BLENDER_BIN") or shutil.which("blender")
    )
    parser.add_argument("--output", type=Path, default=Path("outputs/mcp-smoke"))
    args = parser.parse_args()
    if not args.blender:
        parser.error("Use --blender /path/to/blender or set BLENDER_BIN")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    ready = output / "ready.json"
    ready.unlink(missing_ok=True)
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    env = {**os.environ, "DISABLE_TELEMETRY": "true"}
    with (output / "blender.log").open("w") as log:
        process = subprocess.Popen(
            [
                args.blender,
                "--factory-startup",
                "--python",
                str(Path(__file__).with_name("blender_mcp_session.py").resolve()),
                "--",
                str(get_bundled_addon_path()),
                str(port),
                str(ready),
            ],
            stdout=log,
            stderr=log,
            env=env,
        )
        try:
            until = time.monotonic() + 45
            while not ready.exists():
                if process.poll() is not None or time.monotonic() > until:
                    raise RuntimeError(f"Blender addon not ready; inspect {output / 'blender.log'}")
                time.sleep(0.2)
            report = asyncio.run(asyncio.wait_for(exercise(port, output), timeout=90))
            (output / "mcp-report.json").write_text(json.dumps(report, indent=2))
            print(
                json.dumps({"passed": report["passed"], "report": str(output / "mcp-report.json")})
            )
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
            ready.unlink(missing_ok=True)


if __name__ == "__main__":
    main()

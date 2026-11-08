"""Start an isolated GUI MCP session. Invoked by mcp_smoke.py, never in production."""

import importlib.util
import json
import os
import sys
import time
from pathlib import Path

import bpy

args = sys.argv[sys.argv.index("--") + 1 :]
addon_path, port, ready_path = args
spec = importlib.util.spec_from_file_location("architectural_test_mcp", addon_path)
addon = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = addon
spec.loader.exec_module(addon)
addon.register()
# The bounded test neither checks upstream updates nor starts external integrations.
for callback in (addon._addon_update_check_on_startup, addon._blendermcp_ensure_server_running):
    if bpy.app.timers.is_registered(callback):
        bpy.app.timers.unregister(callback)
bpy.context.scene.blendermcp_auto_start_server = False
bpy.context.scene.blendermcp_port = int(port)
server = addon.BlenderMCPServer(host="127.0.0.1", port=int(port))
server.start()
if not server.running:
    raise RuntimeError("MCP addon did not start: a GUI Blender process is required")
bpy.types.blendermcp_server = server
Path(ready_path).write_text(
    json.dumps({"pid": os.getpid(), "host": server.host, "port": server.port})
)
started = time.monotonic()


def stop_after_timeout():
    if time.monotonic() - started > 150:
        server.stop()
        bpy.ops.wm.quit_blender()
        return None
    return 1.0


bpy.app.timers.register(stop_after_timeout, first_interval=1.0)

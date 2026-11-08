# Optional Blender MCP integration

## Actual status

Tested on 2026-11-06 with **MCP for Blender 2.2.7**, MCP SDK 1.30.0, Python 3.12.16 and Blender 4.5.9 LTS on macOS arm64. The real stdio MCP server communicated with the upstream Blender addon in an isolated GUI process. `outputs/mcp-smoke/mcp-report.json` records passing operations:

1. Create a cube and measure `(2.0, 2.0, 2.0)` metres.
2. Move it and inspect `(1.0, 2.0, 3.0)`.
3. Save `outputs/mcp-smoke/mcp-test.blend` and inspect scene objects.
4. Verify safe mode rejects an `os` import.

The process was terminated after testing and no persistent user preferences or global Codex configuration were changed. The current Codex chat has **not** been restarted with this server, so native Blender tools in this chat are not claimed. The provided Codex configuration is ready to register the verified integration.

## Reproduce the isolated test

From the repository root:

```sh
uv venv --python 3.12 agents/.venv-mcp
uv pip sync --python agents/.venv-mcp/bin/python agents/mcp-requirements.txt
agents/.venv-mcp/bin/python agents/mcp_smoke.py --blender /Applications/Blender.app/Contents/MacOS/Blender
```

Replace `--blender` with the local executable, or set `BLENDER_BIN`. The script starts a fresh GUI Blender process with `--factory-startup`, imports the installed package's bundled addon without copying it, and connects on a free loopback port. It does not use an existing Blender process. All outputs stay under ignored `outputs/mcp-smoke`. The temporary Blender session disables its automatic update check; it ends on success/failure and has a bounded timeout.

The addon explicitly refuses background startup because Blender's normal GUI timers drain its command queue. This is why the smoke uses a GUI instance. The production pipeline uses headless `bpy` scripts and has no MCP dependency.

## Register with Codex for interactive work

The [maintainer's setup](https://github.com/ahujasid/mcp-for-blender#codex) documents `codex mcp add`. A reviewed, pinned entry with safe defaults is in `agents/codex-mcp.example.toml`. Register using:

```sh
codex mcp add architectural-blender \
  --env BLENDER_HOST=127.0.0.1 \
  --env BLENDER_PORT=9876 \
  --env BLENDER_MCP_SAFE_MODE=1 \
  --env DISABLE_TELEMETRY=true \
  -- uvx --python 3.12 mcp-for-blender==2.2.7
codex mcp list
```

This command changes Codex user configuration; it has **not** been run automatically. Alternatively merge the example into the trusted workspace's `.codex/config.toml` using supported Codex workspace configuration. Do not overwrite unrelated entries. GUI clients may need the absolute `uvx` path from `command -v uvx`. Restart the client to expose tools.

For a persistent Blender GUI addon, the maintainer provides:

```sh
uvx --python 3.12 mcp-for-blender==2.2.7 install-addon
```

This copies the bundled addon into Blender's user addon directory; the inspected implementation backs up matching old copies. Enable it in Blender's Preferences → Add-ons, then use the MCP sidebar. Keep bind address `localhost` or `127.0.0.1`, port 9876, remote connections off, external asset integrations off and telemetry consent off. This persistent installation was not required for the isolated test.

## Review and boundaries

- Source: [ahujasid/mcp-for-blender](https://github.com/ahujasid/mcp-for-blender), reviewed commit `2e4b0bc294694b1570d76ed01be657c22e6d02a0`, package metadata version 2.2.7. Community MIT project, not affiliated with Blender Foundation.
- The package was installed through uv from its pinned package distribution. No `curl | sh`, setup wizard or third-party installation script was executed.
- TCP communication to the addon has no authentication or encryption. This project binds only to loopback. Safe mode is enforced in the MCP server, not on arbitrary direct socket clients; it does not make an exposed addon safe.
- `BLENDER_MCP_SAFE_MODE=1` checks Python before forwarding; Blender modeling, saving and export operators remain available. Never treat it as a general sandbox.
- `DISABLE_TELEMETRY=true` disables even the upstream package's minimal anonymous usage telemetry. Content telemetry remains off.
- This integration is optional development tooling. Source geometry, final QA, renders and exports always use the deterministic production pipeline.

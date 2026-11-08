---
name: blender-architectural-modeling
description: Build or repair deterministic Blender architecture when converting validated metric geometry into an editable scene; excludes freeform decoration.
---

# Blender Architectural Modeling

Use [build_scene.py](../../../pipelines/blender/build_scene.py) through `uv run python -m pipelines.run --input plan.pdf --output outputs/project-id`. Production uses headless Blender and must not require an MCP server.

Inspect the geometry schema first. Preserve metre units, source identifiers, floor IDs, and separate authoritative meshes from lighting/cameras/decoration. Start a clean scene for reproducibility. Extrude verified wall polygons, cut only specified openings, and build roofs only when specified. Save `scene.blend` before exporting browser assets.

Measure evaluated Blender mesh extents and compare them with the source; object metadata alone is not proof of fidelity. Test wall placement, thickness, height, holes, scene units, and missing IDs. Optional interactive development uses the reviewed loopback-only integration in [BLENDER_MCP.md](../../../docs/BLENDER_MCP.md).

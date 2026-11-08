---
name: architectural-rendering
description: Render architectural presentation or geometry review images from a validated Blender scene using reproducible clay, preview, and final settings.
---

# Architectural Rendering

Use [build_scene.py](../../../pipelines/blender/build_scene.py) through `uv run python -m pipelines.run --input plan.pdf --output outputs/project-id`. Read its CLI and render configuration before selecting a preset.

Save the exact camera, resolution, samples, seed, light and material configuration with the outputs. Derive cameras from scene extents; only provide an interior camera when the geometry can support it. Keep geometry identical across render and GLB export. Material choices are presentation decisions, not measured building facts.

Review clay geometry first, preview framing second, then final Cycles output. Check the actual images for blank frames, clipped architecture, implausible lighting and hidden openings. CPU is the portable fallback; claim GPU rendering only after executing it. Never use generative image edits as geometric evidence. The [OpenAI architectural example](https://developers.openai.com/blog/architectural-visualization-with-astra) is a workflow reference, not a fidelity guarantee.

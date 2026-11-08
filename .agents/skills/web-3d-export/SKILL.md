---
name: web-3d-export
description: Export, optimize, and validate architectural GLB assets for the browser while preserving metric dimensions, hierarchy and source object IDs.
---

# Web 3D Export

Use [build_scene.py](../../../pipelines/blender/build_scene.py) through the root pipeline. Then use the actual scripts declared in [site/package.json](../../../site/package.json) for optimization and GLB validation; run `npm run build` inside `site`.

Export only approved architecture from the same scene used for renders. Preserve custom IDs and floor/kind metadata. Use lossless deduplication and pruning where safe; avoid simplification or quantization that changes measured extents. Verify pre/post-optimization bounds and identifiers. Load the final asset with Three.js and verify the viewer in a real browser, including relative asset URLs and failure recovery.

Applicable upstream guidance: [OpenAI web 3D asset pipeline](https://github.com/openai/plugins/blob/main/plugins/game-studio/skills/web-3d-asset-pipeline/SKILL.md) and [React Three Fiber game skill](https://github.com/openai/plugins/blob/main/plugins/game-studio/skills/react-three-fiber-game/SKILL.md). These project instructions are original, architecture-specific text; upstream files are linked, not redistributed. See [REFERENCES.md](../../../docs/REFERENCES.md) for provenance and license evaluation.

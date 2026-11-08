# References and compatibility review

Reviewed 2026-11-06. Links are upstream references; generated private/client assets are never part of reference packages.

| Resource | Verified finding | Project decision |
| --- | --- | --- |
| [OpenAI architectural visualization example](https://developers.openai.com/blog/architectural-visualization-with-astra) | Official architectural workflow reference. | Adopt traceable PDF → model → render → viewer flow; do not infer accuracy from an attractive render. |
| [OpenAI PDF inputs](https://developers.openai.com/api/docs/guides/file-inputs) | Official Responses API guide accepts PDF inputs; vision-capable models can use page images and extracted text. | Vision proposals require credentials and upload authorization; deterministic extraction works offline. |
| [Codex skills](https://developers.openai.com/codex/skills) | Redirects to [Build skills](https://learn.chatgpt.com/docs/build-skills). | Six repository skills live in `.agents/skills`, with executable project references. |
| [openai/skills](https://github.com/openai/skills) | Its README explicitly marks this repository deprecated and points to `openai/plugins`. | Do not install the deprecated catalog. Use available maintained skills and original project workflows. |
| [OpenAI web 3D asset pipeline](https://github.com/openai/plugins/blob/main/plugins/game-studio/skills/web-3d-asset-pipeline/SKILL.md) | Live skill recommends GLB/glTF, glTF Transform, stable transforms/units and runtime loading validation. | Export measured architecture, optimize conservatively, check dimensions and source IDs after optimization. |
| [OpenAI React Three Fiber skill](https://github.com/openai/plugins/blob/main/plugins/game-studio/skills/react-three-fiber-game/SKILL.md) | Live skill separates scene root/camera controls from React DOM controls. | R3F/Drei viewer with accessible DOM navigation; no game physics dependencies are needed. |
| [MCP for Blender](https://github.com/ahujasid/mcp-for-blender) | Maintained community package `mcp-for-blender==2.2.7`, Python >=3.10. Reviewed main commit `2e4b0bc294694b1570d76ed01be657c22e6d02a0`, dated 2026-11-04. | Optional isolated development adapter; production stays headless. See `BLENDER_MCP.md`. |
| [ChatGPT Sites](https://learn.chatgpt.com/docs/sites) | Official service documentation; local installed Sites skill provides static hosting manifest and save-only workflow. | Build portable Vite `dist/`; save for review only, with no public production deployment. |

## Provenance and licenses

The six architectural skills are original project instructions, not copies of upstream skill files. They link to upstream references and adapt general workflow ideas to the project's fidelity requirements. No third-party skill text, asset or installer is vendored.

The reviewed `openai/plugins` tree did not expose a root or Game Studio license file. Do not assume a redistribution license; link to those skills instead of copying their text. Re-evaluate licensing before vendoring.

MCP for Blender declares MIT in its `pyproject.toml` and includes an [MIT LICENSE](https://github.com/ahujasid/mcp-for-blender/blob/main/LICENSE). The optional package is installed in an ignored environment; its package metadata retains that license. The project-written smoke driver imports its bundled addon; it does not copy or alter upstream source.

## Scope limits

No research reference grants geometric verification, API credentials, publishing authority or rights to third-party render assets. No remote one-line shell installer was executed. The synthetic PDF is test data; arbitrary plans still require semantic and dimensional review.

# Current local-only workflow — 2026-11-09

The PDF upload/review/generation flow runs on the local FastAPI server:

```sh
uv sync --locked
npm --prefix site ci
npm --prefix site run build
uv run python -m pipelines.web.server --port 5174
```

Review at http://127.0.0.1:5174/#new-project. Do not use a static HTTP server or Vite preview for generation: they cannot execute Blender or the API.

No deployment or publication was performed. The previously saved Sites version 1 below is a historical static viewer; it does **not** include the new server workflow and was not updated. It is not the current review target. Publishing a working PDF service would require a separate, explicitly authorized architecture for server jobs and storage.

---

# Local review and ChatGPT Sites

## Actual status — 2026-11-08

The application is built and available locally at **http://127.0.0.1:5174/** while the review server is running. This is the production `site/dist` build, including the synthetic GLB and render gallery.

**Sites version 1 was saved, not deployed.** Project ID: `appgprj_6aee2bdc87a08191934c4c83b3299952`. Saved version ID: `appgprj_6aee2bdc87a08191934c4c83b3299952~appgver_5b54ed0f8840819194067db22e42d358`. Source commit: `c91515451f9688e3eee44f374fdf822e5cf2af58` in the Sites source repository. `deployment_id` is null. There is no claimed public or private production URL.

The archive `outputs/sites-review.tar.gz` was saved with the source SHA; it contains the static build and `.openai/hosting.json`. Source was pushed via the official Sites helper with an ephemeral credential passed through stdin. No credential is stored in the repository. The Sites copy includes only synthetic presentation assets; it contains no client PDF.

## Review locally

```sh
npm --prefix site run dev
# Or review the production build:
npm --prefix site run preview -- --port 5174
```

For a dependency-free static preview after generating the build:

```sh
python3 -m http.server 5174 --bind 127.0.0.1 --directory site/dist
```

Open the localhost URL printed by the server. Stop it with Ctrl-C when finished. No hosting account is necessary.

## Rebuild or import into Sites later

1. Run the validated pipeline and `npm --prefix site run build`.
2. Reuse the `project_id` in `site/.openai/hosting.json`. Never register a second Site for the same local project.
3. Stage only `site/` source plus explicitly authorized assets in a separate Sites checkout; exclude credentials, node_modules, source PDFs and backend output directories.
4. Use the official Sites source helper to push the exact source commit and package the built `dist` directory. Manifest is static, `directory: "dist"`.
5. Save a version using that pushed commit and matching archive. **Saving is sufficient for review; do not call a deploy operation unless the user authorizes publication.**

Prompt for a later ChatGPT Sites review:

> Open Architectural AI Visualizer, project appgprj_6aee2bdc87a08191934c4c83b3299952, saved version 1. Review the React/Vite static application, its GLB viewer, render gallery, camera controls and mobile layout. The assets are labeled synthetic test data. Keep the Site unpublished. Do not change its audience or deploy without my authorization.

## Validation checklist

- Production build succeeds and uses relative base paths.
- `project/manifest.json`, `project/model.glb` and all gallery WebP paths return 200.
- WebGL visibly renders the GLB, with metadata and metre dimensions retained.
- Exterior/axonometric/top cameras, floor selector, wall toggle and reset work.
- Roof control reflects whether a roof actually exists.
- Keyboard controls and mobile layout remain usable.
- No private source PDF or credentials are included in the Site source or archive.

Workflow reference: [ChatGPT Sites](https://learn.chatgpt.com/docs/sites). The plugin's current static hosting contract is used; no direct Codex CLI deployment capability is assumed.

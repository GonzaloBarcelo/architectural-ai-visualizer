# Architectural AI Visualizer

The uploaded source drawing (PDF or DWG/DXF) is authoritative. Never invent architectural dimensions. Unknown inputs must stop at review.
Separate verified, inferred, and missing facts; preserve source page, coordinates (or DXF handles, layers, blocks and converter), source hash, configuration and code revision.
Production runs use deterministic headless Blender; MCP and vision are optional. Do not publish or upload client drawings (PDF, DWG, DXF).
Use `uv sync --locked`, `uv run pytest`, `uv run ruff check .`, and `cd site && npm ci && npm run build`.
Track actual evidence and incomplete work in docs/IMPLEMENTATION_STATUS.md. Feature branches and atomic commits; no forced pushes.
Generated outputs and credentials are ignored. Only synthetic assets may enter a Site review package.

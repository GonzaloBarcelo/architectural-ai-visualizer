---
name: architectural-quality-gate
description: Audit geometric fidelity and rendered output before architectural delivery, including source-to-scene comparison and critical-failure blocking.
---

# Architectural Quality Gate

Run the pipeline quality gate through `uv run python -m pipelines.run --input plan.pdf --output outputs/project-id`; inspect [check.py](../../../pipelines/quality/check.py) and its generated `quality-report.json`.

Compare actual scene measurements with validated source geometry in metres using an explicit tolerance. Check wall footprints and thickness, openings, floor extents, scale, expected IDs, invalid meshes, and top-down correspondence. Treat blank image checks as necessary but insufficient visual evidence. Inspect the orthographic overlay and presentation renders.

Fail final delivery on critical geometric errors or unreviewed dimensions. Exercise a deliberately perturbed scene or geometry in tests to prove the gate can fail. Record any checks not implemented or untestable instead of converting them to pass. The PDF and its source digest remain authoritative.

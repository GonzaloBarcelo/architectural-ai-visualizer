---
name: architectural-geometry
description: Normalize and validate source-linked architectural geometry when converting reviewed PDF evidence into metric floors, walls, rooms, and openings.
---

# Architectural Geometry

Read [schema.py](../../../pipelines/geometry/schema.py) and [normalize.py](../../../pipelines/geometry/normalize.py) before changing normalization. Execute `uv run python -m pipelines.run --input plan.pdf --output outputs/project-id` or supply the explicitly reviewed geometry through its documented `--geometry` option.

Separate verified, inferred, and missing evidence. Calibration must refer to measured PDF coordinates and an explicit metric measurement; never assume a scale from page size. Keep vertical dimensions and floor elevations explicit. Reject invalid polygons, zero dimensions, unmatched floors/walls, out-of-bounds openings, and conflicts between annotation and drawn extent.

The synthetic format deliberately uses PDF annotations paired with actual drawn shapes. Passing it does not establish arbitrary-plan reconstruction. Review real plans against the source digest and coordinates before marking any entity verified. Run `uv run pytest` after schema or geometry changes; exercise rejection cases as well as valid fixtures.

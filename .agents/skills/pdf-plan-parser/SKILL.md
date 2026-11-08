---
name: pdf-plan-parser
description: Extract source-linked evidence from architectural PDFs when inspecting vector plans or scans; does not approve ambiguous geometry.
---

# Pdf Plan Parser

Run `uv run python -m pipelines.pdf.extract --input plan.pdf --output outputs/review` from the repository root. The executable is [extract.py](../../../pipelines/pdf/extract.py).

Inspect `extraction.json` together with the rendered page PNGs. PDF points have their origin at the top left; raster candidates remain in PDF coordinates after rescaling. Preserve original page indices, vector primitive indices, annotations, text, and the SHA-256 digest. Compare drawn marks with dimension text before proposing a calibration.

Use [vision.py](../../../pipelines/pdf/vision.py) only with explicit upload authorization and credentials. Treat its semantics as proposals. A scan without a verified scale or a plan without heights must stop at a review artifact. Never turn a Hough line into a verified wall merely because it is long.

Generate only the labeled fixture with `uv run python -m pipelines.pdf.synthetic --output outputs/demo-001/original.pdf` to test extraction. See [the official PDF input guide](https://developers.openai.com/api/docs/guides/file-inputs) for Responses API file semantics.

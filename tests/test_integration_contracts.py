"""Cross-stage safety and provenance invariants."""

from copy import deepcopy

import pytest

from pipelines.common import blender_bin
from pipelines.run import source_check


def test_available_blender_is_executable():
    import os

    assert os.access(blender_bin(), os.X_OK)


def test_reviewed_geometry_must_match_pdf(geometry, parsed):
    source_check(geometry, parsed)
    altered = deepcopy(parsed)
    altered["source"]["sha256"] = "0" * 64
    with pytest.raises(ValueError, match="SHA-256"):
        source_check(geometry, altered)


def test_reviewed_vertices_must_match_source_coordinates(geometry, parsed):
    geometry.walls[0].polygon[0] = (20, 20)
    with pytest.raises(ValueError, match="source coordinates"):
        source_check(geometry, parsed)

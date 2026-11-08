from pathlib import Path

import pytest

from pipelines.geometry.normalize import normalize
from pipelines.pdf.extract import extract
from pipelines.pdf.synthetic import create


@pytest.fixture
def parsed(tmp_path: Path):
    pdf = create(tmp_path / "original.pdf")
    return extract(pdf, tmp_path / "evidence")


@pytest.fixture
def geometry(parsed):
    return normalize(parsed, "test-001")

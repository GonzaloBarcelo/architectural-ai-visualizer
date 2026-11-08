import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from pipelines.pdf.vision import Proposal, interpret


def test_vision_requires_explicit_credentials(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(ValueError, match="OPENAI_API_KEY missing"):
        interpret(tmp_path / "absent.pdf", tmp_path)


def test_responses_adapter_keeps_proposals_unverified(tmp_path):
    pdf = tmp_path / "test.pdf"
    pdf.write_bytes(b"%PDF-test")
    proposal = Proposal(
        summary="Drawing evidence",
        wall_observations=["Page 1 wall"],
        opening_observations=[],
        written_measurements=["10 m"],
        uncertainties=["Height absent"],
        missing_information=["Height"],
    )
    parse = Mock(return_value=SimpleNamespace(output_parsed=proposal, id="test-response"))
    client = SimpleNamespace(responses=SimpleNamespace(parse=parse))
    interpret(pdf, tmp_path, client=client)
    kwargs = parse.call_args.kwargs
    assert kwargs["store"] is False
    assert kwargs["text_format"] is Proposal
    assert kwargs["input"][0]["content"][0]["type"] == "input_file"
    assert kwargs["input"][0]["content"][0]["file_data"].startswith("data:application/pdf;base64,")
    result = json.loads((tmp_path / "vision-proposal.json").read_text())
    assert result["status"] == "inferred"
    assert result["proposal"]["missing_information"] == ["Height"]

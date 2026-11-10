"""OpenAI call layer: an answer cut off by the output budget is retried once with more room."""

from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from pipelines.web.grounded import MAX_OUTPUT_RETRY, Calls


class Answer(BaseModel):
    value: int


def usage(out):
    return SimpleNamespace(output_tokens=out, model_dump=lambda: {"output_tokens": out})


def incomplete(out):
    return SimpleNamespace(
        output_parsed=None,
        status="incomplete",
        incomplete_details=SimpleNamespace(reason="max_output_tokens"),
        output=[],
        usage=usage(out),
        id="cut",
    )


def client(responses, seen):
    def parse(**kwargs):
        seen.append(kwargs["max_output_tokens"])
        return responses.pop(0)

    return SimpleNamespace(responses=SimpleNamespace(parse=parse))


def test_running_out_of_output_tokens_retries_once_with_a_larger_budget(tmp_path):
    seen = []
    done = SimpleNamespace(output_parsed=Answer(value=7), usage=usage(20000), id="ok")
    calls = Calls(client([incomplete(32000), done], seen), "gpt-5.4", None, tmp_path)
    assert calls.call("doubts", "k", Answer, "i", []).value == 7
    assert seen == [32000, MAX_OUTPUT_RETRY]
    assert calls.log[-1]["max_output_tokens"] == MAX_OUTPUT_RETRY


def test_a_second_cut_or_a_refusal_is_reported_with_its_reason(tmp_path):
    seen = []
    calls = Calls(client([incomplete(32000), incomplete(64000)], seen), "gpt-5.4", None, tmp_path)
    with pytest.raises(ValueError, match="reason=max_output_tokens"):
        calls.call("doubts", "k", Answer, "i", [])
    assert seen == [32000, MAX_OUTPUT_RETRY]
    refused = SimpleNamespace(
        output_parsed=None,
        status="completed",
        incomplete_details=None,
        output=[SimpleNamespace(content=[SimpleNamespace(type="refusal", refusal="No puedo")])],
        usage=usage(10),
        id="no",
    )
    calls = Calls(client([refused], []), "gpt-5.4", None, tmp_path)
    with pytest.raises(ValueError, match="refusal=No puedo"):
        calls.call("doubts", "k", Answer, "i", [])

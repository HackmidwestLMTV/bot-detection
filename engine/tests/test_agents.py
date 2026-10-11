"""Exercise the actual Strands/OpenAI SDK loop against an in-memory HTTP provider."""

import asyncio
import json

import pytest

pytest.importorskip("strands", reason="install engine/requirements-agents.txt for Phase 2 tests")

import httpx
from openai import AsyncOpenAI
from pydantic import ValidationError

from engine.agents.common import ConfigurationError, ModelSettings, load_settings, make_model
from engine.agents.hooks import RequestBudget, SmokeLimitError
from engine.agents.schemas import RoundReport
from engine.agents.smoke import EXPECTED_REPORT, check_denial, run_smoke


class ScriptedProvider:
    def __init__(self, mode="normal"):
        self.requests = []
        self.mode = mode

    def respond(self, request):
        assert request.url.host == "sdk-smoke.invalid"
        body = json.loads(request.content)
        assert body["stream"] is False and body["max_tokens"] == 1500
        assert "tools" not in body or len(body["tools"]) > 0
        self.requests.append(body)
        tools = {entry["function"]["name"]: entry["function"] for entry in body.get("tools", [])}
        last_role = body["messages"][-1]["role"]
        message = {"role": "assistant", "content": "OK"}
        finish = "stop"
        if tools and (last_role != "tool" or self.mode == "repeat_denied") and self.mode != "no_tools":
            name = next(iter(tools))
            arguments = {"record_probe": {"value": 7}, "blocked_probe": {},
                         "activate_variant": {"variant_id": "smoke_variant"}, "RoundReport": EXPECTED_REPORT}[name]
            message = {"role": "assistant", "content": None, "tool_calls": [{"id": "call_" + str(len(self.requests)),
                "type": "function", "function": {"name": name, "arguments": json.dumps(arguments)}}]}
            finish = "tool_calls"
        return httpx.Response(200, json={"id": "completion_test", "object": "chat.completion", "created": 1,
            "model": "test-model", "choices": [{"index": 0, "finish_reason": finish, "message": message}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20}})


async def run_offline(provider, check=None):
    async with httpx.AsyncClient(transport=httpx.MockTransport(provider.respond)) as transport:
        async with AsyncOpenAI(base_url="https://sdk-smoke.invalid/v1", api_key="test-only", max_retries=0,
                               http_client=transport) as client:
            settings = ModelSettings(provider="akamai", model_id="test-model")
            factory = lambda: make_model(settings, client=client)
            budget = RequestBudget(min_interval_s=0)
            if check is not None:
                return await check(factory, budget)
            report = await run_smoke(factory, budget, attempts=2)
            assert report["model_calls"] == len(provider.requests)
            return report


def test_full_sdk_smoke_offline():
    provider = ScriptedProvider()
    report = asyncio.run(run_offline(provider))
    assert report["status"] == "passed", report
    assert [row["check"] for row in report["checks"]] == ["greeting", "tool_call", "structured_output", "tool_denial", "approval_interrupt"]
    assert report["checks"][2]["detail"]["validated_runs"] == 3
    assert report["checks"][4]["detail"]["y"]["executions"] == 1
    assert report["checks"][4]["detail"]["n"]["executions"] == 0
    # The model actually receives the hook's denial, not just an internal flag.
    assert any(message["role"] == "tool" and "DENIED" in str(message.get("content"))
               for request in provider.requests for message in request["messages"])


def test_unsupported_tool_host_fails_after_two_attempts():
    report = asyncio.run(run_offline(ScriptedProvider("no_tools")))
    assert report["status"] == "failed"
    failures = [row for row in report["checks"] if row["status"] == "failed"]
    assert len(failures) == 2 and all(row["check"] == "tool_call" for row in failures)


def test_repeated_denial_cannot_loop_forever():
    provider = ScriptedProvider("repeat_denied")
    with pytest.raises(SmokeLimitError):
        asyncio.run(run_offline(provider, check_denial))
    assert len(provider.requests) == 4


def test_request_budget_paces_and_limits_calls():
    now = [0.0]
    waits = []

    def sleep(delay):
        waits.append(delay)
        now[0] += delay

    budget = RequestBudget(max_calls=2, min_interval_s=3, clock=lambda: now[0], sleep=sleep)
    budget.acquire()
    now[0] += 1
    budget.acquire()
    assert waits == [2]
    with pytest.raises(SmokeLimitError):
        budget.acquire()


def test_settings_and_nonstreaming_provider():
    settings = load_settings({"AKAMAI_BASE_URL": "https://sdk-smoke.invalid/v1", "AKAMAI_API_KEY": "secret-test-key",
                              "MODEL_ID": "test-model"})
    assert "secret-test-key" not in repr(settings)
    model = make_model(settings)
    assert model.config["stream"] is False and model.config["params"]["max_tokens"] == 1500
    assert model.client_args["max_retries"] == 0
    assert model.client_args["timeout"] == 30
    assert load_settings({"USE_BEDROCK": "1", "BEDROCK_MODEL_ID": "account-model"}).provider == "bedrock"
    assert load_settings({"BEDROCK_MODEL_ID": "account-model"}, provider="bedrock").provider == "bedrock"


@pytest.mark.parametrize("env", [{}, {"USE_BEDROCK": "1"}, {"USE_BEDROCK": "maybe"}, {"MODEL_MIN_INTERVAL_S": "nan"}])
def test_missing_or_invalid_configuration(env):
    with pytest.raises(ConfigurationError):
        load_settings(env)


def test_embedded_credentials_never_appear_in_configuration_error():
    with pytest.raises(ConfigurationError) as result:
        load_settings({"AKAMAI_BASE_URL": "https://user:secret-test-key@example.com/v1", "AKAMAI_API_KEY": "key", "MODEL_ID": "model"})
    assert "secret-test-key" not in str(result.value)


def test_round_report_rejects_impossible_counts():
    assert RoundReport(**EXPECTED_REPORT).attempts == 2
    with pytest.raises(ValidationError):
        RoundReport(**{**EXPECTED_REPORT, "passed": 3})

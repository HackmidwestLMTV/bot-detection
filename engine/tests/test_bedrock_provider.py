"""Exercise the AWS Bedrock branch of the model factory without AWS credentials.

`engine.agents.common.make_model` has a Bedrock branch that had no test coverage:
`engine/tests/test_agents.py` only checks that `load_settings` *selects* the
provider. These tests drive the real factory into `strands.models.BedrockModel`,
assert how the Bedrock-Runtime client is wired, and then run a complete Strands
agent loop (tool call, denial hook, typed structured output) against a stubbed
botocore Converse transport. No network call and no credential is involved:
`botocore.stub.Stubber` intercepts at `before-call`, which is ahead of SigV4
signing, and the AWS environment is emptied for every test.
"""

import asyncio
import contextlib
import json

import pytest

for dependency in ("strands", "boto3", "botocore", "dotenv"):
    pytest.importorskip(dependency, reason="install engine/requirements-agents.txt for agent tests")

from botocore.stub import Stubber
from strands import Agent, tool
from strands.models import BedrockModel
from strands.models.bedrock import DEFAULT_BEDROCK_REGION
from strands.types.exceptions import EventLoopException, ModelThrottledException

from engine.agents.common import ConfigurationError, load_settings, make_model
from engine.agents.hooks import RequestBudget, SmokeHooks
from engine.agents.schemas import RoundReport

MODEL_ID = "test.anthropic.stub-model-v1:0"
REGION = "eu-central-1"
BEDROCK_ENV = {"USE_BEDROCK": "1", "BEDROCK_MODEL_ID": MODEL_ID, "AWS_REGION": REGION,
               "MODEL_MIN_INTERVAL_S": "1"}
# Facts the stubbed model is told to report, so an invented report would be visible.
STUB_REPORT = {"round": 2, "agent": "red", "attempts": 3, "passed": 1,
               "best_params": {"lag_ms": 180.0, "noise_px": 1.5}, "what_changed": "Offline Bedrock stub",
               "evidence": ["bedrock_att_1"]}
USAGE = {"usage": {"inputTokens": 11, "outputTokens": 7, "totalTokens": 18}, "metrics": {"latencyMs": 5}}

AWS_ENVIRONMENT_KEYS = ("AWS_PROFILE", "AWS_DEFAULT_PROFILE", "AWS_REGION", "AWS_DEFAULT_REGION",
                        "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN",
                        "AWS_BEARER_TOKEN_BEDROCK", "AWS_ENDPOINT_URL", "AWS_ENDPOINT_URL_BEDROCK_RUNTIME")


@pytest.fixture(autouse=True)
def isolated_aws_environment(monkeypatch, tmp_path):
    """Never read a developer's real profile, region, or credentials from this test."""
    for name in AWS_ENVIRONMENT_KEYS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("AWS_CONFIG_FILE", str(tmp_path / "absent-config"))
    monkeypatch.setenv("AWS_SHARED_CREDENTIALS_FILE", str(tmp_path / "absent-credentials"))
    monkeypatch.setenv("AWS_EC2_METADATA_DISABLED", "true")


def tool_use_turn(name, arguments):
    return {"output": {"message": {"role": "assistant", "content": [
        {"toolUse": {"toolUseId": "stub_use_" + name, "name": name, "input": arguments}}]}},
        "stopReason": "tool_use", **USAGE}


def text_turn(text):
    return {"output": {"message": {"role": "assistant", "content": [{"text": text}]}},
            "stopReason": "end_turn", **USAGE}


class StubbedBedrock:
    """Records the Converse parameters the product's own configuration produces."""

    def __init__(self, model):
        self.model = model
        self.converse = []
        self.converse_stream = []


@contextlib.contextmanager
def stubbed_bedrock(*, turns=(), client_errors=(), environ=None, request_timeout=30.0):
    settings = load_settings(dict(environ or BEDROCK_ENV))
    model = make_model(settings, request_timeout=request_timeout)
    recorder = StubbedBedrock(model)
    stubber = Stubber(model.client)
    for turn in turns:
        stubber.add_response("converse", turn)
    for code, message in client_errors:
        stubber.add_client_error("converse", service_error_code=code, service_message=message,
                                 http_status_code=429)
    stubber.activate()
    # Stubber short-circuits at before-call; these fire earlier, so they see every attempt.
    model.client.meta.events.register("provide-client-params.bedrock-runtime.Converse",
                                      lambda params, **kwargs: recorder.converse.append(params))
    model.client.meta.events.register("provide-client-params.bedrock-runtime.ConverseStream",
                                      lambda params, **kwargs: recorder.converse_stream.append(params))
    try:
        yield recorder
    finally:
        stubber.deactivate()


def new_agent(model, hooks, tools=()):
    return Agent(model=model, tools=list(tools), hooks=list(hooks), callback_handler=None, retry_strategy=None,
                 system_prompt="You are verifying the Bedrock provider with disposable in-memory tools.")


def unwrap(exc):
    while isinstance(exc, EventLoopException):
        exc = exc.original_exception
    return exc


def test_use_bedrock_flag_spellings_select_bedrock_without_akamai_credentials():
    akamai = {"AKAMAI_BASE_URL": "https://sdk-smoke.invalid/v1", "AKAMAI_API_KEY": "secret-test-key",
              "MODEL_ID": "akamai-model"}
    for flag in ("1", "true", "TRUE", " True "):
        settings = load_settings({**akamai, "USE_BEDROCK": flag, "BEDROCK_MODEL_ID": MODEL_ID})
        assert settings.provider == "bedrock"
        assert settings.model_id == MODEL_ID
        # Bedrock settings must not carry the OpenAI-compatible endpoint's credentials.
        assert settings.base_url == "" and settings.api_key == ""
        assert "secret-test-key" not in repr(settings)
    assert load_settings({**akamai, "USE_BEDROCK": "false"}).provider == "akamai"


def test_bedrock_region_defaults_to_us_east_1_and_not_the_sdk_default():
    settings = load_settings({"USE_BEDROCK": "1", "BEDROCK_MODEL_ID": MODEL_ID})
    assert settings.region == "us-east-1"
    # The repository picks its own default; the SDK would otherwise choose us-west-2.
    assert settings.region != DEFAULT_BEDROCK_REGION
    assert load_settings({**BEDROCK_ENV, "AWS_REGION": "ap-southeast-2"}).region == "ap-southeast-2"


@pytest.mark.parametrize("environ, expected", [
    ({"USE_BEDROCK": "1", "BEDROCK_MODEL_ID": "   "}, "BEDROCK_MODEL_ID"),
    ({"USE_BEDROCK": "true", "AWS_REGION": REGION}, "BEDROCK_MODEL_ID"),
    ({"USE_BEDROCK": "yes", "BEDROCK_MODEL_ID": MODEL_ID}, "USE_BEDROCK"),
    ({"USE_BEDROCK": "1", "BEDROCK_MODEL_ID": MODEL_ID, "MODEL_MIN_INTERVAL_S": "0.5"}, "MODEL_MIN_INTERVAL_S"),
    ({"USE_BEDROCK": "1", "BEDROCK_MODEL_ID": MODEL_ID, "MODEL_MIN_INTERVAL_S": "31"}, "MODEL_MIN_INTERVAL_S"),
])
def test_bedrock_configuration_is_validated_before_any_aws_call(environ, expected):
    with pytest.raises(ConfigurationError) as failure:
        load_settings(environ)
    assert expected in str(failure.value)


def test_unknown_explicit_provider_is_refused():
    with pytest.raises(ConfigurationError):
        load_settings(dict(BEDROCK_ENV), provider="sagemaker")


def test_make_model_reaches_strands_bedrock_model_with_the_configured_id_and_region():
    settings = load_settings(dict(BEDROCK_ENV))
    model = make_model(settings, request_timeout=60)
    assert isinstance(model, BedrockModel)
    assert type(model).__module__ == "strands.models.bedrock"
    assert model.config["model_id"] == MODEL_ID
    # Non-streaming with a bounded output, matching the smoke/worker contract.
    assert model.config["streaming"] is False and model.config["max_tokens"] == 1500
    client = model.client
    assert client.meta.service_model.service_name == "bedrock-runtime"
    assert client.meta.service_model.metadata["signingName"] == "bedrock"
    assert client.meta.region_name == REGION
    botocore_config = client.meta.config
    assert botocore_config.read_timeout == 60 and botocore_config.connect_timeout == 10
    # Both retry layers are off: botocore here, Strands via retry_strategy=None in the agents.
    assert botocore_config.retries["total_max_attempts"] == 1
    assert "strands-agents" in (botocore_config.user_agent_extra or "")
    assert make_model(settings).client.meta.config.read_timeout == 30


def test_bedrock_bearer_token_variable_in_the_example_env_is_the_one_botocore_reads():
    """agents.env.example advertises AWS_BEARER_TOKEN_BEDROCK; confirm botocore agrees."""
    from botocore.handlers import get_bearer_auth_supported_services
    from botocore.utils import _get_bearer_env_var_name

    model = make_model(load_settings(dict(BEDROCK_ENV)))
    signing_name = model.client.meta.service_model.metadata["signingName"]
    assert signing_name in get_bearer_auth_supported_services()
    assert _get_bearer_env_var_name(signing_name) == "AWS_BEARER_TOKEN_BEDROCK"
    assert "smithy.api#httpBearerAuth" in model.client.meta.service_model.metadata["auth"]


def test_bedrock_refuses_an_injected_openai_client():
    settings = load_settings(dict(BEDROCK_ENV))
    with pytest.raises(ValueError):
        make_model(settings, client=object())
    # The Bedrock branch must not silently fall through to the OpenAI-compatible provider.
    assert isinstance(make_model(settings), BedrockModel)


def test_bedrock_agent_executes_a_tool_and_returns_a_validated_round_report():
    executions = []

    @tool
    def record_probe(value: int) -> dict:
        """Record an integer in a disposable in-memory test counter.

        Args:
            value: Integer to record for this test.
        """
        executions.append(value)
        return {"recorded": value}

    turns = [tool_use_turn("record_probe", {"value": 7}), tool_use_turn("RoundReport", STUB_REPORT)]
    with stubbed_bedrock(turns=turns) as bedrock:
        hooks = SmokeHooks(RequestBudget(min_interval_s=0), max_model_calls=4)
        agent = new_agent(bedrock.model, [hooks], [record_probe])
        result = asyncio.run(agent.invoke_async("Call record_probe once with value 7.",
                                                structured_output_model=RoundReport))
        assert executions == [7]
        assert isinstance(result.structured_output, RoundReport)
        assert result.structured_output.model_dump() == STUB_REPORT
        assert hooks.model_calls == 2
        assert {"name": "record_probe", "status": "success"} in hooks.tool_results
        # streaming=False must use Converse, never ConverseStream.
        assert len(bedrock.converse) == 2 and bedrock.converse_stream == []
        first = bedrock.converse[0]
        assert first["modelId"] == MODEL_ID
        assert first["inferenceConfig"] == {"maxTokens": 1500}
        names = {entry["toolSpec"]["name"] for entry in first["toolConfig"]["tools"]}
        assert names == {"record_probe", "RoundReport"}
        assert first["toolConfig"]["toolChoice"] == {"auto": {}}


def test_bedrock_structured_output_falls_back_to_a_forced_tool_choice():
    """Documents a per-model Bedrock requirement: Converse must honour toolChoice."""
    turns = [text_turn("All done."), tool_use_turn("RoundReport", STUB_REPORT)]
    with stubbed_bedrock(turns=turns) as bedrock:
        agent = new_agent(bedrock.model, [SmokeHooks(RequestBudget(min_interval_s=0), max_model_calls=4)])
        result = asyncio.run(agent.invoke_async("Summarise the round.", structured_output_model=RoundReport))
        assert isinstance(result.structured_output, RoundReport)
        assert [turn["toolConfig"]["toolChoice"] for turn in bedrock.converse] == [
            {"auto": {}}, {"tool": {"name": "RoundReport"}}]


def test_bedrock_tool_denial_is_delivered_to_converse_as_a_tool_result():
    executions = []

    @tool
    def blocked_probe() -> dict:
        """A disposable test tool whose execution must be denied by the SDK hook."""
        executions.append(True)
        return {"unexpected_execution": True}

    turns = [tool_use_turn("blocked_probe", {}), text_turn("The tool was denied; stopping.")]
    with stubbed_bedrock(turns=turns) as bedrock:
        hooks = SmokeHooks(RequestBudget(min_interval_s=0), deny={"blocked_probe"}, max_model_calls=4)
        agent = new_agent(bedrock.model, [hooks], [blocked_probe])
        result = asyncio.run(agent.invoke_async("Call blocked_probe once, then stop."))
        assert result.stop_reason == "end_turn"
        assert executions == [] and hooks.denied == ["blocked_probe"]
        follow_up = json.dumps(bedrock.converse[-1])
        assert "toolResult" in follow_up and "DENIED" in follow_up


def test_bedrock_throttling_is_surfaced_once_and_never_retried():
    from engine import worker

    with stubbed_bedrock(client_errors=[("ThrottlingException", "Too many requests, please wait.")]) as bedrock:
        hooks = SmokeHooks(RequestBudget(min_interval_s=0), max_model_calls=4)
        agent = new_agent(bedrock.model, [hooks])
        with pytest.raises(Exception) as failure:
            asyncio.run(agent.invoke_async("Reply with OK."))
        # Bedrock throttling becomes a typed Strands exception rather than an opaque ClientError.
        assert isinstance(unwrap(failure.value), ModelThrottledException)
        # retry_strategy=None means Strands re-issues nothing: one model call, one Converse call.
        assert hooks.model_calls == 1 and len(bedrock.converse) == 1
        # The stub answers above botocore's retry layer, so assert that layer's setting directly.
        assert bedrock.model.client.meta.config.retries["total_max_attempts"] == 1
        # The worker reports the throttle as a terminal round failure, not a retry.
        assert worker.error_data(failure.value) == {"error_type": "ModelThrottledException"}


def test_bedrock_model_access_errors_keep_the_model_id_and_region_debuggable():
    message = "You don't have access to the model with the specified model ID."
    with stubbed_bedrock(client_errors=[("AccessDeniedException", message)]) as bedrock:
        agent = new_agent(bedrock.model, [SmokeHooks(RequestBudget(min_interval_s=0), max_model_calls=4)])
        with pytest.raises(Exception) as failure:
            asyncio.run(agent.invoke_async("Reply with OK."))
        notes = " ".join(getattr(unwrap(failure.value), "__notes__", []))
        assert MODEL_ID in notes and REGION in notes


def test_bedrock_pacing_uses_the_configured_minimum_interval():
    settings = load_settings({**BEDROCK_ENV, "MODEL_MIN_INTERVAL_S": "4"})
    assert settings.min_interval_s == 4
    now, waits = [0.0], []

    def sleep(delay):
        waits.append(delay)
        now[0] += delay

    budget = RequestBudget(max_calls=2, min_interval_s=settings.min_interval_s,
                           clock=lambda: now[0], sleep=sleep)
    budget.acquire()
    budget.acquire()
    assert waits == [4]


def test_bedrock_configuration_requires_no_boto_client_for_validation(monkeypatch):
    """--check-config style validation must not construct an AWS client."""
    import boto3

    def forbidden(*args, **kwargs):
        raise AssertionError("load_settings must not create a boto3 session")

    monkeypatch.setattr(boto3, "Session", forbidden)
    assert load_settings(dict(BEDROCK_ENV)).provider == "bedrock"
    with pytest.raises(ConfigurationError):
        load_settings({"USE_BEDROCK": "1"})

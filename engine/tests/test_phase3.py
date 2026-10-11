import asyncio
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import numpy as np
import pytest
from fastapi.testclient import TestClient

from engine.calibrate import calibration_report, load_traces
from engine.forger import forge_trail
from engine.labserver import create_lab_app

ROOT = Path(__file__).resolve().parents[2]


def variant():
    return json.loads((ROOT / "contracts/fixtures/variant_v1.json").read_text())


def trace(seed=1, device="mouse"):
    # Synthetic fixtures are written only under pytest tmp_path, never human_traces.
    return {"seed": seed, "samples": forge_trail(seed, lag_ms=200, noise_px=2, submove_hz=3),
            "device": device, "pointer_type": "touch" if device == "touch" else "mouse",
            "cohort": "human_test", "round_id": None, "tester": {"consent": True}}


def test_calibration_reports_missing_evidence_without_mutating_baseline(tmp_path):
    baseline = variant()
    saved = deepcopy(baseline)
    report = calibration_report(tmp_path, baseline)
    assert not report["ready_for_review"] and report["candidate"] is None
    (tmp_path / "one.json").write_text(json.dumps(trace()))
    report = calibration_report(tmp_path, baseline)
    assert not report["ready_for_review"] and report["recordings"] == 1
    assert report["devices"]["touch"]["total"] == 0
    assert any("variation" in reason for reason in report["reasons"])
    assert baseline == saved


def test_calibration_percentiles_and_device_totals(tmp_path):
    for i in range(12):
        (tmp_path / f"trace{i}.json").write_text(json.dumps(trace(i, ("mouse", "touch", "trackpad")[i % 3])))
    rows, rejected = load_traces(tmp_path)
    report = calibration_report(tmp_path, variant())
    assert len(rows) == 12 and not rejected
    assert all(row["total"] == 4 for row in report["devices"].values())
    low, high = np.percentile([row["features"]["err_mean_px"] for row in rows], [5, 95])
    pad = .1 * (high - low)
    assert report["candidate"]["features"]["err_mean_px"] == [round(low - pad, 3), round(high + pad, 3)]
    assert report["candidate"]["enabled"] == variant()["enabled"]
    assert report["naive_forgeries"]["total"] == 12


def test_calibration_rejects_unconsented_synthetic_duplicate_and_invalid_files(tmp_path):
    good = trace()
    (tmp_path / "a.json").write_text(json.dumps(good))
    (tmp_path / "duplicate.json").write_text(json.dumps(good))
    (tmp_path / "red.json").write_text(json.dumps({**good, "cohort": "red"}))
    (tmp_path / "no_consent.json").write_text(json.dumps({**good, "tester": {"consent": False}}))
    (tmp_path / "broken.json").write_text("{")
    rows, rejected = load_traces(tmp_path)
    assert len(rows) == 1 and len(rejected) == 4
    assert any(row["reason"] == "duplicate recording" for row in rejected)


def test_lab_auth_red_only_expiration_and_no_tokens():
    now = [0]
    app = create_lab_app(clock=lambda: now[0])
    client = TestClient(app)
    assert client.get("/v1/lab/forgeries").status_code == 403
    headers = {"X-Lab-Key": "dev"}
    challenge = client.post("/v1/challenges", headers=headers, json={"session_id": "run_test"}).json()
    payload = {"samples": forge_trail(challenge["seed"]), "device": "mouse", "pointer_type": "mouse",
               "cohort": "human_test", "round_id": "run_test"}
    path = f'/v1/challenges/{challenge["challenge_id"]}/attempt'
    assert client.post(path, headers=headers, json=payload).status_code == 422
    payload["cohort"] = "red"
    result = client.post(path, headers=headers, json=payload).json()
    assert result["token"] is None and result["result"]["pass"] is False
    assert client.post(path, headers=headers, json=payload).status_code == 404
    assert len(app.state.attempts) == 1 and "samples" not in app.state.attempts[0]
    challenge = client.post("/v1/challenges", headers=headers, json={"session_id": "run_test"}).json()
    now[0] = 121
    assert client.post(f'/v1/challenges/{challenge["challenge_id"]}/attempt', headers=headers, json=payload).status_code == 404


def lab_client(app):
    from engine.agents.lab_client import LabClient
    local = TestClient(app)
    def forward(request):
        response = local.request(request.method, str(request.url), headers=dict(request.headers), content=request.content)
        # Starlette may use httpx2 internally; return the SDK's httpx response type.
        return httpx.Response(response.status_code, headers=dict(response.headers), content=response.content)
    transport = httpx.MockTransport(forward)
    return LabClient("http://127.0.0.1:8001", "dev", transport=transport)


def test_lab_client_evidence_and_url_scope():
    from engine.agents.lab_client import LabClient
    for url in ("http://example.com", "https://user:secret@example.com", "https://example.com/other", "https://example.com?key=x"):
        with pytest.raises(ValueError):
            LabClient(url, "key")
    app = create_lab_app()
    client = lab_client(app)
    try:
        challenge = client.challenge("run_test")
        result = client.submit(challenge, forge_trail(challenge["seed"]), "run_test")
        assert result["attempt_id"] == app.state.attempts[0]["attempt_id"]
        assert len(client.forgeries("run_test")) == 1
        assert client.forgeries("other") == []
    finally:
        client.close()


def test_red_hooks_enforce_tool_budgets_and_round_unlock():
    pytest.importorskip("strands")
    from engine.agents.red import RedHooks
    app = create_lab_app()
    client = lab_client(app)
    try:
        hooks = RedHooks(client, "run_test", 1)
        def call(name):
            event = SimpleNamespace(tool_use={"name": name, "input": {}}, cancel_tool=False)
            hooks.before_tool(event)
            return event.cancel_tool
        assert not any(call("forge_and_submit") for _ in range(8))
        assert call("forge_and_submit")
        assert call("transplant_human_error") and call("activate_variant")
        hooks = RedHooks(client, "run_round3", 3)
        assert not any(call("transplant_human_error") for _ in range(4))
        assert call("transplant_human_error")
        hooks.after_tool(SimpleNamespace(tool_use={"name": "forge_and_submit"}, result={"status": "error"}))
        assert app.state.events[-1]["type"] == "tool_result"
    finally:
        client.close()


@pytest.mark.parametrize("round_number", [1, 3])
def test_real_sdk_red_round_uses_http_and_corrects_fabricated_report(round_number):
    pytest.importorskip("openai")
    pytest.importorskip("strands")
    pytest.importorskip("dotenv")
    from openai import AsyncOpenAI
    from engine.agents.common import ModelSettings, make_model
    from engine.agents.hooks import RequestBudget
    from engine.agents.red import run_red
    app = create_lab_app()
    lab = lab_client(app)
    responses = [0]
    def respond(request):
        body = json.loads(request.content)
        assert request.url.host == "sdk-smoke.invalid"
        # Raw human sample arrays must not be present in model requests.
        assert '"samples"' not in request.content.decode()
        names = [item["function"]["name"] for item in body["tools"]]
        assert ("transplant_human_error" in names) == (round_number >= 3)
        index = responses[0]
        responses[0] += 1
        if index == 0:
            name, args = "forge_and_submit", {}
        elif index == 1:
            name, args = ("transplant_human_error", {"trace_index": 0}) if round_number >= 3 else (
                "forge_and_submit", {"lag_ms": 200, "noise_px": 2, "submove_hz": 3, "overshoot": .1})
        else:
            name, args = "RoundReport", {"round": 99, "agent": "blue", "attempts": 999, "passed": 999,
                "best_params": {}, "what_changed": "Test commentary", "evidence": ["invented"]}
        return httpx.Response(200, json={"id": "completion_test", "object": "chat.completion", "created": 1,
            "model": "test-model", "choices": [{"index": 0, "finish_reason": "tool_calls", "message": {
                "role": "assistant", "content": None, "tool_calls": [{"id": f"call_{index}", "type": "function",
                "function": {"name": name, "arguments": json.dumps(args)}}]}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20}})
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as transport:
            async with AsyncOpenAI(base_url="https://sdk-smoke.invalid/v1", api_key="test", http_client=transport) as client:
                model = make_model(ModelSettings(provider="akamai", model_id="test"), client=client)
                return await run_red(model, lab, run_id="run_test", round_number=round_number,
                                     traces=[{"trace": trace()}], budget=RequestBudget(min_interval_s=0))
    try:
        report = asyncio.run(run())
        assert report.attempts == 2 and report.agent == "red" and report.round == round_number
        assert report.passed == sum(row["pass"] for row in app.state.attempts)
        assert report.evidence == [row["attempt_id"] for row in app.state.attempts]
        assert app.state.events[-1]["type"] == "round_report"
        assert all(len(row["data"]["summary"]) <= 200 for row in app.state.events if row["type"] == "tool_result")
    finally:
        lab.close()


def test_worker_model_timeout_is_explicit_and_smoke_default_preserved():
    pytest.importorskip("openai")
    pytest.importorskip("strands")
    pytest.importorskip("dotenv")
    from engine.agents.common import ModelSettings, make_model
    settings = ModelSettings(provider="akamai", model_id="test", api_key="test", base_url="https://sdk-smoke.invalid/v1")
    assert make_model(settings).client_args["timeout"] == 30
    assert make_model(settings, request_timeout=60).client_args["timeout"] == 60

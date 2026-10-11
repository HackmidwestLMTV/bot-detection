import asyncio
from copy import deepcopy
import json
from types import SimpleNamespace

import httpx
import pytest

for dependency in ("openai", "strands", "dotenv"):
    pytest.importorskip(dependency, reason="install engine/requirements-agents.txt for agent tests")

from openai import AsyncOpenAI

from engine.agents.blue import BlueHooks, human_stats, run_blue
from engine.agents.common import ModelSettings, make_model
from engine.agents.hooks import RequestBudget
from engine.labserver import create_lab_app
from engine.tests.test_phase3 import lab_client, variant
from engine.worker_state import WorkerState


def evidence():
    return {"attempt_id": "human_test_1", "device": "mouse", "nondominant_hand": False,
            "features": {"lag_ms": 200, "err_mean_px": 40, "submoves_per_s": 2, "jitter_px": 2, "power_law_beta": .33}}


def setup_lab(*, humans=True):
    app = create_lab_app(humans=[evidence()] if humans else [])
    forged = deepcopy(evidence()["features"])
    forged["power_law_beta"] = 0
    app.state.attempts.append({"attempt_id": "forged_1", "round_id": "red_1", "features": forged, "score": 1, "pass": True})
    return app, lab_client(app)


def candidate():
    result = variant()
    result.update(id="candidate", parent="v1", enabled=list(result["features"]), pass_threshold=1)
    return result


@pytest.mark.parametrize("action", ["approve", "deny", "timeout", "stale", "missing_humans", "summary_timeout"])
def test_blue_full_sdk_gate_and_human_decision(action):
    app, lab = setup_lab(humans=action != "missing_humans")
    calls = []
    def provider(request):
        body = json.loads(request.content)
        assert '"samples"' not in request.content.decode()
        index = len(calls)
        if action == "summary_timeout" and index == 6:
            raise httpx.ReadTimeout("test summary timeout", request=request)
        plan = ["get_forgeries", "get_human_stats", "get_active_variant", "propose_variant", "run_gate", "activate_variant", "RoundReport"]
        name = plan[index]
        calls.append(name)
        args = {}
        if name == "propose_variant":
            args = {key: candidate()[key] for key in ("features", "enabled", "pass_threshold")}
            args["reason"] = "Fixture beta separates the synthetic examples"
        elif name in ("run_gate", "activate_variant"):
            vid = lab.request("GET", "/v1/variants")[-1]["id"]
            args = {"candidate_id" if name == "run_gate" else "variant_id": vid}
        elif name == "RoundReport":
            args = {"round": 999, "agent": "red", "attempts": 99, "passed": 99,
                    "best_params": {}, "what_changed": "Fixture commentary", "evidence": ["invented"]}
        return httpx.Response(200, json={"id": "test", "object": "chat.completion", "created": 1, "model": "test",
            "choices": [{"index": 0, "finish_reason": "tool_calls", "message": {"role": "assistant", "content": None,
                "tool_calls": [{"id": f"call_{index}", "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}]}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20}})
    async def operator():
        for _ in range(1000):
            if app.state.approvals:
                aid = next(iter(app.state.approvals))
                lab.request("POST", f"/v1/lab/approvals/{aid}/decide", json={"approve": action != "deny"})
                if action == "stale":
                    app.state.humans.append({**evidence(), "attempt_id": "new_human"})
                return
            await asyncio.sleep(.001)
        raise AssertionError("approval was never requested")
    async def run():
        task = asyncio.create_task(operator()) if action in ("approve", "deny", "stale", "summary_timeout") else None
        try:
            async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as transport:
                async with AsyncOpenAI(base_url="https://sdk-smoke.invalid/v1", api_key="test", http_client=transport, max_retries=0) as client:
                    report = await run_blue(make_model(ModelSettings(provider="akamai", model_id="test"), client=client), lab,
                        run_id="blue_test", budget=RequestBudget(min_interval_s=0), approval_timeout=.04, poll_interval=.001)
            if task:
                await task
            return report
        finally:
            if task and not task.done():
                task.cancel()
    try:
        report = asyncio.run(run())
        assert report.agent == "blue" and report.round == 1 and report.attempts == 1
        approved = action in ("approve", "summary_timeout")
        assert report.passed == int(approved)
        if approved:
            assert len(calls) == 6  # No model call after the successful activation tool.
        assert report.evidence == [lab.request("GET", "/v1/variants")[-1]["id"]]
        assert (lab.active_variant()["id"] != "v1") == approved
        assert sum(event["type"] == "variant_activated" for event in app.state.events) == int(approved)
        assert sum(event["type"] == "approval_needed" for event in app.state.events) == (action != "missing_humans")
        assert app.state.events[-1]["type"] == "round_report"
    finally:
        lab.close()


def test_server_rejects_forged_gate_unapproved_reused_and_stale_activation():
    app, lab = setup_lab()
    try:
        lab.propose(candidate())
        with pytest.raises(httpx.HTTPStatusError):
            lab.activate("candidate", "run")
        with pytest.raises(httpx.HTTPStatusError):
            lab.create_approval("i", "candidate", {"verdict": "approve_for_review"}, "run")
        decision = lab.run_gate("candidate", "run")
        aid = lab.create_approval("i", "candidate", decision, "run")["approval_id"]
        lab.request("POST", f"/v1/lab/approvals/{aid}/decide", json={"approve": True})
        app.state.humans.append({**evidence(), "attempt_id": "new"})
        with pytest.raises(httpx.HTTPStatusError):
            lab.activate("candidate", "run")
        aid = lab.create_approval("i2", "candidate", lab.run_gate("candidate", "run"), "run")["approval_id"]
        lab.request("POST", f"/v1/lab/approvals/{aid}/decide", json={"approve": True})
        assert lab.activate("candidate", "run")["variant_id"] == "candidate"
        with pytest.raises(httpx.HTTPStatusError):
            lab.activate("candidate", "run")
        lab.request("POST", "/v1/lab/reset", json={})
        assert len(lab.human_features()) == 2 and not lab.forgeries()
        assert lab.active_variant()["id"] == "v1" and not app.state.approvals
    finally:
        lab.close()


def test_blue_budget_and_summary_preserve_device_groups():
    app, lab = setup_lab()
    try:
        hooks = BlueHooks(lab, "blue_budget")
        for i in range(4):
            event = SimpleNamespace(tool_use={"name": "propose_variant", "input": {}}, cancel_tool=False)
            hooks.before(event)
            assert bool(event.cancel_tool) == (i == 3)
        rows = [evidence(), {**evidence(), "attempt_id": "touch", "device": "touch"}]
        stats = human_stats(rows, variant())
        assert set(stats) == {"mouse", "touch"}
        assert stats["touch"]["features"]["power_law_beta"]["median"] == .33
        assert "attempt_id" not in json.dumps(stats)
    finally:
        lab.close()


def test_worker_journal_persists_rounds_and_rejects_duplicates(tmp_path):
    path = tmp_path / "state.sqlite3"
    state = WorkerState(path)
    assert state.claim("red1", "red") == 1
    state.finish("red1", "completed")
    state.close()
    state = WorkerState(path)
    assert state.claim("red1", "red") is None
    assert state.claim("red2", "red") == 2
    assert state.claim("blue1", "blue") == 1
    assert state.claim("red3", "red") == 3
    with pytest.raises(ValueError):
        state.claim("bad", "green")
    state.close()


def test_worker_consumes_both_agents_and_skips_duplicate(tmp_path, monkeypatch):
    from engine import worker
    from engine.agents.schemas import RoundReport
    app, lab = setup_lab()
    commands = [{"run_id": "r1", "kind": "red"}, {"run_id": "r1", "kind": "red"}, {"run_id": "b1", "kind": "blue"}]
    stop = asyncio.Event()
    def next_command():
        if commands:
            return commands.pop(0)
        stop.set()
        return None
    monkeypatch.setattr(lab, "next_command", next_command)
    seen = []
    async def red(model, client, **kwargs):
        seen.append(("red", kwargs["round_number"]))
        return RoundReport(round=1, agent="red", attempts=0, passed=0, best_params={}, what_changed="test", evidence=[])
    async def blue(model, client, **kwargs):
        seen.append(("blue", kwargs["round_number"]))
        return RoundReport(round=1, agent="blue", attempts=0, passed=0, best_params={}, what_changed="test", evidence=[])
    monkeypatch.setattr(worker, "run_red", red)
    monkeypatch.setattr(worker, "run_blue", blue)
    state = WorkerState(tmp_path / "state.sqlite3")
    try:
        asyncio.run(worker.consume(lab, lambda: None, state, traces_dir=tmp_path, interval=.001, stop=stop, output=lambda text: None))
        assert seen == [("red", 1), ("blue", 1)]
    finally:
        state.close()
        lab.close()


def test_internal_http_requires_explicit_opt_in():
    from engine.agents.lab_client import LabClient
    with pytest.raises(ValueError):
        LabClient("http://app:8000", "test")
    client = LabClient("http://app:8000", "test", allow_internal_http=True)
    client.close()
    with pytest.raises(ValueError):
        LabClient("http://unrelated:8000", "test", allow_internal_http=True)


def test_worker_recovers_after_poll_failure_and_invalid_command(tmp_path, monkeypatch):
    from engine import worker
    from engine.agents.schemas import RoundReport
    stop = asyncio.Event()
    queue = [ConnectionError("unavailable"), {"kind": "red"}, {"run_id": "valid", "kind": "red"}]
    output, seen = [], []

    def next_command():
        if not queue:
            stop.set()
            return None
        item = queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    async def red(model, client, **kwargs):
        seen.append(kwargs["run_id"])
        return RoundReport(round=1, agent="red", attempts=0, passed=0,
                           best_params={}, what_changed="test", evidence=[])

    monkeypatch.setattr(worker, "run_red", red)
    state = WorkerState(tmp_path / "state.sqlite3")
    try:
        asyncio.run(worker.consume(SimpleNamespace(next_command=next_command), lambda: None, state,
            traces_dir=tmp_path, interval=.001, stop=stop, output=lambda item: output.append(json.loads(item))))
        assert seen == ["valid"]
        assert [item["status"] for item in output] == ["poll_failed", "invalid_command", "completed"]
    finally:
        state.close()

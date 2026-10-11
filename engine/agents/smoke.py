"""Bounded Strands capability test. All tools affect only disposable in-memory state."""

import argparse
import asyncio
import importlib.metadata
import json
import logging
import sys

from strands import Agent, tool
from strands.types.exceptions import EventLoopException

from engine.agents.common import ConfigurationError, load_settings, make_model
from engine.agents.hooks import ApproveActivation, RequestBudget, SmokeHooks
from engine.agents.schemas import RoundReport

EXPECTED_REPORT = {"round": 3, "agent": "red", "attempts": 2, "passed": 1,
                   "best_params": {"lag_ms": 200, "noise_px": 1.5, "submove_hz": 3, "overshoot": 0.1},
                   "what_changed": "Synthetic SDK smoke test only", "evidence": ["smoke_att_1"]}


class CapabilityError(RuntimeError):
    """A specific SDK/model capability did not satisfy its observable check."""


def require(condition, message):
    if not condition:
        raise CapabilityError(message)


def new_agent(model, hooks, tools=()):
    return Agent(model=model, tools=list(tools), hooks=list(hooks), callback_handler=None, retry_strategy=None,
                 system_prompt="You are verifying an SDK using synthetic data and in-memory tools. Follow the requested tool call exactly. "
                               "After a tool succeeds or is denied, report the result and stop. Never retry denied tools.")


async def invoke(agent, prompt, **kwargs):
    try:
        return await asyncio.wait_for(agent.invoke_async(prompt, **kwargs), timeout=90)
    except EventLoopException as exc:
        cause = exc.original_exception
        while isinstance(cause, EventLoopException):
            cause = cause.original_exception
        raise cause from None


async def check_greeting(factory, budget):
    hooks = SmokeHooks(budget)
    result = await invoke(new_agent(factory(), [hooks]), "Reply with OK.")
    require(result.stop_reason == "end_turn", "greeting did not finish normally")
    text = " ".join(part.get("text", "") for part in result.message["content"])
    require("OK" in text.upper(), "greeting did not return OK")
    return {"stop_reason": result.stop_reason}


async def check_tool_call(factory, budget):
    calls = []

    @tool
    def record_probe(value: int) -> dict:
        """Record an integer in a disposable in-memory test counter.

        Args:
            value: Integer to record for this test.
        """
        calls.append(value)
        return {"recorded": value}

    require(record_probe.tool_name == "record_probe", "tool.tool_name is incompatible")
    hooks = SmokeHooks(budget)
    result = await invoke(new_agent(factory(), [hooks], [record_probe]), "Call record_probe once with value 7, then confirm its result.")
    require(result.stop_reason == "end_turn" and calls == [7], "model did not execute the probe exactly once")
    require(any(row == {"name": "record_probe", "status": "success"} for row in hooks.tool_results),
            "AfterToolCallEvent.result was not observed")
    return {"stop_reason": result.stop_reason, "executions": len(calls), "result_hook_observed": True}


async def check_structured(factory, budget):
    for _ in range(3):
        hooks = SmokeHooks(budget)
        agent = new_agent(factory(), [hooks])
        result = await invoke(agent, "Return this synthetic round report using the requested schema: " + json.dumps(EXPECTED_REPORT),
                              structured_output_model=RoundReport)
        report = result.structured_output
        # Strands completes structured output directly from its schema tool, so
        # successful results may retain stop_reason='tool_use'.
        require(result.stop_reason in ("end_turn", "tool_use") and isinstance(report, RoundReport),
                "structured output was not a validated RoundReport")
        require((report.round, report.agent, report.attempts, report.passed, report.evidence) ==
                (3, "red", 2, 1, ["smoke_att_1"]), "structured report changed the supplied test facts")
    return {"validated_runs": 3}


async def check_denial(factory, budget):
    calls = []

    @tool
    def blocked_probe() -> dict:
        """A disposable test tool whose execution must be denied by the SDK hook."""
        calls.append(True)
        return {"unexpected_execution": True}

    hooks = SmokeHooks(budget, deny={"blocked_probe"})
    agent = new_agent(factory(), [hooks], [blocked_probe])
    result = await invoke(agent, "Call blocked_probe once. If it is denied, acknowledge the denial and stop.")
    require(result.stop_reason == "end_turn" and not calls and hooks.denied == ["blocked_probe"],
            "tool denial was missing, retried, or failed to block execution")
    return {"stop_reason": result.stop_reason, "executions": 0, "denials": 1}


async def check_approval(factory, budget):
    outcomes = {}
    for answer in ("y", "n"):
        calls = []

        @tool
        def activate_variant(variant_id: str) -> dict:
            """Simulate activation in memory; does not access the application or real variants.

            Args:
                variant_id: Synthetic variant identifier to record in memory.
            """
            calls.append(variant_id)
            return {"simulated_activation": variant_id}

        hooks = SmokeHooks(budget)
        agent = new_agent(factory(), [hooks, ApproveActivation()], [activate_variant])
        result = await invoke(agent, "Call activate_variant once for variant_id smoke_variant. If denied, stop.")
        require(result.stop_reason == "interrupt" and len(result.interrupts) == 1 and not calls,
                "activation was not paused before tool execution")
        interrupt = result.interrupts[0]
        require(interrupt.name == "approve-activation", "unexpected interrupt name")
        # Automatically answer only this disposable fake tool, never a real activation.
        result = await invoke(agent, [{"interruptResponse": {"interruptId": interrupt.id, "response": answer}}])
        expected = ["smoke_variant"] if answer == "y" else []
        require(result.stop_reason == "end_turn" and calls == expected,
                "approval resume did not enforce the requested decision")
        outcomes[answer] = {"stop_reason": result.stop_reason, "executions": len(calls)}
    return outcomes


CHECKS = (("greeting", check_greeting), ("tool_call", check_tool_call), ("structured_output", check_structured),
          ("tool_denial", check_denial), ("approval_interrupt", check_approval))


async def run_smoke(factory, budget, *, attempts=2, on_result=None):
    results = []
    for name, check in CHECKS:
        for attempt in range(1, attempts + 1):
            before = budget.calls
            try:
                detail = await check(factory, budget)
                record = {"check": name, "attempt": attempt, "status": "passed", "model_calls": budget.calls - before,
                          "detail": detail}
            except Exception as exc:
                # Avoid leaking credentials, endpoints, or raw provider response bodies.
                record = {"check": name, "attempt": attempt, "status": "failed", "model_calls": budget.calls - before,
                          "error_type": type(exc).__name__}
                if isinstance(exc, CapabilityError):
                    record["detail"] = str(exc)
            results.append(record)
            if on_result:
                on_result(record)
            if record["status"] == "passed":
                break
        else:
            return {"status": "failed", "checks": results, "model_calls": budget.calls}
    return {"status": "passed", "checks": results, "model_calls": budget.calls}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-config", action="store_true", help="Validate configuration without making model requests")
    parser.add_argument("--provider", choices=("akamai", "bedrock"), help="Explicit provider override")
    parser.add_argument("--attempts", type=int, choices=(1, 2), default=2)
    args = parser.parse_args(argv)
    # The report below is intentionally sanitized. Keep SDK tracebacks/tool dumps out of console logs.
    logging.disable(logging.CRITICAL)
    try:
        settings = load_settings(provider=args.provider)
    except ConfigurationError as exc:
        print(json.dumps({"status": "configuration_required", "reason": str(exc)}), flush=True)
        return 2
    versions = {name: importlib.metadata.version(name) for name in ("strands-agents", "openai")}
    print(json.dumps({"provider": settings.provider, "versions": versions, "stream": False, "max_tokens": 1500}), flush=True)
    if args.check_config:
        print(json.dumps({"status": "configured", "live_test_run": False}), flush=True)
        return 0
    budget = RequestBudget(min_interval_s=settings.min_interval_s)
    report = asyncio.run(run_smoke(lambda: make_model(settings), budget, attempts=args.attempts,
                                   on_result=lambda record: print(json.dumps(record), flush=True)))
    report["provider"] = settings.provider
    report["live_test_run"] = True
    if report["status"] != "passed" and settings.provider == "akamai":
        report["next_step"] = "Configure Bedrock credentials and BEDROCK_MODEL_ID, then rerun with --provider bedrock. No automatic switch occurred."
    print(json.dumps(report), flush=True)
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())

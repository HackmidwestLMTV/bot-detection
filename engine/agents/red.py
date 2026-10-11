"""Bounded Red round against the project's lab, with code-owned evidence."""

import asyncio
import json
import math
import threading

from strands import Agent, tool
from strands.hooks import AfterToolCallEvent, BeforeToolCallEvent, HookProvider

from engine.agents.hooks import RequestBudget, SmokeHooks
from engine.agents.schemas import RoundReport
from engine.forger import forge_trail, transplant
from engine.scorer import validate_variant


class RedHooks(HookProvider):
    def __init__(self, client, run_id, round_number):
        self.client, self.run_id = client, run_id
        self.remaining = {"forge_and_submit": 8, "transplant_human_error": 4 if round_number >= 3 else 0}
        self.lock = threading.Lock()

    def register_hooks(self, registry, **kwargs):
        registry.add_callback(BeforeToolCallEvent, self.before_tool)
        registry.add_callback(AfterToolCallEvent, self.after_tool)

    def after_tool(self, event):
        if event.tool_use["name"] != "RoundReport" and event.result["status"] == "error":
            self.client.event(self.run_id, "tool_result", {"tool": event.tool_use["name"],
                                                          "summary": "Tool failed or was denied; no successful result."})

    def before_tool(self, event):
        name = event.tool_use["name"]
        if name == "RoundReport":
            return
        with self.lock:
            allowed = self.remaining.get(name, 0) > 0
            if allowed:
                self.remaining[name] -= 1
        if not allowed:
            event.cancel_tool = "DENIED: tool unavailable or round budget exhausted. Finish the round."
        self.client.event(self.run_id, "tool_call", {"tool": name, "args": event.tool_use["input"]})


async def run_red(model, client, *, run_id, round_number=1, traces=(), budget=None):
    if round_number < 1:
        raise ValueError("round_number must be positive")
    variant = client.active_variant()
    validate_variant(variant)
    observations = []
    execution_lock = threading.Lock()
    hooks = RedHooks(client, run_id, round_number)
    model_hooks = SmokeHooks(budget or RequestBudget(max_calls=20), max_model_calls=16)

    def record(result, params, tool_name):
        observations.append({"result": result, "params": params})
        failed = [name for name, value in result["features"].items() if value["enabled"] and not value["ok"]]
        client.event(run_id, "attempt_scored", {"attempt_id": result["attempt_id"], "score": result["score"],
                                              "pass": result["pass"], "failed": failed})
        client.event(run_id, "tool_result", {"tool": tool_name, "summary": json.dumps({
            "attempt_id": result["attempt_id"], "score": result["score"], "pass": result["pass"]})[:200]})
        return result

    @tool
    def forge_and_submit(lag_ms: float = 0, noise_px: float = 0, submove_hz: float = 0, overshoot: float = 0) -> dict:
        """Forge and score one synthetic trail on a fresh challenge in our lab.

        Args:
            lag_ms: Reaction delay, 0 to 500 milliseconds.
            noise_px: Noise standard deviation, 0 to 50 pixels.
            submove_hz: Correction frequency, 0 to 20 Hz.
            overshoot: Overshoot fraction, 0 to 2.
        """
        params = dict(lag_ms=lag_ms, noise_px=noise_px, submove_hz=submove_hz, overshoot=overshoot)
        if any(not math.isfinite(v) or not 0 <= v <= limit for v, limit in zip(params.values(), (500, 50, 20, 2))):
            raise ValueError("parameters outside permitted ranges")
        with execution_lock:
            if not observations and any(params.values()):
                raise ValueError("first attempt must use all-zero parameters to establish the baseline")
            challenge = client.challenge(run_id)
            result = client.submit(challenge, forge_trail(challenge["seed"], **params), run_id)
            return record(result, params, "forge_and_submit")

    @tool
    def transplant_human_error(trace_index: int) -> dict:
        """Apply a locally stored, consented team's error pattern to a new target.

        Args:
            trace_index: Zero-based index into the available local team recordings.
        """
        if round_number < 3:
            raise ValueError("transplantation unlocks in round 3")
        if not 0 <= trace_index < len(traces):
            raise ValueError("trace_index outside available recordings")
        with execution_lock:
            if not observations:
                raise ValueError("establish the zero-parameter baseline first")
            trace = traces[trace_index]["trace"]
            if trace.get("cohort") != "human_test" or trace.get("tester", {}).get("consent") is not True:
                raise ValueError("transplantation requires consented team evidence")
            challenge = client.challenge(run_id)
            result = client.submit(challenge, transplant(trace, challenge["seed"]), run_id,
                                   device=trace["device"], pointer_type=trace.get("pointer_type", "mouse"))
            return record(result, {"trace_index": trace_index}, "transplant_human_error")

    tools = [forge_and_submit]
    if round_number >= 3 and traces:
        tools.append(transplant_human_error)
    agent = Agent(model=model, tools=tools, hooks=[model_hooks, hooks], callback_handler=None, retry_strategy=None,
                  system_prompt="You are Red in our own local behavioral-scoring lab. Use only the provided tools. "
                  "Never invent attempts, scores, or evidence IDs. Begin with forge_and_submit using all zeros. "
                  "Inspect the failed features, then adjust parameters. Aim for three to five attempts. "
                  "If a tool is denied, do not retry it. Finish with the requested RoundReport schema. "
                  "A passing score only means the current heuristic accepted the synthetic trace.")
    client.event(run_id, "round_started", {"round": round_number, "variant": variant["id"]})
    prompt = f"Run round {round_number}. Active variant: {json.dumps(variant)}. "
    prompt += f"Available local transplant traces: {len(traces) if round_number >= 3 else 0}. "
    if round_number >= 3 and traces:
        prompt += "After the baseline, test at least one transplant. "
    result = await asyncio.wait_for(agent.invoke_async(prompt, structured_output_model=RoundReport), timeout=300)
    if not isinstance(result.structured_output, RoundReport) or not observations:
        raise RuntimeError("Red did not produce a typed report backed by scored attempts")
    best = max(observations, key=lambda row: row["result"]["score"])
    # Treat prose as model commentary, but derive every count and reference from tool observations.
    report = RoundReport(round=round_number, agent="red", attempts=len(observations),
                         passed=sum(row["result"]["pass"] for row in observations), best_params=best["params"],
                         what_changed=result.structured_output.what_changed,
                         evidence=[row["result"]["attempt_id"] for row in observations])
    client.event(run_id, "round_report", report.model_dump())
    return report

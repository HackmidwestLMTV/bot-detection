"""Blue proposes bounded rule changes; only a fresh gate and a person can activate."""

import asyncio
import hashlib
import json
import threading
import time
from uuid import uuid4

import numpy as np
from strands import Agent, tool
from strands.hooks import AfterToolCallEvent, AfterToolsEvent, BeforeToolCallEvent, HookProvider

from engine.agents.hooks import ApproveActivation, RequestBudget, SmokeHooks
from engine.agents.schemas import RoundReport
from engine.scorer import FEATURES, score_features, validate_variant


def values(row):
    return {name: float(value["value"] if isinstance(value, dict) else value)
            for name, value in row["features"].items() if name in FEATURES}


def human_stats(rows, baseline):
    groups = {}
    for row in rows:
        score_features(row["features"], baseline)
        if row["device"] not in ("mouse", "trackpad", "touch"):
            raise ValueError("unknown human device")
        groups.setdefault(row["device"], []).append(row)
    return {device: {"total": len(group), "nondominant": sum(bool(row.get("nondominant_hand")) for row in group),
                     "features": {name: dict(zip(("min", "p05", "median", "p95", "max"),
                        np.percentile([values(row)[name] for row in group], [0, 5, 50, 95, 100]).tolist()))
                        for name in FEATURES}} for device, group in groups.items()}


def evidence_fingerprint(client):
    body = [client.active_variant(), sorted(client.human_features(), key=lambda row: row["attempt_id"]),
            sorted(client.forgeries(), key=lambda row: row["attempt_id"])]
    return hashlib.sha256(json.dumps(body, sort_keys=True, allow_nan=False).encode()).hexdigest()


class BlueHooks(HookProvider):
    def __init__(self, client, run_id):
        self.client, self.run_id = client, run_id
        self.remaining = {"get_forgeries": 4, "get_human_stats": 4, "get_active_variant": 4,
                          "propose_variant": 3, "run_gate": 6, "activate_variant": 6}
        self.lock = threading.Lock()

    def register_hooks(self, registry, **kwargs):
        registry.add_callback(BeforeToolCallEvent, self.before)
        registry.add_callback(AfterToolCallEvent, self.after)

    def before(self, event):
        name = event.tool_use["name"]
        if name == "RoundReport":
            return
        with self.lock:
            allowed = self.remaining.get(name, 0) > 0
            if allowed:
                self.remaining[name] -= 1
        if not allowed:
            event.cancel_tool = "DENIED: tool scope or budget exhausted. Finish the report."
        self.client.event(self.run_id, "tool_call", {"tool": name, "args": event.tool_use["input"]}, agent="blue")

    def after(self, event):
        if event.tool_use["name"] != "RoundReport":
            self.client.event(self.run_id, "tool_result", {"tool": event.tool_use["name"],
                "summary": "Tool " + event.result["status"] + "; see its returned evidence."}, agent="blue")


async def wait_for_decision(client, approval_id, *, timeout=180, interval=1):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = client.approval(approval_id)["status"]
        if status in ("approved", "denied"):
            return status == "approved"
        if status != "pending":
            raise ValueError("unknown approval status")
        await asyncio.sleep(min(interval, max(0, deadline - time.monotonic())))
    return False


class FinishOnActivation(HookProvider):
    def __init__(self, activated):
        self.activated = activated

    def register_hooks(self, registry, **kwargs):
        registry.add_callback(AfterToolsEvent, self.finish)

    def finish(self, event):
        if self.activated:
            event.end_turn = "Human-approved candidate activated; reporting observed facts."


async def run_blue(model, client, *, run_id, round_number=1, budget=None, approval_timeout=180,
                   poll_interval=1):
    baseline = client.active_variant()
    validate_variant(baseline)
    proposals, grants, activated = {}, {}, []
    tool_lock = threading.Lock()
    model_hooks = SmokeHooks(budget or RequestBudget(max_calls=30), max_model_calls=24)

    @tool
    def get_forgeries() -> dict:
        """Read recent synthetic attack feature values and scores, never raw trails."""
        rows = client.forgeries()
        return {"total": len(rows), "recent": [{"attempt_id": row["attempt_id"], "features": values(row),
                 "score": row["score"], "pass": row["pass"]} for row in rows[-24:]]}

    @tool
    def get_human_stats() -> dict:
        """Read per-device human feature percentiles and counts, never individual human trails."""
        return human_stats(client.human_features(), baseline)

    @tool
    def get_active_variant() -> dict:
        """Read the current rule configuration."""
        return client.active_variant()

    @tool
    def propose_variant(features: dict[str, list[float]], enabled: list[str], pass_threshold: float, reason: str) -> dict:
        """Store a candidate for gate evaluation. This cannot activate a rule.

        Args:
            features: All five feature names mapped to inclusive [low, high] bands.
            enabled: Feature names to enable for this candidate.
            pass_threshold: Required fraction of enabled bands passed, greater than 0 and at most 1.
            reason: Short explanation based on observed human and forgery summaries.
        """
        with tool_lock:
            if len(proposals) >= 3:
                raise ValueError("proposal budget exhausted")
            if client.active_variant()["id"] != baseline["id"]:
                raise ValueError("baseline changed; start a new round")
            candidate = {"id": "blue_" + uuid4().hex, "parent": baseline["id"], "author": "blue",
                         "features": features, "enabled": enabled, "pass_threshold": pass_threshold, "reason": reason[:1000]}
            validate_variant(candidate)
            client.propose(candidate)
            proposals[candidate["id"]] = candidate
            return {"id": candidate["id"]}

    @tool
    def run_gate(candidate_id: str) -> dict:
        """Evaluate a candidate with the fixed server rule against all stored evidence.

        Args:
            candidate_id: ID of a candidate proposed during this round.
        """
        if candidate_id not in proposals:
            raise ValueError("candidate must belong to this round")
        return client.run_gate(candidate_id, run_id)

    @tool
    def activate_variant(variant_id: str) -> dict:
        """Request activation; pauses for a fresh fixed gate and explicit human approval.

        Args:
            variant_id: ID of a candidate proposed during this round.
        """
        with tool_lock:
            proof = grants.pop(variant_id, None)
            if proof is None or variant_id not in proposals:
                raise ValueError("no human approval grant for this activation")
            decision = client.run_gate(variant_id, run_id)
            if (decision["verdict"] != "approve_for_review" or decision != proof["gate"]
                    or evidence_fingerprint(client) != proof["fingerprint"]
                    or client.approval(proof["approval_id"])["status"] != "approved"):
                raise ValueError("approval or evidence changed; activation denied")
            result = client.activate(variant_id, run_id)
            activated.append(variant_id)
            return result

    agent = Agent(model=model, tools=[get_forgeries, get_human_stats, get_active_variant, propose_variant, run_gate, activate_variant],
                  hooks=[model_hooks, BlueHooks(client, run_id), ApproveActivation(), FinishOnActivation(activated)], callback_handler=None, retry_strategy=None,
                  system_prompt="You are Blue in our own behavioral scoring lab. Read forgery and per-device human summaries. "
                  "Propose at most three variants, evaluate each with run_gate, and request activate_variant only if the gate "
                  "returns approve_for_review. Never seek activation after rejection. You cannot approve your own changes. "
                  "Consider enabling power_law_beta only when the observed evidence supports it. Do not force a win or invent "
                  "evidence. Stop after activation, denial, or no useful candidate, and return a RoundReport. "
                  "Report attempts as candidates proposed and passed as candidates actually activated. "
                  "If human or forgery evidence is absent, explain that and finish without proposing changes.")
    client.event(run_id, "round_started", {"round": round_number, "variant": baseline["id"]}, agent="blue")

    async def invoke(prompt):
        return await asyncio.wait_for(agent.invoke_async(prompt, structured_output_model=RoundReport), timeout=300)

    result = await invoke(f"Run Blue round {round_number}. Preserve every represented device group; finish with honest evidence.")
    interruptions = 0
    while result.stop_reason == "interrupt":
        interruptions += 1
        if interruptions > 3:
            raise RuntimeError("approval interruption budget exhausted")
        responses = []
        for interrupt in result.interrupts:
            answer = "n"
            variant_id = (interrupt.reason or {}).get("variant_id")
            if len(result.interrupts) == 1 and interrupt.name == "approve-activation" and variant_id in proposals:
                snapshot = evidence_fingerprint(client)
                decision = client.run_gate(variant_id, run_id)
                if decision["verdict"] == "approve_for_review" and snapshot == evidence_fingerprint(client):
                    approval_id = client.create_approval(interrupt.id, variant_id, decision, run_id)["approval_id"]
                    approved = await wait_for_decision(client, approval_id, timeout=approval_timeout, interval=poll_interval)
                    if approved and snapshot == evidence_fingerprint(client):
                        fresh = client.run_gate(variant_id, run_id)
                        if fresh == decision and fresh["verdict"] == "approve_for_review":
                            grants[variant_id] = {"approval_id": approval_id, "fingerprint": snapshot, "gate": fresh}
                            answer = "y"
                    if answer == "n":
                        client.event(run_id, "error", {"reason": "Activation denied, approval expired, or evidence changed."}, agent="blue")
            responses.append({"interruptResponse": {"interruptId": interrupt.id, "response": answer}})
        result = await invoke(responses)
    if activated:
        explanation = "Human-approved candidate activated. Proposal rationale: " + proposals[activated[-1]]["reason"]
    elif isinstance(result.structured_output, RoundReport):
        explanation = result.structured_output.what_changed
    else:
        raise RuntimeError("Blue did not produce a validated report")
    report = RoundReport(round=round_number, agent="blue", attempts=len(proposals), passed=len(activated), best_params={},
                         what_changed=explanation, evidence=list(proposals))
    client.event(run_id, "round_report", report.model_dump(), agent="blue")
    return report

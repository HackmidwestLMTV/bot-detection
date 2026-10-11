"""Code-enforced smoke-test boundaries and reusable approval interruption."""

import threading
import time

from strands.hooks import AfterToolCallEvent, BeforeModelCallEvent, BeforeToolCallEvent, HookProvider


class SmokeLimitError(RuntimeError):
    """The bounded verification run exhausted its request budget."""


class RequestBudget:
    """Shared across smoke cases in one process, not a team-wide rate limiter."""

    def __init__(self, *, max_calls=30, min_interval_s=3, clock=time.monotonic, sleep=time.sleep):
        self.max_calls = max_calls
        self.min_interval_s = min_interval_s
        self.calls = 0
        self.clock = clock
        self.sleep = sleep
        self.last_call = None
        self.lock = threading.Lock()

    def acquire(self):
        with self.lock:
            if self.calls >= self.max_calls:
                raise SmokeLimitError("smoke test model-call budget exhausted")
            if self.last_call is not None:
                delay = self.min_interval_s - (self.clock() - self.last_call)
                if delay > 0:
                    self.sleep(delay)
            self.calls += 1
            self.last_call = self.clock()


class SmokeHooks(HookProvider):
    def __init__(self, budget, *, deny=(), max_model_calls=4):
        self.budget = budget
        self.deny = set(deny)
        self.max_model_calls = max_model_calls
        self.model_calls = 0
        self.denied = []
        self.tool_results = []

    def register_hooks(self, registry, **kwargs):
        registry.add_callback(BeforeModelCallEvent, self.before_model)
        registry.add_callback(BeforeToolCallEvent, self.before_tool)
        registry.add_callback(AfterToolCallEvent, self.after_tool)

    def before_model(self, event):
        if self.model_calls >= self.max_model_calls:
            raise SmokeLimitError("smoke case model-call budget exhausted")
        self.budget.acquire()
        self.model_calls += 1

    def before_tool(self, event):
        name = event.tool_use["name"]
        if name in self.deny:
            event.cancel_tool = "DENIED: this smoke-test tool is blocked by code. Do not retry it."
            self.denied.append(name)

    def after_tool(self, event):
        # Verify the real SDK's result attribute without logging raw model/tool content.
        self.tool_results.append({"name": event.tool_use["name"], "status": event.result["status"]})


class ApproveActivation(HookProvider):
    """Pause activate_variant and require a fresh 'y' response for this tool call.

    This hook is only one guard. The future production API must also enforce its
    own gate and approved-approval record, as required by the shared contract.
    """

    def register_hooks(self, registry, **kwargs):
        registry.add_callback(BeforeToolCallEvent, self.approve)

    def approve(self, event):
        if event.tool_use["name"] != "activate_variant":
            return
        response = event.interrupt("approve-activation", reason={"variant_id": event.tool_use["input"].get("variant_id")})
        if not isinstance(response, str) or response.strip().lower() != "y":
            event.cancel_tool = "DENIED: activation was not approved. Do not retry."

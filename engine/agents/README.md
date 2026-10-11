# Phase 2: Strands integration smoke test

This kit verifies that the configured model can use Strands tools, return typed
reports, respect a denied tool, and resume after an approval interrupt. All tools
operate on disposable in-memory counters. It does not run Red/Blue workers,
activate application variants, or send human recordings to a model.

## Run locally

From the repository root, using the Phase 1 Python 3.12 environment:

```powershell
.\.venv\Scripts\python.exe -m pip install -r engine/requirements-agents.txt
.\.venv\Scripts\python.exe -m pip install -r engine/requirements-dev.txt
```

If `.env` does not already exist, copy `engine/agents.env.example` to `.env`.
Put credentials only in the ignored `.env`, never in the example file. Set
`AKAMAI_BASE_URL`, `AKAMAI_API_KEY`, and `MODEL_ID`. Existing process environment
variables take precedence over `.env`.

```powershell
.\.venv\Scripts\python.exe -m engine.agents.smoke --check-config
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m engine.agents.smoke
```

The configuration check makes no model requests. Pytest uses an in-memory HTTP
transport for SDK tests; the smoke command makes real model requests. JSON output
contains observed checks and counts, without credentials or raw provider bodies.
Exit codes are 0 for success, 1 for a failed capability, and 2 for missing or
invalid configuration.

## Checks and limits

- Greeting completes with `end_turn`.
- A real SDK tool executes exactly once with the requested value; the result hook
  observes success and the model ends its turn.
- Three separate agents produce validated `RoundReport` instances with the
  supplied synthetic counts and evidence. Strands may finish schema output with
  `tool_use`; a validated typed result is required.
- The denial hook prevents execution and the model stops without retrying.
- A fake `activate_variant` pauses before execution. Resuming the latest interrupt
  with `y` executes once; `n` prevents execution. Automated answers apply only to
  this fake tool. Real activation will require an approval flow and enforcement
  in the application API.

Requests are non-streaming with `max_tokens=1500`. Each agent is limited to four
model calls, and the whole run to 30. Calls start at least three seconds apart by
default (`MODEL_MIN_INTERVAL_S`, range 1–30). This budget is shared within one
process, not across the team's processes. SDK/provider retries are disabled;
each check gets at most two attempts, and the run stops at the first check that
fails both. Model requests have a 30-second timeout; each invocation has a
90-second asyncio timeout.

`AkamaiModel` omits empty `tools` and `tool_choice` fields because this endpoint
rejects `tools: []`. Nonempty tool definitions use the SDK's normal formatting.

## Provider fallback

Akamai is the default. If tool reliability fails twice, configure AWS credentials,
`AWS_REGION`, and an available `BEDROCK_MODEL_ID`, then explicitly run:

```powershell
.\.venv\Scripts\python.exe -m engine.agents.smoke --provider bedrock
```

Alternatively, set `USE_BEDROCK=1`. The harness never silently switches providers.
Bedrock configuration is implemented but was not live-validated in Phase 2.

## Verification recorded on 2026-10-10

Python 3.12, Strands 1.59.0, OpenAI SDK 2.54.0:

- Full suite: **58 passed**; `pip check`: no broken requirements.
- Live Akamai run: every check passed on its first attempt after correcting the
  empty-tools request format. Total: **12 model calls**.
- Greeting: 1 call; tool execution: 2; three structured reports: 3; denial: 2;
  approval/resume for both answers: 4.

This establishes compatibility for the tested provider and model configuration
at that time. It does not establish production reliability or bot-detection
accuracy. Human calibration, Red/Blue workers, the lab API, and deployment remain
later work.

SDK references: [interrupts](https://strandsagents.com/docs/user-guide/sdk/interrupts/),
[hooks](https://strandsagents.com/docs/user-guide/sdk/agents/hooks-events/), and
[structured output](https://strandsagents.com/docs/user-guide/sdk/agents/structured-output/).

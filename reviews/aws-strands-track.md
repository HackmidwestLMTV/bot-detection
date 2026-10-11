# AWS / Strands Agents track — what is real, what is only configured

Audit date 2026-10-11, repo at `3517fef` (branch `p1-platform`).
Environment: Python 3.14.7 venv at `.venv`, `strands-agents==1.59.0`, `boto3==1.43.111`,
`botocore==1.43.111`, `openai==2.54.0`, `pydantic==2.14.0`. `pip check`: no broken requirements.

**Headline in one line:** Strands Agents is the genuine agent framework for this product —
not a wrapper, not a stub — and the AWS Bedrock model provider is wired correctly and now
proven reachable offline, but **it has never once run against real AWS**, and the deployed
worker cannot currently reach it at all (see [Defect 1](#defect-1-the-deployed-worker-cannot-be-switched-to-bedrock)).

---

## 1. What Strands actually does in this product

Every claim below is a file-and-line citation a reviewer can open.

### The two agents are `strands.Agent` instances

| | Red | Blue |
|---|---|---|
| Constructed | `engine/agents/red.py:111` | `engine/agents/blue.py:174` |
| Imports | `from strands import Agent, tool` (`red.py:8`) | same (`blue.py:11`) |
| Invoked | `agent.invoke_async(prompt, structured_output_model=RoundReport)` (`red.py:122`) | same (`blue.py:188`) |
| Model-call ceiling | 16 (`red.py:53`) | 24 (`blue.py:102`) |
| SDK retries | `retry_strategy=None` (`red.py:111`) | `retry_strategy=None` (`blue.py:175`) |

Both pass `callback_handler=None` so no SDK output reaches the logs, and both wrap the
invocation in `asyncio.wait_for(..., timeout=300)`.

### Tools are `@tool`-decorated functions that do real product work

Red (`engine/agents/red.py`):

- `forge_and_submit` (`red.py:64`) — takes `lag_ms`, `noise_px`, `submove_hz`, `overshoot`,
  validates them against hard ranges (`red.py:75`), requests a fresh challenge from the lab
  API, synthesises a trail with `engine.forger.forge_trail`, and POSTs it for scoring.
  The **first** call is forced to all-zero parameters so the round has a real baseline
  (`red.py:78`).
- `transplant_human_error` (`red.py:85`) — only registered from round 3 onward
  (`red.py:109`), and refuses any recording that is not `cohort == "human_test"` with
  `tester.consent is True` (`red.py:100`).

Blue (`engine/agents/blue.py`) has six: `get_forgeries`, `get_human_stats`,
`get_active_variant`, `propose_variant`, `run_gate`, `activate_variant` (`blue.py:104–172`).
`get_human_stats` returns **per-device percentiles only** — never raw human trails
(`blue.py:24–34`), and `engine/tests/test_phase3.py:159` asserts that no `"samples"` array
ever appears in a model request.

### `strands.hooks` lifecycle hooks enforce the safety properties in code, not in prompts

`engine/agents/hooks.py:6` imports `AfterToolCallEvent`, `BeforeModelCallEvent`,
`BeforeToolCallEvent`, `HookProvider`; `engine/agents/blue.py:12` adds `AfterToolsEvent`.

| Hook provider | Event | What it enforces |
|---|---|---|
| `RedHooks` (`red.py:17`) | `BeforeToolCallEvent` | Per-round tool budget: 8 forges, 4 transplants (0 before round 3). Over budget → `event.cancel_tool = "DENIED: ..."` (`red.py:41`), so the **model is told** rather than the tool silently failing. Also emits a `tool_call` lab event for the live UI (`red.py:42`). |
| `RedHooks` | `AfterToolCallEvent` | Reads `event.result["status"]` and publishes a failure summary (`red.py:27–30`). |
| `BlueHooks` (`blue.py:43`) | both | Same pattern with a six-tool budget map (`blue.py:46`). |
| `SmokeHooks` (`hooks.py:37`) | `BeforeModelCallEvent` | Rate limiting and the hard model-call ceiling — raises `SmokeLimitError` and calls `RequestBudget.acquire()` (`hooks.py:51–55`). This is the only thing standing between a looping agent and the inference quota. |
| `ApproveActivation` (`hooks.py:68`) | `BeforeToolCallEvent` | Calls `event.interrupt("approve-activation", ...)` (`hooks.py:81`) to **pause the agent mid-tool-call** and require a literal `"y"`; anything else cancels the tool. |
| `FinishOnActivation` (`blue.py:84`) | `AfterToolsEvent` | Sets `event.end_turn` once a variant is activated (`blue.py:93`), ending the turn from code. |

The interrupt is resumed with the SDK's `{"interruptResponse": {"interruptId": ..., "response": ...}}`
protocol (`blue.py:213`, `smoke.py:134`), and the resume is only granted after the worker
re-runs the deterministic gate, re-checks an evidence SHA-256 fingerprint, and confirms a
human `approved` record (`blue.py:200–213`).

### Typed structured output

`engine/agents/schemas.py:8` defines `RoundReport` as a Pydantic model with
`extra="forbid"` and a `passed <= attempts` validator. Strands registers it as a dynamic
tool literally named `RoundReport` (which is why every hook special-cases that name — e.g.
`red.py:33`), and the round fails if the SDK does not hand back a validated instance
(`red.py:123`, `blue.py:220`).

Critically, **the model's numbers are not trusted**: `red.py:126–130` keeps only the model's
prose `what_changed` and recomputes `attempts`, `passed`, `best_params` and `evidence` from
the observed tool results. That is the right call and it is worth pointing a judge at.

### Typed exception handling

`strands.types.exceptions.EventLoopException` is imported in `engine/worker.py:10` and
`engine/agents/smoke.py:11`, and both unwrap nested causes before reporting an error type —
`worker.error_data` (`worker.py:20–23`) and `smoke.invoke` (`smoke.py:40–44`) — so a
provider error never leaks a traceback, endpoint or credential into the lab event stream.

### Model providers

`engine/agents/common.py:66` `make_model` is the single factory:

- **Akamai (default)** — `engine/agents/providers.py:6` subclasses `strands.models.openai.OpenAIModel`
  purely to drop `tools: []` / `tool_choice`, which that endpoint rejects with HTTP 400.
- **Bedrock** — `common.py:68–77` imports `strands.models.BedrockModel` and builds it with
  the configured `model_id`, `region_name`, `max_tokens=1500`, `streaming=False`, and a
  `botocore` config of `connect_timeout=10`, `read_timeout=request_timeout`,
  `retries={"total_max_attempts": 1, "mode": "standard"}`.

**Verdict on authenticity: the Strands usage is genuine.** `Agent`, `@tool`, four distinct
hook event types, `event.cancel_tool`, `event.interrupt`, `event.end_turn`, structured
output, and typed exceptions are all load-bearing. Remove Strands and there is no product.

---

## 2. Is the Bedrock path sound? — proven offline, unproven live

### Credentials: none exist on this machine

Checked, without printing any value: `AWS_BEARER_TOKEN_BEDROCK`, `AWS_ACCESS_KEY_ID`,
`AWS_SECRET_ACCESS_KEY`, `AWS_SESSION_TOKEN`, `AWS_PROFILE`, `AWS_REGION` — **all unset**.
`~/.aws/` **does not exist**. The repository-root `.env` contains only `DATABASE_URL`,
`AKAMAI_BASE_URL`, `AKAMAI_API_KEY`, `MODEL_ID` — no AWS keys and not even a blank
`BEDROCK_MODEL_ID`.

So: **no live Bedrock call has been made, by me or by anyone, from this checkout.**
`engine/agents/README.md:69` already says so honestly ("Bedrock configuration is implemented
but was not live-validated in Phase 2"), and that remains true.

### New offline proof: `engine/tests/test_bedrock_provider.py` (18 tests, additive)

Before this file, the only Bedrock coverage anywhere was two assertions that
`load_settings` *selects* the provider (`engine/tests/test_agents.py:114–115`). The
`make_model` Bedrock branch — the part that actually touches AWS — had **never executed**.

The new file guards its imports exactly like the existing suite
(`for dependency in ("strands", "boto3", "botocore", "dotenv"): pytest.importorskip(...)`
at module level, before any SDK import) and skips cleanly rather than breaking collection.
Verified by running the suite with an import hook that makes `boto3`/`botocore` raise
`ModuleNotFoundError`: both this file and `test_agents.py` report one module-level SKIP,
no collection error.

It needs no credentials because `botocore.stub.Stubber` intercepts at `before-call`, which
is **ahead of SigV4 signing**, and an autouse fixture empties every `AWS_*` variable and
repoints `AWS_CONFIG_FILE` / `AWS_SHARED_CREDENTIALS_FILE` at nonexistent paths so a
developer's real profile can never be read.

What it proves:

| Test | Proves |
|---|---|
| `test_use_bedrock_flag_spellings_select_bedrock_without_akamai_credentials` | `USE_BEDROCK` in `1 / true / TRUE / " True "` selects Bedrock even when Akamai vars are present, and the Bedrock `ModelSettings` carries **empty** `base_url`/`api_key` — the Akamai key cannot leak into an AWS request or a repr. |
| `test_bedrock_region_defaults_to_us_east_1_and_not_the_sdk_default` | The repo's own `us-east-1` default wins over Strands' `DEFAULT_BEDROCK_REGION` (`us-west-2`), and `AWS_REGION` overrides it. |
| `test_bedrock_configuration_is_validated_before_any_aws_call` | Whitespace-only `BEDROCK_MODEL_ID`, missing id, `USE_BEDROCK=yes`, and `MODEL_MIN_INTERVAL_S` of `0.5`/`31` each raise `ConfigurationError` naming the offending variable. |
| `test_unknown_explicit_provider_is_refused` | `--provider` / `load_settings(provider=...)` accepts only `akamai` or `bedrock`; a typo such as `sagemaker` is rejected rather than silently falling back. |
| `test_make_model_reaches_strands_bedrock_model_with_the_configured_id_and_region` | The object is a real `strands.models.bedrock.BedrockModel`; `config["model_id"]` is the configured id; `streaming is False`; `max_tokens == 1500`; the boto3 client is `bedrock-runtime` with signing name `bedrock` in the configured region; `read_timeout` tracks `request_timeout` (30 default, 60 from the worker); `connect_timeout == 10`; `retries.total_max_attempts == 1`; user agent contains `strands-agents`. **This is the "not merely that the import exists" check.** |
| `test_bedrock_bearer_token_variable_in_the_example_env_is_the_one_botocore_reads` | `agents.env.example:14` advertises `AWS_BEARER_TOKEN_BEDROCK`; botocore's `get_bearer_auth_supported_services()` contains `bedrock`, `_get_bearer_env_var_name("bedrock")` is exactly `AWS_BEARER_TOKEN_BEDROCK`, and the service model offers `smithy.api#httpBearerAuth`. So that documented variable really does work through the standard chain even though `make_model` never passes `api_key=` itself. |
| `test_bedrock_refuses_an_injected_openai_client` | `make_model(settings, client=...)` raises instead of silently falling through to the OpenAI-compatible provider. |
| `test_bedrock_agent_executes_a_tool_and_returns_a_validated_round_report` | **A complete Strands agent loop runs on `BedrockModel`.** Two stubbed `Converse` turns: the agent executes a `@tool` exactly once with the right argument, `SmokeHooks` counts 2 `BeforeModelCallEvent`s and observes `{"name": ..., "status": "success"}` from `AfterToolCallEvent`, and `result.structured_output` is a validated `RoundReport` equal to the supplied facts. The captured request carries `modelId`, `inferenceConfig == {"maxTokens": 1500}`, both tool specs, `toolChoice {"auto": {}}` — and **`ConverseStream` is never called**, confirming `streaming=False`. |
| `test_bedrock_structured_output_falls_back_to_a_forced_tool_choice` | When the model ends its turn without filling the schema, Strands retries with `toolChoice: {"tool": {"name": "RoundReport"}}`. This is the Bedrock-specific capability requirement in risk R3 below. |
| `test_bedrock_tool_denial_is_delivered_to_converse_as_a_tool_result` | `event.cancel_tool` blocks execution and the literal `DENIED` text reaches the next `Converse` request as a `toolResult` block — the safety guarantee holds in Bedrock's wire format, not just in the Akamai one. |
| `test_bedrock_throttling_is_surfaced_once_and_never_retried` | A `ThrottlingException` becomes a typed `strands` `ModelThrottledException`; Strands issues exactly one model call (`retry_strategy=None`); botocore is configured for one attempt; and `engine.worker.error_data` reports `{"error_type": "ModelThrottledException"}` — i.e. the round **fails**, it does not back off. |
| `test_bedrock_model_access_errors_keep_the_model_id_and_region_debuggable` | On `AccessDeniedException`, the exception notes carry the model id and region, so a per-account access failure is diagnosable from the worker's output. |
| `test_bedrock_pacing_uses_the_configured_minimum_interval` / `test_bedrock_configuration_requires_no_boto_client_for_validation` | `MODEL_MIN_INTERVAL_S` really paces Bedrock calls; and `load_settings` creates **no** boto3 session, so `--check-config` is genuinely offline (asserted by monkeypatching `boto3.Session` to raise). |

Suite result after adding the file: **`pytest engine/tests -q` → 114 passed, 1 skipped**;
whole configured suite **166 passed, 9 skipped**. No existing test was modified, weakened or
duplicated.

### What the offline proof does *not* establish

- That any `BEDROCK_MODEL_ID` is enabled for the team's AWS account.
- That the chosen model answers Converse with usable tool calls or fills `RoundReport`.
- Real latency, token usage, or throttling behaviour.
- That `run_red` / `run_blue` themselves complete a round on Bedrock. The new test drives
  the identical Strands machinery (tools + hooks + forced structured output) but through a
  synthetic tool, not through the lab API. `engine/tests/test_phase3.py:144` does the
  real-`run_red` version **on the Akamai path only**. That is the remaining coverage gap.

---

## 3. The exact switch — commands to run with credentials (UNVERIFIED LIVE)

Everything in this section is **untested against AWS**. Nobody has run it. Treat the output,
not this document, as the evidence.

```bash
# 1. Pick a model your account has access to, in a region that offers it.
#    Cross-region inference profiles are region-prefixed and must match AWS_REGION:
#    us.* -> a us-* region, eu.* -> an eu-* region.
aws bedrock list-foundation-models --region us-east-1 \
  --query 'modelSummaries[?contains(modelId,`claude`)].modelId' --output text
aws bedrock list-inference-profiles --region us-east-1 --output table   # for us.*/eu.* ids

# 2. Put AWS settings in the ignored repository-root .env (never in agents.env.example):
#      USE_BEDROCK=1
#      AWS_REGION=us-east-1
#      BEDROCK_MODEL_ID=us.anthropic.claude-sonnet-4-5-20250929-v1:0
#    plus EITHER a standard credential chain (AWS_PROFILE / ~/.aws/credentials / an
#    instance role) OR a single AWS_BEARER_TOKEN_BEDROCK=...

# 3. Offline configuration check — makes no model request. VERIFIED to work:
#    prints {"provider": "bedrock", ...} then {"status": "configured", "live_test_run": false}
.venv/bin/python -m engine.agents.smoke --check-config

# 4. Offline provider tests — no credentials needed. VERIFIED: 18 passed.
.venv/bin/pytest engine/tests/test_bedrock_provider.py -q

# 5. THE LIVE CHECK (never yet run). ~12 model calls, >=3s apart, non-streaming,
#    max_tokens=1500. Exit 0 = all five capabilities passed; 1 = a capability failed;
#    2 = configuration invalid.
.venv/bin/python -m engine.agents.smoke --provider bedrock

# 6. One bounded real Red round against a local lab (needs the lab API running).
.venv/bin/python -m engine.worker --check-api          # read-only, zero model calls
USE_BEDROCK=1 .venv/bin/python -m engine.worker --once red --round 1
```

`--provider bedrock` and `USE_BEDROCK=1` are equivalent and neither switches silently
(`engine/agents/smoke.py:174`, `common.py:32–35`). Process environment beats `.env`
(`common.py:30`, `override=False`), so the one-line `USE_BEDROCK=1` prefix in step 6 works
without editing `.env`.

**When step 5 is run, record from its JSON:** `provider`, each check's `status` and
`model_calls`, and the total. Note that the JSON does **not** currently print the model id,
the region, or the boto3 version — see [Defect 3](#defect-3-a-live-bedrock-run-cannot-prove-which-model-and-region-it-used).
Capture latency with `/usr/bin/time` and token usage from CloudWatch
(`AWS/Bedrock` → `InputTokenCount` / `OutputTokenCount`, dimension `ModelId`) or from
CloudTrail, since the harness deliberately does not log provider response bodies.

---

## 4. What breaks on Bedrock that does not break on Akamai

Ordered by how likely it is to ruin a demo.

**R1 — The deployed worker ignores every Bedrock variable.** Not a risk; a certainty.
See [Defect 1](#defect-1-the-deployed-worker-cannot-be-switched-to-bedrock). Setting
`USE_BEDROCK=1` in the VM's `.env` changes nothing and raises no error: the container keeps
calling Akamai. Fix before claiming the AWS track end-to-end.

**R2 — Throttling is a hard round failure, by design.** Bedrock on-demand quotas are
per-account, per-model, per-region, and a tool loop is bursty. Both retry layers are
deliberately off: `retries={"total_max_attempts": 1}` (`common.py:77`) and
`retry_strategy=None` (`red.py:111`, `blue.py:175`, `smoke.py:32`). Strands' *default*
retry strategy would back off on `ModelThrottledException`; this code opts out. The new test
proves one `ThrottlingException` → `{"error_type": "ModelThrottledException"}` → round
`failed` in `worker_state`. `MODEL_MIN_INTERVAL_S=3` paces **one process** only
(`hooks.py:14` says so explicitly) and does nothing about an account-level quota. The
Akamai workshop endpoint has been forgiving enough that this never surfaced.

**R3 — Forced structured output requires a model that honours `toolChoice`.** Bedrock
Converse always receives a `toolConfig.toolChoice` once any tool exists
(`strands/models/bedrock.py:421`), and the structured-output fallback escalates to
`{"tool": {"name": "RoundReport"}}` — proven in the new test. Converse models differ in
`toolChoice` support; a model that rejects forced tool choice fails with a
`ValidationException` and `RoundReport` never validates, so the round raises
`"did not produce a typed report"` (`red.py:124`). Pick an Anthropic Claude model id.
The OpenAI-compatible path has no equivalent constraint — in fact `AkamaiModel` exists
precisely to *remove* `tool_choice` (`providers.py:12`).

**R4 — The per-round 300 s `wait_for` is tight at Bedrock latencies.** Arithmetic a
reviewer can redo: Red allows 16 model calls (`red.py:53`) paced ≥3 s apart
(`hooks.py:30`), so 15 gaps = ≥45 s of sleep, leaving ≤255 s for 16 round-trips — an average
of **~16 s per call** before `asyncio.wait_for(..., timeout=300)` (`red.py:122`) fires.
Blue is tighter: 24 calls (`blue.py:102`) → 69 s of pacing → **~9.6 s per call** against the
same 300 s (`blue.py:188`). Typical rounds use far fewer calls (Red is prompted toward 3–5
attempts), so this is a ceiling rather than a guarantee of failure — but non-streaming
Converse with `max_tokens=1500` on a Claude-class model routinely takes 10–30 s, where the
Akamai workshop model has been answering in a few seconds. Worth noting that
`RequestBudget.acquire` uses a blocking `time.sleep` inside an async hook (`hooks.py:16`,
`hooks.py:32`), so the pacing is charged in full against the same wall-clock timeout.

**R5 — The 60 s read timeout is not retried.** `worker.py:116` passes
`request_timeout=60`, which becomes botocore `read_timeout=60` (`common.py:76`) — shorter
than Strands' own Bedrock default of 120 s. A single slow Converse call raises
`botocore.exceptions.ReadTimeoutError`, which is **not** a `ClientError`, so Strands' error
mapping (`strands/models/bedrock.py:1520`) does not touch it; verified locally that it
surfaces as `{"error_type": "ReadTimeoutError"}` through `worker.error_data`, and
`total_max_attempts=1` means no second attempt. On a reasoning-capable Bedrock model this
is a realistic single-call failure; on the Akamai endpoint 60 s has been ample.

**R6 — Model access and id/region coupling are per-account, invisible until the first
call.** `BEDROCK_MODEL_ID` must be enabled for the account in that exact region, and
region-prefixed inference-profile ids (`us.*`, `eu.*`, `apac.*`) only work inside the
matching region group. A bare foundation-model id for a model that requires an inference
profile fails with `"on-demand throughput isn't supported"`. Strands attaches targeted notes
for all three cases (`strands/models/bedrock.py:1540`, `:1551`, `:1561`), and the new test proves the
model id and region survive into those notes. The repo's default `AWS_REGION=us-east-1`
(`common.py:49`) differs from Strands' `us-west-2`, so a copied model id may land in the
wrong region.

**R7 — Converse tool-schema strictness, unverified.** Red and Blue tool signatures become
Converse `toolSpec.inputSchema.json`. Blue's `propose_variant(features: dict[str, list[float]], ...)`
(`blue.py:122`) produces a schema with `additionalProperties`, and `transplant_human_error`
takes a bare `int`. Claude models handle this; the new test only validates the *synthetic*
probe tool's schema through Converse, so Blue's real six-tool payload has not been exercised
on Bedrock. Closing this means a Bedrock twin of `engine/tests/test_phase3.py:144`.

**R8 — No cost or quota ceiling.** 16–24 calls per round at `max_tokens=1500`, with a worker
that polls the command queue forever (`worker.py:66`). Akamai is a fixed workshop quota;
Bedrock bills per token against a real account. Nothing in the repo caps spend.

### Non-risks worth stating, so nobody re-investigates

- **`boto3` is already installed everywhere `strands` is.** `boto3<2,>=1.26` and
  `botocore<2,>=1.29` are *core* `Requires-Dist` of `strands-agents` 1.59.0, not extras. The
  worker image (`engine/Dockerfile` → `engine/requirements.txt` → `strands-agents[openai]==1.59.0`)
  already contains them. No dependency change is needed to run Bedrock.
- **Interrupts, `cancel_tool`, `end_turn` and the budget hooks are provider-agnostic** —
  Strands event-loop machinery, not wire-format behaviour. The new denial test confirms the
  Bedrock wire format carries them.
- **`--check-config` really is offline** for Bedrock (asserted by a test that makes
  `boto3.Session` raise).

---

## 5. Defects in files I do not own

Reported, not patched. Exact diffs below; `engine/` belongs to Person 2 and the root compose
file to Person 1.

### Defect 1 — the deployed worker cannot be switched to Bedrock

`compose.yaml:21–28` gives the `worker` service an explicit `environment:` allowlist and
**no** `env_file: .env`. The allowlist contains only `AKAMAI_BASE_URL`, `AKAMAI_API_KEY`,
`MODEL_ID`, so `USE_BEDROCK`, `BEDROCK_MODEL_ID`, `AWS_REGION` and
`AWS_BEARER_TOKEN_BEDROCK` never enter the container. The image also has no `.env` to fall
back on (`engine/Dockerfile` copies only `engine/` and two `contracts/` paths), so
`worker.py:101`'s `load_dotenv` finds nothing. Result: setting `USE_BEDROCK=1` on the VM is
**silently ignored** — no error, no log line, Akamai keeps serving. `deploy.sh:47` already
symlinks `.env` into the release dir, so Compose can interpolate these; only the allowlist
is missing.

```diff
--- a/compose.yaml
+++ b/compose.yaml
@@ -25,4 +25,9 @@ services:
       AKAMAI_BASE_URL: ${AKAMAI_BASE_URL:-https://ws.akamai-workshops.com/v1}
       AKAMAI_API_KEY: ${AKAMAI_API_KEY:-}
       MODEL_ID: ${MODEL_ID:-hackathon-chat}
+      # Explicit AWS Bedrock fallback; the worker never switches provider on its own.
+      USE_BEDROCK: ${USE_BEDROCK:-0}
+      BEDROCK_MODEL_ID: ${BEDROCK_MODEL_ID:-}
+      AWS_REGION: ${AWS_REGION:-us-east-1}
+      AWS_BEARER_TOKEN_BEDROCK: ${AWS_BEARER_TOKEN_BEDROCK:-}
       WORKER_STATE_PATH: /srv/engine/.state/worker.sqlite3
```

(SigV4 instead of a bearer token additionally needs `AWS_ACCESS_KEY_ID`,
`AWS_SECRET_ACCESS_KEY` and optionally `AWS_SESSION_TOKEN` added the same way, or a mounted
`~/.aws`. The bearer token is the smaller change and is the one `agents.env.example:13–14`
already recommends.)

### Defect 2 — `engine/compose.worker.yaml` is dead and would not start a worker

`engine/compose.worker.yaml` sets only `API_BASE`, `LAB_ALLOW_INTERNAL_HTTP` and
`WORKER_STATE_PATH` — no `LAB_KEY`, no model configuration at all — so the worker would exit
on a missing key. Nothing uses it: `engine/deploy-worker.sh` execs the root `deploy.sh`,
which builds from `compose.yaml`. Either delete it or make it a real override; leaving a
stale second compose file next to the one that matters is how an operator switches the wrong
thing at 4 a.m.

### Defect 3 — a live Bedrock run cannot prove which model and region it used

`engine/agents/smoke.py:184–185` prints `{"provider", "versions", "stream", "max_tokens"}`
and reports `openai`'s version even on the Bedrock provider, while never printing
`model_id`, `region`, or the `boto3`/`botocore` versions. For the AWS track that is exactly
the evidence a judge wants, and it is the one run nobody can reproduce for them. None of
these values are secret (`ModelSettings` keeps `api_key` out of its repr by construction —
`common.py:23`).

```diff
--- a/engine/agents/smoke.py
+++ b/engine/agents/smoke.py
@@ -181,8 +181,12 @@ def main(argv=None):
     except ConfigurationError as exc:
         print(json.dumps({"status": "configuration_required", "reason": str(exc)}), flush=True)
         return 2
-    versions = {name: importlib.metadata.version(name) for name in ("strands-agents", "openai")}
-    print(json.dumps({"provider": settings.provider, "versions": versions, "stream": False, "max_tokens": 1500}), flush=True)
+    packages = ("strands-agents", "boto3", "botocore") if settings.provider == "bedrock" else ("strands-agents", "openai")
+    versions = {name: importlib.metadata.version(name) for name in packages}
+    # Model id and region are not credentials; they are the evidence a reviewer needs.
+    print(json.dumps({"provider": settings.provider, "model_id": settings.model_id,
+                      **({"region": settings.region} if settings.provider == "bedrock" else {}),
+                      "versions": versions, "stream": False, "max_tokens": 1500}), flush=True)
     if args.check_config:
```

### Observations, not defects

- **Blocking sleep in an async hook.** `RequestBudget.acquire` calls `time.sleep`
  (`hooks.py:32`) from `SmokeHooks.before_model` (`hooks.py:54`), which runs on the event
  loop. It is correct for throughput but it freezes the loop and is charged against the
  300 s `wait_for` (R4). An `await asyncio.sleep` equivalent would need an async hook.
- **Optional retry policy for Bedrock only.** If a live run hits throttling, the smallest
  change is `retries={"total_max_attempts": 3, "mode": "adaptive"}` in `common.py:77`.
  That knowingly trades the project's "no hidden retries" principle for demo survival, so it
  is Person 2's call, not a fix I would apply unilaterally.
- **Python version drift.** The local venv is 3.14.7; `engine/Dockerfile` pins
  `python:3.12-slim` and `engine/agents/README.md:10` says 3.12. Harmless today (all 166
  tests pass on 3.14), but the Bedrock path has only ever been exercised on 3.14 locally.

---

## 6. Bottom line for a judge

| Claim | Status |
|---|---|
| Built on the Strands Agents SDK | **Proven.** `Agent`, `@tool`, 4 hook event types, `cancel_tool`, `interrupt`, `end_turn`, typed structured output, typed exceptions — all load-bearing, all cited above, all covered by 114 passing engine tests. |
| Strands' AWS Bedrock model provider is wired and reachable | **Proven offline.** `make_model` builds a real `strands.models.BedrockModel` on a `bedrock-runtime` client with the configured model id, region, timeouts and single-attempt retry policy; a full agent loop — tool call, denial, forced structured output, throttling — runs against a stubbed Converse transport in `engine/tests/test_bedrock_provider.py`. |
| Red and Blue have run on Amazon Bedrock | **No. Never. Not once.** No AWS credentials exist in this environment. Every live round to date used the Akamai OpenAI-compatible endpoint. |
| Bedrock can be switched on in the deployed system today | **No** — `compose.yaml` drops the variables ([Defect 1](#defect-1-the-deployed-worker-cannot-be-switched-to-bedrock)). Fixable in five lines. |

The honest sentence to put in the submission: *"The agents are Strands Agents; the AWS
Bedrock provider is implemented through Strands' `BedrockModel` and covered by tests that
construct and drive it offline, but it has not yet been validated against live Bedrock."*
Anything stronger than that will not survive a reviewer who opens the repo.

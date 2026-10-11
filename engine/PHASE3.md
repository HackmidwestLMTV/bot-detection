# Human calibration and local Red rounds

Install both `engine/requirements-agents.txt` and `engine/requirements-dev.txt`
in the Python 3.12 environment used for Phases 1 and 2. Model settings stay in
the ignored repository-root `.env` as described in `engine/agents/README.md`.

## Audit real recordings

Keep recording through `http://127.0.0.1:8000/dev/recorder`. Save only actual
consented human input; select the device you actually use. Phone setup is
documented in `engine/README.md`.

```powershell
.\.venv\Scripts\python.exe -m engine.calibrate
```

The audit checks consent, cohort, device, seed, sample validity, and duplicate
recordings. It recomputes all five features and proposes each band's 5th–95th
percentiles with 10% of that span added on each side, rounded to three decimals.
Feature enablement and the pass threshold remain unchanged. A constant or
rounding-collapsed feature keeps its baseline band and is explicitly flagged.

The JSON report includes per-device human rejections under both configurations,
any failing human files, and perfect-target forgery results on the recorded
seeds. It exits 2 when evidence or sanity checks are incomplete, otherwise 0.
Readiness requires at least 10 unique recordings, all three device groups, no
invalid files or degenerate bands, all recorded humans passing, and all tested
perfect-target forgeries failing. This is an in-sample check on a small team
dataset, not an accuracy estimate. The metadata audit cannot prove a recording
was made by a human.

The command only prints a candidate; it does not edit shared v1 or activate a
variant. Review and coordinate a shared-fixture change separately with Person 1,
including a contract changelog entry. Do not silently widen bands until a desired
outcome appears.

## Start a disposable Red lab

In another terminal, from the repository root:

```powershell
$env:LAB_KEY = 'dev'
.\.venv\Scripts\python.exe -m uvicorn engine.labserver:app --host 127.0.0.1 --port 8001
```

This separate app implements only the challenge, red attempt, active variant,
forgery listing, and event routes needed by Red. State lives in memory and is
discarded on restart. It never writes human files, stores raw trails, or issues
reservation tokens. It requires the lab key even for challenge creation, limits
each challenge to one scored attempt, and caps stored attempts/events. It is not
a production API emulator: sessions, rate limiting, Blue routes, SSE delivery,
database storage, and command queues remain outside this phase.

## Run Red

```powershell
$env:API_BASE = 'http://127.0.0.1:8001'
$env:LAB_KEY = 'dev'
.\.venv\Scripts\python.exe -m engine.worker --once red
# Once ready to test residual transplantation:
.\.venv\Scripts\python.exe -m engine.worker --once red --round 3
```

Each command runs once and prints a JSON report. It exits 1 on failure and emits
a sanitized error event when the API is reachable. `--round` explicitly chooses
the round number; there is no persistent round counter or queue consumer yet.
Commands use unique run IDs so evidence stays separate.

The first successful attack must use zero parameters. The model can then adjust
delay, noise, correction frequency, and overshoot. Hooks enforce eight forge
calls and four transplants per round, including failed calls. Transplantation is
unavailable before round 3 and requires valid consented local team recordings.
The model sees indices and scores, never raw recorded samples. Synthetic trails
travel only to the configured lab, with cohort `red` enforced by the client.

The client uses fixed API routes, rejects non-HTTPS remote origins and embedded
URL credentials, and refuses redirects. Each HTTP request has a 15-second
timeout. The contract attempt response has no attempt ID, so the client obtains
the new ID from the round's forgery listing. It fails if the result is ambiguous;
the API must make the scored attempt visible immediately.

Model pacing uses Phase 2's configured interval, with at most 16 model calls and
a 300-second asyncio deadline per round. The worker uses a 60-second model request
timeout because live runs exceeded the smoke harness's 30-second timeout when
finishing longer conversations. Network operations also have their own
timeouts; synchronous operations can delay cancellation. Budgets are per process.
Final attempt counts, pass counts, best parameters, and evidence IDs come from
observed tool results. `what_changed` remains model-written commentary.

Inspect events locally:

```powershell
Invoke-RestMethod http://127.0.0.1:8001/dev/events -Headers @{'X-Lab-Key'='dev'}
```

Person 1's inspected `origin/p1-platform` still lists the lab routes as TODOs.
Local Red verification therefore does not establish platform or deployment
integration. Blue, dashboard approval, command polling, and Linode remain later
work. This phase stays uncommitted until approved.

## Verification on 2026-10-10

- Full offline suite: **67 passed**; dependency check: no broken requirements.
- Live Akamai run `run_9652f0e3d25f4d599f60c4e1caf14f8d` completed using eight model
  calls, seven scored attempts, and four passes. The first all-zero attempt scored
  0.25 and failed; passing attempts scored 0.75 against the unchanged provisional
  v1 bands. Counts and evidence IDs matched the stored attempts.
- Earlier live attempts timed out during completion. The successful run used the
  explicit 60-second worker timeout. One successful run is not a reliability claim.
- Transplantation was verified through the actual SDK against a scripted model
  and the local HTTP app; a live-model round 3 has not been run.
- Latest human audit: nine valid recordings (eight mouse, one trackpad, no touch).
  The draft bands accept all nine and reject the perfect-target forgeries on all
  nine recorded seeds. Calibration remains incomplete pending touch evidence and
  the minimum count; shared v1 is unchanged.

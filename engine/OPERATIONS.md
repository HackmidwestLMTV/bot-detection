# Person 2 engine and agent operations

The engine, Red, Blue, fixed gate, and queue worker are implemented under `engine/`.
The platform remains Person 1's `web/` on `p1-platform`. Our branch is **p2**.

## Install and run

Use Python 3.12 from the repository root:

```powershell
.\.venv\Scripts\python.exe -m pip install -r engine/requirements.txt -r engine/requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q
```

`requirements.txt` now includes runtime agent dependencies so Person 1's existing
image build can import the worker. `requirements-core.txt` is the smaller option
for engine/recorder-only development. `requirements-agents.txt` is a compatible
alias for the full runtime.

Put model credentials and `API_BASE`/`LAB_KEY` in the ignored root `.env` (see
`agents.env.example`). Never commit credentials. Blue sends per-device counts
and aggregate human-feature statistics to the configured model; raw human trails
stay local. The user explicitly authorized aggregate statistics to Akamai in this
session. Red sends synthetic feature results. Transplantation reads only local,
consented team traces and submits the generated forgery to the configured lab.

```powershell
# Read-only platform readiness check; no model calls or queue claims:
.\.venv\Scripts\python.exe -m engine.worker --check-api
# One round:
.\.venv\Scripts\python.exe -m engine.worker --once red
.\.venv\Scripts\python.exe -m engine.worker --once blue
# Consume dashboard commands until Ctrl+C:
.\.venv\Scripts\python.exe -m engine.worker
```

`--round 3` with `--once red` explicitly tests transplantation. Otherwise each
agent's round number persists in `engine/.state/worker.sqlite3`. `--state` or
`WORKER_STATE_PATH` can select another journal; `--traces` or `HUMAN_TRACES_DIR`
selects consented local traces. Use a new state file for a fresh demo sequence:
the platform's Reset button does not reset the worker's journal.

## Local lab and approvals

The recorder stays on port 8000. Start the disposable lab separately:

```powershell
$env:LAB_KEY = 'dev'
.\.venv\Scripts\python.exe -m uvicorn engine.labserver:app --host 127.0.0.1 --port 8001
```

Open `http://127.0.0.1:8001/lab`, enter the local key, and connect. Start the worker
in another terminal with `API_BASE=http://127.0.0.1:8001` and matching `LAB_KEY`.
Run Red and Blue from the buttons. Human features are loaded from consented local
recordings when the lab starts. Restart after adding recordings. A local-only
`LAB_FORGERIES_FILE` may point to a JSON object with a `forgeries` array to restore
previous synthetic scoring evidence; it is never treated as human evidence.

Blue can read forgery scores, per-device human percentiles, and the active rule;
propose at most three candidates; run the fixed gate; and request activation.
Gate, approval-card, and activation events come from the server, matching Person
1's current API and avoiding duplicate dashboard cards.

An activation request interrupts Strands. The worker runs the gate again, requests
a dashboard decision, and polls for up to 180 seconds (configurable with
`--approval-timeout`, 1–1800). It resumes with `y` only after approval and unchanged
evidence. The activation tool checks the gate, approval status, and evidence a
final time and consumes its local grant. Denial, timeout, unknown status, or
changed evidence cannot activate. An approval that times out may still be visible
on the platform; the worker does not decide it on the person's behalf.

After confirmed activation the SDK stops without another model call. The worker
builds a typed report from observed proposal/activation counts and the candidate's
stated rationale. This avoids losing a completed change to a model-summary timeout.
Other round summaries still use validated Strands structured output.

The disposable lab also enforces an approving gate and evidence-bound, single-use
approval at activation. Person 1's current server checks for an approved approval,
but does not atomically bind it to current gate evidence. The worker enforces those
checks on its path; Person 1 still needs server-side enforcement for direct API
callers and the race between final client verification and server activation.

## Budgets, failures, and restart behavior

- Red: eight forge calls, four transplants from round 3, and 16 model calls.
- Blue: three proposals, bounded reads/gate/activation calls, and 24 model calls.
- Requests are paced across rounds in one worker process. Run one worker replica;
  separate processes do not share the workshop's model quota.
- Model requests time out after 60 seconds; HTTP lab calls after 15 seconds.
  Red invocations have a 300-second deadline. Blue has bounded invocation and
  approval waits plus an outer deadline. Synchronous HTTP operations can delay
  cancellation until their own timeout.
- SDK/provider retries remain off. Queue connection failures back off up to 30
  seconds. Failed runs emit sanitized error events and do not kill the daemon.
- The SQLite journal claims each run at most once and survives restarts. A run
  interrupted by a crash is not automatically replayed, preventing duplicate
  proposals or activation. Queue a new run to retry. The shared command API has
  no lease/ack/requeue endpoint; there is no exactly-once recovery guarantee.

## Person 1 integration and deployment

The inspected `origin/p1-platform` at `180122a` has the required routes and imports
the real engine. Check another checkout without changing its DB:

```powershell
.\.venv\Scripts\python.exe -m engine.check_platform PATH_TO_PLATFORM_CHECKOUT
```

This checks route presence and adapter behavior, not database transactions or a
running site. This workstation has no Docker/Postgres runtime available, so the
full platform database suite and container build have not been run here.

After the reviewed code is committed and pushed to `p2`, Person 1 can run the
engine-owned helper from their prepared VM checkout:

```bash
bash engine/deploy-worker.sh
```

For the first integration, get `engine/` into that checkout with
`git archive origin/p2 engine | tar -x` after fetching. The helper uses `origin/p2`,
copies only `engine/`, builds the app and dedicated worker image, and checks API
readiness. It does not provision a VM or change shared contracts. Review local
engine changes first, since extraction overwrites matching files.

The Compose override selects `engine/Dockerfile`, persists worker state, and opts
in specifically to `http://app:8000`. Other remote HTTP origins remain rejected;
use HTTPS outside the Docker service network. The dedicated worker build excludes
`.env`, local runtime state, and human recordings. Mount approved team recordings
read-only on the VM if transplantation is needed; do not bake them into the image.
Person 1's original `deploy.sh` still uses `p2-engine`; use this helper or update
that reference to `p2` before integration.

## Verification and remaining evidence

The suite covers path parity, all scorer features, consented recording, calibration,
residual transplantation, real SDK tool loops, budget enforcement, gate regression,
approval/denial/timeout/stale evidence, report integrity, and persistent command
dispatch. Scripted SDK fixtures never go into `human_traces/`.

Final local verification: 79 engine/worker tests and three Person 1 adapter tests
passed; the dependency consistency check found no conflicts. Container builds
and database-backed platform integration still require the target environment.

Live Akamai Red completed seven attacks with four passes against provisional v1.
Live Blue proposed one candidate reducing accepted forgeries from 9/16 to 6/16;
mouse rejections stayed 1/8 and trackpad rejections stayed 0/1. The user explicitly
approved it in the disposable localhost lab, and activation was verified. Its
original model explanation timed out; a clearly labeled report was recovered from
server events. The SDK now ends immediately after activation, verified by tests.

Calibration remains provisional: nine consented recordings, eight mouse and one
trackpad, with no touch evidence. Shared v1 is unchanged. The audit-generated draft
accepts all nine but cannot establish unseen-user accuracy. Finish the tenth/touch
recording and rerun `python -m engine.calibrate` before coordinating shared-band
changes with Person 1. Never force the gate or tune forgeries to manufacture a win.

Local replay evidence is saved in ignored `engine/.state/verified-cycle.jsonl`.
If shown as a recording, label it **REPLAY**. Local runtime evidence, credentials,
human recordings, and changes to todo and phase notes are excluded from this
implementation commit.

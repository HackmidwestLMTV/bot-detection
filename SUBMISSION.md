# Follow It

## What it is

Checkout CAPTCHAs are broken theater: they annoy real people and bots solve them
anyway. Follow It replaces the image puzzle with a 3-second task — follow a moving
dot with your finger or mouse — and scores the motion instead of asking a riddle.

But the actual point of this project isn't the comet. It's the loop around it:
one AI (**Red**) tries to learn a motion pattern that fools the scorer. A second
AI (**Blue**) proposes a stricter rule to catch it. Before that rule can go live,
a **fixed, non-AI gate** replays every stored human trace and every forgery
through both the old and new rule and reports, in plain numbers, how many real
people the new rule would additionally lock out and whether it actually catches
more fakes. A person reads that number and decides. The server — not the agent,
not the UI — refuses to activate anything without a recorded approval.

That is the pitch: **AI attacks, AI defends, a fixed arithmetic gate measures the
human cost before a person signs off.**

## Honest demo path — what a judge can actually see right now

Run locally (`.venv/bin/uvicorn web.app:app --port 8000` against a local Postgres,
or `python -m web.dev.replay_events --reset` to seed `/lab` from a fixture):

1. **`/`** — follow the comet for 3 seconds. A pass issues a single-use token;
   reserve a demo ticket; reuse the token and get `409`. Skip, fail, or set
   reduced-motion and you get a keyboard-accessible proof-of-work fallback instead
   — that fallback adds computation cost, not proof of humanity.
2. **`/lab`** — enter the lab key. **Run Red**: an AI agent calls real tools
   against the live scorer and streams its attempts as events. **Run Blue**:
   a second AI agent proposes a stricter variant. The gate replays stored human
   and forgery evidence and renders a verdict with numbers. **Approve**: only
   then does the variant activate; trying to activate without an approved row
   returns a hard `403` from the server.
3. **`/research`** — operator-issued invitations and phone QR codes for
   collecting consented movement recordings for offline model comparison. This
   is research tooling, not something that affects live scoring.

No live cloud deployment is required to see any of this. Everything above runs
against a local Postgres and the real `engine/` code — nothing is stubbed out
for the demo.

If the stage build is flaky, the honest fallback is `backup_run.jsonl` /
`recordings/rehearsal-synthetic-humans.jsonl` replayed at `/lab?replay=1` (banner
visible, every control disabled — it is explicitly a recording, not a live run).

## Architecture

```text
 phone / browser ──HTTPS──▶ Caddy ──▶ FastAPI app (web/) ──▶ Managed Postgres
                                         │   │  └──────────▶ Object Storage (consented trails, 72h)
                                         │   └─ engine_adapter ─▶ engine/ (path, scorer, gate: pure functions)
 /lab dashboard ◀──── SSE ───────────────┤
                                         │  HTTP (X-Lab-Key)
                         agent worker ───┘  Red + Blue (strands.Agent) ──▶ Akamai hosted inference
```

Real and running today, locally verified:
- FastAPI app (`web/`), Postgres-backed challenge/score/token/gate/approval logic.
- `engine/` pure functions (`path.py`, `scorer.py`, `gate.py`, `forger.py`) — no
  stubs when `engine/` is present; `web/engine_adapter.py` logs which mode it's in.
- Red and Blue as real `strands.Agent` instances with `@tool` tools and
  `strands.hooks` lifecycle hooks, calling Akamai's hosted `ws.akamai-workshops.com`
  endpoint over HTTP, driving the recorded Red→Blue→gate→approval cycle in
  `recordings/rehearsal-synthetic-humans.jsonl`.
- The server-side `403` on activation without an approved row (`web/routes_lab.py`).

Configured but **not** verified running in the cloud as of this writing:
- Linode VM, Managed PostgreSQL 18, S3-compatible Object Storage — scripted in
  `deploy.sh`, `vm_setup.sh`, `compose.yaml`, `Caddyfile`, and **deployed and live**
  at <https://172-238-40-140.sslip.io> with a valid certificate. Verified directly
  against that deployment: `/healthz` reports `engine: real` and
  `path_version: smooth_v2`; the browser end-to-end suite passes 8/8; and the
  concurrency test prints `1 success, 19 rejected` against its Managed PostgreSQL
  cluster, so single-use passes hold under 20 parallel redeems in production.
- A Bedrock provider path (`USE_BEDROCK=1` → `strands.models.BedrockModel`) exists
  in `engine/agents/common.py` and is implemented, but was not the provider used
  in any run described in this document — Akamai was.

## The gate — the part that isn't a CAPTCHA demo

A CAPTCHA vendor can claim "99% accuracy" with no visibility into who that 1%
locks out. Follow It's gate is deliberately not a model: it's fixed arithmetic
(`engine/gate.py`), so it can't be argued with or tuned to look good.

**Rule:** a candidate scoring variant is approved for human review only if —
- **no device group (mouse, trackpad, touch) rejects more humans than the
  active baseline does**, and
- **fewer stored forgeries pass under the candidate than under the baseline**.

Otherwise it's `reject`, with a reason listed per violated condition (e.g.
`"rejects 4 of 4 trackpad users (baseline 0)"`). The gate only ever reads stored
feature values, never raw trails, so it's instant and auditable.

Passing the gate is **not** activation. A human still has to press Approve on
`/lab`, and the server enforces that independently: `POST
/v1/variants/{id}/activate` returns `403` unless an unconsumed `approvals` row
for that exact variant has `status='approved'`, and `403` again if the gate,
re-evaluated at activation time, no longer matches what was approved (verified
by reading `web/routes_lab.py`'s `_activate` function — this check exists in the
HTTP handler itself, not just the agent's judgment or the dashboard UI).

Known sharp edge, documented in `reviews/demo-runbook.md` and reproduced by reading
`engine/gate.py`: once a baseline already blocks 100% of stored forgeries
(`passed["candidate"] >= passed["baseline"]` with both at 0), no later candidate
can ever show *fewer* forgery passes than zero, so a second Blue round after a
full-block baseline rejects by construction, not by bug. Demo only one Blue round
per reset.

## Prize tracks

### AWS — Strands Agents SDK
Genuinely used, not bolted on for the prize. `strands-agents==1.59.0` is the
actual agent framework: confirmed installed (`pip show strands-agents`) and
imported directly in `engine/agents/red.py`, `blue.py`, `hooks.py`, `common.py`.
Red and Blue are `strands.Agent` instances with `@tool`-decorated tools and
`strands.hooks` (`BeforeToolCallEvent`, `AfterToolCallEvent`, `AfterToolsEvent`)
for lifecycle control, plus typed structured output (`RoundReport`). A Bedrock
provider path exists (`USE_BEDROCK=1` → `strands.models.BedrockModel`,
`engine/agents/common.py`) and is implemented, but every run referenced in this
repo — the Phase 2 smoke test (12 model calls) and the recorded rehearsal cycle —
ran against **Akamai**, not Bedrock. See `reviews/aws-strands-track.md` for the
fuller, independently-written verification of this track; this section is kept
short deliberately to avoid duplicating it.

### Akamai — the strongest claim here
Deeply used, and not just as a label:
- **Hosted inference** at `ws.akamai-workshops.com` (`hackathon-chat` model id)
  drives both Red and Blue through Strands — this is the actual model backend,
  confirmed in `engine/agents/common.py` and exercised in the Phase 2 smoke test
  and the recorded rehearsal cycle.
- **Linode compute, Managed PostgreSQL 18, and S3-compatible Object Storage** are
  the explicit deployment target: scripted end-to-end in `deploy.sh`,
  `vm_setup.sh`, `compose.yaml`, and `Caddyfile` (confirmed by reading all four).
- **It is deployed and reachable**: <https://172-238-40-140.sslip.io>, valid TLS,
  real engine. `phases.md`'s status table still says "unconfirmed" — that table is
  stale, and the deployment was confirmed directly rather than from documentation.
- Two caveats that remain true and should not be glossed: object storage is **not**
  configured on that deployment, so consented raw trails are skipped rather than
  uploaded (`web/storage.py` degrades to `None` by design); and the deployed
  revision is **older than `main`**, so it predates the typography and catch-zone
  fixes — a judge on Android will see fallback fonts.

### DevRev
Not attempted. No DevRev SDK, API call, or reference exists anywhere in this
repository (checked by search — zero hits). If this track matters, it is
unstarted work, not a partially-built integration.

## What is verified — real numbers, checked while writing this

- **Python test suite**, run against a disposable local Postgres 18
  (`DATABASE_URL=... .venv/bin/pytest -q`): **250 passed, 3 skipped** (253
  collected) — 6 in `contracts/`, 96 passed/1 skipped in `engine/tests`, 148
  passed/2 skipped in `web/tests`. The 3 skips are the documented optional ones
  (stub-scorer example, and the external-site concurrency twin that needs
  `FOLLOWIT_LIVE_URL`).
- **Frontend unit tests** (`node --test web/tests/*.test.*`): **19 passed, 0
  failed** — ticket-controller state transitions, PoW worker restart/retry
  logic, lab evidence display, consent withdrawal, research-enrollment flow.
- **Real-browser end-to-end checks**, run just now against a live local app with
  the real engine using actual headless Chrome (DevTools Protocol, synthetic
  real pointer/touch events, not mocked fetches): **11 of 11 passed** —
  8/8 in `browser_e2e.mjs` (mouse pass+token, phone-scaled canvas, real touch
  with capture, reserve→409 on reuse, skip→PoW→reserve, reduced-motion path,
  short-trail 422+retry, zero console errors across the whole run), 2/2 in
  `presentation_e2e.mjs` (checkout and recorder render identical plain-ring
  display), 1/1 in `research_e2e.mjs` (enrolled collection flow). Note: this is
  more checks than `reviews/product-demo.md`'s "ten Chrome browser checks" and
  more unit tests than its "15 frontend checks" — those figures predate the two
  most recent commits on this branch; the numbers above are from this run.
- **Recorded Red/Blue/gate/approval cycle**
  (`recordings/rehearsal-synthetic-humans.jsonl`, 48 events, inspected directly):
  Red starts at score 0.0 (all 4 enabled features out of band) and reaches a full
  pass (score 1.0) in 5 attempts / 6 model calls, with `jitter_px` converging
  32.2 → 9.9 → 6.7 → 5.19 as its synthetic noise parameter is tuned down — matches
  the round report stored in the file exactly. Blue proposes three candidates;
  the gate rejects the first two (rejects 100% of mouse/touch/trackpad "humans"),
  approves the third (0 humans rejected in any of 3 device groups, forgeries
  passed drop from 4/5 under baseline to 0/5 under the candidate), a person
  approves it, and it activates. The cycle is real end-to-end mechanics —
  **the 14 "human" traces behind every one of these numbers are synthetic**
  (see Limitations).
- **Server-enforced activation gate**: confirmed by reading
  `web/routes_lab.py` (`_activate`, lines ~150-167) — `POST
  /v1/variants/{id}/activate` requires an unconsumed `approvals` row with
  `status='approved'` for that exact variant (`403` if missing), then
  re-evaluates the gate and rejects (`403`) if the verdict or evidence
  fingerprint has changed since approval. This runs in the HTTP handler itself,
  independent of anything the agent or dashboard does.

## Known limitations — stated plainly

- **Zero real human calibration data.** Every gate number anywhere in this repo
  — in the recorded rehearsal cycle, in any `/healthz` count — is built from
  *synthetic* human traces, not real people. `recordings/README.md` says this
  about its own backup recording. `phases.md` confirms: nine old `v1` recordings
  exist (eight mouse, one trackpad) but zero `smooth_v2` recordings exist yet,
  and old traces explicitly do not count as calibration for the current path
  version. **No gate number in this submission says anything about how many real
  people the system would lock out.** That's the single most important caveat.
- **The deployment is live and was verified directly** (8/8 browser end-to-end and
  `1 success, 19 rejected` against its Managed PostgreSQL). `phases.md` still says
  otherwise; that table is stale. Object storage is **not** configured there, so
  consented raw trails are skipped rather than stored.
  (`reviews/product-demo.md` made the same claim and has now been independently
  confirmed against the running site.)
- **The Bedrock path is implemented, not exercised.** `USE_BEDROCK=1` wires in
  `strands.models.BedrockModel`, but no run referenced anywhere in this repo's
  recordings, test output, or READMEs used it. Every documented model call went
  through Akamai.
- **Rate limits and the SSE event broadcaster are in-memory, single-process.**
  `compose.yaml` deliberately pins `--workers 1`; this does not horizontally
  scale and is explicitly called out as a known limit in `README.md`.
  Concurrency correctness for the token/reservation path is still real (an
  atomic, advisory-lock-guarded DB update, not the rate limiter), but the limiter
  itself would need Redis or similar before running more than one process.
- **The proof-of-work fallback is not a CAPTCHA benchmark.** It adds
  computational cost to automation; it does not establish humanity, and
  `phases.md`'s Phase E (comparison against a conventional CAPTCHA baseline) has
  not been run.
- **The scoring bands are provisional and uncalibrated.** `engine/README.md`
  states the five feature bands "start from motor-control literature" and are
  "uncalibrated starting values" with "no claimed human pass rate or tuned-forgery
  success rate" following from synthetic tests. The 0.75 pass threshold has not
  been validated against real users. `reviews/demo-runbook.md` separately notes
  that with the current bands a real human has essentially zero margin — one
  more marginal feature and a real person fails straight to the PoW fallback.
- **The gate rule itself has a known deadlock.** Once a baseline variant blocks
  100% of observed forgeries, no later candidate can ever show fewer forgery
  passes than zero, so a second Blue round in the same session always rejects by
  construction (`engine/gate.py`, confirmed above). This is flagged, unresolved,
  and not something to "fix" live during a demo.
- **Device grouping is coarse and "non-dominant hand" is a crude proxy.** It
  stands in for less-precise movement generally, not a model of disability or
  motor impairment, per `README.md`'s own caveat.

# Handoff — where this was left

Written 2026-10-11, ~05:00 CDT, by Tadiwa's session. He is out of usage; Luc picks this up.
**Submission freeze is 08:00 CDT** and the rules say *"No additional features or bugfixes
are allowed during this period, or you will be disqualified."*

Everything below is pushed to `p1-platform` and merged to `main`. All tests green.

---

## The one thing that matters most

**Collect ~10 real traces. Nobody has done it yet, and only a human can.**

The live site reports `human_traces: 0`. With zero human evidence `engine/gate.py` appends
`"no human evidence"`, **every** gate verdict is `reject`, **no Approve card ever appears**,
and beats 4–5 of the demo — the part that carries the whole idea — cannot happen on stage.

**How:** people on **`https://172-238-40-140.sslip.io/?tester=1`** → tick consent → pick
their real device → follow the dot. Get mouse + trackpad + touch represented. ~30 minutes.

Use **`/?tester=1`** specifically. Three paths write three different places and only this
one feeds the gate:

| Path | Writes | Feeds |
|---|---|---|
| **`/?tester=1`** | `human_test` rows in Postgres | **the gate — the demo** |
| `/research` | signed envelopes in a directory | the ML/shadow model |
| `/dev/recorder` | flat JSON fixtures | `calibrate.py` |

Those last two are mutually incompatible: the website's envelopes would be *rejected* by
`calibrate.py`. Don't mix them up.

Check progress: `curl -s https://172-238-40-140.sslip.io/healthz`

**Demo sequencing trap:** run **Red until it lands a passing forgery** before running Blue.
At zero passing forgeries the gate hits its `0 vs 0` branch and rejects regardless.

---

## Do NOT redeploy

1. **Freeze.** A deploy after 08:00 risks disqualification.
2. **No rollback.** `deploy.sh` builds before replacing, but a bad deploy leaves you
   unhealthy with no automatic way back.
3. **It could void the traces you just collected.** The gate filters evidence by
   `presentation_version`. Live and `main` both read `plain_ring_v1` today, so collected
   traces count — a redeploy that changed that constant would silently exclude all of them.

Cost of not redeploying: live runs an older revision, so `/static/fonts/*` 404 and an
Android judge sees fallback fonts. Polish is explicitly not judged.

---

## Verified against the LIVE site

- Browser end-to-end **8/8**: `node web/tests/browser_e2e.mjs https://172-238-40-140.sslip.io`
- Concurrency vs its Managed PostgreSQL: **`1 success, 19 rejected`**
- `/healthz`: real engine, `smooth_v2`, `plain_ring_v1`, valid TLS

Locally: **268 passed / 3 skipped**, 19 frontend unit tests, `presentation_e2e` 2/2,
`research_e2e` 1/1.

---

## What changed overnight

**AWS track — a defect that would have cost it.** The `worker` service in `compose.yaml`
uses an explicit env allowlist (not `env_file`), and it held only the Akamai variables.
`USE_BEDROCK=1` on the VM was **silently ignored** — Akamai kept serving, no error. Even
with credentials you could not have demonstrated Bedrock. Fixed, plus
`engine/tests/test_bedrock_provider.py` (18 tests, no credentials, no network) proving
`make_model` actually reaches `BedrockModel` and runs a full agent loop on it.
Evidence doc: `reviews/aws-strands-track.md`.

**Runbook — a disqualification risk.** §0 opened by telling the presenter to SSH in and
redeploy on stage. Removed; every on-stage step is now read-only or replays a file.

**Demo script — a false line.** Beat 1 had the presenter say *"a live model scores how
human that motion looked."* Wrong twice: no model runs in checkout, and the score isn't a
humanity probability. Rewritten; beats 4–5 now also name Strands and Akamai.

**The lab's worst overclaim.** "Humans rejected" was a bare count sourced from synthetic
data. Now reads "Recordings from real people" with a `NO REAL PEOPLE YET` badge explaining
there is no human cost to measure until someone records one.

**Consumer copy.** The `stub scorer` badge's visibility check sits *outside* the tester
gate, so an ordinary buyer could have been shown the word "stub". Now "Demo scoring".
Also plain-worded "computational friction" and "browser session".

**Collection tooling.** `scripts/collect.sh` had invalid bash (`${#LAB_KEY:-0}`) and died
instantly, never starting the website half. The progress tally falsely claimed "checkpoint
met" for a dataset `calibrate.py` cannot read. Both fixed.

**UI.** Self-hosted Archivo + IBM Plex Mono — `--font` previously named Inter and *nothing
loaded it*, so Android got Roboto and Windows got Segoe UI. Also warm paper, inked panel
edges, three a11y live-region fixes, and the comet catch zone now matches the drawn ring
(taps on the visible ring did nothing on a phone).

---

## Unfinished — pick up here

**Two agents were stopped mid-task.** Their work is committed in `2904939` and everything
passes, but it is not complete:

1. **Responsive pass** (`style.css`, `design-system.css`) — interrupted part-way through
   its media queries. Targets: 320×568, landscape phone 844×390, the 700–950px tablet
   middle, 1920/2560 wide, dvh + safe-area insets for notched iOS.
2. **Lab readability** (`lab.*`) — the provenance badge and type scale landed; it had not
   reached its CSS pass.
3. **`reviews/device-matrix.md`** — an independent cross-device verification sweep that
   never finished. Worth re-running if there is time *before the freeze*.

**Verify before trusting any of it visually.** The canary for CSS edits is `browser_e2e`
check 2 — logical-px conversion on a CSS-scaled phone canvas. It passes now; keep it that
way.

---

## Known limits — volunteer these before a judge finds them

- All human evidence is **synthetic** until step 1 is done.
- Not a proven detector; scoring bands came from literature and are uncalibrated.
- The Bedrock path is implemented and tested but **never run live**; every real run used
  Akamai's endpoint.
- Object storage isn't configured on the deployment, so consented raw trails are skipped.
- Rate limits are in-memory and single-worker.
- The gate deadlocks at `0 vs 0`, so Blue can only usefully run once per sitting.
- Volunteer the Computer Use cursor bypass rather than letting a judge discover it.

---

## Reference

| Document | Purpose |
|---|---|
| `WAKEUP.md` | the short version of this, written for a groggy reader |
| `SUBMISSION.md` | judge-facing writeup |
| `reviews/demo-runbook.md` | 3-minute script, troubleshooting, stage fallbacks |
| `reviews/judging-gaps.md` | the real criteria, where points are lost, risk questions |
| `reviews/collection-guide.md` | what to say when asking someone for a trace |
| `reviews/aws-strands-track.md` | AWS evidence with file:line citations |
| `reviews/a11y-audit.md` | accessibility findings |
| `recordings/rehearsal-synthetic-humans.jsonl` | complete recorded cycle — stage fallback |

Replaying the recording is **not** a code change, so it stays safe after the freeze:

```bash
python -m web.dev.replay_events https://172-238-40-140.sslip.io \
    --file recordings/rehearsal-synthetic-humans.jsonl --reset
```

Then open `/lab?replay=1`. Say out loud that it is a recording and that its human numbers
are synthetic.

---

## Judging, in one place

Three dimensions, 0–10 each: **value/impact**, **innovative/unique**,
**realness/completeness** — judged *"from the perspective of 'joe average web jockey'"*,
and **code quality is not judged**. No slide decks at any point; the pitch must be the
running prototype. 3 minutes. Be signed into `/lab` before going on stage (the key
persists in `localStorage`).

**The pitch:** *"Bots beat every CAPTCHA eventually. Ours fights back — without locking
real people out."*

1. Phone, follow the dot, ticket reserved — "Three seconds. No puzzles."
2. Run Red — "That's a bot learning to fake a human hand. Watch it win."
3. Run Blue — "Now it writes a tougher test. These numbers are how many real people the
   tougher test would block."
4. Approve — "A person decides. The test just changed."

**When Red wins:** "That's not our demo failing — that's the premise."
**"Better than reCAPTCHA?"** → "No idea — we haven't measured that. Ours is beatable, you
just watched it. The difference is what happens after."

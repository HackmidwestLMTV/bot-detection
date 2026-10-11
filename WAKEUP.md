# Read this first

Written overnight while you slept. Submission freeze is **08:00 CDT** and the rules say
*"No additional features or bugfixes are allowed during this period, or you will be
disqualified."* I stopped committing well before that; see "State" below.

---

## 1. Do this before anything else: collect ~10 real traces (~30 min)

This is the single highest-value thing left and **only a human can do it.**

Right now the live site reports `human_traces: 0`. That means `engine/gate.py` appends
`"no human evidence"`, **every** gate verdict is `reject`, **no Approve card ever appears**,
and beats 4–5 of your demo — the part that carries the whole idea — cannot happen on stage.

**How:** get people on **`https://172-238-40-140.sslip.io/?tester=1`**, tick consent, pick
their real device, follow the dot. Aim for mouse + trackpad + touch all represented.

Collect at `/?tester=1` — **not** `/research`, **not** `/dev/recorder`. Three different
paths write three different places and only this one feeds the gate:

| Path | Writes | Feeds |
|---|---|---|
| **`/?tester=1`** | `human_test` rows in Postgres | **the gate — your demo** |
| `/research` | signed envelopes in a directory | the ML/shadow model |
| `/dev/recorder` | flat JSON fixtures | `calibrate.py` |

Check progress any time:

```bash
curl -s https://172-238-40-140.sslip.io/healthz
```

**Sequencing trap for the demo:** run **Red until it lands a passing forgery** before you
run Blue. If zero forgeries are passing, the gate hits its `0 vs 0` branch and rejects no
matter what.

---

## 2. Do NOT redeploy

Three independent reasons:

1. **Freeze.** A deploy after 08:00 is a disqualification risk. The runbook used to list
   redeploy as on-stage fallback #1 — that has been removed.
2. **No rollback.** `deploy.sh` builds before replacing, but a bad deploy leaves you
   unhealthy with no automatic way back.
3. **It could void your traces.** The gate filters evidence by `presentation_version`.
   Live and `main` both read `plain_ring_v1` today, so traces you collect will count — but
   a redeploy that changed that constant would silently exclude every one of them.

The cost of not redeploying: the live site runs an older revision, so `/static/fonts/*`
404 and a judge on Android sees fallback fonts instead of Archivo. Polish is explicitly
not judged. Verified-working beats prettier-but-unverified.

---

## 3. Verified against the LIVE site

- Browser end-to-end: **8/8** (`node web/tests/browser_e2e.mjs https://172-238-40-140.sslip.io`)
- Concurrency against its Managed PostgreSQL: **`1 success, 19 rejected`**
- `/healthz`: real engine, `smooth_v2`, `plain_ring_v1`, valid TLS

Locally: **268 passed, 3 skipped**; 19 frontend unit tests.

---

## 4. The pitch, in plain words

> **"Bots beat every CAPTCHA eventually. Ours fights back — without locking real people out."**

Four beats, each a thing they watch happen:

1. **Phone, follow the dot, ticket reserved.** "Three seconds. No puzzles."
2. **Run Red.** "That's a bot learning to fake a human hand. Watch it win."
3. **Run Blue.** "Now it writes a tougher test. These numbers are how many real people the
   tougher test would block."
4. **Approve.** "A person decides. The test just changed. The bot's trick stopped working."

Rules worth knowing: **no slide decks at all** — the pitch must be the running prototype.
3 minutes. Be signed in before you start (the `/lab` key persists in `localStorage`, so
enter it beforehand). Judging is 0–10 on *value/impact*, *innovative/unique*, and
*realness/completeness*, explicitly from a *"joe average web jockey"* perspective —
**code quality is not judged**, so don't lead with the test suite.

### Lines to have ready

**When Red wins:** "That's not our demo failing — that's the premise. Any fixed check gets
solved. The question is what happens next."

**"Is it better than reCAPTCHA?"** → "No idea — we haven't measured that. Ours is beatable,
you just watched it. The difference is what happens after it's beaten."

**"Run Blue again?"** → "It rejects by design. Once nothing's getting through there's
nothing to improve against; we'd want fresh attack evidence before tightening again."

Saying "we haven't measured that" costs nothing and buys credibility. Everyone else in the
room will claim their thing is better.

---

## 5. Honest limits — say these before a judge finds them

- **All human evidence is synthetic** until you do step 1. Every "humans rejected" number
  so far is a claim about nobody.
- Not a proven detector. The scoring bands came from literature and are uncalibrated.
- The Bedrock path is implemented and tested but **never run live** — every real run used
  Akamai's endpoint.
- Object storage isn't configured on the deployment, so consented raw trails are skipped.
- Rate limits are in-memory and single-worker.
- Volunteer the Computer Use cursor bypass rather than letting a judge discover it.

---

## 6. Reference

| Document | What it's for |
|---|---|
| `SUBMISSION.md` | judge-facing writeup |
| `reviews/demo-runbook.md` | the 3-minute script, troubleshooting, stage fallbacks |
| `reviews/judging-gaps.md` | the real criteria and where you lose points |
| `reviews/collection-guide.md` | what to say when asking someone for a trace |
| `reviews/aws-strands-track.md` | AWS evidence, with file:line citations |
| `recordings/rehearsal-synthetic-humans.jsonl` | complete recorded cycle — the stage fallback |

Replaying the recording is **not** a code change, so it stays safe after the freeze:

```bash
python -m web.dev.replay_events https://172-238-40-140.sslip.io --file recordings/rehearsal-synthetic-humans.jsonl --reset
```

Then open `/lab?replay=1`. Say out loud that it's a recording and that its human numbers
are synthetic.

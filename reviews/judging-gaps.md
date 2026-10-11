# Judging gap analysis — Follow It vs. Hack Midwest's real criteria

Written 2026-10-11 ~04:00 CDT. **Submission closes 08:00 CDT today; demos begin 09:00.**
Everything below is ranked by points-gained-per-hour against the *published* criteria,
not by completeness. Items are tagged with who they're blocked on.

Ownership note: this file is the only thing this review created or changed. Every
other fix below is a recommendation to the owner of that file.

---

## 0. The criteria, from the source

All of the following is quoted from **<https://hackmidwest.com/>** (the event's own
rules/judging/schedule sections). Treat the quotes as the authority, not my paraphrase.

**Judging — three dimensions, 0–10 per judge:**

> "All judging will occur from the perspective of 'joe average web jockey'. That is,
> code quality will not be judged. Your application will be judged based on a few
> criteria: 1) value / impact / usefulness, 2) innovative / unique (are excited about
> idea), 3) realness / completeness (is it actually built / is it an actual MVP).
> Each judge will be able to rate each application on a scale of zero to ten (0-10)."

**Format rules the team may not have priced in — see §1:**

> "Your pitch must be done by showing the prototype you built during the competition.
> No slide decks, power points or anything else can be used at any time."

> "You've got 3 minutes to show us what you built and what it does."
> … "Don't waste time on logins - be signed into your app already."
> … "Tell us if your app involves specific sponsor challenge(s) or sponsor APIs\Platforms."

> "No additional features or bugfixes are allowed during this period, or you will be
> disqualified." (i.e. between the 08:00 submission and judging)

> "All participants must be present - no remote developers or teams are allowed."
> … teams of one to five; "Each team may only submit ONE single project."

**Schedule:** 08:00 CDT Sun — hackathon ends, project submissions due. 09:00 — app demos
begin. 11:30 — awards.

**Sponsor tracks ($2,500 cash each), from the same page:**

| Track | Requirement as published | Stated judging notes |
|---|---|---|
| **AWS — Strands Agents SDK** | "develop an application that leverages Strands Agents SDK to create agents that can solve complex problems, automate workflows, or enhance user experiences" | "Does the project integrate Strands Agents SDK?" / "Did you build something unique and innovative using Strands Agents creatively?" |
| **Akamai Cloud AI** | "build a working AI-powered application on Akamai Cloud that solves a real-world problem and goes beyond a basic chatbot"; $300 credits + hosted AI inference provided | 1) Impact & Usefulness 2) Powered by Akamai (Akamai Cloud resources and/or AI inference) 3) Technical Execution (functional, stable code) 4) Creativity & Innovation |
| **DevRev** | "Build a reusable skill or MCP connector in DevRev Computer that solves a real enterprise workflow using the Enterprise-Bench dataset"; must "demonstrate another authorized teammate can use it to produce useful, evidence-backed results"; separate registration form required | — |

### What I could NOT find

Said plainly, rather than padded with generic advice:

- **No Devpost page for Hack Midwest 2026 exists that I could locate.** Searches
  surfaced Devpost pages for MHacks, HackISU, the Midwest Blockathon and others, but
  not Hack Midwest. Hack Midwest appears to run its own submission process.
- **The submission mechanism itself is not published** on hackmidwest.com — no stated
  form, required fields, repo requirement, or URL requirement. Only the 08:00 deadline.
- **No demo-video requirement is published anywhere, and no rubric weighting.** Because
  the pitch is explicitly a live prototype demo, I'd expect no video — but I could not
  confirm a negative. **Someone on the team should confirm the actual submission form's
  required fields with an organizer directly.** If it turns out a video *is* required,
  that is a hard blocker and outranks every item in this document.
- Whether a project URL, repo link, or written description is scored at all.

This is **not** a fallback to generic Devpost dimensions — the real criteria above were
retrieved from the event's own site. Only the submission *mechanics* are unknown.

---

## 1. The format rules that matter more than any code change

The task asked specifically for a format rule the team may be unaware of. There are
three, and the third is the one with teeth.

1. **No slide decks, at any time.** The repo has no deck, so there is nothing to
   delete — but the consequence is structural: **the `/lab` dashboard *is* the slide.**
   The governance concept cannot be explained on a diagram; it has to be legible on
   screen in seconds. That makes `reviews/a11y-audit.md` finding #4 ("`/lab` text is
   small for across-the-room viewing", filed as nice-to-have) a *pitch* issue, not an
   accessibility nicety. Judges read those numbers from across a room or not at all.

2. **"Don't waste time on logins — be signed into your app already."** `/lab` is behind
   a lab-key prompt. The key persists in `localStorage` under `followit_lab_key`
   (`web/static/lab.js:143`), so **enter it on the venue machine before you go on
   stage** and confirm the panels render. Typing a 32-character secret into a prompt on
   a projector costs ~20 of your 180 seconds and exposes the key on the venue screen.
   The runbook's checklist tells you to retrieve `LAB_KEY` privately; it does not tell
   you to pre-authenticate before stage. Do both.

3. **Hard freeze at 08:00 CDT: "No additional features or bugfixes are allowed during
   this period, or you will be disqualified."** This is the rule to brief the whole team
   on right now. It means:
   - Every code change in this document must land **before 08:00**, not before 09:00.
   - The instinct to fix something between submission and demo — including the font
     redeploy in item 6 — is a **disqualification risk**, not a polish opportunity.
   - `reviews/demo-runbook.md` §0 ("IF IT IS BROKEN ON STAGE, DO THIS") currently tells
     you to **redeploy** on stage as fallback #1. Under this rule, redeploying a
     *different build* after submission is at best ambiguous and at worst disqualifying.
     The safe stage fallback is the recorded replay (§0 step 2) or the ticket page only
     (§0 step 3) — **not** `bash deploy.sh`. Someone should rewrite §0's ordering.

4. Minor but worth confirming: **all participants must be present, no remote members.**
   `phases.md` describes Luc testing from his own PC over a phone hotspot and a P1/P2
   split. If anyone is contributing remotely at demo time, check that against this rule.

---

## 2. Criterion-by-criterion: score today, highest-leverage change

Scores are my estimate of what a "joe average web jockey" judge rates *today*, given the
live deployment at <https://172-238-40-140.sslip.io> as it actually stands.

| Criterion | Likely score today | Highest-leverage change | Effort | Blocked on |
|---|---|---|---|---|
| **1. Value / impact / usefulness** | **6/10** — the problem ("CAPTCHAs annoy humans and bots solve them anyway") is instantly legible to any judge, but the pitch as written in `SUBMISSION.md` leads with the governance loop, which is an abstraction. The honest "this is not a proven detector" caveat, if delivered as the headline, reads as "it doesn't work." | Reorder the 3 minutes: beat 1 is the visceral user win (follow a dot for 3 seconds → ticket reserved, no squares, works on a phone). Governance arrives second, as *"and here's who that rule locks out,"* with a non-zero number on screen. Keep the caveat for Q&A, not the opener. | ~15 min, doc only | Whoever owns `reviews/demo-runbook.md` §3 |
| **2. Innovative / unique** | **7/10** — the Red-attacks / Blue-defends / fixed-arithmetic-gate / human-approval loop is genuinely distinctive in a field of LLM wrappers. The risk is purely that a judge doesn't *get* it inside 180 seconds. | One sentence that lands the gate: *"the gate is arithmetic, not AI — it can't be argued with or tuned to look good."* That line already exists in `SUBMISSION.md` and is the best sentence in the repo; it is not in the demo script. Put it in. Second: the gate numbers must be **non-zero** on screen (see criterion 3). | ~5 min, doc only | Same |
| **3. Realness / completeness** | **5/10 as the demo currently runs live** — and this is the single biggest gap in the project. The site is genuinely live with real HTTPS, the real engine, managed Postgres, real agents, and 8/8 browser E2E against it. But **the scripted demo's climax cannot happen on the live deployment.** See §3 item 1. If fixed: **9/10**. | Collect real human evidence on the live site (§3 item 1). This is the one change that converts a demo that dies at beat 5 into one that completes. | ~30–45 min, no code | The team's own hands and phones. Nobody else. |
| **AWS — Strands Agents** | **8/10** — strong and honest. `strands-agents==1.59.0` is the actual framework; Red and Blue are real `strands.Agent` instances with `@tool` tools, `strands.hooks` lifecycle events, and typed `RoundReport` structured output. Observed live: Red 3 model calls / 2 synthetic attempts, Blue 4 calls / 1 candidate. An adversarial agent *pair* with a human-approval interrupt answers "creatively?" well. | Two things. (a) Say the words "Strands Agents SDK" out loud on stage — the rules explicitly ask you to name the sponsor tech. The current script never does. (b) `SUBMISSION.md` points at `reviews/aws-strands-track.md`, **which does not exist in this checkout** — a sponsor judge following that pointer finds nothing. Either write it or drop the reference. | ~10 min | Owner of `SUBMISSION.md` |
| **Akamai Cloud AI** | **7/10, artificially depressed** — this should be the strongest track. Hosted inference at `ws.akamai-workshops.com` drives both agents; Linode compute + Managed PostgreSQL 18 are live and verified. It is emphatically "beyond a basic chatbot." **But `SUBMISSION.md` currently tells the Akamai judge that "nothing from that stack is confirmed deployed."** That was true when written; it is false now. | Correct the Akamai section to state the verified live facts: `/healthz` on the live host returns `{"ok":true,"engine":"real","path_version":"smooth_v2"}` over valid TLS, backed by the managed PostgreSQL 18 cluster, and the concurrency test printed `1 success, 19 rejected` against that managed database. This is a ~10-minute doc edit worth a $2,500 track. | ~10 min, doc only | Owner of `SUBMISSION.md` |
| **DevRev** | **0/10** — zero integration, confirmed by search. The requirement is a reusable skill or MCP connector *inside DevRev Computer*, using the *Enterprise-Bench dataset*, plus a separate registration form, plus a demonstration that another authorized teammate can reuse it. | **Do not attempt this, and do not mention DevRev on stage.** With under four hours to a freeze, a credible DevRev entry is not reachable; a half-built one would read as padding and costs you time against criteria you can actually win. `SUBMISSION.md`'s current treatment ("Not attempted… unstarted work, not a partially-built integration") is exactly right — leave it. | 0 | Nobody; accept the loss |

---

## 3. Ranked do-next list — shortest payback first

**All code and data work must land before 08:00 CDT.** Times are wall-clock estimates.

### 1. Collect real human traces on the live site — ~30–45 min, no code, highest payback by far

This is the top item on every axis simultaneously. It is also the only item that is
blocked on nobody.

**Why it's urgent, not just nice:** `engine/gate.py` opens with

```python
if not humans:
    reasons.append("no human evidence")
```

and any non-empty `reasons` makes the verdict `reject`. The live site reports
`"human_traces":{"total":0}`. **Therefore, on the live deployment right now, the gate
*always* rejects, Blue's candidate can never reach approval, no Approve card appears, and
beats 5 and 6 of the three-minute script are physically impossible.** This is already
documented as having happened: `reviews/product-demo.md` records the live Blue run being
"rejected… for missing human evidence," with "no approval or activation." If the team
runs the scripted demo at 09:00 as written, it dies at beat 5 in front of the judges.

**Why it's cheap — verified this session, no code change needed:**
- `human_test` attempts require **no** research enrollment. `web/routes_public.py` admits
  them on the ordinary attempt path with only a valid `device` and matching
  `presentation_version`; the enrollment check (`research.validate_attempt`) governs the
  separate raw-recording path, not whether the attempt is stored.
- Object Storage being unconfigured does **not** break it. `web/storage.py`'s
  `put_trail` returns `None` and logs a warning when `S3_*` is unset. The attempt still
  succeeds and the feature values still land in Postgres.
- Feature values in Postgres are **all the gate reads** — `gate()` "uses stored feature
  values only, never raw trails" (`contracts/CONTRACT.md`). So no storage, no problem.

**Do this:** open `https://172-238-40-140.sslip.io/qr/tester` (or `/?tester=1`), have
every person present do several attempts with **explicit consent and the correct device
selected**, covering **mouse, trackpad, and touch** — the gate groups per device and a
missing group is simply untested. Aim for ten or more total with all three devices
represented; `phases.md` Phase C calls that "an initial checkpoint, not proof of general
accuracy," which is the right thing to say on stage. Confirm with `/healthz` that
`human_traces.total` is no longer 0. Only genuine human interaction — `phases.md` is
explicit that automation-created trails belong in synthetic tests, never calibration.

**What it buys:** (a) the demo's climax becomes possible; (b) the project's central
claim — "here is how many real people this rule would lock out" — becomes **true for the
first time**; (c) it deletes the most dangerous overclaim in the repo (§5 item 1).

Note the honest ceiling: ten traces from the people in the room is a pilot, not
calibration. It makes the sentence *"these are real people, measured an hour ago"* true.
It does not make *"we know our false-rejection rate"* true. Say the first, not the second.

### 2. Fix the Akamai section of `SUBMISSION.md` — ~10 min, doc only

See the table above. The submission currently under-sells a live, verified Linode +
Managed PostgreSQL 18 + hosted-inference deployment as unconfirmed. That is a self-
inflicted wound on the track this project is strongest in. Same edit should drop or
satisfy the dangling `reviews/aws-strands-track.md` reference.

### 3. Rewrite the three-minute script against the real rules — ~15 min, doc only

Concretely, against `reviews/demo-runbook.md` §3:
- **Pre-enter the lab key before stage** (rule: don't waste time on logins).
- **Name "Strands Agents SDK" and "Akamai Cloud" out loud** (rule: tell us if your app
  involves sponsor challenges or platforms). The current script names neither.
- **Fix beat 1's wording** — it currently claims a live model scores the motion. It
  doesn't. See §5 item 2.
- **Run Red until it lands at least one *passing* forgery before you click Blue.**
  `engine/gate.py` deadlocks when the baseline already blocks everything:
  `if passed["baseline"] == passed["candidate"] == 0` appends
  *"baseline already blocks all stored forgeries."* If Red's attempts all fail under
  `v1`, Blue is guaranteed to reject no matter what it proposes. The observed live run
  got 1 of 2 passing — that was luck, not design. Check the event stream for a pass
  before advancing.
- **Reorder §0's stage-emergency list** so "redeploy" is not step 1, per §1 item 3.
- Decide whether you can do this on **one** screen. Phone-plus-venue-screen with a
  handoff is a lot of motion inside 180 seconds.

### 4. Re-record the backup run from a real cycle — ~20 min, after item 1

Once real human traces exist, run one clean Red → Blue → Approve cycle on the live site,
then `/v1/lab/reset`, and re-record `backup_run.jsonl`. Today the complete-cycle
fallback is `recordings/rehearsal-synthetic-humans.jsonl`, whose own README says
**"Not demo-safe for the gate numbers"** because its 14 human traces are synthetic, and
asks for exactly this re-record. This converts the emergency fallback from "a recording
we have to apologise for" into "the run we did an hour ago." Do it before 08:00.

### 5. Fix the spoken overclaim in the runbook — ~5 min, doc only

§5 item 2 below. Five minutes, removes the most likely way to get caught contradicting
your own documentation on stage.

### 6. Font/accent redeploy — ~15 min, code + deploy, and I recommend **not** doing it

The live deployment is an older revision than `main`. Verified this session:
`/static/design-system.css` on the live host declares
`--font: Inter, ui-sans-serif, -apple-system, …` with **no `@font-face` rule at all**,
and `/static/fonts/archivo-var-latin.woff2`, `plexmono-400-latin.woff2` and
`inter-var-latin.woff2` all return **404**. Nothing loads Inter. An Android judge sees
Roboto; a Mac judge sees SF Pro. Live accent is `#c84c08`; `main` is `#b63d05` with
self-hosted Archivo + IBM Plex Mono.

Why I'd skip it anyway, in priority order:
- **Code quality and polish are explicitly not judged** ("joe average web jockey… code
  quality will not be judged"). A font fallback is close to invisible on these three
  criteria.
- **The 8/8 browser E2E was run against the *current live* revision.** Redeploying puts
  bits on stage that have *not* been verified in production, four hours before demo.
- `README.md` states `deploy.sh` "does not provide automatic rollback," and a failure
  after container replacement "can leave the new deployment unhealthy."
- Under the 08:00 freeze, if it breaks you cannot fix it.

If someone insists: do it before 07:00 and re-run `browser_e2e.mjs` against the new
revision, or don't do it at all. **Verified-ugly beats unverified-pretty.**

### Honestly cannot be done in time

- **DevRev.** Needs a skill/MCP connector inside DevRev Computer, the Enterprise-Bench
  dataset, a registration form, and a teammate-reuse demonstration. Not reachable. Skip.
- **Real calibration** of the 0.75 threshold and the five feature bands.
  `reviews/product-demo.md` puts the pilot at "roughly 30–50 participants… repeated
  sessions." Item 1's ten traces are a pilot sample, not calibration.
- **The gate deadlock** (`passed["candidate"] >= passed["baseline"]`). It is flagged and
  unresolved. Do **not** touch `engine/gate.py` today: it's load-bearing for the demo,
  and any change after 08:00 is a disqualification risk. Demo one Blue round per reset
  and say the edge case out loud if asked.
- **Phase E** (comparison against a conventional CAPTCHA baseline). Never run. Which
  means "better than a CAPTCHA" is not a claim you own.
- **Object Storage.** Not enabled, no key, awaiting a billing decision. Consequence for
  the pitch: **do not say "72-hour retention" on stage** (§5 item 4).
- **Any ML model** (Random Forest / CNN / LSTM). `reviews/product-demo.md` is clear this
  is a *proposal*, not a trained artifact. Don't imply otherwise.

---

## 4. RISK — the sharp questions, and the honest answer to each

Rehearse these. Several have good answers that the team is currently not giving.

**Q1. "How many real people has this locked out?"**
Honest: **zero measurements.** Until item 1 is done there were no real `smooth_v2`
traces at all, and every gate number anywhere in this repo is computed from 14 synthetic
traces. The mechanism is real; the measurement is not. After item 1: *"N real traces
across mouse, trackpad and touch, collected an hour ago — here's the per-device number,
and it's a pilot, not a calibration."*

**Q2. "Is this better than reCAPTCHA, or Akamai Bot Manager?"**
Honest: **unknown, and not claimed.** `reviews/product-demo.md` says so in writing:
"We have not established superiority over either product." Phase E never ran. The
defensible claim is about *visibility into human cost*, not detection accuracy.

**Q3. "Couldn't a bot just move the mouse in a wave and pass?"**
Honest: **yes, and it already did.** An operator-approved Computer Use test passed
ordinary checkout on its second cursor attempt using eight generic wavy drag calls — the
page displayed "You're through" and enabled reservation, with no fallback and no
telemetry injection (`reviews/product-demo.md`; evidence under
`release-artifacts/cursor-bypass-*`). **Volunteer this.** It is the single strongest
argument for why the project is a governance mechanism rather than a detector, and if a
judge discovers it instead of being told, it reads as concealment. Said first, it reads
as unusual rigour.

**Q4. "The path is seeded and your JavaScript is public — can't an attacker read the path
and trace it?"**
Honest: yes. `reviews/product-demo.md`: the new display "does not hide the deterministic
path from code running in the browser." No mitigation is built. Listed as pilot work.

**Q5. "You call this a governance mechanism rather than a detector. So what does the
governance actually prevent?" — the pressure test**

This is the pitch's weakest joint, and it deserves a straight answer rather than a
reframe. What it genuinely prevents, and this part is real and server-enforced: **a
scoring-rule change cannot ship without a measured human-cost number and a recorded
human approval.** `POST /v1/variants/{id}/activate` returns `403` without an unconsumed
`approved` row for that exact variant, and `403` again if the gate re-evaluated at
activation time no longer matches what was approved — in the HTTP handler itself
(`web/routes_lab.py`), not in the agent's judgment or the dashboard. That is a real
control and it is unusual to find built at a hackathon.

What it does **not** do, and the team should concede all four before being pushed:
1. It does not make the underlying detector correct. A well-governed bad detector is
   still a bad detector — see Q3.
2. The gate checks exactly two arithmetic conditions: no device group gets worse, and
   strictly fewer stored forgeries pass. **That is not a fairness proof.** A rule can
   satisfy both and still be bad for people not represented in the evidence.
3. Its device groups are coarse (mouse / trackpad / touch), and the W3C Pointer Events
   spec — cited in the team's own review — notes trackpads and external mice commonly
   feed the same pointer type, so the device label is a self-report the system cannot
   verify.
4. Until item 1, the "human cost" it measured was **the cost to imaginary people.**

The honest one-liner: *"it doesn't prove the detector is right. It makes it impossible to
change the rule without someone seeing the cost first and signing for it."* That claim
survives scrutiny. "AI defends against AI" does not.

**Q6. "The gate is only as good as its evidence. Who picks the evidence?"**
Honest: the operator does, and the gate reads whatever `human_test` rows happen to exist.
There is **no held-out audit set** in the live system; `reviews/product-demo.md`
recommends one ("a frequently reused gate sample must not be presented as an unseen test
set") as future work. A judge who pulls this thread is right, and the team's own document
agrees with them.

**Q7. "What stops Blue from proposing a rule that passes the gate but is terrible?"**
Honest: only those two arithmetic conditions and the human. There *are* real constraints
— Blue cannot change the path version, and cannot submit executable code, only bands.
But on a small evidence sample, a rule that trivially satisfies both conditions is easy
to find. The human approval is doing more work here than the arithmetic.

**Q8. "Is the AI actually doing anything, or is this an LLM wrapper?"**
Strong answer, if stated precisely: Red and Blue are real Strands agents making real
model calls against Akamai hosted inference — observed live, Red made 3 calls across 2
synthetic attempts and Blue made 4 calls producing 1 candidate; the recorded cycle shows
Red driving `jitter_px` 32.2 → 9.9 → 6.7 → 5.19 across 5 attempts. **But the checkout
scorer contains no model at all** — it is deterministic feature extraction against
fixed bands. Be precise about which half is AI. The current script's opening line is not
(§5 item 2), and a judge who catches that contradiction discounts everything after it.

**Q9. "You said Managed Postgres — is it really managed, or SQLite in a container?"**
Good answer, fully verifiable: the live `/healthz` is database-backed and returns
`engine: real`, and the concurrency test printed `1 success, 19 rejected` against that
live managed PostgreSQL 18 cluster. Token single-use is an atomic
`UPDATE … WHERE consumed_at IS NULL RETURNING` plus a per-session advisory lock.

**Q10. "Was all of this built during the 24 hours?"**
Flagging, not answering: the rules forbid production assets — "application code, and
user stories / test cases" — created before the competition start. A 250-test suite, a
frozen inter-person contract, and a five-phase plan are a lot of artefact. I cannot
verify provenance from this checkout; the team should be ready with their git history.
If anything predates the start, know that before a judge asks.

---

## 5. Overclaim flags

Ordered by how much damage each does if a judge catches it.

**1. The most dangerous overclaim in the repo: the `/lab` UI's "Humans rejected" label.**
`web/static/lab.html` and `web/static/lab.js` render *"Humans rejected"* and
*"human rejections"* as bare counts, with **no provenance label anywhere** — no
"synthetic," no sample size caveat, nothing. The entire pitch rests on that number
meaning real people, and **it has never once meant real people.** Every value it has ever
displayed came from 14 synthetic traces. Worse, the honest framing exists only in
`recordings/README.md` and in whatever someone remembers to say aloud under a 180-second
clock — the artefact on the projector asserts the strong version by itself. The gate's
own reason strings compound it, reading like *"rejects 4 of 4 trackpad users"* — a
sentence about people, generated from data about nobody.
Two acceptable fixes: do item 1 so the label becomes true, or put the word *synthetic*
next to the number. The first is better and barely slower.

**2. The most dangerous *spoken* overclaim: `reviews/demo-runbook.md` §3, beat 1.**
The script has the presenter say, as the **first sentence of the pitch**:

> "follow a comet with your finger for three seconds, and **a live model scores how
> human that motion looked**"

Both halves are false. There is no model in checkout — `reviews/product-demo.md` states
"checkout uses deterministic scoring without model calls." And the score is not a
humanity estimate — the same document says "This heuristic score is not a probability of
humanity." So the opening line of the demo contradicts the team's own review documents,
and it invites the worst possible follow-up ("which model?"). Five-minute fix. Suggested
replacement: *"…and the server measures five properties of that motion against fixed
bands — no model, no image, nothing sent anywhere."* That is both true and more
impressive.

**3. An *under*-claim that costs real money: `SUBMISSION.md`'s Akamai section.**
It says in bold that "nothing from that stack is confirmed deployed" and warns the reader
not to read it as claiming a live deployment. The site **is** live on Linode with valid
TLS, the real engine, and a managed PostgreSQL 18 cluster behind it. Being
scrupulously honest about a stale fact is still being wrong, and here it is wrong in the
direction that loses a $2,500 track.

**4. `README.md` presents Object Storage as operational.** It lists Object Storage
holding "raw movement traces, kept only from consenting testers and only for 72 hours,"
shows it in the architecture diagram without caveat, and repeats the 72-hour deletion
under "Known limits" as established behaviour. `reviews/product-demo.md` is explicit:
"Object Storage is not enabled… no storage key exists… Do not present uploads or
72-hour deletion as verified operational behavior yet." **Do not say "72-hour retention"
on stage** — a privacy claim that turns out to be unimplemented is the worst category of
thing to be caught on.

**5. `README.md`'s lead and architecture diagram** carry none of the deployment caveats
`SUBMISSION.md` carries. If a judge reads the README instead of the submission — likely,
since it's the repo's front door — they get the confident version.

**6. `SUBMISSION.md` cites `reviews/aws-strands-track.md`, which does not exist** in this
checkout. It is cited as "the fuller, independently-written verification of this track"
for the AWS prize. A sponsor judge who follows that pointer finds nothing, which is worse
than never having promised it.

**7. Stale counts across submission-adjacent docs.** `reviews/product-demo.md` claims
"235 automated checks… 15 frontend checks, and ten Chrome browser checks"; the verified
figures are 250 passed / 3 skipped Python, 19 frontend, and 11 browser E2E.
`SUBMISSION.md` already flags the discrepancy and explains it, so this is minor — but two
submission documents disagreeing on test counts is an avoidable credibility nick, and the
direction is unflattering (the real numbers are *better*).

---

## 6. The compressed version

If the team reads one paragraph: **the demo as scripted cannot complete on the live site,
because the gate always rejects with "no human evidence" while `human_traces` is 0.**
Spend the next 45 minutes having everyone present follow the comet at
`/qr/tester` on mouse, trackpad and phone with consent on — no code, no deploy, nothing
blocked on anyone else. That single action makes the climax possible, makes the project's
central claim true for the first time, and deletes the worst overclaim in the repo. Then
spend 25 minutes on documents: correct the Akamai section, name Strands and Akamai in the
script, and fix the "a live model scores" opening line. Leave `engine/gate.py` and the
deployed revision alone. Everything must land before **08:00 CDT** — after that,
"no additional features or bugfixes… or you will be disqualified."

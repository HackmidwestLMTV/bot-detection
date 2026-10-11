# Follow It: CAPTCHA replacement demo

## Pitch

Follow It replaces image puzzles with a three-second movement check. AI agents
test simulated attacks and propose defense updates; measured human impact and
operator approval control what goes live.

For ticketing teams, the demonstration connects verification to the action being
protected: a short-lived, single-use pass authorizes one demo reservation. The
visitor follows a ball; the operator sees the evidence behind proposed updates.
No payment is collected.

Our proposed differentiator is the combination of movement verification,
transparent attack testing, and reviewed updates. Removing image puzzles alone
is not unique: [reCAPTCHA v3](https://developers.google.com/recaptcha/docs/v3)
already scores interactions without an interactive puzzle. Akamai's
[Bot Manager](https://www.akamai.com/products/bot-manager) also offers behavioral
analysis. We have not established superiority over either product.

## What actually runs

- Checkout: server issues a seeded challenge and snapshots its scoring policy.
  The browser renders only the current ball and ring, records pointer movement,
  and submits samples. The server extracts deterministic movement features and
  evaluates the issued policy. This heuristic score is not a probability of humanity.
- A successful attempt issues a pass valid for 120 seconds, bound to the session
  and `reserve_ticket` action. The reservation endpoint consumes it atomically.
- Skip, reduced motion, or unsuccessful scoring uses a keyboard-accessible browser
  proof-of-work check. Automation can solve it too; it adds computational cost.
- Red and Blue are separate Strands agent roles using Akamai's configured
  `hackathon-chat` endpoint. The underlying model is not confirmed. No image,
  embedding, or per-visitor LLM call is needed. Blue receives aggregate human
  statistics; raw human recordings do not enter model prompts.
- Red tests synthetic trails. Blue proposes scoring bands. A fixed server gate
  requires fewer stored forgery passes without increased human rejections within
  represented device groups. A person reviews the result before activation.
  Timeout, denial, missing evidence, or changed evidence cannot activate a policy.
- Gate evidence must match both `smooth_v2` motion and `plain_ring_v1` display.
  Historical recordings remain legacy evidence and do not count for this display.
  Legacy consented residuals can still generate attacks; those are labeled Red,
  never converted into fresh human recordings.

## Two-minute demonstration

1. Open `/` or scan `/qr`. Say: "This is a ticket checkout using Follow It."
   Touch or point at the ball and follow it for three seconds. Reserve a demo
   ticket after receiving a pass. If scoring fails, use the browser check and
   explain its added computational cost. Never imply a fallback pass is a human verdict.
2. Open `/lab`, authenticate privately, and show current device counts. Devices
   without recordings are untested; small samples do not establish accessibility.
3. Run Red. Show observed synthetic attempts and how many the active policy accepts.
   Say: "The agent is probing our own heuristic with simulated attacks."
4. Run Blue. Compare its proposal against the same recorded human and attack
   sample. Explain the two gate requirements. If no proposal improves the sample,
   show the rejection; do not invent an improvement or force activation.
5. If a reviewable proposal exists, inspect and approve it. Show the activation
   event and new active rule. An already issued challenge retains its original rule.
6. Close: "We can show what this update catches and whom it affects in our recorded
   sample before deploying it. The next step is a broader customer pilot."

## Calibration and backup

Share `/qr/tester` separately with people helping collect fresh mouse, trackpad,
and real phone-touch attempts. Tester mode requires consent and device selection.
Only actual human interaction belongs in calibration data. Consent-controlled
cloud recordings are deleted by the hourly 72-hour janitor; local recorder files
are local development data and require manual removal.

Audit local recordings with `python -m engine.calibrate --path-version smooth_v2`.
The default display is `plain_ring_v1`; `--presentation-version legacy` is only for
historical inspection. Empty current evidence correctly prevents approval.

After a real run, save events with:

```powershell
python -m web.dev.record_events https://YOUR_DOMAIN backup_run.jsonl
```

The existing replay tool resets lab state; use it only on a dedicated demo
deployment. Replay at `/lab?replay=1` and explicitly call it a recorded run.
Never silently mix replay counts with live verification results. The recorded
backup (kept outside Git) at `release-artifacts/recorded-live-red-blue-20261011.jsonl` contains 21 events
exported from the observed live Red and Blue runs for this deployment. Its adjacent
label explains that Blue was rejected, no policy activated, and no fresh human
recordings were available. It is a recorded attack/no-change demonstration;
the complete human-impact/approval demonstration remains pending.

## Akamai architecture and verification

| Service | Purpose | Required evidence before saying it is operational |
| --- | --- | --- |
| Linode compute | FastAPI, Caddy HTTPS, separate agent worker | Reviewed release running; external HTTPS checkout and authenticated worker readiness pass |
| Managed PostgreSQL | Challenges, attempts/features, tokens, variants, approvals | Deployed app connects to the managed cluster; schema and database-backed health pass |
| Object Storage | Private, consented tester recordings | Operator confirms one consented upload and retention cleanup using dedicated test objects |
| Hosted inference | Red/Blue tool calls through `hackathon-chat` | Bounded live smoke test plus a successful observed lab round |

The updated checkout passed 235 automated checks against disposable PostgreSQL,
15 frontend checks, and ten Chrome browser checks. Browser touch emulation verifies
input handling; actual mouse, trackpad, and phone comfort trials are still needed.
The current-presentation calibration audit found zero matching human recordings.

Verified on 2026-10-11: the reviewed working-tree bundle is running on
`followit-vm` at [the live checkout](https://172-238-40-140.sslip.io), with valid
HTTPS, a healthy real-engine app, Caddy, and the agent worker. The app connected to
the managed `followit-db` PostgreSQL 18.6 cluster. External checks confirmed
`smooth_v2`, `plain_ring_v1`, ordinary `/qr`, and separate `/qr/tester`. A browser
check reserved one demo ticket; wrong-session and reused-pass requests were rejected.

The deployed Akamai compatibility smoke passed five checks in 12 model calls
without sending human samples or activating scoring changes. A live Red round
made three model calls and tested two synthetic attempts: one failed and one
passed policy `v1`. This demonstrates an observed weakness of the heuristic,
not successful attack prevention. Current human evidence is still zero.

Live Blue made four model calls and proposed one candidate. The fixed gate
rejected it for missing human evidence and unchanged forgery passes (one of two
for both baseline and candidate). No approval or activation occurred; policy
`v1` remained active. Both agent runs have a labeled recorded event backup.

A subsequent operator-approved Computer Use test passed ordinary checkout on
its second cursor attempt. Eight browser drag calls traced a generic wavy
pattern; the page displayed "You're through" and enabled reservation. No fallback,
telemetry injection, or policy change was used. This is a demonstrated automated
UI pass, not merely an API simulation. The observation and screenshot are saved
under `release-artifacts/cursor-bypass-*`; it is not human calibration evidence.

Object Storage is not enabled. The private bucket draft awaits the operator's
decision about its charge; no storage key exists. Tester features can be retained
in PostgreSQL, but raw cloud recordings are unavailable until storage is configured.
Do not present uploads or 72-hour deletion as verified operational behavior yet.

The demo uses one app worker and one agent worker; in-memory rate limits and SSE
are not a multi-instance architecture. Bot Manager/EdgeWorkers are future pilot
options. Akamai's documented
[BotScore interface](https://techdocs.akamai.com/edgeworkers/docs/botscore-object)
can supply trusted edge risk context when the required property and product are
configured. No such integration is claimed here.

## Next customer pilot

Add an embeddable widget and authenticated server verification API, with explicit
site/session/action binding and tenant isolation. Evaluate on independent, diverse
human and adversarial samples. Address forgeable browser telemetry, public seeded
paths, fallback abuse, operational monitoring, and scalable rate limits before
production claims. The new display removes movement guidance; it does not hide
the deterministic path from code running in the browser.

## Behavioral-model research and implementation proposal — 2026-10-11

Status: research and code audit completed; the following is a proposed upgrade,
not a trained or deployed detector. Keep the current live policy while collecting
evidence and evaluating candidates in shadow mode.

### What the research supports

The final [BeCAPTCHA-Mouse paper](https://biometrics.eps.uam.es/fierrez/files/2022_PR_BeCAPTCHA-Mouse_Acien.pdf)
compares handcrafted features and sequence models. Its Random Forest outperformed
its LSTM overall, with a particular advantage at smaller training-set sizes. It
studied mouse input and explicitly left laptop trackpads for future work. Its
results are benchmark evidence, not a performance estimate for Follow It.

[Niu et al.'s sequence-learning paper](https://www.researchgate.net/profile/Hongfeng-Niu/publication/354468819_Mouse_Dynamics_Based_Bot_Detection_Using_Sequence_Learning/links/6604089610ca86798715bbd3/Mouse-Dynamics-Based-Bot-Detection-Using-Sequence-Learning.pdf)
evaluates LSTM, 1D CNN, and CNN+LSTM using displacement and velocity sequences,
with people separated between training, validation, and testing. Its login task
and four synthetic bot families differ from our moving-target challenge. The
hybrid was not uniformly better than the individual architectures.

[Adversarial mouse-dynamics research](https://arxiv.org/abs/1905.11831)
also demonstrates successful generated-trajectory attacks against authentication
models. Authentication of known users is a different task from our bot check,
but the result contradicts any general claim that neuromotor signals cannot be
imitated. No browser-coordinate model can establish a biological source when an
attacker can supply indistinguishable telemetry.

The cited [2026 CNN/XGBoost paper](https://www.sciencedirect.com/science/article/pii/S1877050926029509)
reports 99.48% accuracy in its abstract. Full methods could not be retrieved in
this review, so its leakage controls and relevance to our task were not verified.
Do not adopt that number as our expected accuracy. Vendor explanations and the
2023 overview are useful context, not independent validation of universal rules
such as low human path efficiency, uniform angles, or inevitable bot consistency.

### Findings in this checkout

- `engine/scorer.py` reduces the entire attempt to five values. The active fixture
  enables four and accepts three passing bands (`pass_threshold=0.75`). Thus a
  failed tracking-related band can be outweighed by other properties.
- The lag estimator always returns a best offset between 0 and 500 ms. It does
  not separately establish that the best alignment is meaningful. A plausible
  lag estimate is insufficient evidence that the user responded to this target.
- Native samples are rounded and clamped in `web/static/comet.js`; scoring then
  linearly resamples at 60 Hz and applies a seven-sample smoother. This is useful
  for coarse motion but cannot be interpreted as a direct measurement of muscle
  tremor. Differentiation can amplify timestamp/position noise, while smoothing
  and interpolation can create or erase apparent corrections.
- The observed open-loop cursor pass is a required attack regression case. Its
  raw trajectory was not retained by ordinary checkout. Preserve the observed
  result and regenerate separately labeled synthetic trials across many seeds;
  do not reconstruct a fabricated exact recording or count it as human evidence.
- A read-only SSH attempt to fetch the exact stored pass features timed out in
  this research turn. The code findings explain a structural weakness; they do
  not identify which exact band that cursor attempt failed or passed.
- `engine/gate.py` currently re-scores stored summary features. It cannot evaluate
  a CNN/LSTM candidate from those summaries. New sequence evidence and an evaluator
  are necessary; installing a neural-network library alone cannot upgrade it.

### Which signals fit a three-second pursuit task

| Signal | Proposed use | Limit |
| --- | --- | --- |
| Response to target turns/speed changes | Error distribution, velocity alignment, lag plus alignment strength, recovery after turns | Core hypothesis to test; public seeded paths remain predictable |
| Speed, acceleration, jerk, corrections | Windowed statistics and learned local patterns; explicitly version filtering | Browser delivery and hardware affect these values; never require a universal tremor signature |
| Curvature and direction changes | Compare cursor motion with target-relative motion and residuals | A human following a curve need not have uniform angles or inefficient motion |
| Pauses and intervals | Short stalls, coverage gaps, and native event timing as supporting features | Event batching is not cognitive hesitation; do not infer a long-tail distribution from a few pauses |
| Fatigue/session drift | Defer | A single three-second trial does not measure long-session fatigue |

The [W3C Pointer Events specification](https://www.w3.org/TR/pointerevents3/)
documents coalescing and that trackpads and external mice commonly feed the same
mouse pointer. Browser telemetry does not reliably identify those two devices.
Retain explicit tester device labels; do not select a permissive scoring policy
solely from an untrusted device claim. Missing pressure or coalescing support is
not evidence of a bot. Predicted events must not become measured movement samples.

### Candidate models and data representation

Our engineering recommendation is to compare these candidates on the same data:

1. **Expanded feature baseline:** logistic regression and Random Forest, using
   target-response, kinematic, native timing, and sample-quality features. This
   tests whether extra representation alone fixes the known weakness and gives
   an interpretable comparator for neural models.
2. **First neural candidate: small 1D CNN.** Convolutions over time can learn local
   acceleration/correction patterns and relationships to the moving target.
   Start with three Conv1D blocks (32/64/64 channels), masked pooling, and a small
   classification head; treat these sizes as tunable starting points.
3. **LSTM comparator:** a 32- or 64-unit recurrent layer, dropout, and a small
   head. It can model the order of overshoot and recovery across the trial.
   Benchmark its accuracy and CPU cost; do not assume memory makes it superior.
4. **CNN+LSTM or fusion:** only if held-out results show a useful gain over the
   simpler candidates. A 2D image CNN is a secondary experiment because trajectory
   rasterization needs explicit time/speed encoding and can discard ordering.

An initial shared sequence representation can use about 180 time positions for
the three-second interval at 60 Hz: normalized cursor displacement/velocity,
target velocity, target-relative error, and a validity mask. Feed native timing
and quality summaries alongside the sequence. Keep native consented samples as
the source of truth; no interpolation across large gaps, no treating padding as
stillness, and no claiming resampled derivatives recover high-frequency biology.
Compare this representation with native-event sequences carrying delta-time if
the initial experiments show timing information is being lost.

Fit normalization, filtering choices, and any imputation on training data only.
Use binary cross-entropy, bounded hyperparameter search, early stopping on a
separate validation split, and learning curves. Tune decision thresholds for low
human rejection. Calibrate any probability-like output on separate representative
data, label it as a model risk score, and measure calibration under distribution
shift. A sigmoid output is not automatically a probability of humanity.

### Collection and honest evaluation

Collect fresh `plain_ring_v1`/`smooth_v2` recordings with explicit consent for
training and evaluation, including mouse, trackpad, and real phone touch. Begin
with a diverse pilot of roughly 30–50 participants and repeated sessions to test
the pipeline; this is a planning target, not a sufficient sample-size guarantee.
Use learning curves and per-device uncertainty to decide whether more data is
needed. The last verified current-display count was zero.

Add pseudonymous participant and session identifiers, telemetry schema version,
collector version, challenge binding, device labels, viewport scale, observed
event timing, and sample-quality metadata. Avoid names, unrelated browsing data,
or persistent hardware identifiers. The public `human_test` request field does
not prove a human label: admit training evidence through controlled tester
enrollment and server-issued collection authorization. Passing the old detector
must never be used as a human ground-truth label.

Consented local files can support the initial experiment; paid Object Storage
is not a prerequisite for offline research. A durable cloud sequence dataset
does require configured storage. Retain the existing 72-hour raw-cloud deletion
policy; derived sequence tensors require equivalent treatment. Local research
copies need explicit cleanup. Do not silently extend retention for training.
Explain training purpose and model-artifact retention in participant consent.

Generate labeled attacks through several mechanisms: the observed generic wave,
simple straight/curved motion, target-aware feedback, existing Red forgeries,
and consent-permitted replay/transplantation. Include real browser-generated
automation events so the detector cannot succeed merely by recognizing one
synthetic timestamp format. Source replays and all their derivatives stay in the
same split. Public benchmarks are useful for reproducing methods, with their
permissions checked; their click tasks are not our final evaluation population.

Keep all recordings from one participant in one train/validation/test split.
Use fresh seeds, browser/device holdouts, and leave-one-attack-family-out tests.
[Grouped evaluation](https://scikit-learn.org/stable/modules/cross_validation.html#cross-validation-iterators-for-grouped-data)
prevents subject leakage. Keep a locked audit set outside Red/Blue tuning; a
frequently reused gate sample must not be presented as an unseen test set.

Report attack acceptance by attack family; human rejection and retry rates by
device; completion time; fallback use; and p50/p95 inference latency. Include
participant-aware confidence intervals, not accuracy alone. Evaluate motor/access
needs through consented usability testing rather than inferring disability from
motion. Missing coverage remains untested. Preserve the keyboard fallback and
measure its abuse separately: a stronger movement model does not secure checkout
if automation can choose a permissive fallback.

### Integration with Red, Blue, and Akamai

The roles are separate: the trained classifier evaluates movement; Akamai's
`hackathon-chat` endpoint continues powering the Strands Red/Blue agents. The
chat endpoint is not a supplied LSTM/CNN training or serving API. Train candidates
in a controlled offline job. Blue receives aggregate evaluation reports and
proposes a registered candidate; raw human samples never enter its prompts.

Initially run candidate inference in shadow mode with identical inputs to the
active deterministic scorer. Ordinary raw samples remain transient in memory.
Use PyTorch for neural experiments and evaluate CPU export, such as
[ONNX Runtime](https://onnxruntime.ai/docs/performance/), on the actual Linode.
A sub-50-ms p95 inference budget is a proposed target, not a measured claim.
No GPU service or additional paid resource is required to start the benchmark.

After approval, a trained classifier would be a local, versioned calculation in
the app request path; this deliberately expands the initial heuristic-only plan.
LLM/network inference remains outside checkout. Missing/invalid artifacts or
inference failures must produce a browser-check outcome, never an automatic pass
or a silent switch to another scorer. LLM timeouts cannot alter the active policy.

Proposed code changes, kept backward-compatible with the existing v1 scorer:

| Area | Change |
| --- | --- |
| `web/static/comet.js`, recorder, contracts | Versioned telemetry/quality metadata; consented native sequence collection |
| New `engine/features_v2.py` | Target-conditioned features and explicit signal-quality handling |
| New `engine/ml/` | Dataset validation/splits, model candidates, training, evaluation, inference adapter |
| `engine/scorer.py`, `web/engine_adapter.py` | Tagged scorer families; retain existing deterministic evaluator |
| `web/schema.sql`, public challenge route | Snapshot model hash, preprocessing/feature version, threshold, and policy at issue time |
| `engine/gate.py`, `web/routes_lab.py` | Evaluate both candidates on the identical available sequence evidence; include artifact and evidence hashes in approvals |

The model manifest must bind weights, preprocessing, schema, threshold, dataset
manifest, split IDs, and motion/display versions. Blue cannot submit arbitrary
executable model code or replace a registered artifact. Activation retains the
fixed requirement of fewer stored attack passes and no added human rejections in
represented device groups, plus operator approval. Include missing-group notices
and separate locked-audit results. The gate has to revalidate its evidence at
activation; expired/deleted sequence evidence invalidates pending approvals.
Historical aggregate reports may document a past evaluation but cannot stand in
for missing inputs during a new activation check. Previously issued challenges
keep their complete pinned scorer, including retained artifact availability.

Suggested order: trusted collection and attack regression suite; expanded feature
baseline; CNN/LSTM offline comparison; shadow benchmark on the VM; then a gated
operator-reviewed release if the measured evidence supports it. The defensible
pitch is learning the relationship between target response and movement while
showing measured human impact—not claiming that AI cannot mimic a hand.

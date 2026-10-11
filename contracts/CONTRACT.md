# API and data contract

The FastAPI app owns persistence and reservations. It imports deterministic
engine functions through `web.engine_adapter`; the separate agent worker calls
the authenticated HTTP API. See [the changelog](CHANGELOG.md) for protocol
changes. The examples below illustrate shapes, not measured human performance.

## Constants

| Name | Value |
|---|---|
| Canvas | 600 × 400 logical px (scale with CSS; always convert pointer coords to logical px) |
| Challenge duration | 5,000 ms of following (`plain_ring_5s_v2`) |
| Sample rate | browser sends every `pointermove` (coalesced), about 60 Hz; the scorer resamples to 60 Hz |
| Token lifetime | 120 s, single use, bound to `session_id` and `action="reserve_ticket"` |
| PoW | SHA-256(`nonce` + ":" + `counter`), leading zero **bits** = `bits` (start 18) |
| Lab auth | header `X-Lab-Key: <LAB_KEY>` on every `/v1/lab/*` and on red attempts |
| Limits | 10 challenges/min per `session_id`, 5 attempts per challenge, 2 reservations per `session_id`, IP ceiling 300/min |

## The comet path (both implementations must give identical numbers)

The algorithm below is retained as legacy `v1`. New challenges use
[roaming_v3](ROAMING_PATH.md); [smooth_v2](SMOOTH_PATH.md) remains documented
for historical recordings. An omitted version in old recordings or direct
path calls still means `v1`. Challenge responses pin `path_version`; both rendering
and scoring must use it, and calibration/gate evidence must not mix versions.

PRNG is **mulberry32** on a 32-bit unsigned integer seed. Draw random numbers in exactly this order:

1. For the x axis, then the y axis, for each of 3 components with base amplitudes **x: 130, 50, 20** and **y: 80, 35, 15**: `freq = 0.10 + r()*0.25` Hz, `phase = r()*2π`, `amp = base*(0.6 + 0.4*r())`.
2. Two "kicks" (sudden direction changes) with base times 900 and 1900 ms: `tk = base + r()*500`, `angle = r()*2π`, `mag = 60 + r()*30`.

Position at `t_ms`:

- `x = 300 + Σ amp·sin(2π·freq·t + phase)`, `y = 200 + Σ …` (t in seconds)
- For each kick: `u = clamp((t_ms − tk)/120, 0, 1)`, `s = u²(3 − 2u)`, `x += mag·cos(angle)·s`, `y += mag·sin(angle)·s`
- Clamp x to [30, 570] and y to [30, 370].

**Verified test vectors** (Python and JS implementations below match these exactly):
```json
{"seed": 42, "points": [[0, 361.782, 286.807], [500, 265.068, 254.297], [1000, 103.824, 209.568], [1500, 75.053, 158.319], [2000, 99.391, 116.103], [2500, 191.758, 125.05], [3000, 289.423, 169.156]]}
{"seed": 1, "points": [[0, 279.634, 232.203], [500, 392.337, 154.75], [1000, 435.541, 127.362], [1500, 387.799, 99.195], [2000, 282.197, 152.985], [2500, 275.603, 174.972], [3000, 276.073, 122.435]]}
```
Check to within 0.01 px.

## Data shapes (JSON)

October 11 five-second update: each challenge returns `path_version` and
`presentation_version="plain_ring_5s_v2"`. The server stores both on attempts and
consented recordings, and snapshots the issued scoring policy on the challenge.
Retiring/resetting a variant does not change an already issued check. Missing
historical presentation metadata means `legacy`; current gates and lab listings
filter both motion and display. Approval fingerprints include both identities.
The visitor QR is `/qr`; consent-based calibration uses `/qr/tester`.

**Trail** (browser → server, and Red → server):
```json
{"samples": [[0, 412.0, 233.5], [16, 414.2, 236.0]],
 "device": "mouse | trackpad | touch",
 "pointer_type": "mouse | pen | touch",
 "cohort": "organic | human_test | red",
 "tester": {"consent": true, "nondominant_hand": false},
 "round_id": null,
 "presentation_version": "plain_ring_5s_v2"}
```
- `samples` are `[t_ms, x, y]`. `t_ms` counts from the moment the comet starts moving. `x` and `y` are logical canvas px.
- `tester` appears only in tester mode.
- `round_id` is set only for red attempts.
- Tester submissions must confirm the issued `presentation_version`; missing or
  mismatched display metadata returns 409 without recording current human evidence.
  This prevents accidental mixing from cached tester pages, not forged telemetry.

**ScoreResult** (`engine.scorer.score()` and the attempt API return it; the ordinary checkout UI hides detailed features):
```json
{"score": 0.75, "pass": true, "variant": "v1",
 "features": {
   "lag_ms":         {"value": 216.7, "band": [120, 450], "ok": true,  "enabled": true},
   "err_mean_px":    {"value": 45.2,  "band": [8, 90],    "ok": true,  "enabled": true},
   "submoves_per_s": {"value": 2.0,   "band": [1.5, 6],   "ok": true,  "enabled": true},
   "jitter_px":      {"value": 0.4,   "band": [0.8, 6],   "ok": false, "enabled": true},
   "power_law_beta": {"value": 0.24,  "band": [0.2, 0.45],"ok": true,  "enabled": false}}}
```

**Variant** (stored as JSON in `variants.config`):
```json
{"id": "v1", "parent": null, "author": "operator | blue",
 "enabled": ["lag_ms", "err_mean_px", "submoves_per_s", "jitter_px"],
 "pass_threshold": 0.75,
 "features": {"lag_ms": [120, 450], "err_mean_px": [8, 90], "submoves_per_s": [1.5, 6],
              "jitter_px": [0.8, 6], "power_law_beta": [0.2, 0.45]},
 "reason": "starting bands from motor-control literature; recalibrate from human traces"}
```

**GateResult** (`engine.gate()` returns it):
```json
{"candidate": "v2", "baseline": "v1", "verdict": "approve_for_review | reject",
 "humans_rejected": {"mouse": {"total": 9, "candidate": 0, "baseline": 0},
                     "trackpad": {"total": 9, "candidate": 3, "baseline": 0}},
 "forgeries_passed": {"candidate": 1, "baseline": 7, "total": 24},
 "reasons": ["rejects 3 of 9 trackpad users (baseline 0)"]}
```

**Gate rule** (fixed, no model): approve for human review only if **no device group rejects more humans than the baseline** AND **fewer forgeries pass than under the baseline**. Otherwise reject, listing every reason.

## Python interfaces imported through `web.engine_adapter`
```python
from engine.path import make_path        # make_path(seed:int) -> pos(t_ms:float) -> (x, y)
from engine.scorer import score          # score(samples:list, seed:int, variant:dict) -> ScoreResult dict
                                         #   raises ValueError("trail too short") if < 1 s of samples
from engine.gate import gate             # gate(candidate:dict, baseline:dict,
                                         #      humans:[{"device","features"}], forgeries:[{"round_id","features"}]) -> GateResult
```
`score()` always computes all 5 features (store `features` as given). `gate()` uses **stored feature values only**, never raw trails, without a model call.

## HTTP API

**Public**
| Method | Path | Body → Response |
|---|---|---|
| POST | `/v1/challenges` | `{session_id}` → `{challenge_id, seed, variant_id, duration_ms: 5000, expires_in_s: 120, path_version, presentation_version}` |
| POST | `/v1/challenges/{id}/attempt` | Trail → `{result: ScoreResult, token: "tok_…" \| null, fallback: "pow" \| null}`. A red attempt needs `X-Lab-Key` and never gets a token. |
| POST | `/v1/pow` | `{session_id}` → `{pow_id, nonce, bits, expires_in_s: 120}` |
| POST | `/v1/pow/{id}/solve` | `{counter}` → `{token}` or 400 |
| POST | `/demo/tickets/reserve` | `{token, session_id}` → 200 `{reservation_id}`, or 409 `{reason: "used" \| "expired" \| "wrong_session" \| "cap"}` |

**Lab** (all need `X-Lab-Key`)
| Method | Path | Body → Response |
|---|---|---|
| GET | `/v1/lab/human-features` | → `[{"attempt_id", "device", "nondominant_hand", "features", "path_version", "presentation_version"}]` (current motion/display `human_test` cohort only; **no raw trails**) |
| GET | `/v1/lab/forgeries?round_id=` | → `[{"attempt_id", "round_id", "features", "score", "pass", "path_version", "presentation_version"}]` (current motion/display; all rounds if no `round_id`) |
| GET | `/v1/variants` / `/v1/variants/active` | → `[Variant]` / `Variant` |
| POST | `/v1/variants` | Variant → `{id}`, stored with status `candidate` |
| POST | `/v1/lab/gate` | `{candidate_id}` → GateResult (baseline = active variant; stored in `gate_decisions`) |
| POST | `/v1/lab/approvals` | `{interrupt_id, variant_id, gate}` → `{approval_id}` (shows the Approve card on the dashboard) |
| GET | `/v1/lab/approvals/{approval_id}` | → `{status: "pending" \| "approved" \| "denied"}` |
| POST | `/v1/lab/approvals/{approval_id}/decide` | `{approve: bool}`. Dashboard only. |
| POST | `/v1/variants/{id}/activate` | → 200, or **403 unless an approval for this variant is `approved`** (the server enforces this too, not only Strands) |
| POST | `/v1/lab/runs` | `{kind: "red" \| "blue"}` → `{run_id}`. Dashboard button; queues a command. |
| GET | `/v1/lab/commands/next` | → `{run_id, kind}` or 204. The worker polls this every second. |
| POST | `/v1/lab/events` | LabEvent → 204. The worker posts; the app stores it and pushes it to SSE. |
| GET | `/v1/lab/stream` | SSE: one `data: <LabEvent JSON>` per event |
| POST | `/v1/lab/reset` | Deletes red attempts, approvals and candidate variants; re-activates `v1` |

**LabEvent**:
```json
{"run_id": "run_7", "agent": "red | blue | gate | system", "type": "round_started | tool_call | tool_result | attempt_scored | round_report | gate_result | approval_needed | variant_activated | error", "ts": 1760130000.12, "data": {}}
```
- `tool_call.data = {tool, args}`
- `tool_result.data = {tool, summary}` (≤ 200 chars)
- `attempt_scored.data = {attempt_id, score, pass, failed: [feature names]}`
- `round_report.data = RoundReport`
- `gate_result.data = GateResult`
- `approval_needed.data = {approval_id, variant_id, gate}`

**RoundReport** (Strands structured output):
```json
{"round": 3, "agent": "red", "attempts": 8, "passed": 3, "best_params": {"lag_ms": 230, "noise_px": 1.4, "submove_hz": 3, "overshoot": 0.1},
 "what_changed": "added sub-movements; jitter now inside band", "evidence": ["att_91", "att_94"]}
```

## Database state

The schema in [web/schema.sql](../web/schema.sql) defines challenges, attempts,
passes, reservations, variants, approvals, gate decisions, lab events/commands,
and research enrollments/recordings. Challenges snapshot their issued policy;
attempts retain path and presentation versions. Approval fingerprints bind the
exact evidence. Research schema and consent are described in
[model research](../engine/ml/README.md).

## Environment variables

| Var | Used by | Example |
|---|---|---|
| `DATABASE_URL` | app | `postgresql://…@…:…/defaultdb?sslmode=require` |
| `S3_ENDPOINT`, `S3_BUCKET`, `S3_KEY`, `S3_SECRET` | app | `https://us-sea-1.linodeobjects.com`, `followit-trails` |
| `LAB_KEY` | both | a random 32-char string |
| `API_BASE` | worker | `https://<your-domain>` (or `http://localhost:8000` against the devserver) |
| `AKAMAI_BASE_URL`, `AKAMAI_API_KEY`, `MODEL_ID` | worker | `https://ws.akamai-workshops.com/v1`, `hk_…`, `hackathon-chat` |
| `USE_BEDROCK`, `AWS_BEARER_TOKEN_BEDROCK` | worker | explicitly configured optional provider |

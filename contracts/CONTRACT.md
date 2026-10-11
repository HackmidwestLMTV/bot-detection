## SHARED CONTRACT (identical in both files, frozen at 5:30 PM)

This section is word-for-word the same in `person-1-platform.md` and `person-2-engine.md`. If you change anything here, both of you change it, and you note it in `contracts/CHANGELOG.md` (see "Changing the contract").

### The product in one sentence
> On a ticket checkout, one AI (Red) learns to fake a human hand, a second AI (Blue) tries to block it, and before any block goes live, a fixed gate shows how many real people it would lock out, and a person approves.

### Who owns what (never edit the other person's folders)

```text
followit/
├── contracts/            SHARED. Person 2 commits it at 5:30; Person 1 pulls that one commit. Then frozen.
│   ├── CONTRACT.md       this section
│   ├── CHANGELOG.md      every change after 5:30, one line each
│   └── fixtures/
│       ├── path_vectors.json       seed → comet positions (both path implementations must match)
│       ├── variant_v1.json         the starting variant
│       ├── score_example.json      a real ScoreResult
│       ├── gate_example.json       a real GateResult
│       └── events_example.jsonl    one full lab cycle of SSE events (for Person 1's dashboard)
├── web/                PERSON 1 ONLY (not named platform/: that hides Python's built-in module): FastAPI app, DB, storage, tokens, PoW, all HTML/JS, deploy files
└── engine/               PERSON 2 ONLY: path.py, scorer.py, gate.py, forger.py, agents/, worker.py, devserver.py
```

- **Only two places where the code meets:**
  1. Person 1's app **imports three pure functions** from `engine`: `make_path`, `score`, `gate`. It always goes through `web/engine_adapter.py`, which falls back to stubs until the merge.
  2. Person 2's worker **talks to Person 1's app over HTTP** (the lab endpoints below). It never touches the database.
- **One repo, two branches:** `p1-platform` and `p2-engine`. Merge to `main` at the end.
- **Both of you run** `pytest contracts/` **before every push.** Each of you writes your half of those tests (below).

### Constants
| Name | Value |
|---|---|
| Canvas | 600 × 400 logical px (scale with CSS; always convert pointer coords to logical px) |
| Challenge duration | 3,000 ms of following |
| Sample rate | browser sends every `pointermove` (coalesced), about 60 Hz; the scorer resamples to 60 Hz |
| Token lifetime | 120 s, single use, bound to `session_id` and `action="reserve_ticket"` |
| PoW | SHA-256(`nonce` + ":" + `counter`), leading zero **bits** = `bits` (start 18) |
| Lab auth | header `X-Lab-Key: <LAB_KEY>` on every `/v1/lab/*` and on red attempts |
| Limits | 10 challenges/min per `session_id`, 5 attempts per challenge, 2 reservations per `session_id`, IP ceiling 300/min |

### The comet path (both implementations must give identical numbers)
Version note (October 10 demo update): the algorithm below is retained as `v1`.
New platform/recorder challenges use the versioned smooth path specified in
[SMOOTH_PATH.md](SMOOTH_PATH.md). An omitted version in old recordings or direct
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

### Data shapes (JSON)

**Trail** (browser → server, and Red → server):
```json
{"samples": [[0, 412.0, 233.5], [16, 414.2, 236.0]],
 "device": "mouse | trackpad | touch",
 "pointer_type": "mouse | pen | touch",
 "cohort": "organic | human_test | red",
 "tester": {"consent": true, "nondominant_hand": false},
 "round_id": null}
```
- `samples` are `[t_ms, x, y]`. `t_ms` counts from the moment the comet starts moving. `x` and `y` are logical canvas px.
- `tester` appears only in tester mode.
- `round_id` is set only for red attempts.

**ScoreResult** (`engine.score()` returns it; the attempt endpoint returns it):
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

### Python functions Person 1 imports from `engine`
```python
from engine.path import make_path        # make_path(seed:int) -> pos(t_ms:float) -> (x, y)
from engine.scorer import score          # score(samples:list, seed:int, variant:dict) -> ScoreResult dict
                                         #   raises ValueError("trail too short") if < 1 s of samples
from engine.gate import gate             # gate(candidate:dict, baseline:dict,
                                         #      humans:[{"device","features"}], forgeries:[{"round_id","features"}]) -> GateResult
```
`score()` always computes all 5 features (store `features` as given). `gate()` uses **stored feature values only**, never raw trails, so it's instant.

### HTTP API (Person 1 builds every route; Person 2's worker calls the lab ones)

**Public**
| Method | Path | Body → Response |
|---|---|---|
| POST | `/v1/challenges` | `{session_id}` → `{challenge_id, seed, variant_id, duration_ms: 3000, expires_in_s: 120}` |
| POST | `/v1/challenges/{id}/attempt` | Trail → `{result: ScoreResult, token: "tok_…" \| null, fallback: "pow" \| null}`. A red attempt needs `X-Lab-Key` and never gets a token. |
| POST | `/v1/pow` | `{session_id}` → `{pow_id, nonce, bits, expires_in_s: 120}` |
| POST | `/v1/pow/{id}/solve` | `{counter}` → `{token}` or 400 |
| POST | `/demo/tickets/reserve` | `{token, session_id}` → 200 `{reservation_id}`, or 409 `{reason: "used" \| "expired" \| "wrong_session" \| "cap"}` |

**Lab** (all need `X-Lab-Key`)
| Method | Path | Body → Response |
|---|---|---|
| GET | `/v1/lab/human-features` | → `[{"attempt_id", "device", "nondominant_hand", "features"}]` (cohort `human_test` only; **no raw trails**) |
| GET | `/v1/lab/forgeries?round_id=` | → `[{"attempt_id", "round_id", "features", "score", "pass"}]` (all rounds if no `round_id`) |
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

### Database tables (Person 1 owns them; listed here so Person 2 knows what exists)
`challenges(id, session_id, seed, variant_id, created_at, expires_at, attempts)`,
`attempts(id, challenge_id, cohort, device, nondominant_hand, round_id, features jsonb, score, pass, trail_key, created_at)`,
`tokens(id, session_id, action, expires_at, consumed_at)`, `pow(id, session_id, nonce, bits, expires_at, solved_at)`,
`reservations(id, session_id, token_id, created_at)`, `variants(id, config jsonb, status, created_at)`,
`approvals(id, interrupt_id, variant_id, gate jsonb, status, decided_at)`, `gate_decisions(id, candidate, baseline, result jsonb, created_at)`,
`lab_commands(id, kind, status, created_at)`, `lab_events(id, run_id, body jsonb, created_at)`.

### Environment variables
| Var | Used by | Example |
|---|---|---|
| `DATABASE_URL` | P1 | `postgresql://…@…:…/defaultdb?sslmode=require` |
| `S3_ENDPOINT`, `S3_BUCKET`, `S3_KEY`, `S3_SECRET` | P1 | `https://us-sea-1.linodeobjects.com`, `followit-trails` |
| `LAB_KEY` | both | a random 32-char string |
| `API_BASE` | P2 worker | `https://<your-domain>` (or `http://localhost:8000` against the devserver) |
| `AKAMAI_BASE_URL`, `AKAMAI_API_KEY`, `MODEL_ID` | P2 | `https://ws.akamai-workshops.com/v1`, `hk_…`, `hackathon-chat` |
| `USE_BEDROCK`, `AWS_BEARER_TOKEN_BEDROCK` | P2 | fallback only |

### The biggest risk, said plainly: merging only at the end
Two people working separately and merging at 7 AM is how teams demo nothing. The danger isn't git conflicts: you own separate folders, so those will be near zero. The danger is **two halves that each work alone and disagree on something small**: a coordinate scale, a field name, a timestamp origin, an SSE format. You'd find out at 7 AM with no time to fix it.

**The cheapest fixes that keep your way of working:**
1. **Integrate at deploy time, not in git.** From 11 PM, the VM builds from `p1-platform` plus the latest `engine/` folder copied from `p2-engine`. The deploy script does this (`git archive origin/p2-engine engine | tar -x`), and the copy is never committed. The live site then scores with the real engine, and Person 2's worker runs on the VM as a second container against the live API. Branches stay separate, but the system works together all night.
2. **Shared fixtures and tests.** Both of you run `pytest contracts/`. Person 2's tests check the engine against the fixtures. Person 1's tests check that the API returns fixture-shaped JSON.
3. **One adapter file.** Person 1 calls engine functions only through `web/engine_adapter.py`. It does `try: from engine… except ImportError: use stubs`. The merge flips it to real code with zero edits.
4. **Two throwaway trial merges, at 11 PM and 2 AM** (15 minutes each, below). Merge both branches into a scratch branch, run tests, start the app locally, play one comet, then **delete the scratch branch**. `main` stays untouched until the end.
5. **The final merge at 6:00 AM, not 7:45.** That leaves two hours to fix whatever it breaks.

### Trial merge (11 PM and 2 AM, either person runs it)
```bash
git fetch origin
git switch -c try-merge origin/p1-platform
git merge --no-edit origin/p2-engine          # should be conflict-free; if not, someone edited the other's folder
pip install -r web/requirements.txt -r engine/requirements.txt
pytest contracts/ engine/tests web/tests
uvicorn web.app:app --port 8000 &        # open /, play one comet, confirm the score has real feature values (not stub)
python -m engine.worker --once red            # one red round against localhost
git switch - && git branch -D try-merge       # throw it away
```

### Changing the contract after 5:30
Avoid it. If you must: message the other person first, then **Person 2** makes the change in `contracts/` as a single commit with a line in `CHANGELOG.md`. Person 1 runs `git cherry-pick <that commit>`. Never edit `contracts/` on `p1-platform` directly.

### Final merge checklist (start at 6:00 AM)
- [ ] Both branches pushed. Both `pytest` runs are green on their own branch.
- [ ] `git switch main && git merge p1-platform && git merge p2-engine`, with no conflicts outside `contracts/` (if there are any in `contracts/`, take Person 2's version).
- [ ] `engine_adapter.py` logs `using real engine` on startup, not `using stubs`.
- [ ] `pytest contracts/ engine/tests web/tests` passes on `main`.
- [ ] Deploy `main` to the VM (`docker compose up -d --build`), then **hard refresh** the browser.
- [ ] On the live site: play the comet on a phone (score shows 5 real features), reserve a ticket, and check a reused token returns 409.
- [ ] Skip → PoW → reserve works with the keyboard only.
- [ ] `/lab`: Run Red (events stream), Run Blue (gate result appears), Approve (variant activates), Reset.
- [ ] The concurrency test prints `1 success, 19 rejected`.
- [ ] Record the backup run (labelled REPLAY). Write the README. Submit by 8:00.
- [ ] **If the merge breaks and can't be fixed by 7:00, redeploy the 11 PM setup (`p1-platform` + `engine/` copied from `p2-engine` at deploy time) and demo that.** It has been running all night, so it's your safest build.

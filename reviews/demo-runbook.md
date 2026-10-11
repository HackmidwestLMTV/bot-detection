# Demo-night runbook — Follow It

Written 2026-10-10 for execution starting ~7:00 AM. Submission is 8:00 AM. Read the next
section first, do nothing else until you've skimmed it.

Branch note: Person 2's branch is **`origin/p2`**, not `p2-engine`. The contract
(`contracts/CONTRACT.md`) still says `p2-engine` in a few places — ignore that, it's stale.
`deploy.sh` already defaults `ENGINE_REF` to `origin/p2`; every command below uses the real
branch name.

---

## 0. IF IT IS BROKEN ON STAGE, DO THIS

In order. Don't debug live — fall back, then debug after you're off stage.

1. **Redeploy the last known-good build and demo that.** Per the contract's final-merge
   checklist: *"If the merge breaks and can't be fixed by 7:00, redeploy the 11 PM setup
   (`p1-platform` + `engine/` copied from `origin/p2` at deploy time) and demo that. It has
   been running all night, so it's your safest build."* Concretely:
   ```bash
   ssh root@<vm-ip>
   cd ~/followit
   bash deploy.sh engine          # platform + origin/p2, no BRANCH= override — the overnight combo
   ```
   If even that's shaky, go one step further and drop `engine` entirely:
   ```bash
   bash deploy.sh                 # platform only, stops the worker — ticket page still works
   ```
2. **If the live site itself is unreachable or flaky, play the recorded backup run instead
   of anything live.**
   ```bash
   # on your laptop, pointed at the deployed site
   python -m web.dev.replay_events https://$DOMAIN --file backup_run.jsonl --reset
   ```
   Then open `https://$DOMAIN/lab?replay=1` on the venue screen — the REPLAY banner confirms
   it to the audience, and the Run Red / Run Blue / Reset buttons are disabled (this is a
   recording, not a live run; nothing you click can break it). Narrate it as "this is the
   actual run we recorded overnight" — that's true, and it's the honest framing, not a trick.
   `recordings/rehearsal-synthetic-humans.jsonl` is a COMPLETE cycle you can replay today,
   but its gate numbers rest on SYNTHETIC human traces -- say that out loud, or better, record
   a real one first (see §5). If no recording exists at all, record one now before you need it.
3. **If /lab itself won't load at all**, fall back to the ticket page only (`https://$DOMAIN/`)
   and narrate the Red/Blue/gate concept verbally using the gate numbers from your last
   successful run. A half demo beats a frozen screen.
4. Whatever you fall back to, **say out loud that it's a recording or a safe build** if it is
   one. Judges reward candour (see §7).

---

## 1. Deploy sequence — literal commands, in order

Run these from a fresh terminal on the VM (`ssh root@<vm-ip>`, then `cd ~/followit` — `deploy.sh`
`cd`s there itself, but you need to be there for ad-hoc `.env` edits).

### 1a. First time only: `vm_setup.sh`
```bash
bash vm_setup.sh
```
**Correct output:** ends with
```
Edit ~/followit/.env: DATABASE_URL, S3_KEY, S3_SECRET and AKAMAI_API_KEY.
Allow this VM's IP in Managed Postgres, then run: bash ~/followit/deploy.sh engine
Keep LAB_KEY private; retrieve it from .env only when setting up the lab dashboard.
```
**If wrong:**
- `docker compose version` fails → Docker didn't install; re-run, check network.
- Script exits with `Set DOMAIN explicitly when public IPv4 discovery is unavailable.` → the VM
  couldn't reach `ifconfig.me` (firewall?); re-run with `DOMAIN=<your-host> bash vm_setup.sh`.
- Nothing printed about editing `.env` → an `.env` already existed and was left alone
  (deliberate — it never overwrites). Check `cat ~/followit/.env | grep -c '^'` to confirm it
  has content, then fill in the four secrets below by hand.

Then, **by hand**, fill in `~/followit/.env`: `DATABASE_URL`, `S3_KEY`, `S3_SECRET`,
`AKAMAI_API_KEY`. Do not print the file to a shared screen — it holds live secrets.

### 1b. Platform-only deploy (`bash deploy.sh`)
Use this to get the ticket page up fast, with the worker stopped. The gate/approval/activate
path on `/lab` will **503** in this mode — that's deliberate, not a bug (see §6).
```bash
bash deploy.sh
```
**Correct output**, in order:
```
Deployment snapshot: /root/.local/share/followit/releases/release.XXXXXXXX
<docker compose build output for app, caddy>
<docker compose up -d --wait output — containers reported healthy>
{"ok":true,"engine":"stubs","active_variant":"v1","human_traces":{"total":0}}
Live at https://<ip-with-dashes>.sslip.io
```
`"engine":"stubs"` is correct here — the engine isn't overlaid in platform-only mode.
**If wrong:**
- `Run vm_setup.sh and configure .env first.` → `.env` missing or empty; go back to §1a.
- Fails at `git rev-parse --verify origin/p1-platform^{commit}` → branch not pushed, or you
  forgot `git fetch origin` happened automatically (it does, inside the script) — check your
  push actually landed: `git ls-remote origin p1-platform`.
- Fails at `docker compose ... config --quiet` → a Compose/Caddyfile syntax error, or a
  required env var is unset (`LAB_KEY` is hard-required: `${LAB_KEY:?Configure LAB_KEY in
  .env}` in `compose.yaml`). Check `.env` has `LAB_KEY=`.
- `up -d --wait --wait-timeout 120` times out → the app's healthcheck (`/healthz`) never goes
  green. Usual cause: `DATABASE_URL` wrong or the Managed Postgres allow list doesn't include
  this VM's IP yet — **it hangs, it does not error clearly** (see §6). Check:
  `docker compose --project-name followit -f <release>/compose.yaml logs app` from the printed
  release path.
- Final `curl -fsS http://127.0.0.1:8000/healthz` fails → app crashed after passing its own
  healthcheck transiently; check the same logs.

### 1c. Engine deploy (`bash deploy.sh engine`)
Use this before demoing anything on `/lab` past "Red runs and streams events" — Approve only
works once `engine/` is overlaid.
```bash
bash deploy.sh engine
```
**Correct output:** same shape as 1b, plus a worker build/start, plus one extra line before the
healthz check:
```
<worker image build>
<app, caddy, worker reported healthy/started>
<no visible output from the worker --check-api line unless it fails>
{"ok":true,"engine":"real","active_variant":"v1","human_traces":{"total":0}}
Live at https://...
```
`"engine":"real"` is the thing to look for — if it still says `"stubs"`, the engine overlay
failed silently upstream (see troubleshooting table).
**If wrong (in addition to the 1b causes):**
- Fails at `git cat-file -e origin/p2:engine/Dockerfile` → `origin/p2` doesn't exist or wasn't
  pushed; check `git ls-remote origin p2`. (If someone revived the old `p2-engine` name, set
  `ENGINE_REF=origin/p2-engine bash deploy.sh engine` explicitly — but confirm with Person 2
  which branch is actually current first.)
- `docker compose exec -T worker python -m engine.worker --check-api` fails → `LAB_KEY`
  mismatch (the worker and the app must share the same value from `.env`) or `AKAMAI_API_KEY`
  missing/invalid. Deploy **stops here with a nonzero exit** — containers from the *old*
  release are still running because build-before-replace means nothing was torn down; you are
  not down, just not upgraded.

### 1d. After the final merge: `BRANCH=main`
Once `p1-platform` and `origin/p2` are merged into `main` (contract's 6:00 AM step):
```bash
BRANCH=main bash deploy.sh engine
```
Everything else is identical to 1c, just reading `origin/main` instead of
`origin/p1-platform`. Optionally pin a specific reviewed commit instead of chasing `origin/p2`
live: `ENGINE_REF=<commit-sha> BRANCH=main bash deploy.sh engine`.

After any successful deploy: **hard refresh** the browser tab showing `/` and `/lab` (old
cached JS is a classic "why isn't Approve working" false alarm).

---

## 2. Pre-demo checklist (physically verify each line)

Derived from the contract's final-merge checklist (`contracts/CONTRACT.md`), translated into
exact commands/clicks. Run top to bottom.

- [ ] **Both branches pushed.** `git ls-remote origin p1-platform p2` — both print a commit
      hash, not empty.
- [ ] **Both `pytest` runs are green on their own branch.**
      On `p1-platform`: `.venv/bin/pytest contracts/ web/tests -q` → no failures (DB-dependent
      tests skip without Postgres, that's fine). On `p2`: `pytest contracts/ engine/tests -q`.
- [ ] **Merge to `main` is conflict-free outside `contracts/`.**
      `git switch main && git merge p1-platform --no-edit && git merge p2 --no-edit`
      — if a conflict appears anywhere except `contracts/`, someone edited the other person's
      folder; stop and sort it out before continuing. A conflict inside `contracts/` takes
      Person 2's version.
- [ ] **Real engine is loaded, not stubs.** After deploying `main`:
      `docker compose --project-name followit logs app | grep -i "engine mode"` → must print
      `engine mode: real engine`, not `engine mode: stubs`.
- [ ] **Full suite passes on `main`.** `.venv/bin/pytest contracts/ engine/tests web/tests -q`.
- [ ] **Deploy `main`.** `BRANCH=main bash ~/followit/deploy.sh engine` (not
      `docker compose up -d --build` — that's what the contract's checklist literally says, but
      `deploy.sh` replaced that manual step; use the script). Then hard-refresh the browser.
- [ ] **On the live site, phone or laptop:** open `https://$DOMAIN/`, play the comet. Confirm
      the result panel shows 5 real feature values (not all `0.0` — that pattern means the
      stub scorer, i.e. the engine didn't load). Click Reserve — get a reservation id.
- [ ] **Reused token returns 409.** Reload the ticket page with the same token in devtools, or
      simply click Reserve twice fast — second call returns HTTP 409 with
      `{"reason": "used"}` (or `wrong_session`/`expired`/`cap`).
- [ ] **Keyboard-only path works.** Tab to the "skip" control, Enter, tab through the PoW
      flow, Enter to reserve — no mouse.
- [ ] **`/lab` full cycle.** Open `https://$DOMAIN/lab`, enter `LAB_KEY` (from `.env` on the
      VM — retrieve it privately, never paste it on a shared screen):
      `grep '^LAB_KEY=' ~/followit/.env`. Click **Run Red** (log streams), **Run Blue** (a gate
      result card appears with numbers), **Approve** (variant activates, metrics update),
      **Reset** (clears red attempts/approvals/candidates, re-activates `v1`).
      **Only run Blue once per approved cycle** — see the gate-deadlock trap in §6.
- [ ] **Concurrency test prints the exact line.**
      `FOLLOWIT_LIVE_URL=https://$DOMAIN .venv/bin/pytest -s web/tests/test_concurrency.py`
      → output contains `1 success, 19 rejected`.
- [ ] **Record the backup run** (see §5) and confirm `backup_run.jsonl` exists and is non-empty
      (`wc -l backup_run.jsonl`).
- [ ] **README reflects the deployed state**, submit by 8:00.

---

## 3. Three-minute demo script

Keep this tight — rehearse it once end to end before stage time. One sentence per beat; don't
ad-lib longer.

| # | Action | Say |
|---|---|---|
| 1 | On a phone, open `https://$DOMAIN/` (must be the **https** URL, never `http://ip:8000`). Follow the comet for 3 seconds. | "This is the real checkout gate: follow a comet with your finger for three seconds, and a live model scores how human that motion looked." |
| 2 | Show the pass → reserve a ticket, get a reservation id. | "Pass, and you get a single-use token — reserved, done." |
| 3 | Try to reuse the same token (reload and reserve again, or hit the API a second time) → 409. | "That token is single-use, enforced by an atomic database update — not a client check. Reuse it and it's rejected, no race." |
| 4 | Switch to `https://$DOMAIN/lab` on the venue screen. Click **Run Red**, let a few events stream. | "This is Red — an AI agent learning to fake that same hand motion against the live scorer, right now." |
| 5 | Click **Run Blue**, let the gate result render (point at the human-rejected and forgeries-passed numbers). | "Blue proposes a stricter rule. Before anything ships, a fixed gate — no model, just arithmetic — replays every stored human trace and every forgery against it." |
| 6 | Click **Approve**. Point at the active-variant metric updating. | "A person has to press this. The server enforces that too — try to activate a variant without an approval, and it's a hard 403, not just a UI guard." |

That's the whole arc: human passes → bot tries → gate checks → human approves → rule goes
live. Don't run Blue a second time in the same sitting (see §6) — end on the activation.

---

## 4. Troubleshooting table

| Symptom | Likely cause | Fix |
|---|---|---|
| `/lab` Approve (or even Run Blue's gate) returns 503 on an otherwise-working site | Platform-only deploy (`bash deploy.sh`, no `engine`) — gate/approval/activate require the real engine and refuse to serve stub evidence as real | Redeploy with `bash deploy.sh engine` before trying to demo Approve. This is intentional, not a bug — don't "debug" it live. |
| A phone sits forever on the comet result / PoW fallback, never gets a ticket | Phone loaded `http://<ip>:8000` directly instead of the HTTPS domain — `crypto.subtle` (used by the PoW worker) doesn't exist outside HTTPS/localhost, so the fallback silently never finishes | Always hand testers the `https://$DOMAIN/` URL (the `/qr` page encodes this correctly); never the bare IP:port. |
| `deploy.sh` hangs at `docker compose up -d --wait` and eventually times out after 120s with no useful error | Managed Postgres's IP allow list doesn't include the VM's address yet — the connection **hangs**, it does not fail fast | In Cloud Manager, add the VM's public IPv4 to the database cluster's allow list, then re-run `deploy.sh`. Confirm first with `docker run --rm postgres:18 psql "$DATABASE_URL" -c "select version();"` from the VM — same hang means same cause. |
| Running Blue a second time after an Approve always comes back `verdict: reject` with reason "forgeries passed did not decrease" | Known gate-rule edge case (flagged in `reviews/p2-engine-review.md`, item #3, unresolved as of this writing — `engine/gate.py` still has `passed["candidate"] >= passed["baseline"]`): once a variant blocks 100% of forgeries, no later variant can ever show fewer forgeries passing than 0, so the rule deadlocks by design, not by bug | Demo only **one** Blue round per `/lab` reset. If a second round is needed, run `/v1/lab/reset` first. |
| Dashboard SSE feels laggy, drops events, or two sessions see different numbers | Someone started the app with `--workers 2` (or more) — the rate limiter and SSE broadcaster are both in-process, in-memory state that doesn't share across workers | Confirm `compose.yaml`'s app command is `uvicorn web.app:app --host 0.0.0.0 --port 8000 --workers 1`. Never override `--workers` on the CLI or in a derived compose override. |
| A real phone takes noticeably long (several seconds of visible stall) on the PoW fallback | `POW_BITS` defaults to 18, which is tuned for a laptop CPU | Set `POW_BITS=16` in `.env` and redeploy (`bash deploy.sh`) if a real phone is taking more than ~4 seconds. |
| `/lab?replay=1` shows the right events but Approve/Run Red/Run Blue/Reset are all greyed out | Expected — it's a recorded run; `lab.js` disables those controls whenever `replay=1` because the database never actually changes during a replay | Not a bug. Use replay only as the stage-emergency fallback (§0), not as the primary demo. |
| `deploy.sh engine` fails at `git cat-file -e ...:engine/Dockerfile` | `ENGINE_REF` (defaults to `origin/p2`) doesn't resolve — branch not pushed, renamed, or someone reintroduced the stale `p2-engine` name from the contract | `git ls-remote origin p2` should print a hash. If the branch really is named differently now, set `ENGINE_REF=origin/<actual-branch>` explicitly and tell Person 2 the name drifted. |
| `deploy.sh engine` fails at `docker compose exec -T worker python -m engine.worker --check-api` | `LAB_KEY` in `.env` doesn't match what the app expects, or `AKAMAI_API_KEY` is blank/invalid | `grep -E '^(LAB_KEY|AKAMAI_API_KEY)=' ~/followit/.env` — confirm both are non-empty; LAB_KEY must be the same value you type into the `/lab` dashboard. |
| Scorer or rate limiter behaves oddly after someone "tested" curling port 8000 directly from outside the VM | Port 8000 is bound to VM-localhost in `compose.yaml` (`127.0.0.1:8000:8000`), so this specific exposure shouldn't be reachable publicly — but confirm | `ss -tlnp | grep 8000` on the VM should show it bound to `127.0.0.1`, not `0.0.0.0`. Only Caddy (80/443) should be publicly reachable; check the Linode Cloud Firewall rules too. |
| `/healthz` shows `"engine": "stubs"` right after an `engine` deploy | The engine overlay didn't take — either the build used a cached layer from before the overlay, or `ENGINE_REF` pointed at a ref that predates `engine/` existing cleanly | Re-run `bash deploy.sh engine` (build-before-replace means a bad attempt didn't break anything); check the printed release folder's `engine/` directory actually has the expected files: `ls <release>/engine`. |

---

## 5. Recording the REPLAY backup (do this once you have a clean successful run)

```bash
python -m web.dev.record_events https://$DOMAIN backup_run.jsonl
# now, on /lab: Run Red, Run Blue, Approve — the recorder stops itself after variant_activated
python -m web.dev.replay_events https://$DOMAIN --file backup_run.jsonl --reset   # verify it plays back
```
Keep `backup_run.jsonl` somewhere you can reach even if the VM is unreachable (laptop, not just
the VM) — it's your §0 fallback.

---

## 6. Known limitations — say these out loud if asked

- **In-memory rate limits and the SSE broadcaster.** Both live in a single Python process.
  The app is deliberately deployed with exactly one `uvicorn` worker
  (`--workers 1` in `compose.yaml`) on a single VM. This does not horizontally scale as-is;
  a real production version would move both to Redis or similar.
- **Single point of engine truth.** Until `engine/` is overlaid at deploy time, the app runs
  on stub scoring (`USING_STUBS=True` in `web/engine_adapter.py`) and the gate/approval/activate
  path refuses to run at all (`503`) rather than fabricate a real-looking decision. That's a
  deliberate safety choice, not a missing feature — but it means platform and engine are not
  actually one codebase yet; they're integrated at deploy time by copying `engine/` from
  `origin/p2` into the release snapshot, not by merging git history until the final `main`
  merge.
- **Humans pass with essentially zero margin.** With the starting variant's 4 enabled
  features and a 0.75 pass threshold, a human has to pass 3 of 4 — any one more marginal
  feature (an unfamiliar trackpad, a shaky hand) drops a real person straight to rejected.
  It degrades safely (rejection falls through to the proof-of-work path, nobody is locked out
  of the ticket), but it means the "watch a human pass the comet" demo moment has no slack.
- **The gate rule itself can deadlock.** Once a variant blocks 100% of observed forgeries, no
  later candidate can ever show fewer forgeries passing than zero, so a second Blue round
  always rejects by construction. This is flagged and unresolved as of this build
  (`reviews/p2-engine-review.md`); worth fixing in `engine/gate.py` after tonight, not during
  the demo.
- **The scorer's feature bands are not calibrated from real users yet.** They start from
  motor-control literature. `/healthz` reports how many human traces exist per device; that
  sample is still small. The gate is only as good as that evidence.
- **"Non-dominant hand" is a crude proxy for less precise movement**, not a model of
  disability, and device grouping (mouse/trackpad/touch) is coarse. Worth saying plainly if a
  judge asks about accessibility framing.

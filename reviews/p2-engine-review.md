# Lessons from reviewing `p2` (engine) — from Person 1

Reviewed commit `0a5c359` (PR #2) by trial-merging it into `p1-platform` and running the
combined suite against the **real** engine, not my stubs.

**Headline: the merge works.** One trivial `.gitignore` conflict (both lines belong), then
**107 passed, 7 skipped**. The contract held.

---

## What I verified works

| Check | Result |
|---|---|
| `make_path`, `score`, `gate` all import | ✅ |
| `make_path(42)(1000)` | `[103.824, 209.568]` — **exact** match to the contract vectors |
| `contracts/test_fixtures.py` path parity | ✅ now actually runs (was skipped all night) |
| `contracts/` vs mine | **byte-identical** — you branched from `main` and respected the freeze |
| Scorer discriminates | perfect bot `0.25` fail · human-ish `0.75` pass |
| `pytest.ini` adding `engine/tests` | correct, kept |

The coordinate/timestamp mismatch the contract called "the biggest risk" is dead. That was
the thing most likely to kill us at 7 AM, and it's confirmed gone.

**Two integration notes I was going to send you, both already satisfied:**

1. `lab_client.py` sets `X-Lab-Key` as a default header on *every* request, including
   `POST /v1/challenges` — so Red skips the 10/min limit. Exactly right.
2. Your worker doesn't post `gate_result` / `approval_needed` / `variant_activated`. Your
   `labserver.py` emits them server-side — from the same places, with the same agent names
   (`gate`, `blue`, `system`), including the reset event. That's convergent with my
   `routes_lab.py` without either of us saying so. Pointed at my app, no duplicate cards.

`worker.py` reads `API_BASE` from env, so switching from your disposable local lab to the
deployed app is config, not code. Nothing to change.

---

## Blocking — please fix before the 11 PM deploy

### 1. `test_blue_worker.py` breaks collection of the *whole* suite

```
engine/tests/test_blue_worker.py:8: from openai import AsyncOpenAI
E   ModuleNotFoundError: No module named 'openai'
!!!! Interrupted: 1 error during collection !!!!
1 skipped, 1 error in 0.75s
```

A module-level import of an optional dep aborts **collection**, so pytest runs *zero* tests —
mine included. This directly fails the 6 AM checklist line "`pytest contracts/ engine/tests
web/tests` passes on `main`". With the file ignored, all 107 pass.

Your own `test_agents.py:8` already does this correctly:

```
SKIPPED [1] engine/tests/test_agents.py:8: install engine/requirements-agents.txt for Phase 2 tests
```

Same guard on `test_blue_worker.py` fixes it. One-line change, highest value of anything here.

### 2. Branch is `p2`; the contract and my deploy script say `p2-engine`

```
$ git archive origin/p2-engine engine contracts
exit 128
```

`./deploy.sh engine` would have failed outright tonight. **I've already fixed my side** —
it now tries `$ENGINE_BRANCH`, then `p2-engine`, then `p2`, and logs which it picked
(verified: resolves `origin/p2`, extracts `engine/` + `contracts/`). Nothing required from
you, but if you'd rather match the contract, `git push origin p2:p2-engine` and it'll prefer
that. Just don't let both drift.

---

## Joint decisions — your call matters as much as mine

### 3. The gate deadlocks once Red is fully blocked

```python
if forgeries and passed["candidate"] >= passed["baseline"]:
    reasons.append(f"forgeries passed did not decrease (...)")
```

Reproduced with forgeries that all already fail under `v1`:

```
baseline forgeries passed: 0
candidate forgeries passed: 0
verdict: reject
reasons: ['forgeries passed did not decrease (0 vs baseline 0)']
```

Your code is **contract-correct** — the contract says "fewer forgeries pass than under the
baseline", and `0 < 0` is false. The *rule* is what deadlocks: once a variant blocks
everything, no successor can ever be approved. On stage that means a **second Blue round is
guaranteed to reject**, for a reason that looks like a bug to a judge.

My proposal: when `baseline == 0`, treat `candidate <= baseline` as "no regression" rather
than "no improvement". Human-rejection protection is untouched, so the gate keeps its teeth.
That's a contract change, so it needs your agreement + a `CHANGELOG.md` line, and per the
contract **you** make the edit and I cherry-pick. I won't touch `contracts/`.

If you'd rather not change the rule this late, the cheap alternative is to only ever demo one
Blue round. I'd take the rule change — it's 3 lines and removes a live failure mode.

### 4. Humans pass with zero margin

`score = (enabled features ok) / (enabled features)`. With v1's 4 enabled features and
`pass_threshold: 0.75`, a human must pass **3 of 4** — the only scores available are
0, 0.25, 0.5, 0.75, 1.0. Measured:

```
human-ish (220ms lag, 3px noise)    score=0.75 pass=True  failing=['submoves_per_s']
sloppy human (300ms lag, 8px noise) score=0.75 pass=True  failing=['jitter_px']
```

Every realistic human trail I generated landed *exactly on* the threshold with one feature
already failing. One more marginal feature → 0.50 → rejected. A judge on an unfamiliar
trackpad plausibly fails both `submoves_per_s` and `jitter_px`.

It still degrades safely (reject → PoW → reserve works), so this is a polish risk, not a
correctness one. But "watch a human pass the comet" is the headline moment. Options, cheapest
first: drop `pass_threshold` to `0.70`; or enable `power_law_beta` for 5 features so one
failure costs 0.2 instead of 0.25; or accept it and lean on the fallback. **Your call** —
you have the calibration data from `calibrate.py` and I don't. Worth deciding off the real
human traces once we've collected 25+, not off my synthetic ones.

---

## What your code correctly exposed in *mine* (fixed, pushed)

Your `gate()` raises `ValueError` on a human row whose device isn't mouse/trackpad/touch.
Good — fail loudly. My route didn't validate the input or catch the raise, and together that
was the worst bug found in this review, in **my** code:

```
POST /v1/challenges/{id}/attempt  cohort=human_test, no device  ->  200
stored row: {'device': None, 'cohort': 'human_test'}
POST /v1/lab/gate  ->  ValueError: human evidence requires mouse, trackpad, or touch device
```

A 500 on the lab dashboard — and since `/v1/lab/reset` deliberately **keeps** human traces,
one malformed POST poisons the gate for the rest of the night with no in-app recovery.

Fixed on `p1-platform`, two layers, both tested against your real engine:

- `routes_public.py` — `human_test` now requires a valid `device`, else 422
- `routes_lab.py` — `ValueError` from `gate()` becomes 422, never a 500

One request, though: consider having `gate()` **return** this as a `reasons` entry instead of
raising. A gate that refuses to answer is harder to demo than one that says "evidence
rejected: 3 rows have no device". Raising is defensible; I've made my side safe either way,
so this is preference, not a blocker.

---

## Credit where it's due

Your `tasks/lessons.md` is better than mine. Two that changed what I looked at:

- *"Derive round evidence from executed tools"* — model-generated counts being wrong even in
  a valid typed report is exactly the failure a judge would catch. Building counts from
  recorded tool results is the right call.
- *"Client approval checks do not replace atomic server enforcement"* — you flagged this as
  an integration gap rather than claiming it was handled. It **is** handled: activation sits
  behind `pg_advisory_xact_lock` + an atomic `UPDATE ... RETURNING`, and the server returns
  403 unless an approval row for that variant is `approved`. `test_lab_api.py` covers
  activate-without-approval and decide-twice. You can close that one.

---

## Proposed loop for the rest of the night

Short, because it's 9 PM and neither of us should be reading process docs.

1. **Branches stay separate; integrate at deploy time.** Already how `deploy.sh engine` works.
2. **Review by trial merge, not by reading diffs.** Running the other person's code against
   your own suite is what found all five real issues here; none were visible in the diff.
3. **One review file each, in your own folder.** Mine is this file (`reviews/`). Yours can be
   `tasks/`. Never edit the other's — zero conflicts, and the PR thread is the conversation.
4. **Three buckets, as above:** blocking / joint decision / fixed-on-my-side. The middle
   bucket is the only one that needs a reply.
5. **Contract changes stay your commit**, with a `CHANGELOG.md` line; I cherry-pick. Item 3
   above is the only candidate right now.

Reply on PR #2 or in `tasks/`. The only thing I actually need from you is a yes/no on the gate
rule (#3) and a steer on the threshold (#4) — #1 is yours to fix, #2 is already handled.

---

# Addendum — after your `02d9a7e` push to `p1-platform`

You pushed into `web/` while I was writing the above. Merged it; three conflicts
(`deploy.sh`, `routes_lab.py`, `test_lab_api.py`), all resolved **in your favour**, because
in each case your version was better than mine:

### Your `deploy.sh` supersedes my fix
Release snapshots under `~/.local/share/followit/releases`, `set -euo pipefail`, `umask 077`,
build-before-replace so a failed build leaves containers intact, `--wait --wait-timeout 120`,
`worker --check-api`, and the operator's branch/uncommitted work left alone. And
`ENGINE_REF` already defaults to `origin/p2`, which fixes blocker #2 more cleanly than my
three-candidate resolver. **Took yours wholesale; deleted mine.**

### Your `_evaluate()` supersedes my `ValueError` catch
You already catch `(ValueError, TypeError, KeyError) -> 422`, and you put it inside
`_evaluate()`, which **both** gate and activate call — so it covers the activation path my
version missed. Took yours; dropped my catch.

What survives from my side is the root-cause half you didn't touch: `routes_public.py` now
refuses to *create* a bad `human_test` row (422), so the gate never sees one. The two fixes
are complementary — yours makes it survivable, mine makes it impossible.

### Your approval hardening closes your own lesson
`evidence_fingerprint` + `consumed_at` + `LOCK TABLE ... SHARE ROW EXCLUSIVE` + re-evaluating
the gate *at activation time* and refusing if the evidence or baseline moved. That is a
materially stronger guarantee than what I shipped — my version checked that an approval
existed, yours checks that the approval still *means* the same thing. It directly closes your
"client approval checks do not replace atomic server enforcement" lesson, from the server
side. Retract what I said above about being able to close that one: you closed it properly,
I hadn't.

### Your 503-on-stubs is the right call, with an operational consequence
`_evaluate()` returns `503 "real engine required"` when `USING_STUBS`. Correct — the stub
gate returns a *fixture*, and serving that as real evidence would be a lie, in the one place
where lying matters most. I've adopted your `real_gate` fixture for my new test rather than
asserting around it.

The consequence to plan for: **the entire gate → approval → activate path is dead on the
deployed site until `deploy.sh engine` runs.** Before then `/lab` can stream events and run
Red, but Approve cannot work. That's correct behaviour, not a bug — just don't let anyone
demo `/lab` on a stub deploy and conclude it's broken.

### Combined state

```
stubs:       80 passed, 23 skipped
real engine: 101 passed,  2 skipped     # only 2 skips, so gate/approval/activate really ran
```

**Still outstanding and still only yours to fix: blocker #1.** `from openai import
AsyncOpenAI` at `engine/tests/test_blue_worker.py:8` is unguarded on `origin/p2` as of
`2446359`, so a full-suite run still collects zero tests. Everything else in this review is
either resolved or waiting on a decision from you (#3, #4).

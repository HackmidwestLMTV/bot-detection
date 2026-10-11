# Real-trace collection guide — one page, read before you start

Goal: at least ten real `smooth_v2` recordings in `contracts/fixtures/human_traces`, with
mouse, trackpad, **and** touch all represented. That is what `engine.calibrate.py` reads and
what Phase C's checkpoint is measured against. Synthetic data never counts, and neither do
legacy `v1` recordings — only fresh `smooth_v2` ones.

There are **two separate collection surfaces** in this app. Do not confuse their numbers:

| Surface | Where | Saves to | Counts for Phase C? |
|---|---|---|---|
| **Local recorder** | `/dev/recorder` (phone/LAN) | `contracts/fixtures/human_traces/*.json` | **Yes — this is the checkpoint.** |
| **Website research console** | `/research` → invite a volunteer → `/?tester=1` | signed envelopes in `RESEARCH_RECORDINGS_DIR` | No. Separate consent for future model-training data. Nice to have, not the blocker. |

If you only have a couple of hours, spend them on the **local recorder**. Use the website
invite flow afterward, or in parallel on a second device, if people are still willing.

## 1. Start everything (one command, one terminal)

```bash
bash scripts/collect.sh
```

Env vars you may want: `DATABASE_URL` and `LAB_KEY` (≥16 chars) to also bring up the website
and `/research` console; `RESEARCH_RECORDINGS_DIR` for where its recordings land; `BIND=127.0.0.1`
if you don't want other devices on the wi-fi able to reach it. Leave everything else default.
The script prints a scannable QR for the recorder and, if the website came up, a second QR/URL
for it. Ctrl-C stops both; nothing already saved is deleted.

If the phone can't connect: the wi-fi may isolate clients (try a hotspot), or a local firewall
is blocking the port.

## 2. What to say to someone

> "Can I borrow thirty seconds? We're calibrating a 'prove you're human' game and right now
> we only have fake, computer-generated data — we need a few people actually using their
> mouse, trackpad, or phone."

Hand them the device (or show the QR) and say:

> "Pick [mouse / trackpad / touch], hit New recording, and follow the glowing ball with
> [your mouse / your trackpad / your finger] for three seconds. Missing it is fine — that's
> useful too. When it's done, tick the consent box and hit Save. You'll see 'Saved locally'
> when it lands. A few goes — three or four — is plenty, then let the next person have a turn."

Each recording on the local recorder needs its own consent tick and its own tap on Save —
unlike the website flow, consent does not carry over between attempts there, so remind people
to tick the box every time before they hand the device back.

## 3. What consent they're actually giving

- **Local recorder** (`/dev/recorder`): one checkbox per recording — "I consent to saving
  this real human movement recording locally for calibration." Nothing is written to disk
  unless they tick it and press Save. No name, email, or other identifier is collected.
- **Website tester mode** (`/?tester=1`, reached via a `/research` invite): two boxes, top to
  bottom — (1) *optional*, only matters if a research code is present, consents to using the
  recording to **train and evaluate movement models**; (2) consents to **sharing the
  recording for calibration**. Both are refusable independently; an invite link pre-fills the
  device and code but grants nothing — the volunteer ticks both boxes themselves, on their
  own screen. Raw recordings expire in 72 hours either way.

Never tick a consent box on someone's behalf, and never ask for a name or email — pseudonymous
IDs only.

## 4. Covering mouse, trackpad, and touch

Aim for ten total with all three represented — not ten of one device. Practical split for two
people and a couple hours: have the laptop out for mouse/trackpad passersby and a phone (or the
QR) out for touch, and consciously ask the next few people to use whichever device chip is
still empty. The `/research` console's chips (see below) make this easy to glance at; for the
local recorder, just keep a tally on paper or watch the terminal count (§6).

## 5. Checking progress mid-session

Two different counters, two different meanings — don't let one reassure you about the other:

- **`/research` console** (needs the operator `LAB_KEY`): shows a live tally of *website*
  recordings, chips per device, and a "+N just landed" flash right after a save — useful for
  confirming the website path is working, **not** a Phase C readout.
- **Phase C's actual count** is only on the collecting machine's disk. Run §6 or §7.

If the website's progress page shows a recording that "just landed" but you were watching the
*recorder*, you're looking at the wrong counter — go to §6 instead.

## 6. Confirm traces landed, by device (the real Phase C count)

Run this on the machine the recorder is running on (also printed by `scripts/collect.sh`, and
copyable from the `/research` page's "Local recorder traces" panel):

```bash
python3 -c "import collections,glob,json;t=[json.load(open(f)) for f in glob.glob('contracts/fixtures/human_traces/*.json')];c=collections.Counter(x['device'] for x in t if x.get('path_version')=='smooth_v2');print(sum(c.values()),dict(c))"
```

It prints a total and a per-device breakdown, filtered to `smooth_v2` only (legacy `v1` files
in the same folder are ignored, as they must be). Re-run it between volunteers.

## 7. Check usability — read-only, changes no bands

```bash
.venv/bin/python -m engine.calibrate --path-version smooth_v2
```

This only reads `contracts/fixtures/human_traces` and prints a JSON report — it never writes
to a variant file and never changes a threshold or band. Run it as often as you like. Look at:

- `"ready_for_review"` — `true`/`false`; the command also exits `0` when true, `2` when false.
- `"reasons"` — the first one is almost always `"need at least 10 unique consented
  recordings; found N"` until you hit ten, then `"missing devices: ..."` if one is still at
  zero.
- `"devices"` — per-device counts and how many recorded humans the candidate bands would
  reject; a nonzero `candidate_rejected` on a device means you want a couple more varied
  attempts from that device, not fewer.

If it rejects a file, the reason shows up under `"rejected_files"` — usually a stale
`path_version`/`presentation_version`, or a recording that didn't go through consented tester
mode. Don't edit those files or relabel them to make the count work; collect a fresh one instead.

# Recordings

Event streams captured from `/v1/lab/stream` with `web/dev/record_events.py`, replayed with
`web/dev/replay_events.py --file <path> --reset` and shown at `/lab?replay=1`.

## `rehearsal-synthetic-humans.jsonl`

A **complete** model-driven cycle, recorded locally on 2026-10-11 against the real engine and
the live Akamai model: Red round -> Blue round -> gate -> approval -> activation. 48 events,
nothing missing (`gate_result`, `approval_needed` and `variant_activated` all present).

Red went from score 0.0 with every enabled feature out of band to a full pass in 5 attempts
and 6 model calls, driving `jitter_px` 32.2 -> 9.9 -> 6.7 -> 5.19. Blue then capped the upper
bounds just above the human maxima and the gate approved it for review.

**Not demo-safe for the gate numbers.** The 14 human traces underlying it are SYNTHETIC --
generated to give the gate something to measure, because there were zero real `smooth_v2`
recordings. So its "humans rejected" figures say nothing about real people, and `phases.md`
is explicit that synthetic data must not stand in for real evidence.

Use it to show that the cycle works end to end, and say out loud that the human side is
synthetic. Re-record once Phase C has real consented `smooth_v2` traces, and only then treat
it as the stage fallback the runbook describes.

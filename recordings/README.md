# Recorded demonstration

`rehearsal-synthetic-humans.jsonl` is a historical local run recorded on October 11,
2026 against the real engine and Akamai inference: Red → Blue → gate → approval →
activation. Its 14 human-side traces were **synthetic**. The recording demonstrates
the control flow, not measured human impact or accuracy. It uses an older
presentation and is not evidence for `roaming_v3` / `plain_ring_5s_v2`.

Label it **REPLAY / SYNTHETIC HUMAN EVIDENCE** whenever shown. Do not import its
sample counts into current human calibration or research data.

## Play on a disposable local app

Set the local app's `LAB_KEY` in the terminal environment, then:

```bash
python -m web.dev.replay_events http://localhost:8000 \
  --file recordings/rehearsal-synthetic-humans.jsonl --reset
```

Open `http://localhost:8000/lab?replay=1`. The replay banner is visible and approval
controls are disabled. The command writes events and resets lab state: use a
disposable database, never the live collection deployment.

## Capture a new backup

```bash
python -m web.dev.record_events https://YOUR-HOST backup_run.jsonl
```

Run a real lab sequence while recording. Preserve its actual verdict, device
coverage, path/presentation, and whether approval occurred. Keep runtime captures
local. Only a fresh consented human sample can support human-impact claims for
the current presentation.

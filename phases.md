# Follow It: demo-first phases and P1/P2 handoff

Updated October 10, 2026 (America/Chicago). This is the current working plan;
earlier phase notes and `reviews/demo-runbook.md` describe historical states.

## Original goal

On a ticket checkout, Red tries to imitate a human hand, Blue proposes scoring
changes, and a fixed gate shows the effect on real people before a person approves.
The immediate priority is a demo Luc can use himself: smooth comet → understandable
score → ticket or accessible browser-check fallback. Akamai is the deployment target.

Do not expand the dashboard, add agents, relax the gate, or provision another VM to
fill time. Reuse the team's existing infrastructure after confirming its endpoint.

## Where we are

| Area | Current evidence | Still needed |
|---|---|---|
| Website and lab | Shared desktop/mobile design; ticket, fallback, single-use token, review/approval controls implemented | Real phone checkout over HTTPS |
| Engine | Deterministic paths, five features, forger, residual transplantation, fixed per-device gate | Real calibration for the new smooth path |
| Red / Blue | Akamai model integration and approval cycle previously exercised in a disposable local lab | A bounded cycle against the deployed integrated API |
| Integration | Current local suite: 220 Python tests, two expected skips; 13 frontend tests passed. Previous CI verified PostgreSQL18 and both Docker builds | Container CI for this update |
| Smooth comet | New versioned `smooth_v2`; continuous seeded curves, no kicks or hard clipping; Python/JS agreement | Luc's feedback on actual mouse/trackpad/touch comfort |
| Recordings | Nine consented legacy `v1` traces: eight mouse, one trackpad | New smooth-path recordings; do not count old traces as new calibration |
| Cloud | Scripts and containers target Akamai/Linode; model API already used | Team VM/app URL/IP, managed database and storage status are unconfirmed |
| PRs | #1 merged; #2 approved; #3 under integrated review | Finish current checks, merge #3 then #2, deploy one reviewed revision |

## Phase A — consolidate the demo (P2, with P1 review)

- Review both pending PRs together; preserve the stronger server approval checks.
- Use explicit trusted proxy ranges, with Caddy as the only public edge.
- Deploy one complete reviewed commit, including website, API and engine.
- Run contracts, engine, PostgreSQL API, frontend and container checks before merging.
- Preserve `v1` fixtures and recordings. New challenges pin `smooth_v2`; scoring,
  forgeries and saved metadata use that version. Gate evidence is separated by path.

The new path stays within x145–455 / y110–290 of the 600×400 logical canvas.
Its speed is bounded below 158 logical pixels/second. It remains a three-second task.
Motion smoothness does not establish detection accuracy; the old bands are provisional.

## Phase B — Luc's live trial (Luc + P2)

1. On this computer, open `http://127.0.0.1:8002/?tester=1`.
2. Select your actual input device and choose whether to consent to recording.
3. Follow the comet naturally; do not try to imitate the scoring rules.
4. Inspect the score and each feature. Repeat a few times, including one ordinary
   miss, then use the browser-check fallback and reserve a demo ticket.
5. Record what felt difficult: starting, speed, direction, finger occlusion or retry.

For raw local calibration recordings use the recorder below. Scoring alone does not
save a file; check consent and press **Save recording** only for a real human attempt.
Automation-created trails belong in synthetic tests, never human calibration data.

### Phone testing now: movement and scoring

The current Wi-Fi recorder address is:

**http://192.168.128.69:8004/dev/recorder**

- Put computer and phone on the same Wi-Fi and keep this computer awake.
- Select **Touchscreen**, press the comet, follow it for three seconds, inspect the
  feature table, then optionally consent and save.
- This private-LAN HTTP recorder does not run checkout or proof of work. It is for
  genuine touch recordings and motion feedback.
- If it cannot connect, the Wi-Fi may isolate devices or Windows Firewall may block
  inbound traffic. Try a trusted shared hotspot; do not disable the firewall globally.
- This address can change when Wi-Fi changes. Run `ipconfig` and use the Wi-Fi IPv4.

Restart the recorder from the repository root:

```powershell
.\.venv\Scripts\python.exe -m uvicorn engine.devserver:app --host 0.0.0.0 --port 8004
```

Binding to the LAN permits other devices on that network to reach the recorder.
Use localhost (`--host 127.0.0.1`) for desktop-only use.

### Phone testing of the complete ticket flow (P1)

Provide the team's existing HTTPS deployment URL. Use `https://<team-host>/?tester=1`
or its `/qr` page. Verify comet → score, Skip → PoW → reserve, and token reuse rejection.
Phone `127.0.0.1` addresses the phone itself. Plain `http://<computer-IP>` cannot be
assumed to support Web Crypto for the complete fallback flow.

## Phase C — calibrate with real evidence (P2)

- Collect fresh `smooth_v2` recordings across available devices. At least ten with
  each device represented is an initial checkpoint, not proof of general accuracy.
- Inspect per-device false rejections and collect held-out attempts before tuning.
- Preserve the 0.75 threshold for now. With four features, 0.70 accepts the same
  discrete scores; that change would not add margin.
- Keep strict gate improvement. If zero stored forgeries pass already, keep the
  active rule and gather new evidence. Do not force a second Blue activation.
- Changing path version is an operator/demo choice; Blue cannot change it as a rule.

The calibration loader treats missing path versions as `v1` and selects one
version at a time. Run `python -m engine.calibrate --path-version smooth_v2`.
Never silently relabel or discard legacy recordings to make a candidate pass.

## Phase D — deploy and show one honest Red/Blue cycle (P1 + P2)

P1 supplies the existing VM/app URL, database and storage readiness, and access via
ignored local configuration. Never post keys in PRs or chat. No duplicate VM is needed.

On the prepared VM, deploy the exact tested integrated commit:

```bash
RELEASE_REF=<reviewed-commit-sha> bash deploy.sh engine
```

After merge, `RELEASE_REF=origin/main bash deploy.sh engine` selects integrated main.
The script builds first, then replaces services and checks readiness. A failure after
container replacement can leave the new deployment unhealthy; inspect logs and redeploy
the last known-good pinned revision. It does not provide automatic rollback.

Verify `/healthz` reports the real engine and `smooth_v2`, plus the correct evidence
counts. Run the authenticated worker `--check-api`, then one bounded Red round and Blue
evaluation. A gate rejection is a valid result. Activation requires explicit approval
for that environment; earlier localhost approval does not authorize cloud activation.

P1 also verifies storage retention settings before promising a retention duration.
The app must not claim raw trails were uploaded when storage is unavailable.

## Phase E — compare with a conventional CAPTCHA (after the demo works)

Select one authorized conventional CAPTCHA baseline. Use the same people/devices,
alternate order, and record task completion time, success/retry counts and perceived
effort. Separate browser-check fallback outcomes from comet passes. Label tiny samples
as a pilot. The current PoW fallback is not an image-CAPTCHA benchmark.

Report observed user experience first. A pleasant motion demo or synthetic attack
score does not establish better bot detection. Expand the study only after the basic
demo and phone flow are reliable.

## Ownership and next handoff

- **P1:** existing HTTPS deployment and phone URL, database/storage configuration,
  real-phone checkout verification, review integration changes.
- **P2:** smooth motion/scoring parity, engine/agents, version-aware evidence,
  calibration report and fixed gate.
- **Luc:** real input trials and consent decisions; share the existing nonsecret
  deployment endpoint or coordinate with the teammate who provisioned it.

Next milestone: Luc completes a smooth attempt, sees understandable measurements,
and can reserve through either successful movement or the fallback. Do that before
expanding the comparison study or adding features.

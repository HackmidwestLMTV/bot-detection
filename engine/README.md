# Phase 1 engine kit

Local deterministic movement analysis and a consent-based recorder. No AI agents,
model connection, production deployment, or full lab API emulator are included yet.
Work is on the user-requested `p2` branch. Person 1's pre-merge deployment script
must use `origin/p2` instead of the guide's `origin/p2-engine` if it includes this work.

## Run on Windows (PowerShell, from the repository root)

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r engine/requirements-dev.txt
.\engine\prepare-recorder.ps1
.\.venv\Scripts\python.exe -m pytest contracts engine/tests -q
.\.venv\Scripts\python.exe -m uvicorn engine.devserver:app --host 127.0.0.1 --port 8000
```

Open http://127.0.0.1:8000/dev/recorder. Choose mouse, trackpad, or touchscreen,
select **New recording**, press the comet, and follow it for three seconds.
Keep touch/pen contact until the recording ends. Scoring does not write a file.
Check the consent box and select **Save recording** to save a genuine human trace
in `contracts/fixtures/human_traces/team_<unique-id>.json`.

The save includes `seed`, `samples`, `device`, `pointer_type`, `cohort: human_test`,
`round_id: null`, and `tester: {consent: true, nondominant_hand: ...}`. An unsaved
attempt expires after ten minutes or a server restart. Saved recordings persist.
Browser automation and generated traces must never be saved to this dataset.
Mouse versus trackpad cannot be inferred from pointer events; select it manually.

For a phone on the same trusted Wi-Fi, start with `--host 0.0.0.0` and visit
`http://<computer-LAN-IP>:8000/dev/recorder`. This is a development server without
authentication, so return to the localhost binding after local testing. The
production checkout's keyboard-accessible proof-of-work fallback is Person 1's
responsibility; this movement recorder requires a pointing device.

`prepare-recorder.ps1` copies the unchanged JavaScript path from the existing
`origin/p1-platform` remote-tracking branch and excludes only that local copy via
`.git/info/exclude`. It refuses to overwrite a different file. It does not fetch
or modify Person 1's branch. On another OS, obtain the same file with
`git show origin/p1-platform:web/static/path.js`, place it at `web/static/path.js`,
and add `/web/static/path.js` to `.git/info/exclude`.

## Integration interfaces

- `engine.path.make_path(seed)` returns `pos(t_ms) -> (x, y)` using the contract's
  exact unsigned 32-bit random arithmetic and 600 × 400 logical canvas.
- `engine.scorer.features(samples, seed)` returns five plain numerical features.
- `engine.scorer.score(samples, seed, variant)` returns the unchanged `ScoreResult`.
- `engine.scorer.score_features(values, variant)` also accepts the stored nested
  feature objects (`{"value": ..., ...}`) returned by Person 1's API.
- `engine.gate.gate(candidate, baseline, humans, forgeries)` returns the unchanged
  `GateResult`. Device groups are mouse, trackpad, and touch. Missing human or
  forgery evidence rejects review. An unrepresented device has no safety evidence;
  the gate makes no claim about it. Gate approval never activates a variant.
- `engine.forger.forge_trail(seed, lag_ms=0, noise_px=0, submove_hz=0, overshoot=0,
  rng_seed=None)` returns sample triples. Noise is seeded Gaussian noise per axis;
  corrections are a 2-pixel sine/cosine offset. Overshoot adds a fraction of the
  delayed path's preceding 100 ms displacement. Defaults follow the target exactly.
- `engine.forger.transplant(trace, seed)` transfers `trace.samples - old_target`
  onto the new target at the original timestamps. It preserves residuals without
  clamping. Neither forger function writes files.

## Feature definitions (provisional, not a trained detector)

Input is `[t_ms, x, y]` in logical pixels. Times must be finite, nonnegative, and
nondecreasing. Duplicate timestamps keep the last position. At least one second
of data is required. Coordinates must be finite. Linear interpolation produces
60 Hz samples starting at the first timestamp, stopping before the last if it
does not lie on the grid; there is no extrapolation of recorded movement.

| Feature | Exact method |
|---|---|
| `lag_ms` | Minimize mean squared 2D distance to the target delayed by 0–500 ms in 1/60-second increments. Use the same observations at times >= 500 ms for every candidate, with smaller lags winning ties. |
| `err_mean_px` | Mean Euclidean distance to the target at the same time, without lag correction. |
| `submoves_per_s` | Differentiate the smoothed trajectory; smooth its speed again. Count local speed maxima with prominence >= 10% of the total speed range, at least six samples (100 ms) apart. Keep higher peaks first and count plateaus once. Divide by resampled duration. |
| `jitter_px` | RMS Euclidean distance between the original resampled coordinates and their smoothed trajectory. |
| `power_law_beta` | Negative least-squares slope of log speed against log curvature, with curvature `abs(vx*ay-vy*ax)/speed^3`. Exclude four edge samples on either side, speed <= 1e-6, and curvature <= 1e-9. Return zero with <10 eligible points or log-curvature standard deviation <= 1e-6. |

Smoothing is a centered seven-sample moving average with replicated edges.
Derivatives use 1/60-second finite differences. All five features are computed;
only enabled features contribute to the score. Bands are inclusive, and the
score is the fraction of enabled features inside their bands. Passing means
`score >= pass_threshold`. Invalid variants and feature data raise `ValueError`.

Smoothing also responds to target geometry, so jitter and speed peaks do not
isolate human motor noise. The coefficient does not prove a movement is human.
The existing v1 bands are untouched, uncalibrated starting values. No claimed
human pass rate or tuned-forgery success rate follows from these synthetic tests.

## Local-only HTTP endpoints

| Endpoint | Behavior |
|---|---|
| `GET /healthz` | Recorder status and availability of the local path.js copy. |
| `GET /dev/recorder`, `GET /dev/path.js` | Recorder page and unchanged browser path code. |
| `POST /dev/challenges` | New random seed, challenge ID, three-second duration, 120-second expiration. |
| `POST /dev/attempts` | Accept challenge ID, samples, device, and pointer type; score once and retain the attempt in memory. Return attempt ID, result, and `saved: false`. |
| `POST /dev/recordings` | Accept attempt ID, literal boolean `consent: true`, and optional `nondominant_hand`. Save once; a repeated save returns the same filename. |

The recorder only accepts timestamps within the challenge's 0–3000 ms window
and at most 10,000 samples. A hidden page or cancelled pointer recording must
be restarted. Consent records the tester's declaration, not proof of human origin.

## Verification

Run `python -m pytest contracts engine/tests -q` using the virtual environment.
Node.js is needed for the existing browser-path parity test. The adapter test
reads `origin/p1-platform:web/engine_adapter.py` without modifying that branch.
Recorder API tests use temporary directories exclusively for synthetic traces.
The default pytest configuration also includes the engine tests and retains
`web/tests` for the eventual platform merge.

Next phase: validate Strands/model tool calling, then collect real recordings
and calibrate v1 before building Red and Blue around these heuristics.

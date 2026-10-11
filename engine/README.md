# Movement engine

Deterministic path generation, movement features, scoring, synthetic attacks, and
the fixed comparison gate. Agent operation is documented in
[OPERATIONS.md](OPERATIONS.md); sequence models in [ml/README.md](ml/README.md).

## Local calibration recorder

Install the dependencies from the root README, then run:

```bash
python -m uvicorn engine.devserver:app --host 127.0.0.1 --port 8004
```

Open `http://127.0.0.1:8004/dev/recorder`. Select the actual device, start a new
recording, and follow the ball for five seconds. Keep touch/pen contact until
the end. Scoring does not save a file. With explicit consent, **Save recording**
writes to `contracts/fixtures/human_traces/`. Browser automation and generated
traces must never be saved as human evidence. Local recorder files require
manual cleanup; the deployed research store has a separate 72-hour policy.

Current recordings use `roaming_v3` and `plain_ring_5s_v2`. Mouse/trackpad is a
participant selection, not something Pointer Events can identify. Prior path
and presentation cohorts remain separate. The visible ring is the start area;
there is no direction arrow or fading movement trail. See the
[path geometry](../contracts/ROAMING_PATH.md).

For supervised phone collection on trusted Wi-Fi, `bash scripts/collect.sh`
starts the recorder and prints its LAN URL and QR. This development recorder has
no authentication: stop it after the session. The deployed `/research` flow is
the route for enrolled, consented model-training data; local calibration files
are not accepted as ML research records.

Ask participants to follow naturally and keep unsuccessful attempts too. Do not
coach them to imitate a target score. Collect mouse, trackpad, and physical phone
touch separately; emulated touch is only a software input test.

## Audit calibration

```bash
python -m engine.calibrate --path-version roaming_v3 --presentation-version plain_ring_5s_v2
```

The read-only audit checks consent, device metadata, duplicates, cohort versions,
and samples. It prints provisional band suggestions, human rejections by device,
and perfect-target forgery results. It does not alter v1 or activate a variant.
Its small-sample readiness checks are not an accuracy estimate. Historical audits
must explicitly select the original path and presentation; never relabel evidence.

## Integration interfaces

- `engine.path.make_path(seed, path_version)` returns `pos(t_ms) -> (x, y)` using the contract's
  exact unsigned 32-bit random arithmetic and 600 × 400 logical canvas.
- `engine.scorer.features(samples, seed, path_version)` returns five plain numerical features.
- `engine.scorer.score(samples, seed, variant)` returns the unchanged `ScoreResult`.
- `engine.scorer.score_features(values, variant)` also accepts the stored nested
  feature objects (`{"value": ..., ...}`) returned by the API.
- `engine.gate.gate(candidate, baseline, humans, forgeries)` returns the unchanged
  `GateResult`. Device groups are mouse, trackpad, and touch. Missing human or
  forgery evidence rejects review. An unrepresented device has no safety evidence;
  the gate makes no claim about it. Gate approval never activates a variant.
- `engine.forger.forge_trail(seed, lag_ms=0, noise_px=0, submove_hz=0, overshoot=0,
  rng_seed=None, path_version="v1", duration_ms=5000)` returns sample triples.
  Pass the issued challenge's version and duration. Noise is seeded Gaussian noise per axis;
  corrections are a 2-pixel sine/cosine offset. Overshoot adds a fraction of the
  delayed path's preceding 100 ms displacement. Defaults follow the target exactly.
- `engine.forger.transplant(trace, seed, path_version)` transfers `trace.samples - old_target`
  onto the new target at the original timestamps. It preserves residuals without
  clamping. Neither forger function writes files.

Direct path/feature calls retain `v1` as their compatibility default; callers
must supply the issued version when processing current challenges.

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
| `GET /healthz` | Recorder status and availability of the shared path.js. |
| `GET /dev/recorder`, `GET /dev/path.js` | Recorder page and shared browser path code. |
| `POST /dev/challenges` | New random seed, challenge ID, five-second duration, 120-second expiration. |
| `POST /dev/attempts` | Accept challenge ID, samples, device, and pointer type; score once and retain the attempt in memory. Return attempt ID, result, and `saved: false`. |
| `POST /dev/recordings` | Accept attempt ID, literal boolean `consent: true`, and optional `nondominant_hand`. Save once; a repeated save returns the same filename. |

The recorder only accepts timestamps within the challenge's 0–5000 ms window
and at most 10,000 samples. A hidden page or cancelled pointer recording must
be restarted. Consent records the tester's declaration, not proof of human origin.

## Verification

Run `python -m pytest contracts engine/tests -q` with development dependencies.
Node.js is required for Python/JavaScript path parity. Recorder tests use
temporary directories for generated fixtures; integrated web tests require a
disposable PostgreSQL database. See the root README for the complete suite.

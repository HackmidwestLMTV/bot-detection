# Contract changelog

- 2026-10-11: Added optional operator-enrolled research collection (`research_sequence_v1`,
  `movement_training_v1`, `pointer_v2`) and header-only private research routes.
  Enrollment codes bind to a session; server-signed sequences expire in 72 hours.
  Public challenge/attempt responses remain unchanged without enrollment. Enrolled
  attempt responses add `research_recording=saved|storage_unavailable`. Optional
  `target_response_v1` models write shadow results only; activation is unavailable.
  See `engine/ml/README.md` for privacy, artifacts, grouped evaluation and limits.

- 2026-10-10: Added explicit `smooth_v2` target motion and separate fixtures. Missing `path_version` retains legacy `v1`; challenge rendering/scoring and saved evidence carry the issued version. Calibration isolates path cohorts. See `SMOOTH_PATH.md` for the function, bounds, and APIs.

One line per change after the 5:30 PM freeze. Person 2 commits; Person 1 cherry-picks.

- 2026-10-10 initial: contract + fixtures. `gate_example.json` uses `verdict: "reject"` (the contract example has trackpad 3 > baseline 0, so the rule rejects it). `path_vectors.json` adds seeds 7 and 4294967295 at 250 ms steps, generated from `web/static/path.js` and cross-checked against an independent Python implementation.
# Plain-ring demo presentation — 2026-10-10

- Challenges add `presentation_version=plain_ring_v1`; attempts and consented
  recordings persist the server-issued display identity. Missing historical
  metadata means `legacy`, never current display evidence.
- Human/forgery listings add presentation metadata and filter both path and display.
  Approval fingerprints include display identity. Scoring uses a challenge's
  issued policy snapshot; activation changes newly issued challenges only.
- `/qr` opens checkout; `/qr/tester` opens the existing consent-based tester flow.
- Ball/ring rendering removes arrows and motion trails without changing paths.
- Tester/recorder submissions confirm the issued display; cached or incompatible
  clients cannot add current human evidence. Static entrypoints carry a display
  cache key. This handshake does not attest browser authenticity.

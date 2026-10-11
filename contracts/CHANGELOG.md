# Contract changelog

- 2026-10-10: Added explicit `smooth_v2` target motion and separate fixtures. Missing `path_version` retains legacy `v1`; challenge rendering/scoring and saved evidence carry the issued version. Calibration isolates path cohorts. See `SMOOTH_PATH.md` for the function, bounds, and APIs.

One line per change after the 5:30 PM freeze. Person 2 commits; Person 1 cherry-picks.

- 2026-10-10 initial: contract + fixtures. `gate_example.json` uses `verdict: "reject"` (the contract example has trackpad 3 > baseline 0, so the rule rejects it). `path_vectors.json` adds seeds 7 and 4294967295 at 250 ms steps, generated from `web/static/path.js` and cross-checked against an independent Python implementation.

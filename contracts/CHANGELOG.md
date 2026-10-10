# Contract changelog

One line per change after the 5:30 PM freeze. Person 2 commits; Person 1 cherry-picks.

- 2026-10-10 initial: contract + fixtures. `gate_example.json` uses `verdict: "reject"` (the contract example has trackpad 3 > baseline 0, so the rule rejects it). `path_vectors.json` adds seeds 7 and 4294967295 at 250 ms steps, generated from `web/static/path.js` and cross-checked against an independent Python implementation.

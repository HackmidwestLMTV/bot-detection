# Phase 1: Follow It engine kit

- [x] Inspect contracts, preserve local edits, and create user-requested `p2` branch.
- [x] Create Python 3.12 environment and install engine/test dependencies.
- [x] Implement deterministic path, movement features/scoring, forger, and gate.
- [x] Implement consent-based local recorder using Person 1's unchanged path.js.
- [x] Verify contracts, numerical behavior, recorder, and platform adapter integration.
- [x] Document startup, feature definitions, limitations, and verification results.

## Decisions

- Build in `engine/`; preserve the shared function signatures and JSON shapes.
- Use branch `p2` (user override of the guide's `p2-engine`). Deployment must use `p2` if integrated before merge.
- AI agents, the full lab emulator, deployment, and human calibration are later phases.
- Original bands are provisional. Synthetic checks establish software behavior, not detection accuracy.
- Finish and verify each phase, then wait for the user's explicit approval before committing. Do not auto-commit or push.

## Review

- Implemented path parity, five explicit numerical features, configurable scoring,
  repeatable forgeries, error transplantation, evidence gate, and local recorder.
- Python 3.12: `python -m pytest -q` -> 47 passed. `python -m pip check` -> no broken requirements.
- Existing JavaScript and Python contract-vector checks pass; the platform adapter imports the real functions.
- Browser smoke test completed a three-second attempt and displayed the feature table with Save disabled until consent.
- Synthetic save tests used temporary directories; no human calibration recordings were created.
- One upstream deprecation warning remains: Starlette's TestClient warns about its httpx integration. Tests succeed.
- Startup and feature definitions are documented in `engine/README.md`. Human calibration, actual phone testing, AI agents, and production deployment remain later work.
- Original `.gitignore` edit and local planning documents were preserved. Local-only path.js is excluded through `.git/info/exclude`.
- Phase 1 commit explicitly approved by the user. Stage only the verified Phase 1 kit; preserve unrelated local edits and subsequent recordings.

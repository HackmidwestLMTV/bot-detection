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

# Phase 2: Strands integration

- [x] Implement bounded provider configuration, SDK hooks, and synthetic smoke checks.
- [x] Verify offline SDK behavior and run the live Akamai checks.
- [x] Complete regression checks and documentation (see `tasks/phase2.md`).
- [x] User explicitly approved committing Phase 2.

## Phase 2 review

- Phase 1 committed as `ed1ff1e`. Phase 2 verified and approved for a separate commit.
- 58 tests passed and dependencies are consistent. Live Akamai checks passed in
  12 model calls; no application variants were activated.
- Worker implementation, human calibration, and deployment remain later phases.

# Phase 3: Human calibration and local Red rounds

- [x] Audit consented recordings and implement a reproducible percentile calibration report.
- [x] Add a separate local lab emulator for Red's contract endpoints.
- [x] Build a scoped HTTP client, budgeted Red tools, and one-round worker command.
- [x] Verify tool budgets, event shapes, evidence counts, and local HTTP integration offline.
- [x] Run a bounded live-model Red round against the local emulator.
- [x] Document setup and evidence; leave the phase uncommitted for approval.
- [ ] Complete calibration with at least 10 real recordings covering mouse, trackpad, and touch.

## Phase 3 decisions

- The user authorized the next phase after committing Phase 2 (`147eac6`).
- Keep the existing recorder available on port 8000; use a separate Red lab on port 8001.
- Preserve shared v1 until evidence supports calibration; emit a candidate and per-device diagnostics locally.
- Red receives scores and summary values only. Transplantation reads consented team
  traces locally and never sends their samples to the model.
- Blue approval flows and live deployment remain subsequent work.

## Phase 3 review (calibration evidence pending)

- Full suite: 67 tests passed. `pip check`: no broken requirements.
- Offline tests cover percentile calculations, missing/invalid/duplicate evidence,
  lab authentication, red-only submissions, expiry, evidence ID lookup, budgets,
  round-3 transplant availability, and correction of fabricated model report counts.
- Latest calibration audit: nine valid recordings (eight mouse, one trackpad,
  zero touch). Candidate accepts all nine; perfect-target baseline fails all nine
  recorded seeds. Shared v1 remains unchanged while touch evidence is pending.
- Live Akamai round completed with seven attempts, four passes, and eight model
  calls: `run_9652f0e3d25f4d599f60c4e1caf14f8d`. Naive score was 0.25; tuned attempts
  reached 0.75. The successful typed report and seven stored IDs agree.
- Earlier live runs failed during report completion; the diagnosed root cause was
  APITimeoutError. An explicit 60-second worker request timeout allowed the final
  run to complete. Phase 2's 30-second smoke default remains unchanged.
- Implementation and commands are documented in `engine/PHASE3.md`.
- Phase 3 is uncommitted; no push was performed. Calibration still needs touch
  evidence and at least 10 recordings before a shared-band change is considered.

# Finish Person 2 (user authorized)

- [x] Extend the disposable lab with variants, gate, approval enforcement, human feature summaries, commands, and events.
- [x] Implement Blue tools, fixed budgets, fresh-gate approval interruption, and bounded dashboard-decision polling.
- [x] Implement a persistent worker command loop with Red/Blue dispatch, round progression, duplicate-run protection, and clean shutdown.
- [x] Add engine-owned container/integration support and check compatibility with Person 1's current branch.
- [x] Verify full Red → Blue → gate → approve/deny flows, including stale evidence and missing evidence failures.
- [x] Run bounded live model integration, audit calibration, and document the precise remaining external dependencies.
- [ ] Validate against Person 1's running test API and a Docker/Postgres environment when available.

## Person 2 completion review

- 79 engine/worker tests and 3 current Person 1 adapter tests pass; pip check is clean.
- Live Blue candidate `blue_4f03c00120594d7d82ce98e9ba05aa3b` was explicitly
  approved by the user for the disposable localhost lab and activated there.
  Forgery passes decreased 9/16 to 6/16; mouse rejections stayed 1/8 and trackpad
  rejections stayed 0/1. Touch remains untested, with nine total human recordings.
- The original model summary timed out after successful activation. A labeled
  report was recovered from server events. The SDK now stops after activation
  and builds its report from observed facts; regression tests verify no extra call.
- Local recorder, lab, and queue worker remain available. No new runs were queued
  during the final checks. No production variants were changed.
- Person 1's `180122a` routes and real-engine adapter are compatible. Full DB and
  container tests remain unrun because Docker/Postgres and a test API are unavailable.
  Person 1 must bind activation approval atomically to fresh gate evidence server-side;
  our worker and disposable lab enforce checks on their own paths.
- See `engine/OPERATIONS.md` for handoff, deployment helper, limits, and replay evidence.
  All current changes remain uncommitted; todo and phase notes are outside future commit scope.

## Current instructions

- Person 2 only; the temporary Person 1 selection was explicitly corrected.
- Do not include todo or phase documentation files in future commits. Existing
  committed history is unchanged; all new code also awaits commit approval.
- Do not replace real evidence with synthetic recordings or approve real variants
  automatically. Approval tests use disposable local state.

# Cross-team completion goal

- [x] Locate teammate PR #1 and inspect current p1-platform and p2 heads.
- [x] Reproduce the stuck proof-of-work worker and submit actionable review feedback.
- [x] Create engine PR #2 and request teammate review.
- [x] Resolve platform review blockers and merge after the user's direct-fix instruction.
- [x] Build and visually verify a shared ticket/lab design system for Hack Midwest.
- [x] Validate integrated engine, browser flows, and database-backed API behavior.
- [ ] Validate Akamai deployment with a real endpoint; collect missing touch calibration.
- [ ] Recheck both PR discussions, address feedback, and merge agreed changes.

User authorized GitHub review discussion, PR creation, and merges after agreement.
Platform fixes requested from teammate; visual changes will use an isolated branch.

## Integrated review progress

- Teammate PR #1 reviewed, directly fixed with three agents, verified and merged as b6d572c.
- Shared visual system rendered on desktop and 390 px phone layouts; real browser
  skip -> PoW -> reservation -> reused-token rejection verified against PostgreSQL18.
- Combined suite: 172 Python passed, 2 expected skips; 12 frontend tests passed.
- Engine PR #2 opened, teammate review requested, no response at last check.
- Merged main into p2 with both .gitignore entries retained.
- User says the teammate already set up Akamai. Reuse that infrastructure once its
  role and public endpoint are confirmed; no cloud resources have been created.
- CI exposed an adapter test tied to an unfetched remote branch. It now tests the
  checked-out adapter; the focused test passes. Full CI and image builds pending.

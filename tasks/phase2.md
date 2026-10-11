# Phase 2: Verify Strands and model integration

- [x] Install the guide's Strands 1.59 / OpenAI 2.x combination and inspect actual SDK interfaces.
- [x] Add explicit Akamai/Bedrock configuration, bounded model calls, and request pacing.
- [x] Add a smoke harness for one real tool call, three structured reports, tool denial, and approval interrupt/resume.
- [x] Test the SDK integration offline with simulated provider responses, without credentials or network calls.
- [x] Run the live model smoke test when credentials are configured; report provider evidence separately from offline tests.
- [x] Document results, provider selection, and remaining limitations.
- [x] User explicitly approved committing Phase 2 before starting the next phase.

## Boundaries

- Preserve user-recorded human traces and do not transmit them to the model.
- Smoke tools only manipulate in-memory test counters. No real variants activate.
- Red, Blue, the lab worker, and deployment remain outside this integration-validation phase.
- User reported that model configuration is ready; validate it without printing secrets before the live run.
- Phase 2 commit is explicitly approved; no push was requested.

## Review

- Phase 1 committed separately as `ed1ff1e` on `p2`.
- Full regression suite: 58 passed; dependency check: no broken requirements.
- Live Akamai smoke run passed all five checks in 12 model calls, including
  three structured reports and both approval decisions. Bedrock was not needed
  and remains unverified against a live account.
- Fixed an observed HTTP 400 by omitting empty tool fields from Akamai requests;
  an offline regression assertion protects this behavior.
- Setup, limits, and verification evidence are in `engine/agents/README.md`.
- Credentials are in ignored `.env`; no human recordings were transmitted.

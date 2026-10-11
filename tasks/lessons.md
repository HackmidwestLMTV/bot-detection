# Phase 1 lessons

## Lesson: Preserve consent boundaries during testing
Synthetic recorder tests must inject a temporary output directory. Browser smoke
tests may score automation-generated input but must never save it as human evidence.

## Lesson: Windows Store Python may require runtime permission
The installed Python 3.12 interpreter and virtual environment launcher require
elevated tool execution in this workspace. Use the approved project environment;
do not silently switch the project to the default Python 3.14 interpreter.

## Lesson: Clear interactive state before awaiting a score
Once a recording ends, clear its active challenge before making the asynchronous
score request so another pointer-down cannot start an overlapping recording.

## Lesson: Phase completion does not authorize a commit
The user requested approval after each phase before committing. Keep completed
changes uncommitted, report verification, and wait for that explicit approval.

## Lesson: Test the provider's actual wire format

An OpenAI-compatible endpoint can reject optional fields that the SDK sends.
Akamai rejected `tools: []`. Omit empty tool fields in the provider adapter and
assert this in an offline HTTP transport test before rerunning live checks.

## Lesson: Structured output can finish through a schema tool

Strands 1.59 may return `tool_use` when it has already produced validated
structured output. Check the typed report and expected facts; do not require
`end_turn` for this path. Ordinary tool loops must still finish their turn.

## Lesson: Do not assume TestClient and SDK response classes are identical

Starlette can use httpx2 while the model SDK uses httpx. Convert the test server's
response explicitly when bridging it into an httpx MockTransport; otherwise a
valid synchronous response can produce a misleading async-handler TypeError.

## Lesson: Derive round evidence from executed tools

Model-generated counts and evidence IDs can be incorrect even in a valid typed
report. Build final counts, best parameters, and evidence from recorded tool
results; retain generated prose only as commentary.

## Lesson: Short smoke checks do not establish round latency

The provider completed the short Phase 2 smoke suite but a multi-tool Red round
timed out when finishing its report. Record the underlying exception type, test
an explicit bounded worker timeout, and verify full-round completion separately.

## Lesson: Do not require a model summary after successful activation

The live Blue tool activated its approved candidate, but the next model call timed
out while summarizing it. Stop the SDK loop after confirmed activation and build
the final report from observed actions. Keep historical errors visible when a
report is recovered from server evidence.

## Lesson: Client approval checks do not replace atomic server enforcement

A worker can verify the gate and evidence before activation, but the server must
bind and consume approval atomically to protect direct callers and concurrent
changes. Report that integration gap rather than claiming deployment validation.

## Lesson: Integration tests must inspect the checked-out code

Do not read an integrated component from a remote Git branch in a test. Shallow
CI checkouts may lack that ref, and a moving branch does not represent the code
under review. Read the component from the current checkout.

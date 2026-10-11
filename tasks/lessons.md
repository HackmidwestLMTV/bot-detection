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

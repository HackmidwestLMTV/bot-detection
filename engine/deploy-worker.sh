#!/usr/bin/env bash
# Run from Person 1's prepared VM checkout, after the reviewed p2 commit is pushed.
# Copies only engine/; shared contract changes require a separate coordinated merge.
set -euo pipefail
test -f compose.yaml && test -f web/app.py
git fetch origin
git archive "${ENGINE_REF:-origin/p2}" engine | tar -x
docker compose -f compose.yaml -f engine/compose.worker.yaml --profile engine config --quiet
docker compose -f compose.yaml -f engine/compose.worker.yaml --profile engine up -d --build app worker
for attempt in {1..30}; do
  if docker compose -f compose.yaml -f engine/compose.worker.yaml --profile engine exec -T worker python -m engine.worker --check-api; then
    exit 0
  fi
  sleep 2
done
echo 'Worker could not reach the platform API within 60 seconds.' >&2
exit 1

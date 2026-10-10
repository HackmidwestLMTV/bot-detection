#!/usr/bin/env bash
# Run ON THE VM. Deploy-time integration: p1-platform + latest engine/ from p2-engine. Nothing gets committed.
#   ./deploy.sh            before 11 PM (p1-platform only)
#   ./deploy.sh engine     from 11 PM (copies engine/ + contracts/ from p2-engine, starts the worker)
set -e
cd ~/followit && git fetch origin && git checkout -B deploy origin/p1-platform
if [ "$1" = "engine" ]; then
  rm -rf engine && git archive origin/p2-engine engine contracts | tar -x   # Person 2's latest engine + contract
  docker compose --profile engine up -d --build
else
  docker compose up -d --build app caddy
fi
sleep 3
docker compose logs --tail 50 app | grep -E "using (real engine|stubs)" || echo "WARN: adapter log line not found"

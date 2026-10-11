#!/usr/bin/env bash
# Run ON THE VM. Deploy-time integration: p1-platform + latest engine/ from p2-engine. Nothing gets committed.
#   ./deploy.sh            before 11 PM (p1-platform only)
#   ./deploy.sh engine     from 11 PM (copies engine/ + contracts/ from p2-engine, starts the worker)
#   BRANCH=main ./deploy.sh   after the final merge
set -e
cd ~/followit && git fetch origin
# -f + clean: a previous `engine` deploy left engine/ and Person 2's contracts/ in the tree
#   (rm before checkout, so a branch that tracks engine/, like main, gets it restored)
rm -rf engine && git checkout -f -B deploy "origin/${BRANCH:-p1-platform}"
if [ "$1" = "engine" ]; then
  git archive origin/p2-engine engine contracts | tar -x   # Person 2's latest engine + contract
  docker compose --profile engine up -d --build
else
  docker compose up -d --build app caddy
fi
sleep 4
docker compose logs --tail 50 app | grep -E "using (real engine|stubs)" || echo "WARN: adapter log line not found"
curl -fsS http://localhost:8000/healthz && echo
grep -E '^DOMAIN=' .env | sed 's|DOMAIN=|live at https://|'

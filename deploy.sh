#!/usr/bin/env bash
# ON THE VM: bash ~/followit/deploy.sh [engine]
# BRANCH=main selects the reviewed merged platform; ENGINE_REF defaults to origin/p2.
set -euo pipefail
umask 077
mode="${1:-platform}"
case "$mode" in platform|engine) ;; *) echo 'Usage: bash deploy.sh [engine]' >&2; exit 2 ;; esac
FOLLOWIT_DIR="${FOLLOWIT_DIR:-$HOME/followit}"
cd "$FOLLOWIT_DIR"
test -s .env || { echo 'Run vm_setup.sh and configure .env first.' >&2; exit 1; }
git fetch origin
platform_ref="origin/${BRANCH:-p1-platform}"
git rev-parse --verify "$platform_ref^{commit}" >/dev/null
if [ "$mode" = engine ]; then
  git cat-file -e "${ENGINE_REF:-origin/p2}:engine/Dockerfile"
fi

# Isolated snapshots preserve the operator's branch and uncommitted work.
release_root="${FOLLOWIT_RELEASES:-$HOME/.local/share/followit/releases}"
mkdir -p "$release_root"
release=$(mktemp -d "$release_root/release.XXXXXXXX")
echo "Deployment snapshot: $release"
if [ "$mode" = engine ]; then
  git archive "$platform_ref" | tar --exclude=engine -x -C "$release"
  git archive "${ENGINE_REF:-origin/p2}" engine | tar -x -C "$release"
else
  git archive "$platform_ref" | tar -x -C "$release"
fi
ln -s "$FOLLOWIT_DIR/.env" "$release/.env"
cd "$release"
compose=(docker compose --project-name followit)
if [ "$mode" = engine ]; then compose+=(--profile engine); fi
"${compose[@]}" config --quiet
services=(app caddy)
if [ "$mode" = engine ]; then services+=(worker); fi
# Build before replacing running containers so a failed build leaves them intact.
"${compose[@]}" build "${services[@]}"
if [ "$mode" = platform ]; then "${compose[@]}" --profile engine stop worker; fi
"${compose[@]}" up -d --wait --wait-timeout 120 "${services[@]}"
if [ "$mode" = engine ]; then
  "${compose[@]}" exec -T worker python -m engine.worker --check-api
fi
curl -fsS http://127.0.0.1:8000/healthz
echo
grep -E '^DOMAIN=' .env | sed 's|DOMAIN=|Live at https://|'

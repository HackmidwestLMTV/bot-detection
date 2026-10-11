#!/usr/bin/env bash
# ON THE VM: bash ~/followit/deploy.sh [engine]
# RELEASE_REF selects one reviewed integrated revision (default origin/main).
# ENGINE_REF is an optional, explicit engine-only override for integration testing.
set -euo pipefail
umask 077
mode="${1:-platform}"
case "$mode" in platform|engine) ;; *) echo 'Usage: bash deploy.sh [engine]' >&2; exit 2 ;; esac
FOLLOWIT_DIR="${FOLLOWIT_DIR:-$HOME/followit}"
cd "$FOLLOWIT_DIR"
test -s .env || { echo 'Run vm_setup.sh and configure .env first.' >&2; exit 1; }
git fetch origin
if [ -n "${RELEASE_REF:-}" ] && [ -n "${BRANCH:-}" ]; then
  echo 'Set RELEASE_REF or the legacy BRANCH override, not both.' >&2
  exit 2
fi
release_ref="${RELEASE_REF:-origin/${BRANCH:-main}}"
# Resolve once: all files come from the same immutable revision even if a ref moves.
release_commit=$(git rev-parse --verify --end-of-options "$release_ref^{commit}")
git cat-file -e "$release_commit:compose.yaml"
git cat-file -e "$release_commit:web/app.py"
if [ "$mode" = engine ]; then
  engine_commit="$release_commit"
  if [ -n "${ENGINE_REF:-}" ]; then
    engine_commit=$(git rev-parse --verify --end-of-options "$ENGINE_REF^{commit}")
  fi
  git cat-file -e "$engine_commit:engine/Dockerfile"
elif [ -n "${ENGINE_REF:-}" ]; then
  echo 'ENGINE_REF requires engine mode.' >&2
  exit 2
fi

# Isolated snapshots preserve the operator's branch and uncommitted work.
release_root="${FOLLOWIT_RELEASES:-$HOME/.local/share/followit/releases}"
mkdir -p "$release_root"
release=$(mktemp -d "$release_root/release.XXXXXXXX")
echo "Deployment snapshot: $release"
if [ "$mode" = engine ] && [ "$engine_commit" != "$release_commit" ]; then
  git archive "$release_commit" | tar --exclude=engine -x -C "$release"
  git archive "$engine_commit" engine | tar -x -C "$release"
else
  git archive "$release_commit" | tar -x -C "$release"
fi
printf 'release_ref=%s\nrelease_commit=%s\nengine_commit=%s\n' \
  "$release_ref" "$release_commit" "${engine_commit:-disabled}" > "$release/release-info.txt"
cat "$release/release-info.txt"
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

#!/usr/bin/env bash
# Run on a fresh Ubuntu 24.04 Linode as root: bash vm_setup.sh
set -euo pipefail
umask 077
REPO="${REPO:-https://github.com/HackmidwestLMTV/bot-detection.git}"
if [ -n "${RELEASE_REF:-}" ] && [ -n "${BRANCH:-}" ]; then
  echo 'Set RELEASE_REF or the legacy BRANCH override, not both.' >&2
  exit 2
fi
release_ref="${RELEASE_REF:-origin/${BRANCH:-p2}}"
FOLLOWIT_DIR="${FOLLOWIT_DIR:-$HOME/followit}"

# Docker engine + compose plugin
if ! command -v docker >/dev/null; then curl -fsSL https://get.docker.com | sh; fi
docker compose version

# The Linode Cloud Firewall must also allow TCP 22, 80 and 443.
if command -v ufw >/dev/null; then
  ufw allow 22/tcp
  ufw allow 80/tcp
  ufw allow 443/tcp
  # Supersede the old bootstrap's public 8000 allow rule, if present.
  ufw insert 1 deny 8000/tcp
  ufw --force enable
fi

# Private repos need a deploy key. Existing operator checkouts stay on their branch.
fresh_checkout=0
if [ ! -d "$FOLLOWIT_DIR/.git" ]; then
  git clone "$REPO" "$FOLLOWIT_DIR"
  fresh_checkout=1
fi
cd "$FOLLOWIT_DIR"
git fetch origin
release_commit=$(git rev-parse --verify --end-of-options "$release_ref^{commit}")
git cat-file -e "$release_commit:deploy.sh"
git cat-file -e "$release_commit:.env.example"
if [ "$fresh_checkout" = 1 ]; then git checkout --detach "$release_commit"; fi

# .env with a fresh LAB_KEY and the sslip.io domain for this VM's public IP
if [ ! -f .env ]; then
  if [ -z "${DOMAIN:-}" ]; then
    IP=$(curl -fsS https://ifconfig.me)
    [[ "$IP" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]] || { echo 'Set DOMAIN explicitly when public IPv4 discovery is unavailable.' >&2; exit 1; }
    DOMAIN="${IP//./-}.sslip.io"
  fi
  [[ "$DOMAIN" =~ ^[a-zA-Z0-9.-]+$ ]] || { echo 'DOMAIN must be a hostname.' >&2; exit 1; }
  env_tmp=$(mktemp .env.tmp.XXXXXX)
  trap 'rm -f -- "$env_tmp"' EXIT
  lab_key=$(openssl rand -hex 32)
  # Read the selected remote template even if an existing checkout is on main.
  git show "$release_commit:.env.example" | sed -e "s|^LAB_KEY=.*|LAB_KEY=$lab_key|" \
      -e "s|^DOMAIN=.*|DOMAIN=$DOMAIN|" \
      -e "s|^PUBLIC_URL=.*|PUBLIC_URL=https://$DOMAIN|" \
      -e "s|^API_BASE=.*|API_BASE=http://app:8000|" > "$env_tmp"
  test -s "$env_tmp"
  chmod 600 "$env_tmp"
  mv -- "$env_tmp" .env
  trap - EXIT
  echo "Wrote $FOLLOWIT_DIR/.env for https://$DOMAIN"
fi
echo
echo "Edit $FOLLOWIT_DIR/.env: DATABASE_URL, S3_KEY, S3_SECRET and AKAMAI_API_KEY."
echo "Allow this VM's IP in Managed Postgres, then run: RELEASE_REF=$release_commit bash $FOLLOWIT_DIR/deploy.sh engine"
echo 'Keep LAB_KEY private; retrieve it from .env only when setting up the lab dashboard.'

#!/usr/bin/env bash
# Run on a fresh Ubuntu 24.04 Linode as root: bash vm_setup.sh
set -euo pipefail
umask 077
REPO="${REPO:-https://github.com/HackmidwestLMTV/bot-detection.git}"
BRANCH="${BRANCH:-p1-platform}"
FOLLOWIT_DIR="${FOLLOWIT_DIR:-$HOME/followit}"

# Docker engine + compose plugin
if ! command -v docker >/dev/null; then curl -fsSL https://get.docker.com | sh; fi
docker compose version

# The Linode Cloud Firewall must also allow TCP 22, 80 and 443.
if command -v ufw >/dev/null; then
  ufw allow 22/tcp
  ufw allow 80/tcp
  ufw allow 443/tcp
  ufw --force enable
fi

# main may contain only contracts before integration. Private repos need a deploy key.
if [ ! -d "$FOLLOWIT_DIR/.git" ]; then git clone --branch "$BRANCH" "$REPO" "$FOLLOWIT_DIR"; fi
cd "$FOLLOWIT_DIR"
git fetch origin

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
  git show "origin/$BRANCH:.env.example" | sed -e "s|^LAB_KEY=.*|LAB_KEY=$lab_key|" \
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
echo "Allow this VM's IP in Managed Postgres, then run: bash $FOLLOWIT_DIR/deploy.sh engine"
echo 'Keep LAB_KEY private; retrieve it from .env only when setting up the lab dashboard.'

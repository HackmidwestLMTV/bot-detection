#!/usr/bin/env bash
# One-time setup ON A FRESH Ubuntu 24.04 Linode (run as root):
#   curl -fsSL https://raw.githubusercontent.com/HackmidwestLMTV/bot-detection/p1-platform/vm_setup.sh | bash
#   (private repo? scp this file over and run `bash vm_setup.sh` instead)
# Then: fill in ~/followit/.env and run ~/followit/deploy.sh
set -euo pipefail
REPO="${REPO:-https://github.com/HackmidwestLMTV/bot-detection.git}"

# Docker engine + compose plugin
if ! command -v docker >/dev/null; then curl -fsSL https://get.docker.com | sh; fi
docker compose version

# Host firewall (the Linode Cloud Firewall must ALSO allow TCP 80 and 443; the kit only opens 22 and 8000)
if command -v ufw >/dev/null; then
  ufw allow 22/tcp && ufw allow 80/tcp && ufw allow 443/tcp && ufw allow 8000/tcp && ufw --force enable
fi

# Code (private repo: use https://<user>:<token>@github.com/... or a deploy key)
if [ ! -d ~/followit/.git ]; then git clone "$REPO" ~/followit; fi
cd ~/followit && git fetch origin

# .env with a fresh LAB_KEY and the sslip.io domain for this VM's public IP
if [ ! -f .env ]; then
  IP=$(curl -fsS https://ifconfig.me || hostname -I | awk '{print $1}')
  DOMAIN="${IP//./-}.sslip.io"
  sed -e "s|^LAB_KEY=.*|LAB_KEY=$(openssl rand -hex 16)|" \
      -e "s|^DOMAIN=.*|DOMAIN=$DOMAIN|" \
      -e "s|^PUBLIC_URL=.*|PUBLIC_URL=https://$DOMAIN|" \
      -e "s|^API_BASE=.*|API_BASE=http://app:8000|" .env.example > .env
  chmod 600 .env
  echo "Wrote ~/followit/.env for https://$DOMAIN"
fi
echo
echo "Next: edit ~/followit/.env  (DATABASE_URL, S3_KEY, S3_SECRET, AKAMAI_API_KEY), add this VM's IP"
echo "to the Managed Postgres allow list, then run:  ~/followit/deploy.sh"
grep -E '^(DOMAIN|LAB_KEY)=' .env

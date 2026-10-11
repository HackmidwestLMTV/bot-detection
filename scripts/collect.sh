#!/usr/bin/env bash
# One command for a real-movement collection session.
#
#   bash scripts/collect.sh
#
# Starts the local movement recorder (the files engine/calibrate.py reads) and, when a
# database and operator key are configured, the website so /research can hand out invites
# and watch recordings land. Prints the LAN addresses plus a scannable QR for the phone.
#
# Env: BIND (default 0.0.0.0), RECORDER_PORT (8004), APP_PORT (8002), LAN_IP,
#      PYTHON, TRACES_DIR, DATABASE_URL, LAB_KEY, RESEARCH_RECORDINGS_DIR, POW_BITS.
set -euo pipefail
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

BIND="${BIND:-0.0.0.0}"
RECORDER_PORT="${RECORDER_PORT:-8004}"
APP_PORT="${APP_PORT:-8002}"
PYTHON="${PYTHON:-}"
if [ -z "$PYTHON" ]; then
  for candidate in .venv/bin/python .venv/Scripts/python.exe python3; do
    if command -v "$candidate" >/dev/null 2>&1 || [ -x "$candidate" ]; then PYTHON="$candidate"; break; fi
  done
fi
"$PYTHON" -c 'import fastapi, uvicorn, segno' >/dev/null 2>&1 \
  || { echo "No usable Python environment. Create the venv and install requirements, or set PYTHON=." >&2; exit 1; }

# ---- LAN address: what a phone on the same wi-fi can actually reach ----
lan_ip() {
  if [ -n "${LAN_IP:-}" ]; then printf '%s' "$LAN_IP"; return; fi
  local ip=""
  if command -v ipconfig >/dev/null 2>&1; then
    for interface in en0 en1 en2; do
      ip=$(ipconfig getifaddr "$interface" 2>/dev/null || true)
      [ -n "$ip" ] && break
    done
  fi
  if [ -z "$ip" ] && command -v ip >/dev/null 2>&1; then
    ip=$(ip -4 route get 1.1.1.1 2>/dev/null | sed -n 's/.* src \([0-9.]*\).*/\1/p' | head -1)
  fi
  if [ -z "$ip" ] && command -v hostname >/dev/null 2>&1; then
    ip=$(hostname -I 2>/dev/null | awk '{print $1}')
  fi
  printf '%s' "$ip"
}
IP=$(lan_ip)
HOSTPART="${IP:-127.0.0.1}"
if [ -z "$IP" ]; then
  echo "Could not detect a LAN address; printing localhost only. Set LAN_IP=<wi-fi IPv4> to share." >&2
fi
if [ "$BIND" = "127.0.0.1" ]; then HOSTPART="127.0.0.1"; fi

pids=()
cleanup() {
  trap - INT TERM EXIT
  for pid in "${pids[@]:-}"; do [ -n "$pid" ] && kill "$pid" 2>/dev/null || true; done
  wait 2>/dev/null || true
  echo
  echo "Collection session stopped. Saved traces and recordings are kept."
}
trap cleanup INT TERM EXIT

wait_health() {   # url label
  for _ in $(seq 1 60); do
    if curl -fsS --max-time 2 "$1" >/dev/null 2>&1; then return 0; fi
    sleep 0.5
  done
  echo "$2 did not become healthy; see its log above." >&2
  return 1
}

# ---- 1. the recorder: writes the trace files engine/calibrate.py reads ----
TRACES_DIR="${TRACES_DIR:-contracts/fixtures/human_traces}"
if [ "$TRACES_DIR" = "contracts/fixtures/human_traces" ]; then
  RECORDER_APP="engine.devserver:app"
else
  mkdir -p "$TRACES_DIR"
  export TRACES_DIR
  RECORDER_APP="scripts.recorder_app:app"
fi
"$PYTHON" -m uvicorn "$RECORDER_APP" --host "$BIND" --port "$RECORDER_PORT" &
pids+=("$!")
wait_health "http://127.0.0.1:$RECORDER_PORT/healthz" "The recorder"
RECORDER_URL="http://$HOSTPART:$RECORDER_PORT/dev/recorder"

# ---- 2. the website: research invites, the operator console, checkout ----
APP_URL=""
LAB_KEY="${LAB_KEY:-}"
if [ -n "${DATABASE_URL:-}" ] && [ "${#LAB_KEY}" -ge 16 ]; then
  export RESEARCH_RECORDINGS_DIR="${RESEARCH_RECORDINGS_DIR:-$PWD/research-data}"
  mkdir -p "$RESEARCH_RECORDINGS_DIR"
  chmod 700 "$RESEARCH_RECORDINGS_DIR" 2>/dev/null || true
  export POW_BITS="${POW_BITS:-16}"
  "$PYTHON" -m uvicorn web.app:app --host "$BIND" --port "$APP_PORT" &
  pids+=("$!")
  wait_health "http://127.0.0.1:$APP_PORT/healthz" "The website"
  APP_URL="http://$HOSTPART:$APP_PORT"
fi

rule() { printf '%s\n' "----------------------------------------------------------------------"; }
echo
rule
echo "COLLECTION SESSION — real human movement only"
rule
echo
echo "PHONE / LAPTOP RECORDER   $RECORDER_URL"
echo "  Saves to $TRACES_DIR — this is what 'python -m engine.calibrate' reads."
echo "  Device, consent and Save recording are the volunteer's choices, on their screen."
echo
"$PYTHON" - "$RECORDER_URL" <<'PY'
import sys
import segno
segno.make(sys.argv[1], error="m").terminal(compact=True)
PY
echo
if [ -n "$APP_URL" ]; then
  echo "WEBSITE                   $APP_URL/?tester=1"
  echo "  Operator console        $APP_URL/research       (needs your LAB_KEY; keep it off shared screens)"
  echo "  QR page for a screen    $APP_URL/qr/tester"
  echo "  Invite recordings land in $RESEARCH_RECORDINGS_DIR (72-hour retention)."
  echo "  Those signed envelopes train models; they are NOT the files engine.calibrate reads."
else
  echo "WEBSITE                   not started."
  echo "  Set DATABASE_URL and a LAB_KEY of at least 16 characters to run the invite flow,"
  echo "  the /research console and checkout. The recorder above needs neither."
fi
echo
rule
echo "PLAIN HTTP OVER THE LAN IS FOR RECORDING ONLY — NOT CHECKOUT."
echo "  Browsers expose crypto.subtle only on HTTPS or localhost, so the proof-of-work"
echo "  fallback cannot complete over http://$HOSTPART. Movement, scoring and saving work;"
echo "  Skip-the-game -> reserve does not. Demo full checkout on the HTTPS deployment or on"
echo "  127.0.0.1 on this machine."
rule
echo
if [ "$BIND" = "0.0.0.0" ]; then
  echo "Bound to 0.0.0.0: every device on this network can reach these ports. Use BIND=127.0.0.1"
  echo "for desktop-only collection. If a phone cannot connect, the wi-fi may isolate clients or"
  echo "a host firewall may block inbound traffic — try a shared hotspot, and remove any temporary"
  echo "firewall rule when you finish. Keep this machine awake."
  echo
fi
echo "Count what you have collected (run here, in another terminal):"
echo "  $PYTHON -c \"import collections,glob,json;t=[json.load(open(f)) for f in glob.glob('$TRACES_DIR/*.json')];c=collections.Counter(x['device'] for x in t if x.get('path_version')=='smooth_v2');print(sum(c.values()),dict(c))\""
echo
echo "Check the set is usable (reads only; changes no bands):"
echo "  $PYTHON -m engine.calibrate --path-version smooth_v2 --traces $TRACES_DIR"
echo
echo "Ctrl-C stops both servers. reviews/collection-guide.md has the words to say."
wait

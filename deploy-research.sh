#!/usr/bin/env bash
# Run inside a reviewed, versioned release on the existing Follow It VM.
# Uses private VM disk; does not enable paid Object Storage or activate a model.
set -euo pipefail
umask 077
release=$(pwd -P)
case "$release" in /root/followit/releases/*) ;; *) echo 'Run from /root/followit/releases/<reviewed-release>'; exit 2;; esac
test -s .env
test -f compose.research.yaml
app_id=$(docker ps -q --filter label=com.docker.compose.project=followit --filter label=com.docker.compose.service=app)
test -n "$app_id"
test "$(echo "$app_id" | wc -l)" -eq 1
old_image=$(docker inspect -f '{{.Image}}' "$app_id")
old_release=$(docker inspect -f '{{index .Config.Labels "com.docker.compose.project.working_dir"}}' "$app_id")
curl -fsS http://127.0.0.1:8000/healthz > baseline-health.json
rollback_tag="followit-app:before-research-$(date -u +%Y%m%d%H%M%S)"
docker tag "$old_image" "$rollback_tag"
printf 'services:\n  app:\n    image: %s\n' "$rollback_tag" > rollback-image.yaml
printf 'previous_release=%s\nprevious_image=%s\nrollback_tag=%s\n' "$old_release" "$old_image" "$rollback_tag" > deployment-info.txt
install -d -m 700 /root/followit/research /root/followit/research/recordings /root/followit/research/models
compose=(docker compose -p followit -f compose.yaml -f compose.research.yaml)
"${compose[@]}" config --quiet
"${compose[@]}" build app

# Independent of the app process, so an app outage/rollback does not stop raw-file expiry.
cat > /etc/systemd/system/followit-research-retention.service <<'UNIT'
[Unit]
Description=Expire Follow It private raw recordings after 72 hours
[Service]
Type=oneshot
ExecStart=/usr/bin/find /root/followit/research/recordings -maxdepth 1 -type f -name *.json -mmin +4320 -delete
NoNewPrivileges=true
ProtectSystem=strict
ReadWritePaths=/root/followit/research/recordings
UNIT
cat > /etc/systemd/system/followit-research-retention.timer <<'UNIT'
[Unit]
Description=Check Follow It raw recording expiry each minute
[Timer]
OnBootSec=1min
OnUnitActiveSec=1min
AccuracySec=1s
Persistent=true
[Install]
WantedBy=timers.target
UNIT
systemctl daemon-reload
systemctl enable --now followit-research-retention.timer

rollback() {
  echo 'Research release failed verification; restoring the previous app image.' >&2
  "${compose[@]}" -f rollback-image.yaml up -d --no-deps --no-build --wait --wait-timeout 120 app
}
trap rollback ERR
"${compose[@]}" up -d --no-deps --wait --wait-timeout 120 app
"${compose[@]}" exec -T app python - <<'PY'
import json, os, pathlib, stat, time, urllib.request, uuid
from web import config, db, research
assert not config.SHADOW_MODEL_DIR, 'First collection release must await genuine-data artifacts'
root = pathlib.Path(config.RESEARCH_RECORDINGS_DIR)
assert root.is_dir() and stat.S_IMODE(root.stat().st_mode) == 0o700
probe = root / ('deployment_probe_' + uuid.uuid4().hex + '.json')
try:
    with os.fdopen(os.open(probe, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), 'w') as f:
        f.write('{"test_fixture":true,"purpose":"storage expiry probe; no human data"}')
    os.utime(probe, (time.time()-73*3600, time.time()-73*3600))
    db.open_pool()
    try:
        research.cleanup()
    finally:
        db.close_pool()
    assert not probe.exists(), 'expired probe was not removed'
finally:
    probe.unlink(missing_ok=True)
request = urllib.request.Request('http://127.0.0.1:8000/v1/research/status', headers={'X-Lab-Key': config.LAB_KEY})
status = json.load(urllib.request.urlopen(request, timeout=10))
assert status['storage_configured'] and not status['activation_available']
assert status['mode'] == 'shadow_only' and status['model_status'] == 'awaiting_real_training_data'
health = json.load(urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=10))
baseline = json.loads(pathlib.Path('/srv/baseline-health.json').read_text())
assert health['active_variant'] == baseline['active_variant']
assert health['engine'] == 'real' and health['presentation_version'] == 'plain_ring_v1'
print(json.dumps({'health':health, 'research':status, 'storage_write_and_expiry':'passed'}))
PY
systemctl is-active followit-research-retention.timer
trap - ERR
printf 'Research release ready: %s\n' "$release"

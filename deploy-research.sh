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
worker_id=$(docker ps -q --filter label=com.docker.compose.project=followit --filter label=com.docker.compose.service=worker)
test -n "$app_id"
test -n "$worker_id"
test "$(echo "$app_id" | wc -l)" -eq 1
test "$(echo "$worker_id" | wc -l)" -eq 1
old_image=$(docker inspect -f '{{.Image}}' "$app_id")
old_worker_image=$(docker inspect -f '{{.Image}}' "$worker_id")
old_release=$(docker inspect -f '{{index .Config.Labels "com.docker.compose.project.working_dir"}}' "$app_id")
old_worker_release=$(docker inspect -f '{{index .Config.Labels "com.docker.compose.project.working_dir"}}' "$worker_id")
test -f "$old_release/compose.yaml"
test -f "$old_worker_release/compose.yaml"
# Old settings stay untouched. Only this fresh release opts into wider motion.
test "$release" != "$old_release"
test "$release" != "$old_worker_release"
python3 - <<'PY'
from pathlib import Path
path = Path('.env')
lines = path.read_text().splitlines()
lines = [line for line in lines if not line.lstrip().startswith(('PATH_VERSION=', 'export PATH_VERSION='))]
path.write_text('\n'.join(lines + ['PATH_VERSION=roaming_v3', '']))
PY
stamp=$(date -u +%Y%m%d%H%M%S)
rollback_tag="followit-app:before-research-$stamp"
rollback_worker_tag="followit-worker:before-research-$stamp"
docker tag "$old_image" "$rollback_tag"
docker tag "$old_worker_image" "$rollback_worker_tag"
printf 'services:\n  app:\n    image: %s\n  worker:\n    image: %s\n' "$rollback_tag" "$rollback_worker_tag" > rollback-image.yaml
printf 'previous_release=%s\nprevious_worker_release=%s\nprevious_image=%s\nprevious_worker_image=%s\nrollback_tag=%s\nrollback_worker_tag=%s\n' "$old_release" "$old_worker_release" "$old_image" "$old_worker_image" "$rollback_tag" "$rollback_worker_tag" > deployment-info.txt
install -d -m 700 /root/followit/research /root/followit/research/recordings /root/followit/research/models
compose=(docker compose --env-file "$release/.env" -p followit --profile engine -f compose.yaml -f compose.research.yaml)
"${compose[@]}" config --quiet
"${compose[@]}" build app worker

# A lab command remains 'running' in PostgreSQL after it finishes; the durable
# worker journal is the completion authority. Do not interrupt a live agent or
# an operator's recent approval window just to deploy a UI change.
deadline=$((SECONDS + 600))
while :; do
  running=$(docker exec -i "$worker_id" python - <<'PY'
import os, pathlib, sqlite3
path = pathlib.Path(os.environ['WORKER_STATE_PATH'])
if path.exists():
    with sqlite3.connect(path.as_uri() + '?mode=ro', uri=True) as conn:
        print(conn.execute("SELECT count(*) FROM runs WHERE status='running'").fetchone()[0])
else:
    print(0)
PY
)
  waiting=$(docker exec -i "$app_id" python - <<'PY'
from web import db
db.open_pool()
try:
    queued = db.one("SELECT count(*) AS n FROM lab_commands WHERE status='queued'")['n']
    pending = db.one("""SELECT count(*) AS n FROM approvals a WHERE a.status='pending'
        AND EXISTS (SELECT 1 FROM lab_events e WHERE e.body->>'type'='approval_needed'
          AND e.body->'data'->>'approval_id'=a.id AND e.created_at > now() - interval '30 minutes')""")['n']
    print(queued + pending)
finally:
    db.close_pool()
PY
)
  if test "$running" -eq 0 && test "$waiting" -eq 0; then break; fi
  if test "$SECONDS" -ge "$deadline"; then
    echo 'Lab is busy or awaiting approval; no application containers were changed. Retry after it finishes.' >&2
    exit 3
  fi
  echo "Waiting for lab work to finish (running=$running, queued/recent approvals=$waiting)."
  sleep 5
done
curl -fsS http://127.0.0.1:8000/healthz > baseline-health.json
docker exec -i "$app_id" python - > baseline-state.json <<'PY'
import hashlib, json
from web import config, db
db.open_pool()
try:
    humans = db.one("SELECT count(*) AS n FROM attempts WHERE cohort='human_test'")['n']
finally:
    db.close_pool()
print(json.dumps({'human_attempts': humans,
                  'lab_key_sha256': hashlib.sha256(config.LAB_KEY.encode()).hexdigest()}))
PY

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
  trap - ERR
  echo 'Research release failed verification; restoring previous app and worker images and settings.' >&2
  "${compose[@]}" stop worker || true
  old_app=(docker compose --env-file "$old_release/.env" --project-directory "$old_release" -p followit -f "$old_release/compose.yaml")
  old_worker=(docker compose --env-file "$old_worker_release/.env" --project-directory "$old_worker_release" -p followit --profile engine -f "$old_worker_release/compose.yaml")
  if test -f "$old_release/compose.research.yaml"; then old_app+=(-f "$old_release/compose.research.yaml"); fi
  if test -f "$old_worker_release/compose.research.yaml"; then old_worker+=(-f "$old_worker_release/compose.research.yaml"); fi
  "${old_app[@]}" -f "$release/rollback-image.yaml" up -d --no-deps --no-build --wait --wait-timeout 120 app
  "${old_worker[@]}" -f "$release/rollback-image.yaml" up -d --no-deps --no-build --wait --wait-timeout 120 worker
}
trap rollback ERR
# Stop the old generator before changing challenge metadata; preserve its durable queue.
"${compose[@]}" stop worker
"${compose[@]}" up -d --no-deps --wait --wait-timeout 120 app
"${compose[@]}" cp baseline-health.json app:/srv/baseline-health.json
"${compose[@]}" cp baseline-state.json app:/srv/baseline-state.json
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
assert health['engine'] == 'real' and health['presentation_version'] == config.PRESENTATION_VERSION
assert health['path_version'] == config.PATH_VERSION == 'roaming_v3'
assert config.DURATION_MS == 5000
print(json.dumps({'health':health, 'research':status, 'storage_write_and_expiry':'passed'}))
PY
"${compose[@]}" up -d --no-deps --wait --wait-timeout 120 worker
# The worker can inspect current rules/evidence without queuing an attack or making a model call.
"${compose[@]}" exec -T worker python -m engine.worker --check-api
"${compose[@]}" exec -T worker python - <<'PY'
from contracts.presentation import DURATION_MS, PRESENTATION_VERSION
from engine.path import make_path
assert DURATION_MS == 5000 and PRESENTATION_VERSION == 'plain_ring_5s_v2'
assert len(make_path(1, 'roaming_v3')(5000)) == 2
print('Worker supports the same five-second roaming path.')
PY
"${compose[@]}" exec -T app python verify-research-live.py
systemctl is-active followit-research-retention.timer
trap - ERR
printf 'Research release ready: %s\n' "$release"

"""Read-only release verification, run inside the deployed app container."""
import hashlib
import fnmatch
import json
from pathlib import Path
import urllib.error
import urllib.request
from web import config, db

root = Path('/srv')
manifest = json.loads((root / 'source-manifest.json').read_text())
# These planning docs are explicitly excluded by the app's .dockerignore.
files = {name: digest for name, digest in manifest['files'].items()
         if not any(fnmatch.fnmatchcase(Path(name).name, pattern) for pattern in ('PHASE*.md', 'phase*.md'))}
changed = [name for name, digest in files.items()
           if hashlib.sha256((root / name).read_bytes()).hexdigest() != digest]
assert not changed, changed
request = urllib.request.Request('http://127.0.0.1:8000/v1/research/status', headers={'X-Lab-Key': config.LAB_KEY})
status = json.load(urllib.request.urlopen(request, timeout=10))
assert status['storage_configured'] and status['mode'] == 'shadow_only'
assert not status['shadow_configured'] and not status['activation_available']
for path in ('/.env', '/static/.env', '/var/lib/followit/research/'):
    try:
        urllib.request.urlopen('http://127.0.0.1:8000' + path, timeout=10)
        raise AssertionError('private path unexpectedly served')
    except urllib.error.HTTPError as exc:
        assert exc.code == 404
db.open_pool()
try:
    ordinary_raw = db.one("SELECT count(*) AS n FROM attempts WHERE cohort='organic' AND trail_key IS NOT NULL")['n']
    active = db.all("SELECT id FROM variants WHERE status='active'")
finally:
    db.close_pool()
assert ordinary_raw == 0 and active == [{'id':'v1'}]
print(json.dumps({'release':manifest['release'], 'source_files_verified':len(files),
                  'ordinary_raw_recordings':ordinary_raw, 'active_policy':active[0]['id'],
                  'research':status, 'private_http_paths':'not served'}))

"""Build a code-only deployment snapshot; never include secrets or human recordings."""
import hashlib
import io
import json
from pathlib import Path
import tarfile

root = Path(__file__).resolve().parents[1]
output = root / 'release-artifacts' / 'followit-research-collection.tar.gz'
files = []
for folder in ('web', 'engine', 'contracts'):
    for path in (root / folder).rglob('*'):
        rel = path.relative_to(root)
        if (path.is_file() and not any(p.startswith('.') or p in {'__pycache__', 'tests', 'human_traces', 'recordings'} for p in rel.parts)
                and (path.suffix in {'.py', '.js', '.html', '.css', '.sql', '.txt', '.md', '.json'}
                     or path.name in {'Dockerfile', 'Dockerfile.dockerignore'})):
            files.append(path)
for name in ('Dockerfile', '.dockerignore', 'compose.yaml', 'compose.research.yaml', 'Caddyfile', 'deploy-research.sh'):
    files.append(root / name)
manifest = {str(p.relative_to(root)).replace('\\', '/'): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(files)}
with tarfile.open(output, 'w:gz') as archive:
    for path in files:
        archive.add(path, arcname=str(path.relative_to(root)).replace('\\', '/'))
    body = json.dumps({'release':'research-collection-20261011-r2', 'files':manifest}, indent=2).encode()
    info = tarfile.TarInfo('source-manifest.json'); info.size = len(body); info.mode = 0o600
    archive.addfile(info, io.BytesIO(body))
print(json.dumps({'archive':str(output), 'files':len(files), 'bytes':output.stat().st_size,
                  'sha256':hashlib.sha256(output.read_bytes()).hexdigest()}))

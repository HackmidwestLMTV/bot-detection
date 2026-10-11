"""Package the reviewed working tree as LF code only, never credentials or recordings."""
import argparse
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import re
import tarfile

ROOT = Path(__file__).resolve().parents[1]
TEXT_SUFFIXES = {".py", ".js", ".html", ".css", ".sql", ".txt", ".md", ".json", ".yaml", ".sh"}
FORBIDDEN_PARTS = {"__pycache__", "tests", "human_traces", "human-traces", "recordings"}


def package(release, output):
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,79}", release):
        raise ValueError("release must be a short lowercase directory name")
    files = {}
    for folder in ("web", "engine", "contracts"):
        for path in (ROOT / folder).rglob("*"):
            rel = path.relative_to(ROOT)
            if not path.is_file() or path.is_symlink():
                continue
            if any(part.startswith(".") or part in FORBIDDEN_PARTS for part in rel.parts):
                continue
            if path.suffix in TEXT_SUFFIXES | {".woff2"} or path.name in {"Dockerfile", "Dockerfile.dockerignore"}:
                files[rel.as_posix()] = path
    for name in ("Dockerfile", ".dockerignore", "compose.yaml", "compose.research.yaml", "Caddyfile", "deploy-research.sh"):
        files[name] = ROOT / name
    files["verify-research-live.py"] = ROOT / "release-artifacts" / "verify-research-live.py"
    manifest = {}
    output.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(output, "w:gz") as archive:
        for name, path in sorted(files.items()):
            body = path.read_bytes()
            # Windows checkouts may use CRLF; Bash and Docker receive exact LF bytes.
            if path.suffix != ".woff2":
                body = body.replace(b"\r\n", b"\n")
            manifest[name] = hashlib.sha256(body).hexdigest()
            info = tarfile.TarInfo(name)
            info.size, info.mode = len(body), 0o644
            archive.addfile(info, io.BytesIO(body))
        body = json.dumps({"release": release, "files": manifest}, indent=2).encode()
        info = tarfile.TarInfo("source-manifest.json")
        info.size, info.mode = len(body), 0o600
        archive.addfile(info, io.BytesIO(body))
    return {"release": release, "archive": str(output), "files": len(files),
            "bytes": output.stat().st_size, "sha256": hashlib.sha256(output.read_bytes()).hexdigest()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release", default="followit-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ").lower())
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    output = args.output or ROOT / "release-artifacts" / (args.release + ".tar.gz")
    print(json.dumps(package(args.release, output)))


if __name__ == "__main__":
    main()

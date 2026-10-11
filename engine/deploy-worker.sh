#!/usr/bin/env bash
# Compatibility entry point; the root deploy script owns release snapshots and readiness.
set -euo pipefail
repo_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
exec bash "$repo_root/deploy.sh" engine

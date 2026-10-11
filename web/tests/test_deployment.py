"""Execute deployment control flow with local command doubles; no VM or Docker needed."""
import os
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[2]
BASH = next((str(p) for p in (
    Path(r"C:\Program Files\Git\bin\bash.exe"),
    Path(shutil.which("bash") or "/bin/bash"),
) if p.is_file()), None)


@pytest.fixture
def deployment(tmp_path):
    if not BASH:
        pytest.skip("Bash is required for deployment script tests")
    commands = tmp_path / "commands"
    commands.mkdir()
    template = tmp_path / "template"
    template.write_text("LAB_KEY=placeholder\nDOMAIN=localhost\nPUBLIC_URL=https://localhost\nAPI_BASE=localhost\n")
    platform = tmp_path / "platform"
    platform.mkdir()
    (platform / "compose.yaml").write_text("services: {}\n")
    engine = tmp_path / "engine-source" / "engine"
    engine.mkdir(parents=True)
    (engine / "Dockerfile").write_text("FROM python:3.12-slim\n")
    scripts = {
        "git": '''#!/usr/bin/env bash
set -eu
echo "git $*" >> "$MOCK_LOG"
case "$1" in
  clone) mkdir -p "${@: -1}/.git" ;;
  show) [ "${MOCK_FAIL_TEMPLATE:-0}" = 0 ]; cat "$MOCK_TEMPLATE" ;;
  archive)
    if [ "$2" = origin/p2 ]; then tar -cf - -C "$MOCK_ENGINE" engine;
    else tar -cf - -C "$MOCK_PLATFORM" .; fi ;;
esac
''',
        "docker": '''#!/usr/bin/env bash
echo "docker $*" >> "$MOCK_LOG"
case " $* " in *" build "*) [ "${MOCK_FAIL_BUILD:-0}" = 0 ] ;; esac
''',
        "curl": '#!/usr/bin/env bash\necho "{\\"ok\\":true}"\n',
        "openssl": '#!/usr/bin/env bash\nprintf "test-private-lab-key\\n"\n',
        "ufw": '#!/usr/bin/env bash\nexit 0\n',
    }
    for name, script in scripts.items():
        command = commands / name
        command.write_text(script, newline="\n")
        command.chmod(0o755)
    env = os.environ.copy()
    env.update({
        "PATH": str(commands) + os.pathsep + env["PATH"],
        "FOLLOWIT_DIR": (tmp_path / "checkout").as_posix(),
        "FOLLOWIT_RELEASES": (tmp_path / "releases").as_posix(),
        "DOMAIN": "followit.example", "BRANCH": "p1-platform",
        "MOCK_LOG": (tmp_path / "commands.log").as_posix(),
        "MOCK_TEMPLATE": template.as_posix(),
        "MOCK_PLATFORM": platform.as_posix(),
        "MOCK_ENGINE": engine.parent.as_posix(),
        "MOCK_COMMANDS": ("/" + commands.drive[0].lower() + commands.as_posix()[2:]
                          if os.name == "nt" else str(commands)),
    })

    def run(script, *args):
        # Git Bash prepends its own bin directory during startup; override afterwards.
        return subprocess.run([BASH, "-c", 'export PATH="$MOCK_COMMANDS:$PATH"; exec bash "$@"',
                               "test-deploy", str(ROOT / script), *args], env=env,
                              capture_output=True, text=True, timeout=30)
    return env, run


def test_setup_selects_platform_and_keeps_secret_private(deployment):
    env, run = deployment
    result = run("vm_setup.sh")
    assert result.returncode == 0, result.stderr
    saved = Path(env["FOLLOWIT_DIR"]) / ".env"
    assert "LAB_KEY=test-private-lab-key" in saved.read_text()
    assert "test-private-lab-key" not in result.stdout + result.stderr
    log = Path(env["MOCK_LOG"]).read_text()
    assert "clone --branch p1-platform" in log
    assert "show origin/p1-platform:.env.example" in log
    saved.write_text("LAB_KEY=existing\n")
    assert run("vm_setup.sh").returncode == 0
    assert saved.read_text() == "LAB_KEY=existing\n"


def test_setup_failure_does_not_leave_partial_env(deployment):
    env, run = deployment
    env["MOCK_FAIL_TEMPLATE"] = "1"
    result = run("vm_setup.sh")
    assert result.returncode != 0
    checkout = Path(env["FOLLOWIT_DIR"])
    assert not (checkout / ".env").exists()
    assert not list(checkout.glob(".env.tmp.*"))


@pytest.mark.parametrize("mode", [None, "engine"])
def test_deploy_preserves_checkout_and_checks_readiness(deployment, mode):
    env, run = deployment
    assert run("vm_setup.sh").returncode == 0
    local = Path(env["FOLLOWIT_DIR"]) / "local-work.txt"
    local.write_text("keep my changes")
    result = run("deploy.sh", *([mode] if mode else []))
    assert result.returncode == 0, result.stderr
    assert local.read_text() == "keep my changes"
    log = Path(env["MOCK_LOG"]).read_text()
    assert "checkout" not in log.replace(env["FOLLOWIT_DIR"], "")
    assert "--wait --wait-timeout 120" in log
    assert "--project-name followit" in log
    if mode:
        assert "archive origin/p2 engine" in log
        assert "python -m engine.worker --check-api" in log
    else:
        assert "--profile engine stop worker" in log
    assert "test-private-lab-key" not in result.stdout + result.stderr


def test_failed_build_does_not_replace_running_services(deployment):
    env, run = deployment
    assert run("vm_setup.sh").returncode == 0
    env["MOCK_FAIL_BUILD"] = "1"
    result = run("deploy.sh", "engine")
    assert result.returncode != 0
    log = Path(env["MOCK_LOG"]).read_text()
    assert " up " not in log
    assert " stop " not in log

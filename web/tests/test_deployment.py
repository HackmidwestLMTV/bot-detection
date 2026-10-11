"""Execute deployment control flow with local command doubles; no VM or Docker needed."""
import os
from pathlib import Path
import shutil
import shlex
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[2]
INTEGRATED_COMMIT = "1" * 40
PLATFORM_COMMIT = "2" * 40
ENGINE_COMMIT = "3" * 40
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
    (platform / "web").mkdir()
    (platform / "web" / "lab.js").write_text("old platform UI")
    integrated = tmp_path / "integrated"
    shutil.copytree(platform, integrated)
    (integrated / "web" / "lab.js").write_text("reviewed p2 approval reload fix")
    (integrated / "engine").mkdir()
    (integrated / "engine" / "Dockerfile").write_text("integrated engine")
    (integrated / "engine" / "removed-by-overlay.txt").write_text("old engine file")
    engine = tmp_path / "engine-source" / "engine"
    engine.mkdir(parents=True)
    (engine / "Dockerfile").write_text("FROM python:3.12-slim\n")
    scripts = {
        "git": '''#!/usr/bin/env bash
set -eu
echo "git $*" >> "$MOCK_LOG"
case "$1" in
  clone) mkdir -p "${@: -1}/.git" ;;
  rev-parse)
    case "${@: -1}" in
      origin/main*|1111111111111111111111111111111111111111*) printf '%s\\n' 1111111111111111111111111111111111111111 ;;
      origin/p1-platform*) printf '%s\\n' 2222222222222222222222222222222222222222 ;;
      origin/engine-test*) printf '%s\\n' 3333333333333333333333333333333333333333 ;;
      *) exit 128 ;;
    esac ;;
  show) [ "${MOCK_FAIL_TEMPLATE:-0}" = 0 ]; cat "$MOCK_TEMPLATE" ;;
  archive)
    case "$2" in
      1111111111111111111111111111111111111111) tar -cf - -C "$MOCK_INTEGRATED" web engine compose.yaml ;;
      2222222222222222222222222222222222222222) tar -cf - -C "$MOCK_PLATFORM" web compose.yaml ;;
      3333333333333333333333333333333333333333) tar -cf - -C "$MOCK_ENGINE" engine ;;
      *) exit 128 ;;
    esac ;;
esac
''',
        "docker": '''#!/usr/bin/env bash
echo "docker $*" >> "$MOCK_LOG"
case " $* " in *" build "*) [ "${MOCK_FAIL_BUILD:-0}" = 0 ] ;; esac
''',
        "curl": '#!/usr/bin/env bash\necho "{\\"ok\\":true}"\n',
        "openssl": '#!/usr/bin/env bash\nprintf "test-private-lab-key\\n"\n',
        "ufw": '#!/usr/bin/env bash\necho "ufw $*" >> "$MOCK_LOG"\n',
    }
    for name, script in scripts.items():
        command = commands / name
        command.write_text(script, newline="\n")
        command.chmod(0o755)
    env = os.environ.copy()
    for name in ("BRANCH", "RELEASE_REF", "ENGINE_REF"):
        env.pop(name, None)
    env.update({
        "PATH": str(commands) + os.pathsep + env["PATH"],
        "FOLLOWIT_DIR": (tmp_path / "checkout").as_posix(),
        "FOLLOWIT_RELEASES": (tmp_path / "releases").as_posix(),
        "DOMAIN": "followit.example",
        "MOCK_LOG": (tmp_path / "commands.log").as_posix(),
        "MOCK_TEMPLATE": template.as_posix(),
        "MOCK_PLATFORM": platform.as_posix(),
        "MOCK_INTEGRATED": integrated.as_posix(),
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


def test_setup_selects_integrated_revision_and_keeps_secret_private(deployment):
    env, run = deployment
    result = run("vm_setup.sh")
    assert result.returncode == 0, result.stderr
    saved = Path(env["FOLLOWIT_DIR"]) / ".env"
    assert "LAB_KEY=test-private-lab-key" in saved.read_text()
    assert "test-private-lab-key" not in result.stdout + result.stderr
    log = Path(env["MOCK_LOG"]).read_text()
    assert f"checkout --detach {INTEGRATED_COMMIT}" in log
    assert f"show {INTEGRATED_COMMIT}:.env.example" in log
    assert "ufw insert 1 deny 8000/tcp" in log
    saved.write_text("LAB_KEY=existing\n")
    assert run("vm_setup.sh").returncode == 0
    assert saved.read_text() == "LAB_KEY=existing\n"
    assert Path(env["MOCK_LOG"]).read_text().count("checkout --detach") == 1


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
    Path(env["MOCK_LOG"]).write_text("")
    result = run("deploy.sh", *([mode] if mode else []))
    assert result.returncode == 0, result.stderr
    assert local.read_text() == "keep my changes"
    log = Path(env["MOCK_LOG"]).read_text()
    assert "git checkout" not in log
    assert "--wait --wait-timeout 120" in log
    assert "--project-name followit" in log
    if mode:
        assert f"archive {INTEGRATED_COMMIT}\n" in log
        assert "python -m engine.worker --check-api" in log
    else:
        assert "--profile engine stop worker" in log
    assert "test-private-lab-key" not in result.stdout + result.stderr
    release = next(Path(env["FOLLOWIT_RELEASES"]).glob("release.*"))
    assert (release / "web" / "lab.js").read_text() == "reviewed p2 approval reload fix"
    assert (release / "engine" / "Dockerfile").read_text() == "integrated engine"
    assert f"release_commit={INTEGRATED_COMMIT}" in (release / "release-info.txt").read_text()


def test_failed_build_does_not_replace_running_services(deployment):
    env, run = deployment
    assert run("vm_setup.sh").returncode == 0
    env["MOCK_FAIL_BUILD"] = "1"
    result = run("deploy.sh", "engine")
    assert result.returncode != 0
    log = Path(env["MOCK_LOG"]).read_text()
    assert " up " not in log
    assert " stop " not in log


@pytest.mark.parametrize("ref", ["origin/main", INTEGRATED_COMMIT])
def test_explicit_reviewed_release_uses_one_revision(deployment, ref):
    env, run = deployment
    env["RELEASE_REF"] = ref
    assert run("vm_setup.sh").returncode == 0
    result = run("deploy.sh", "engine")
    assert result.returncode == 0, result.stderr
    release = next(Path(env["FOLLOWIT_RELEASES"]).glob("release.*"))
    manifest = (release / "release-info.txt").read_text()
    assert f"release_ref={ref}" in manifest
    assert f"release_commit={INTEGRATED_COMMIT}" in manifest
    assert f"engine_commit={INTEGRATED_COMMIT}" in manifest


def test_explicit_engine_overlay_keeps_reviewed_web_and_removes_old_engine(deployment):
    env, run = deployment
    assert run("vm_setup.sh").returncode == 0
    env["ENGINE_REF"] = "origin/engine-test"
    result = run("deploy.sh", "engine")
    assert result.returncode == 0, result.stderr
    release = next(Path(env["FOLLOWIT_RELEASES"]).glob("release.*"))
    assert (release / "web" / "lab.js").read_text() == "reviewed p2 approval reload fix"
    assert (release / "engine" / "Dockerfile").read_text() == "FROM python:3.12-slim\n"
    assert not (release / "engine" / "removed-by-overlay.txt").exists()
    assert f"engine_commit={ENGINE_COMMIT}" in (release / "release-info.txt").read_text()


@pytest.mark.parametrize("overrides", [
    {"RELEASE_REF": "missing-ref"},
    {"RELEASE_REF": "origin/main", "BRANCH": "p2"},
])
def test_invalid_or_ambiguous_release_cannot_replace_containers(deployment, overrides):
    env, run = deployment
    assert run("vm_setup.sh").returncode == 0
    env.update(overrides)
    Path(env["MOCK_LOG"]).write_text("")
    result = run("deploy.sh", "engine")
    assert result.returncode != 0
    assert "docker " not in Path(env["MOCK_LOG"]).read_text()


def test_proxy_trust_requires_private_app_and_overwritten_client_header():
    compose = (ROOT / "compose.yaml").read_text()
    caddy = (ROOT / "Caddyfile").read_text()
    assert '"127.0.0.1:8000:8000"' in compose
    assert '"8000:8000"' not in compose
    assert "--proxy-headers" in compose
    assert "--forwarded-allow-ips" in compose
    command = next(line.partition("command:")[2] for line in compose.splitlines()
                   if "command: uvicorn " in line)
    arguments = shlex.split(command)
    trusted = arguments[arguments.index("--forwarded-allow-ips") + 1].split(",")
    assert "*" not in trusted
    assert set(trusted) == {"127.0.0.1", "::1", "10.0.0.0/8", "172.16.0.0/12",
                            "192.168.0.0/16", "fc00::/7"}
    assert "header_up X-Forwarded-For {remote_host}" in caddy

"""The container readiness check must retry transient failures and retain crash logs."""

import os
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "web_smoke.sh"


@pytest.mark.parametrize(
    "scenario,successful,health_calls",
    [
        ("reset_then_ready", True, 2),
        ("crash", False, 0),
        ("never_ready", False, 30),
        ("bad_callback", False, 1),
    ],
)
def test_web_readiness_and_failure_diagnostics(tmp_path, scenario, successful, health_calls):
    binary = tmp_path / "bin"
    binary.mkdir()
    log = tmp_path / "commands"
    for name, body in {
        "docker": """#!/bin/sh
printf '%s\\n' "docker $*" >> "$SMOKE_LOG"
case "$1" in
  run) echo container-id ;;
  inspect)
    case "$3" in
      *Running*) [ "$SMOKE_SCENARIO" != crash ] && echo true || echo false ;;
      *) echo '{"Status":"exited","ExitCode":1}' ;;
    esac ;;
  logs) echo 'Container startup diagnostics' ;;
esac
""",
        "curl": """#!/bin/sh
printf '%s\\n' "curl $*" >> "$SMOKE_LOG"
case "$*" in
  *healthz*)
    count=0
    [ ! -f "$SMOKE_COUNT" ] || count=$(cat "$SMOKE_COUNT")
    count=$((count + 1)); echo "$count" > "$SMOKE_COUNT"
    if [ "$SMOKE_SCENARIO" = never_ready ] || { [ "$SMOKE_SCENARIO" = reset_then_ready ] && [ "$count" = 1 ]; }; then
      echo 'curl: (56) Recv failure: Connection reset by peer' >&2
      exit 56
    fi ;;
  *auth/callback*)
    if [ "$SMOKE_SCENARIO" = bad_callback ]; then echo incorrect-page; else echo '<div id="root">'; fi ;;
  *runtime-config.json*) echo '{"clientId":"smoke-client","scope":"openid api://smoke/play"}' ;;
esac
""",
        "sleep": "#!/bin/sh\nexit 0\n",
    }.items():
        path = binary / name
        path.write_text(body)
        path.chmod(0o755)
    env = {
        **os.environ,
        "PATH": str(binary) + os.pathsep + os.environ["PATH"],
        "SMOKE_LOG": str(log),
        "SMOKE_COUNT": str(tmp_path / "count"),
        "SMOKE_SCENARIO": scenario,
    }
    result = subprocess.run(["bash", str(SCRIPT), "test-image"], env=env, capture_output=True, text=True)
    assert (result.returncode == 0) is successful, result.stderr
    commands = log.read_text().splitlines()
    assert sum("healthz" in command for command in commands) == health_calls
    assert commands[-1] == "docker rm -f web-smoke"
    if successful:
        assert "runtime-config.json" in "\n".join(commands)
        assert not any(command.startswith("docker logs") for command in commands)
    else:
        assert "Container startup diagnostics" in result.stdout
        assert any(command.startswith("docker logs") for command in commands)
        assert not any("runtime-config.json" in command for command in commands)

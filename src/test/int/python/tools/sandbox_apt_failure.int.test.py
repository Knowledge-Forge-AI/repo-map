"""Actual failed builder subprocesses retain canonical redacted APT diagnostics."""
from pathlib import Path
import hashlib
import json
import os
import subprocess

import pytest
import test_sandbox


def test_failed_build_subprocess_retains_apt_cause_without_retry(tmp_path: Path, capsys) -> None:
    builder = tmp_path / "fixture-docker"
    calls = tmp_path / "calls"
    line = "#7 1.250 apt prerequisites refused: apt-get install --simulate failed with exit 100; libssl-dev Depends: libssl3t64 (= 3.5.5-1~deb13u1)"
    script = (
        "#!/bin/sh\n"
        'printf "%s\\n" "$1 $2" >> "$FIXTURE_CALLS"\n'
        'if [ "$1 $2" = "image inspect" ]; then\n'
        '  printf "Error response from daemon: No such image: %s\\n" "$3" >&2\n'
        '  exit 1\n'
        'fi\n'
        'if [ "$1 $2" = "build --tag" ]; then\n'
        "  printf '%s\\n' " + repr(line) + " >&2\n"
        '  exit 37\n'
        'fi\n'
        'exit 91\n'
    )
    builder.write_text(script)
    builder.chmod(0o700)
    recipe = tmp_path / "Dockerfile"
    recipe.write_text("FROM scratch\n")

    def runner(command, **kwargs):
        return subprocess.run([str(builder), *command[1:]], env=os.environ | {"FIXTURE_CALLS": str(calls)}, **kwargs)

    with pytest.raises(RuntimeError, match="build failed: exit=37"):
        test_sandbox.ensure_sandbox_image(dockerfile=recipe, runner=runner)
    assert calls.read_text().splitlines() == ["image inspect", "build --tag"]
    diagnostics = [json.loads(value) for value in capsys.readouterr().err.splitlines()]
    assert [value["category"] for value in diagnostics] == ["cache_absent", "build_failed"]
    detail = diagnostics[-1]["apt_failure"]
    assert "exit 100" in detail["redacted_message"]
    assert "libssl3t64 (= 3.5.5-1~deb13u1)" in detail["redacted_message"]
    assert detail["source_line_sha256"] == hashlib.sha256(line.encode()).hexdigest()
    assert str(tmp_path) not in json.dumps(diagnostics)

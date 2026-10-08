"""Inner daemon, workspace, and boundary probes for the test sandbox."""

from __future__ import annotations

from pathlib import Path
import re
import subprocess
import time
from typing import Callable

from test_sandbox_contract import Captured, EXACT_CONTAINER_ID, Runner


RequireInnerCommand = Callable[..., subprocess.CompletedProcess[str]]
InnerCommand = Callable[..., list[str]]


def wait_for_inner_daemon(
    runner: Runner,
    container_id: str,
    *,
    captured: Captured,
) -> None:
    command = ["docker", "exec", container_id, "docker", "info", "--format", "{{.ServerVersion}}"]
    for _attempt in range(120):
        result = captured(runner, command, timeout=10)
        if result.returncode == 0:
            return
        time.sleep(0.25)
    raise RuntimeError("inner Docker daemon did not become ready")


def prepare_inner_images(
    runner: Runner,
    container_id: str,
    *,
    captured: Captured,
    images: tuple[str, ...],
) -> None:
    for image in images:
        result = captured(
            runner,
            ["docker", "exec", container_id, "docker", "pull", image],
            timeout=300,
        )
        if result.returncode != 0:
            if "no space left on device" in result.stderr.lower():
                raise RuntimeError("inner_docker_capacity_refused: exhausted")
            raise RuntimeError(
                f"inner Docker prerequisite acquisition failed for {image}: "
                f"{result.stderr}"
            )


def prepare_workspace_and_identity(
    runner: Runner,
    container_id: str,
    *,
    require_inner_command: RequireInnerCommand,
    inner_report_root: Path,
    inner_test_scratch_root: Path,
) -> None:
    require_inner_command(
        runner,
        container_id,
        (
            "mkdir",
            "-p",
            "/workspace",
            "/sandbox-scratch/bin",
            "/sandbox-scratch/project-build",
            "/sandbox-scratch/project-egg-info",
            "/sandbox-scratch/workspace-upper",
            "/sandbox-scratch/workspace-work",
            "/sandbox-scratch/tmp",
            "/sandbox-scratch/cache",
            "/sandbox-scratch/pip-cache",
            "/sandbox-scratch/go-tmp",
            "/sandbox-scratch/go-cache",
            "/sandbox-scratch/go-mod-cache",
            "/sandbox-scratch/go-path",
            "/sandbox-scratch/golangci-cache",
            "/sandbox-scratch/operator-home",
            str(inner_report_root.parent),
            str(inner_test_scratch_root),
        ),
    )
    require_inner_command(
        runner,
        container_id,
        ("chmod", "0700", str(inner_test_scratch_root)),
    )
    require_inner_command(
        runner,
        container_id,
        (
            "mount",
            "-t",
            "overlay",
            "overlay",
            "-o",
            "lowerdir=/workspace-ro,upperdir=/sandbox-scratch/workspace-upper,"
            "workdir=/sandbox-scratch/workspace-work",
            "/workspace",
        ),
    )
    require_inner_command(
        runner,
        container_id,
        (
            "mkdir",
            "-p",
            "/workspace/build",
            "/workspace/src/main/python/repomap_kg.egg-info",
        ),
    )
    require_inner_command(
        runner,
        container_id,
        (
            "mount",
            "--bind",
            "/sandbox-scratch/project-build",
            "/workspace/build",
        ),
    )
    require_inner_command(
        runner,
        container_id,
        (
            "mount",
            "--bind",
            "/sandbox-scratch/project-egg-info",
            "/workspace/src/main/python/repomap_kg.egg-info",
        ),
    )
    passwd_probe = (
        "from pathlib import Path; path=Path('/etc/passwd'); rows=[]; "
        "\nfor line in path.read_text(encoding='utf-8').splitlines():"
        "\n fields=line.split(':');"
        "\n if fields[0] == 'root': fields[5]='/sandbox-scratch/operator-home'"
        "\n rows.append(':'.join(fields))"
        "\npath.write_text('\\n'.join(rows)+'\\n', encoding='utf-8')"
    )
    require_inner_command(
        runner,
        container_id,
        ("python3", "-c", passwd_probe),
    )
    cli_wrapper = (
        "#!/bin/sh\n"
        'PYTHONPATH="${PYTHONPATH:+${PYTHONPATH}:}/workspace/tools:'
        '/workspace/src/main/python:/workspace/src/test/support/python" '
        "exec python3 -c 'from repomap_kg.cli import main; "
        "raise SystemExit(main())' \"$@\"\n"
    )
    wrapper_probe = (
        "from pathlib import Path; "
        "path=Path('/sandbox-scratch/bin/repomap-kg'); "
        f"path.write_text({cli_wrapper!r}, encoding='utf-8'); "
        "path.chmod(0o755)"
    )
    require_inner_command(
        runner,
        container_id,
        ("python3", "-c", wrapper_probe),
    )
    require_inner_command(
        runner,
        container_id,
        (
            "git",
            "config",
            "--file",
            "/sandbox-scratch/operator-home/.gitconfig",
            "--add",
            "safe.directory",
            "/workspace",
        ),
    )


def remove_inner_container(
    runner: Runner,
    outer_id: str,
    inner_id: str,
    *,
    require_inner_command: RequireInnerCommand,
    captured: Captured,
    inner_exec: InnerCommand,
) -> None:
    require_inner_command(runner, outer_id, ("docker", "rm", "-f", "-v", inner_id))
    absent = captured(
        runner,
        inner_exec(outer_id, "docker", "container", "inspect", inner_id),
        timeout=30,
    )
    if absent.returncode == 0:
        raise RuntimeError("nested bind-probe container remains after cleanup")


def probe_inner_volume(
    runner: Runner,
    container_id: str,
    token: str,
    *,
    require_inner_command: RequireInnerCommand,
    captured: Captured,
    inner_exec: InnerCommand,
) -> None:
    name = f"repomap-sandbox-probe-volume-{token}"
    created = require_inner_command(
        runner,
        container_id,
        (
            "docker",
            "volume",
            "create",
            "--label",
            "org.repomap.test.sandbox.probe=true",
            name,
        ),
    )
    if created.stdout.strip() != name:
        raise RuntimeError("nested volume probe returned unexpected identity")
    require_inner_command(runner, container_id, ("docker", "volume", "rm", name))
    absent = captured(
        runner,
        inner_exec(container_id, "docker", "volume", "inspect", name),
        timeout=30,
    )
    if absent.returncode == 0:
        raise RuntimeError("nested volume probe remains after cleanup")


def prove_inner_boundary(
    runner: Runner,
    *,
    container_id: str,
    token: str,
    require_inner_command: RequireInnerCommand,
    captured: Captured,
    inner_exec: InnerCommand,
    remove_container: Callable[..., None],
    probe_volume: Callable[..., None],
    alpine_probe_image: str,
    exact_container_id: re.Pattern[str] = EXACT_CONTAINER_ID,
) -> None:
    python_probe = (
        "from pathlib import Path; import docker,sys; "
        "assert sys.version_info[:2] == (3, 13); "
        "assert not Path('/var/run/docker.sock').exists(); "
        "assert Path('/run/repomap-docker.sock').is_socket(); "
        "scratch = Path('/sandbox-scratch/test-scratch'); "
        "assert scratch.is_dir() and scratch.stat().st_uid == 0 and (scratch.stat().st_mode & 0o777) == 0o700; "
        "client=docker.from_env(); assert client.ping(); client.close()"
    )
    require_inner_command(runner, container_id, ("python3", "-c", python_probe))
    go = require_inner_command(runner, container_id, ("go", "version"))
    lint = require_inner_command(runner, container_id, ("golangci-lint", "version"))
    if "go1.25" not in go.stdout or "2.6.2" not in lint.stdout:
        raise RuntimeError("integration sandbox toolchain parity probe failed")
    git_safe = require_inner_command(
        runner,
        container_id,
        (
            "git",
            "config",
            "--file",
            "/sandbox-scratch/operator-home/.gitconfig",
            "--get-all",
            "safe.directory",
        ),
    )
    if git_safe.stdout.strip() != "/workspace":
        raise RuntimeError("integration sandbox git safe.directory configuration is invalid")
    git_toplevel = require_inner_command(
        runner,
        container_id,
        ("git", "-C", "/workspace", "rev-parse", "--show-toplevel"),
    )
    if git_toplevel.stdout.strip() != "/workspace":
        raise RuntimeError("integration sandbox git repository root probe failed")
    require_inner_command(
        runner,
        container_id,
        ("git", "-C", "/workspace", "status", "--porcelain=v1", "--untracked-files=no"),
    )
    inner_name = f"repomap-sandbox-probe-{token}"
    child_id: str | None = None
    try:
        started = require_inner_command(
            runner,
            container_id,
            (
                "docker",
                "run",
                "-d",
                "--name",
                inner_name,
                "--label",
                "org.repomap.test.sandbox.probe=true",
                "--mount",
                "type=bind,src=/workspace,dst=/workspace,readonly",
                "--mount",
                "type=bind,src=/sandbox-scratch,dst=/sandbox-scratch",
                alpine_probe_image.split("@")[0] if "@" in alpine_probe_image else alpine_probe_image,
                "sh",
                "-c",
                "test -r /workspace/pyproject.toml && printf 'ok\\n' > /sandbox-scratch/bind-proof",
            ),
        )
        candidate = started.stdout.strip()
        if exact_container_id.fullmatch(candidate) is None:
            raise RuntimeError("nested bind probe returned no exact container ID")
        child_id = candidate
        proof = require_inner_command(
            runner,
            container_id,
            ("cat", "/sandbox-scratch/bind-proof"),
        )
        if proof.stdout != "ok\n":
            raise RuntimeError("nested bind probe did not preserve identical paths")
    finally:
        if child_id is not None:
            remove_container(runner, container_id, child_id)
        captured(
            runner,
            inner_exec(container_id, "rm", "-f", "/sandbox-scratch/bind-proof"),
        )
    probe_volume(runner, container_id, token)


def run_inner_tests(
    runner: Runner,
    container_id: str,
    *,
    require_inner_command: RequireInnerCommand,
    captured: Captured,
) -> int:
    require_inner_command(runner, container_id, ("touch", "/sandbox-scratch/start-tests"))
    waited = captured(runner, ["docker", "wait", container_id], timeout=21_600)
    if waited.returncode != 0:
        raise RuntimeError("integration sandbox test result readback failed")
    try:
        return int(waited.stdout.strip())
    except ValueError as error:
        raise RuntimeError("integration sandbox test exit status is malformed") from error

"""Run dockerd and canonical tests in one supervised sandbox process tree."""

from __future__ import annotations

import os
from pathlib import Path
import signal
import subprocess
import sys
import time


try:
    from test_sandbox import (
        INNER_DOCKER_HOST,
        INNER_OWNER_PATH as OWNER_PATH,
        INNER_TEST_SCRATCH_ROOT,
    )
except ImportError:
    INNER_DOCKER_HOST = "unix:///run/repomap-docker.sock"
    OWNER_PATH = Path("/run/repomap-test-sandbox-owner")
    INNER_TEST_SCRATCH_ROOT = Path("/sandbox-scratch/test-scratch")

START_PATH = Path("/sandbox-scratch/start-tests")
INFRASTRUCTURE_PROBE_FLAG = "--repomap-sandbox-infrastructure-probe"
INFRASTRUCTURE_PROBE_PAYLOAD = (
    "probe/path.py::ProbeClass::test_node[param]",
    "probe/second.py::test_other",
)


def _arguments(argv: list[str]) -> tuple[int, list[str]]:
    if len(argv) < 3 or argv[0] != "--docker-group" or "--" not in argv:
        raise RuntimeError("sandbox entrypoint arguments are invalid")
    separator = argv.index("--")
    if separator != 2:
        raise RuntimeError("sandbox entrypoint separator is invalid")
    group = int(argv[1])
    if group < 0 or not argv[separator + 1 :]:
        raise RuntimeError("sandbox entrypoint payload is invalid")
    return group, argv[separator + 1 :]


def _test_environment() -> dict[str, str]:
    token = OWNER_PATH.read_text(encoding="utf-8").strip()
    if len(token) != 64:
        raise RuntimeError("sandbox owner token is invalid")
    environment = dict(os.environ)
    environment.update(
        {
            "_REPOMAP_TEST_SANDBOX_ACTIVE": "1",
            "_REPOMAP_TEST_SANDBOX_TOKEN": token,
            "DOCKER_HOST": INNER_DOCKER_HOST,
            "REPOMAP_TEST_SCRATCH_ROOT": str(INNER_TEST_SCRATCH_ROOT),
            "PYTHONPYCACHEPREFIX": "/sandbox-scratch/pycache",
            "TMPDIR": "/sandbox-scratch/tmp",
            "TMP": "/sandbox-scratch/tmp",
            "TEMP": "/sandbox-scratch/tmp",
            "XDG_CACHE_HOME": "/sandbox-scratch/cache",
            "PIP_CACHE_DIR": "/sandbox-scratch/pip-cache",
            "GOTMPDIR": "/sandbox-scratch/go-tmp",
            "GOCACHE": "/sandbox-scratch/go-cache",
            "GOMODCACHE": "/sandbox-scratch/go-mod-cache",
            "GOPATH": "/sandbox-scratch/go-path",
            "GOLANGCI_LINT_CACHE": "/sandbox-scratch/golangci-cache",
            "HOME": "/sandbox-scratch/operator-home",
            "USER": "repomap-test",
            "LOGNAME": "repomap-test",
            "PYTHONPATH": "/workspace:/workspace/tools",
            "PATH": (
                "/sandbox-scratch/bin:/usr/lib/postgresql/17/bin:"
                "/usr/local/go/bin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
            ),
        }
    )
    return environment


def _test_command(test_argv: list[str]) -> tuple[str, ...]:
    if test_argv and test_argv[0] == INFRASTRUCTURE_PROBE_FLAG:
        if tuple(test_argv[1:]) != INFRASTRUCTURE_PROBE_PAYLOAD:
            raise RuntimeError("sandbox infrastructure probe payload is invalid")
        probe = (
            "import json,sys; "
            "sys.path.insert(0, '/workspace/tools'); "
            "from test_sandbox import active_sandbox; "
            "assert active_sandbox(); "
            f"expected={INFRASTRUCTURE_PROBE_PAYLOAD!r}; "
            "assert tuple(sys.argv[1:]) == expected; "
            "print(json.dumps({'sandbox_probe':'passed','argv':sys.argv[1:]}))"
        )
        return ("python3", "-c", probe, *test_argv[1:])
    return ("python3", "/workspace/tools/run_tests.py", *test_argv)


def main(argv: list[str] | None = None) -> int:
    docker_group, test_argv = _arguments(list(sys.argv[1:] if argv is None else argv))
    dockerd = subprocess.Popen(
        (
            "dockerd",
            f"--host={INNER_DOCKER_HOST}",
            "--data-root=/var/lib/docker",
            "--storage-driver=overlay2",
            "--pidfile=/run/repomap-docker.pid",
            f"--group={docker_group}",
            "--mtu=1400",
        ),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    test_process: subprocess.Popen[bytes] | None = None

    def terminate(_signum, _frame) -> None:
        if test_process is not None and test_process.poll() is None:
            test_process.terminate()
        raise KeyboardInterrupt

    previous_sigterm = signal.signal(signal.SIGTERM, terminate)
    try:
        while not START_PATH.exists():
            if dockerd.poll() is not None:
                raise RuntimeError("inner Docker daemon exited before test release")
            time.sleep(0.05)
        test_process = subprocess.Popen(
            _test_command(test_argv),
            cwd="/workspace",
            env=_test_environment(),
        )
        return test_process.wait()
    except KeyboardInterrupt:
        return 130
    finally:
        signal.signal(signal.SIGTERM, previous_sigterm)
        if test_process is not None and test_process.poll() is None:
            test_process.kill()
            test_process.wait()
        if dockerd.poll() is None:
            dockerd.terminate()
            try:
                dockerd.wait(timeout=5)
            except subprocess.TimeoutExpired:
                dockerd.kill()
                dockerd.wait()


if __name__ == "__main__":
    raise SystemExit(main())

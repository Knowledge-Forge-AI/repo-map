"""Run-owned disposable PostgreSQL container for the native host MCP proof.

The maintained ``PostgresContainerSession`` owns the container shape: exact
digest image with ``--pull=never``, tmpfs data, a loopback-only
``127.0.0.1:<fresh port>:5432`` publication, a unique ``repomap-test-postgres-
<run id>`` name with the ``org.repomap.test.run_id`` label, and a 0700 psql
wrapper file. PostgreSQL is the only component; there is no server container,
coordinator, service manager, or installation. Every command here names the
exact owned container; nothing lists, prunes, or stops anything else.
"""

from __future__ import annotations

import subprocess
from typing import Any

from repomap_test_support.postgres_container import (
    PostgresContainerConfig,
    PostgresContainerDatabase,
    PostgresContainerSession,
    SubprocessRunner,
    redacted_command,
)


def own_session(runner: SubprocessRunner) -> SubprocessRunner:
    """Run each Docker CLI helper in its own session.

    A terminal Ctrl-C or hangup reaches the runner's foreground process group; outside it, an
    in-flight ``docker rm -f`` or label check during deferred cleanup is not killed as well.
    Timeouts still bound every command.
    """
    def run(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        kwargs.setdefault("start_new_session", True)
        return runner(*args, **kwargs)

    return run


class OwnedContainerBackend:
    kind = "owned-docker-postgres"

    def __init__(self, *, port: int, run_id: str, runner: SubprocessRunner = subprocess.run) -> None:
        self.config = PostgresContainerConfig(host_port=port, run_id=run_id)
        self.runner = runner = own_session(runner)
        self.session = PostgresContainerSession(self.config, runner=runner)
        self.admin: PostgresContainerDatabase | None = None
        self.commands: list[dict[str, Any]] = []

    @property
    def name(self) -> str:
        return self.session.harness.container_name

    @property
    def label(self) -> str:
        return f"org.repomap.test.run_id={self.config.run_id}"

    @property
    def password(self) -> str:
        return self.config.password

    def describe(self) -> dict[str, Any]:
        return {"kind": self.kind, "container_name": self.name, "label": self.label, "image": self.config.image,
                "bind": f"{self.config.bind_host}:{self.config.host_port}:5432", "data": "tmpfs",
                "pull": "never", "start_command": redacted_command(self.session.harness.start_command())}

    def manual_cleanup(self) -> str:
        return f"docker rm -f {self.name}"

    def start(self) -> PostgresContainerDatabase:
        self.session.__enter__()
        self.admin = self.session.database()
        return self.admin

    def create_database(self, name: str) -> PostgresContainerDatabase:
        if self.admin is None:
            raise RuntimeError("backend is not started")
        return self.admin.create_database(name)

    def route_evidence(self) -> dict[str, Any]:
        published = self._docker("port", self.name, "5432/tcp")
        return {"docker_port": published["stdout"].strip(), "exit": published["exit"]}

    def stop_for_outage(self) -> dict[str, Any]:
        return self._docker("stop", "--time", "10", self.name)

    def outage_active(self) -> bool:
        inspected = self._docker("inspect", "--format", "{{.State.Running}}", self.name)
        return inspected["exit"] == 0 and inspected["stdout"].strip() == "false"

    def cleanup(self) -> list[dict[str, Any]]:
        steps: list[dict[str, Any]] = []
        try:
            self.session.__exit__(None, None, None)
            steps.append({"step": "remove-owned-container", "ok": True, "command": self.manual_cleanup()})
        except Exception as error:  # recorded, never hidden
            steps.append({"step": "remove-owned-container", "ok": False, "error": f"{type(error).__name__}"})
        remaining = self._docker("ps", "-a", "-q", "--filter", f"label={self.label}")
        steps.append({"step": "verify-no-labelled-container", "ok": remaining["exit"] == 0
                      and not remaining["stdout"].strip(), "label": self.label,
                      "remaining": remaining["stdout"].split()})
        return steps

    def _docker(self, *args: str) -> dict[str, Any]:
        command = [self.config.runtime, *args]
        try:
            completed = self.runner(command, check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    text=True, timeout=60)
            record = {"command": redacted_command(command), "exit": completed.returncode,
                      "stdout": completed.stdout or "", "stderr": (completed.stderr or "")[-1000:]}
        except (OSError, subprocess.SubprocessError) as error:
            record = {"command": redacted_command(command), "exit": None, "stdout": "",
                      "stderr": f"{type(error).__name__}: {error}"}
        self.commands.append(record)
        return record

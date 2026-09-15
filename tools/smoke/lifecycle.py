"""Bounded end-to-end RepoMap smoke lifecycle over exact Docker resources."""

from __future__ import annotations

from contextlib import contextmanager
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from typing import Any, Callable, Iterator

from repomap_kg.runtime.local import LocalRuntimeIdentity
from repomap_kg.runtime.release import POSTGRES_RELEASE_IMAGE
from repomap_test_support.resource_docker import (
    DockerBaseline,
    DockerResourceOwner,
    ownership_labels,
)
from repomap_test_support.resource_docker_engine import DockerSdkApi
from repomap_test_support.resource_ledger import ResourceKind

from . import lifecycle_reporting as _lifecycle_reporting
from .lifecycle_reporting import (
    _private_env,
    _write_config,
    _write_fixture,
    validate_control_graph_readback,
    validate_target_database_absent,
)

_ALLOWLISTED_DIAGNOSTIC_CODES = _lifecycle_reporting._ALLOWLISTED_DIAGNOSTIC_CODES
_ALLOWLISTED_RESULTS = _lifecycle_reporting._ALLOWLISTED_RESULTS
_ALLOWLISTED_SEVERITIES = _lifecycle_reporting._ALLOWLISTED_SEVERITIES
_bounded_smoke_failure_summary = _lifecycle_reporting._bounded_smoke_failure_summary


POSTGRES_DATA = "/var/lib/postgresql/data"
WORKSPACE = "/workspace"


class SmokeBudgetExceeded(RuntimeError):
    """The single smoke wall-clock budget was exhausted."""


class SmokeBudget:
    def __init__(
        self,
        limit_seconds: float,
        *,
        clock: Callable[[], float] = time.monotonic,
        cleanup_reserve_seconds: float = 30.0,
    ) -> None:
        if limit_seconds <= 0:
            raise ValueError("smoke budget must be greater than 0 seconds")
        self.limit_seconds = float(limit_seconds)
        self.cleanup_reserve_seconds = min(
            float(cleanup_reserve_seconds), self.limit_seconds / 2
        )
        self._clock = clock
        self.started = clock()
        self.timings: dict[str, float] = {}

    def elapsed(self) -> float:
        return max(0.0, self._clock() - self.started)

    def remaining(self, *, cleanup: bool = False) -> float:
        reserve = 0.0 if cleanup else self.cleanup_reserve_seconds
        remaining = self.limit_seconds - self.elapsed() - reserve
        if remaining <= 0:
            raise SmokeBudgetExceeded("smoke wall-clock budget exhausted")
        return remaining

    @contextmanager
    def step(self, name: str, *, cleanup: bool = False) -> Iterator[None]:
        self.remaining(cleanup=cleanup)
        started = self._clock()
        try:
            yield
        finally:
            self.timings[name] = max(0.0, self._clock() - started)


def _run_cli(
    budget: SmokeBudget,
    home: Path,
    *arguments: str,
    expect_success: bool = True,
) -> dict[str, Any] | None:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[2] / "src/main/python")
    private_env = home / "runtime/.env"
    if private_env.is_file():
        env.update(_private_env(private_env))
    completed = subprocess.run(
        [sys.executable, "-m", "repomap_kg", *arguments],
        cwd=Path(__file__).resolve().parents[2],
        env=env,
        check=False,
        capture_output=True,
        text=True,
        timeout=budget.remaining(),
    )
    if expect_success and completed.returncode != 0:
        detail = " ".join(
            value.strip()
            for value in (completed.stderr, completed.stdout)
            if value.strip()
        )
        for private_path in (str(home), str(Path(__file__).resolve().parents[2])):
            detail = detail.replace(private_path, "[REDACTED_PATH]")
        detail = " ".join(detail.split())[-1000:]
        raise RuntimeError(
            f"product command {arguments[:3]!r} failed with "
            f"exit {completed.returncode}: {detail or '[no diagnostic]'}"
        )
    if not expect_success:
        return validate_target_database_absent(completed)
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise RuntimeError(f"product command {arguments[:3]!r} returned invalid JSON") from error


def _create_network(resource_run: Any, client: Any, identity: LocalRuntimeIdentity):
    api = DockerSdkApi(client)
    baseline = DockerBaseline.capture(api, kinds=(ResourceKind.DOCKER_NETWORK,))
    owner = DockerResourceOwner(resource_run.ledger.identity, resource_run.ledger, api, baseline)
    labels = {
        **identity.labels("network"),
        **ownership_labels(resource_run.ledger.identity, role="smoke-network", retained=False),
    }
    network = client.networks.create(identity.network_name, labels=labels)
    owner.register_created(ResourceKind.DOCKER_NETWORK, network.id, role="smoke-network")
    return network, owner


def _wait_postgres(container: Any, budget: SmokeBudget) -> None:
    while True:
        result = container.exec_run(
            ["pg_isready", "-h", "127.0.0.1", "-p", "5432", "-U", "repomap", "-d", "postgres"],
        )
        if result.exit_code is not None and int(result.exit_code) == 0:
            return
        if budget.remaining() < 0.2:
            raise SmokeBudgetExceeded("PostgreSQL readiness exhausted smoke budget")
        time.sleep(min(0.1, budget.remaining()))


def _run_runtime_probe(
    config: Any,
    containers: Any,
    client: Any,
    network_name: str,
    postgres_host: str,
    password: str,
    budget: SmokeBudget,
) -> None:
    command = [
        "-c",
        (
            "import psycopg, repomap_kg; "
            "assert repomap_kg.__file__.startswith('/workspace/src/main/python/repomap_kg/'); "
            f"c=psycopg.connect(host={postgres_host!r},dbname='postgres',user='repomap',"
            "password=__import__('os').environ['REPOMAP_PG_PASSWORD']); "
            "assert c.execute('SELECT 1').fetchone()==(1,); c.close()"
        ),
    ]
    identity = containers.create(
        config.image_reference,
        command,
        role="smoke-runtime",
        entrypoint=["python"],
        environment={
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONPATH": "/workspace/src/main/python",
            "REPOMAP_PG_PASSWORD": password,
        },
        network=network_name,
        tmpfs={POSTGRES_DATA: "rw,noexec,nosuid,nodev"},
        volumes={str(config.repo_root.resolve()): {"bind": WORKSPACE, "mode": "ro"}},
        working_dir=WORKSPACE,
    )
    try:
        container = client.containers.get(identity)
        container.start()
        status = int(container.wait(timeout=budget.remaining()).get("StatusCode", 2))
        if status != 0:
            try:
                raw_logs = container.logs(stdout=True, stderr=True)
                log_text = raw_logs.decode("utf-8", errors="replace").strip()
            except Exception as log_err:
                log_text = f"[log retrieval failed: {log_err}]"
            for secret in (password, str(config.repo_root.resolve())):
                log_text = log_text.replace(secret, "[REDACTED]")
            bounded_log = " ".join(log_text.split())[-1000:]
            raise RuntimeError(
                f"current-checkout runtime probe failed (exit={status}): {bounded_log or '[empty output]'}"
            )
    finally:
        containers.cleanup(identity)


def run_lifecycle(
    config: Any,
    resource_run: Any,
    containers: Any,
    client: Any,
    budget: SmokeBudget,
) -> dict[str, Any]:
    smoke_root = resource_run.layout.run_root / "smoke-lifecycle"
    home = smoke_root / "home"
    target_fixture = smoke_root / "target-repository"
    control_fixture = smoke_root / "control-repository"
    network = network_owner = postgres_id = None
    report: dict[str, Any] = {"assertions": {}}
    try:
        smoke_root.mkdir(mode=0o700)
        with budget.step("initialize-home"):
            _run_cli(
                budget, home, "local", "setup", "--repo-map-home", str(home), "--json"
            )
            home.chmod(0o700)
            _write_fixture(target_fixture, "target")
            _write_fixture(control_fixture, "control")
            _write_config(home, config.pg_container_port, target_fixture, control_fixture)
            (home / "repomap.rpl.toml").chmod(0o600)
            private = _private_env(home / "runtime/.env")
            password = private["REPOMAP_PG_PASSWORD"]
            identity = LocalRuntimeIdentity.from_home(home)

        with budget.step("start-resources"):
            client.images.get(POSTGRES_RELEASE_IMAGE)
            network, network_owner = _create_network(resource_run, client, identity)
            postgres_id = containers.create(
                POSTGRES_RELEASE_IMAGE,
                None,
                role="smoke-postgres",
                name=identity.postgres_container,
                labels=identity.labels("postgres"),
                environment={
                    "POSTGRES_DB": "postgres",
                    "POSTGRES_USER": "repomap",
                    "POSTGRES_PASSWORD": password,
                },
                network=identity.network_name,
                ports={"5432/tcp": ("127.0.0.1", config.pg_container_port)},
                tmpfs={POSTGRES_DATA: "rw,noexec,nosuid,nodev"},
            )
            postgres = client.containers.get(postgres_id)
            postgres.start()
            _wait_postgres(postgres, budget)
            _run_runtime_probe(
                config,
                containers,
                client,
                identity.network_name,
                identity.postgres_container,
                password,
                budget,
            )
            report["assertions"]["current_checkout_runtime"] = True

        for graph, database in (
            ("target", "repomap_smoke_target"),
            ("control", "repomap_smoke_control"),
        ):
            with budget.step(f"initialize-{graph}-database"):
                _run_cli(
                    budget, home, "local", "db", "init", "--repo-map-home",
                    str(home), "--database", database, "--from-source", "--json",
                )

        with budget.step("initialize-coordinator-control"):
            _run_cli(
                budget,
                home,
                "ops",
                "coordinator-control-init",
                "--repo-map-home",
                str(home),
                "--json",
            )

        for graph in ("target", "control"):
            with budget.step(f"refresh-{graph}"):
                _run_cli(
                    budget, home, "ops", "refresh-graph", "--repo-map-home",
                    str(home), "--graph", graph, "--json",
                )

        with budget.step("product-readback"):
            target_summary = _run_cli(
                budget, home, "ops", "graph-summary", "--repo-map-home", str(home),
                "--graph", "target", "--json",
            )
            target_files = _run_cli(
                budget, home, "ops", "graph-files", "--repo-map-home", str(home),
                "--graph", "target", "--limit", "10", "--json",
            )
            if not target_summary or not target_files:
                raise RuntimeError("target graph product readback was empty")
            report["assertions"]["graph_data_exists"] = True

        with budget.step("backup-first-drop"):
            drop = _run_cli(
                budget, home, "local", "db", "drop", "--repo-map-home", str(home),
                "--database", "repomap_smoke_target", "--backup-first", "--yes",
                "--reason", "bounded smoke lifecycle", "--json",
            )
            if not drop or not drop.get("backup_id") or not drop.get("database_dropped"):
                raise RuntimeError("backup-first drop result was incomplete")

        with budget.step("post-drop-readback"):
            _run_cli(
                budget, home, "ops", "graph-summary", "--repo-map-home", str(home),
                "--graph", "target", "--json", expect_success=False,
            )
            control = _run_cli(
                budget, home, "ops", "graph-summary", "--repo-map-home", str(home),
                "--graph", "control", "--json",
            )
            validate_control_graph_readback(control)
            report["assertions"]["target_gone_control_coherent"] = True

        with budget.step("backup-inspection"):
            inspection = _run_cli(
                budget, home, "local", "db", "backup-inspect", "--repo-map-home",
                str(home), str(drop["backup_id"]), "--json",
            )
            dumps = tuple((home / "backups").rglob("dump.pgcustom"))
            if (
                len(dumps) != 1
                or dumps[0].stat().st_size <= 0
                or not inspection
                or not inspection.get("manifest_verified")
                or not inspection.get("checksum_verified")
                or not inspection.get("dump_contents_read")
            ):
                raise RuntimeError("run-owned PostgreSQL backup proof was incomplete")
            report["assertions"]["backup_structurally_verified"] = True
        report["result"] = "passed"
        return report
    finally:
        cleanup_errors = []
        try:
            with budget.step("cleanup-containers", cleanup=True):
                if postgres_id is not None:
                    containers.cleanup(postgres_id)
        except Exception as error:
            cleanup_errors.append(error)
        try:
            with budget.step("cleanup-network", cleanup=True):
                if network is not None and network_owner is not None:
                    network_owner.cleanup(ResourceKind.DOCKER_NETWORK, network.id)
                    network_owner.verify_preexisting_unchanged()
        except Exception as error:
            cleanup_errors.append(error)
        try:
            with budget.step("cleanup-files", cleanup=True):
                if smoke_root.exists():
                    shutil.rmtree(smoke_root)
        except Exception as error:
            cleanup_errors.append(error)
        report["elapsed_seconds"] = budget.elapsed()
        report["step_timings"] = dict(budget.timings)
        report["assertions"]["exact_cleanup"] = not cleanup_errors
        if cleanup_errors:
            raise RuntimeError("smoke cleanup did not complete exactly") from cleanup_errors[0]

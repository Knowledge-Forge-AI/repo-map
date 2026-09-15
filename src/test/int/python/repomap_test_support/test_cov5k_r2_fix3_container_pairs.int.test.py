from __future__ import annotations

import time
import uuid

import docker
import pytest

from repomap_test_support.test_cov5k_r2_fix2_catalog import build_closed_catalog
from repomap_test_support.resource_docker_current import CurrentRunDockerContainers
from repomap_test_support.resource_run import active_resource_run
from repomap_test_support.test_cov5k_r2_fix2_evidence import verify_executor_evidence
from repomap_test_support.test_cov5k_r2_fix2_runtime import (
    execute_container_rss_equivalence,
)


def _entry(workload: str):
    return next(
        entry
        for entry in build_closed_catalog()
        if entry.semantic_group == "D"
        and entry.operation_kind == "container_rss_equivalence"
        and dict(entry.parameter_values)["workload"] == workload
        and dict(entry.parameter_values)["pair"] == 1
    )


def _start_workload(client, owner, workload: str, name: str):
    if workload == "database_activity":
        image = client.images.get(
            "postgres:16-alpine@sha256:"
            "e013e867e712fec275706a6c51c966f0bb0c93cfa8f51000f85a15f9865a28cb"
        )
        identity = owner.create(
            image.id,
            None,
            role="container-pair-database",
            name=name,
            environment={"POSTGRES_HOST_AUTH_METHOD": "trust"},
            tmpfs={"/var/lib/postgresql/data": "rw"},
        )
        container = client.containers.get(identity)
        try:
            container.start()
            for _ in range(100):
                ready = container.exec_run(("pg_isready", "-U", "postgres"))
                activity = container.exec_run(
                    (
                        "psql",
                        "-U",
                        "postgres",
                        "-d",
                        "postgres",
                        "-c",
                        "SELECT count(*) FROM generate_series(1, 10000)",
                    )
                )
                if ready.exit_code == 0 and activity.exit_code == 0:
                    break
                time.sleep(0.05)
            else:
                raise RuntimeError(
                    "disposable database workload did not become query-ready"
                )
        except Exception:
            owner.cleanup(identity)
            raise
        return container, identity
    image = client.images.get(
        "alpine:latest@sha256:"
        "28bd5fe8b56d1bd048e5babf5b10710ebe0bae67db86916198a6eec434943f8b"
    )
    command = ("sh", "-c", "sleep 60")
    if workload == "unrelated_activity":
        command = ("sh", "-c", "while :; do :; done")
    identity = owner.create(
        image.id,
        command,
        role=f"container-pair-{workload.replace('_', '-')}",
        name=name,
    )
    container = client.containers.get(identity)
    try:
        container.start()
    except Exception:
        owner.cleanup(identity)
        raise
    return container, identity


@pytest.mark.parametrize(
    "workload",
    ("quiet", "database_activity", "unrelated_activity"),
)
def test_fix3_one_actual_container_pair_per_workload_is_exactly_cleaned(
    workload: str,
) -> None:
    client = docker.from_env()
    resource_run = active_resource_run()
    if resource_run is None:
        raise RuntimeError("container-pair workload requires a managed resource run")
    owner = CurrentRunDockerContainers(resource_run, client)
    name = f"repomap-fix3-pair-{workload.replace('_', '-')}-{uuid.uuid4().hex[:8]}"
    container = None
    container_id = None
    try:
        container, container_id = _start_workload(client, owner, workload, name)
        container.reload()
        assert container.status == "running"
        entry = _entry(workload)
        result = execute_container_rss_equivalence(
            entry,
            runtime_identity_context={
                "runtime": "docker",
                "container_name": name,
                "repomap_commit": "1" * 40,
                "postgresql_server_version": "16",
            },
            workload_probe=lambda: (
                workload,
                {
                    "container_running": container.status == "running",
                    "process_count": len(container.top().get("Processes", ())),
                },
            ),
        )
        verify_executor_evidence(entry, result)
        observed = dict(result.observed_fields)
        assert observed["runtime_identity_available"] is True
        assert observed["within_tolerance"] is True
    finally:
        if container_id is not None:
            owner.cleanup(container_id)
            owner.verify_baseline()
        with pytest.raises(docker.errors.NotFound):
            client.containers.get(container_id or name)
        client.close()

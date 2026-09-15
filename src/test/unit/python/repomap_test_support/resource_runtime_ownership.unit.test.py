"""TEST-HYGIENE1 process, socket, port, and PostgreSQL ownership contracts."""

from __future__ import annotations

from pathlib import Path

import pytest

from repomap_test_support.resource_ledger import ResourceLedger, RunIdentity
from repomap_test_support.resource_runtime import (
    RuntimeOwnershipError,
    RuntimeResourceOwner,
)


def _owner(tmp_path: Path):
    identity = RunIdentity("repo-map_dev", "TEST-HYGIENE1", "run1")
    ledger = ResourceLedger.create(tmp_path / "ledger.json", identity)
    return RuntimeResourceOwner(ledger), ledger


def test_exact_process_and_socket_cleanup_require_independent_absence(tmp_path):
    owner, ledger = _owner(tmp_path)
    owner.register_process("process-1")
    owner.register_socket("socket-1")

    owner.cleanup_process("process-1", terminate=lambda: None, is_present=lambda: False)
    owner.cleanup_socket("socket-1", remove=lambda: None, is_present=lambda: False)

    projection = ledger.public_projection()
    assert projection["phase_processes_remaining"] == 0
    assert projection["phase_sockets_remaining"] == 0


def test_free_port_alone_does_not_prove_postgres_cleanup(tmp_path):
    owner, ledger = _owner(tmp_path)
    owner.register_postgres("cluster-1", "port-1")

    with pytest.raises(RuntimeOwnershipError, match="cluster remains"):
        owner.cleanup_postgres(
            "cluster-1",
            "port-1",
            stop=lambda: None,
            cluster_is_present=lambda: True,
            port_is_bound=lambda: False,
        )

    projection = ledger.public_projection()
    assert projection["phase_postgres_clusters_remaining"] == 1
    assert projection["phase_ports_remaining"] == 0


def test_postgres_cleanup_requires_cluster_and_port_readback(tmp_path):
    owner, ledger = _owner(tmp_path)
    owner.register_postgres("cluster-1", "port-1")

    owner.cleanup_postgres(
        "cluster-1",
        "port-1",
        stop=lambda: None,
        cluster_is_present=lambda: False,
        port_is_bound=lambda: False,
    )

    projection = ledger.public_projection()
    assert projection["phase_postgres_clusters_remaining"] == 0
    assert projection["phase_ports_remaining"] == 0


def test_runtime_cleanup_failure_is_preserved(tmp_path):
    owner, ledger = _owner(tmp_path)
    owner.register_process("process-1")

    with pytest.raises(RuntimeOwnershipError, match="cleanup failed"):
        owner.cleanup_process(
            "process-1",
            terminate=lambda: (_ for _ in ()).throw(OSError("denied")),
            is_present=lambda: True,
        )

    assert ledger.public_projection()["phase_processes_remaining"] == 1

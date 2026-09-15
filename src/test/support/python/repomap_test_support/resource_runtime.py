"""Exact lifecycle evidence for phase-owned process and socket resources."""

from __future__ import annotations

from collections.abc import Callable

from repomap_test_support.resource_ledger import (
    CleanupResult,
    FinalPresence,
    ResourceKind,
    ResourceLedger,
)


class RuntimeOwnershipError(RuntimeError):
    """A runtime resource could not be cleaned and independently read back."""


class RuntimeResourceOwner:
    def __init__(self, ledger: ResourceLedger) -> None:
        self.ledger = ledger

    def register_process(self, identity: str) -> None:
        self._register(ResourceKind.PROCESS, identity, "process-owner")

    def register_socket(self, identity: str) -> None:
        self._register(ResourceKind.UNIX_SOCKET, identity, "socket-owner")

    def register_postgres(self, cluster_identity: str, port_identity: str) -> None:
        self._register(
            ResourceKind.POSTGRES_CLUSTER,
            cluster_identity,
            "postgres-container-owner",
        )
        self._register(ResourceKind.TCP_PORT, port_identity, "postgres-port-owner")

    def cleanup_process(
        self,
        identity: str,
        *,
        terminate: Callable[[], None],
        is_present: Callable[[], bool],
    ) -> None:
        self._cleanup_exact(
            ResourceKind.PROCESS,
            identity,
            cleanup=terminate,
            is_present=is_present,
        )

    def cleanup_socket(
        self,
        identity: str,
        *,
        remove: Callable[[], None],
        is_present: Callable[[], bool],
    ) -> None:
        self._cleanup_exact(
            ResourceKind.UNIX_SOCKET,
            identity,
            cleanup=remove,
            is_present=is_present,
        )

    def cleanup_postgres(
        self,
        cluster_identity: str,
        port_identity: str,
        *,
        stop: Callable[[], None],
        cluster_is_present: Callable[[], bool],
        port_is_bound: Callable[[], bool],
    ) -> None:
        cluster_kind = ResourceKind.POSTGRES_CLUSTER
        port_kind = ResourceKind.TCP_PORT
        self.ledger.mark_cleanup_attempted(cluster_kind, cluster_identity)
        self.ledger.mark_cleanup_attempted(port_kind, port_identity)
        try:
            stop()
        except Exception as error:
            self._failed(cluster_kind, cluster_identity, cluster_is_present())
            self._failed(port_kind, port_identity, port_is_bound())
            raise RuntimeOwnershipError("PostgreSQL cleanup failed") from error

        cluster_present = cluster_is_present()
        port_present = port_is_bound()
        self._complete(cluster_kind, cluster_identity, cluster_present)
        self._complete(port_kind, port_identity, port_present)
        if cluster_present:
            raise RuntimeOwnershipError("PostgreSQL cluster remains after cleanup")
        if port_present:
            raise RuntimeOwnershipError("PostgreSQL port remains after cleanup")

    def _register(self, kind: ResourceKind, identity: str, owner: str) -> None:
        self.ledger.register(
            kind,
            identity,
            creation_owner=owner,
            created_before_run=False,
            creation_observed=True,
            cleanup_required=True,
        )

    def _cleanup_exact(
        self,
        kind: ResourceKind,
        identity: str,
        *,
        cleanup: Callable[[], None],
        is_present: Callable[[], bool],
    ) -> None:
        self.ledger.mark_cleanup_attempted(kind, identity)
        try:
            cleanup()
        except Exception as error:
            self._failed(kind, identity, is_present())
            raise RuntimeOwnershipError("runtime resource cleanup failed") from error
        present = is_present()
        self._complete(kind, identity, present)
        if present:
            raise RuntimeOwnershipError("runtime resource remains after cleanup")

    def _complete(self, kind: ResourceKind, identity: str, present: bool) -> None:
        self.ledger.mark_cleanup_result(
            kind,
            identity,
            CleanupResult.FAILED if present else CleanupResult.REMOVED,
        )
        self.ledger.mark_final_presence(
            kind,
            identity,
            FinalPresence.PRESENT if present else FinalPresence.ABSENT,
        )

    def _failed(self, kind: ResourceKind, identity: str, present: bool) -> None:
        self.ledger.mark_cleanup_result(kind, identity, CleanupResult.FAILED)
        self.ledger.mark_final_presence(
            kind,
            identity,
            FinalPresence.PRESENT if present else FinalPresence.UNOBSERVED,
        )


__all__ = ["RuntimeOwnershipError", "RuntimeResourceOwner"]

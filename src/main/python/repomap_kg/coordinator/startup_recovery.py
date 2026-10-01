"""Bounded startup recovery for durable publication uncertainty."""

from __future__ import annotations

from abc import abstractmethod
from dataclasses import dataclass
from datetime import timedelta
from typing import Callable, Mapping, Protocol

from repomap_kg.coordinator._control_types import JobClaim
from repomap_kg.coordinator.limits import DEFAULT_LIMITS


class PublicationRouteChangedError(ValueError):
    """The current configured storage route does not own the durable attempt."""


class RecoveryStore(Protocol):
    def reconciliation_claims(self, limit: int) -> tuple[JobClaim, ...]: ...

    def reconcile_publication(
        self,
        claim: JobClaim,
        *,
        reconciler_instance_id: str | None = None,
        reconciler_epoch: int | None = None,
        unpublished_proved: bool = False,
    ) -> str: ...

    def acquire_singleton(self, instance_id: str, ttl: timedelta) -> int: ...

    def stop_singleton(self, instance_id: str, fencing_epoch: int) -> bool: ...


@dataclass(frozen=True)
class StartupRecoveryReport:
    """Bounded aggregate outcome for one startup recovery pass."""

    scanned: int
    resolved: int
    pending: int
    route_changed: int
    unavailable: int
    residuals: int = 0


class StartupRecoveryMixin:
    """Coordinator startup ownership and bounded recovery behavior."""

    _store: RecoveryStore
    _instance_id: str
    _singleton_ttl: timedelta
    _epoch: int | None
    _publication_reader: Callable[[object], Mapping[str, object] | None] | None
    _publication_retirer: Callable[[object], object] | None

    def startup(self, reconcile_startup: Callable[[], object]) -> int:
        epoch = self._store.acquire_singleton(
            self._instance_id, self._singleton_ttl
        )
        self._epoch = epoch
        try:
            recover_abandoned = getattr(
                self._store, "recover_abandoned_attempts", None
            )
            if recover_abandoned is not None:
                recover_abandoned(
                    self._instance_id,
                    epoch,
                    DEFAULT_LIMITS.max_nonterminal_jobs,
                )
            self._startup_recovery_report = reconcile_startup()
        except BaseException:
            self._store.stop_singleton(self._instance_id, epoch)
            self._epoch = None
            raise
        return epoch

    def recover_startup(self) -> StartupRecoveryReport:
        """Reconcile the bounded durable uncertainty set under this fence."""

        reader = self._publication_reader or (lambda _claim: None)
        retirer = getattr(self, "_publication_retirer", None)
        return recover_startup(
            self._store,
            reader,
            publication_retirer=retirer,
            instance_id=self._instance_id,
            fencing_epoch=self._require_started(),
            limit=DEFAULT_LIMITS.max_nonterminal_jobs,
        )

    @property
    def startup_recovery_report(self) -> object | None:
        return getattr(self, "_startup_recovery_report", None)

    @abstractmethod
    def _require_started(self) -> int: ...


def recover_startup(
    store: RecoveryStore,
    publication_reader: Callable[[object], Mapping[str, object] | None],
    *,
    instance_id: str,
    fencing_epoch: int,
    limit: int,
    publication_retirer: Callable[[object], object] | None = None,
) -> StartupRecoveryReport:
    """Reconcile a stable bounded set before the coordinator accepts clients."""

    resolved = 0
    pending = 0
    route_changed = 0
    unavailable = 0
    residuals = 0
    claims = store.reconciliation_claims(limit)
    for claim in claims:
        try:
            marker = publication_reader(claim)
        except PublicationRouteChangedError:
            route_changed += 1
            marker = None
        except (OSError, RuntimeError, ValueError):
            unavailable += 1
            marker = None
        if marker is not None:
            try:
                _record_marker(store, claim, marker)
            except ValueError:
                pass
        outcome = store.reconcile_publication(
            claim,
            reconciler_instance_id=instance_id,
            reconciler_epoch=fencing_epoch,
            **({"unpublished_proved": True} if marker is not None and marker.get("publication_state") == "not_started" else {}),
        )
        if outcome in {"succeeded", "queued", "failed", "cancelled", "quarantined"}:
            resolved += 1
            if outcome in {"succeeded", "queued", "failed", "cancelled"} and publication_retirer is not None:
                try:
                    publication_retirer(claim)
                except (OSError, ValueError):
                    residuals += 1
        else:
            pending += 1
    return StartupRecoveryReport(
        scanned=len(claims),
        resolved=resolved,
        pending=pending,
        route_changed=route_changed,
        unavailable=unavailable,
        residuals=residuals,
    )



def _record_marker(
    store: RecoveryStore, claim: object, marker: Mapping[str, object]
) -> None:
    recorder = getattr(store, "record_publication_marker", None)
    if recorder is None:
        return
    required = (
        "latest_run_identity",
        "source_generation",
        "config_generation",
        "extractor_generation",
        "canonicalizer_generation",
    )
    if any(marker.get(field) is None for field in required):
        return
    recorder(
        claim,
        run_identity=marker["latest_run_identity"],
        source_generation=marker["source_generation"],
        config_generation=marker["config_generation"],
        extractor_generation=marker["extractor_generation"],
        canonicalizer_generation=marker["canonicalizer_generation"],
        outcome="committed",
    )


__all__ = [
    "PublicationRouteChangedError",
    "StartupRecoveryMixin",
    "StartupRecoveryReport",
    "recover_startup",
]

"""Bounded startup recovery for durable publication uncertainty."""

from __future__ import annotations

from abc import abstractmethod
from collections import deque
from dataclasses import dataclass
from datetime import timedelta
import logging
import re
from typing import Callable, Mapping, Protocol
import threading

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
    refused: int = 0
    unexpected: tuple[str, ...] = ()


@dataclass(frozen=True)
class RecoveryDiagnostic:
    """A redacted unexpected recovery error retained until acknowledgement."""

    sequence: int
    error_type: str
    category: str = "unexpected_recovery_error"
    summary: str = ""

    def __post_init__(self) -> None:
        if not self.summary:
            object.__setattr__(self, "summary", self.error_type)
        if not self.category:
            object.__setattr__(self, "category", "unexpected_recovery_error")

    def to_dict(self) -> dict[str, object]:
        return {"category": self.category, "summary": self.summary, "sequence": self.sequence}


_logger = logging.getLogger("repomap_kg.coordinator.startup_recovery")


def _emit_structured_diagnostic_log(diagnostic: RecoveryDiagnostic) -> None:
    _logger.warning(
        "recovery diagnostic created: sequence=%d category=%s summary=%s",
        diagnostic.sequence,
        diagnostic.category,
        diagnostic.summary,
        extra={"recovery_diagnostic": diagnostic.to_dict()},
    )


def _format_unexpected_diagnostic(error: BaseException) -> str:
    name = type(error).__name__
    if not isinstance(name, str) or re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]{0,63}", name) is None:
        name = "Exception"
    return name


def _expected_refusal(error: Exception) -> bool:
    # Keep the base SQLite import surface free of the optional server driver.
    try:
        from psycopg.errors import LockNotAvailable, QueryCanceled
        from repomap_kg.coordinator._restart_fencing import FencingContentionError, StaleDurableAuthorityError
    except ImportError:
        return False
    return isinstance(error, (StaleDurableAuthorityError, FencingContentionError, LockNotAvailable, QueryCanceled))


class StartupRecoveryMixin:
    """Coordinator startup ownership and bounded recovery behavior."""

    _store: RecoveryStore
    _instance_id: str
    _singleton_ttl: timedelta
    _epoch: int | None
    _publication_reader: Callable[[object], Mapping[str, object] | None] | None
    _publication_closer: Callable[[object, object], bool] | None
    _publication_retirer: Callable[[object], object] | None
    _recovery_diagnostics: deque[RecoveryDiagnostic]
    _recovery_diagnostics_lock: threading.Lock
    _recovery_diagnostic_sequence: int

    def _record_startup_recovery_report(self, report: object) -> None:
        created: list[RecoveryDiagnostic] = []
        with self._recovery_diagnostics_lock:
            self._startup_recovery_report = report
            if isinstance(report, StartupRecoveryReport):
                for name in report.unexpected:
                    # Never retain messages, identities, routes or raw payloads.
                    safe_name = name if re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]{0,63}", name) else "Exception"
                    self._recovery_diagnostic_sequence += 1
                    diagnostic = RecoveryDiagnostic(
                        self._recovery_diagnostic_sequence, safe_name,
                    )
                    self._recovery_diagnostics.append(diagnostic)
                    while len(self._recovery_diagnostics) > 32:
                        self._recovery_diagnostics.popleft()
                    created.append(diagnostic)
        for diagnostic in created:
            _emit_structured_diagnostic_log(diagnostic)

    @property
    def recovery_diagnostics(self) -> tuple[RecoveryDiagnostic, ...]:
        """Read the bounded retained ring independently of the latest pass."""
        with self._recovery_diagnostics_lock:
            return tuple(self._recovery_diagnostics)

    def acknowledge_recovery_diagnostics(self, through_sequence: int) -> None:
        """Clear observed entries without clearing a concurrent newer error."""
        if type(through_sequence) is not int or through_sequence < 0:
            raise ValueError("diagnostic acknowledgement must be a nonnegative sequence")
        with self._recovery_diagnostics_lock:
            while self._recovery_diagnostics and self._recovery_diagnostics[0].sequence <= through_sequence:
                self._recovery_diagnostics.popleft()

    def _renew_singleton(self) -> bool:
        heartbeat = getattr(self._store, "heartbeat_singleton", None)
        if heartbeat is not None and self._epoch is not None:
            return bool(heartbeat(self._instance_id, self._epoch, self._singleton_ttl))
        return True

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
            self._record_startup_recovery_report(reconcile_startup())
        except BaseException:
            self._store.stop_singleton(self._instance_id, epoch)
            self._epoch = None
            raise
        return epoch

    def recover_startup(self) -> StartupRecoveryReport:
        """Reconcile the bounded durable uncertainty set under this fence."""

        reader = self._publication_reader or (lambda _claim: None)
        retirer = getattr(self, "_publication_retirer", None)
        closer = getattr(self, "_publication_closer", None)
        try:
            return recover_startup(
                self._store, reader, publication_closer=closer, publication_retirer=retirer,
                instance_id=self._instance_id, fencing_epoch=self._require_started(),
                limit=DEFAULT_LIMITS.max_nonterminal_jobs, renew_singleton=self._renew_singleton,
            )
        except Exception as error:
            self._record_startup_recovery_report(StartupRecoveryReport(
                0, 0, 0, 0, 0, unexpected=(_format_unexpected_diagnostic(error),),
            ))
            raise

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
    publication_closer: Callable[[object, object], bool] | None = None,
    publication_retirer: Callable[[object], object] | None = None,
    renew_singleton: Callable[[], bool] | None = None,
) -> StartupRecoveryReport:
    """Reconcile a stable bounded set before the coordinator accepts clients."""

    resolved = 0
    pending = 0
    route_changed = 0
    unavailable = 0
    residuals = 0
    refused = 0
    unexpected: list[str] = []
    claims = store.reconciliation_claims(limit)
    for index, claim in enumerate(claims):
        if renew_singleton is not None and renew_singleton() is False:
            pending += len(claims) - index
            refused += 1
            break

        if getattr(claim, "graph_lease_fencing_epoch", None) == 0:
            quarantine_op = getattr(store, "quarantine_legacy_attempt", None)
            if quarantine_op is not None:
                try:
                    if quarantine_op(
                        claim,
                        reconciler_instance_id=instance_id,
                        reconciler_epoch=fencing_epoch,
                    ):
                        resolved += 1
                    else:
                        refused += 1
                        pending += 1
                except PublicationRouteChangedError:
                    route_changed += 1
                    pending += 1
                except Exception as error:
                    if _expected_refusal(error):
                        refused += 1
                    else:
                        unexpected.append(_format_unexpected_diagnostic(error))
                    pending += 1
            else:
                pending += 1
            if renew_singleton is not None and renew_singleton() is False:
                pending += len(claims) - index - 1
                refused += 1
                break
            continue

        try:
            marker = publication_reader(claim)
        except PublicationRouteChangedError:
            route_changed += 1
            marker = None
        except OSError:
            unavailable += 1
            marker = None
        except Exception as error:
            unavailable += 1
            if _expected_refusal(error):
                refused += 1
            else:
                unexpected.append(_format_unexpected_diagnostic(error))
            marker = None
        is_unresolved = marker is None or marker.get("publication_state") == "commit_unknown"
        if is_unresolved and publication_closer is not None:
            closer_op = getattr(store, "close_unpublished_reconciliation", None)
            if closer_op is not None:
                try:
                    if closer_op(
                        claim,
                        reconciler_instance_id=instance_id,
                        reconciler_epoch=fencing_epoch,
                        file_closer=publication_closer,
                    ):
                        marker = {"publication_state": "not_started"}
                    else:
                        refused += 1
                except PublicationRouteChangedError:
                    route_changed += 1
                    marker = None
                except Exception as error:
                    if _expected_refusal(error):
                        refused += 1
                    else:
                        unexpected.append(_format_unexpected_diagnostic(error))
                    marker = None
            else:
                prover = getattr(store, "prove_worker_fenced", None)
                if prover is not None:
                    try:
                        proof = prover(
                            claim,
                            reconciler_instance_id=instance_id,
                            reconciler_epoch=fencing_epoch,
                        )
                        if proof is not None:
                            if publication_closer(claim, proof):
                                marker = {"publication_state": "not_started"}
                            else:
                                refused += 1
                        else:
                            refused += 1
                    except PublicationRouteChangedError:
                        route_changed += 1
                        marker = None
                    except Exception as error:
                        if _expected_refusal(error):
                            refused += 1
                        else:
                            unexpected.append(_format_unexpected_diagnostic(error))
                        marker = None

        if marker is not None:
            try:
                _record_marker(store, claim, marker)
            except ValueError:
                refused += 1
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

        if renew_singleton is not None and renew_singleton() is False:
            pending += len(claims) - index - 1
            refused += 1
            break
    return StartupRecoveryReport(
        scanned=len(claims),
        resolved=resolved,
        pending=pending,
        route_changed=route_changed,
        unavailable=unavailable,
        residuals=residuals,
        refused=refused,
        unexpected=tuple(unexpected),
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
    "RecoveryDiagnostic",
    "StartupRecoveryMixin",
    "StartupRecoveryReport",
    "recover_startup",
]

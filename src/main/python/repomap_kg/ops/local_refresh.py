"""Explicit SQLite Local initialization and full refresh (parent side only).

``initialize_local_graph`` creates one graph database at the current schema
(every migration in order); it never migrates an existing older database.
``refresh_local_graph`` supervises the unchanged portable semantic path:
seal sources, run the database-independent worker once, validate its bundle
in this parent process, and hand the validated seven logical families to the
SQLite publisher. There is no PostgreSQL route, maintenance admission,
coordinator, container or server in this path, and no fallback to one.

Both refuse ``local-state-layout-invalid`` before the lock when the home's
``state/`` tree is not real and owned (LOCAL10, :mod:`.local_state_layout`).

Retained-attempt reconciliation (REPOMAP-PRODUCT3-SQLITE-LOCAL3). Local attempts
use the existing owner-only portable retention records in one directory per
graph. After validation and before the publisher is entered, the attempt record
is armed with its publication identity (graph, expected generation, bundle id,
job id, attempt). An attempt is settled failed only on positive proof that
COMMIT was never attempted; every other failure leaves it armed. Every refresh
first takes the graph's publisher lock and reconciles an armed, unsettled
attempt against the accepted marker, before any source check or capture:

* accepted generation is the attempt's expected next generation with its
  bundle id, job id and attempt: settle it accepted and replay that accepted
  outcome without sources or a new generation;
* accepted generation is still the attempt's expected previous generation:
  settle it failed and refresh normally;
* anything else (unreadable database, conflicting identity, another
  generation, invalid or multiple armed records): refuse with
  ``graph-publication-reconciliation-required`` and change nothing.

An unarmed unsettled record never reached the publisher (arming precedes it
under the same lock) and is settled failed.

Durability (LOCAL7). ``sqlite-init`` fsyncs the new store levels, the
completed file and the store directory after install. Every Local attempt
record replacement (arming and settling) fsyncs the record's directory and
each retention namespace level above it through ``<home>/state``; a failed
sync is a bounded ``local-durability-*`` refusal. Arming failure refuses before the publisher;
a settle failure after publish is suppressed like any settle failure (the
database is the source of truth and the next refresh reconciles), while a
reconciliation settle failure refuses with ``attempt-record-unwritable``.
"""

from __future__ import annotations

import os
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from repomap_kg.ops.config_local import (
    SQLITE_GRAPH_STORE_RELATIVE,
    LocalSqliteConfig,
    local_graph_binding,
)
from repomap_kg.ops.config_records import OpsGraphConfig
from repomap_kg.ops._portable_retention import (
    PortableRefreshError,
    _mark_retained_terminal,
    _unsettled_retained_attempts,
)
from repomap_kg.ops.local_state_layout import LOCAL_STAGE_ID, attempts_namespace, mutable_local_state
from repomap_kg.ops.portable_refresh import (
    PortableCapture,
    capture_portable_candidate,
    portable_attempts_parent,
    portable_publication_binding,
    validate_portable_capture,
)
from repomap_kg.storage.publication import PortablePublicationBinding, RunPublicationReceipt
from repomap_kg.storage.sqlite_local import investigation_queries
from repomap_kg.storage.sqlite_local.connection import (
    initialize_graph_database,
    publisher_lock,
    read_transaction,
)
from repomap_kg.storage.sqlite_local.publisher import (
    FAMILY_ORDER,
    LocalPublication,
    publication_not_committed,
    publish_generation,
    read_accepted_generation,
    utc_timestamp,
)
from repomap_kg.storage.sqlite_local.schema import (
    NOT_INITIALIZED,
    PUBLICATION_RECONCILIATION_REQUIRED,
    PUBLICATION_REJECTED,
    LocalGraphBinding,
    LocalStoreError,
    accepted_identity,
)

ATTEMPT_BLOCK = "sqlite_local_publication"
_BLOCK_KEYS = frozenset(
    {
        "graph_id",
        "expected_generation",
        "publication_bundle_id",
        "publication_job_id",
        "publication_attempt",
    }
)


class LocalRefreshError(ValueError):
    """Bounded SQLite Local command refusal; never a fallback authority."""


@dataclass(frozen=True)
class LocalRefreshResult:
    graph_id: str
    generation: int
    run_id: int
    previous_run_id: int | None
    publication: Mapping[str, object]
    family_counts: Mapping[str, int]
    # True when an already-accepted attempt was replayed; kept out of the JSON.
    reconciled: bool = False

    def to_jsonable(self) -> dict[str, Any]:
        return {
            "command": "refresh-graph",
            "storage_backend": "sqlite",
            "result": "success",
            "graph_id": self.graph_id,
            "accepted_generation": self.generation,
            "run_id": self.run_id,
            "previous_run_id": self.previous_run_id,
            "publication": dict(self.publication),
            "family_counts": dict(self.family_counts),
        }


def _graph(config: LocalSqliteConfig, graph_id: str) -> OpsGraphConfig:
    for graph in config.graphs:
        if graph.id == graph_id:
            return graph
    raise LocalRefreshError(f"unknown graph_id: {graph_id}")


def initialize_local_graph(config: LocalSqliteConfig, graph_id: str) -> dict[str, str]:
    """Create the graph's database, or report an existing current one unchanged."""
    graph = _graph(config, graph_id)
    path = mutable_local_state(config, graph).database
    with publisher_lock(path):
        outcome = initialize_graph_database(
            path,
            local_graph_binding(graph),
            applied_at=utc_timestamp(),
            durable_ancestors=len(SQLITE_GRAPH_STORE_RELATIVE.parts),
        )
    return {
        "command": "sqlite-init",
        "storage_backend": "sqlite",
        "result": outcome,
        "graph_id": graph.id,
    }


def refresh_local_graph(
    config: LocalSqliteConfig,
    graph_id: str,
    *,
    limits: object | None = None,
) -> LocalRefreshResult:
    """Reconcile a pending attempt, then capture, validate and publish one generation."""
    graph = _graph(config, graph_id)
    if not graph.enabled:
        raise LocalRefreshError(f"graph {graph_id!r} is disabled")
    if graph.refresh_unsupported_classification is not None:
        raise LocalRefreshError(graph.refresh_unsupported_classification)
    path = mutable_local_state(config, graph, attempts=True).database
    identity = local_graph_binding(graph)
    if not path.is_file():
        raise LocalStoreError(NOT_INITIALIZED, "run ops sqlite-init for this graph first")
    with publisher_lock(path):
        replay = _reconcile(config, graph, path, identity)
        if replay is not None:
            return replay
        for binding in graph.effective_source_bindings:
            if not Path(binding.root_path_expanded).is_dir():
                raise LocalRefreshError(f"graph {graph_id!r} source root is unavailable")
        expected = read_accepted_generation(path, identity)
        capture = capture_portable_candidate(
            config, graph, authority=None, limits=limits,
            attempts_namespace=attempts_namespace(graph.id),
        )
        receipt, validated = validate_portable_capture(capture, stage_id=LOCAL_STAGE_ID)
        try:
            try:
                portable = portable_publication_binding(
                    capture, receipt, validated, stage_id=LOCAL_STAGE_ID
                )
                publication = LocalPublication(
                    binding=identity,
                    repository_name=graph.repository_name,
                    receipt=RunPublicationReceipt(
                        capture.authority.receipt().attempt,
                        capture.authority.receipt().generations,
                        portable,
                    ).validate(),
                    privacy=validated.privacy.value,
                )
                spools = validated.family_spools
                if spools is None:
                    raise LocalStoreError(PUBLICATION_REJECTED, "validated rows are unavailable")
                capture.annotate(
                    ATTEMPT_BLOCK,
                    _attempt_block(graph.id, expected, publication, portable),
                    sync_directory=True,
                )
            except BaseException:
                _settle(capture, accepted=False)  # the publisher was never entered
                raise
            try:
                result = publish_generation(
                    path,
                    publication,
                    {family: spools[family] for family in FAMILY_ORDER},
                    expected_generation=expected,
                )
            except BaseException as error:
                # Only positive proof that COMMIT was never attempted settles the
                # attempt failed; anything else stays armed for reconciliation.
                if publication_not_committed(error):
                    _settle(capture, accepted=False)
                raise
            _settle(capture, accepted=True)
        finally:
            validated.close()
    return LocalRefreshResult(
        graph_id=graph.id,
        generation=result.generation,
        run_id=result.run_id,
        previous_run_id=result.previous_run_id,
        publication=portable.public_mapping(),
        family_counts=result.family_counts,
    )


def _settle(capture: PortableCapture, *, accepted: bool) -> None:
    """Best effort: an unsettled attempt is reconciled by the next invocation."""
    with suppress(OSError, ValueError):
        capture.mark_terminal(accepted=accepted, sync_directory=True)


def _attempt_block(
    graph_id: str,
    expected: int,
    publication: LocalPublication,
    portable: PortablePublicationBinding,
) -> dict[str, object]:
    attempt = publication.receipt.attempt
    return {
        "graph_id": graph_id,
        "expected_generation": expected,
        "publication_bundle_id": portable.publication_bundle_id,
        "publication_job_id": attempt.job_id,
        "publication_attempt": attempt.attempt,
    }


def _reconciliation_required(reason: str) -> LocalStoreError:
    return LocalStoreError(PUBLICATION_RECONCILIATION_REQUIRED, reason)


def _armed_identity(block: object, graph_id: str) -> tuple[int, tuple[str, str, int]]:
    """Validate an armed block: (expected generation, (bundle, job, attempt))."""
    if not isinstance(block, dict) or set(block) != _BLOCK_KEYS or block["graph_id"] != graph_id:
        raise _reconciliation_required("attempt-record-invalid")
    expected, bundle = block["expected_generation"], block["publication_bundle_id"]
    job, attempt = block["publication_job_id"], block["publication_attempt"]
    if (
        not isinstance(expected, int) or isinstance(expected, bool) or expected < 0
        or not isinstance(attempt, int) or isinstance(attempt, bool) or attempt < 1
        or not isinstance(bundle, str) or not bundle or not isinstance(job, str) or not job
    ):
        raise _reconciliation_required("attempt-record-invalid")
    return expected, (bundle, job, attempt)


def _settle_record(record: Path, *, accepted: bool) -> None:
    try:
        _mark_retained_terminal(
            record, "terminal-accepted" if accepted else "terminal-failed", sync_directory=True
        )
    except (OSError, ValueError):
        raise _reconciliation_required("attempt-record-unwritable") from None


def _settle_unarmed(records: list[Path]) -> None:
    """Unarmed attempts never reached the publisher (arming precedes it under the lock)."""
    for record in records:
        with suppress(OSError, ValueError):
            _mark_retained_terminal(record, "terminal-failed", sync_directory=True)


def _reconcile(
    config: LocalSqliteConfig,
    graph: OpsGraphConfig,
    path: Path,
    identity: LocalGraphBinding,
) -> LocalRefreshResult | None:
    """Settle this graph's pending attempt; the caller holds the publisher lock."""
    parent = portable_attempts_parent(config, attempts_namespace(graph.id))
    if not os.path.lexists(parent):
        return None
    try:
        unsettled = _unsettled_retained_attempts(parent)
    except PortableRefreshError:
        raise _reconciliation_required("attempt-record-invalid") from None
    armed = [(record, payload[ATTEMPT_BLOCK]) for record, payload in unsettled if ATTEMPT_BLOCK in payload]
    unarmed = [record for record, payload in unsettled if ATTEMPT_BLOCK not in payload]
    if not armed:
        _settle_unarmed(unarmed)
        return None
    if len(armed) > 1:
        raise _reconciliation_required("multiple-unsettled-attempts")
    record, block = armed[0]
    expected, attempt = _armed_identity(block, graph.id)
    try:
        with read_transaction(path, identity) as connection:
            accepted = accepted_identity(connection)
            publication = (
                None if accepted is None
                else investigation_queries.status_fields(connection)["publication"]
            )
    except LocalStoreError as error:
        raise _reconciliation_required(error.code) from None
    except Exception:
        raise _reconciliation_required("accepted-state-unreadable") from None
    generation = 0 if accepted is None else accepted.generation
    if accepted is not None and publication is not None and generation == expected + 1 and (
        accepted.publication_bundle_id, accepted.publication_job_id, accepted.publication_attempt
    ) == attempt:
        _settle_record(record, accepted=True)
        _settle_unarmed(unarmed)
        return LocalRefreshResult(
            graph_id=graph.id,
            generation=accepted.generation,
            run_id=accepted.run_id,
            previous_run_id=accepted.previous_run_id,
            publication=publication,
            family_counts=dict(publication["family_counts"]),
            reconciled=True,
        )
    if generation == expected:
        _settle_record(record, accepted=False)
        _settle_unarmed(unarmed)
        return None
    if generation == expected + 1:
        raise _reconciliation_required("publication-identity-conflict")
    raise _reconciliation_required("accepted-generation-mismatch")


__all__ = (
    "ATTEMPT_BLOCK",
    "LOCAL_STAGE_ID",
    "LocalRefreshError",
    "LocalRefreshResult",
    "attempts_namespace",
    "initialize_local_graph",
    "refresh_local_graph",
)

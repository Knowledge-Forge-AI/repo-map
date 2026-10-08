"""SQLite Local ``ops refresh-enabled``: every enabled graph, in configuration order.

Each enabled graph goes through the accepted :func:`refresh_local_graph` path on
its own: its own publisher lock, retained-attempt reconciliation and one
publication. There is no transaction across graph database files, no
maintenance admission, coordinator, container or PostgreSQL route, and no
fallback to one. Disabled graphs are skipped; MCP visibility is not an
eligibility criterion (the PostgreSQL owner does not use it either).

Aggregate semantics follow the PostgreSQL ``refresh-enabled`` contract: a
graph-level refusal or failure becomes a failure row and the loop continues;
an interrupt records a ``cancelled`` row and stops; the result is ``success``,
``partial`` or ``failed``. Failure rows carry a bounded ``error_category``
(``refresh-rejected``, a SQLite Local store code, a portable-route category,
``refresh-failed`` or ``cancelled``) and path-free error text.

Conversion owner (LOCAL7 review): only ``OSError`` and ``ValueError`` become
rows. That mirrors the PostgreSQL owner, ``ops.refresh``, which converts
``OSError``, ``ValueError`` and its ``StorageSchemaError`` and
``PortableRefreshError`` subclasses. ``ValueError`` is the maintained refusal
type of the Local refresh path (``LocalRefreshError``, ``LocalStoreError``,
``PortableRefreshError``, ``OpsConfigError`` and publication receipt
validation); a row never claims success and keeps only the exception type for
anything without a bounded code. Programmer errors (``TypeError``,
``AttributeError``, ``KeyError`` and the like) are not converted and propagate.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from repomap_kg.graph.discovery import DEFAULT_DISCOVERY_EXCLUDE_PATHS
from repomap_kg.ops._portable_retention import PortableRefreshError
from repomap_kg.ops.config_local import LocalSqliteConfig
from repomap_kg.ops.config_storage import SQLITE_BACKEND
from repomap_kg.ops.local_refresh import LocalRefreshError, LocalRefreshResult, refresh_local_graph
from repomap_kg.ops.report_records import _redact_text, _refresh_safety_markers
from repomap_kg.storage.sqlite_local.schema import LocalStoreError

REFRESH_REJECTED = "refresh-rejected"
REFRESH_FAILED = "refresh-failed"
REFRESH_CANCELLED = "cancelled"
_CANCELLED_TEXT = "refresh cancelled; the next refresh settles any pending publication"


@dataclass(frozen=True)
class LocalRefreshFailure:
    graph_id: str
    error_category: str
    error: str

    def to_jsonable(self) -> dict[str, Any]:
        return {
            "graph_id": self.graph_id,
            "result": "failure",
            "error_category": self.error_category,
            "error": self.error,
        }


LocalRefreshOutcome = LocalRefreshResult | LocalRefreshFailure


def refresh_enabled_local_graphs(
    config: LocalSqliteConfig,
    *,
    refresh: Callable[[LocalSqliteConfig, str], LocalRefreshResult] | None = None,
) -> tuple[LocalRefreshOutcome, ...]:
    run = refresh or refresh_local_graph
    outcomes: list[LocalRefreshOutcome] = []
    for graph in config.graphs:
        if not graph.enabled:
            continue
        try:
            outcomes.append(run(config, graph.id))
        except KeyboardInterrupt:
            outcomes.append(LocalRefreshFailure(graph.id, REFRESH_CANCELLED, _CANCELLED_TEXT))
            break
        except (OSError, ValueError) as error:
            outcomes.append(_failure(graph.id, error))
    return tuple(outcomes)


def _failure(graph_id: str, error: OSError | ValueError) -> LocalRefreshFailure:
    """Only path-free refusals keep their text; anything else is category plus type."""
    if isinstance(error, LocalRefreshError):
        return LocalRefreshFailure(graph_id, REFRESH_REJECTED, _redact_text(str(error)))
    if isinstance(error, LocalStoreError):
        return LocalRefreshFailure(graph_id, error.code, _redact_text(str(error)))
    category = error.category if isinstance(error, PortableRefreshError) else REFRESH_FAILED
    return LocalRefreshFailure(graph_id, category, f"{category}: {type(error).__name__}")


def _row(outcome: LocalRefreshOutcome) -> dict[str, Any]:
    if isinstance(outcome, LocalRefreshFailure):
        return outcome.to_jsonable()
    row = outcome.to_jsonable()
    del row["command"], row["storage_backend"]
    return row


def local_refresh_enabled_to_jsonable(
    config: LocalSqliteConfig,
    outcomes: Sequence[LocalRefreshOutcome],
) -> dict[str, Any]:
    failed = sum(1 for outcome in outcomes if isinstance(outcome, LocalRefreshFailure))
    refreshed = len(outcomes) - failed
    overall = "success"
    if failed and refreshed:
        overall = "partial"
    elif failed:
        overall = "failed"
    return {
        "command": "refresh-enabled",
        "storage_backend": SQLITE_BACKEND,
        "config_path": config.config_path,
        "schema_version": config.schema_version,
        "result": overall,
        "graph_count": len(outcomes),
        "refreshed_graph_count": refreshed,
        "failed_graph_count": failed,
        "graphs": [_row(outcome) for outcome in outcomes],
        "watch": {"implemented": False, "status": "deferred"},
        "include_exclude": {
            "implemented": True,
            "status": "implemented",
            "default_exclude_paths_count": len(DEFAULT_DISCOVERY_EXCLUDE_PATHS),
        },
        "safety": _refresh_safety_markers(),
    }


def format_local_refresh_enabled_table(
    config: LocalSqliteConfig,
    outcomes: Sequence[LocalRefreshOutcome],
) -> str:
    payload = local_refresh_enabled_to_jsonable(config, outcomes)
    lines = [
        "RepoMap ops refresh result",
        (
            "summary: command=refresh-enabled "
            f"storage={SQLITE_BACKEND} "
            f"result={payload['result']} "
            f"graphs={payload['graph_count']} "
            f"refreshed={payload['refreshed_graph_count']} "
            f"failed={payload['failed_graph_count']}"
        ),
        "id | result | generation | error_category",
    ]
    for row in payload["graphs"]:
        lines.append(
            " | ".join(
                (
                    str(row["graph_id"]),
                    str(row["result"]),
                    str(row.get("accepted_generation") or "-"),
                    str(row.get("error_category") or "-"),
                )
            )
        )
    lines.append(
        "safety: source_trees_mutated=false destructive_db_actions=false "
        "cross_graph_transaction=false postgres_fallback=false"
    )
    return "\n".join(lines)


__all__ = (
    "LocalRefreshFailure",
    "LocalRefreshOutcome",
    "REFRESH_CANCELLED",
    "REFRESH_FAILED",
    "REFRESH_REJECTED",
    "format_local_refresh_enabled_table",
    "local_refresh_enabled_to_jsonable",
    "refresh_enabled_local_graphs",
)

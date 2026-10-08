"""Home-level storage backend selector for RepoMap operations config.

A home declares at most one backend in ``[storage] backend``. An absent
section keeps the PostgreSQL meaning of every existing home. SQLite Local homes
are parsed only by the SQLite-capable loader in ``ops.config_local``; the
PostgreSQL loaders refuse them before deriving any PostgreSQL setting.

Backend authority across a layered home (:func:`merge_storage_declarations`):
the first file in load order is the base and fixes the backend, either by its
explicit ``[storage]`` table or, when that table is absent, as PostgreSQL. A
later file may omit ``[storage]`` or repeat the same backend. A later file
without ``[storage]`` that carries PostgreSQL-only sections declares
PostgreSQL implicitly. Every other declaration is a conflict: an overlay can
never switch a home between PostgreSQL and SQLite.
"""

from __future__ import annotations

from typing import Any, Literal, Mapping, Sequence

from repomap_kg.ops.config_helpers import (
    OpsConfigDiagnostic,
    unknown_field_diagnostics,
)
from repomap_kg.ops.config_records import OpsConfigError

StorageBackend = Literal["postgresql", "sqlite"]

POSTGRESQL_BACKEND: StorageBackend = "postgresql"
SQLITE_BACKEND: StorageBackend = "sqlite"
KNOWN_STORAGE_FIELDS = frozenset(("backend",))
POSTGRESQL_ONLY_SECTIONS = ("postgres", "runtime")
SQLITE_LOCAL_HOME_REQUIRES_LOCAL_COMMAND = "sqlite-local-home-requires-local-command"
STORAGE_BACKEND_CONFLICT = "storage-backend-conflict"


def parse_storage_section(
    payload: Any,
) -> tuple[StorageBackend, list[OpsConfigDiagnostic]]:
    """Return the declared backend; an absent section means PostgreSQL."""
    diagnostics: list[OpsConfigDiagnostic] = []
    if payload is None:
        return POSTGRESQL_BACKEND, diagnostics
    if not isinstance(payload, dict):
        diagnostics.append(
            OpsConfigDiagnostic("error", "invalid-section", "storage", "storage must be a table")
        )
        return POSTGRESQL_BACKEND, diagnostics
    for diagnostic in unknown_field_diagnostics(payload, KNOWN_STORAGE_FIELDS, "storage"):
        diagnostics.append(
            OpsConfigDiagnostic("error", diagnostic.code, diagnostic.path, diagnostic.message)
        )
    backend = payload.get("backend")
    if backend == SQLITE_BACKEND:
        return SQLITE_BACKEND, diagnostics
    if backend != POSTGRESQL_BACKEND:
        diagnostics.append(
            OpsConfigDiagnostic(
                "error",
                "unsupported-storage-backend",
                "storage.backend",
                "storage.backend must be postgresql or sqlite",
            )
        )
    return POSTGRESQL_BACKEND, diagnostics


def storage_backend_conflict(
    source: str,
    base: str,
    *,
    base_backend: StorageBackend,
    base_implicit: bool = False,
    implicit: bool = False,
) -> OpsConfigDiagnostic:
    """A later file may not reinterpret the backend its home's base fixes."""
    fixed = f"{base_backend} backend of {base}"
    if base_implicit:
        fixed += " (it declares no [storage] table)"
    if implicit:
        return OpsConfigDiagnostic(
            "error",
            STORAGE_BACKEND_CONFLICT,
            f"{source}:storage",
            f"{STORAGE_BACKEND_CONFLICT}: {source} carries PostgreSQL-only settings, "
            f"which conflict with the {fixed}",
        )
    return OpsConfigDiagnostic(
        "error",
        STORAGE_BACKEND_CONFLICT,
        f"{source}:storage.backend",
        f"{STORAGE_BACKEND_CONFLICT}: storage.backend conflicts with the {fixed}",
    )


def _declared_backend(storage: Any) -> StorageBackend | None:
    """Return an explicit table's backend, or ``None`` when it is invalid."""
    if isinstance(storage, dict):
        backend = storage.get("backend")
        if backend == SQLITE_BACKEND:
            return SQLITE_BACKEND
        if backend == POSTGRESQL_BACKEND:
            return POSTGRESQL_BACKEND
    return None


def merge_storage_declarations(
    file_payloads: Sequence[tuple[str, Mapping[str, Any]]],
) -> tuple[Any, list[OpsConfigDiagnostic]]:
    """Return the base file's ``[storage]`` table and every later conflict.

    Only the base table reaches the merged payload, so backend selection,
    routing and the builders' refusal order all see the base's backend. An
    invalid base table is reported by the builders; later tables are
    validated here with source-prefixed paths.
    """
    diagnostics: list[OpsConfigDiagnostic] = []
    if not file_payloads:
        return None, diagnostics
    base, base_payload = file_payloads[0]
    base_storage = base_payload.get("storage")
    base_implicit = base_storage is None
    base_backend = POSTGRESQL_BACKEND if base_implicit else _declared_backend(base_storage)
    for source, payload in file_payloads[1:]:
        storage = payload.get("storage")
        implicit = storage is None
        if implicit:
            if not any(section in payload for section in POSTGRESQL_ONLY_SECTIONS):
                continue
            declared: StorageBackend | None = POSTGRESQL_BACKEND
        else:
            _backend, storage_diagnostics = parse_storage_section(storage)
            diagnostics.extend(
                OpsConfigDiagnostic(
                    item.severity, item.code, f"{source}:{item.path}", item.message
                )
                for item in storage_diagnostics
            )
            declared = _declared_backend(storage)
        if base_backend is not None and declared is not None and declared != base_backend:
            diagnostics.append(
                storage_backend_conflict(
                    source,
                    base,
                    base_backend=base_backend,
                    base_implicit=base_implicit,
                    implicit=implicit,
                )
            )
    return base_storage, diagnostics


def refuse_sqlite_home(
    payload: Any,
    diagnostics: list[OpsConfigDiagnostic],
) -> None:
    """Refuse a SQLite Local home in a PostgreSQL-only loader."""
    backend, storage_diagnostics = parse_storage_section(payload)
    diagnostics.extend(storage_diagnostics)
    if backend == SQLITE_BACKEND:
        raise OpsConfigError(
            [
                *(item for item in diagnostics if item.severity == "error"),
                OpsConfigDiagnostic(
                    "error",
                    SQLITE_LOCAL_HOME_REQUIRES_LOCAL_COMMAND,
                    "storage.backend",
                    "this home selects SQLite Local storage; this command supports "
                    "PostgreSQL homes only (Local commands: ops sqlite-init, "
                    "sqlite-backup, sqlite-restore, sqlite-upgrade, sqlite-cleanup, config-check, graphs, "
                    "refresh-preflight, refresh-graph, refresh-enabled, and mcp serve)",
                ),
            ]
        )


__all__ = (
    "KNOWN_STORAGE_FIELDS",
    "POSTGRESQL_BACKEND",
    "POSTGRESQL_ONLY_SECTIONS",
    "SQLITE_BACKEND",
    "SQLITE_LOCAL_HOME_REQUIRES_LOCAL_COMMAND",
    "STORAGE_BACKEND_CONFLICT",
    "StorageBackend",
    "merge_storage_declarations",
    "parse_storage_section",
    "refuse_sqlite_home",
    "storage_backend_conflict",
)

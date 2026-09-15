"""Deterministic graph migration discovery, records, and SQL construction."""

from __future__ import annotations

import hashlib
import re
import sysconfig
from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from repomap_kg.storage.errors import StorageSchemaError
from repomap_kg.storage.row_helpers import clean_yaml_value

CHANGESET_PATTERN = re.compile(r"^--changeset\s+(\S+)")


@dataclass(frozen=True)
class Migration:
    path: Path
    changeset_id: str
    ordinal: int
    relative_path: str
    checksum: str


class GraphSchemaStatus(str, Enum):
    UNINITIALIZED = "uninitialized"
    CURRENT = "current"
    BEHIND = "behind"
    UNMANAGED = "unmanaged"
    DIVERGED = "diverged"


@dataclass(frozen=True)
class GraphSchemaReadiness:
    status: GraphSchemaStatus
    expected_version: str
    applied_version: str | None
    expected_count: int
    applied_count: int

    @property
    def ready(self) -> bool:
        return self.status is GraphSchemaStatus.CURRENT


def default_rdbms_root() -> Path:
    source_root = Path(__file__).resolve().parents[3] / "resources" / "rdbms"
    if source_root.is_dir():
        return source_root
    return Path(sysconfig.get_path("data")) / "share" / "repomap-kg" / "rdbms"


def discover_migrations(rdbms_root: Path | str | None = None) -> tuple[Migration, ...]:
    root = Path(rdbms_root) if rdbms_root is not None else default_rdbms_root()
    changelog = root / "changelog.yaml"
    if not changelog.exists():
        raise StorageSchemaError(f"missing changelog: {changelog}")

    paths = []
    for include_path in include_all_paths(changelog):
        include_root = root / include_path
        if not include_root.exists():
            raise StorageSchemaError(f"missing includeAll path: {include_path}")
        for sql_path in sorted(include_root.rglob("*.sql")):
            paths.append(sql_path)

    if not paths:
        raise StorageSchemaError(f"no SQL migrations found under {root}")
    migrations = tuple(
        migration_from_path(path, root=root, ordinal=ordinal)
        for ordinal, path in enumerate(paths, start=1)
    )
    changeset_ids = [migration.changeset_id for migration in migrations]
    if len(changeset_ids) != len(set(changeset_ids)):
        raise StorageSchemaError("duplicate migration changeset identity")
    return tuple(migrations)


def include_all_paths(changelog: Path) -> tuple[str, ...]:
    paths = []
    in_include_all = False
    for raw_line in changelog.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("- includeAll:") or line == "includeAll:":
            in_include_all = True
            continue
        if in_include_all and line.startswith("path:"):
            paths.append(clean_yaml_value(line.removeprefix("path:").strip()))
            in_include_all = False
    if not paths:
        raise StorageSchemaError(f"no includeAll paths found in {changelog}")
    return tuple(paths)


def migration_from_path(path: Path, *, root: Path, ordinal: int) -> Migration:
    lines = path.read_text(encoding="utf-8").splitlines()
    first_content = next((line.strip().lower() for line in lines if line.strip()), "")
    if first_content != "--liquibase formatted sql":
        raise StorageSchemaError(f"{path} is not liquibase formatted sql")

    for line in lines:
        match = CHANGESET_PATTERN.match(line.strip())
        if match:
            return Migration(
                path=path,
                changeset_id=match.group(1),
                ordinal=ordinal,
                relative_path=path.relative_to(root).as_posix(),
                checksum=hashlib.sha256(path.read_bytes()).hexdigest(),
            )
    raise StorageSchemaError(f"{path} is missing a changeset")


def graph_schema_initialization_sql(
    rdbms_root: Path | str | None = None,
) -> str:
    """Build the authoritative transaction for one fresh graph database."""

    return _migration_script(
        discover_migrations(rdbms_root),
        initialize_ledger=True,
    )


def graph_schema_ledger_bootstrap_sql(
    rdbms_root: Path | str | None = None,
) -> str:
    """Build the ledger-only transaction for an exact pre-ledger schema."""

    migrations = discover_migrations(rdbms_root)
    statements = ["BEGIN;", *_ledger_create_statements()]
    statements.extend(_ledger_insert_statement(migration) for migration in migrations)
    statements.append("COMMIT;")
    return "\n".join(statements) + "\n"


def graph_schema_forward_sql(
    applied_count: int,
    rdbms_root: Path | str | None = None,
    *,
    target_count: int | None = None,
) -> str:
    """Build one transaction for an exact nonempty pending migration suffix."""

    migrations = discover_migrations(rdbms_root)
    target = len(migrations) if target_count is None else target_count
    if (
        applied_count <= 0
        or target <= applied_count
        or target > len(migrations)
    ):
        raise StorageSchemaError(
            "forward migration requires an exact nonempty applied prefix"
        )
    return _migration_script(
        migrations[applied_count:target],
        initialize_ledger=False,
    )


def _migration_script(
    migrations: Sequence[Migration], *, initialize_ledger: bool
) -> str:
    statements = ["BEGIN;"]
    if initialize_ledger:
        statements.extend(_ledger_create_statements())
    for migration in migrations:
        statements.append(migration.path.read_text(encoding="utf-8").rstrip())
        statements.append(_ledger_insert_statement(migration))
    statements.append("COMMIT;")
    return "\n".join(statements) + "\n"


def _ledger_create_statements() -> tuple[str, str]:
    return (
        "CREATE TABLE repomap_schema_migrations (\n"
        "    ordinal INTEGER PRIMARY KEY CHECK (ordinal > 0),\n"
        "    changeset_id TEXT NOT NULL UNIQUE,\n"
        "    migration_path TEXT NOT NULL UNIQUE,\n"
        "    checksum TEXT NOT NULL CHECK (checksum ~ '^[0-9a-f]{64}$'),\n"
        "    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()\n"
        ");",
        "COMMENT ON TABLE repomap_schema_migrations IS "
        "'repomap-graph-schema-ledger:1';",
    )


def _ledger_insert_statement(migration: Migration) -> str:
    return (
        "INSERT INTO repomap_schema_migrations "
        "(ordinal, changeset_id, migration_path, checksum) VALUES ("
        f"{migration.ordinal}, {_sql_literal(migration.changeset_id)}, "
        f"{_sql_literal(migration.relative_path)}, "
        f"{_sql_literal(migration.checksum)});"
    )


def _sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"

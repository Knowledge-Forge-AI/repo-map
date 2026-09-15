from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from repomap_kg.storage import (
    GraphSchemaStatus,
    StorageSchemaError,
    apply_migrations,
    discover_migrations,
    graph_schema_readiness,
    graph_schema_ledger_bootstrap_sql,
)


def _migration_root(tmp_path: Path) -> Path:
    root = tmp_path / "rdbms"
    migrations = root / "2026"
    migrations.mkdir(parents=True)
    (root / "changelog.yaml").write_text(
        "databaseChangeLog:\n"
        "  - includeAll:\n"
        "      path: 2026\n"
        "      relativeToChangelogFile: true\n",
        encoding="utf-8",
    )
    (migrations / "01-first.sql").write_text(
        "--liquibase formatted sql\n"
        "--changeset test:001-first\n"
        "CREATE TABLE first_table(id BIGINT PRIMARY KEY);\n",
        encoding="utf-8",
    )
    (migrations / "02-second.sql").write_text(
        "--liquibase formatted sql\n"
        "--changeset test:002-second\n"
        "CREATE TABLE second_table(id BIGINT PRIMARY KEY);\n",
        encoding="utf-8",
    )
    return root


def _result(stdout: str) -> SimpleNamespace:
    return SimpleNamespace(stdout=stdout)


def test_arch5a2_ledger_bootstrap_uses_catalog_without_replaying_ddl(
    tmp_path: Path,
) -> None:
    script = graph_schema_ledger_bootstrap_sql(_migration_root(tmp_path))

    assert script.startswith("BEGIN;\n")
    assert script.rstrip().endswith("COMMIT;")
    assert "CREATE TABLE repomap_schema_migrations" in script
    assert script.count("INSERT INTO repomap_schema_migrations") == 2
    assert "CREATE TABLE first_table" not in script
    assert "CREATE TABLE second_table" not in script


def test_arch5a1_catalog_has_stable_order_paths_and_checksums(tmp_path: Path) -> None:
    migrations = discover_migrations(_migration_root(tmp_path))

    assert [migration.ordinal for migration in migrations] == [1, 2]
    assert [migration.relative_path for migration in migrations] == [
        "2026/01-first.sql",
        "2026/02-second.sql",
    ]
    assert all(len(migration.checksum) == 64 for migration in migrations)


def test_arch5a1_catalog_rejects_duplicate_changeset_identity(tmp_path: Path) -> None:
    root = _migration_root(tmp_path)
    (root / "2026" / "02-second.sql").write_text(
        "--liquibase formatted sql\n"
        "--changeset test:001-first\n"
        "SELECT 2;\n",
        encoding="utf-8",
    )

    with pytest.raises(StorageSchemaError, match="duplicate migration changeset"):
        discover_migrations(root)


def test_arch5a1_readiness_classifies_exact_prefix_and_checksum_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _migration_root(tmp_path)
    migrations = discover_migrations(root)
    outputs = iter(
        (
            _result("repomap_schema_migrations\n"),
            _result(
                f"1\ttest:001-first\t2026/01-first.sql\t{migrations[0].checksum}\n"
            ),
            _result("repomap_schema_migrations\n"),
            _result(
                "1\ttest:001-first\t2026/01-first.sql\t"
                + "0" * 64
                + "\n"
            ),
        )
    )
    monkeypatch.setattr(
        "repomap_kg.storage.main.run_psql", lambda *args, **kwargs: next(outputs)
    )

    behind = graph_schema_readiness(root, ["-d", "graph"])
    diverged = graph_schema_readiness(root, ["-d", "graph"])

    assert behind.status is GraphSchemaStatus.BEHIND
    assert behind.applied_count == 1
    assert behind.expected_count == 2
    assert diverged.status is GraphSchemaStatus.DIVERGED


def test_arch5a1_apply_uses_one_transaction_and_is_exact_current(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _migration_root(tmp_path)
    migrations = discover_migrations(root)
    outputs = iter(
        (
            _result(""),
            _result(""),
            _result("repomap_schema_migrations\nfirst_table\nsecond_table\n"),
            _result(
                "".join(
                    f"{migration.ordinal}\t{migration.changeset_id}\t"
                    f"{migration.relative_path}\t{migration.checksum}\n"
                    for migration in migrations
                )
            ),
        )
    )
    calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def run(*args, **kwargs):
        calls.append((args, kwargs))
        return next(outputs)

    monkeypatch.setattr("repomap_kg.storage.main.run_psql", run)

    applied = apply_migrations(root, ["-d", "graph"], psql_command="psql")

    script = next(
        kwargs["input_text"] for _, kwargs in calls if kwargs.get("input_text")
    )
    assert isinstance(script, str)
    assert applied == migrations
    assert script.startswith("BEGIN;\n")
    assert script.rstrip().endswith("COMMIT;")
    assert script.count("INSERT INTO repomap_schema_migrations") == 2
    assert "CREATE TABLE repomap_schema_migrations" in script


def test_arch5a1_apply_refuses_unmanaged_nonempty_schema(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _migration_root(tmp_path)
    monkeypatch.setattr(
        "repomap_kg.storage.main.run_psql",
        lambda *args, **kwargs: _result("repositories\n"),
    )

    with pytest.raises(StorageSchemaError, match="unmanaged graph schema"):
        apply_migrations(root, ["-d", "graph"])


def test_arch5a1_apply_runs_only_pending_prefix_suffix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _migration_root(tmp_path)
    migrations = discover_migrations(root)
    first_row = (
        f"1\t{migrations[0].changeset_id}\t{migrations[0].relative_path}\t"
        f"{migrations[0].checksum}\n"
    )
    all_rows = first_row + (
        f"2\t{migrations[1].changeset_id}\t{migrations[1].relative_path}\t"
        f"{migrations[1].checksum}\n"
    )
    outputs = iter(
        (
            _result("first_table\nrepomap_schema_migrations\n"),
            _result(first_row),
            _result(""),
            _result(
                "first_table\nrepomap_schema_migrations\nsecond_table\n"
            ),
            _result(all_rows),
        )
    )
    scripts: list[str] = []

    def run(*args, **kwargs):
        if kwargs.get("input_text"):
            scripts.append(kwargs["input_text"])
        return next(outputs)

    monkeypatch.setattr("repomap_kg.storage.main.run_psql", run)

    apply_migrations(root, ["-d", "graph"])

    assert len(scripts) == 1
    assert "CREATE TABLE repomap_schema_migrations" not in scripts[0]
    assert "CREATE TABLE first_table" not in scripts[0]
    assert "CREATE TABLE second_table" in scripts[0]


def test_arch5a1_readiness_rejects_malformed_ledger_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _migration_root(tmp_path)
    outputs = iter(
        (
            _result("repomap_schema_migrations\n"),
            _result("not-a-ledger-row\n"),
        )
    )
    monkeypatch.setattr(
        "repomap_kg.storage.main.run_psql", lambda *args, **kwargs: next(outputs)
    )

    with pytest.raises(StorageSchemaError, match="invalid graph schema ledger"):
        graph_schema_readiness(root, ["-d", "graph"])


def test_arch5a1_apply_requires_exact_current_postcondition(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _migration_root(tmp_path)
    outputs = iter((_result(""), _result(""), _result("")))
    monkeypatch.setattr(
        "repomap_kg.storage.main.run_psql", lambda *args, **kwargs: next(outputs)
    )

    with pytest.raises(StorageSchemaError, match="not exact-current"):
        apply_migrations(root, ["-d", "graph"])

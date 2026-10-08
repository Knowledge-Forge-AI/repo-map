"""Exact-prefix, backup-verified control migration repair."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from repomap_kg.coordinator import _control_schema as schema
from repomap_kg.coordinator._control_types import ControlSchemaError
from repomap_test_support.fencing_control_fakes import FencingControl
from repomap_kg.coordinator._control_types import JobClaim


def test_graph_lease_epoch_migration_is_append_only() -> None:
    migrations = schema.discover_control_migrations()
    assert migrations[0].relative_path == "2026/07/13-001-async2-create-control-schema.sql"
    assert migrations[-2].relative_path == "2026/10/02-001-repair4-persist-graph-lease-epoch.sql"
    sql = migrations[-2].path.read_text()
    assert "ALTER TABLE job_attempts" in sql and "ALTER TABLE graph_leases" in sql
    assert sql.count("ADD COLUMN graph_lease_fencing_epoch") == 2
    assert "DEFAULT 0" in sql

    assert migrations[-1].relative_path == "2026/10/03-001-repair6-persist-supervisor-digest.sql"
    digest_sql = migrations[-1].path.read_text()
    assert "ALTER TABLE job_attempts" in digest_sql
    assert "ADD COLUMN supervisor_registration_digest TEXT" in digest_sql
    assert "CHECK (supervisor_registration_digest IS NULL OR supervisor_registration_digest ~ '^[0-9a-f]{64}$')" in digest_sql


@pytest.mark.parametrize("backup", [False, True])
def test_ledger_upgrade_requires_backup_and_known_prefix(backup, monkeypatch) -> None:
    control = FencingControl(JobClaim("job", "graph", 1, "owner", 1))
    monkeypatch.setattr(schema, "control_schema_readiness_connection", lambda c: schema.ControlSchemaReadiness(schema.ControlSchemaStatus.DIVERGED, 2, 1))
    with pytest.raises(ControlSchemaError):
        schema.upgrade_ledgered_schema(control.connect, expected_manifest=(), backup_verified=backup)
    assert not any("ALTER" in sql for sql, _ in control.executions)


def test_ledger_upgrade_applies_suffix_and_requires_exact_result(tmp_path, monkeypatch) -> None:
    control = FencingControl(JobClaim("job", "graph", 1, "owner", 1))
    migration_path = tmp_path / "upgrade.sql"
    migration_path.write_text("ALTER TABLE fixture ADD COLUMN lease_epoch BIGINT;")
    migration = SimpleNamespace(path=migration_path, ordinal=2, changeset_id="test:upgrade", relative_path="upgrade.sql", checksum="a" * 64)
    states = iter([schema.ControlSchemaReadiness(schema.ControlSchemaStatus.BEHIND, 2, 1), schema.ControlSchemaReadiness(schema.ControlSchemaStatus.CURRENT, 2, 2)])
    monkeypatch.setattr(schema, "control_schema_readiness_connection", lambda c: next(states))
    monkeypatch.setattr(schema, "discover_control_migrations", lambda: (None, migration))
    monkeypatch.setattr(schema, "control_schema_manifest_connection", lambda c: ("current",))
    schema.upgrade_ledgered_schema(control.connect, expected_manifest=("current",), backup_verified=True)
    assert control.executions[0][0].startswith("LOCK TABLE")
    assert any(sql == migration_path.read_text() for sql, _ in control.executions)
    assert any("INSERT INTO repomap_control_schema_migrations" in sql for sql, _ in control.executions)


def test_ledger_upgrade_refuses_nonmatching_schema_result(monkeypatch) -> None:
    control = FencingControl(JobClaim("job", "graph", 1, "owner", 1))
    states = iter([schema.ControlSchemaReadiness(schema.ControlSchemaStatus.BEHIND, 1, 1), schema.ControlSchemaReadiness(schema.ControlSchemaStatus.CURRENT, 1, 1)])
    monkeypatch.setattr(schema, "control_schema_readiness_connection", lambda c: next(states))
    monkeypatch.setattr(schema, "discover_control_migrations", lambda: ())
    monkeypatch.setattr(schema, "control_schema_manifest_connection", lambda c: ("unexpected",))
    with pytest.raises(ControlSchemaError, match="not exact-current"):
        schema.upgrade_ledgered_schema(control.connect, expected_manifest=("current",), backup_verified=True)

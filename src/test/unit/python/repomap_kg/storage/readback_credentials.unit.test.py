"""Credentials stay in memory and out of readback failure chains."""

import os
from types import SimpleNamespace
import traceback

import pytest

from repomap_kg.ops.readback import _psycopg_error_details
from repomap_kg.storage import readback_driver as driver
from repomap_kg.storage.errors import StorageSchemaError


PASSWORD = "public-fixture-password"


def test_psycopg_credential_failure_has_only_bounded_diagnostics(monkeypatch):
    class OperationalError(Exception):
        sqlstate = "28P01"

    OperationalError.__module__ = "psycopg"

    def connect(**kwargs):
        assert kwargs["password"] == PASSWORD
        raise OperationalError(PASSWORD)

    monkeypatch.setattr(driver, "_import_psycopg", lambda: SimpleNamespace(connect=connect))
    with pytest.raises(StorageSchemaError) as caught:
        driver.execute_json_readback_with_driver(
            "SELECT 1", driver="psycopg", psql_args=("-U", "repomap_read_status"),
            psql_command="psql", label="fixture", expected_shape="object", password=PASSWORD,
        )
    assert PASSWORD not in "".join(traceback.format_exception(caught.value))
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    assert _psycopg_error_details(caught.value) == ("28P01", True)


def test_psql_credential_failure_does_not_retain_raw_error(monkeypatch):
    def run(*args, **kwargs):
        raise StorageSchemaError(PASSWORD)

    monkeypatch.setattr(driver, "run_psql", run)
    with pytest.raises(StorageSchemaError) as caught:
        driver.execute_json_readback_with_driver(
            "SELECT 1", driver="psql", psql_args=("-U", "repomap_read_status"),
            psql_command="psql", label="fixture", expected_shape="object", password=PASSWORD,
        )
    assert PASSWORD not in "".join(traceback.format_exception(caught.value))
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


def test_psql_password_uses_only_private_child_environment(monkeypatch):
    monkeypatch.setenv("PGPASSWORD", "ambient-fixture")
    monkeypatch.setenv("REPOMAP_PG_PASSWORD", "ambient-admin-fixture")
    before = dict(os.environ)

    def run(command, *, input_text, env):
        assert PASSWORD not in repr(command)
        assert env["PGPASSWORD"] == PASSWORD
        assert "REPOMAP_PG_PASSWORD" not in env
        return SimpleNamespace(stdout='{"ok":true}')

    monkeypatch.setattr(driver, "run_psql", run)
    assert driver.execute_json_readback_with_driver(
        "SELECT 1", driver="psql", psql_args=("-U", "repomap_read_status"),
        psql_command="psql", label="fixture", expected_shape="object", password=PASSWORD,
    ) == {"ok": True}
    assert dict(os.environ) == before

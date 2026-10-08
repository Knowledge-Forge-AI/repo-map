from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path

import pytest

from repomap_kg.ops.config import load_ops_config_home
from repomap_kg.runtime.database_role_contract import (
    READ_STATUS_PASSWORD_ENV,
    READ_STATUS_ROLE,
    read_configured_postgres_password,
    read_read_status_password,
)
from repomap_kg.runtime.local import setup_local_runtime
from repomap_kg.runtime.postgres_route import readback_postgres_authority


def _local_config(tmp_path: Path):
    home = tmp_path / "home"
    setup_local_runtime(home)
    config_path = next(home.glob("*.rpl.toml"))
    config_path.write_text(
        config_path.read_text(encoding="utf-8").replace(
            "direct_host_port_enabled = false",
            "direct_host_port_enabled = true",
        ),
        encoding="utf-8",
    )
    return home, load_ops_config_home(home)


def test_setup_default_local_native_projects_read_status_secret_without_ambient_admin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home, config = _local_config(tmp_path)
    env_path = home / "runtime" / ".env"
    before_bytes = env_path.read_bytes()
    before_mode = env_path.stat().st_mode
    read_secret = read_read_status_password(home)
    monkeypatch.setenv("REPOMAP_PG_PASSWORD", "ambient-admin")
    monkeypatch.setenv("PGPASSWORD", "ambient-admin")

    authority = readback_postgres_authority(config)

    assert authority.projected_read_status is True
    assert authority.postgres.user == READ_STATUS_ROLE
    assert authority.postgres.password_env == READ_STATUS_PASSWORD_ENV
    assert authority.password == read_secret
    assert authority.password != "ambient-admin"
    assert "ambient-admin" not in repr(authority)
    assert read_secret not in repr(authority)
    assert env_path.read_bytes() == before_bytes
    assert env_path.stat().st_mode == before_mode
    assert os.environ["PGPASSWORD"] == "ambient-admin"


def test_custom_user_and_password_env_remain_custom_and_do_not_read_runtime_secret(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home, config = _local_config(tmp_path)
    monkeypatch.setenv("CUSTOM_READBACK_PASSWORD", "custom-secret")
    monkeypatch.setattr("repomap_kg.runtime.postgres_route.read_read_status_password",
                        lambda _home: pytest.fail("custom authority read runtime secrets"))
    custom = replace(
        config,
        postgres=replace(
            config.postgres,
            user="custom_reader",
            password_env="CUSTOM_READBACK_PASSWORD",
        ),
    )

    authority = readback_postgres_authority(custom)

    assert authority.projected_read_status is False
    assert authority.postgres.user == "custom_reader"
    assert authority.password == "custom-secret"
    assert "custom-secret" not in repr(authority)


@pytest.mark.parametrize(
    "text",
    (
        "REPOMAP_READ_STATUS_PASSWORD=\n",
        "REPOMAP_READ_STATUS_PASSWORD=   \n",
        "REPOMAP_READ_STATUS_PASSWORD=one\nREPOMAP_READ_STATUS_PASSWORD=two\n",
        "malformed-runtime-line\n",
    ),
)
def test_read_status_secret_rejects_ambiguous_or_malformed_runtime_authority(
    tmp_path: Path, text: str
) -> None:
    home, _ = _local_config(tmp_path)
    env_path = home / "runtime" / ".env"
    env_path.write_text(text, encoding="utf-8")
    env_path.chmod(0o600)

    with pytest.raises(ValueError, match="read/status credential unavailable"):
        read_read_status_password(home)


def test_configured_password_file_is_read_only_and_relative_to_config_home(
    tmp_path: Path
) -> None:
    home, config = _local_config(tmp_path)
    password_path = home / "custom-password"
    password_path.write_text("file-secret\n", encoding="utf-8")
    password_path.chmod(0o600)
    configured = replace(
        config,
        postgres=replace(
            config.postgres,
            password_env=None,
            password_file=password_path.name,
        ),
    )

    assert read_configured_postgres_password(configured) == "file-secret"
    assert password_path.read_bytes() == b"file-secret\n"


@pytest.mark.parametrize("case", ["missing", "symlink", "permissions", "directory", "runtime", "home", "owner"])
def test_unsafe_runtime_secret_authority_refuses_without_repair(tmp_path, monkeypatch, case):
    home, _ = _local_config(tmp_path)
    env_path = home / "runtime" / ".env"
    original = env_path.read_bytes()
    if case == "missing":
        env_path.unlink()
    elif case == "symlink":
        target = home / "target"
        env_path.rename(target)
        env_path.symlink_to(target)
    elif case == "permissions":
        env_path.chmod(0o644)
    elif case == "directory":
        env_path.unlink()
        env_path.mkdir(mode=0o700)
    elif case == "runtime":
        env_path.parent.chmod(0o755)
    elif case == "home":
        home.chmod(0o755)
    else:
        owner = os.getuid()
        monkeypatch.setattr(os, "getuid", lambda: owner + 1)
    before = env_path.lstat().st_mode if env_path.exists() else None
    with pytest.raises(ValueError, match="read/status credential unavailable"):
        read_read_status_password(home)
    assert (env_path.lstat().st_mode if env_path.exists() else None) == before
    if env_path.is_file():
        assert env_path.read_bytes() == original


@pytest.mark.parametrize("text", ["OTHER=value\n", "REPOMAP_READ_STATUS_PASSWORD=" + "x" * 257 + "\n"])
def test_missing_or_oversized_read_status_value_refuses(tmp_path, text):
    home, _ = _local_config(tmp_path)
    env = home / "runtime" / ".env"
    env.write_text(text)
    with pytest.raises(ValueError, match="read/status credential unavailable"):
        read_read_status_password(home)
    assert env.read_text() == text


@pytest.mark.parametrize("case", ["remote", "port", "user", "environment", "standalone", "disabled", "container"])
def test_ineligible_config_never_loads_runtime_secret(tmp_path, monkeypatch, case):
    home, config = _local_config(tmp_path)
    monkeypatch.delenv("REPOMAP_PG_PASSWORD", raising=False)
    monkeypatch.setattr("repomap_kg.runtime.postgres_route.read_read_status_password",
                        lambda _home: pytest.fail("ineligible config read runtime secrets"))
    if case == "remote":
        config = replace(config, postgres=replace(config.postgres, host="db.example.invalid"))
    elif case == "port":
        config = replace(config, postgres=replace(config.postgres, port=5433))
    elif case == "user":
        config = replace(config, postgres=replace(config.postgres, user="custom_reader"))
    elif case == "environment":
        monkeypatch.setenv("CUSTOM_PASSWORD", "custom-value")
        config = replace(config, postgres=replace(config.postgres, password_env="CUSTOM_PASSWORD"))
    elif case == "standalone":
        config = replace(config, config_path=str(home / "standalone.toml"))
    elif case == "disabled":
        config = replace(config, runtime=replace(config.runtime,
            postgres=replace(config.runtime.postgres, direct_host_port_enabled=False)))
    else:
        marker = tmp_path / "container-marker"
        marker.touch()
        monkeypatch.setattr("repomap_kg.runtime.postgres_route.CONTAINER_INTERNAL_MARKER", marker)
    assert readback_postgres_authority(config).projected_read_status is False


@pytest.mark.parametrize("kind", ["literal", "file", "environment"])
def test_explicit_credential_authority_is_preserved(tmp_path, monkeypatch, kind):
    home, config = _local_config(tmp_path)
    monkeypatch.setattr("repomap_kg.runtime.postgres_route.read_read_status_password",
                        lambda _home: pytest.fail("explicit authority read runtime secrets"))
    if kind == "literal":
        postgres = replace(config.postgres, password_env=None, password="explicit-value")
    elif kind == "file":
        path = home / "credential"
        path.write_text("explicit-value\n")
        path.chmod(0o600)
        postgres = replace(config.postgres, password_env=None, password_file=str(path))
    else:
        monkeypatch.setenv("EXPLICIT_PASSWORD", "explicit-value")
        postgres = replace(config.postgres, user=READ_STATUS_ROLE, password_env="EXPLICIT_PASSWORD")
    result = readback_postgres_authority(replace(config, postgres=postgres))
    assert result.password == "explicit-value"
    assert not result.projected_read_status
    assert result.postgres.user == postgres.user
    assert "explicit-value" not in repr(result)

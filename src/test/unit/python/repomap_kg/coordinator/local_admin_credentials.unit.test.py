"""Administrator fallback is bounded, private and separate from role secrets."""

from dataclasses import replace
import os

import pytest

from repomap_kg.coordinator._local_admin_credentials import local_admin_password
from repomap_kg.coordinator.local_lifecycle import (
    CoordinatorControlError, coordinator_control_status, initialize_coordinator_control,
    maintenance_activity_for_home,
)
from repomap_kg.ops.config_loading import load_ops_config_home
from repomap_kg.runtime.local import setup_local_runtime
from repomap_kg.runtime.maintenance import MaintenanceUnavailableError


@pytest.fixture
def local_config(tmp_path, monkeypatch):
    monkeypatch.delenv("REPOMAP_PG_PASSWORD", raising=False)
    home = tmp_path / "home"
    setup_local_runtime(home)
    path = home / "repomap.rpl.toml"
    path.write_text(path.read_text().replace("direct_host_port_enabled = false", "direct_host_port_enabled = true"))
    return home, load_ops_config_home(home)


def test_generated_secret_and_environment_precedence(local_config, monkeypatch):
    home, config = local_config
    env = home / "runtime/.env"
    env.write_text("OTHER=ignored\nREPOMAP_PG_PASSWORD=fixture-generated\n")
    before = dict(os.environ)
    assert local_admin_password(config, home) == "fixture-generated"
    assert dict(os.environ) == before
    monkeypatch.setenv("REPOMAP_PG_PASSWORD", "fixture-process")
    assert local_admin_password(config, home) == "fixture-process"
    monkeypatch.setenv("REPOMAP_PG_PASSWORD", "")
    with pytest.raises(ValueError):
        local_admin_password(config, home)


def test_literal_then_file_then_env_both_set(local_config, monkeypatch):
    home, config = local_config
    path = home / "password"
    path.write_text("fixture-file")
    path.chmod(0o600)
    monkeypatch.setenv("REPOMAP_PG_PASSWORD", "fixture-process")
    postgres = replace(config.postgres, password_file="password", password="fixture-literal")
    assert local_admin_password(replace(config, postgres=postgres), home) == "fixture-literal"
    postgres = replace(postgres, password=None)
    assert local_admin_password(replace(config, postgres=postgres), home) == "fixture-file"
    path.write_text("")
    with pytest.raises(ValueError):
        local_admin_password(replace(config, postgres=postgres), home)


@pytest.mark.parametrize("text", [
    "REPOMAP_PG_PASSWORD=fixture-secret\nREPOMAP_PG_PASSWORD=second\n",
    "POSTGRES_PASSWORD=fixture-secret\n", "REPOMAP_PG_PASSWORD=\n",
    "REPOMAP_PG_PASSWORD=" + "x" * 257,
    "REPOMAP_PG_PASSWORD=fixture-secret\r\n",
    "REPOMAP_PG_PASSWORD=fixture-secret\x00\n",
])
def test_invalid_generated_secret_fails_closed(local_config, text):
    home, config = local_config
    (home / "runtime/.env").write_text(text)
    with pytest.raises(ValueError) as error:
        local_admin_password(config, home)
    assert "fixture-secret" not in str(error.value)


@pytest.mark.parametrize("kind", ["broad", "symlink", "oversized"])
def test_unsafe_file_fails_closed(local_config, kind):
    home, config = local_config
    path = home / "runtime/.env"
    if kind == "broad":
        path.chmod(0o644)
    elif kind == "oversized":
        path.write_text("#" * 65537)
    else:
        path.rename(home / "saved")
        path.symlink_to(home / "saved")
    with pytest.raises(ValueError):
        local_admin_password(config, home)


@pytest.mark.parametrize("kind", ["custom", "nonlocal", "no-home", "no-direct", "container"])
def test_ineligible_authority_never_uses_runtime_file(local_config, monkeypatch, kind):
    home, config = local_config
    if kind == "custom":
        (home / "runtime/.env").write_text("CUSTOM=fixture-secret\n")
        config = replace(config, postgres=replace(config.postgres, password_env="CUSTOM"))
        monkeypatch.delenv("CUSTOM", raising=False)
    elif kind == "nonlocal":
        config = replace(config, postgres=replace(config.postgres, host="remote.invalid"))
    elif kind == "no-home":
        config = replace(config, config_home=None)
    elif kind == "no-direct":
        config = replace(config, runtime=replace(config.runtime, postgres=replace(config.runtime.postgres, direct_host_port_enabled=False)))
    else:
        monkeypatch.setattr("repomap_kg.runtime.postgres_route.CONTAINER_INTERNAL_MARKER", home)
        monkeypatch.setattr(type(home), "is_file", lambda p: True)
    with pytest.raises(ValueError):
        local_admin_password(config, home)


def test_control_and_maintenance_preserve_authority_class(local_config):
    home, _ = local_config
    (home / "runtime/.env").write_text("REPOMAP_PG_PASSWORD=\n")
    for operation in (coordinator_control_status, initialize_coordinator_control):
        with pytest.raises(CoordinatorControlError, match="local-admin-credential"):
            operation(home)
    with pytest.raises(MaintenanceUnavailableError, match="local-admin-credential"):
        with maintenance_activity_for_home(home):
            pytest.fail("invalid authority admitted")

@pytest.mark.parametrize("authority", ["literal", "environment", "file"])
@pytest.mark.parametrize("value", ["fixture\rcarriage", "fixture\nline", "x" * 256])
def test_explicit_password_preserves_predecessor_validation(
    local_config, monkeypatch, authority, value,
):
    from repomap_kg.coordinator.configured_refresh import _postgres_password

    home, config = local_config
    postgres = replace(config.postgres, password_env=None)
    if authority == "literal":
        postgres = replace(postgres, password=value)
    elif authority == "environment":
        postgres = replace(postgres, password_env="EXPLICIT_ADMIN")
        monkeypatch.setenv("EXPLICIT_ADMIN", value)
    else:
        path = home / "explicit-password"
        path.write_text(value)
        path.chmod(0o600)
        postgres = replace(postgres, password_file="explicit-password")
    config = replace(config, postgres=postgres)
    assert local_admin_password(config, home) == _postgres_password(config, home)

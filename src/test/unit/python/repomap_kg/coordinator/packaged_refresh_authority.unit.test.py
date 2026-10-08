"""Packaged-service search authority must never inherit the working directory."""

from dataclasses import asdict, replace
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from repomap_kg.coordinator.configured_refresh import (
    ConfiguredRefreshResolver,
    _executable_search_path,
)
from repomap_kg.coordinator.refresh_adapter import (
    RefreshCapability,
    create_refresh_capability,
    load_refresh_capability,
    remove_refresh_capability,
)
from repomap_kg.runtime.database_role_contract import REFRESH_PUBLICATION_ROLE
from repomap_kg.service_package.environment import apply_service_environment
from repomap_test_support.executable_authority import approved_psql


@pytest.mark.parametrize("path_value", [None, "", ".", "relative", ":relative:"])
def test_search_authority_excludes_relative_entries(tmp_path, monkeypatch, path_value):
    psql = approved_psql(tmp_path)
    (tmp_path / "relative").mkdir(mode=0o700)
    monkeypatch.chdir(tmp_path)
    if path_value is None:
        monkeypatch.delenv("PATH", raising=False)
    else:
        monkeypatch.setenv("PATH", path_value.replace(":", os.pathsep))

    assert _executable_search_path(psql) == (psql.parent,)


def test_search_authority_retains_absolute_entries_in_order(tmp_path, monkeypatch):
    psql = approved_psql(tmp_path)
    second = tmp_path / "second"
    second.mkdir(mode=0o755)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PATH", os.pathsep.join(["", str(second), str(psql.parent), "."]))

    assert _executable_search_path(psql) == (psql.parent, second)


def test_packaged_native_authority_round_trip(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir(mode=0o700)
    source = tmp_path / "source"
    source.mkdir()
    (source / "README.md").write_text("# Public fixture\n", encoding="utf-8")
    (home / "repomap.rpl.toml").write_text(
        'schema_version = 1\n[service]\nmode = "local"\n'
        'mcp_transport = "stdio"\nlog_level = "info"\n'
        '[postgres]\nhost = "postgres"\nport = 5432\n'
        'database = "fixture"\nuser = "repomap"\n'
        'password_env = "REPOMAP_PG_PASSWORD"\n'
        '[runtime.postgres]\ndirect_host_port_enabled = true\nhost_port = 55891\n'
        '[[graphs]]\nid = "fixture"\nname = "Fixture"\n'
        f'root_path = "{source}"\nrepository_name = "fixture"\n'
        'privacy = "public-dev"\nenabled = true\nmcp_visible = false\n'
        'extractor_profile = "default"\nrefresh_policy = "manual"\n'
        '[server_memory]\nenabled = false\npath = "disabled"\nmode = "read_only"\n',
        encoding="utf-8",
    )
    psql = approved_psql(tmp_path)
    resolver = ConfiguredRefreshResolver(
        home, psql, postgres_user=REFRESH_PUBLICATION_ROLE,
        postgres_password="test-only-password",
    )
    monkeypatch.chdir(home)
    with patch.dict(os.environ):
        apply_service_environment(os.environ)
        assert "PATH" not in os.environ
        authority = resolver.resolve_authority("fixture")

    assert authority.executable_search_path == (psql.parent,)
    assert authority.postgres_route_kind == "local-native"
    assert authority.postgres_user == REFRESH_PUBLICATION_ROLE
    capability = RefreshCapability(
        schema_version=1, job_id="packaged-fixture", attempt=1,
        coordinator_instance_id="fixture-instance", singleton_fencing_epoch=1,
        graph_lease_fencing_epoch=1, **asdict(authority),
    )
    assert capability.validate() is capability
    path = create_refresh_capability(home, capability)
    try:
        assert path.stat().st_size <= 4096
        assert load_refresh_capability(path) == capability
    finally:
        remove_refresh_capability(path)
    assert not path.exists()
    for invalid in ((), (Path("."),), (Path("relative"),), (psql.parent, Path("."))):
        with pytest.raises(ValueError, match="invalid refresh capability"):
            replace(capability, executable_search_path=invalid).validate()

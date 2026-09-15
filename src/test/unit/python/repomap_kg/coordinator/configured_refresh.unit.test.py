from pathlib import Path
import os
import threading
from types import SimpleNamespace
from typing import cast
from unittest.mock import patch

import pytest

from repomap_test_support.executable_authority import approved_psql
from repomap_kg.coordinator.configured_refresh import (
    ConfiguredRefreshResolver,
    _executable_search_path,
    _postgres_password,
    build_configured_refresh_coordinator,
)
from repomap_kg.coordinator._refresh_contracts import RefreshSourceError
from repomap_kg.coordinator.refresh_adapter import build_refresh_worker_runner
from repomap_kg.coordinator.startup_recovery import PublicationRouteChangedError
from repomap_kg.graph.multi_source_pipeline import MultiSourceCaptureError


def request():
    return {
        "schema_version": 1,
        "job_kind": "refresh_graph",
        "graph_id": "configured-refresh",
        "request_id": "configured-request",
        "idempotency_key": "configured-key",
        "priority": "manual",
        "operation_options": {"reason": "configured-pilot"},
    }


def write_config(path: Path, root: Path) -> None:
    path.write_text(
        f'schema_version = 1\n[service]\nmode = "local"\nmcp_transport = "stdio"\nlog_level = "info"\n'
        f'[postgres]\nhost = "localhost"\nport = 5432\ndatabase = "configured_graph"\nuser = "configured_user"\n'
        f'password_env = "ASYNC7_TEST_PASSWORD"\n[[graphs]]\nid = "configured-refresh"\nname = "Configured Refresh"\n'
        f'root_path = "{root}"\nrepository_name = "configured-refresh"\nprivacy = "public-dev"\nenabled = true\n'
        f'mcp_visible = false\nextractor_profile = "default"\nrefresh_policy = "manual"\n'
        f'[server_memory]\nenabled = false\npath = "disabled"\nmode = "read_only"\n',
        encoding="utf-8",
    )
    path.chmod(0o600)


def test_configured_resolver_owns_generations_and_private_authority(tmp_path, monkeypatch):
    repository = tmp_path / "repository"
    repository.mkdir()
    source = repository / "README.md"
    source.write_text("# One\n", encoding="utf-8")
    config_path = tmp_path / "ops.toml"
    write_config(config_path, repository)
    monkeypatch.setenv("ASYNC7_TEST_PASSWORD", "private-test-password")
    resolver = ConfiguredRefreshResolver(config_path, approved_psql(tmp_path))

    first = resolver.resolve_request(request())
    authority = resolver.resolve_authority("configured-refresh")
    assert first.source_generation == authority.source_generation
    assert first.config_generation == authority.config_generation
    assert first.extractor_generation == authority.extractor_generation
    assert first.canonicalizer_generation == authority.canonicalizer_generation
    assert authority.postgres_password == "private-test-password"
    assert "private-test-password" not in repr(first)

    source.write_text("# Two\n", encoding="utf-8")
    second = resolver.resolve_request(request())
    assert second.source_generation != first.source_generation
    assert second.config_generation == first.config_generation


@pytest.mark.skipif(os.name == "nt", reason="POSIX wrapper indirection")
def test_configured_resolver_preserves_lexical_psql_wrapper(tmp_path, monkeypatch):
    repository = tmp_path / "repository"
    repository.mkdir()
    (repository / "README.md").write_text("# Fixture\n", encoding="utf-8")
    config_path = tmp_path / "ops.toml"
    write_config(config_path, repository)
    monkeypatch.setenv("ASYNC7_TEST_PASSWORD", "private-test-password")
    wrapper = approved_psql(tmp_path, name="pg_wrapper")
    lexical_psql = tmp_path / "psql"
    lexical_psql.symlink_to(wrapper)

    resolver = ConfiguredRefreshResolver(config_path, lexical_psql)

    assert resolver.resolve_authority("configured-refresh").psql_path == lexical_psql


@pytest.mark.skipif(os.name == "nt", reason="POSIX executable ownership")
def test_executable_search_path_excludes_unowned_directory(tmp_path, monkeypatch):
    unowned = tmp_path / "unowned-bin"
    unowned.mkdir(mode=0o700)
    original_stat = Path.stat
    owner_uid = os.getuid()

    def stat_with_unowned_directory(path, *args, **kwargs):
        details = original_stat(path, *args, **kwargs)
        if path == unowned:
            return SimpleNamespace(st_mode=details.st_mode, st_uid=owner_uid + 1)
        return details

    monkeypatch.setattr(Path, "stat", stat_with_unowned_directory)
    monkeypatch.setenv("PATH", "")

    assert unowned not in _executable_search_path(unowned / "psql")


def test_configured_publication_readback_uses_private_child_environment(
    tmp_path, monkeypatch
):
    repository = tmp_path / "repository"
    repository.mkdir()
    (repository / "README.md").write_text("# Fixture\n", encoding="utf-8")
    config_path = tmp_path / "ops.toml"
    write_config(config_path, repository)
    monkeypatch.setenv("ASYNC7_TEST_PASSWORD", "private-test-password")
    resolver = ConfiguredRefreshResolver(config_path, approved_psql(tmp_path))
    record = SimpleNamespace(marker=lambda: {"latest_run_identity": "run-1"})
    accepted = resolver.resolve_request(request())
    claim = SimpleNamespace(
        graph_id="configured-refresh",
        job_id="job-configured",
        attempt=1,
        config_generation=accepted.config_generation,
    )
    with patch(
        "repomap_kg.coordinator.configured_refresh.read_run_publication",
        return_value=record,
    ) as read:
        assert resolver.read_publication(claim) == {"latest_run_identity": "run-1"}
    assert read.call_args.kwargs["env"]["PGPASSWORD"] == "private-test-password"
    assert os.environ.get("PGPASSWORD") != "private-test-password"


def test_configured_publication_readback_rejects_changed_route_before_psql(
    tmp_path, monkeypatch
):
    repository = tmp_path / "repository"
    repository.mkdir()
    (repository / "README.md").write_text("# Fixture\n", encoding="utf-8")
    config_path = tmp_path / "ops.toml"
    write_config(config_path, repository)
    monkeypatch.setenv("ASYNC7_TEST_PASSWORD", "private-test-password")
    resolver = ConfiguredRefreshResolver(config_path, approved_psql(tmp_path))
    claim = SimpleNamespace(
        graph_id="configured-refresh",
        job_id="job-configured",
        attempt=1,
        config_generation="cg1:prior-route",
    )

    with patch(
        "repomap_kg.coordinator.configured_refresh.read_run_publication"
    ) as read:
        with pytest.raises(
            PublicationRouteChangedError,
            match="configured storage route changed",
        ):
            resolver.read_publication(claim)
    read.assert_not_called()


def test_configured_resolver_exposes_polling_targets_and_latest_publication(
    tmp_path, monkeypatch
):
    repository = tmp_path / "repository"
    repository.mkdir()
    (repository / "README.md").write_text("# Fixture\n", encoding="utf-8")
    config_path = tmp_path / "ops.toml"
    write_config(config_path, repository)
    config_path.write_text(
        config_path.read_text(encoding="utf-8").replace(
            'refresh_policy = "manual"', 'refresh_policy = "polling"'
        ),
        encoding="utf-8",
    )
    config_path.chmod(0o600)
    monkeypatch.setenv("ASYNC7_TEST_PASSWORD", "private-test-password")
    resolver = ConfiguredRefreshResolver(config_path, approved_psql(tmp_path))

    assert resolver.polling_graphs() == (("configured-refresh", "polling"),)
    snapshot = resolver.polling_snapshot("configured-refresh")
    assert snapshot.source.category == "ready"
    with patch(
        "repomap_kg.coordinator.configured_refresh."
        "read_latest_receipt_bearing_publication",
        return_value=None,
    ) as read:
        assert resolver.latest_publication("configured-refresh") is None
    read.assert_called_once()
    assert read.call_args.kwargs["env"]["PGPASSWORD"] == "private-test-password"


def test_configured_source_change_fails_before_capability_creation(
    tmp_path, monkeypatch
):
    repository = tmp_path / "repository"
    repository.mkdir()
    source = repository / "README.md"
    source.write_text("# Accepted\n", encoding="utf-8")
    config_path = tmp_path / "ops.toml"
    write_config(config_path, repository)
    monkeypatch.setenv("ASYNC7_TEST_PASSWORD", "private-test-password")
    resolver = ConfiguredRefreshResolver(config_path, approved_psql(tmp_path))
    accepted = resolver.resolve_request(request())
    source.write_text("# Changed\n", encoding="utf-8")
    claim = SimpleNamespace(
        job_id="job-configured",
        attempt=1,
        graph_id=accepted.graph_id,
        source_generation=accepted.source_generation,
        config_generation=accepted.config_generation,
        extractor_generation=accepted.extractor_generation,
        canonicalizer_generation=accepted.canonicalizer_generation,
    )
    runner = build_refresh_worker_runner(
        resolver.resolve_authority, tmp_path, {}
    )
    terminal = runner(claim, threading.Event())
    assert terminal["publication_state"] == "not_started"
    assert terminal["error_category"] == "generation_changed"
    assert not tuple(tmp_path.glob("refresh-*.json"))


def test_configured_resolver_refuses_incomplete_authority_credentials(tmp_path):
    config_path = tmp_path / "ops.toml"
    psql = approved_psql(tmp_path)
    with pytest.raises(ValueError, match="configured refresh authority is incomplete"):
        ConfiguredRefreshResolver(config_path, psql, postgres_user="user", postgres_password=None)
    with pytest.raises(ValueError, match="configured refresh authority is incomplete"):
        ConfiguredRefreshResolver(config_path, psql, postgres_user=None, postgres_password="pw")


def test_configured_resolver_explicit_credentials_and_immutable_authority(tmp_path, monkeypatch):
    repository = tmp_path / "repository"
    repository.mkdir()
    (repository / "README.md").write_text("# Repo\n", encoding="utf-8")
    config_path = tmp_path / "ops.toml"
    write_config(config_path, repository)
    resolver = ConfiguredRefreshResolver(
        config_path,
        approved_psql(tmp_path),
        postgres_user="explicit_user",
        postgres_password="explicit_password",
    )
    authority = resolver.resolve_authority("configured-refresh")
    assert authority.postgres_user == "explicit_user"
    assert authority.postgres_password == "explicit_password"
    assert authority.graph_id == "configured-refresh"
    assert authority.config_path == config_path.resolve()


def test_configured_resolver_refuses_invalid_payload_and_graph(tmp_path):
    def _invalid_graph_id(value: int | list[str] | None) -> str:
        """Narrow runtime-invalid graph ID builder for negative controls."""
        return cast(str, value)

    config_path = tmp_path / "ops.toml"
    psql = approved_psql(tmp_path)
    resolver = ConfiguredRefreshResolver(config_path, psql)
    for bad in (None, [1, 2], "not-dict", 999):
        with pytest.raises(ValueError, match="configured refresh request is invalid"):
            resolver.resolve_request(bad)
    for bad_graph in (None, 123, ["graph"]):
        with pytest.raises(ValueError, match="configured graph is invalid"):
            resolver.resolve_authority(_invalid_graph_id(bad_graph))
        with pytest.raises(ValueError, match="configured graph is invalid"):
            resolver.polling_snapshot(_invalid_graph_id(bad_graph))


def test_configured_resolver_refuses_missing_root_or_unsupported(tmp_path, monkeypatch):
    repository = tmp_path / "nonexistent"
    config_path = tmp_path / "ops.toml"
    write_config(config_path, repository)
    monkeypatch.setenv("ASYNC7_TEST_PASSWORD", "test-pass")
    resolver = ConfiguredRefreshResolver(config_path, approved_psql(tmp_path))
    with pytest.raises(ValueError, match="configured graph root is unavailable"):
        resolver.resolve_authority("configured-refresh")

    fake_unsupported = SimpleNamespace(
        id="unsupported-graph",
        refresh_unsupported_classification="archive_source_unsupported",
        explicit_source_bindings=(),
    )
    with patch(
        "repomap_kg.coordinator.configured_refresh.configured_graph",
        return_value=fake_unsupported,
    ):
        with pytest.raises(ValueError, match="archive_source_unsupported"):
            resolver.resolve_authority("configured-refresh")
        with pytest.raises(ValueError, match="archive_source_unsupported"):
            resolver.polling_snapshot("configured-refresh")


def test_configured_resolver_multi_source_and_error_attribution(tmp_path, monkeypatch):
    repository = tmp_path / "repository"
    repository.mkdir()
    (repository / "README.md").write_text("# Multi\n", encoding="utf-8")
    config_path = tmp_path / "ops.toml"
    write_config(config_path, repository)
    monkeypatch.setenv("ASYNC7_TEST_PASSWORD", "test-pass")
    resolver = ConfiguredRefreshResolver(config_path, approved_psql(tmp_path))

    fake_multi = SimpleNamespace(
        id="configured-refresh", enabled=True, refresh_policy="polling",
        refresh_unsupported_classification=None,
        explicit_source_bindings=(SimpleNamespace(source_kind="git"),), exclude_paths=(),
    )
    with patch("repomap_kg.coordinator.configured_refresh.configured_graph", return_value=fake_multi):
        with pytest.raises(ValueError, match="multi-source graph polling refresh is unsupported"):
            resolver.polling_snapshot("configured-refresh")
        scan_target = "repomap_kg.coordinator.configured_refresh.scan_multi_source_generations"
        with patch(scan_target, side_effect=MultiSourceCaptureError("down", category="source_unavailable")):
            with pytest.raises(RefreshSourceError, match="source is unavailable"):
                resolver.resolve_authority("configured-refresh")
        with patch(scan_target, side_effect=MultiSourceCaptureError("broken", category="other")):
            with pytest.raises(RefreshSourceError, match="source capture failed"):
                resolver.resolve_authority("configured-refresh")
        with patch(scan_target, side_effect=OSError("disk read fail")):
            with pytest.raises(ValueError, match="configured graph source is unavailable"):
                resolver.resolve_authority("configured-refresh")

    with patch.object(
        resolver, "_snapshot",
        return_value=SimpleNamespace(psql_args=("arg",), password="test-pass", config_generation="cg1:expected"),
    ):
        with patch("repomap_kg.coordinator.configured_refresh.read_run_publication", return_value=None) as read_publication:
            claim = SimpleNamespace(
                graph_id="configured-refresh", job_id="job-1", attempt=1, config_generation="cg1:expected",
            )
            assert resolver.read_publication(claim) is None
            read_publication.assert_called_once()
            args, kwargs = read_publication.call_args
            assert args == (("arg",),)
            assert kwargs["job_id"] == "job-1" and kwargs["attempt"] == 1
            assert kwargs["psql_command"] == str(resolver._psql_path)
            assert kwargs["env"]["PGPASSWORD"] == "test-pass"


def test_postgres_password_resolution_and_file_guards(tmp_path, monkeypatch):
    config_path = tmp_path / "ops.toml"
    pw = lambda p=None, pe=None, pf=None: SimpleNamespace(postgres=SimpleNamespace(password=p, password_env=pe, password_file=pf))
    assert _postgres_password(pw("direct_password"), config_path) == "direct_password"

    monkeypatch.delenv("MISSING_ENV_TEST", raising=False)
    with pytest.raises(ValueError, match="postgres credential is unavailable"):
        _postgres_password(pw(pe="MISSING_ENV_TEST"), config_path)

    monkeypatch.setenv("LONG_ENV_TEST", "a" * 257)
    with pytest.raises(ValueError, match="postgres credential is unavailable"):
        _postgres_password(pw(pe="LONG_ENV_TEST"), config_path)

    pw_file = tmp_path / "secret.pw"
    pw_file.write_text("file_password\n", encoding="utf-8")
    pw_file.chmod(0o600)
    cfg_file = pw(pf="secret.pw")
    assert _postgres_password(cfg_file, config_path) == "file_password"

    if os.name != "nt":
        pw_file.chmod(0o666)
        with pytest.raises(ValueError, match="postgres credential is unavailable"):
            _postgres_password(cfg_file, config_path)

    with pytest.raises(ValueError, match="postgres credential is unavailable"):
        _postgres_password(pw(pf=str(tmp_path)), config_path)


def test_build_configured_refresh_coordinator_wiring(tmp_path, monkeypatch):
    repository = tmp_path / "repository"
    repository.mkdir()
    (repository / "README.md").write_text("# Rep\n", encoding="utf-8")
    config_path = tmp_path / "ops.toml"
    write_config(config_path, repository)
    monkeypatch.setenv("ASYNC7_TEST_PASSWORD", "test-pass")
    resolver = ConfiguredRefreshResolver(config_path, approved_psql(tmp_path))
    fake_store = SimpleNamespace()
    cap_dir = tmp_path / "cap"
    cap_dir.mkdir()
    coord = build_configured_refresh_coordinator(fake_store, "inst-alpha", resolver, cap_dir)
    assert coord._instance_id == "inst-alpha"
    assert coord._store is fake_store
    assert coord._publication_reader == resolver.read_publication


def test_polling_snapshot_cancellation_event(tmp_path, monkeypatch):
    repository = tmp_path / "repository"
    repository.mkdir()
    (repository / "README.md").write_text("# Cancelled\n", encoding="utf-8")
    config_path = tmp_path / "ops.toml"
    write_config(config_path, repository)
    monkeypatch.setenv("ASYNC7_TEST_PASSWORD", "test-pass")
    resolver = ConfiguredRefreshResolver(config_path, approved_psql(tmp_path))

    cancel_ev = threading.Event()
    cancel_ev.set()
    snapshot = resolver.polling_snapshot("configured-refresh", cancel_event=cancel_ev)
    assert snapshot.source.category == "cancelled"
    assert snapshot.source.generation is None

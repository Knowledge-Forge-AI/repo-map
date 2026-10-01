from pathlib import Path
from unittest.mock import MagicMock, patch
from dataclasses import replace
import pytest

from repomap_test_support.executable_authority import approved_psql, search_path_for
from repomap_kg.coordinator.configured_refresh import ConfiguredRefreshResolver
from repomap_kg.coordinator.refresh_adapter import (
    RefreshCapability, RefreshConfigurationError, create_refresh_capability, load_refresh_capability,
)


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


def test_native_route_is_bound_and_worker_rejects_route_change(tmp_path, monkeypatch):
    from dataclasses import replace
    from repomap_kg.coordinator.refresh_adapter import RefreshCapability, execute_refresh
    from repomap_kg.coordinator._refresh_contracts import RefreshGenerationChangedError
    from repomap_kg.runtime.postgres_route import execution_postgres

    repository = tmp_path / "source"
    repository.mkdir()
    (repository / "README.md").write_text("# Fixture\n")
    home = tmp_path / "home"
    home.mkdir(mode=0o700)
    config_path = home / "repomap.rpl.toml"
    write_config(config_path, repository)
    config_path.write_text(config_path.read_text().replace('host = "localhost"', 'host = "postgres"') +
                           '\n[runtime.postgres]\ndirect_host_port_enabled = true\nhost_port = 55891\n')
    monkeypatch.setenv("ASYNC7_TEST_PASSWORD", "test-only")
    resolver = ConfiguredRefreshResolver(home, approved_psql(tmp_path))
    authority = resolver.resolve_authority("configured-refresh")
    assert (authority.postgres_host, authority.postgres_port, authority.postgres_route_kind) == ("127.0.0.1", 55891, "local-native")
    capability = RefreshCapability(
        schema_version=1, job_id="route-test", attempt=1, graph_id=authority.graph_id,
        config_path=authority.config_path, psql_path=authority.psql_path,
        postgres_user=authority.postgres_user, postgres_password=authority.postgres_password,
        executable_search_path=authority.executable_search_path,
        source_generation=authority.source_generation, config_generation=authority.config_generation,
        extractor_generation=authority.extractor_generation, canonicalizer_generation=authority.canonicalizer_generation,
        postgres_host=authority.postgres_host, postgres_port=authority.postgres_port,
        postgres_route_kind=authority.postgres_route_kind,
        coordinator_instance_id="route-instance", singleton_fencing_epoch=1, graph_lease_fencing_epoch=1,
    )
    with patch("repomap_kg.ops.refresh.refresh_graph", return_value="complete") as refresh:
        assert execute_refresh(capability) == "complete"
        executed = refresh.call_args.args[0]
        assert executed.postgres.host == "postgres"
        assert execution_postgres(executed).port == 55891
        bound = refresh.call_args.kwargs["_postgres_route"]
        assert (bound.host, bound.port, bound.kind) == ("127.0.0.1", 55891, "local-native")
    with patch("repomap_kg.ops.refresh.refresh_graph") as refresh:
        with pytest.raises(RefreshGenerationChangedError):
            execute_refresh(replace(capability, postgres_port=55892))
        refresh.assert_not_called()
    config_path.write_text(config_path.read_text().replace("55891", "55892"))
    with patch("repomap_kg.ops.refresh.refresh_graph") as refresh:
        with pytest.raises(RefreshGenerationChangedError):
            execute_refresh(capability)
        refresh.assert_not_called()



def _cfg(root: Path) -> Path:
    p = root / "ops.toml"
    p.write_text("version = 1\n", encoding="utf-8")
    p.chmod(0o600)
    return p


def capability(root: Path, config_path: Path) -> RefreshCapability:
    psql_path = approved_psql(root)
    return RefreshCapability(
        schema_version=1, job_id="job-refresh-1", attempt=1, graph_id="synthetic-refresh",
        config_path=config_path, psql_path=psql_path, postgres_user="repomap_refresh_publication",
        postgres_password="test-only", executable_search_path=search_path_for(psql_path),
        source_generation="sg1:source", config_generation="cg1:config",
        extractor_generation="eg1:extractor", canonicalizer_generation="kg1:canonicalizer",
        coordinator_instance_id="instance-refresh-1", singleton_fencing_epoch=7, graph_lease_fencing_epoch=7,
    )


@pytest.mark.parametrize("field,value", [("postgres_host", ""), ("postgres_port", True),
    ("postgres_port", 0), ("postgres_port", 65536), ("postgres_route_kind", "arbitrary")])
def test_capability_route_validation(tmp_path, field, value):
    with pytest.raises(ValueError, match="invalid refresh capability"):
        replace(capability(tmp_path, _cfg(tmp_path)), **{field: value}).validate()


def test_native_capability_route_round_trip(tmp_path):
    target = replace(capability(tmp_path, _cfg(tmp_path)), postgres_host="127.0.0.1",
                     postgres_port=55891, postgres_route_kind="local-native")
    path = create_refresh_capability(tmp_path, target)
    try:
        assert load_refresh_capability(path) == target
    finally:
        path.unlink()


from repomap_kg.runtime.postgres_route import PostgresRoute


def test_ops_refresh_error_is_strictly_preflight_configuration_error() -> None:
    from repomap_kg.ops.report_records import OpsRefreshError
    from repomap_kg.coordinator._refresh_execution import execute_refresh_attempt

    capability = MagicMock()
    capability.config_path.exists.return_value = True
    capability.psql_path.exists.return_value = True
    capability.graph_id = "test-graph"
    capability.postgres_host = "127.0.0.1"
    capability.postgres_port = 5432
    capability.postgres_route_kind = "configured"

    with (
        patch("repomap_kg.coordinator._refresh_execution.effective_postgres_route", return_value=PostgresRoute("127.0.0.1", 5432, "configured")),
        patch("repomap_kg.ops.config.load_ops_config"),
        patch("repomap_kg.runtime.database_role_contract.project_database_role_config"),
        patch("repomap_kg.coordinator._refresh_execution.validate_configured_generations"),
        patch("repomap_kg.ops.refresh.refresh_graph") as mock_refresh,
    ):
        mock_refresh.side_effect = OpsRefreshError("graph 'test-graph' is disabled")
        with pytest.raises(RefreshConfigurationError, match="disabled"):
            execute_refresh_attempt(capability)


from repomap_kg.coordinator.refresh_adapter import execute_refresh
from repomap_kg.storage.authority import AttemptNumber, JobId, OperationId
from repomap_kg.storage.publication import RunPublicationReceipt, RunPublicationAttempt, RunPublicationGenerations
from repomap_kg.storage.staged_ingestion import IngestionAuthority


def test_execute_refresh_delegates_once_to_existing_forced_full_operation(tmp_path: Path) -> None:
    config_path, target = _cfg(tmp_path), capability(tmp_path, _cfg(tmp_path))
    existing_result, execution_config = object(), object()
    with (
        patch("repomap_kg.ops.config.load_ops_config", return_value="loaded-config") as load,
        patch("repomap_kg.ops.refresh.refresh_graph", return_value=existing_result) as refresh,
        patch("repomap_kg.coordinator._refresh_execution.validate_configured_generations"),
        patch("repomap_kg.coordinator._refresh_execution.effective_postgres_route", return_value=PostgresRoute("127.0.0.1", 5432, "configured")),
        patch("repomap_kg.runtime.database_role_contract.project_database_role_config", return_value=execution_config) as project,
    ):
        assert execute_refresh(target) is existing_result
    load.assert_called_once_with(config_path)
    project.assert_called_once_with("loaded-config", role="repomap_refresh_publication", password="test-only")
    expected_receipt = RunPublicationReceipt(
        attempt=RunPublicationAttempt(JobId("job-refresh-1"), AttemptNumber(1)),
        generations=RunPublicationGenerations("sg1:source", "cg1:config", "eg1:extractor", "kg1:canonicalizer"),
    )
    expected_auth = IngestionAuthority(
        operation_id=OperationId("job-refresh-1"), attempt=AttemptNumber(1), execution_mode="coordinator",
        source_generation="sg1:source", config_generation="cg1:config",
        extractor_generation="eg1:extractor", canonicalizer_generation="kg1:canonicalizer",
        job_id=JobId("job-refresh-1"), coordinator_instance_id="instance-refresh-1",
        singleton_fencing_epoch=7, graph_lease_fencing_epoch=7, process_deadline_seconds=600,
    )
    refresh.assert_called_once_with(
        execution_config, "synthetic-refresh", psql_command=str(target.psql_path),
        publication_receipt=expected_receipt, ingestion_mode="staged", staged_authority=expected_auth,
        _postgres_route=PostgresRoute("127.0.0.1", 5432, "configured"),
    )

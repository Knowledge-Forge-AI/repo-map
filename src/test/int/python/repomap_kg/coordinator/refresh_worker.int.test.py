from pathlib import Path
import shutil
from datetime import timedelta

import psycopg
import pytest

from repomap_test_support.executable_authority import controlled_psql_copy
from repomap_test_support.test_scratch import short_test_directory
from repomap_kg.ops.config import load_ops_config
from repomap_kg.ops.refresh import refresh_graph
from repomap_kg.graph.multi_source_pipeline import scan_multi_source_generations
from repomap_kg.ops.generations import (
    canonicalizer_generation,
    configured_graph,
    extractor_generation,
)
from repomap_kg.storage import (
    apply_migrations,
    default_rdbms_root,
    read_run_publication,
)
from repomap_test_support.postgres_harness import (
    require_postgres_binaries,
    temporary_postgres,
)

from repomap_kg.coordinator.protocol import ProtocolError, run_refresh_worker
from repomap_kg.coordinator import normalize_request
from repomap_kg.coordinator.core import SyntheticCoordinator
from repomap_kg.coordinator.refresh_adapter import (
    RefreshCapability,
    ResolvedRefreshAuthority,
    build_refresh_worker_runner,
    create_refresh_capability,
)
from repomap_kg.coordinator.limits import DEFAULT_LIMITS
from repomap_kg.coordinator.storage import ControlStore


def search_path():
    psql = shutil.which("psql")
    assert psql is not None
    return (Path(psql).parent,)


def worker_limits():
    return {
        "process_deadline_seconds": 10, "heartbeat_seconds": 10, "hello_deadline_seconds": 2,
        "cancellation_after_seconds": 1, "cancel_deadline_seconds": 1,
        "process_termination_grace_seconds": 1, "max_diagnostic_bytes": 4096,
        "max_protocol_line_bytes": 1024 * 1024, "max_array_items": 32,
    }


def test_production_refresh_worker_uses_shared_protocol_and_cleans_capability():
    with short_test_directory("async4-", "repository/README.md") as directory:
        root = Path(directory)
        config_path = root / "invalid-ops.toml"
        config_path.write_text("version = 1\n", encoding="utf-8")
        psql_path = controlled_psql_copy(root)
        capability = RefreshCapability(
            schema_version=1, job_id="job-refresh-1", attempt=1,
            graph_id="synthetic-refresh", config_path=config_path, psql_path=psql_path,
            postgres_user="repomap_refresh_publication", postgres_password="test-only",
            executable_search_path=(psql_path.parent,), source_generation="sg1:source",
            config_generation="cg1:config", extractor_generation="eg1:extractor",
            canonicalizer_generation="kg1:canonicalizer", coordinator_instance_id="worker-refresh-1",
            singleton_fencing_epoch=1, graph_lease_fencing_epoch=1,
        )
        path = create_refresh_capability(root, capability)
        result = run_refresh_worker(
            path, {"job_id": capability.job_id, "attempt": capability.attempt}, DEFAULT_LIMITS,
            job_context={
                "graph_id": capability.graph_id,
                "source_generation": capability.source_generation,
                "config_generation": capability.config_generation,
            },
        )
        assert result.terminal["message_type"] == "error"
        assert result.terminal["error_category"] == "configuration"
        assert result.terminal["publication_state"] == "not_started"
        assert result.process_group_cleaned is True
        assert not path.exists()


def test_refresh_worker_rejects_generation_mismatch_and_cleans_capability():
    with short_test_directory("async4-", "repository/README.md") as directory:
        root = Path(directory)
        config_path = root / "ops.toml"
        config_path.write_text("version = 1\n", encoding="utf-8")
        psql_path = controlled_psql_copy(root)
        capability = RefreshCapability(
            schema_version=1, job_id="job-refresh-mismatch", attempt=1,
            graph_id="synthetic-refresh", config_path=config_path, psql_path=psql_path,
            postgres_user="repomap_refresh_publication", postgres_password="test-only",
            executable_search_path=(psql_path.parent,), source_generation="sg1:source",
            config_generation="cg1:config", extractor_generation="eg1:extractor",
            canonicalizer_generation="kg1:canonicalizer", coordinator_instance_id="worker-refresh-mismatch",
            singleton_fencing_epoch=1, graph_lease_fencing_epoch=1,
        )
        path = create_refresh_capability(root, capability)
        with pytest.raises(ProtocolError, match="identity_mismatch"):
            run_refresh_worker(
                path, {"job_id": capability.job_id, "attempt": capability.attempt}, DEFAULT_LIMITS,
                job_context={
                    "graph_id": capability.graph_id,
                    "source_generation": "sg1:newer",
                    "config_generation": capability.config_generation,
                },
            )
        assert not path.exists()


def test_coordinator_records_stale_resolver_as_not_started_generation_failure():
    with short_test_directory("async5-", "repository/README.md") as directory:
        root = Path(directory)
        config_path = root / "ops.toml"
        config_path.write_text("version = 1\n", encoding="utf-8")
        with temporary_postgres() as postgres:
            def connect():
                return psycopg.connect(
                    host=postgres.host,
                    port=postgres.port,
                    user=postgres.user,
                    dbname=postgres.database,
                    password=postgres.password,
                )

            store = ControlStore(connect)
            store.initialize_schema()
            request = normalize_request(
                {
                    "schema_version": 1,
                    "job_kind": "refresh_graph",
                    "graph_id": "synthetic-refresh",
                    "request_id": "request-stale-generation",
                    "idempotency_key": "stale-generation-key",
                    "priority": "manual",
                    "operation_options": {"reason": "generation-fence"},
                },
                source_generation="sg1:source",
                config_generation="cg1:config",
            )
            submitted = store.submit(request)
            authority = ResolvedRefreshAuthority(
                graph_id="synthetic-refresh",
                config_path=config_path,
                psql_path=Path(postgres.psql_command),
                postgres_user=postgres.user,
                postgres_password=postgres.password,
                executable_search_path=search_path(),
                source_generation="sg1:newer",
                config_generation="cg1:config",
                extractor_generation="eg1:synthetic",
                canonicalizer_generation="kg1:synthetic",
            )
            coordinator = SyntheticCoordinator(
                store,
                "coordinator-stale-generation",
                build_refresh_worker_runner(
                    lambda _graph_id: authority, root, worker_limits()
                ),
                singleton_ttl=timedelta(seconds=30),
            )
            coordinator.startup(lambda: None)
            try:
                assert coordinator.run_once() == "failed"
                status = store.status(submitted.job_id)
                assert status.state == "failed"
                assert status.publication_state == "not_started"
                assert status.error_category == "generation_changed"
                with connect() as conn:
                    with conn.cursor() as cur:
                        row = cur.execute(
                            "SELECT diagnostic_summary FROM job_attempts WHERE job_id = %s",
                            (submitted.job_id,),
                        ).fetchone()
                        assert row is not None
                        assert row[0] is not None
                        assert "identity_mismatch" in row[0]
            finally:
                coordinator.shutdown()
        assert not tuple(root.glob("refresh-*.json"))


def test_worker_matches_existing_forced_full_refresh_on_disposable_graph():
    require_postgres_binaries()
    with short_test_directory("async4-", "repository/README.md") as directory:
        root = Path(directory)
        repository = root / "repository"
        repository.mkdir()
        (repository / "README.md").write_text("# Fixture\n", encoding="utf-8")
        with temporary_postgres() as postgres:
            apply_migrations(
                default_rdbms_root(),
                postgres.psql_args,
                psql_command=postgres.psql_command,
            )
            config_path = root / "ops.toml"
            config_path.write_text(
                f'''schema_version = 1

[service]
mode = "local"
mcp_transport = "stdio"
log_level = "info"

[postgres]
host = "{postgres.socket_dir}"
port = {postgres.port}
database = "repomap_test"
user = "{postgres.user}"
password_env = "REPOMAP_PG_PASSWORD"

[[graphs]]
id = "synthetic-refresh"
name = "Synthetic Refresh"
root_path = "{repository}"
repository_name = "synthetic-refresh"
privacy = "public-dev"
enabled = true
mcp_visible = false
extractor_profile = "default"
refresh_policy = "manual"

[server_memory]
enabled = false
path = "disabled"
mode = "read_only"
''',
                encoding="utf-8",
            )
            loaded_config = load_ops_config(config_path)
            configured = configured_graph(loaded_config, "synthetic-refresh")
            scan = scan_multi_source_generations(configured)
            publication_source = scan.source_generation
            publication_config = scan.config_generation
            publication_extractor = extractor_generation(configured)
            publication_canonicalizer = canonicalizer_generation()
            capability = RefreshCapability(
                schema_version=1,
                job_id="job-refresh-parity",
                attempt=1,
                graph_id="synthetic-refresh",
                config_path=config_path,
                psql_path=Path(postgres.psql_command),
                postgres_user=postgres.user,
                postgres_password=postgres.password,
                executable_search_path=search_path(),
                source_generation=publication_source,
                config_generation=publication_config,
                extractor_generation=publication_extractor,
                canonicalizer_generation=publication_canonicalizer,
                coordinator_instance_id="worker-refresh-parity",
                singleton_fencing_epoch=1,
                graph_lease_fencing_epoch=1,
            )
            path = create_refresh_capability(root, capability)
            result = run_refresh_worker(
                path,
                {"job_id": capability.job_id, "attempt": capability.attempt},
                worker_limits(),
                job_context={
                    "graph_id": capability.graph_id,
                    "source_generation": capability.source_generation,
                    "config_generation": capability.config_generation,
                },
            )
            assert postgres.password not in repr(result)
            direct = refresh_graph(
                loaded_config,
                "synthetic-refresh",
                psql_command=postgres.psql_command,
            )
            with psycopg.connect(
                host=postgres.host,
                port=postgres.port,
                user=postgres.user,
                dbname=postgres.database,
                password=postgres.password,
                autocommit=True,
            ) as bootstrap:
                bootstrap.execute("CREATE DATABASE async4_control")

            def connect():
                return psycopg.connect(
                    host=postgres.host,
                    port=postgres.port,
                    user=postgres.user,
                    dbname="async4_control",
                    password=postgres.password,
                )

            store = ControlStore(connect)
            store.initialize_schema()
            request = normalize_request(
                {
                    "schema_version": 1,
                    "job_kind": "refresh_graph",
                    "graph_id": "synthetic-refresh",
                    "request_id": "request-refresh-core",
                    "idempotency_key": "refresh-core-key",
                    "priority": "manual",
                    "operation_options": {"reason": "adapter-pilot"},
                },
                source_generation=publication_source,
                config_generation=publication_config,
                extractor_generation=publication_extractor,
                canonicalizer_generation=publication_canonicalizer,
            )
            submitted = store.submit(request)
            authority = ResolvedRefreshAuthority(
                graph_id="synthetic-refresh",
                config_path=config_path,
                psql_path=Path(postgres.psql_command),
                postgres_user=postgres.user,
                postgres_password=postgres.password,
                executable_search_path=search_path(),
                source_generation=publication_source,
                config_generation=publication_config,
                extractor_generation=publication_extractor,
                canonicalizer_generation=publication_canonicalizer,
            )
            production_runner = build_refresh_worker_runner(
                lambda _graph_id: authority, root, worker_limits()
            )
            def lose_committed_terminal(claim, cancel_event):
                terminal = dict(production_runner(claim, cancel_event))
                assert terminal["publication_state"] == "committed"
                return {
                    **terminal,
                    "status": "failed",
                    "publication_state": "commit_unknown",
                    "latest_run_identity": None,
                    "error_category": "publication_unknown",
                }
            def publication_reader(claim):
                record = read_run_publication(
                    postgres.psql_args,
                    job_id=claim.job_id,
                    attempt=claim.attempt,
                    psql_command=postgres.psql_command,
                )
                return None if record is None else record.marker()

            coordinator = SyntheticCoordinator(
                store,
                "coordinator-refresh-adapter",
                lose_committed_terminal,
                publication_reader=publication_reader,
                singleton_ttl=timedelta(seconds=30),
            )
            coordinator.startup(lambda: None)
            try:
                assert coordinator.run_once() == "succeeded"
                assert store.status(submitted.job_id).state == "succeeded"
            finally:
                coordinator.shutdown()
            with psycopg.connect(
                host=postgres.host,
                port=postgres.port,
                user=postgres.user,
                dbname=postgres.database,
                password=postgres.password,
                autocommit=True,
            ) as graph_connection:
                generation_rows = graph_connection.execute(
                    "SELECT publication_job_id, publication_attempt, "
                    "source_generation, config_generation, "
                    "extractor_generation, canonicalizer_generation "
                    "FROM runs ORDER BY id"
                ).fetchall()
        assert direct.result == "success"
        assert result.terminal["status"] == "succeeded", result
        assert result.terminal["files"] == direct.files
        assert result.terminal["observations"] == direct.observations
        assert result.terminal["publication_state"] == "committed"
        expected_generations = (
            publication_source,
            publication_config,
            publication_extractor,
            publication_canonicalizer,
        )
        assert generation_rows[0] == (
            "job-refresh-parity",
            1,
            *expected_generations,
        )
        assert generation_rows[1][0].startswith("direct-")
        assert generation_rows[1][1:] == (1, *expected_generations)
        assert generation_rows[2] == (
            submitted.job_id,
            1,
            *expected_generations,
        )

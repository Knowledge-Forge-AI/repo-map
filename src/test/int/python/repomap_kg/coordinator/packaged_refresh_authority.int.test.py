"""Resolve packaged refresh authority; prove real packaged-worker publication."""

from dataclasses import replace
from datetime import timedelta
import hashlib
import json
import os
from pathlib import Path
import secrets
import sys
from threading import Event
from unittest.mock import patch

import psycopg
import pytest

from repomap_kg.coordinator import refresh_adapter
from repomap_kg.coordinator.configured_refresh import (
    ConfiguredRefreshResolver,
    build_configured_refresh_coordinator,
)
from repomap_kg.coordinator.limits import DEFAULT_LIMITS
from repomap_kg.coordinator.refresh_adapter import (
    build_refresh_worker_runner,
    load_refresh_capability,
    remove_refresh_capability,
)
from repomap_kg.coordinator.storage import ControlStore
from repomap_kg.graph.multi_source import graph_source_binding_id
from repomap_kg.ops.config import load_ops_config
from repomap_kg.ops.graph_file_sql import GraphFileFilters
from repomap_kg.ops.graph_files import query_graph_files
from repomap_kg.runtime.database_role_contract import (
    READ_STATUS_PASSWORD_ENV,
    project_read_status_config,
)
from repomap_kg.runtime.database_roles import (
    REFRESH_PUBLICATION_ROLE,
    RoleSecrets,
    render_database_role_sql,
)
from repomap_kg.service_package.environment import apply_service_environment
from repomap_kg.storage import apply_migrations, default_rdbms_root, read_run_publication
from repomap_test_support.executable_authority import controlled_psql_copy
from repomap_test_support.postgres_harness import (
    require_postgres_binaries,
    temporary_postgres,
)
from repomap_test_support.test_scratch import short_test_directory

_WORKER_ENVIRONMENT_KEYS = {"PATH", "PGUSER", "PGPASSWORD", "PSQLRC", "LANG", "LC_ALL", "PYTHONPATH"}


def _binding_toml(alias: str, root: Path) -> str:
    return (
        f'[[graphs.source_bindings]]\nschema_version = 1\n'
        f'binding_id = "{graph_source_binding_id("fixture", alias)}"\n'
        f'source_definition_id = "src1:{alias}"\nalias = "{alias}"\nrevision = 1\nkind = "folder"\n'
        f'root_path = "{root}"\nrepository_name = "fixture-{alias}"\nlogical_root = "."\n'
        'privacy = "public-dev"\nevidence_retention = "metadata-only"\nextractor_profile = "default"\n'
        f'resolution_policy = "allow-declared"\nrole = "entry"\ninput_name = "{alias}"\n'
    )


def test_packaged_authority_reaches_prelaunch_with_durable_claim(monkeypatch):
    require_postgres_binaries()
    with short_test_directory("packaged-cap-", "source/README.md") as directory:
        root = Path(directory)
        root.chmod(0o700)
        source = root / "source"
        source.mkdir()
        (source / "README.md").write_text("# Public fixture\n", encoding="utf-8")
        with temporary_postgres() as pg:
            config = root / "ops.toml"
            config.write_text(
                'schema_version = 1\n[service]\nmode = "local"\n'
                'mcp_transport = "stdio"\nlog_level = "info"\n'
                f'[postgres]\nhost = "{pg.host}"\nport = {pg.port}\n'
                f'database = "{pg.database}"\nuser = "{pg.user}"\n'
                'password_env = "FIXTURE_PASSWORD"\n'
                '[[graphs]]\nid = "fixture"\nname = "Fixture"\n'
                f'root_path = "{source}"\nrepository_name = "fixture"\n'
                'privacy = "public-dev"\nenabled = true\nmcp_visible = false\n'
                'extractor_profile = "default"\nrefresh_policy = "manual"\n'
                '[server_memory]\nenabled = false\npath = "disabled"\nmode = "read_only"\n',
                encoding="utf-8",
            )
            config.chmod(0o600)
            resolver = ConfiguredRefreshResolver(
                config, Path(pg.psql_command), postgres_user=pg.user,
                postgres_password=pg.password,
            )
            store = ControlStore(lambda: psycopg.connect(
                host=pg.host, port=pg.port, user=pg.user,
                dbname=pg.database, password=pg.password,
            ))
            store.initialize_schema()
            submitted = store.submit(resolver.resolve_request({
                "schema_version": 1, "job_kind": "refresh_graph", "graph_id": "fixture",
                "request_id": "packaged-request", "idempotency_key": "packaged-key",
                "priority": "manual", "operation_options": {"reason": "capability-test"},
            }))
            epoch = store.acquire_singleton("packaged-instance", timedelta(seconds=30))
            claim = store.claim_next("packaged-instance", epoch, timedelta(seconds=30))
            assert claim is not None and claim.job_id == submitted.job_id
            captured = []

            class PrelaunchReached(Exception):
                pass

            def nonexecuting_worker(path, identity, limits, **kwargs):
                capability = load_refresh_capability(path)
                assert identity == {"job_id": claim.job_id, "attempt": claim.attempt}
                assert capability.source_generation == claim.source_generation
                assert capability.config_generation == claim.config_generation
                assert capability.coordinator_instance_id == claim.instance_id
                assert capability.singleton_fencing_epoch == claim.fencing_epoch
                assert capability.graph_lease_fencing_epoch == claim.graph_lease_fencing_epoch
                assert capability.executable_search_path == (Path(pg.psql_command).parent,)
                with pytest.raises(ValueError, match="invalid refresh capability"):
                    replace(capability, executable_search_path=(Path("."),)).validate()
                captured.append(capability)
                remove_refresh_capability(path)
                assert not path.exists()
                raise PrelaunchReached

            monkeypatch.chdir(root)
            try:
                with patch.dict(os.environ), patch(
                    "repomap_kg.coordinator.refresh_adapter.run_refresh_worker",
                    side_effect=nonexecuting_worker,
                ) as worker:
                    apply_service_environment(os.environ)
                    runner = build_refresh_worker_runner(resolver.resolve_authority, root, DEFAULT_LIMITS)
                    with pytest.raises(PrelaunchReached):
                        runner(claim, Event())
                    worker.assert_called_once()
                assert len(captured) == 1
                assert not tuple(root.glob("refresh-*.json"))
            finally:
                store.stop_singleton("packaged-instance", epoch)


def test_packaged_worker_publishes_two_binding_fixture_through_real_protocol(monkeypatch):
    """Unmocked positive proof: real child, real protocol, production publisher."""
    require_postgres_binaries()
    with short_test_directory("packaged-pub-", "alpha/README.md") as directory:
        root = Path(directory)
        root.chmod(0o700)
        for alias in ("alpha", "beta"):
            (root / alias).mkdir()
            (root / alias / "README.md").write_text(f"# {alias} fixture\n", encoding="utf-8")
        psql = controlled_psql_copy(root)
        role_secrets = RoleSecrets(*(secrets.token_urlsafe(24) for _ in range(3)))
        with temporary_postgres() as pg:
            apply_migrations(default_rdbms_root(), pg.psql_args, psql_command=pg.psql_command)
            owner = dict(host=pg.host, port=pg.port, user=pg.user, password=pg.password)
            with psycopg.connect(dbname=pg.database, **owner) as admin:
                admin.execute(render_database_role_sql(
                    database=pg.database, owner_role=pg.user, database_kind="graph", secrets=role_secrets,
                ))
            control = pg.create_database("pwfix1_control")
            try:
                config = root / "ops.toml"
                config.write_text(
                    'schema_version = 1\n[service]\nmode = "local"\nmcp_transport = "stdio"\nlog_level = "info"\n'
                    f'[postgres]\nhost = "{pg.host}"\nport = {pg.port}\ndatabase = "{pg.database}"\n'
                    f'user = "{pg.user}"\npassword_env = "FIXTURE_PASSWORD"\n'
                    '[[graphs]]\nid = "fixture"\nname = "Fixture"\nenabled = true\nmcp_visible = false\n'
                    f'refresh_policy = "manual"\ndatabase = "{pg.database}"\n'
                    + _binding_toml("alpha", root / "alpha") + _binding_toml("beta", root / "beta")
                    + '[server_memory]\nenabled = false\npath = "disabled"\nmode = "read_only"\n',
                    encoding="utf-8",
                )
                config.chmod(0o600)
                store = ControlStore(lambda: psycopg.connect(dbname=control.database, **owner))
                store.initialize_schema()
                resolver = ConfiguredRefreshResolver(
                    config, psql, postgres_user=REFRESH_PUBLICATION_ROLE,
                    postgres_password=role_secrets.refresh_publication,
                )
                original = refresh_adapter._run_protocol_worker
                launches = []

                def observe_launch(argv, environment, cwd, *args, **kwargs):
                    sealed = load_refresh_capability(Path(argv[4]))
                    result = original(argv, environment, cwd, *args, **kwargs)
                    launches.append({
                        "argv": tuple(argv), "keys": set(environment), "path": environment["PATH"], "cwd": cwd,
                        "endpoint": (sealed.postgres_host, sealed.postgres_port, sealed.postgres_route_kind),
                        "search_path": sealed.executable_search_path, "result": result,
                    })
                    return result

                monkeypatch.chdir(root)
                with patch.dict(os.environ), patch.object(refresh_adapter, "_run_protocol_worker", observe_launch):
                    apply_service_environment(os.environ)
                    assert "PATH" not in os.environ
                    request = resolver.resolve_request({
                        "schema_version": 1, "job_kind": "refresh_graph", "graph_id": "fixture",
                        "request_id": "packaged-publication", "idempotency_key": "packaged-publication-key",
                        "priority": "manual", "operation_options": {"reason": "packaged-publication"},
                    })
                    submitted = store.submit(request)
                    authority = resolver.resolve_authority("fixture")
                    assert (authority.postgres_host, authority.postgres_port, authority.postgres_route_kind) == (
                        pg.host, pg.port, "configured")
                    assert authority.executable_search_path == (psql.parent,)
                    coordinator = build_configured_refresh_coordinator(store, "packaged-publisher", resolver, root)
                    coordinator.startup(lambda: None)
                    try:
                        outcome = coordinator.run_once()
                    finally:
                        coordinator.shutdown()
                assert len(launches) == 1, launches
                launch = launches[0]
                result = launch["result"]
                assert launch["argv"][:3] == (sys.executable, "-m", "repomap_kg.coordinator.refresh_worker")
                assert launch["keys"] <= _WORKER_ENVIRONMENT_KEYS and launch["path"] == str(psql.parent)
                assert launch["cwd"] == root.resolve()
                assert launch["endpoint"] == (pg.host, pg.port, "configured")
                assert launch["search_path"] == (psql.parent,)
                assert (result.synthesized_terminal, result.protocol_error, result.returncode) == (False, None, 0)
                assert result.waited and result.process_group_cleaned
                terminal = result.terminal
                assert (terminal["status"], terminal["publication_state"], terminal["error_category"]) == (
                    "succeeded", "committed", None), terminal
                assert outcome == "succeeded"
                status = store.status(submitted.job_id)
                assert (status.state, status.publication_state, status.error_category) == ("succeeded", "committed", None)
                for secret in (role_secrets.refresh_publication, pg.password):
                    assert secret not in repr(result)
                record = read_run_publication(
                    pg.psql_args, job_id=submitted.job_id, attempt=1, psql_command=pg.psql_command,
                )
                assert record is not None
                marker = record.marker()
                assert marker["latest_run_identity"] == terminal["latest_run_identity"]
                assert (marker["source_generation"], marker["config_generation"]) == (
                    request.source_generation, request.config_generation)
                attempt = hashlib.sha256(f"{submitted.job_id}\0{1}".encode()).hexdigest()
                retained = root.resolve() / "state/portable-publication/attempts" / attempt / "portable-result.json"
                assert json.loads(retained.read_text(encoding="utf-8"))["retention_class"] == "terminal-accepted"
                monkeypatch.setenv(READ_STATUS_PASSWORD_ENV, role_secrets.read_status)
                page = query_graph_files(
                    project_read_status_config(load_ops_config(config)), "fixture", filters=GraphFileFilters(),
                )
                paths = {(item.binding_alias, item.path) for item in page.records}
                assert {("alpha", "README.md"), ("beta", "README.md")} <= paths, paths
                assert {item.binding_alias for item in page.records} == {"alpha", "beta"}
                assert len({item.candidate_id for item in page.records}) == 1
                assert None not in {item.candidate_id for item in page.records}
                assert not tuple(root.glob("refresh-*.json"))
            finally:
                with psycopg.connect(dbname=pg.database, autocommit=True, **owner) as admin:
                    admin.execute("DROP DATABASE pwfix1_control WITH (FORCE)")

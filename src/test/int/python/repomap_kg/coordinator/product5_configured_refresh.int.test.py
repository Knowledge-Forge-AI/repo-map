"""Integration tests for configured refresh resolution, fencing, and execution boundaries.

Behavioral coverage for configured_refresh.py, _configured_fencing.py, and refresh_adapter.py
under REPOMAP-PRODUCT5-HOSTED-CI-REPAIR2.
"""

from __future__ import annotations

import threading
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import psycopg
import pytest
from repomap_kg.coordinator.configured_refresh import (
    ConfiguredRefreshResolver,
    build_configured_refresh_coordinator,
)
from repomap_kg.coordinator.refresh_adapter import (
    RefreshSourceError,
    build_refresh_worker_runner,
)
from repomap_kg.coordinator.startup_recovery import PublicationRouteChangedError
from repomap_test_support.executable_authority import controlled_psql_copy
from repomap_test_support.portable_worker_scenarios import coordinator_test_limits
from repomap_test_support.startup_recovery_scenarios import (
    _make_refresh_fixture,
    _refresh_harness,
)


def _write_contract_config(
    config_path: Path,
    repository: Path,
    *,
    password_file: str | None = None,
    password_env: str | None = None,
    password: str | None = "test-only-password",
) -> None:
    lines = ["[postgres]", 'host = "localhost"', "port = 5432", 'database = "repomap_test"', 'user = "test_user"']
    if password is not None:
        lines.append(f'password = "{password}"')
    if password_file is not None:
        lines.append(f'password_file = "{password_file}"')
    if password_env is not None:
        lines.append(f'password_env = "{password_env}"')
    pg_block = "\n".join(lines)
    config_path.write_text(
        f'schema_version = 1\n[service]\nmode = "local"\nmcp_transport = "stdio"\nlog_level = "info"\n'
        f"{pg_block}\n"
        f'[[graphs]]\nid = "fixture-g1"\nname = "Fixture Graph"\ndatabase = "fixture_g1_db"\nroot_path = "{repository}"\n'
        'repository_name = "fixture-g1"\nprivacy = "public-dev"\nenabled = true\nmcp_visible = false\nextractor_profile = "default"\nrefresh_policy = "polling"\n'
        '[[graphs]]\nid = "fixture-ms"\nname = "Multi Source"\ndatabase = "fixture_ms_db"\n'
        'enabled = true\nmcp_visible = false\nrefresh_policy = "polling"\n'
        '[[graphs.source_bindings]]\nschema_version = 1\nsource_definition_id = "src1:1"\nalias = "src1"\nrevision = 1\nkind = "folder"\n'
        f'root_path = "{repository}"\nrepository_name = "fixture"\nlogical_root = "."\nprivacy = "public-dev"\nevidence_retention = "metadata-only"\n'
        'extractor_profile = "default"\nresolution_policy = "allow-declared"\nrole = "entry"\ninput_name = "src1"\n'
        '[[graphs]]\nid = "fixture-disabled-binding"\nname = "Disabled Binding"\ndatabase = "fixture_disabled_db"\n'
        'enabled = true\nmcp_visible = false\nrefresh_policy = "manual"\n'
        '[[graphs.source_bindings]]\nschema_version = 1\nsource_definition_id = "src1:2"\nalias = "src2"\nrevision = 1\nkind = "folder"\n'
        f'root_path = "{repository}"\nrepository_name = "fixture"\nlogical_root = "."\nprivacy = "public-dev"\nevidence_retention = "metadata-only"\n'
        'extractor_profile = "default"\nresolution_policy = "allow-declared"\nrole = "entry"\ninput_name = "src2"\nenabled = false\n'
        '[server_memory]\nenabled = false\npath = "disabled"\nmode = "read_only"\n',
        encoding="utf-8",
    )


def test_configured_refresh_resolver_authority_and_payload_contracts(tmp_path: Path) -> None:
    psql = controlled_psql_copy(tmp_path)
    cfg = tmp_path / "authority_ops.toml"
    cfg.write_text("version = 1\n", encoding="utf-8")

    with pytest.raises(ValueError, match="configured refresh authority is incomplete"):
        ConfiguredRefreshResolver(cfg, psql, postgres_user="user_only", postgres_password=None)
    with pytest.raises(ValueError, match="configured refresh authority is incomplete"):
        ConfiguredRefreshResolver(cfg, psql, postgres_user=None, postgres_password="pass_only")

    resolver = ConfiguredRefreshResolver(cfg, psql)
    with pytest.raises(ValueError, match="configured refresh request is invalid"):
        resolver.resolve_request("not-a-mapping")
    with pytest.raises(ValueError, match="configured refresh request is invalid"):
        resolver.resolve_request([1, 2, 3])

    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "README.md").write_text("# Test\n", encoding="utf-8")
    cfg_valid = tmp_path / "valid_ops.toml"
    _write_contract_config(cfg_valid, repo)
    resolver_valid = ConfiguredRefreshResolver(cfg_valid, psql)

    polling = resolver_valid.polling_graphs()
    assert ("fixture-g1", "polling") in polling
    assert not any(gid == "fixture-ms" for gid, _ in polling)

    with pytest.raises(ValueError, match="multi-source graph polling refresh is unsupported"):
        resolver_valid.polling_snapshot("fixture-ms")
    with pytest.raises(ValueError, match="source-binding-refresh-unsupported"):
        resolver_valid.polling_snapshot("fixture-disabled-binding")

    req_disabled = {
        "schema_version": 1, "job_kind": "refresh_graph", "graph_id": "fixture-disabled-binding",
        "request_id": "r-disabled", "idempotency_key": "k-disabled", "priority": "manual",
    }
    with pytest.raises(ValueError, match="source-binding-refresh-unsupported"):
        resolver_valid.resolve_request(req_disabled)

    cfg_missing = tmp_path / "missing_ops.toml"
    _write_contract_config(cfg_missing, tmp_path / "nonexistent_repo")
    resolver_missing = ConfiguredRefreshResolver(cfg_missing, psql)
    req_missing = {
        "schema_version": 1, "job_kind": "refresh_graph", "graph_id": "fixture-g1",
        "request_id": "r-missing", "idempotency_key": "k-missing", "priority": "manual",
    }
    with pytest.raises(ValueError, match="configured graph root is unavailable"):
        resolver_missing.resolve_request(req_missing)


def test_configured_refresh_credential_security_contracts(tmp_path: Path) -> None:
    psql = controlled_psql_copy(tmp_path)
    repo = tmp_path / "repo_cred"
    repo.mkdir()
    (repo / "README.md").write_text("# Credential Test\n", encoding="utf-8")

    req = {
        "schema_version": 1, "job_kind": "refresh_graph", "graph_id": "fixture-g1",
        "request_id": "r-cred", "idempotency_key": "k-cred", "priority": "manual",
    }

    cfg_env = tmp_path / "ops_env.toml"
    _write_contract_config(cfg_env, repo, password=None, password_env="UNSET_REPOMAP_VAR_XYZ_123")
    res_env = ConfiguredRefreshResolver(cfg_env, psql)
    with pytest.raises(ValueError, match="postgres credential is unavailable"):
        res_env.resolve_request(req)

    cfg_absent = tmp_path / "ops_absent.toml"
    _write_contract_config(cfg_absent, repo, password=None)
    with pytest.raises(ValueError, match="postgres credential is unavailable"):
        ConfiguredRefreshResolver(cfg_absent, psql).resolve_request(req)

    cfg_long = tmp_path / "ops_long.toml"
    _write_contract_config(cfg_long, repo, password="a" * 257)
    res_long = ConfiguredRefreshResolver(cfg_long, psql)
    with pytest.raises(ValueError, match="postgres credential is unavailable"):
        res_long.resolve_request(req)

    pass_file = tmp_path / "secret.key"
    pass_file.write_text("secret_pw\n", encoding="utf-8")
    pass_file.chmod(0o666)
    cfg_file = tmp_path / "ops_file.toml"
    _write_contract_config(cfg_file, repo, password=None, password_file="secret.key")
    res_file = ConfiguredRefreshResolver(cfg_file, psql)
    with pytest.raises(ValueError, match="postgres credential is unavailable"):
        res_file.resolve_request(req)

    pass_file.chmod(0o600)
    pass_file.write_text("x" * 4097, encoding="utf-8")
    with pytest.raises(ValueError, match="postgres credential is unavailable"):
        res_file.resolve_request(req)

    pass_file.write_text("secure_password\n", encoding="utf-8")
    resolved = res_file.resolve_request(req)
    assert resolved.graph_id == "fixture-g1"
    assert resolved.source_generation.startswith("sg1:")
    assert resolved.config_generation.startswith("cg1:")
    cfg_absolute = tmp_path / "ops_absolute.toml"
    _write_contract_config(cfg_absolute, repo, password=None, password_file=str(pass_file))
    assert ConfiguredRefreshResolver(cfg_absolute, psql).resolve_request(req).graph_id == "fixture-g1"


def test_configured_fencing_epoch_and_route_refusals() -> None:
    with _refresh_harness() as (store, cap_dir, connect, postgres, graph_db):
        config, sg, cg, eg, kg = _make_refresh_fixture(postgres, cap_dir, graph_db)
        resolver = ConfiguredRefreshResolver(
            config, Path(postgres.psql_command), postgres_user=postgres.user, postgres_password=postgres.password,
        )

        claim_mismatch = SimpleNamespace(
            graph_id="synthetic-g1", config_generation="cg1:stale_mismatched",
            job_id="job-fence-mismatch", attempt=1, graph_lease_fencing_epoch=0,
        )
        with pytest.raises(PublicationRouteChangedError, match="configured storage route changed"):
            resolver.read_publication(claim_mismatch)
        with pytest.raises(PublicationRouteChangedError, match="configured storage route changed"):
            resolver.install_graph_publication_fence(
                claim_mismatch, reconciler_instance_id="rec-1", reconciler_epoch=1,
                prior_lease_epoch=0, replacement_lease_epoch=1,
            )

        claim_valid_cg = SimpleNamespace(
            graph_id="synthetic-g1", config_generation=cg,
            job_id="job-fence-1", attempt=1, graph_lease_fencing_epoch=2,
        )
        with pytest.raises(ValueError, match="replacement_lease_epoch is required and must be positive for exact legacy zeros"):
            resolver.install_graph_publication_fence(
                claim_valid_cg, reconciler_instance_id="rec-1", reconciler_epoch=1,
                prior_lease_epoch=0, replacement_lease_epoch=1,
            )

        claim_legacy = SimpleNamespace(
            graph_id="synthetic-g1", config_generation=cg,
            job_id="job-fence-1", attempt=1, graph_lease_fencing_epoch=0,
        )
        for bad_replacement in (None, 0):
            with pytest.raises(ValueError, match="replacement_lease_epoch is required and must be positive for exact legacy zeros"):
                resolver.install_graph_publication_fence(
                    claim_legacy, reconciler_instance_id="rec-1", reconciler_epoch=1,
                    prior_lease_epoch=0, replacement_lease_epoch=bad_replacement,
                )

        with pytest.raises(ValueError, match="replacement_lease_epoch is only permitted for exact legacy zeros"):
            resolver.install_graph_publication_fence(
                claim_legacy, reconciler_instance_id="rec-1", reconciler_epoch=1,
                prior_lease_epoch=1, replacement_lease_epoch=2,
            )

        with pytest.raises(ValueError, match="durable graph lease epoch is unavailable or mismatched"):
            resolver.install_graph_publication_fence(
                claim_legacy, reconciler_instance_id="rec-1", reconciler_epoch=1,
                prior_lease_epoch=1, replacement_lease_epoch=None,
            )

        claim_neg = SimpleNamespace(
            graph_id="synthetic-g1", config_generation=cg, graph_lease_fencing_epoch=-1,
            job_id="job-fence-neg", attempt=1,
        )
        with pytest.raises(ValueError, match="durable graph lease epoch is unavailable or mismatched"):
            resolver.install_graph_publication_fence(
                claim_neg, reconciler_instance_id="rec-1", reconciler_epoch=1,
                prior_lease_epoch=-1, replacement_lease_epoch=None,
            )


def test_configured_publication_fence_and_coordinator_lifecycle() -> None:
    with _refresh_harness() as (store, cap_dir, connect, postgres, graph_db):
        config, sg, cg, eg, kg = _make_refresh_fixture(postgres, cap_dir, graph_db)
        resolver = ConfiguredRefreshResolver(
            config, Path(postgres.psql_command), postgres_user=postgres.user, postgres_password=postgres.password,
        )

        req = resolver.resolve_request({
            "schema_version": 1, "job_kind": "refresh_graph", "graph_id": "synthetic-g1",
            "request_id": "req-live-1", "idempotency_key": "k-live-1", "priority": "manual",
            "operation_options": {"reason": "test"},
        })
        store.submit(req)
        epoch = store.acquire_singleton("coord-inst-live", timedelta(seconds=300))
        claim = store.claim_next("coord-inst-live", epoch, timedelta(seconds=300))
        assert claim is not None

        assert resolver.read_publication(claim) is None

        installed = resolver.install_graph_publication_fence(
            claim, reconciler_instance_id=claim.instance_id, reconciler_epoch=epoch,
            prior_lease_epoch=claim.graph_lease_fencing_epoch,
        )
        assert installed is True

        with psycopg.connect(
            host=postgres.host, port=postgres.port, user=postgres.user, dbname=graph_db, password=postgres.password,
        ) as conn:
            with conn.cursor() as cur:
                row = cur.execute(
                    "SELECT singleton_fencing_epoch, graph_lease_fencing_epoch, coordinator_instance_id, job_id, attempt "
                    "FROM graph_publication_authority WHERE job_id = %s",
                    (claim.job_id,),
                ).fetchone()
                assert row == (epoch, claim.graph_lease_fencing_epoch, claim.instance_id, claim.job_id, claim.attempt)

        coord = build_configured_refresh_coordinator(store, "coord-inst-live", resolver, cap_dir)
        assert coord is not None

        assert store.compare_and_set_state(
            claim.job_id, expected_state="claimed", new_state="starting",
            attempt=claim.attempt, instance_id=claim.instance_id, fencing_epoch=epoch,
        )
        assert store.compare_and_set_state(
            claim.job_id, expected_state="starting", new_state="running",
            attempt=claim.attempt, instance_id=claim.instance_id, fencing_epoch=epoch,
        )

        runner = build_refresh_worker_runner(
            resolver.resolve_authority, cap_dir, coordinator_test_limits(),
            fencing_prover=store.in_process_fencing_proof,
            launch_registrar=store.register_supervisor_launch,
        )
        term = runner(claim, threading.Event())
        assert term["status"] == "succeeded"
        assert term["_termination_proved"] is True

        marker = resolver.read_publication(claim)
        assert marker is not None
        assert store.record_publication_marker(
            claim, run_identity=marker["latest_run_identity"],
            source_generation=marker["source_generation"], config_generation=marker["config_generation"],
            extractor_generation=marker["extractor_generation"], canonicalizer_generation=marker["canonicalizer_generation"],
            outcome="committed",
        )
        assert store.compare_and_set_state(
            claim.job_id, expected_state="running", new_state="succeeded", attempt=claim.attempt,
            instance_id=claim.instance_id, fencing_epoch=epoch, publication_state="committed",
        )
        assert store.status(claim.job_id).state == "succeeded"
        assert store.stop_singleton(claim.instance_id, epoch)


def test_refresh_adapter_runner_contract_and_generation_safeguards() -> None:
    with _refresh_harness() as (store, cap_dir, connect, postgres, graph_db):
        config, sg, cg, eg, kg = _make_refresh_fixture(postgres, cap_dir, graph_db)
        resolver = ConfiguredRefreshResolver(
            config, Path(postgres.psql_command), postgres_user=postgres.user, postgres_password=postgres.password,
        )

        for bad_limit in (0, -1, 3601, True):
            with pytest.raises(ValueError, match="process_deadline_seconds must be a positive integer <= 3600"):
                build_refresh_worker_runner(
                    resolver.resolve_authority, cap_dir,
                    {"process_deadline_seconds": bad_limit, "refresh_attempt_deadline_seconds": 4000, "heartbeat_seconds": 1.0},
                )

        runner = build_refresh_worker_runner(resolver.resolve_authority, cap_dir, coordinator_test_limits())

        claim_wrong_gid = SimpleNamespace(
            job_id="job-wrong-gid", attempt=1, graph_id="other-graph-id",
            source_generation=sg, config_generation=cg,
            extractor_generation=eg, canonicalizer_generation=kg,
            instance_id="inst-1", fencing_epoch=1, graph_lease_fencing_epoch=1,
        )
        with pytest.raises(ValueError, match="invalid refresh capability"):
            build_refresh_worker_runner(lambda _: resolver.resolve_authority("synthetic-g1"), cap_dir, coordinator_test_limits())(claim_wrong_gid, threading.Event())

        runner_source_err = build_refresh_worker_runner(
            lambda _gid: (_ for _ in ()).throw(RefreshSourceError("source_unavailable")),
            cap_dir, coordinator_test_limits(),
        )
        term_src = runner_source_err(claim_wrong_gid, threading.Event())
        assert term_src["status"] == "failed"
        assert term_src["error_category"] == "source_unavailable"

        claim_gen_diff = SimpleNamespace(
            job_id="job-stale-gen", attempt=1, graph_id="synthetic-g1",
            source_generation="sg1:stale_changed", config_generation=cg,
            extractor_generation=eg, canonicalizer_generation=kg,
            instance_id="inst-1", fencing_epoch=1, graph_lease_fencing_epoch=1,
        )
        term_diff = runner(claim_gen_diff, threading.Event())
        assert term_diff["status"] == "failed"
        assert term_diff["error_category"] == "generation_changed"

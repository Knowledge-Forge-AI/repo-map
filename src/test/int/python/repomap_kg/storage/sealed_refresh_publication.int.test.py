"""Sealed pre-turnover authority exercises the maintained worker storage route."""

from datetime import timedelta
import io
import json
from pathlib import Path
import secrets
from types import SimpleNamespace

import psycopg

from repomap_kg.coordinator import _publication_phase
from repomap_kg.coordinator import refresh_worker
from repomap_kg.coordinator.configured_refresh import ConfiguredRefreshResolver
from repomap_kg.coordinator.protocol import encode_jsonl
from repomap_kg.coordinator.refresh_adapter import (
    RefreshCapability, create_refresh_capability, load_refresh_capability,
)
from repomap_kg.ops.config import load_ops_config
from repomap_kg.ops.generations import (
    canonicalizer_generation, configured_graph, extractor_generation,
)
from repomap_kg.ops.resolved_config import configured_repository_identity
from repomap_kg.graph.multi_source_pipeline import scan_multi_source_generations
from repomap_kg.runtime.postgres_route import effective_postgres_route
from repomap_kg.storage import apply_migrations, default_rdbms_root, staged_ingestion
from repomap_test_support.startup_recovery_scenarios import (
    _make_refresh_fixture, _refresh_harness, _req_norm,
    _run_real_refresh_attempt, _search_path,
)


def _advance_running(store, claim):
    for before, after in (("claimed", "starting"), ("starting", "running")):
        assert store.compare_and_set_state(
            claim.job_id, expected_state=before, new_state=after,
            attempt=claim.attempt, instance_id=claim.instance_id,
            fencing_epoch=claim.fencing_epoch,
        )


def _seal(postgres, cap_dir, config, claim, sg, cg, eg, kg):
    route = effective_postgres_route(load_ops_config(config))
    return create_refresh_capability(cap_dir, RefreshCapability(
        schema_version=1, job_id=claim.job_id, attempt=claim.attempt,
        graph_id=claim.graph_id, config_path=config,
        psql_path=Path(postgres.psql_command), postgres_user=postgres.user,
        postgres_host=route.host, postgres_port=route.port,
        postgres_route_kind=route.kind, postgres_password=postgres.password,
        executable_search_path=_search_path(), source_generation=sg,
        config_generation=cg, extractor_generation=eg, canonicalizer_generation=kg,
        coordinator_instance_id=claim.instance_id,
        singleton_fencing_epoch=claim.fencing_epoch,
        graph_lease_fencing_epoch=claim.graph_lease_fencing_epoch,
    ))


def _finish_published(store, claim, terminal, connect):
    assert terminal["status"] == "succeeded" and terminal["_termination_proved"]
    store.record_publication_marker(
        claim, run_identity=terminal["latest_run_identity"], outcome="committed",
        **{key: terminal[key] for key in ("source_generation", "config_generation",
                                         "extractor_generation", "canonicalizer_generation")},
    )
    assert store.compare_and_set_state(
        claim.job_id, expected_state="running", new_state="succeeded",
        attempt=claim.attempt, instance_id=claim.instance_id,
        fencing_epoch=claim.fencing_epoch, publication_state="committed",
    )
    assert store.release_graph_lease(
        claim.graph_id, claim.job_id, claim.attempt, claim.instance_id, claim.fencing_epoch,
        reconciler_instance_id=claim.instance_id, reconciler_epoch=claim.fencing_epoch,
    )
    assert store.status(claim.job_id).state == "succeeded"
    assert store.status(claim.job_id).publication_state == "committed"
    with connect() as connection:
        assert connection.execute(
            "SELECT is_current, finished_at IS NOT NULL, publication_state FROM job_attempts "
            "WHERE job_id = %s AND attempt = %s", (claim.job_id, claim.attempt),
        ).fetchone() == (False, True, "committed")


def _install_fence_owner(store, config, postgres):
    resolver = ConfiguredRefreshResolver(
        config, Path(postgres.psql_command),
        postgres_user=postgres.user, postgres_password=postgres.password,
    )
    store.set_durable_fence_callback(resolver.install_graph_publication_fence)


def _assert_no_publication(postgres, database):
    with psycopg.connect(host=postgres.host, port=postgres.port, user=postgres.user,
                         dbname=database, password=postgres.password) as connection:
        for relation in ("files", "raw_observations", "canonical_nodes", "canonical_edges",
                         "canonical_evidence", "canonical_node_evidence", "canonical_edge_evidence"):
            assert connection.execute(f"SELECT count(*) FROM {relation}").fetchone() == (0,)
        for condition in ("status = 'complete'", "publication_job_id IS NOT NULL"):
            assert connection.execute(f"SELECT count(*) FROM runs WHERE {condition}").fetchone() == (0,)


def _worker_terminal(monkeypatch, sealed):
    """Drive the real worker main, protocol START and unchanged refresh/storage."""
    capability = load_refresh_capability(sealed)
    start = dict(schema_version=1, message_type="job_start", job_kind="refresh_graph",
                 job_id=capability.job_id, attempt=capability.attempt,
                 graph_id=capability.graph_id,
                 source_generation=capability.source_generation,
                 config_generation=capability.config_generation)
    output = io.BytesIO()
    with monkeypatch.context() as streams:
        streams.setattr(refresh_worker.sys, "stdin", SimpleNamespace(buffer=io.BytesIO(encode_jsonl(start))))
        streams.setattr(refresh_worker.sys, "stdout", SimpleNamespace(buffer=output))
        streams.setattr(refresh_worker.sys, "stderr", io.StringIO())
        assert refresh_worker.main([
            "--capability", str(sealed), "--job-id", capability.job_id,
            "--attempt", str(capability.attempt),
        ]) == 0
    messages = [json.loads(line) for line in output.getvalue().splitlines()]
    assert messages[0]["message_type"] == "worker_hello"
    assert messages[-1]["message_type"] in {"result", "error"}
    return messages[-1]


def test_t1a_staged_transaction_before_turnover_refuses_callback(monkeypatch):
    """T1a: Staged transaction established before B turnover; B truthful closure and retry; A refuses."""
    with _refresh_harness() as (store, cap_dir, connect, postgres, graph_db):
        config, sg, cg, eg, kg = _make_refresh_fixture(postgres, cap_dir, graph_db)
        monkeypatch.setenv("REPOMAP_PG_PASSWORD", postgres.password)
        store.submit(_req_norm("sealed-turnover-t1a", sg, cg, eg, kg))
        old_epoch = store.acquire_singleton("sealed-owner-a", timedelta(seconds=300))
        claim_a = store.claim_next("sealed-owner-a", old_epoch, timedelta(seconds=300))
        assert claim_a is not None
        _advance_running(store, claim_a)
        sealed = _seal(postgres, cap_dir, config, claim_a, sg, cg, eg, kg)
        original_bytes = sealed.read_bytes()
        _publication_phase.initialize(cap_dir, claim_a)
        _install_fence_owner(store, config, postgres)
        real_check = _publication_phase.before_publication
        transactions = []
        original_transaction = staged_ingestion.execute_final_transaction

        def observe_transaction(*args, **kwargs):
            transactions.append("entered")
            return original_transaction(*args, **kwargs)

        monkeypatch.setattr(staged_ingestion, "execute_final_transaction", observe_transaction)
        staged_verified = False
        new_epoch = None
        checks = []

        def observe_check_t1a(directory, attempt):
            nonlocal staged_verified, new_epoch
            checks.append("entered")

            with psycopg.connect(host=postgres.host, port=postgres.port, user=postgres.user,
                                 dbname=graph_db, password=postgres.password) as graph_conn:
                stage_row = graph_conn.execute(
                    "SELECT state, merge_status, validation_status FROM ingestion_stages WHERE job_id = %s",
                    (claim_a.job_id,),
                ).fetchone()
                assert stage_row == ("validated", "not_started", "passed")
                run_row = graph_conn.execute(
                    "SELECT status FROM runs WHERE status = 'running'",
                ).fetchone()
                assert run_row == ("running",)
            staged_verified = True

            with connect() as connection:
                connection.execute("UPDATE coordinator_instances SET expires_at = now() - interval '1 second'")
                connection.execute("UPDATE graph_leases SET expires_at = now() - interval '1 second'")
            new_epoch = store.acquire_singleton("sealed-owner-b", timedelta(seconds=300))
            assert new_epoch > old_epoch
            assert store.recover_abandoned_attempts("sealed-owner-b", new_epoch, 1) == 1

            closed = store.close_unpublished_reconciliation(
                claim_a, reconciler_instance_id="sealed-owner-b", reconciler_epoch=new_epoch,
                file_closer=lambda c, proof: _publication_phase.close_unpublished(cap_dir, c, proof=proof),
            )
            assert closed is True
            assert store.status(claim_a.job_id).publication_state == "not_started"

            outcome = store.reconcile_publication(
                claim_a, reconciler_instance_id="sealed-owner-b", reconciler_epoch=new_epoch,
                unpublished_proved=True,
            )
            assert outcome == "queued"
            assert store.status(claim_a.job_id).state == "queued"
            assert store.status(claim_a.job_id).publication_state == "not_started"
            assert sealed.read_bytes() == original_bytes

            try:
                real_check(directory, attempt)
            except FileExistsError:
                checks.append("refused")
                raise

        monkeypatch.setattr(_publication_phase, "before_publication", observe_check_t1a)
        rejected = _worker_terminal(monkeypatch, sealed)
        assert rejected["status"] == "failed"
        assert staged_verified is True
        assert checks == ["entered", "refused"]
        assert transactions == []
        assert new_epoch is not None

        _assert_no_publication(postgres, graph_db)

        with connect() as connection:
            connection.execute(
                "UPDATE jobs SET next_eligible_at = now() - interval '1 second' WHERE job_id = %s",
                (claim_a.job_id,),
            )
        claim_b = store.claim_next("sealed-owner-b", new_epoch, timedelta(seconds=300))
        assert claim_b is not None
        assert claim_b.job_id == claim_a.job_id
        assert claim_b.attempt == claim_a.attempt + 1
        assert claim_b.instance_id == "sealed-owner-b"
        assert claim_b.fencing_epoch == new_epoch
        assert claim_b.graph_lease_fencing_epoch > claim_a.graph_lease_fencing_epoch
        _advance_running(store, claim_b)

        cap_b = cap_dir / "replacement"
        cap_b.mkdir(mode=0o700)
        monkeypatch.setattr(_publication_phase, "before_publication", real_check)
        terminal = _run_real_refresh_attempt(postgres, cap_b, claim_b, config, sg, cg, eg, kg)
        _finish_published(store, claim_b, terminal, connect)

        with psycopg.connect(host=postgres.host, port=postgres.port, user=postgres.user,
                             dbname=graph_db, password=postgres.password) as graph_conn:
            assert graph_conn.execute("SELECT count(*) FROM runs WHERE publication_job_id IS NOT NULL").fetchone() == (1,)
            files = graph_conn.execute("SELECT count(*) FROM files").fetchone()
            assert files is not None and files[0] > 0

        sealed.unlink()
        assert store.stop_singleton("sealed-owner-b", new_epoch)


def test_t1b_post_callback_turnover_fences_storage_and_allows_replacement_publication(monkeypatch):
    """T1b: Wrapper calls real callback while A current, B fences A, A storage rejects, B publishes."""
    with _refresh_harness() as (store, cap_dir, connect, postgres, graph_db):
        monkeypatch.setenv("REPOMAP_PG_PASSWORD", postgres.password)
        graph_db_b = f"repomap_graph_{secrets.token_hex(4)}"
        with psycopg.connect(host=postgres.host, port=postgres.port, user=postgres.user,
                             dbname=postgres.database, password=postgres.password, autocommit=True) as admin_conn:
            admin_conn.execute(f"CREATE DATABASE {graph_db_b}")
        apply_migrations(
            default_rdbms_root(),
            [a if a != postgres.database else graph_db_b for a in postgres.psql_args],
            psql_command=postgres.psql_command,
        )

        try:
            repo_a, repo_b = cap_dir / "repo", cap_dir / "repo_b"
            for repository in (repo_a, repo_b):
                repository.mkdir(parents=True, exist_ok=True)
                (repository / "README.md").write_text("# Test Repo\n", encoding="utf-8")

            config = cap_dir / "ops.toml"
            config.write_text(
                f'schema_version = 1\n[service]\nmode = "local"\nmcp_transport = "stdio"\nlog_level = "info"\n'
                f'[postgres]\nhost = "{postgres.socket_dir}"\nport = {postgres.port}\ndatabase = "{graph_db}"\n'
                f'user = "{postgres.user}"\npassword_env = "REPOMAP_PG_PASSWORD"\n'
                f'[[graphs]]\nid = "synthetic-g1"\nname = "Synthetic Refresh A"\nroot_path = "{repo_a}"\n'
                f'repository_name = "synthetic-g1"\ndatabase = "{graph_db}"\nprivacy = "public-dev"\n'
                f'enabled = true\nmcp_visible = false\nextractor_profile = "default"\nrefresh_policy = "manual"\n'
                f'[[graphs]]\nid = "synthetic-g2"\nname = "Synthetic Refresh B"\nroot_path = "{repo_b}"\n'
                f'repository_name = "synthetic-g2"\ndatabase = "{graph_db_b}"\nprivacy = "public-dev"\n'
                f'enabled = true\nmcp_visible = false\nextractor_profile = "default"\nrefresh_policy = "manual"\n'
                f'[server_memory]\nenabled = false\npath = "disabled"\nmode = "read_only"\n',
                encoding="utf-8",
            )

            ops_cfg = load_ops_config(config)
            conf_a = configured_graph(ops_cfg, "synthetic-g1")
            scan_a = scan_multi_source_generations(conf_a)
            sg_a, cg_a, eg_a, kg_a = scan_a.source_generation, scan_a.config_generation, extractor_generation(conf_a), canonicalizer_generation()

            conf_b = configured_graph(ops_cfg, "synthetic-g2")
            scan_b = scan_multi_source_generations(conf_b)
            sg_b, cg_b, eg_b, kg_b = scan_b.source_generation, scan_b.config_generation, extractor_generation(conf_b), canonicalizer_generation()

            store.submit(_req_norm("sealed-turnover-t1b-a", sg_a, cg_a, eg_a, kg_a, graph_id="synthetic-g1"))
            old_epoch = store.acquire_singleton("sealed-owner-a", timedelta(seconds=300))
            claim_a = store.claim_next("sealed-owner-a", old_epoch, timedelta(seconds=300))
            assert claim_a is not None and claim_a.graph_id == "synthetic-g1"
            _advance_running(store, claim_a)
            sealed_a = _seal(postgres, cap_dir, config, claim_a, sg_a, cg_a, eg_a, kg_a)
            _publication_phase.initialize(cap_dir, claim_a)
            _install_fence_owner(store, config, postgres)
            real_check = _publication_phase.before_publication

            original_transaction = staged_ingestion.execute_final_transaction
            transactions = []
            refusals = []

            def observe_transaction(*args, **kwargs):
                transactions.append("entered")
                try:
                    return original_transaction(*args, **kwargs)
                except psycopg.errors.RaiseException as error:
                    if "SCALE5 stale publication fence" in str(error):
                        refusals.append(error.sqlstate)
                    raise

            monkeypatch.setattr(staged_ingestion, "execute_final_transaction", observe_transaction)

            checks = []
            new_epoch = None
            claim_b = None
            def observe_check_t1b(directory, attempt):
                nonlocal new_epoch, claim_b
                checks.append("entered")
                assert store.status(claim_a.job_id).state == "running"
                with connect() as connection:
                    assert connection.execute(
                        "SELECT instance_id, fencing_epoch FROM coordinator_instances WHERE singleton_scope = 'control'"
                    ).fetchone() == ("sealed-owner-a", old_epoch)

                real_check(directory, attempt)
                checks.append("passed")
                assert _publication_phase.publication_state(directory, claim_a) == "commit_unknown"

                with connect() as connection:
                    connection.execute("UPDATE coordinator_instances SET expires_at = now() - interval '1 second'")
                    connection.execute("UPDATE graph_leases SET expires_at = now() - interval '1 second'")
                new_epoch = store.acquire_singleton("sealed-owner-b", timedelta(seconds=300))
                assert new_epoch > old_epoch
                assert store.recover_abandoned_attempts("sealed-owner-b", new_epoch, 1) == 1

                store.submit(_req_norm("sealed-turnover-t1b-b", sg_b, cg_b, eg_b, kg_b, graph_id="synthetic-g2"))
                claim_b = store.claim_next("sealed-owner-b", new_epoch, timedelta(seconds=300))
                assert claim_b is not None
                assert claim_b.graph_id == "synthetic-g2"
                assert claim_b.instance_id == "sealed-owner-b"
                assert claim_b.fencing_epoch == new_epoch
                assert claim_b.graph_lease_fencing_epoch > 0
                _advance_running(store, claim_b)

                closed = store.close_unpublished_reconciliation(
                    claim_a, reconciler_instance_id="sealed-owner-b", reconciler_epoch=new_epoch,
                    file_closer=lambda c, proof: _publication_phase.close_unpublished(cap_dir, c, proof=proof),
                )
                assert closed is False
                outcome = store.reconcile_publication(
                    claim_a, reconciler_instance_id="sealed-owner-b", reconciler_epoch=new_epoch,
                    unpublished_proved=closed,
                )
                assert outcome == "reconciliation_required"
                with psycopg.connect(host=postgres.host, port=postgres.port, user=postgres.user,
                                     dbname=graph_db, password=postgres.password) as graph_conn:
                    assert graph_conn.execute(
                        "SELECT singleton_fencing_epoch, coordinator_instance_id FROM graph_publication_authority "
                        "WHERE repository_id = (SELECT id FROM repositories WHERE repository_identity = %s)",
                        (str(configured_repository_identity("synthetic-g1")),),
                    ).fetchone() == (new_epoch, "sealed-owner-b")

            monkeypatch.setattr(_publication_phase, "before_publication", observe_check_t1b)
            rejected = _worker_terminal(monkeypatch, sealed_a)
            assert rejected["status"] == "failed"
            assert checks == ["entered", "passed"]
            assert transactions == ["entered"]
            assert refusals == ["P0001"]
            assert new_epoch is not None
            _assert_no_publication(postgres, graph_db)

            status_a = store.status(claim_a.job_id)
            assert status_a.state == "reconciliation_required"
            assert status_a.publication_state == "commit_unknown"
            with connect() as connection:
                attempt_row = connection.execute(
                    "SELECT is_current, finished_at IS NOT NULL, publication_state FROM job_attempts "
                    "WHERE job_id = %s AND attempt = %s",
                    (claim_a.job_id, claim_a.attempt),
                ).fetchone()
                assert attempt_row == (True, True, "commit_unknown")

            assert claim_b is not None
            cap_b = cap_dir / "replacement"
            cap_b.mkdir(mode=0o700)
            monkeypatch.setattr(_publication_phase, "before_publication", real_check)
            terminal_b = _run_real_refresh_attempt(postgres, cap_b, claim_b, config, sg_b, cg_b, eg_b, kg_b)
            _finish_published(store, claim_b, terminal_b, connect)

            with psycopg.connect(host=postgres.host, port=postgres.port, user=postgres.user,
                                 dbname=graph_db_b, password=postgres.password) as graph_conn_b:
                assert graph_conn_b.execute(
                    "SELECT count(*) FROM runs WHERE publication_job_id = %s AND status = 'complete'",
                    (claim_b.job_id,),
                ).fetchone() == (1,)
                files_b = graph_conn_b.execute("SELECT count(*) FROM files").fetchone()
                assert files_b is not None and files_b[0] > 0

            sealed_a.unlink()
            assert store.stop_singleton("sealed-owner-b", new_epoch)
        finally:
            try:
                with psycopg.connect(host=postgres.host, port=postgres.port, user=postgres.user,
                                     dbname=postgres.database, password=postgres.password, autocommit=True) as admin_conn:
                    admin_conn.execute(f"DROP DATABASE IF EXISTS {graph_db_b} WITH (FORCE)")
            except Exception:
                pass

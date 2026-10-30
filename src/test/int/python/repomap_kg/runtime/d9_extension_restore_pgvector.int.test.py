"""Containerized pgvector integration proof for ADR 0084 D9-B extension_v2 restore."""

from __future__ import annotations

from contextlib import closing
from dataclasses import replace
import hashlib
from pathlib import Path
import shutil
import subprocess
from typing import Any

import pytest

from common_lore_index.coordinator.local_lifecycle import initialize_coordinator_control
from common_lore_index.runtime._backup_observation import observe_database_provenance
from common_lore_index.runtime._backup_provenance import parse_toc_entries
from common_lore_index.runtime._extension_restore_exec import bound_exec_custody
from common_lore_index.runtime._extension_restore_native import run_bounded_ext_command
from common_lore_index.runtime._extension_restore_grants import (
    canonical_grant_statements,
)
from common_lore_index.runtime._extension_restore_toc import (
    build_derived_toc_plan,
)
from common_lore_index.runtime._extension_restore_toc_custody import (
    private_derived_toc_custody,
)
from common_lore_index.runtime.backup import dump_all_databases, dump_database, init_database_from_dump, inspect_backup
from common_lore_index.runtime.backup_commands import planned_pg_restore_command
from common_lore_index.runtime.backup_records import LocalDbBackupError
from common_lore_index.runtime.backup_restore_sets import restore_coordinated_backup
from common_lore_index.runtime.local import build_local_runtime_plan
from common_lore_index.storage import apply_migrations, default_rdbms_root, query_canonical_node_records, run_psql
from common_lore_index.storage.publication_readback import read_latest_publication
from common_lore_index.storage.semantic_candidate_import import build_embedding_import_sql, candidate_schema_sql
from common_lore_index.storage.semantic_candidate_readback import query_semantic_candidates
from common_lore_index.storage.semantic_candidates import CandidatePublication, EmbeddingEntry
from common_lore_index.storage.staged_ingestion import run_staged_portable_refresh
from repomap_test_support.d9_extension_policies import DEFAULT_REPLAY_BOUNDS, adr0077_pgvector_extension_policy, probe_live_container_qualification
from repomap_test_support.d9_extension_restore import (
    clean_template_reference, database_names, engine_container_id, owned_d9_postgres_cluster, seed_adr0077_roles_on_cluster,
)
from repomap_test_support.local_db_backup import connect_real_postgres as _connect
from repomap_test_support.portable_publication_fixtures import _authority, _binding
from repomap_test_support.postgres_harness import require_postgres_binaries
from repomap_test_support.semantic_candidate_fixtures import BINDING, PROFILE, candidate_query
from repomap_test_support.semantic_candidate_publication import candidate_bundle
from repomap_test_support.semantic_candidate_restore import (
    record_optional_schema_state, verify_reader_privilege_refusals, verify_restored_acl_and_principal, verify_writer_privilege_refusals,
)
from repomap_test_support.test_scratch import short_test_directory

REPOSITORY = "repo1:candidate-fixture"
ROOT = "graph:candidate-fixture"
READER = "candidate_fixture_reader"
WRITER = "candidate_fixture_enrichment"
LEGACY = "candidate_fixture_legacy_writer"
BASELINE_ROLES = ("repomap_read_status", "repomap_refresh_publication", "repomap_coordinator_control")
ROWS_SQL = "SELECT coalesce(json_agg(to_jsonb(r) ORDER BY r.rebuild_id), '[]')::text FROM repomap_enrichment.rebuilds r;"
EMBEDDINGS_SQL = "SELECT md5(coalesce(string_agg(e::text, '|' ORDER BY e.rebuild_id, e.canonical_key), '')) FROM repomap_enrichment.embeddings e;"


def _toc_dirs(runner: Any, container: str) -> list[str]:
    res = runner(["docker", "exec", "-i", container, "find", "/tmp", "-maxdepth", "1", "-name", "repomap-ext-toc-*"], capture_output=True, text=True, check=False)
    assert res.returncode == 0, res.stderr
    return sorted(res.stdout.split())


def _publish(postgres: Any, *, revision: int) -> CandidatePublication:
    bundle = candidate_bundle(job_id=f"candidate-publication-{revision}", revision=revision)
    authority = replace(_authority(bundle), singleton_fencing_epoch=7 + revision, graph_lease_fencing_epoch=9 + revision)
    run_staged_portable_refresh(
        postgres.psql_args, bundle, repository_name="candidate-fixture", root_path=ROOT,
        repository_identity=REPOSITORY, authority=authority, portable_binding=_binding(bundle, authority),
    )
    record = read_latest_publication(postgres.psql_args, psql_command=postgres.psql_command)
    assert record is not None
    return CandidatePublication(REPOSITORY, record)


def _execute(postgres: Any, sql: str, *, role: str | None = None) -> None:
    run_psql([postgres.psql_command, *postgres.psql_args, "-qAt", "-v", "ON_ERROR_STOP=1"], input_text=(f'SET ROLE "{role}";\n' if role else "") + sql)


def _read_candidates(postgres: Any, query: Any) -> Any:
    with pytest.MonkeyPatch.context() as env:
        env.setenv("REPOMAP_STORAGE_READBACK_DRIVER", "psql")
        env.setenv("PGOPTIONS", f"-c role={READER} -c default_transaction_read_only=on")
        return query_semantic_candidates(postgres.psql_args, query=query, psql_command=postgres.psql_command)


def _entries() -> tuple[EmbeddingEntry, ...]:
    return tuple(EmbeddingEntry(f"file:src/{n}.py", BINDING, v, "sha256:" + "a" * 64) for n, v in (("a", (1, 0, 0)), ("b", (1, 0, 0)), ("c", (0, 1, 0))))


def _seed_two_publications(handle: Any) -> Any:
    """Publication 1 imported by a legacy writer, publication 2 by the current writer; returns the current query."""
    _execute(handle, "CREATE SCHEMA repomap_vector; CREATE EXTENSION vector WITH SCHEMA repomap_vector VERSION '0.8.7'; COMMENT ON EXTENSION vector IS 'custom vector comment for d9b';")
    _execute(handle, candidate_schema_sql(read_principal=READER, enrichment_principal=LEGACY))
    first = _publish(handle, revision=1)
    legacy_query = replace(candidate_query(), publication=first, rebuild_id="rebuild-fixture-legacy")
    _execute(handle, build_embedding_import_sql(first, PROFILE, _entries(), rebuild_id=legacy_query.rebuild_id, enrichment_principal=LEGACY, public_safe=True), role=LEGACY)
    _execute(handle, "\n".join(canonical_grant_statements(READER, WRITER)) + f'\nREVOKE ALL ON ALL TABLES IN SCHEMA repomap_enrichment FROM "{LEGACY}";')
    second = _publish(handle, revision=2)
    query = replace(candidate_query(), publication=second)
    _execute(handle, build_embedding_import_sql(second, PROFILE, _entries(), rebuild_id=query.rebuild_id, enrichment_principal=WRITER, public_safe=True), role=WRITER)
    return query


@pytest.mark.requires_pgvector
def test_first_proof_unchanged_pgcustom_private_derived_toc_stdin_transport(monkeypatch: pytest.MonkeyPatch) -> None:
    require_postgres_binaries()
    with short_test_directory("d9b-proof-", "home/repomap.rpl.toml") as directory:
        root = Path(directory)
        src_db, dst_db, home = "d9b_src_graph", "d9b_dst_graph", root / "home"
        reference = clean_template_reference(root)
        with owned_d9_postgres_cluster(home, graph_db=src_db) as (identity, postgres, runner):
            monkeypatch.setenv("REPOMAP_PG_PASSWORD", str(postgres.password))
            monkeypatch.setenv("POSTGRES_PASSWORD", str(postgres.password))
            src = postgres.create_database(src_db)
            apply_migrations(default_rdbms_root(), src.psql_args, psql_command=src.psql_command)
            seed_adr0077_roles_on_cluster(lambda sql: _execute(src, sql), reader_role=READER, writer_role=WRITER)
            _execute(src, f'CREATE ROLE "{LEGACY}" LOGIN NOINHERIT;')
            _seed_two_publications(src)
            archive_path = root / "source_graph.pgcustom"
            dump_cmd = ["docker", "exec", "-i", "-e", f"PGPASSWORD={postgres.password}", identity.postgres_container, "/usr/bin/pg_dump",
                        "--host", "127.0.0.1", "--port", "5432", "--username", postgres.user, "--dbname", src_db, "--format=custom", "--no-owner", "--no-privileges"]
            with archive_path.open("wb") as out_f:
                assert runner(dump_cmd, stdout=out_f, stderr=subprocess.PIPE, text=False, check=False).returncode == 0
            archive_sha_before = hashlib.sha256(archive_path.read_bytes()).hexdigest()
            with archive_path.open("rb") as in_f:
                list_res = runner(["docker", "exec", "-i", identity.postgres_container, "/usr/bin/pg_restore", "-l"], stdin=in_f, capture_output=True, text=False, check=False)
            assert list_res.returncode == 0, list_res.stderr
            rt_plan = build_local_runtime_plan(home)
            policy = adr0077_pgvector_extension_policy(owner=postgres.user, reader_role=READER, writer_role=WRITER, container_name=identity.postgres_container, template_baseline_sha256=reference)
            src_obs = observe_database_provenance(rt_plan, src_db, runner, extension_restore_policy=policy)
            toc_plan = build_derived_toc_plan(list_res.stdout, database=src_db, database_catalog=src_obs.database_catalog, expected_toc_sha256=parse_toc_entries(list_res.stdout, database=src_db).toc_sha256)
            assert toc_plan.extension_comments == ("vector",)
            assert {e["reason"] for e in toc_plan.excluded_entries} == {"precreated-extension-schema", "preinstalled-extension"}
            dst = postgres.create_database(dst_db)
            _execute(dst, "CREATE SCHEMA repomap_vector; CREATE EXTENSION vector WITH SCHEMA repomap_vector VERSION '0.8.7';")
            with bound_exec_custody(engine_container_id(identity.postgres_container)) as custody:
                with private_derived_toc_custody(rt_plan, dst_db, toc_plan, runner, invocation_token="first-proof-tok") as toc_file:
                    restore_cmd = planned_pg_restore_command(rt_plan, dst_db, exit_on_error=True, use_list_path=toc_file)
                    run_bounded_ext_command(rt_plan, restore_cmd, runner, field="pg_restore", max_output_bytes=DEFAULT_REPLAY_BOUNDS.max_output_bytes,
                                            timeout_seconds=DEFAULT_REPLAY_BOUNDS.timeout_seconds, stdin_path=archive_path)
            assert custody.unknown == [] and {o.remote for o in custody.outcomes} == {"exited"}, [o.record() for o in custody.outcomes]
            assert _toc_dirs(runner, identity.postgres_container) == []
            assert hashlib.sha256(archive_path.read_bytes()).hexdigest() == archive_sha_before
            with closing(_connect(postgres, dst_db)) as dst_conn, closing(_connect(postgres, src_db)) as src_conn:
                assert dst_conn.execute("SELECT count(*) FROM repomap_enrichment.embeddings").fetchone() == (6,)
                assert dst_conn.execute(ROWS_SQL).fetchone() == src_conn.execute(ROWS_SQL).fetchone()
                assert dst_conn.execute("SELECT obj_description(oid, 'pg_extension') FROM pg_extension WHERE extname = 'vector'").fetchone() == ("custom vector comment for d9b",)


@pytest.mark.requires_pgvector
def test_pgvector_d9b_end_to_end_single_and_coordinated_restore_and_role_reconciliation(monkeypatch: pytest.MonkeyPatch) -> None:
    require_postgres_binaries()
    with short_test_directory("d9b-vec-", "home/repomap.rpl.toml") as directory:
        root = Path(directory)
        graph_db, home = "d9b_vec_graph", root / "home"
        ctrl_db = f"{graph_db}_control"
        reference = clean_template_reference(root)
        with owned_d9_postgres_cluster(home, graph_db=graph_db) as (identity, postgres, runner):
            monkeypatch.setenv("REPOMAP_PG_PASSWORD", str(postgres.password))
            monkeypatch.setenv("POSTGRES_PASSWORD", str(postgres.password))
            policy = adr0077_pgvector_extension_policy(owner=postgres.user, reader_role=READER, writer_role=WRITER, container_name=identity.postgres_container, template_baseline_sha256=reference)
            g = postgres.create_database(graph_db)
            apply_migrations(default_rdbms_root(), g.psql_args, psql_command=g.psql_command)
            seed_adr0077_roles_on_cluster(lambda sql: _execute(g, sql), owner=postgres.user, reader_role=READER, writer_role=WRITER)
            _execute(g, f'CREATE ROLE "{LEGACY}" LOGIN NOINHERIT;')
            query = _seed_two_publications(g)
            expected_state = record_optional_schema_state(g, reader=READER, writer=WRITER)
            assert expected_state["enrichment_principal"] == f"{WRITER},{LEGACY}", "two publications by two principals are retained as data"
            expected_rows, expected_embeddings = g.psql_scalar(ROWS_SQL), g.psql_scalar(EMBEDDINGS_SQL)
            expected_nodes = query_canonical_node_records(g.psql_args, root_path=ROOT, repository_identity=REPOSITORY, psql_command=g.psql_command)
            expected_candidates = _read_candidates(g, query)

            assert dump_database(home, database=graph_db, timestamp="20261021T030000Z", command_runner=runner).restore_supported is False
            vec_dump = dump_database(home, database=graph_db, timestamp="20261021T030100Z", command_runner=runner, extension_restore_policy=policy)
            assert vec_dump.restore_supported is True and vec_dump.restore_blockers == (), f"blockers: {vec_dump.restore_blockers}"
            assert inspect_backup(home, vec_dump.plan.backup_id, command_runner=runner, extension_restore_policy=policy).diagnostics == ()
            archive_file = vec_dump.plan.backup_path / "dump.pgcustom"
            archive_sha_before = hashlib.sha256(archive_file.read_bytes()).hexdigest()

            with closing(_connect(postgres, autocommit=True)) as adm:
                adm.execute(f'DROP DATABASE "{graph_db}" WITH (FORCE)')
                adm.execute(f'DROP ROLE IF EXISTS "{WRITER}";')
                for r in BASELINE_ROLES:
                    adm.execute(f'DROP ROLE IF EXISTS "{r}";')
            before = database_names(postgres)
            with pytest.raises(LocalDbBackupError) as missing_role_exc:
                init_database_from_dump(home, database=graph_db, backup=vec_dump.plan.backup_path, command_runner=runner, extension_restore_policy=policy)
            assert "restore-custom-principal-missing" in [d.code for d in missing_role_exc.value.diagnostics] and database_names(postgres) == before
            seed_adr0077_roles_on_cluster(lambda sql: _execute(postgres, sql), owner=postgres.user, reader_role=READER, writer_role=WRITER)

            def tamper_historical(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[Any]:
                joined = " ".join(cmd)
                if "to_regclass('repomap_enrichment.rebuilds')" in joined and "SELECT CASE WHEN" in joined:
                    with closing(_connect(postgres, graph_db, autocommit=True)) as bad:
                        bad.execute(f"UPDATE repomap_enrichment.rebuilds SET source_generation = 'sg1:tampered' WHERE enrichment_principal = '{LEGACY}';")
                return runner(cmd, **{**kwargs, "check": False})

            with pytest.raises(LocalDbBackupError) as prov_exc:
                init_database_from_dump(home, database=graph_db, backup=vec_dump.plan.backup_path, command_runner=tamper_historical, extension_restore_policy=policy)
            assert "restore-postcheck-provenance-invalid" in [d.code for d in prov_exc.value.diagnostics], "a tampered historical binding refuses"
            assert database_names(postgres) == before, "the refused invocation-owned target is compensated"

            init_res = init_database_from_dump(home, database=graph_db, backup=vec_dump.plan.backup_path, command_runner=runner, extension_restore_policy=policy)
            assert init_res.result == "success" and hashlib.sha256(archive_file.read_bytes()).hexdigest() == archive_sha_before
            assert _toc_dirs(runner, identity.postgres_container) == []
            verify_restored_acl_and_principal(g, expected=expected_state, reader=READER, writer=WRITER)
            verify_reader_privilege_refusals(g, reader=READER)
            verify_writer_privilege_refusals(g, writer=WRITER)
            assert g.psql_scalar(ROWS_SQL) == expected_rows and g.psql_scalar(EMBEDDINGS_SQL) == expected_embeddings, "archived rows preserved exactly"
            assert g.psql_scalar("SELECT has_schema_privilege('repomap_refresh_publication', 'repomap_vector', 'USAGE');") == "f"
            assert query_canonical_node_records(g.psql_args, root_path=ROOT, repository_identity=REPOSITORY, psql_command=g.psql_command) == expected_nodes
            assert _read_candidates(g, query) == expected_candidates, "current accepted publication readback is unchanged"

            initialize_coordinator_control(home)
            coord_dump = dump_all_databases(home, timestamp="20261021T030500Z", command_runner=runner, stable_recovery_point=True, extension_restore_policy=policy)
            assert coord_dump.restore_supported is True
            target_home = root / "target_home"
            with owned_d9_postgres_cluster(target_home, graph_db=graph_db, password=str(postgres.password)) as (target_id, target_pg, target_runner):
                ids = [subprocess.run(["docker", "inspect", "--format", "{{.Id}}", c], capture_output=True, text=True, check=True).stdout.strip() for c in (identity.postgres_container, target_id.postgres_container)]
                assert ids[0] != ids[1], "source and target are separate real containers"
                with closing(_connect(postgres)) as s_adm, closing(_connect(target_pg)) as t_adm:
                    sql = "SELECT system_identifier::text FROM pg_control_system()"
                    assert s_adm.execute(sql).fetchone() != t_adm.execute(sql).fetchone(), "source and target are separate clusters"
                target_backup = target_home / "backups" / "imported" / coord_dump.plan.backup_path.name
                target_backup.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                shutil.copytree(coord_dump.plan.backup_path, target_backup)
                seed_adr0077_roles_on_cluster(lambda sql: _execute(target_pg, sql), owner=target_pg.user, reader_role=READER, writer_role=WRITER)
                coord_res = restore_coordinated_backup(target_home, backup=target_backup, command_runner=target_runner, extension_restore_policy=policy)
                assert coord_res.result == "success" and set(coord_res.databases) == {graph_db, ctrl_db}
                assert _toc_dirs(target_runner, target_id.postgres_container) == []
                tg = replace(target_pg, database=graph_db)
                verify_restored_acl_and_principal(tg, expected=expected_state, reader=READER, writer=WRITER)
                verify_reader_privilege_refusals(tg, reader=READER)
                verify_writer_privilege_refusals(tg, writer=WRITER)
                assert tg.psql_scalar(ROWS_SQL) == expected_rows and _read_candidates(tg, query) == expected_candidates

            core_home = root / "core_target_home"
            core_reference = clean_template_reference(root, profile="core")
            with owned_d9_postgres_cluster(core_home, graph_db=graph_db, password=str(postgres.password), profile="core") as (core_id, core_pg, core_runner):
                with closing(_connect(core_pg)) as c_adm:
                    assert c_adm.execute("SELECT count(*) FROM pg_available_extensions WHERE name = 'vector'").fetchone() == (0,), "real core-only target lacks pgvector"
                seed_adr0077_roles_on_cluster(lambda sql: _execute(core_pg, sql), owner=core_pg.user, reader_role=READER, writer_role=WRITER)
                core_before = database_names(core_pg)
                core_backup = core_home / "backups" / "imported" / vec_dump.plan.backup_path.name
                core_backup.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                shutil.copytree(vec_dump.plan.backup_path, core_backup)
                with pytest.raises(LocalDbBackupError) as core_img_exc:
                    init_database_from_dump(core_home, database=graph_db, backup=core_backup, command_runner=core_runner, extension_restore_policy=policy)
                assert "restore-target-artifact-unqualified" in [d.code for d in core_img_exc.value.diagnostics] and database_names(core_pg) == core_before
                core_qual = probe_live_container_qualification(core_id.postgres_container, user=core_pg.user, template_baseline_sha256=core_reference)
                q = policy.artifact_qualification
                both_qual = replace(
                    q, allowed_server_versions=tuple(sorted({*q.allowed_server_versions, *core_qual.allowed_server_versions})),
                    allowed_os_arch_abis=tuple(sorted({*q.allowed_os_arch_abis, *core_qual.allowed_os_arch_abis})),
                    allowed_engine_image_ids=tuple(sorted({*q.allowed_engine_image_ids, *core_qual.allowed_engine_image_ids})),
                    allowed_client_versions=tuple(sorted({*q.allowed_client_versions, *core_qual.allowed_client_versions})),
                    template_baselines=tuple(sorted({*q.template_baselines, *core_qual.template_baselines})),
                )
                both_policy = replace(policy, artifact_qualification=both_qual)
                # The original backup and manifest are considered against the later qualification; no re-dump.
                original_bytes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(core_backup.iterdir())}
                with pytest.raises(LocalDbBackupError) as no_vec_exc:
                    init_database_from_dump(core_home, database=graph_db, backup=core_backup, command_runner=core_runner, extension_restore_policy=both_policy)
                assert {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(core_backup.iterdir())} == original_bytes
                codes = [d.code for d in no_vec_exc.value.diagnostics]
                assert codes and codes[0] == "restore-extension-version-unavailable", f"same-ABI core target must refuse on real extension absence: {codes}"
                assert database_names(core_pg) == core_before, "core-only target refused before any CREATE DATABASE"

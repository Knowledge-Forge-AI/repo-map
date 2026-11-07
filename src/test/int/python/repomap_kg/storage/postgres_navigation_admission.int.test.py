"""Disposable PostgreSQL W3 metadata parity, admission, and wire-bound tests."""

from __future__ import annotations

from collections.abc import Sequence
from contextlib import contextmanager
import json
from pathlib import Path
from typing import Any, Iterator

import psycopg
import pytest

from common_lore_index.ops.config_local import load_graph_registry_config_home
from common_lore_index.ops.config_records import OpsConfig
from common_lore_index.runtime.database_role_contract import (
    COORDINATOR_CONTROL_PASSWORD_ENV,
    READ_STATUS_PASSWORD_ENV,
    READ_STATUS_ROLE,
    REFRESH_PUBLICATION_PASSWORD_ENV,
    RoleSecrets,
)
from common_lore_index.runtime.database_roles import render_database_role_sql
from common_lore_index.runtime.local import setup_local_runtime
from common_lore_index.runtime.postgres_route import readback_postgres_authority
from common_lore_index.server._navigation_groups import source_scope_admission
from common_lore_index.server.ops import investigation_stores
from common_lore_index.storage import apply_migrations, default_rdbms_root, run_psql
from common_lore_index.storage.navigation_search import NavigationSearchQuery
from common_lore_index.storage.node_locations import NodeLocationsQuery
from common_lore_index.storage.postgres_navigation_search import (
    read_postgres_navigation_search_with_executor,
)
from common_lore_index.storage.postgres_navigation_sql import PG_SCOPED_TRANSPORT_BYTE_CAP
from common_lore_index.storage.postgres_node_locations import (
    read_postgres_node_locations_with_executor,
)
from common_lore_index.storage.psql import last_output_line
from repomap_test_support.portable_publication_fixtures import publish_portable_bundle
from repomap_test_support.postgres_harness import require_postgres_binaries, temporary_postgres
from repomap_test_support.retrieval_evaluation_fixture import (
    MIXED_V1_GRAPH_ID,
    binding_id_for_alias,
    materialize_mixed_v1_working_copy,
    write_mixed_v1_postgres_home,
    write_mixed_v1_sqlite_home,
)
from repomap_test_support.retrieval_evaluation_publication import (
    publish_and_load_postgres_corpus,
    publish_and_load_sqlite_corpus,
)


_CORE_BINDING = binding_id_for_alias("core")
_MARKERS = ("[private-path]", "[private-root]", "[REDACTED]")


@contextmanager
def _published_postgres(root: Path) -> Iterator[tuple[Any, Any, Path]]:
    """Yield a real maintained mixed-v1 publication and disposable database."""
    working = materialize_mixed_v1_working_copy(root / "working-copy")
    with temporary_postgres() as postgres:
        home = write_mixed_v1_postgres_home(
            root / "postgres-home", working, host=postgres.host, port=postgres.port,
            database=postgres.database, user=postgres.user, password=postgres.password,
        )
        state = publish_and_load_postgres_corpus(home, psql_command=postgres.psql_command)
        yield postgres, state, working


def _connection(postgres: Any, *, user: str | None = None, password: str | None = None) -> Any:
    return psycopg.connect(
        host=postgres.host, port=postgres.port, dbname=postgres.database,
        user=user or postgres.user, password=postgres.password if password is None else password,
    )


def _repository_run(postgres: Any, identity: str) -> tuple[int, int, str]:
    with _connection(postgres) as connection:
        repo = connection.execute(
            "SELECT id FROM repositories WHERE repository_identity = %s", (identity,)
        ).fetchone()
        assert repo is not None
        run = connection.execute(
            "SELECT id, snapshot_vector_json FROM runs WHERE repository_id = %s "
            "AND status = 'complete' ORDER BY id DESC LIMIT 1", (repo[0],)
        ).fetchone()
        assert run is not None and isinstance(run[1], str)
        return int(repo[0]), int(run[0]), run[1]


def _metadata(path: str, **extra: Any) -> str:
    value: dict[str, Any] = {
        "binding_id": _CORE_BINDING,
        "binding_alias": "core",
        "snapshot_id": "snap1:w3-public",
        "source_relative_path": path,
    }
    value.update(extra)
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _seed_owned_rows(
    postgres: Any,
    identity: str,
    rows: Sequence[tuple[str, str, str] | tuple[str, str, str, str]],
) -> None:
    """Add owned corruption rows after a real accepted base; never publisher evidence."""
    repository_id, run_id, _ = _repository_run(postgres, identity)
    with _connection(postgres) as connection:
        for ordinal, item in enumerate(rows, start=100_000):
            key, path, evidence_metadata = item[:3]
            node_metadata = item[3] if len(item) == 4 else _metadata(path, doc_path=path)
            node = connection.execute(
                "INSERT INTO canonical_nodes (repository_id, graph_key_version, canonical_key, "
                "kind, display_name, metadata_json, confidence, first_seen_run_id, last_seen_run_id) "
                "VALUES (%s, 1, %s, 'python.module', %s, %s::jsonb, 'extracted', %s, %s) RETURNING id",
                (repository_id, key, key, node_metadata, run_id, run_id),
            ).fetchone()
            assert node is not None
            evidence = connection.execute(
                "INSERT INTO canonical_evidence (repository_id, run_id, graph_key_version, "
                "evidence_key, raw_observation_ordinal, raw_schema_version, raw_kind, raw_source_id, "
                "path, start_line, end_line, extractor, extractor_version, confidence, metadata_json) "
                "VALUES (%s, %s, 1, %s, %s, 1, 'python.module', %s, %s, 1, 2, "
                "'w3-owned-corruption', '1', 'extracted', %s::jsonb) RETURNING id",
                (repository_id, run_id, f"w3-owned:{key}", ordinal, f"w3-owned:{key}", path, evidence_metadata),
            ).fetchone()
            assert evidence is not None
            connection.execute(
                "INSERT INTO canonical_node_evidence "
                "(canonical_node_id, canonical_evidence_id, link_kind) VALUES (%s, %s, 'observed')",
                (node[0], evidence[0]),
            )


def _wire_json(postgres: Any, sql: str, observed: dict[str, Any]) -> dict[str, Any]:
    completed = run_psql(
        [postgres.psql_command, *postgres.psql_args, "-X", "-A", "-t", "-v", "ON_ERROR_STOP=1"],
        input_text=sql,
    )
    serialized = last_output_line(completed.stdout, label="navigation JSON")
    observed["serialized_bytes"] = len(serialized.encode("utf-8"))
    payload = json.loads(serialized)
    assert isinstance(payload, dict)
    observed["payload"] = payload
    return payload


def _navigation_wire(
    postgres: Any,
    query: NavigationSearchQuery,
    identity: str | None,
    observed: dict[str, Any],
    *,
    admits_location: Any = None,
    root_path: str = "graph:mixed-v1",
) -> dict[str, Any]:
    return read_postgres_navigation_search_with_executor(
        query,
        executor=lambda sql: _wire_json(postgres, sql, observed),
        admits_location=admits_location,
        root_path=root_path,
        repository_identity=identity,
    )


def test_real_portable_postgres_navigation_matches_sqlite_and_keeps_safe_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Maintained publications preserve SQLite wire facts and public redaction."""
    require_postgres_binaries()
    working = materialize_mixed_v1_working_copy(tmp_path / "working-copy")
    sqlite_home = write_mixed_v1_sqlite_home(tmp_path / "sqlite-home", working)
    sqlite_state = publish_and_load_sqlite_corpus(sqlite_home)
    sqlite_store = investigation_stores(load_graph_registry_config_home(sqlite_home)).investigation_store()
    with temporary_postgres() as postgres:
        postgres_home = write_mixed_v1_postgres_home(
            tmp_path / "postgres-home", working, host=postgres.host, port=postgres.port,
            database=postgres.database, user=postgres.user, password=postgres.password,
        )
        postgres_state = publish_and_load_postgres_corpus(postgres_home, psql_command=postgres.psql_command)
        monkeypatch.setenv("REPOMAP_PSQL_COMMAND", postgres.psql_command)
        postgres_store = investigation_stores(load_graph_registry_config_home(postgres_home)).investigation_store()
        for query in (
            NavigationSearchQuery(query="RetrievalExecutionPipeline", limit=5),
            NavigationSearchQuery(query="DispatchTable", source_binding_id=_CORE_BINDING, source_path_prefix="pkg", limit=5),
        ):
            sqlite_result = sqlite_store.navigation_search(MIXED_V1_GRAPH_ID, query)
            postgres_result = postgres_store.navigation_search(MIXED_V1_GRAPH_ID, query)
            assert postgres_result["status"] == sqlite_result["status"] == "ok"
            assert {n["canonical_key"] for n in postgres_result["nodes"]} == {
                n["canonical_key"] for n in sqlite_result["nodes"]
            }
            assert all(not any(marker in json.dumps(n, ensure_ascii=False) for marker in _MARKERS)
                       for n in postgres_result["nodes"])
        key = sqlite_store.navigation_search(
            MIXED_V1_GRAPH_ID, NavigationSearchQuery(query="RetrievalExecutionPipeline", limit=5)
        )["nodes"][0]["canonical_key"]
        sqlite_locations = sqlite_store.node_locations(
            MIXED_V1_GRAPH_ID, NodeLocationsQuery(canonical_key=key, evidence_role="direct", limit=5)
        )
        postgres_locations = postgres_store.node_locations(
            MIXED_V1_GRAPH_ID, NodeLocationsQuery(canonical_key=key, evidence_role="direct", limit=5)
        )
        assert postgres_locations["status"] == sqlite_locations["status"] == "ok"
        assert [r["path"] for r in postgres_locations["locations"]] == [
            r["path"] for r in sqlite_locations["locations"]
        ]
        assert sqlite_state.receipt.portable is not None and postgres_state.receipt.portable is not None


def test_read_status_role_can_use_public_navigation_without_lexical_schema_or_owner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The existing read/status authority reads public metadata without lexical access."""
    require_postgres_binaries()
    with _published_postgres(tmp_path) as (postgres, state, working):
        read_home = write_mixed_v1_postgres_home(
            tmp_path / "read-status-home", working, host="postgres", port=5432,
            database=postgres.database, user="repomap",
        )
        config_text = (read_home / "repomap.rpl.toml").read_text(encoding="utf-8")
        config_text = config_text.replace("host_port = 5432", f"host_port = {postgres.port}", 1)
        config_text = config_text.replace(
            '[runtime.postgres]\ndirect_host_port_enabled = true\n'
            f'host_port = {postgres.port}\nbind_host = "postgres"',
            '[runtime.postgres]\ndirect_host_port_enabled = true\n'
            f'host_port = {postgres.port}\nbind_host = "127.0.0.1"',
            1,
        )
        config_text = config_text.replace(
            'user = "repomap"\n', 'user = "repomap"\npassword_env = "REPOMAP_PG_PASSWORD"\n', 1
        )
        (read_home / "repomap.rpl.toml").write_text(config_text, encoding="utf-8")
        setup_local_runtime(read_home)
        env = {
            line.split("=", 1)[0]: line.split("=", 1)[1]
            for line in (read_home / "runtime" / ".env").read_text(encoding="utf-8").splitlines()
            if "=" in line and not line.startswith("#")
        }
        secrets = RoleSecrets(
            read_status=env[READ_STATUS_PASSWORD_ENV],
            refresh_publication=env[REFRESH_PUBLICATION_PASSWORD_ENV],
            coordinator_control=env[COORDINATOR_CONTROL_PASSWORD_ENV],
        )
        with _connection(postgres) as owner:
            owner.execute(render_database_role_sql(
                database=postgres.database, owner_role=postgres.user, database_kind="graph", secrets=secrets
            ))
        config = load_graph_registry_config_home(read_home)
        assert isinstance(config, OpsConfig)
        authority = readback_postgres_authority(config)
        assert authority.projected_read_status is True and authority.postgres.user == READ_STATUS_ROLE
        with psycopg.connect(
            host=authority.postgres.host, port=authority.postgres.port, dbname=postgres.database,
            user=authority.postgres.user, password=authority.password,
        ) as read_connection:
            assert read_connection.execute("SELECT current_user").fetchone() == (READ_STATUS_ROLE,)
            public_count = read_connection.execute("SELECT count(*) FROM public.canonical_nodes").fetchone()
            assert public_count is not None and public_count[0] > 0
        monkeypatch.setenv("REPOMAP_PSQL_COMMAND", postgres.psql_command)
        store = investigation_stores(config).investigation_store()
        result = store.navigation_search(
            MIXED_V1_GRAPH_ID, NavigationSearchQuery(query="RetrievalExecutionPipeline", limit=5)
        )
        assert result["status"] == "ok" and result["nodes"]
        locations = store.node_locations(
            MIXED_V1_GRAPH_ID, NodeLocationsQuery(canonical_key=result["nodes"][0]["canonical_key"], limit=5)
        )
        assert locations["status"] == "ok" and locations["locations"]
        assert state.accepted_reference.repository_id


def test_coordinator_publication_requires_graph_authority_for_navigation() -> None:
    """Coordinator publication is readable only while its graph authority is present."""
    require_postgres_binaries()
    with temporary_postgres() as postgres:
        apply_migrations(default_rdbms_root(), postgres.psql_args, psql_command=postgres.psql_command)
        summary = publish_portable_bundle(
            postgres.psql_args, repository_name="w3-coordinator", root_path="graph:w3-coordinator"
        )
        assert summary.run_id is not None
        with _connection(postgres) as connection:
            repo_id, identity = connection.execute(
                "SELECT id, repository_identity FROM repositories WHERE root_path = 'graph:w3-coordinator'"
            ).fetchone()
            key = connection.execute(
                "SELECT canonical_key FROM canonical_nodes WHERE repository_id = %s ORDER BY canonical_key LIMIT 1",
                (repo_id,),
            ).fetchone()[0]
        query = NavigationSearchQuery(query=key, limit=5)
        observed: dict[str, Any] = {}
        result = _navigation_wire(
            postgres, query, identity, observed, root_path="graph:w3-coordinator"
        )
        assert result["status"] == "ok" and result["nodes"]
        with _connection(postgres) as connection:
            connection.execute("DELETE FROM graph_publication_authority WHERE repository_id = %s", (repo_id,))
        after = _navigation_wire(postgres, query, identity, {}, root_path="graph:w3-coordinator")
        assert after["status"] == "unavailable" and after["reason"] == "publication_absent"


@pytest.mark.parametrize("case", ["metadata", "vector", "aggregate"])
def test_navigation_transport_budget_is_utf8_bounded_for_metadata_vector_and_aggregate(
    tmp_path: Path, case: str,
) -> None:
    """Real accepted data plus owned stress rows must refuse before Python transport/admission."""
    require_postgres_binaries()
    with _published_postgres(tmp_path) as (postgres, state, _working):
        identity = state.accepted_reference.repository_id
        original_vector = _repository_run(postgres, identity)[2]
        if case == "metadata":
            query_text = "w3-byte-metadata"
            rows = [(query_text, "nested/a..b.py", _metadata("nested/a..b.py", oversized="Δ" * 17_000_000))]
        elif case == "vector":
            query_text = "w3-byte-vector"
            rows = [(query_text, "nested/a..b.py", _metadata("nested/a..b.py"))]
            vector = json.dumps([{"binding_id": _CORE_BINDING, "revision": 1, "snapshot_id": "λ" * 17_000_000}], ensure_ascii=False)
            with _connection(postgres) as connection:
                _, run_id, _ = _repository_run(postgres, identity)
                connection.execute("UPDATE runs SET snapshot_vector_json = %s WHERE id = %s", (vector, run_id))
        else:
            query_text = "w3-byte-aggregate"
            rows = [
                (f"{query_text}-a", "nested/a..b.py", _metadata("nested/a..b.py", payload="A" * 16_800_000)),
                (f"{query_text}-b", "nested/b.py", _metadata("nested/b.py", payload="B" * 16_800_000)),
            ]
        _seed_owned_rows(postgres, identity, rows)
        try:
            for scoped in (True, False):
                query = NavigationSearchQuery(
                    query=query_text, limit=5,
                    source_binding_id=_CORE_BINDING if scoped else None,
                    source_path_prefix="nested" if scoped else None,
                )
                observed: dict[str, Any] = {}
                result = _navigation_wire(
                    postgres, query, identity, observed,
                    admits_location=source_scope_admission(query, _MARKERS) if scoped else None,
                )
                payload = observed["payload"]
                assert observed["serialized_bytes"] <= PG_SCOPED_TRANSPORT_BYTE_CAP
                assert payload["transport_overflow"] is True
                assert payload["candidate_nodes"] == [] and payload["direct_evidence"] == []
                assert result["status"] == "incomplete" and result["reason"] == "admission_work_limit"
        finally:
            _, run_id, _ = _repository_run(postgres, identity)
            with _connection(postgres) as connection:
                connection.execute("UPDATE runs SET snapshot_vector_json = %s WHERE id = %s", (original_vector, run_id))


@pytest.mark.parametrize("field", ["metadata", "vector"])
def test_node_locations_transport_budget_bounds_oversized_metadata_and_vector(
    tmp_path: Path, field: str,
) -> None:
    """Node-location transport bounds detoasted UTF-8 metadata/vector before arrays cross the wire."""
    require_postgres_binaries()
    with _published_postgres(tmp_path) as (postgres, state, _working):
        identity = state.accepted_reference.repository_id
        key = "w3-byte-node-location"
        original_vector = _repository_run(postgres, identity)[2]
        oversized_node = _metadata(
            "nested/a..b.md", doc_path="nested/a..b.md",
            oversized="Δ" * 17_000_000 if field == "metadata" else None,
        )
        if field == "vector":
            vector = json.dumps(
                [{"binding_id": _CORE_BINDING, "revision": 1, "snapshot_id": "λ" * 17_000_000}],
                ensure_ascii=False,
            )
            _, run_id, _ = _repository_run(postgres, identity)
            with _connection(postgres) as connection:
                connection.execute("UPDATE runs SET snapshot_vector_json = %s WHERE id = %s", (vector, run_id))
        _seed_owned_rows(postgres, identity, [(key, "nested/a..b.md", _metadata("nested/a..b.md"), oversized_node)])
        query = NodeLocationsQuery(canonical_key=key, evidence_role="direct", limit=5)
        observed: dict[str, Any] = {}
        try:
            result = read_postgres_node_locations_with_executor(
                query,
                executor=lambda sql: _wire_json(postgres, sql, observed),
                repository_identity=identity,
                root_path="graph:mixed-v1",
            )
            payload = observed["payload"]
            assert observed["serialized_bytes"] <= PG_SCOPED_TRANSPORT_BYTE_CAP
            assert payload["transport_overflow"] is True
            assert payload["current_rows"] == [] and payload["historical_rows"] == []
            assert result["status"] == "unavailable" and result["reason"] == "admission_work_limit"
        finally:
            _, run_id, _ = _repository_run(postgres, identity)
            with _connection(postgres) as connection:
                connection.execute("UPDATE runs SET snapshot_vector_json = %s WHERE id = %s", (original_vector, run_id))

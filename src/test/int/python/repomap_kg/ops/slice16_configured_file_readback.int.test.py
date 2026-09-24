"""Configured file filters compose validation, SQL and immutable durable readback."""
import json
from pathlib import Path
import pytest
from repomap_kg.ops.config import load_ops_config
from repomap_kg.ops.graph_files import (
    query_graph_files, GraphFileFilters, GraphFileRecord, OpsRefreshError,
    graph_file_page_to_jsonable, format_graph_file_table,
)
from repomap_kg.storage import apply_migrations, default_rdbms_root, run_psql
from repomap_test_support.postgres_harness import temporary_postgres


@pytest.fixture(scope="module")
def configured_files(tmp_path_factory):
    with temporary_postgres() as postgres:
        apply_migrations(default_rdbms_root(), postgres.psql_args, psql_command=postgres.psql_command)
        _seed(postgres)
        home = tmp_path_factory.mktemp("slice16-readback")
        _write_config(home, postgres=postgres)
        yield load_ops_config(home / "repomap.rpl.toml"), postgres


@pytest.mark.parametrize("filters,expected", [
    (GraphFileFilters(path_prefix="src/", ambiguity="exclude"), ("src/a.py", "src/referenced.py")),
    (GraphFileFilters(generated="only"), ("src/conflict.py",)),
    (GraphFileFilters(executable="only"), ("src/conflict.py",)),
    (GraphFileFilters(generated="exclude", executable="exclude"), ("README.md", "src/a.py")),
    (GraphFileFilters(path_prefix="missing/"), ()),
    (GraphFileFilters(path_prefix="src/", language="python", role="source", ambiguity="exclude"), ("src/a.py",)),
], ids=["prefix-unambiguous", "generated", "executable", "both-false", "missing-prefix", "combined"])
def test_configured_filters_select_exact_nonempty_contrasts(configured_files, filters, expected):
    config, postgres = configured_files
    before = _storage_fingerprint(postgres)
    page = query_graph_files(config, "public", filters=filters, psql_command=postgres.psql_command)
    assert tuple(row.path for row in page.records) == expected
    assert page.has_more is False
    all_rows = query_graph_files(config, "public", filters=GraphFileFilters(), psql_command=postgres.psql_command)
    assert len(all_rows.records) == 4
    assert _storage_fingerprint(postgres) == before


@pytest.mark.parametrize("filters,limit,offset,message", [
    (GraphFileFilters(path="src/a.py", path_prefix="src/"), 10, 0, "cannot combine"),
    (GraphFileFilters(generated="invalid"), 10, 0, "invalid generated"),
    (GraphFileFilters(executable="invalid"), 10, 0, "invalid executable"),
    (GraphFileFilters(observation_state="invalid"), 10, 0, "invalid observation state"),
    (GraphFileFilters(ambiguity="invalid"), 10, 0, "invalid ambiguity"),
    (GraphFileFilters(language=""), 10, 0, "language filter must not be empty"),
    (GraphFileFilters(role=""), 10, 0, "role filter must not be empty"),
    (GraphFileFilters(), 201, 0, "limit must be between"),
    (GraphFileFilters(), 10, -1, "offset must be a non-negative"),
], ids=["combined-path", "generated", "executable", "state", "ambiguity", "language", "role", "limit", "offset"])
def test_configured_filter_refusal_then_readback_preserves_storage(configured_files, filters, limit, offset, message):
    config, postgres = configured_files
    before = _storage_fingerprint(postgres)
    with pytest.raises(OpsRefreshError, match=message):
        query_graph_files(config, "public", filters=filters, limit=limit, offset=offset,
                          psql_command=postgres.psql_command)
    recovered = query_graph_files(config, "public", filters=GraphFileFilters(path="src/a.py"),
                                 psql_command=postgres.psql_command)
    assert tuple(row.path for row in recovered.records) == ("src/a.py",)
    assert _storage_fingerprint(postgres) == before


def _seed(postgres) -> None:
    run_psql(
        [
            postgres.psql_command,
            *postgres.psql_args,
            "-qAt",
            "-v",
            "ON_ERROR_STOP=1",
        ],
        input_text="""
INSERT INTO repositories(name, root_path)
VALUES ('public-repository', '/public/repository');
INSERT INTO runs(repository_id, status, finished_at)
SELECT id, 'complete', CURRENT_TIMESTAMP FROM repositories
WHERE name = 'public-repository';
INSERT INTO canonical_nodes(repository_id, graph_key_version, canonical_key,
kind, display_name, metadata_json, confidence, conflict)
SELECT repositories.id, 1, row.canonical_key, 'file', row.canonical_key,
       row.metadata_json, 'extracted', row.conflict
FROM repositories CROSS JOIN (VALUES
  ('file:README.md',
   '{"language":"markdown","role":"documentation","generated":false,"executable":false}'::jsonb,
   false),
  ('file:src/a.py',
   '{"language":"python","role":"source","generated":false,"executable":false,"content_hash":"private-content-hash"}'::jsonb,
   false),
  ('file:src/conflict.py',
   '{"language":["text","python"],"role":"source","generated":[true,false],"executable":true}'::jsonb,
   true),
  ('file:src/referenced.py', '{}'::jsonb, false)
) AS row(canonical_key, metadata_json, conflict)
WHERE repositories.name = 'public-repository';
INSERT INTO canonical_evidence(repository_id, run_id, graph_key_version,
evidence_key, raw_observation_ordinal, raw_schema_version, raw_kind,
raw_source_id, path, extractor, extractor_version, confidence)
SELECT repositories.id, runs.id, 1, row.evidence_key, row.ordinal, 1,
       row.raw_kind, row.raw_source_id, row.path, 'fixture', '1', 'extracted'
FROM repositories JOIN runs ON runs.repository_id = repositories.id
CROSS JOIN (VALUES
  ('private-evidence-key-readme', 0, 'file', 'private-source-id-readme', 'README.md'),
  ('private-evidence-key-a', 1, 'file', 'private-source-id-a', 'src/a.py'),
  ('private-evidence-key-conflict', 2, 'symbol', 'private-source-id-conflict', 'src/conflict.py'),
  ('private-evidence-key-referenced', 3, 'symbol', 'private-source-id-referenced', 'src/referenced.py')
) AS row(evidence_key, ordinal, raw_kind, raw_source_id, path)
WHERE repositories.name = 'public-repository';
INSERT INTO canonical_node_evidence(
canonical_node_id, canonical_evidence_id, link_kind)
SELECT canonical_nodes.id, canonical_evidence.id, 'observed'
FROM canonical_nodes JOIN canonical_evidence
  ON canonical_evidence.repository_id = canonical_nodes.repository_id
 AND canonical_evidence.path = substring(canonical_nodes.canonical_key FROM 6)
WHERE canonical_nodes.repository_id = (
  SELECT id FROM repositories WHERE name = 'public-repository'
);
""",
    )


def _write_config(home: Path, *, postgres) -> None:
    (home / "repomap.rpl.toml").write_text(
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
password_env = "PUBLIC_SAFE_PASSWORD"
[[graphs]]
id = "public"
name = "Public"
root_path = "/public/repository"
repository_name = "public-repository"
privacy = "public-dev"
enabled = true
mcp_visible = false
extractor_profile = "default"
refresh_policy = "manual"
[server_memory]
enabled = false
path = "./public-server-memory"
mode = "read_only"
''',
        encoding="utf-8",
    )


def _storage_fingerprint(postgres) -> tuple[int, int, int]:
    output = run_psql(
        [postgres.psql_command, *postgres.psql_args, "-qAt"],
        input_text="""
SELECT (SELECT COUNT(*) FROM canonical_nodes),
       (SELECT COUNT(*) FROM canonical_evidence),
       (SELECT COUNT(*) FROM canonical_node_evidence);
""",
    )
    values = tuple(int(value) for value in output.stdout.strip().split("|"))
    assert len(values) == 3
    return values[0], values[1], values[2]


@pytest.mark.parametrize("filters,expected,states", [
    (GraphFileFilters(observation_state="observed"), ("README.md", "src/a.py"), ("observed", "observed")),
    (GraphFileFilters(observation_state="referenced"), ("src/conflict.py", "src/referenced.py"), ("referenced", "referenced")),
    (GraphFileFilters(ambiguity="only"), ("src/conflict.py",), ("referenced",)),
    (GraphFileFilters(language="python", observation_state="referenced"), ("src/conflict.py",), ("referenced",)),
    (GraphFileFilters(role="documentation"), ("README.md",), ("observed",)),
    (GraphFileFilters(role="absent"), (), ()),
], ids=["observed", "referenced", "ambiguity", "language-reference", "documentation", "no-role-match"])
def test_filtered_pagination_preserves_evidence_and_public_projection(configured_files, filters, expected, states):
    config, postgres = configured_files
    records: list[GraphFileRecord] = []
    for offset in range(len(expected) + 1):
        page = query_graph_files(config, "public", filters=filters, limit=1, offset=offset,
                                 psql_command=postgres.psql_command)
        assert tuple(row.path for row in page.records) == expected[offset:offset + 1]
        assert page.has_more is (offset + 1 < len(expected))
        payload = graph_file_page_to_jsonable(page)
        assert payload["pagination"] == {"limit": 1, "offset": offset,
                                         "returned": len(page.records), "has_more": page.has_more}
        rendered = format_graph_file_table(page)
        assert f"returned={len(page.records)}" in rendered
        encoded = json.dumps(payload) + rendered
        for private_field in ("private-content-hash", "private-evidence-key", "private-source-id"):
            assert private_field not in encoded
        records.extend(page.records)
    assert tuple(row.observation_state for row in records) == states
    for row in records:
        assert row.evidence_count == 1
        assert row.file_observation_count == int(row.observation_state == "observed")
        assert row.link_kinds == ("observed",)
        if row.path == "src/conflict.py":
            assert row.languages == ("python", "text")
            assert row.generated_states == (False, True)
            assert row.ambiguous_fields == ("languages", "generated_states")

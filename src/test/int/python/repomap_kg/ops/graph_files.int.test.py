from __future__ import annotations

import json
import tempfile
from pathlib import Path

from repomap_test_support.cli_in_process import run_repo_map_in_process
from repomap_test_support.postgres_harness import (
    require_postgres_binaries,
    temporary_postgres,
)

from repomap_kg.storage import (
    apply_migrations,
    default_rdbms_root,
    run_psql,
)


def test_canonical_graph_files_cli_filters_paginates_and_preserves_storage() -> None:
    require_postgres_binaries()
    with temporary_postgres() as postgres, tempfile.TemporaryDirectory() as tmpdir:
        home = Path(tmpdir) / "repo-map-home"
        home.mkdir()
        apply_migrations(
            default_rdbms_root(),
            postgres.psql_args,
            psql_command=postgres.psql_command,
        )
        _seed(postgres)
        _write_config(home, postgres=postgres)
        before = _storage_fingerprint(postgres)

        first = _run_json(
            home,
            postgres=postgres,
            extra=("--limit", "2"),
        )
        second = _run_json(
            home,
            postgres=postgres,
            extra=("--limit", "2", "--offset", "2"),
        )
        referenced = _run_json(
            home,
            postgres=postgres,
            extra=("--observation-state", "referenced"),
        )
        ambiguous = _run_json(
            home,
            postgres=postgres,
            extra=("--ambiguity", "only"),
        )
        exact = _run_json(
            home,
            postgres=postgres,
            extra=("--path", "src/a.py"),
        )

        assert first["command"] == "graph-files"
        assert first["schema_version"] == 1
        assert first["graph"] == {
            "graph_key_version": 1,
            "id": "public",
            "repository_name": "public-repository",
        }
        assert first["pagination"] == {
            "has_more": True,
            "limit": 2,
            "offset": 0,
            "returned": 2,
        }
        assert [record["canonical_key"] for record in first["files"]] == [
            "file:README.md",
            "file:src/a.py",
        ]
        assert [record["canonical_key"] for record in second["files"]] == [
            "file:src/conflict.py",
            "file:src/referenced.py",
        ]
        assert second["pagination"]["has_more"] is False
        assert {record["observation_state"] for record in referenced["files"]} == {
            "referenced"
        }
        assert len(referenced["files"]) == 2
        assert [record["canonical_key"] for record in ambiguous["files"]] == [
            "file:src/conflict.py"
        ]
        assert ambiguous["files"][0]["ambiguous_fields"] == [
            "languages",
            "generated_states",
        ]
        assert [record["path"] for record in exact["files"]] == ["src/a.py"]
        assert exact["files"][0]["evidence"] == {
            "count": 1,
            "file_observation_count": 1,
            "link_kind_overflow": 0,
            "link_kinds": ["observed"],
        }
        assert first["readback"] == {
            "bounded": True,
            "mode": "canonical",
            "raw_payloads_included": False,
        }

        exit_code, stdout, stderr = run_repo_map_in_process(
            "ops",
            "graph-files",
            "--repo-map-home",
            str(home),
            "--graph",
            "public",
            "--limit",
            "1",
            "--psql-command",
            postgres.psql_command,
        )
        assert exit_code == 0, stderr
        assert "RepoMap canonical graph files" in stdout
        assert "canonical_key" in stdout

        serialized = json.dumps(
            {
                "first": first,
                "second": second,
                "referenced": referenced,
                "ambiguous": ambiguous,
                "exact": exact,
            },
            sort_keys=True,
        )
        for forbidden in (
            "/public/repository",
            "private-database",
            "private-content-hash",
            "private-evidence-key",
            "private-source-id",
            "raw_observation_id",
            "internal_id",
        ):
            assert forbidden not in serialized
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


def _run_json(home: Path, *, postgres, extra: tuple[str, ...]):
    exit_code, stdout, stderr = run_repo_map_in_process(
        "ops",
        "graph-files",
        "--repo-map-home",
        str(home),
        "--graph",
        "public",
        *extra,
        "--psql-command",
        postgres.psql_command,
        "--json",
    )
    assert exit_code == 0, stderr
    return json.loads(stdout)


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

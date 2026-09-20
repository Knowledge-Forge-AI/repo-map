import json
from pathlib import Path
import tempfile

import pytest

from repomap_kg.graph.multi_source import graph_source_binding_id
from repomap_kg.ops.config import OpsConfigError, load_ops_config
from repomap_kg.ops.graph_file_sql import GraphFileFilters
from repomap_kg.ops.graph_files import query_graph_files
from repomap_kg.ops.ingestion.github_api import (
    GitHubApiPolicyError,
    PublicGitHubRestTransport,
    acquire_github_api_source,
    load_github_api_source_config,
)
from repomap_kg.storage import apply_migrations, default_rdbms_root
from repomap_test_support.cli_in_process import run_repo_map_in_process
from repomap_test_support.postgres_harness import (
    require_postgres_binaries,
    temporary_postgres,
)
from repomap_test_support.source_ingestion_integration import (
    IntFakeGitHubOpener,
    github_api_fixture_root,
)


def _binding(
    alias: str, root: Path, *, privacy: str = "public-dev",
    binding_id: str | None = None, binding_alias: str | None = None,
    input_name: str | None = None,
) -> str:
    return f"""
[[graphs.source_bindings]]
schema_version = 1
binding_id = "{binding_id or graph_source_binding_id('fixture-graph', alias)}"
source_definition_id = "src1:{alias}"
alias = "{binding_alias or alias}"
revision = 1
kind = "folder"
root_path = "{root}"
repository_name = "fixture-{alias}"
logical_root = "."
privacy = "{privacy}"
evidence_retention = "metadata-only"
extractor_profile = "default"
resolution_policy = "allow-declared"
role = "entry"
input_name = "{input_name or alias}"
exclude_paths = ["result-*"]
"""


def _config(postgres, *bindings: str) -> str:
    return f"""schema_version = 1

[service]
mode = "local"
mcp_transport = "stdio"
log_level = "info"

[postgres]
host = "{postgres.socket_dir}"
port = {postgres.port}
database = "repomap_test"
user = "{postgres.user}"

[[graphs]]
id = "fixture-graph"
name = "Fixture Graph"
enabled = true
mcp_visible = true
refresh_policy = "manual"
database = "repomap_test"
{''.join(bindings)}

[server_memory]
enabled = false
path = "disabled"
mode = "read_only"
"""


def _legacy_config(postgres, root: Path) -> str:
    return f"""schema_version = 1

[service]
mode = "local"
mcp_transport = "stdio"
log_level = "info"

[postgres]
host = "{postgres.socket_dir}"
port = {postgres.port}
database = "repomap_test"
user = "{postgres.user}"

[[graphs]]
id = "fixture-graph"
name = "Fixture Graph"
root_path = "{root}"
repository_name = "fixture-legacy"
privacy = "public-dev"
enabled = true
mcp_visible = true
extractor_profile = "default"
refresh_policy = "manual"
database = "repomap_test"

[server_memory]
enabled = false
path = "disabled"
mode = "read_only"
"""


def _refresh(config_path: Path, psql_command: str) -> tuple[int, str, str]:
    return run_repo_map_in_process(
        "ops", "refresh-graph", "--config", str(config_path),
        "--graph", "fixture-graph", "--psql-command", psql_command, "--json",
    )


def _counts(postgres) -> tuple[int, ...]:
    return tuple(
        int(postgres.psql_scalar(f"SELECT count(*) FROM {table};"))
        for table in ("runs", "files", "raw_observations", "canonical_nodes", "canonical_edges")
    )


def _latest_generations(postgres) -> tuple[str, str, str, str]:
    columns = (
        "source_generation", "config_generation",
        "extractor_generation", "canonicalizer_generation",
    )
    return tuple(
        postgres.psql_scalar(
            f"SELECT {column} FROM runs ORDER BY id DESC LIMIT 1;"
        )
        for column in columns
    )


def test_multi_source_stages_one_atomic_publication_and_source_qualified_readback(tmp_path):
    require_postgres_binaries()
    entry = tmp_path / "entry"
    composition = tmp_path / "composition"
    for root in (entry, composition):
        (root / "modules").mkdir(parents=True)
        (root / "modules/default.nix").write_text("{ ... }: {}\n", encoding="utf-8")
    (entry / "flake.nix").write_text(
        "{ inputs, ... }: { imports = [ inputs.composition.nixosModules.default ]; }\n",
        encoding="utf-8",
    )
    (composition / "flake.nix").write_text(
        "{ ... }: { nixosModules.default = import ./modules/default.nix; }\n",
        encoding="utf-8",
    )
    config_path = tmp_path / "repomap.toml"

    with temporary_postgres() as postgres:
        apply_migrations(default_rdbms_root(), postgres.psql_args, psql_command=postgres.psql_command)
        config_path.write_text(
            _config(postgres, _binding("entry", entry), _binding("composition", composition)),
            encoding="utf-8",
        )
        exit_code, stdout, stderr = _refresh(config_path, postgres.psql_command)
        first_counts = _counts(postgres)
        first_generations = _latest_generations(postgres)
        config = load_ops_config(config_path)
        page = query_graph_files(
            config, "fixture-graph", filters=GraphFileFilters(),
            psql_command=postgres.psql_command,
        )
        replay_code, replay_stdout, replay_stderr = _refresh(
            config_path, postgres.psql_command
        )
        replay_counts = _counts(postgres)
        replay_generations = _latest_generations(postgres)

        (composition / "flake.nix").unlink()
        (composition / "modules/default.nix").unlink()
        failed_code, failed_stdout, failed_stderr = _refresh(
            config_path, postgres.psql_command
        )
        failed_counts = _counts(postgres)

    assert exit_code == 0, stderr
    assert replay_code == 0, replay_stderr
    assert failed_code == 1
    assert '"result": "success"' in stdout
    assert {record.binding_alias for record in page.records} == {"entry", "composition"}
    assert all(record.snapshot_id and record.candidate_id for record in page.records)
    assert all(value.startswith(prefix) for value, prefix in zip(
        first_generations, ("sg1:", "cg1:", "eg1:", "kg1:"), strict=True
    ))
    assert replay_generations == first_generations
    assert first_counts[1] == replay_counts[1]
    assert first_counts[3:] == replay_counts[3:]
    assert failed_counts == replay_counts
    rendered = stdout + replay_stdout + failed_stdout + failed_stderr
    assert str(entry) not in rendered
    assert str(composition) not in rendered


def test_legacy_one_source_publication_and_readback_qualifies_keys_with_source_relative_path(tmp_path):
    require_postgres_binaries()
    root = tmp_path / "legacy"
    (root / "modules").mkdir(parents=True)
    (root / "modules/default.nix").write_text("{ ... }: {}\n", encoding="utf-8")
    config_path = tmp_path / "repomap.toml"

    with temporary_postgres() as postgres:
        apply_migrations(
            default_rdbms_root(),
            postgres.psql_args,
            psql_command=postgres.psql_command,
        )
        config_path.write_text(_legacy_config(postgres, root), encoding="utf-8")
        exit_code, stdout, stderr = _refresh(config_path, postgres.psql_command)
        page = query_graph_files(
            load_ops_config(config_path),
            "fixture-graph",
            filters=GraphFileFilters(),
            psql_command=postgres.psql_command,
        )

    assert exit_code == 0, stderr
    record = next(item for item in page.records if item.path == "modules/default.nix")
    assert record.canonical_key == "file:root/modules/default.nix"
    assert record.path == "modules/default.nix"
    assert record.binding_alias == "root"
    assert record.binding_id == graph_source_binding_id("fixture-graph", "root")
    assert record.candidate_id is not None and record.candidate_id.startswith("cand1:")
    payload = json.loads(stdout)
    assert payload["config_path"] == str(config_path)
    assert payload["result"] == "success"
    assert len(payload["graphs"]) == 1
    graph_row = payload["graphs"][0]
    assert graph_row["graph_id"] == "fixture-graph"
    assert graph_row["repository_name"] == "fixture-legacy"
    assert graph_row["privacy"] == "public-dev"
    assert graph_row["root_path_display"] == str(root)
    assert graph_row["root_path_expanded"] == str(root)


def test_multi_source_routing_and_config_refusals_prevent_storage_mutation(tmp_path):
    require_postgres_binaries()
    root = tmp_path / "valid_src"
    root.mkdir()
    (root / "sample.py").write_text("print('hello')\n", encoding="utf-8")

    with temporary_postgres() as postgres:
        apply_migrations(
            default_rdbms_root(), postgres.psql_args, psql_command=postgres.psql_command
        )
        baseline = _counts(postgres)

        # 1. Each duplicate dimension reaches its own refusal independently.
        for overrides, code in (
            ({"binding_alias": "first"}, "duplicate-source-binding-alias"),
            ({"binding_id": graph_source_binding_id("fixture-graph", "first")}, "duplicate-source-binding-id"),
            ({"input_name": "first"}, "duplicate-source-binding-input-name"),
        ):
            p1 = tmp_path / f"{code}.toml"
            p1.write_text(_config(postgres, _binding("first", root), _binding("second", root, **overrides)))
            with pytest.raises(OpsConfigError) as exc1:
                load_ops_config(p1)
            assert {d.code for d in exc1.value.diagnostics if d.severity == "error"} == {code}
            assert _refresh(p1, postgres.psql_command)[0] == 1
            assert _counts(postgres) == baseline

        # 2. Conflicting source kinds for same source_definition_id
        b1 = _binding("s1", root).replace(
            'source_definition_id = "src1:s1"', 'source_definition_id = "src1:shared"'
        )
        b2 = (
            _binding("s2", root)
            .replace('source_definition_id = "src1:s2"', 'source_definition_id = "src1:shared"')
            .replace('kind = "folder"', 'kind = "archive"')
        )
        p2 = tmp_path / "kind_conflict.toml"
        p2.write_text(_config(postgres, b1, b2), encoding="utf-8")
        with pytest.raises(OpsConfigError) as exc2:
            load_ops_config(p2)
        assert any(d.code == "source-definition-collision" for d in exc2.value.diagnostics)
        assert _refresh(p2, postgres.psql_command)[0] == 1
        assert _counts(postgres) == baseline

        # 3. Invalid exclude path (with ..)
        bad_exclude = _binding("s3", root).replace(
            'exclude_paths = ["result-*"]', 'exclude_paths = ["../escape"]'
        )
        p3 = tmp_path / "bad_exclude.toml"
        p3.write_text(_config(postgres, bad_exclude), encoding="utf-8")
        with pytest.raises(OpsConfigError) as exc3:
            load_ops_config(p3)
        assert any(d.code == "invalid-source-binding-exclude-path" for d in exc3.value.diagnostics)
        assert _refresh(p3, postgres.psql_command)[0] == 1
        assert _counts(postgres) == baseline

        # 4. Unsupported source binding privacy
        bad_privacy = _binding("s4", root, privacy="unsupported-privacy")
        p4 = tmp_path / "bad_privacy.toml"
        p4.write_text(_config(postgres, bad_privacy), encoding="utf-8")
        with pytest.raises(OpsConfigError) as exc4:
            load_ops_config(p4)
        assert any(d.code == "unsupported-source-binding-privacy" for d in exc4.value.diagnostics)
        assert _refresh(p4, postgres.psql_command)[0] == 1
        assert _counts(postgres) == baseline

        # 5. Coherent recovery: valid configuration loads cleanly and publishes to storage
        recovered_toml = _config(postgres, _binding("recovered", root))
        p5 = tmp_path / "recovered.toml"
        p5.write_text(recovered_toml, encoding="utf-8")
        cfg5 = load_ops_config(p5)
        assert not any(d.severity == "error" for d in cfg5.diagnostics)
        assert _refresh(p5, postgres.psql_command)[0] == 0
        assert _counts(postgres)[0] == baseline[0] + 1


def test_offline_github_api_acquisition_refusals_leave_no_artifacts():
    fixture_dir = github_api_fixture_root() / "public_real_transport_config"
    config_path = fixture_dir / "github-source.toml"
    load_github_api_source_config(config_path)

    with tempfile.TemporaryDirectory() as tmpdir:
        out = Path(tmpdir) / "output"

        # 1. HTTP 404 error from fake opener
        transport_404 = PublicGitHubRestTransport(opener=IntFakeGitHubOpener(
            status=404, headers={"content-type": "application/json"}, body=b'{"message": "Not Found"}'
        ))
        with pytest.raises(GitHubApiPolicyError, match="returned HTTP status 404"):
            acquire_github_api_source(config_path, root_path=out, transport=transport_404)
        assert not out.exists() or not list(out.glob("*"))

        # 2. Redirect (302) from fake opener
        transport_302 = PublicGitHubRestTransport(opener=IntFakeGitHubOpener(
            status=302,
            headers={"content-type": "application/json", "location": "https://api.github.com/other"},
            body=b'{}',
        ))
        with pytest.raises(GitHubApiPolicyError, match="redirects are not followed"):
            acquire_github_api_source(config_path, root_path=out, transport=transport_302)
        assert not out.exists() or not list(out.glob("*"))

        # 3. Rate limit exhausted (x-ratelimit-remaining: 0)
        transport_ratelimit = PublicGitHubRestTransport(opener=IntFakeGitHubOpener(
            status=200, headers={"content-type": "application/json", "x-ratelimit-remaining": "0"}, body=b'{}'
        ))
        with pytest.raises(GitHubApiPolicyError, match="hit GitHub API rate limit"):
            acquire_github_api_source(config_path, root_path=out, transport=transport_ratelimit)
        assert not out.exists() or not list(out.glob("*"))

        # 4. Non-JSON response
        transport_html = PublicGitHubRestTransport(opener=IntFakeGitHubOpener(
            status=200, headers={"content-type": "text/html"}, body=b'<html>Not JSON</html>'
        ))
        with pytest.raises(GitHubApiPolicyError, match="did not return a JSON response"):
            acquire_github_api_source(config_path, root_path=out, transport=transport_html)
        assert not out.exists() or not list(out.glob("*"))

        # A successful acquisition writes artifacts but never publishes a graph.
        transport_ok = PublicGitHubRestTransport(opener=IntFakeGitHubOpener(
            status=200,
            headers={"content-type": "application/json; charset=utf-8", "x-ratelimit-remaining": "50"},
            body=b'{"full_name": "fixture-owner/fixture-repo"}',
        ))
        summary = acquire_github_api_source(config_path, root_path=out, transport=transport_ok)
        assert summary.publication.publication_state == "not_published"
        assert summary.requests == summary.responses == 2
        assert {record.endpoint_name for record in summary.response_records} == {"repository", "issues"}
        manifest = json.loads((summary.output_path / "manifest.json").read_text())
        assert manifest["api_run_id"] == summary.api_run_id
        assert {observation.kind for observation in summary.raw_observations} >= {"github.repository", "config.document"}

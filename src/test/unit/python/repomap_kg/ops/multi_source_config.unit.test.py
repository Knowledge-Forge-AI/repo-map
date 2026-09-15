import json
from pathlib import Path

import pytest

from repomap_kg.graph.multi_source import graph_source_binding_id
from repomap_kg.ops.config import (
    OpsConfigError,
    load_ops_config,
    ops_config_status_to_jsonable,
    ops_graph_registry_status_to_jsonable,
    resolve_ops_config,
)


HEADER = """schema_version = 1

[service]
mode = "local"
mcp_transport = "stdio"
log_level = "info"

[postgres]
host = "127.0.0.1"
port = 5432
database = "repomap"
user = "fixture"

"""

FOOTER = """
[server_memory]
enabled = false
path = "disabled"
mode = "read_only"
"""


def _binding(
    alias: str,
    root: str,
    *,
    privacy: str = "public-dev",
    repository_name: str | None = None,
    extractor_profile: str = "default",
    exclude_paths: tuple[str, ...] = ("result-*",),
    role: str = "source",
    input_name: str | None = None,
) -> str:
    rendered_excludes = ", ".join(json.dumps(path) for path in exclude_paths)
    return f"""
[[graphs.source_bindings]]
schema_version = 1
binding_id = "{graph_source_binding_id('fixture-graph', alias)}"
source_definition_id = "src1:{alias}"
alias = "{alias}"
revision = 1
kind = "git-working-tree"
root_path = "{root}"
repository_name = "{repository_name or f'fixture-{alias}'}"
logical_root = "."
privacy = "{privacy}"
evidence_retention = "inherit"
extractor_profile = "{extractor_profile}"
resolution_policy = "isolated"
role = {json.dumps(role)}
{f'input_name = {json.dumps(input_name)}' if input_name is not None else ''}
exclude_paths = [{rendered_excludes}]
"""


def _explicit_graph(*bindings: str, legacy: str = "") -> str:
    return (
        HEADER
        + f"""[[graphs]]
id = "fixture-graph"
name = "Fixture Graph"
enabled = true
mcp_visible = false
refresh_policy = "manual"
database = "repomap_fixture"
{legacy}
"""
        + "".join(bindings)
        + FOOTER
    )


def _legacy_graph(
    root: str,
    *,
    extractor_profile: str = "default",
    exclude_paths: tuple[str, ...] = ("result-*",),
) -> str:
    rendered_excludes = json.dumps(exclude_paths, ensure_ascii=False)
    return (
        HEADER
        + f"""[[graphs]]
id = "fixture-graph"
name = "Fixture Graph"
root_path = "{root}"
repository_name = "fixture"
privacy = "public-dev"
enabled = true
mcp_visible = false
extractor_profile = {json.dumps(extractor_profile, ensure_ascii=False)}
refresh_policy = "manual"
exclude_paths = {rendered_excludes}
database = "repomap_fixture"
"""
        + FOOTER
    )


def _load(tmp_path: Path, text: str):
    path = tmp_path / "repomap.toml"
    path.write_text(text, encoding="utf-8")
    return load_ops_config(path)


def test_legacy_configuration_projects_one_stable_compatibility_binding(tmp_path):
    first = _load(tmp_path, _legacy_graph("/physical/one"))
    first_binding = first.graphs[0].effective_source_bindings[0]
    second = _load(tmp_path, _legacy_graph("/physical/two"))
    second_binding = second.graphs[0].effective_source_bindings[0]

    assert first.graphs[0].source_binding_mode == "legacy-projection"
    assert len(first.graphs[0].effective_source_bindings) == 1
    assert first_binding.binding_id == second_binding.binding_id
    assert first_binding.root_path_expanded != second_binding.root_path_expanded
    assert str(resolve_ops_config(first).graphs[0].repository_identity) == (
        "repo1:fixture-graph"
    )


def test_explicit_binding_inventory_is_ordered_and_additive(tmp_path):
    root = _binding("root", "/physical/root")
    security = _binding("security", "/physical/security")
    first = _load(tmp_path, _explicit_graph(root))
    root_id = first.graphs[0].effective_source_bindings[0].binding_id

    second = _load(tmp_path, _explicit_graph(security, root))
    bindings = second.graphs[0].effective_source_bindings
    assert [item.binding_id for item in bindings] == sorted(
        item.binding_id for item in bindings
    )
    assert root_id in {item.binding_id for item in bindings}
    assert resolve_ops_config(first).graph("fixture-graph").configuration_identity != (
        resolve_ops_config(second).graph("fixture-graph").configuration_identity
    )


def test_ambiguous_legacy_and_explicit_source_syntax_fails_closed(tmp_path):
    text = _explicit_graph(
        _binding("root", "/physical/root"),
        legacy='root_path = "/legacy/private"\nrepository_name = "legacy"\n',
    )
    with pytest.raises(OpsConfigError) as caught:
        _load(tmp_path, text)
    assert {item.code for item in caught.value.diagnostics} == {
        "ambiguous-graph-source-syntax"
    }
    assert "/legacy/private" not in str(caught.value)


@pytest.mark.parametrize(
    "replacement,code",
    (
        ("schema_version = 2", "unsupported-source-binding-version"),
        ("alias = \"root\"", "duplicate-source-binding-alias"),
    ),
)
def test_unknown_version_and_duplicate_alias_fail_closed(
    tmp_path, replacement: str, code: str
):
    root = _binding("root", "/physical/root")
    if code == "unsupported-source-binding-version":
        text = _explicit_graph(root.replace("schema_version = 1", replacement, 1))
    else:
        duplicate = _binding("security", "/physical/security").replace(
            'alias = "security"', replacement
        )
        text = _explicit_graph(root, duplicate)
    with pytest.raises(OpsConfigError) as caught:
        _load(tmp_path, text)
    assert code in {item.code for item in caught.value.diagnostics}


def test_source_definition_kind_collision_fails_closed(tmp_path):
    root = _binding("root", "/physical/root")
    other = _binding("security", "/physical/security").replace(
        'source_definition_id = "src1:security"',
        'source_definition_id = "src1:root"',
    ).replace('kind = "git-working-tree"', 'kind = "folder"')
    with pytest.raises(OpsConfigError) as caught:
        _load(tmp_path, _explicit_graph(root, other))
    assert "source-definition-collision" in {
        item.code for item in caught.value.diagnostics
    }


def test_private_binding_projection_redacts_source_details(tmp_path):
    private_root = "/private/operator/secret-source"
    config = _load(
        tmp_path,
        _explicit_graph(
            _binding(
                "root", private_root, privacy="private-config",
                role="security", input_name="private-policy",
            )
        ),
    )
    projections = (
        ops_config_status_to_jsonable(config),
        ops_graph_registry_status_to_jsonable(config),
    )
    rendered = json.dumps(projections, sort_keys=True)
    assert private_root not in rendered
    assert "fixture-root" not in rendered
    assert "private-policy" not in rendered
    assert "[private-root]" in rendered


def test_effectively_private_mixed_graph_redacts_every_binding_root(tmp_path):
    public_root = "/public/operator/visible-source"
    private_root = "/private/operator/secret-source"
    config = _load(
        tmp_path,
        _explicit_graph(
            _binding(
                "public", public_root, privacy="public-dev",
                role="public", input_name="public-input",
            ),
            _binding(
                "private", private_root, privacy="private-config",
                role="secret", input_name="private-input",
            ),
        ),
    )
    projections = (
        ops_config_status_to_jsonable(config),
        ops_graph_registry_status_to_jsonable(config),
    )

    for projection in projections:
        graph = projection["graphs"][0]
        assert graph["privacy"] == "private-ops"
        assert [item["root_path"] for item in graph["source_bindings"]] == [
            "[private-root]",
            "[private-root]",
        ]
        assert [
            item["root_path_expanded"] for item in graph["source_bindings"]
        ] == ["[private-root]", "[private-root]"]
        rendered = json.dumps(projection, sort_keys=True)
        assert public_root not in rendered
        assert private_root not in rendered
        assert "fixture-public" not in rendered
        assert "fixture-private" not in rendered


@pytest.mark.parametrize(
    "field,value",
    (
        ("role", ""),
        ("role", "r" * 65),
        ("role", "bad role"),
        ("role", "bad/name"),
        ("role", "bad\nrole"),
        ("role", "BadRole"),
        ("role", "naïve"),
        ("input_name", ""),
        ("input_name", "i" * 65),
        ("input_name", "bad name"),
        ("input_name", "bad.name"),
        ("input_name", "bad/name"),
        ("input_name", "bad\nname"),
        ("input_name", "naïve"),
    ),
)
def test_explicit_role_and_input_name_grammar_rejects_unsafe_values(
    tmp_path: Path, field: str, value: str
):
    binding_text = (
        _binding("root", "/physical/root", role=value)
        if field == "role"
        else _binding("root", "/physical/root", input_name=value)
    )
    text = _explicit_graph(binding_text)
    with pytest.raises(OpsConfigError) as caught:
        _load(tmp_path, text)
    assert any(
        item.code.startswith("invalid-source-binding")
        for item in caught.value.diagnostics
    )
    if value:
        assert all(value not in item.message for item in caught.value.diagnostics)


def test_duplicate_input_name_refuses_configuration(tmp_path):
    text = _explicit_graph(
        _binding("root", "/physical/root", input_name="shared-input"),
        _binding("security", "/physical/security", input_name="shared-input"),
    )
    with pytest.raises(OpsConfigError) as caught:
        _load(tmp_path, text)
    assert "duplicate-source-binding-input-name" in {
        item.code for item in caught.value.diagnostics
    }


def test_alias_fallback_duplicate_input_name_refuses_configuration(tmp_path):
    text = _explicit_graph(
        _binding("shared-input", "/physical/root"),
        _binding("security", "/physical/security", input_name="shared-input"),
    )
    with pytest.raises(OpsConfigError) as caught:
        _load(tmp_path, text)
    assert "duplicate-source-binding-input-name" in {
        item.code for item in caught.value.diagnostics
    }


def test_binding_role_and_input_name_are_explicit_configuration(tmp_path):
    config = _load(
        tmp_path,
        _explicit_graph(
            _binding(
                "composition", "/physical/composition",
                role="composition", input_name="composition",
            )
        ),
    )
    binding = config.graphs[0].effective_source_bindings[0]
    assert binding.role == "composition"
    assert binding.input_name == "composition"


def test_top_level_source_registry_remains_distinct_from_graph_bindings(tmp_path):
    text = _explicit_graph(_binding("root", "/physical/root")) + """

[[sources.feed]]
id = "feed-fixture"
graph_id = "fixture-graph"
url = "https://example.invalid/feed.xml"
enabled = false
"""
    config = _load(tmp_path, text)
    assert len(config.graphs[0].effective_source_bindings) == 1
    assert len(config.sources.feed) == 1

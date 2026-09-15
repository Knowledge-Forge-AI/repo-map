from __future__ import annotations

import json
from pathlib import Path

import pytest

from repomap_kg.graph.multi_source import graph_source_binding_id
from repomap_kg.ops.config import (
    OpsConfigError,
    load_ops_config,
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

def test_hand_authored_binding_derives_binding_id(tmp_path):
    binding_without_id = """
[[graphs.source_bindings]]
schema_version = 1
source_definition_id = "src1:root"
alias = "root"
revision = 1
kind = "git-working-tree"
root_path = "/physical/root"
repository_name = "fixture-root"
logical_root = "."
privacy = "public-dev"
evidence_retention = "inherit"
extractor_profile = "default"
resolution_policy = "isolated"
exclude_paths = ["result-*"]
"""
    config = _load(tmp_path, _explicit_graph(binding_without_id))
    binding = config.graphs[0].effective_source_bindings[0]
    assert binding.binding_id == graph_source_binding_id("fixture-graph", "root")


@pytest.mark.parametrize(
    "extractor_profile,exclude_paths",
    (
        ("Legacy", ("result-*",)),
        ("legacy_profile", ("result-*",)),
        ("legacy profile", ("result-*",)),
        ("legacy-" + "a" * 32, ("result-*",)),
        ("default", ("result-*", "result-*")),
        ("default", ("naive-路径",)),
        ("default", ("x" * 300,)),
        ("default", (".",)),
    ),
)
def test_pre_ms_id1_legacy_domain_loads_and_projects_without_migration(
    tmp_path, extractor_profile: str, exclude_paths: tuple[str, ...]
):
    first = _load(
        tmp_path,
        _legacy_graph(
            "/physical/one",
            extractor_profile=extractor_profile,
            exclude_paths=exclude_paths,
        ),
    )
    first_binding = first.graphs[0].effective_source_bindings[0]
    second = _load(
        tmp_path,
        _legacy_graph(
            "/physical/two",
            extractor_profile=extractor_profile,
            exclude_paths=exclude_paths,
        ),
    )
    second_binding = second.graphs[0].effective_source_bindings[0]

    assert len(first.graphs[0].effective_source_bindings) == 1
    assert first_binding.binding_id == second_binding.binding_id
    assert first_binding.selection_policy_id == second_binding.selection_policy_id
    assert first_binding.extractor_profile == second_binding.extractor_profile
    assert first_binding.root_path_expanded != second_binding.root_path_expanded
    assert resolve_ops_config(first).graph("fixture-graph").configuration_identity
    assert not [item for item in first.diagnostics if item.severity == "error"]


@pytest.mark.parametrize(
    "replacement,code",
    (
        ('extractor_profile = "Legacy Profile"', "invalid-source-binding-identity"),
        (
            f'extractor_profile = "legacy-{"a" * 32}"',
            "invalid-source-binding-identity",
        ),
        (
            'exclude_paths = ["result-*", "result-*"]',
            "duplicate-source-binding-exclude-path",
        ),
        ('exclude_paths = ["naive-路径"]', "invalid-source-binding-selection-policy"),
        (
            f'exclude_paths = ["{"x" * 600}"]',
            "invalid-source-binding-selection-policy",
        ),
        ('exclude_paths = ["."]', "invalid-source-binding-selection-policy"),
    ),
)
def test_explicit_binding_syntax_keeps_strict_identity_validation(
    tmp_path, replacement: str, code: str
):
    binding = _binding("root", "/physical/root")
    if replacement.startswith("extractor_profile"):
        binding = binding.replace('extractor_profile = "default"', replacement)
    else:
        binding = binding.replace('exclude_paths = ["result-*"]', replacement)
    with pytest.raises(OpsConfigError) as caught:
        _load(tmp_path, _explicit_graph(binding))
    assert code in {item.code for item in caught.value.diagnostics}


def test_supplied_binding_id_is_verified(tmp_path):
    binding = _binding("root", "/physical/root").replace(
        graph_source_binding_id("fixture-graph", "root"),
        "bind1:" + "0" * 64,
    )
    with pytest.raises(OpsConfigError) as caught:
        _load(tmp_path, _explicit_graph(binding))
    assert "invalid-source-binding-identity" in {
        item.code for item in caught.value.diagnostics
    }


def test_unknown_source_binding_field_diagnostic_code(tmp_path):
    binding_with_unknown = _binding("root", "/physical/root") + "unknown_extra = true\n"
    config = _load(tmp_path, _explicit_graph(binding_with_unknown))
    assert any(
        item.code == "unknown-graphs-source_bindings-field"
        for item in config.diagnostics
    )


def test_effective_source_bindings_total_on_arbitrary_dataclass():
    from repomap_kg.ops.config_records import OpsGraphConfig

    graph = OpsGraphConfig(
        id="fixture",
        name="fixture",
        root_path="/tmp",
        root_path_expanded="/tmp",
        repository_name="repo",
        privacy="public-dev",
        enabled=True,
        mcp_visible=True,
        extractor_profile="",
        refresh_policy="manual",
        exclude_paths=("",),
    )
    bindings = graph.effective_source_bindings
    assert len(bindings) == 1
    assert bindings[0].selection_policy_id == ""
    assert bindings[0].extractor_profile == ""


def test_legacy_graph_effective_source_bindings_selection_policy_derivation():
    from repomap_kg.graph.multi_source import (
        compatibility_source_selection_policy_id,
        source_selection_policy_id,
    )
    from repomap_kg.ops.config_records import OpsGraphConfig

    strict_graph = OpsGraphConfig(
        id="fixture",
        name="fixture",
        root_path="/tmp",
        root_path_expanded="/tmp",
        repository_name="repo",
        privacy="public-dev",
        enabled=True,
        mcp_visible=True,
        extractor_profile="",
        refresh_policy="manual",
        exclude_paths=("result-*",),
    )
    assert strict_graph.effective_source_bindings[0].selection_policy_id == (
        source_selection_policy_id((), ("result-*",))
    )

    legacy_fallback_graph = OpsGraphConfig(
        id="fixture",
        name="fixture",
        root_path="/tmp",
        root_path_expanded="/tmp",
        repository_name="repo",
        privacy="public-dev",
        enabled=True,
        mcp_visible=True,
        extractor_profile="",
        refresh_policy="manual",
        exclude_paths=("result-*", "result-*"),
    )
    assert legacy_fallback_graph.effective_source_bindings[0].selection_policy_id == (
        compatibility_source_selection_policy_id(("result-*", "result-*"))
    )
    assert (
        legacy_fallback_graph.effective_source_bindings[0].selection_policy_id
        != strict_graph.effective_source_bindings[0].selection_policy_id
    )

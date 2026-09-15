import json

import pytest

from repomap_kg.graph.multi_source import graph_source_binding_id
from repomap_kg.ops.config_graphs import parse_graphs_section


def _binding(
    alias: str,
    root: str,
    *,
    privacy: str,
    repository_name: str,
    extractor_profile: str,
    exclude_path: str,
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "binding_id": graph_source_binding_id("fixture-graph", alias),
        "source_definition_id": f"src1:{alias}",
        "alias": alias,
        "revision": 1,
        "kind": "git-working-tree",
        "root_path": root,
        "repository_name": repository_name,
        "logical_root": ".",
        "privacy": privacy,
        "evidence_retention": "inherit",
        "extractor_profile": extractor_profile,
        "resolution_policy": "isolated",
        "exclude_paths": [exclude_path],
    }


def _graph(*bindings: dict[str, object]):
    graphs, diagnostics = parse_graphs_section(
        [{
            "id": "fixture-graph",
            "name": "Fixture Graph",
            "enabled": True,
            "mcp_visible": False,
            "refresh_policy": "manual",
            "database": "repomap_fixture",
            "source_bindings": list(bindings),
        }]
    )
    assert not [item for item in diagnostics if item.severity == "error"]
    return graphs[0]


@pytest.mark.parametrize(
    "bindings_spec",
    (
        ("a-public", "z-private"),
        ("a-private", "z-public"),
    ),
)
def test_multi_binding_projection_owns_no_binding_source_facts(bindings_spec: tuple[str, str]):
    spec1, spec2 = bindings_spec
    b1_is_pub = "public" in spec1
    b2_is_pub = "public" in spec2
    binding1 = _binding(
        spec1,
        f"/root/{spec1}",
        privacy="public-dev" if b1_is_pub else "private-config",
        repository_name=f"repo-{spec1}",
        extractor_profile=f"profile-{spec1}",
        exclude_path=f"exclude-{spec1}",
    )
    binding2 = _binding(
        spec2,
        f"/root/{spec2}",
        privacy="public-dev" if b2_is_pub else "private-config",
        repository_name=f"repo-{spec2}",
        extractor_profile=f"profile-{spec2}",
        exclude_path=f"exclude-{spec2}",
    )
    graph = _graph(binding1, binding2)
    projection = graph.to_jsonable()

    assert (
        graph.root_path, graph.root_path_expanded, graph.repository_name,
        graph.privacy, graph.extractor_profile, graph.exclude_paths,
    ) == ("", "", "[multi-source]", "private-ops", "", ())
    assert (
        projection["root_path"], projection["root_path_expanded"],
        projection["repository_name"], projection["privacy"],
        projection["extractor_profile"], projection["exclude_paths"],
        projection["exclude_paths_count"],
    ) == (
        "[private-root]", "[private-root]", "[multi-source]", "private-ops",
        "", [], 0,
    )
    graph_only = json.dumps(
        {key: value for key, value in projection.items() if key != "source_bindings"}
    )
    assert not any(
        value in graph_only
        for value in (
            f"/root/{spec1}", f"/root/{spec2}",
            f"repo-{spec1}", f"repo-{spec2}",
            f"profile-{spec1}", f"profile-{spec2}",
            f"exclude-{spec1}", f"exclude-{spec2}",
            "public-dev", "private-config",
        )
    )


def test_multi_binding_inherited_privacy_is_conservatively_graph_private():
    first = _binding(
        "one", "/source/one", privacy="inherit", repository_name="one",
        extractor_profile="one", exclude_path="one-output",
    )
    second = _binding(
        "two", "/source/two", privacy="inherit", repository_name="two",
        extractor_profile="two", exclude_path="two-output",
    )

    graph = _graph(first, second)
    assert graph.privacy == "private-ops"
    projection = graph.to_jsonable()
    assert projection["privacy"] == "private-ops"
    for binding in projection["source_bindings"]:
        assert binding["private"] is True
        assert binding["root_path"] == "[private-root]"
        assert binding["repository_name"] == "[private-source]"
        assert binding["exclude_paths"] == ["[private-path]"]

    full_payload = json.dumps(projection)
    assert "/source/one" not in full_payload
    assert "/source/two" not in full_payload
    assert "one-output" not in full_payload
    assert "two-output" not in full_payload

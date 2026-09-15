import unittest
from collections.abc import Mapping
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from repomap_kg.canonicalization.main import canonicalize_observations
else:
    from repomap_kg.canonicalization import canonicalize_observations

from repomap_kg.graph.go_source_keys import (
    go_source_const_key,
    go_source_function_key,
    go_source_method_key,
    go_source_module_key,
    go_source_package_fallback_key,
    go_source_package_key,
    go_source_type_key,
    go_source_var_key,
)
from repomap_kg.graph.keys import file_key, go_module_key
from repomap_kg.observations.raw import RawObservation


REPOSITORY_SCOPE = "go-family-fixture"


def canonicalize(items):
    return canonicalize_observations(items, repository_scope=REPOSITORY_SCOPE)


def observation(
    kind: str,
    path: str,
    *,
    name: str | None = None,
    metadata: Mapping[str, Any] | None = None,
    start_line: int = 1,
    end_line: int | None = None,
    source_suffix: str | None = None,
) -> RawObservation:
    suffix = source_suffix or f"{kind}:{start_line}:{name or 'unnamed'}"
    return RawObservation(
        kind=kind,
        source_id=f"{path}#{suffix}",
        path=path,
        confidence="extracted",
        extractor="go9-fixture",
        extractor_version="0.1.0",
        start_line=start_line,
        end_line=start_line if end_line is None else end_line,
        name=name,
        metadata=dict(metadata or {}),
    )


def file_observation(path: str, *, role: str = "source") -> RawObservation:
    return observation(
        "file",
        path,
        name=path,
        metadata={"language": "go", "role": role, "generated": False},
    )


def package_observation(
    path: str,
    package_name: str,
    *,
    external_test: bool = False,
    source_suffix: str | None = None,
) -> RawObservation:
    return observation(
        "go.package",
        path,
        name=package_name,
        metadata={
            "package_name": package_name,
            "external_test_package": external_test,
            "test_file": path.endswith("_test.go"),
            "generated": False,
            "vendor": False,
            "start_offset": 0,
            "end_offset": 12,
        },
        source_suffix=source_suffix,
    )


def accounting(result) -> Mapping[str, int]:
    record = next(
        item
        for item in result.diagnostics
        if item.category == "go_canonical_accounting"
    )
    assert isinstance(record.value, Mapping)
    return record.value


def edge_tuples(result) -> set[tuple[str, str, str]]:
    return {
        (edge.source_key, edge.kind, edge.target_key)
        for edge in result.graph.edges
    }


def primary_observations() -> tuple[RawObservation, ...]:
    package_metadata = {
        "package_name": "app",
        "generated": False,
        "vendor": False,
        "test_file": False,
        "start_offset": 20,
        "end_offset": 40,
    }
    type_source_id = "main.go#go.type:60:90:0"
    return (
        file_observation("go.mod", role="config"),
        observation("go.module", "go.mod", name="example.invalid/app"),
        file_observation("main.go"),
        package_observation("main.go", "app"),
        observation(
            "go.type",
            "main.go",
            name="Item",
            metadata={**package_metadata, "exported": True},
            start_line=3,
            source_suffix="go.type:60:90:0",
        ),
        observation(
            "go.struct",
            "main.go",
            name="Item",
            metadata={**package_metadata, "parent_source_id": type_source_id},
            start_line=3,
        ),
        observation(
            "go.type_alias",
            "main.go",
            name="ItemAlias",
            metadata={**package_metadata, "exported": True},
            start_line=4,
        ),
        observation(
            "go.function",
            "main.go",
            name="Run",
            metadata={**package_metadata, "exported": True},
            start_line=5,
        ),
        observation(
            "go.method",
            "main.go",
            name="Validate",
            metadata={
                **package_metadata,
                "receiver_base": "Item",
                "receiver_pointer": True,
                "exported": True,
            },
            start_line=6,
        ),
        observation(
            "go.const",
            "main.go",
            name="DefaultLimit",
            metadata={**package_metadata, "exported": True},
            start_line=7,
        ),
        observation(
            "go.var",
            "main.go",
            name="Current",
            metadata={**package_metadata, "exported": True},
            start_line=8,
        ),
        file_observation("sub/sub.go"),
        package_observation("sub/sub.go", "sub"),
        observation(
            "go.import",
            "main.go",
            name="example.invalid/app/sub",
            metadata=package_metadata,
            start_line=9,
        ),
        observation(
            "go.module_require",
            "go.mod",
            name="example.invalid/dependency",
            metadata={
                "owner_module_path": "example.invalid/app",
                "version": "v1.2.3",
                "indirect": False,
            },
            start_line=10,
        ),
        observation(
            "go.module_replace",
            "go.mod",
            name="example.invalid/old",
            metadata={
                "owner_module_path": "example.invalid/app",
                "old_version": None,
                "replacement_kind": "module",
                "replacement": "example.invalid/replacement",
                "replacement_version": "v1.0.0",
            },
            start_line=11,
        ),
        file_observation("go.work", role="config"),
        observation("go.workspace", "go.work", name="go.work"),
        observation(
            "go.workspace_use",
            "go.work",
            name=".",
            metadata={"owner_workspace_path": "go.work", "resolved_under_root": True},
            start_line=3,
        ),
    )


class GoCanonicalizationTests(unittest.TestCase):
    def test_canonicalizes_declarations_and_only_exact_relationships(self):
        result = canonicalize(primary_observations())
        module = go_module_key("example.invalid/app")
        source_module = go_source_module_key(
            REPOSITORY_SCOPE, ".", "example.invalid/app"
        )
        package = go_source_package_key(source_module, ".", "app")
        subpackage = go_source_package_key(source_module, "sub", "sub")
        item = go_source_type_key(package, "Item")
        method = go_source_method_key(package, "Item", "Validate")
        node_kinds = {node.canonical_key: node.kind for node in result.graph.nodes}

        self.assertTrue(result.ok)
        self.assertEqual(node_kinds[module], "go.module")
        self.assertEqual(node_kinds[source_module], "go.source_module")
        self.assertEqual(node_kinds[package], "go.source_package")
        self.assertEqual(node_kinds[go_source_type_key(package, "ItemAlias")], "go.source_type_alias")
        self.assertEqual(node_kinds[go_source_function_key(package, "Run")], "go.source_function")
        self.assertEqual(node_kinds[method], "go.source_method")
        self.assertEqual(node_kinds[go_source_const_key(package, "DefaultLimit")], "go.source_const")
        self.assertEqual(node_kinds[go_source_var_key(package, "Current")], "go.source_var")

        edges = edge_tuples(result)
        self.assertIn((file_key("go.mod"), "declares", source_module), edges)
        self.assertIn((source_module, "instance_of", module), edges)
        self.assertIn((file_key("main.go"), "declares", package), edges)
        self.assertIn((source_module, "contains", package), edges)
        self.assertIn((package, "declares", item), edges)
        self.assertIn((method, "method_of", item), edges)
        self.assertIn((package, "imports", subpackage), edges)
        self.assertIn(
            (module, "requires_module", go_module_key("example.invalid/dependency")),
            edges,
        )
        self.assertIn(
            (module, "replaces_module", go_module_key("example.invalid/replacement")),
            edges,
        )
        self.assertIn((file_key("go.work"), "workspace_uses", source_module), edges)
        self.assertEqual(accounting(result)["identity_collisions"], 0)
        self.assertFalse(
            any(item.category == "unsupported_raw_observation_kind" for item in result.diagnostics)
        )

    def test_fallback_and_external_test_packages_remain_distinct(self):
        package = package_observation("pkg/item.go", "item")
        test_package = package_observation(
            "pkg/item_test.go",
            "item_test",
            external_test=True,
        )
        function = observation(
            "go.function",
            "pkg/item_test.go",
            name="TestItem",
            metadata={
                "package_name": "item_test",
                "test_file": True,
                "start_offset": 20,
                "end_offset": 50,
            },
            source_suffix="go.function:20:50:0",
        )
        profile = observation(
            "go.test",
            "pkg/item_test.go",
            name="TestItem",
            metadata={
                "package_name": "item_test",
                "test_file": True,
                "start_offset": 20,
                "end_offset": 50,
                "resolution": "syntactic",
            },
            source_suffix="go.test:20:50:0",
        )
        observations = (
            file_observation("pkg/item.go"),
            package,
            file_observation("pkg/item_test.go", role="test"),
            test_package,
            function,
            profile,
        )

        result = canonicalize(observations)
        regular_key = go_source_package_fallback_key(REPOSITORY_SCOPE, "pkg", "item")
        external_key = go_source_package_fallback_key(
            REPOSITORY_SCOPE, "pkg", "item_test"
        )
        function_key = go_source_function_key(external_key, "TestItem")
        nodes = {node.canonical_key: node for node in result.graph.nodes}

        self.assertIn(regular_key, nodes)
        self.assertIn(external_key, nodes)
        self.assertNotEqual(regular_key, external_key)
        self.assertEqual(nodes[external_key].metadata["identity_source"], "repository_relative")
        self.assertEqual(nodes[function_key].metadata["supporting_evidence_count"], 1)
        self.assertFalse(any(edge.kind == "tests" for edge in result.graph.edges))

    def test_unresolved_syntax_stays_evidence_only_and_is_counted(self):
        observations = (
            file_observation("main.go"),
            package_observation("main.go", "main"),
            observation(
                "go.import",
                "main.go",
                name="example.invalid/external",
                metadata={"package_name": "main"},
            ),
            observation(
                "go.reference",
                "main.go",
                name="Run",
                metadata={"package_name": "main", "resolution": "unresolved"},
            ),
            observation(
                "go.call",
                "main.go",
                name="Run",
                metadata={"package_name": "main", "resolution": "syntactic"},
            ),
            observation(
                "go.selector",
                "main.go",
                name="Method",
                metadata={"package_name": "main", "resolution": "syntactic"},
            ),
        )

        result = canonicalize(observations)

        self.assertTrue(result.ok)
        self.assertFalse(
            any(edge.kind in {"imports", "references", "calls", "selects"} for edge in result.graph.edges)
        )
        self.assertEqual(accounting(result)["unresolved_relationships"], 4)
        self.assertEqual(
            sum(1 for item in result.graph.evidence if item.raw_kind.startswith("go.")),
            5,
        )

    def test_node_and_edge_identity_is_stable_under_input_reordering(self):
        observations = primary_observations()
        forward = canonicalize(observations)
        reverse = canonicalize(tuple(reversed(observations)))

        forward_nodes = sorted(
            (node.to_dict() for node in forward.graph.nodes),
            key=lambda item: item["canonical_key"],
        )
        reverse_nodes = sorted(
            (node.to_dict() for node in reverse.graph.nodes),
            key=lambda item: item["canonical_key"],
        )
        forward_edges = sorted(
            (edge.to_dict() for edge in forward.graph.edges),
            key=lambda item: item["edge_key"],
        )
        reverse_edges = sorted(
            (edge.to_dict() for edge in reverse.graph.edges),
            key=lambda item: item["edge_key"],
        )
        self.assertEqual(forward_nodes, reverse_nodes)
        self.assertEqual(forward_edges, reverse_edges)


if __name__ == "__main__":
    unittest.main()

import unittest

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from repomap_kg.canonicalization.main import canonicalize_observations
    from repomap_kg.observations.raw import RawObservation
else:
    from repomap_kg.canonicalization import canonicalize_observations
from repomap_kg.graph.go_source_keys import (
    go_source_module_key,
    go_source_package_key,
)
from repomap_kg.graph.keys import file_key, go_module_key
from repomap_test_support.go_canonicalization import (
    accounting,
    observation,
    package_observation,
)


REPOSITORY_SCOPE = "go-relationship-fixture"


def canonicalize(items, *, scope: str | None = REPOSITORY_SCOPE):
    return canonicalize_observations(items, repository_scope=scope)


def edge_tuples(result) -> set[tuple[str, str, str]]:
    return {
        (edge.source_key, edge.kind, edge.target_key)
        for edge in result.graph.edges
    }


class GoSourceRelationshipTests(unittest.TestCase):
    def test_local_import_resolves_only_within_source_module_instance(self):
        module_path = "example.invalid/shared"
        result = canonicalize(
            (
                observation("go.module", "one/go.mod", name=module_path),
                package_observation("one/main.go", "main"),
                observation(
                    "go.import",
                    "one/main.go",
                    name=f"{module_path}/pkg",
                    metadata={"package_name": "main"},
                ),
                package_observation("one/pkg/pkg.go", "pkg"),
                observation("go.module", "two/go.mod", name=module_path),
                package_observation("two/pkg/pkg.go", "pkg"),
            )
        )
        one_module = go_source_module_key(REPOSITORY_SCOPE, "one", module_path)
        one_main = go_source_package_key(one_module, ".", "main")
        one_package = go_source_package_key(one_module, "pkg", "pkg")

        self.assertIn((one_main, "imports", one_package), edge_tuples(result))
        self.assertEqual(
            [edge for edge in result.graph.edges if edge.kind == "imports"],
            [
                edge
                for edge in result.graph.edges
                if edge.source_key == one_main and edge.target_key == one_package
            ],
        )

    def test_import_does_not_cross_independent_source_instances(self):
        module_path = "example.invalid/shared"
        result = canonicalize(
            (
                observation("go.module", "one/go.mod", name=module_path),
                package_observation("one/main.go", "main"),
                observation(
                    "go.import",
                    "one/main.go",
                    name=f"{module_path}/pkg",
                    metadata={"package_name": "main"},
                ),
                observation("go.module", "two/go.mod", name=module_path),
                package_observation("two/pkg/pkg.go", "pkg"),
            )
        )

        self.assertFalse(any(edge.kind == "imports" for edge in result.graph.edges))
        self.assertEqual(accounting(result)["identity_collisions"], 0)
        self.assertEqual(accounting(result)["unresolved_relationships"], 1)

    def test_unique_local_import_can_target_a_distinct_module_instance(self):
        result = canonicalize(
            (
                observation(
                    "go.module",
                    "app/go.mod",
                    name="example.invalid/app",
                ),
                package_observation("app/main.go", "main"),
                observation(
                    "go.import",
                    "app/main.go",
                    name="example.invalid/tools/pkg",
                    metadata={"package_name": "main"},
                ),
                observation(
                    "go.module",
                    "tools/go.mod",
                    name="example.invalid/tools",
                ),
                package_observation("tools/pkg/pkg.go", "pkg"),
            )
        )
        app_module = go_source_module_key(
            REPOSITORY_SCOPE,
            "app",
            "example.invalid/app",
        )
        tools_module = go_source_module_key(
            REPOSITORY_SCOPE,
            "tools",
            "example.invalid/tools",
        )
        source = go_source_package_key(app_module, ".", "main")
        target = go_source_package_key(tools_module, "pkg", "pkg")

        self.assertIn((source, "imports", target), edge_tuples(result))

    def test_workspace_use_targets_exact_source_module_instance(self):
        module_path = "example.invalid/shared"
        result = canonicalize(
            (
                observation("go.module", "one/go.mod", name=module_path),
                observation("go.module", "two/go.mod", name=module_path),
                observation(
                    "go.workspace_use",
                    "go.work",
                    name="two",
                    metadata={"resolved_under_root": True},
                ),
            )
        )
        target = go_source_module_key(REPOSITORY_SCOPE, "two", module_path)

        self.assertIn(
            (file_key("go.work"), "workspace_uses", target),
            edge_tuples(result),
        )

    def test_semantic_requirement_is_shared_across_source_instances(self):
        module_path = "example.invalid/shared"
        dependency = "example.invalid/dependency"
        observations: list[RawObservation] = []
        for root in ("one", "two"):
            observations.extend(
                (
                    observation("go.module", f"{root}/go.mod", name=module_path),
                    observation(
                        "go.module_require",
                        f"{root}/go.mod",
                        name=dependency,
                        metadata={"owner_module_path": module_path},
                    ),
                )
            )
        result = canonicalize(tuple(observations))
        relationship = (
            go_module_key(module_path),
            "requires_module",
            go_module_key(dependency),
        )

        self.assertIn(relationship, edge_tuples(result))
        edge = next(edge for edge in result.graph.edges if edge.kind == "requires_module")
        self.assertEqual(
            sum(
                1
                for link in result.graph.edge_evidence_links
                if link.edge_key == edge.edge_key
            ),
            2,
        )

    def test_each_module_occurrence_links_source_instance_to_coordinate(self):
        module_path = "example.invalid/shared"
        result = canonicalize(
            tuple(
                observation("go.module", f"{root}/go.mod", name=module_path)
                for root in ("one", "two")
            )
        )
        semantic = go_module_key(module_path)
        instance_edges = [
            edge for edge in result.graph.edges if edge.kind == "instance_of"
        ]

        self.assertEqual(len(instance_edges), 2)
        self.assertEqual({edge.target_key for edge in instance_edges}, {semantic})
        self.assertTrue(
            all(
                any(
                    link.edge_key == edge.edge_key
                    for link in result.graph.edge_evidence_links
                )
                for edge in instance_edges
            )
        )

    def test_missing_or_invalid_repository_scope_fails_closed(self):
        observations = (
            observation("go.module", "go.mod", name="example.invalid/app"),
            package_observation("main.go", "main"),
        )
        for scope in (None, "../private", "/absolute", "has space"):
            with self.subTest(scope=scope):
                result = canonicalize(observations, scope=scope)

                self.assertFalse(result.ok)
                self.assertFalse(
                    any(node.kind.startswith("go.") for node in result.graph.nodes)
                )
                self.assertFalse(result.graph.evidence)
                self.assertIn(
                    "go_repository_scope_invalid",
                    {item.category for item in result.diagnostics},
                )

    def test_source_identity_evidence_is_complete_and_public_safe(self):
        module_path = "example.invalid/app"
        result = canonicalize(
            (
                observation("go.module", "go.mod", name=module_path),
                package_observation("main.go", "main"),
                observation(
                    "go.function",
                    "main.go",
                    name="Run",
                    metadata={
                        "package_name": "main",
                        "source_text": "private body",
                        "resolved_path": "/private/target/main.go",
                    },
                ),
            )
        )
        serialized = result.to_json()
        source_nodes = [
            node
            for node in result.graph.nodes
            if node.metadata.get("identity_format") == "go-source-v2"
        ]

        self.assertTrue(source_nodes)
        self.assertTrue(
            all(
                any(
                    link.canonical_key == node.canonical_key
                    for link in result.graph.node_evidence_links
                )
                for node in source_nodes
            )
        )
        self.assertNotIn("private body", serialized)
        self.assertNotIn("/private/target", serialized)


if __name__ == "__main__":
    unittest.main()

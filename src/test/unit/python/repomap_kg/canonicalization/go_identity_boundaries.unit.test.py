import unittest

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from repomap_kg.canonicalization.main import canonicalize_observations as _canonicalize
else:
    from repomap_kg.canonicalization import canonicalize_observations as _canonicalize
from repomap_kg.graph.go_source_keys import (
    go_source_function_key,
    go_source_module_key,
    go_source_package_fallback_key,
    go_source_package_key,
    go_source_type_key,
)
from repomap_kg.graph.keys import go_module_key
from repomap_test_support.go_canonicalization import (
    accounting,
    file_observation,
    observation,
    package_observation,
)


REPOSITORY_SCOPE = "go-boundary-fixture"


def canonicalize_observations(items):
    return _canonicalize(items, repository_scope=REPOSITORY_SCOPE)


class GoIdentityBoundaryTests(unittest.TestCase):
    def test_duplicate_declarations_merge_but_alias_collision_fails_closed(self):
        duplicates = (
            file_observation("first.go"),
            package_observation("first.go", "sample"),
            observation(
                "go.function",
                "first.go",
                name="Run",
                metadata={"package_name": "sample"},
            ),
            file_observation("second_linux.go"),
            package_observation("second_linux.go", "sample"),
            observation(
                "go.function",
                "second_linux.go",
                name="Run",
                metadata={"package_name": "sample"},
            ),
        )
        duplicate_result = canonicalize_observations(duplicates)
        package = go_source_package_fallback_key(REPOSITORY_SCOPE, ".", "sample")
        function = next(
            node
            for node in duplicate_result.graph.nodes
            if node.canonical_key == go_source_function_key(package, "Run")
        )

        self.assertTrue(duplicate_result.ok)
        self.assertEqual(function.metadata["duplicate_declaration_evidence_count"], 1)
        self.assertGreaterEqual(
            accounting(duplicate_result)["duplicate_declaration_evidence"], 2
        )

        collision_result = canonicalize_observations(
            duplicates[:2]
            + (
                observation(
                    "go.type",
                    "first.go",
                    name="Value",
                    metadata={"package_name": "sample"},
                ),
                observation(
                    "go.type_alias",
                    "first.go",
                    name="Value",
                    metadata={"package_name": "sample"},
                    start_line=2,
                ),
            )
        )

        self.assertFalse(collision_result.ok)
        self.assertEqual(accounting(collision_result)["identity_collisions"], 1)
        self.assertNotIn(
            go_source_type_key(package, "Value"),
            {node.canonical_key for node in collision_result.graph.nodes},
        )

    def test_method_on_alias_has_no_method_ownership_edge(self):
        result = canonicalize_observations(
            (
                file_observation("alias.go"),
                package_observation("alias.go", "sample"),
                observation(
                    "go.type_alias",
                    "alias.go",
                    name="Alias",
                    metadata={"package_name": "sample"},
                ),
                observation(
                    "go.method",
                    "alias.go",
                    name="Run",
                    metadata={"package_name": "sample", "receiver_base": "Alias"},
                    start_line=2,
                ),
            )
        )

        self.assertFalse(result.ok)
        self.assertFalse(any(edge.kind == "method_of" for edge in result.graph.edges))
        self.assertIn(
            "go_method_receiver_alias_unsupported",
            {item.category for item in result.diagnostics},
        )

    def test_module_package_identity_survives_source_file_movement(self):
        def canonical_go_keys(path: str) -> set[str]:
            result = canonicalize_observations(
                (
                    observation("go.module", "go.mod", name="example.invalid/project"),
                    file_observation(path),
                    package_observation(path, "library"),
                    observation(
                        "go.function",
                        path,
                        name="Run",
                        metadata={"package_name": "library"},
                    ),
                )
            )
            return {
                node.canonical_key
                for node in result.graph.nodes
                if node.canonical_key.startswith("go.")
            }

        self.assertEqual(
            canonical_go_keys("library/first.go"),
            canonical_go_keys("library/renamed.go"),
        )

    def test_deepest_nested_module_owns_package_identity(self):
        result = canonicalize_observations(
            (
                observation("go.module", "go.mod", name="example.invalid/root"),
                observation(
                    "go.module",
                    "tools/go.mod",
                    name="example.invalid/tools",
                ),
                file_observation("tools/cmd/main.go"),
                package_observation("tools/cmd/main.go", "main"),
            )
        )

        keys = {node.canonical_key for node in result.graph.nodes}
        self.assertIn(go_module_key("example.invalid/root"), keys)
        self.assertIn(go_module_key("example.invalid/tools"), keys)
        nested_module = go_source_module_key(
            REPOSITORY_SCOPE, "tools", "example.invalid/tools"
        )
        self.assertIn(go_source_package_key(nested_module, "cmd", "main"), keys)

    def test_multiple_module_paths_at_one_root_fail_closed(self):
        result = canonicalize_observations(
            (
                observation(
                    "go.module",
                    "go.mod",
                    name="example.invalid/first",
                    source_suffix="go.module:1:first",
                ),
                observation(
                    "go.module",
                    "go.mod",
                    name="example.invalid/second",
                    source_suffix="go.module:2:second",
                ),
                package_observation("main.go", "main"),
            )
        )

        self.assertFalse(result.ok)
        self.assertFalse(
            any(node.kind in {"go.source_module", "go.source_package"} for node in result.graph.nodes)
        )
        self.assertIn(
            "go_canonical_identity_collision",
            {item.category for item in result.diagnostics},
        )

    def test_one_module_path_at_multiple_roots_owns_independent_packages(self):
        result = canonicalize_observations(
            (
                observation("go.module", "go.mod", name="example.invalid/shared"),
                observation(
                    "go.module",
                    "nested/go.mod",
                    name="example.invalid/shared",
                ),
                package_observation("nested/pkg/pkg.go", "pkg"),
            )
        )

        nested_module = go_source_module_key(
            REPOSITORY_SCOPE, "nested", "example.invalid/shared"
        )
        nested_package = go_source_package_key(nested_module, "pkg", "pkg")
        self.assertTrue(result.ok)
        self.assertIn(
            nested_package,
            {node.canonical_key for node in result.graph.nodes},
        )
        self.assertEqual(accounting(result)["identity_collisions"], 0)

    def test_invalid_module_reference_does_not_inflate_retained_evidence_count(self):
        dependency = "example.invalid/dependency"
        result = canonicalize_observations(
            (
                observation("go.module", "go.mod", name="example.invalid/app"),
                observation(
                    "go.module_require",
                    "go.mod",
                    name=dependency,
                    metadata={"owner_module_path": "/private/project"},
                    start_line=2,
                ),
                observation(
                    "go.module_require",
                    "go.mod",
                    name=dependency,
                    metadata={"owner_module_path": "example.invalid/app"},
                    start_line=3,
                ),
            )
        )
        dependency_key = go_module_key(dependency)
        dependency_node = next(
            node for node in result.graph.nodes if node.canonical_key == dependency_key
        )
        retained_links = [
            link
            for link in result.graph.node_evidence_links
            if link.canonical_key == dependency_key
        ]

        self.assertFalse(result.ok)
        self.assertEqual(dependency_node.metadata["supporting_evidence_count"], 1)
        self.assertEqual(len(retained_links), 1)

    def test_vendor_package_identity_is_explicitly_deferred(self):
        result = canonicalize_observations(
            (
                file_observation("vendor/example.invalid/lib/lib.go"),
                package_observation(
                    "vendor/example.invalid/lib/lib.go",
                    "lib",
                    vendor=True,
                ),
            )
        )

        self.assertTrue(result.ok)
        self.assertFalse(
            any(node.kind == "go.source_package" for node in result.graph.nodes)
        )
        self.assertIn(
            "go_vendor_package_identity_deferred",
            {item.category for item in result.diagnostics},
        )

    def test_vendor_path_is_deferred_even_when_metadata_is_false(self):
        result = canonicalize_observations(
            (
                file_observation("internal/vendor/example.invalid/lib/lib.go"),
                package_observation(
                    "internal/vendor/example.invalid/lib/lib.go",
                    "lib",
                    vendor=False,
                ),
            )
        )

        self.assertTrue(result.ok)
        self.assertFalse(any(node.kind == "go.source_package" for node in result.graph.nodes))
        self.assertIn(
            "go_vendor_package_identity_deferred",
            {item.category for item in result.diagnostics},
        )

    def test_unresolved_workspace_use_does_not_emit_canonical_edge(self):
        result = canonicalize_observations(
            (
                observation("go.module", "tools/go.mod", name="example.invalid/tools"),
                observation(
                    "go.workspace_use",
                    "go.work",
                    name="tools",
                    metadata={"resolved_under_root": False},
                ),
            )
        )

        self.assertTrue(result.ok)
        self.assertFalse(any(edge.kind == "workspace_uses" for edge in result.graph.edges))
        self.assertEqual(accounting(result)["unresolved_relationships"], 1)

    def test_duplicate_source_ids_fail_closed_without_cross_linking_claims(self):
        duplicate_source_id = "go.mod#duplicate"
        result = canonicalize_observations(
            (
                observation(
                    "go.module",
                    "go.mod",
                    name="example.invalid/project",
                    source_id=duplicate_source_id,
                ),
                observation(
                    "go.package",
                    "main.go",
                    name="main",
                    metadata={"package_name": "main"},
                    source_id=duplicate_source_id,
                ),
            )
        )

        self.assertFalse(result.ok)
        self.assertFalse(any(node.kind.startswith("go.") for node in result.graph.nodes))
        self.assertFalse(any(edge.kind == "declares" for edge in result.graph.edges))
        self.assertIn(
            "go_duplicate_source_id",
            {item.category for item in result.diagnostics},
        )

    def test_nested_source_text_metadata_is_removed_from_evidence(self):
        result = canonicalize_observations(
            (
                package_observation("main.go", "main"),
                observation(
                    "go.reference",
                    "main.go",
                    name="Run",
                    metadata={
                        "package_name": "main",
                        "details": {"safe_shape": "identifier", "source_text": "secret"},
                    },
                ),
            )
        )

        serialized = result.to_json()
        self.assertNotIn("source_text", serialized)
        self.assertNotIn("secret", serialized)
        self.assertIn("safe_shape", serialized)

    def test_duplicate_edge_metadata_is_stable_under_input_reordering(self):
        observations = (
            observation("go.module", "go.mod", name="example.invalid/app"),
            package_observation("first.go", "app"),
            package_observation("second.go", "app"),
            package_observation("sub/sub.go", "sub"),
            observation(
                "go.import",
                "first.go",
                name="example.invalid/app/sub",
                metadata={"package_name": "app", "alias": "zeta"},
            ),
            observation(
                "go.import",
                "second.go",
                name="example.invalid/app/sub",
                metadata={"package_name": "app", "alias": "alpha"},
            ),
        )
        forward = canonicalize_observations(observations)
        reverse = canonicalize_observations(tuple(reversed(observations)))
        forward_import = next(edge for edge in forward.graph.edges if edge.kind == "imports")
        reverse_import = next(edge for edge in reverse.graph.edges if edge.kind == "imports")

        self.assertEqual(forward_import.to_dict(), reverse_import.to_dict())
        self.assertEqual(forward_import.metadata["alias"], ["alpha", "zeta"])


if __name__ == "__main__":
    unittest.main()

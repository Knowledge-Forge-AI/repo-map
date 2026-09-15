import unittest

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from repomap_kg.canonicalization.main import canonicalize_observations
    from repomap_kg.observations.raw import RawObservation
else:
    from repomap_kg.canonicalization import canonicalize_observations
from repomap_kg.graph.go_source_keys import (
    go_source_function_key,
    go_source_module_key,
    go_source_package_fallback_key,
    go_source_package_key,
)
from repomap_kg.graph.keys import go_module_key
from repomap_test_support.go_canonicalization import (
    accounting,
    observation,
    package_observation,
)


REPOSITORY_SCOPE = "go-source-fixture"


def canonicalize(items, *, scope: str = REPOSITORY_SCOPE):
    return canonicalize_observations(items, repository_scope=scope)


def node_keys(result) -> set[str]:
    return {node.canonical_key for node in result.graph.nodes}


def source_nodes(result, kind: str):
    return [node for node in result.graph.nodes if node.kind == kind]


class GoSourceIdentityTests(unittest.TestCase):
    def test_one_module_root_emits_semantic_and_source_identity(self):
        module_path = "example.invalid/app"
        result = canonicalize(
            (
                observation("go.module", "go.mod", name=module_path),
                package_observation("main.go", "app"),
                observation(
                    "go.function",
                    "main.go",
                    name="Run",
                    metadata={"package_name": "app"},
                ),
            )
        )
        semantic = go_module_key(module_path)
        source_module = go_source_module_key(REPOSITORY_SCOPE, ".", module_path)
        source_package = go_source_package_key(source_module, ".", "app")
        source_function = go_source_function_key(source_package, "Run")

        self.assertTrue(result.ok)
        self.assertTrue(
            {semantic, source_module, source_package, source_function}.issubset(
                node_keys(result)
            )
        )
        self.assertFalse(
            any(
                key.startswith(("go.package:", "go.function:"))
                for key in node_keys(result)
            )
        )
        self.assertEqual(
            next(node for node in result.graph.nodes if node.canonical_key == semantic)
            .metadata["identity_format"],
            "go-v1",
        )
        self.assertEqual(
            next(
                node
                for node in result.graph.nodes
                if node.canonical_key == source_module
            ).metadata["identity_format"],
            "go-source-v2",
        )

    def test_repeated_module_path_at_independent_roots_is_not_a_collision(self):
        module_path = "example.invalid/shared"
        observations: list[RawObservation] = []
        for root, function_name in (("first", "First"), ("second", "Second")):
            observations.extend(
                (
                    observation("go.module", f"{root}/go.mod", name=module_path),
                    package_observation(f"{root}/main.go", "main"),
                    observation(
                        "go.function",
                        f"{root}/main.go",
                        name=function_name,
                        metadata={"package_name": "main"},
                    ),
                )
            )

        result = canonicalize(tuple(observations))
        semantic = go_module_key(module_path)
        first_module = go_source_module_key(REPOSITORY_SCOPE, "first", module_path)
        second_module = go_source_module_key(REPOSITORY_SCOPE, "second", module_path)
        first_package = go_source_package_key(first_module, ".", "main")
        second_package = go_source_package_key(second_module, ".", "main")

        self.assertTrue(result.ok)
        self.assertEqual(len(source_nodes(result, "go.module")), 1)
        self.assertEqual(len(source_nodes(result, "go.source_module")), 2)
        self.assertEqual(len(source_nodes(result, "go.source_package")), 2)
        self.assertTrue(
            {
                semantic,
                first_module,
                second_module,
                first_package,
                second_package,
                go_source_function_key(first_package, "First"),
                go_source_function_key(second_package, "Second"),
            }.issubset(node_keys(result))
        )
        self.assertEqual(accounting(result)["identity_collisions"], 0)

    def test_same_semantic_module_is_distinct_across_repository_scopes(self):
        module_path = "example.invalid/shared"
        observations = (observation("go.module", "go.mod", name=module_path),)
        first = canonicalize_observations(observations, repository_scope="repo-one")
        second = canonicalize_observations(observations, repository_scope="repo-two")

        self.assertIn(go_module_key(module_path), node_keys(first) & node_keys(second))
        self.assertIn(
            go_source_module_key("repo-one", ".", module_path),
            node_keys(first),
        )
        self.assertIn(
            go_source_module_key("repo-two", ".", module_path),
            node_keys(second),
        )
        self.assertNotEqual(
            node_keys(first) - {go_module_key(module_path)},
            node_keys(second) - {go_module_key(module_path)},
        )

    def test_multiple_module_paths_at_one_root_fail_source_ownership_closed(self):
        result = canonicalize(
            (
                observation("go.module", "go.mod", name="example.invalid/first"),
                observation(
                    "go.module",
                    "go.mod",
                    name="example.invalid/second",
                    start_line=2,
                ),
                package_observation("main.go", "main"),
            )
        )

        self.assertFalse(result.ok)
        self.assertFalse(source_nodes(result, "go.source_module"))
        self.assertFalse(source_nodes(result, "go.source_package"))
        self.assertEqual(accounting(result)["identity_collisions"], 1)

    def test_deepest_nested_module_owns_source_package(self):
        result = canonicalize(
            (
                observation("go.module", "go.mod", name="example.invalid/root"),
                observation(
                    "go.module",
                    "tools/go.mod",
                    name="example.invalid/tools",
                ),
                package_observation("tools/cmd/main.go", "main"),
            )
        )
        nested = go_source_module_key(
            REPOSITORY_SCOPE,
            "tools",
            "example.invalid/tools",
        )

        self.assertIn(
            go_source_package_key(nested, "cmd", "main"),
            node_keys(result),
        )

    def test_overlapping_import_paths_remain_distinct_by_source_module(self):
        module_path = "example.invalid/shared"
        result = canonicalize(
            (
                observation("go.module", "one/go.mod", name=module_path),
                package_observation("one/main.go", "main"),
                observation("go.module", "two/go.mod", name=module_path),
                package_observation("two/main.go", "main"),
            )
        )
        first = go_source_package_key(
            go_source_module_key(REPOSITORY_SCOPE, "one", module_path),
            ".",
            "main",
        )
        second = go_source_package_key(
            go_source_module_key(REPOSITORY_SCOPE, "two", module_path),
            ".",
            "main",
        )

        self.assertNotEqual(first, second)
        self.assertTrue({first, second}.issubset(node_keys(result)))

    def test_external_test_package_is_distinct(self):
        module_path = "example.invalid/app"
        external = observation(
            "go.package",
            "app_external_test.go",
            name="app_test",
            metadata={
                "package_name": "app_test",
                "external_test_package": True,
                "test_file": True,
            },
        )
        result = canonicalize(
            (
                observation("go.module", "go.mod", name=module_path),
                package_observation("app.go", "app"),
                external,
            )
        )
        source_module = go_source_module_key(REPOSITORY_SCOPE, ".", module_path)

        self.assertTrue(
            {
                go_source_package_key(source_module, ".", "app"),
                go_source_package_key(source_module, ".", "app_test"),
            }.issubset(node_keys(result))
        )

    def test_no_module_fallback_is_repository_scoped(self):
        first = canonicalize(
            (package_observation("cmd/main.go", "main"),),
            scope="repo-one",
        )
        second = canonicalize(
            (package_observation("cmd/main.go", "main"),),
            scope="repo-two",
        )

        self.assertIn(
            go_source_package_fallback_key("repo-one", "cmd", "main"),
            node_keys(first),
        )
        self.assertIn(
            go_source_package_fallback_key("repo-two", "cmd", "main"),
            node_keys(second),
        )

    def test_source_file_movement_inside_package_preserves_identity(self):
        def keys_for(path: str) -> set[str]:
            return node_keys(
                canonicalize(
                    (
                        observation(
                            "go.module",
                            "go.mod",
                            name="example.invalid/app",
                        ),
                        package_observation(path, "library"),
                        observation(
                            "go.function",
                            path,
                            name="Run",
                            metadata={"package_name": "library"},
                        ),
                    )
                )
            )

        self.assertEqual(
            keys_for("library/first.go"),
            keys_for("library/renamed.go"),
        )

    def test_repository_relocation_is_irrelevant_but_scope_change_is_distinct(self):
        observations = (
            observation("go.module", "go.mod", name="example.invalid/app"),
            package_observation("main.go", "main"),
        )
        first = canonicalize_observations(observations, repository_scope="stable-repo")
        relocated = canonicalize_observations(
            observations,
            repository_scope="stable-repo",
        )
        renamed = canonicalize_observations(observations, repository_scope="new-repo")

        self.assertEqual(first.to_json(), relocated.to_json())
        self.assertNotEqual(node_keys(first), node_keys(renamed))
        self.assertIn(go_module_key("example.invalid/app"), node_keys(renamed))

    def test_identity_claims_are_stable_under_input_reordering(self):
        observations = (
            observation("go.module", "go.mod", name="example.invalid/app"),
            package_observation("main.go", "main"),
            observation(
                "go.function",
                "main.go",
                name="Run",
                metadata={"package_name": "main"},
            ),
        )
        forward = canonicalize(observations)
        reverse = canonicalize(tuple(reversed(observations)))

        self.assertEqual(
            forward.to_dict()["nodes"],
            reverse.to_dict()["nodes"],
        )
        self.assertEqual(
            forward.to_dict()["edges"],
            reverse.to_dict()["edges"],
        )


if __name__ == "__main__":
    unittest.main()

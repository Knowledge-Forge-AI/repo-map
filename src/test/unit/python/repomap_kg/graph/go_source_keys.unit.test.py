import unittest

from repomap_kg.graph.go_source_keys import (
    go_source_const_key,
    go_source_function_key,
    go_source_method_key,
    go_source_module_key,
    go_source_package_fallback_key,
    go_source_package_key,
    go_source_type_key,
    go_source_var_key,
    validate_go_repository_scope,
)
from repomap_kg.graph.keys import GraphKeyError, go_module_key, parse_key


class GoSourceGraphKeyTests(unittest.TestCase):
    def test_source_keys_round_trip_with_explicit_v2_namespaces(self):
        semantic = go_module_key("example.invalid/shared")
        source_module = go_source_module_key(
            "public-repository",
            "examples/one",
            "example.invalid/shared",
        )
        source_package = go_source_package_key(source_module, ".", "main")
        keys = {
            source_module: (
                "public-repository",
                "examples/one",
                "example.invalid/shared",
            ),
            source_package: (source_module, ".", "main"),
            go_source_type_key(source_package, "Value"): (source_package, "Value"),
            go_source_function_key(source_package, "Run"): (source_package, "Run"),
            go_source_method_key(source_package, "Value", "Apply"): (
                source_package,
                "Value",
                "Apply",
            ),
            go_source_const_key(source_package, "Default"): (
                source_package,
                "Default",
            ),
            go_source_var_key(source_package, "current"): (
                source_package,
                "current",
            ),
        }

        self.assertNotEqual(source_module, semantic)
        for key, expected_segments in keys.items():
            with self.subTest(key=key):
                self.assertEqual(parse_key(key).segments, expected_segments)

    def test_fallback_package_key_is_repository_scoped_and_distinct(self):
        first = go_source_package_fallback_key("repo-one", "cmd", "main")
        second = go_source_package_fallback_key("repo-two", "cmd", "main")

        self.assertNotEqual(first, second)
        self.assertEqual(
            parse_key(first).segments,
            ("repo-one", "cmd", "main"),
        )
        self.assertEqual(
            parse_key(go_source_type_key(first, "Config")).segments,
            (first, "Config"),
        )

    def test_source_module_key_distinguishes_root_and_repository_scope(self):
        first = go_source_module_key("repo-one", "first", "example.invalid/shared")
        second = go_source_module_key("repo-one", "second", "example.invalid/shared")
        third = go_source_module_key("repo-two", "first", "example.invalid/shared")

        self.assertEqual(len({first, second, third}), 3)

    def test_repository_scope_is_bounded_and_public_safe(self):
        self.assertEqual(
            validate_go_repository_scope("repo-map.public_1"),
            "repo-map.public_1",
        )
        invalid = (
            "",
            "-leading",
            "/absolute",
            r"C:\private",
            "contains/slash",
            "contains:colon",
            "contains space",
            "..",
            "x" * 513,
        )

        for scope in invalid:
            with self.subTest(scope=scope):
                with self.assertRaises(GraphKeyError):
                    validate_go_repository_scope(scope)

    def test_source_paths_must_be_normalized_repository_relative_directories(self):
        invalid = (
            "",
            "/absolute",
            r"C:\private",
            "../escape",
            "nested/../escape",
            "./nested",
            "nested//package",
            "nested/",
            "x" * 4097,
        )

        for directory in invalid:
            with self.subTest(directory=directory):
                with self.assertRaises(GraphKeyError):
                    go_source_module_key(
                        "repo-one",
                        directory,
                        "example.invalid/shared",
                    )

    def test_declaration_builders_reject_wrong_or_unbounded_parent_keys(self):
        semantic = go_module_key("example.invalid/shared")
        oversized_parent = f"go.source-package-fallback.v2:repo:{'x' * 4097}:main"

        for parent in (semantic, oversized_parent):
            with self.subTest(parent=parent[:80]):
                with self.assertRaises(GraphKeyError):
                    go_source_type_key(parent, "Value")

        source_module = go_source_module_key(
            "repo-one",
            ".",
            "example.invalid/shared",
        )
        source_package = go_source_package_key(source_module, ".", "main")
        with self.assertRaises(GraphKeyError):
            go_source_method_key(source_package, "x" * 513, "Run")


if __name__ == "__main__":
    unittest.main()

import unittest

from repomap_kg.graph.keys import (
    GraphKeyError,
    go_const_key,
    go_function_key,
    go_method_key,
    go_module_key,
    go_package_key,
    go_type_key,
    go_var_key,
    parse_key,
    validate_key,
)


class GoGraphKeyTests(unittest.TestCase):
    def test_go_keys_round_trip_and_escape_nested_keys(self):
        module = go_module_key("example.invalid/app")
        package = go_package_key("example.invalid/app/internal/task", "task")
        keys = {
            module: ("example.invalid/app",),
            package: ("example.invalid/app/internal/task", "task"),
            go_type_key(package, "Box"): (package, "Box"),
            go_function_key(package, "Run"): (package, "Run"),
            go_method_key(package, "Box", "Transform"): (
                package,
                "Box",
                "Transform",
            ),
            go_const_key(package, "Default:Value"): (package, "Default:Value"),
            go_var_key(package, "current value"): (package, "current value"),
        }

        for key, expected_segments in keys.items():
            with self.subTest(key=key):
                self.assertEqual(parse_key(key).segments, expected_segments)
                self.assertTrue(validate_key(key).valid)

    def test_go_keys_reject_empty_and_unbounded_components(self):
        package = "go.package:example.invalid%2Fapp:app"
        cases = (
            lambda: go_module_key(""),
            lambda: go_module_key("x" * 4097),
            lambda: go_package_key("x" * 4097, "pkg"),
            lambda: go_package_key("example.invalid/app", "x" * 513),
            lambda: go_type_key(package, ""),
            lambda: go_method_key(package, "x" * 513, "Run"),
        )

        for build in cases:
            with self.subTest(build=build):
                with self.assertRaises(GraphKeyError):
                    build()

    def test_go_module_keys_reject_local_or_traversing_paths(self):
        for module_path in (
            "/private/project",
            r"C:\private\project",
            "C:/private/project",
            "./local",
            "../local",
            "example.invalid/../local",
        ):
            with self.subTest(module_path=module_path):
                with self.assertRaises(GraphKeyError):
                    go_module_key(module_path)

    def test_go_package_keys_validate_repo_relative_fallback_identities(self):
        root_package = go_package_key("repo-relative:.", "main")
        nested_package = go_package_key("repo-relative:cmd/tool", "main")

        self.assertEqual(
            parse_key(root_package).segments,
            ("repo-relative:.", "main"),
        )
        self.assertEqual(
            parse_key(nested_package).segments,
            ("repo-relative:cmd/tool", "main"),
        )
        for import_path in (
            "repo-relative:",
            "repo-relative:/private",
            "repo-relative:../outside",
            "repo-relative:cmd//tool",
            "repo-relative:cmd tool",
        ):
            with self.subTest(import_path=import_path):
                with self.assertRaisesRegex(GraphKeyError, "repository-relative"):
                    go_package_key(import_path, "main")

    def test_nested_go_keys_revalidate_handcrafted_package_components(self):
        oversized_package = f"go.package:{'x' * 4097}:pkg"

        with self.assertRaises(GraphKeyError):
            go_type_key(oversized_package, "Value")

        with self.assertRaisesRegex(GraphKeyError, "go.package parent"):
            go_type_key(go_module_key("example.invalid/app"), "Value")


if __name__ == "__main__":
    unittest.main()

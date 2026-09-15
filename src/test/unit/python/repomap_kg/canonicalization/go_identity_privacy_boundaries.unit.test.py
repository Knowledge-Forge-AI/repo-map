import unittest

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from repomap_kg.canonicalization.main import canonicalize_observations as _canonicalize
else:
    from repomap_kg.canonicalization import canonicalize_observations as _canonicalize
from repomap_test_support.go_canonicalization import (
    accounting,
    observation,
    package_observation,
)


def canonicalize_observations(items):
    return _canonicalize(items, repository_scope="go-privacy-fixture")


class GoIdentityPrivacyBoundaryTests(unittest.TestCase):
    def test_absolute_path_is_rejected_without_path_or_evidence_exposure(self):
        result = canonicalize_observations(
            (package_observation("/private/target/main.go", "main"),)
        )

        error = next(item for item in result.diagnostics if item.severity == "error")
        self.assertFalse(result.ok)
        self.assertIsNone(error.path)
        self.assertIsNone(error.raw_source_id)
        self.assertFalse(result.graph.evidence)
        self.assertEqual(accounting(result)["identity_collisions"], 1)

    def test_windows_absolute_and_unc_paths_are_rejected(self):
        for path in (r"C:\private\target\main.go", r"\\server\share\main.go"):
            with self.subTest(path=path):
                result = canonicalize_observations((package_observation(path, "main"),))

                self.assertFalse(result.ok)
                self.assertFalse(result.graph.evidence)
                self.assertFalse(
                    any(node.kind == "go.package" for node in result.graph.nodes)
                )

    def test_nul_and_non_normalized_paths_fail_closed(self):
        for path in ("a/./main.go", "a//main.go", "a\x00b.go"):
            with self.subTest(path=path):
                result = canonicalize_observations(
                    (package_observation(path, "main"),)
                )
                error = next(
                    item for item in result.diagnostics if item.severity == "error"
                )

                self.assertFalse(result.ok)
                self.assertIsNone(error.path)
                self.assertIsNone(error.raw_source_id)
                self.assertFalse(result.graph.evidence)
                self.assertFalse(
                    any(node.kind.startswith("go.") for node in result.graph.nodes)
                )

    def test_local_or_traversing_module_identity_is_rejected(self):
        for module_path in (
            "/private/project",
            r"C:\private\project",
            "./local",
            "../local",
        ):
            with self.subTest(module_path=module_path):
                result = canonicalize_observations(
                    (observation("go.module", "go.mod", name=module_path),)
                )

                self.assertFalse(result.ok)
                self.assertFalse(
                    any(node.kind == "go.module" for node in result.graph.nodes)
                )
                self.assertIn(
                    "go_canonical_identity_invalid",
                    {item.category for item in result.diagnostics},
                )

    def test_unsafe_owner_module_identity_is_not_retained_as_evidence(self):
        result = canonicalize_observations(
            (
                observation(
                    "go.module_require",
                    "go.mod",
                    name="example.invalid/dependency",
                    metadata={"owner_module_path": "/private/project"},
                ),
            )
        )

        self.assertFalse(result.ok)
        self.assertFalse(result.graph.evidence)
        self.assertNotIn("/private/project", result.to_json())


if __name__ == "__main__":
    unittest.main()

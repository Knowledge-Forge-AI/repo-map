"""Unit tests for tools/ci/public_export_policy.py."""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from ci.public_export_policy import (
    check_candidate_identity,
    check_fixture_integrity,
    check_promotion_policy,
    check_retention_independence,
    check_version_consistency,
    check_withheld_paths,
    evaluate_public_export,
)


class TestPublicExportPolicy(unittest.TestCase):
    def test_withheld_paths_clean(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            violations = check_withheld_paths(repo_root)
            self.assertEqual(violations, [])

    def test_withheld_paths_detects_status(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            status_dir = repo_root / "docs/status"
            status_dir.mkdir(parents=True)
            violations = check_withheld_paths(repo_root)
            self.assertTrue(any("docs/status" in v for v in violations))

    def test_withheld_paths_detects_superpowers(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            sp_dir = repo_root / "docs/superpowers"
            sp_dir.mkdir(parents=True)
            violations = check_withheld_paths(repo_root)
            self.assertTrue(any("docs/superpowers" in v for v in violations))

    def test_version_consistency_passes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            pyproject = repo_root / "pyproject.toml"
            pyproject.write_text('[project]\nname = "repomap-kg"\nversion = "0.0.2"\n')

            pkg_dir = repo_root / "src/main/python/repomap_kg"
            pkg_dir.mkdir(parents=True)
            (pkg_dir / "__init__.py").write_text('__version__ = "0.0.2"\n')

            violations = check_version_consistency(repo_root, "0.0.2")
            self.assertEqual(violations, [])

    def test_version_consistency_detects_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            pyproject = repo_root / "pyproject.toml"
            pyproject.write_text('[project]\nname = "repomap-kg"\nversion = "0.1.0"\n')

            pkg_dir = repo_root / "src/main/python/repomap_kg"
            pkg_dir.mkdir(parents=True)
            (pkg_dir / "__init__.py").write_text('__version__ = "0.0.1"\n')

            violations = check_version_consistency(repo_root, "0.0.1")
            self.assertTrue(len(violations) >= 1)
            self.assertTrue(any("0.1.0" in v for v in violations))

    def test_version_consistency_missing_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            violations = check_version_consistency(repo_root, "0.0.1")
            self.assertTrue(len(violations) >= 2)

    def test_promotion_policy_valid(self) -> None:
        payload = {
            "pull_request": {
                "base": {"ref": "main"},
                "head": {
                    "ref": "staging",
                    "repo": {"full_name": "Knowledge-Forge-AI/repo-map"},
                },
            }
        }
        violations = check_promotion_policy(payload, "Knowledge-Forge-AI/repo-map")
        self.assertEqual(violations, [])

    def test_promotion_policy_rejects_non_staging_head(self) -> None:
        payload = {
            "pull_request": {
                "base": {"ref": "main"},
                "head": {
                    "ref": "feature-branch",
                    "repo": {"full_name": "Knowledge-Forge-AI/repo-map"},
                },
            }
        }
        violations = check_promotion_policy(payload, "Knowledge-Forge-AI/repo-map")
        self.assertTrue(any("only 'staging' may promote to 'main'" in v for v in violations))

    def test_promotion_policy_rejects_fork(self) -> None:
        payload = {
            "pull_request": {
                "base": {"ref": "main"},
                "head": {
                    "ref": "staging",
                    "repo": {"full_name": "external-fork/repo-map"},
                },
            }
        }
        violations = check_promotion_policy(payload, "Knowledge-Forge-AI/repo-map")
        self.assertTrue(any("head must come from 'Knowledge-Forge-AI/repo-map'" in v for v in violations))

    def test_promotion_policy_rejects_non_main_base(self) -> None:
        payload = {
            "pull_request": {
                "base": {"ref": "staging"},
                "head": {
                    "ref": "staging",
                    "repo": {"full_name": "Knowledge-Forge-AI/repo-map"},
                },
            }
        }
        violations = check_promotion_policy(payload, "Knowledge-Forge-AI/repo-map")
        self.assertTrue(any("policy applies only to pull requests targeting 'main'" in v for v in violations))

    def test_promotion_policy_invalid_payload(self) -> None:
        violations = check_promotion_policy({}, "Knowledge-Forge-AI/repo-map")
        self.assertEqual(violations, ["event payload has no pull_request object"])

    def test_candidate_identity_empty_is_no_op(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            violations = check_candidate_identity(Path(temp_dir))
            self.assertEqual(violations, [])

    def test_evaluate_public_export_integration(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            pyproject = repo_root / "pyproject.toml"
            pyproject.write_text('[project]\nname = "repomap-kg"\nversion = "0.0.2"\n')

            pkg_dir = repo_root / "src/main/python/repomap_kg"
            pkg_dir.mkdir(parents=True)
            (pkg_dir / "__init__.py").write_text('__version__ = "0.0.2"\n')

            payload = {
                "pull_request": {
                    "base": {"ref": "main"},
                    "head": {
                        "ref": "staging",
                        "repo": {"full_name": "Knowledge-Forge-AI/repo-map"},
                    },
                }
            }

            violations = evaluate_public_export(
                repo_root,
                payload=payload,
                repository="Knowledge-Forge-AI/repo-map",
                expected_version="0.0.2",
            )
            self.assertEqual(violations, [])

    def test_retention_independence_detects_missing_historical_manifests(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            tools_ci = repo_root / "tools/ci"
            tools_ci.mkdir(parents=True)
            violations = check_retention_independence(repo_root)
            self.assertTrue(
                any("historical ownership manifests file is missing" in v for v in violations)
            )

    def test_retention_independence_passes_with_manifests(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            tools_ci = repo_root / "tools/ci"
            tools_ci.mkdir(parents=True)
            (tools_ci / "historical_ownership_manifests.json").write_text("{}")
            violations = check_retention_independence(repo_root)
            self.assertEqual(violations, [])

    def test_fixture_integrity_passes_on_repo(self) -> None:
        repo_root = Path(__file__).resolve().parents[6]
        violations = check_fixture_integrity(repo_root)
        self.assertEqual(violations, [])

    def test_fixture_integrity_detects_missing_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            tools_ci = repo_root / "tools/ci"
            tools_ci.mkdir(parents=True)
            violations = check_fixture_integrity(repo_root)
            self.assertTrue(any("public fixture manifest missing" in v for v in violations))

    def test_fixture_integrity_detects_missing_fixture(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            tools_ci = repo_root / "tools/ci"
            tools_ci.mkdir(parents=True)
            manifest = {
                "schema": "repomap-public-fixture-manifest-v1",
                "fixtures": [
                    {
                        "path": "src/test/fixtures/missing/file.js",
                        "sha256": "0" * 64,
                    }
                ],
            }
            import json
            (tools_ci / "public_fixture_manifest.json").write_text(json.dumps(manifest))
            violations = check_fixture_integrity(repo_root)
            self.assertTrue(any("required public fixture is missing" in v for v in violations))

    def test_fixture_integrity_detects_hash_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            tools_ci = repo_root / "tools/ci"
            tools_ci.mkdir(parents=True)
            fixture = repo_root / "src/test/fixtures/corrupt/file.js"
            fixture.parent.mkdir(parents=True)
            fixture.write_text("hello world")
            manifest = {
                "schema": "repomap-public-fixture-manifest-v1",
                "fixtures": [
                    {
                        "path": "src/test/fixtures/corrupt/file.js",
                        "sha256": "0" * 64,
                    }
                ],
            }
            import json
            (tools_ci / "public_fixture_manifest.json").write_text(json.dumps(manifest))
            violations = check_fixture_integrity(repo_root)
            self.assertTrue(any("content hash mismatch" in v for v in violations))

    def test_fixture_integrity_rejects_withheld_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            tools_ci = repo_root / "tools/ci"
            tools_ci.mkdir(parents=True)
            manifest = {
                "schema": "repomap-public-fixture-manifest-v1",
                "fixtures": [
                    {
                        "path": "docs/status/forbidden.md",
                        "sha256": "0" * 64,
                    }
                ],
            }
            import json
            (tools_ci / "public_fixture_manifest.json").write_text(json.dumps(manifest))
            violations = check_fixture_integrity(repo_root)
            self.assertTrue(any("references withheld path" in v for v in violations))

    def test_fixture_integrity_detects_mode_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            tools_ci = repo_root / "tools/ci"
            tools_ci.mkdir(parents=True)
            fixture = repo_root / "src/test/fixtures/file.js"
            fixture.parent.mkdir(parents=True)
            fixture.write_text("hello world")
            manifest = {
                "schema": "repomap-public-fixture-manifest-v1",
                "fixtures": [
                    {
                        "path": "src/test/fixtures/file.js",
                        "mode": "100755",
                    }
                ],
            }
            import json
            (tools_ci / "public_fixture_manifest.json").write_text(json.dumps(manifest))
            violations = check_fixture_integrity(repo_root)
            self.assertTrue(any("mode mismatch" in v for v in violations))



if __name__ == "__main__":
    unittest.main()

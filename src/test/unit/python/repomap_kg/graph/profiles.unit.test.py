import tempfile
import unittest
from pathlib import Path

from repomap_kg.graph.discovery import classify_path, discover_repository
from repomap_kg.graph.profiles import ProfileValidationError, ProjectProfile, load_profile


class ProfileUnitTests(unittest.TestCase):
    def test_load_profile_parses_directories_and_overrides(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            profile_path = Path(tmpdir) / "repomap-profile.toml"
            profile_path.write_text(
                """
command_dirs = ["bin", "ops"]
script_dirs = ["scripts"]
generated_dirs = ["build/generated"]

[role_overrides]
"README.md" = "documentation"

[confidence_overrides]
"README.md" = "manual"
"""
            )

            profile = load_profile(profile_path)

        self.assertEqual(profile.command_dirs, ("bin", "ops"))
        self.assertEqual(profile.script_dirs, ("scripts",))
        self.assertEqual(profile.generated_dirs, ("build/generated",))
        self.assertEqual(profile.role_overrides["README.md"], "documentation")
        self.assertEqual(profile.confidence_overrides["README.md"], "manual")

    def test_invalid_role_override_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            profile_path = Path(tmpdir) / "repomap-profile.toml"
            profile_path.write_text(
                """
[role_overrides]
"README.md" = "definitely-important"
"""
            )

            with self.assertRaisesRegex(ProfileValidationError, "role"):
                load_profile(profile_path)

    def test_profile_directories_override_discovery_roles(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            command = root / "ops" / "release"
            script = root / "scripts" / "repair.sh"
            generated = root / "build" / "generated" / "manifest.json"
            self.write(command, "#!/usr/bin/env bash\n")
            self.write(script, "#!/usr/bin/env bash\n")
            self.write(generated, "{}\n")
            profile = ProjectProfile(
                command_dirs=("ops",),
                script_dirs=("scripts",),
                generated_dirs=("build/generated",),
            )

            command_info = classify_path(root, command, profile=profile)
            script_info = classify_path(root, script, profile=profile)
            generated_info = classify_path(root, generated, profile=profile)

        self.assertEqual(command_info.role, "entrypoint")
        self.assertEqual(script_info.role, "script")
        self.assertEqual(generated_info.role, "generated")
        self.assertTrue(generated_info.generated)

    def test_profile_overrides_role_and_confidence_for_exact_path(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            readme = root / "README.md"
            self.write(readme, "# Notes\n")
            profile = ProjectProfile(
                role_overrides={"README.md": "config"},
                confidence_overrides={"README.md": "manual"},
            )

            file_info = classify_path(root, readme, profile=profile)
            observation = file_info.to_observation()

        self.assertEqual(file_info.role, "config")
        self.assertEqual(file_info.confidence, "manual")
        self.assertEqual(observation.confidence, "manual")
        self.assertEqual(observation.metadata["role"], "config")

    def test_discover_repository_does_not_require_profile(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self.write(root / "src" / "main" / "python" / "app.py", "print('ok')\n")

            files = discover_repository(root)

        self.assertEqual(files[0].role, "source")
        self.assertEqual(files[0].confidence, "extracted")

    def write(self, path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)


if __name__ == "__main__":
    unittest.main()

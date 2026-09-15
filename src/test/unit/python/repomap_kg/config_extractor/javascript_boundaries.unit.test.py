import unittest

from repomap_kg.extractors.config.generic import extract_config_file_observations


class ConfigExtractorJavascriptBoundariesUnitTests(unittest.TestCase):
    def test_package_json_framework_hints_and_url_references(self):
        observations = extract_config_file_observations(
            "package.json",
            """{
  "name": "my-app",
  "homepage": "https://example.com/my-app",
  "bugs": {"url": "https://example.com/bugs"},
  "scripts": {
    "test": "NODE_ENV=test jest",
    "build": "next build",
    "start": "ng serve",
    "serve": "nest start",
    "e2e": "playwright test",
    "empty": "",
    "custom": "scripts/run.sh"
  }
}""",
        )
        self.assertEqual(observations[0].kind, "config.document")
        hints = [o for o in observations if o.kind == "ecosystem.framework_hint"]
        self.assertGreaterEqual(len(hints), 5)
        refs = [o for o in observations if o.kind == "ecosystem.reference"]
        ref_targets = {o.target for o in refs}
        self.assertIn("external.url:https%3A%2F%2Fexample.com%2Fmy-app", ref_targets)
        self.assertIn("external.url:https%3A%2F%2Fexample.com%2Fbugs", ref_targets)

    def test_package_lock_dependencies_fallback(self):
        observations = extract_config_file_observations(
            "package-lock.json",
            """{
  "name": "legacy-lock",
  "lockfileVersion": 1,
  "dependencies": {
    "express": {"version": "4.18.2"}
  }
}""",
        )
        package_obs = [o for o in observations if o.kind == "ecosystem.package"]
        self.assertEqual(len(package_obs), 1)

    def test_tsconfig_path_aliases_extends_and_project_references(self):
        observations = extract_config_file_observations(
            "tsconfig.json",
            """{
  "extends": "./tsconfig.base.json",
  "compilerOptions": {
    "paths": {
      "@core/*": ["packages/core/src/*"],
      "@utils/*": ["packages/utils/src/*"]
    }
  },
  "references": [
    {"path": "./packages/core"},
    {"path": "./packages/utils"}
  ]
}""",
        )
        ts_config = next(o for o in observations if o.kind == "typescript.config")
        self.assertEqual(ts_config.metadata["path_alias_count"], 2)
        self.assertEqual(ts_config.metadata["project_reference_count"], 2)
        ts_refs = [o for o in observations if o.kind == "typescript.reference"]
        ref_targets = {o.target for o in ts_refs}
        self.assertIn("file:tsconfig.base.json", ref_targets)
        self.assertIn("file:packages/core", ref_targets)
        self.assertIn("file:packages/utils", ref_targets)

    def test_angular_and_playwright_config_profiles(self):
        angular_obs = extract_config_file_observations(
            "angular.json",
            """{
  "version": 1,
  "projects": {
    "web": {
      "root": "src/app",
      "architect": {
        "build": {
          "builder": "@angular-devkit/build-angular:browser"
        }
      }
    }
  }
}""",
        )
        projects = [o for o in angular_obs if o.kind == "angular.project"]
        self.assertEqual(len(projects), 1)
        self.assertEqual(projects[0].metadata["project_name"], "web")

        playwright_obs = extract_config_file_observations(
            "playwright.config.json",
            """{
  "projects": [
    {"name": "chromium"},
    {"name": "firefox"}
  ]
}""",
        )
        pw_config = next(o for o in playwright_obs if o.kind == "playwright.config")
        self.assertEqual(pw_config.metadata["project_names"], ["chromium", "firefox"])

    def test_javascript_and_playwright_malformed_structures(self):
        # tsconfig with malformed references
        ts_obs = extract_config_file_observations(
            "tsconfig.json",
            """{
  "references": [
    "not-a-dict",
    {"path": 123}
  ]
}""",
        )
        self.assertEqual(ts_obs[0].kind, "config.document")

        # playwright with invalid projects
        pw_obs = extract_config_file_observations(
            "playwright.config.json",
            """{
  "projects": [
    "not-a-dict",
    {"other": "field"}
  ]
}""",
        )
        pw_config = next(o for o in pw_obs if o.kind == "playwright.config")
        self.assertEqual(pw_config.metadata["project_count"], 0)

        # angular with non-dict
        ang_obs = extract_config_file_observations(
            "angular.json",
            """{
  "projects": {
    "not-dict": "string",
    "app": {"root": "src"}
  }
}""",
        )
        self.assertEqual(ang_obs[0].kind, "config.document")

        from repomap_kg.extractors.config.javascript import _script_is_secret_prone
        self.assertFalse(_script_is_secret_prone(None))
        self.assertFalse(_script_is_secret_prone(123))


if __name__ == "__main__":
    unittest.main()

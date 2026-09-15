import json
import unittest

from repomap_kg.extractors.config.generic import (
    extract_config_file_observations,
)


class ConfigExtractorPythonJavascriptProfileUnitTests(unittest.TestCase):
    def test_rootpkg34_python_support_helpers_are_reexported(self):
        import repomap_kg.extractors.config.python as python_config
        import repomap_kg.extractors.config.python_support as python_support
        helper_names = (
            "_PythonRequirement",
            "_is_python_requirements_file_name",
            "_is_pyproject_file_name",
            "_parse_python_requirement_line",
            "_python_bounded_string",
            "_python_requirement_file_family",
            "_python_requirement_local_path_target",
            "_python_slug",
        )
        for name in helper_names:
            self.assertIs(getattr(python_config, name), getattr(python_support, name))

    def test_python_requirements_emit_package_references_and_safe_redactions(self):
        observations = extract_config_file_observations(
            "requirements.txt",
            (
                "requests>=2.31,<3\n"
                "fastapi[standard]==0.111.0; python_version >= '3.11'\n"
                "-r dev-requirements.txt\n"
                "-c ../outside.txt\n"
                "-e ./localpkg\n"
                "example @ https://packages.example.invalid/example-1.0.tar.gz\n"
                "--index-url https://user:fake-python-index-secret@packages.example.invalid/simple\n"
                "secret-package @ https://user:fake-python-direct-secret@packages.example.invalid/secret.tar.gz\n"
                "@@not a requirement@@\n"
            ),
        )

        payload = json.dumps(
            [observation.to_dict() for observation in observations],
            sort_keys=True,
        )
        kinds = {observation.kind for observation in observations}
        requirements = [
            item for item in observations if item.kind == "python.requirement"
        ]
        references = [item for item in observations if item.kind == "python.reference"]
        redactions = [item for item in observations if item.kind == "python.redaction"]
        parse_errors = [
            item for item in observations if item.kind == "python.parse_error"
        ]

        self.assertIn("python.package_file", kinds)
        self.assertEqual(
            {
                item.metadata["package_name"]
                for item in requirements
                if "package_name" in item.metadata
            },
            {"requests", "fastapi", "localpkg", "example", "secret-package"},
        )
        fastapi = next(
            item
            for item in requirements
            if item.metadata.get("package_name") == "fastapi"
        )
        self.assertEqual(fastapi.metadata["extras"], ["standard"])
        self.assertEqual(
            fastapi.metadata["environment_marker"],
            "python_version >= '3.11'",
        )
        self.assertIn(
            ("include_file", "file:dev-requirements.txt"),
            {(item.metadata["reference_kind"], item.target) for item in references},
        )
        self.assertIn(
            ("local_path", "file:localpkg"),
            {(item.metadata["reference_kind"], item.target) for item in references},
        )
        self.assertIn(
            "repo-escaping-requirement-reference",
            {item.metadata["error_kind"] for item in parse_errors},
        )
        self.assertIn(
            "malformed-python-requirement",
            {item.metadata["error_kind"] for item in parse_errors},
        )
        self.assertTrue(any(item.metadata["not_fetched"] for item in references))
        self.assertTrue(redactions)
        self.assertNotIn("fake-python-index-secret", payload)
        self.assertNotIn("fake-python-direct-secret", payload)
        self.assertNotIn("user:fake", payload)

    def test_pyproject_emits_python_profile_observations_and_keeps_toml_config(self):
        observations = extract_config_file_observations(
            "pyproject.toml",
            (
                "[project]\n"
                'name = "fixture-python-app"\n'
                'version = "0.1.0"\n'
                'dynamic = ["description"]\n'
                "dependencies = [\n"
                '  "requests>=2.31",\n'
                '  "fastapi[standard]>=0.111; python_version >= \'3.11\'",\n'
                '  "secret-package @ https://user:fake-pyproject-secret@packages.example.invalid/secret.tar.gz",\n'
                "]\n"
                "\n"
                "[project.optional-dependencies]\n"
                'test = ["pytest>=8"]\n'
                "\n"
                "[project.scripts]\n"
                'fixture-tool = "fixture_app.cli:main"\n'
                "\n"
                '[project.entry-points."fixture.plugins"]\n'
                'demo = "fixture_app.plugins:Demo"\n'
                "\n"
                "[build-system]\n"
                'requires = ["setuptools>=69", "wheel"]\n'
                'build-backend = "setuptools.build_meta"\n'
                "\n"
                "[tool.pytest.ini_options]\n"
                'testpaths = ["tests"]\n'
                "\n"
                "[tool.ruff]\n"
                "line-length = 88\n"
            ),
        )

        payload = json.dumps(
            [observation.to_dict() for observation in observations],
            sort_keys=True,
        )
        kinds = {observation.kind for observation in observations}
        pyproject = next(item for item in observations if item.kind == "python.pyproject")
        build_system = next(
            item for item in observations if item.kind == "python.build_system"
        )
        tool_sections = [
            item.metadata["tool_name"]
            for item in observations
            if item.kind == "python.tool_config"
        ]
        requirements = [
            item for item in observations if item.kind == "python.requirement"
        ]
        entry_points = [
            item for item in observations if item.kind == "python.entry_point"
        ]

        self.assertIn("config.document", kinds)
        self.assertIn("config.path", kinds)
        self.assertEqual(pyproject.metadata["project_name"], "fixture-python-app")
        self.assertEqual(pyproject.metadata["project_version"], "0.1.0")
        self.assertEqual(pyproject.metadata["dynamic_metadata"], ["description"])
        self.assertEqual(build_system.metadata["build_backend"], "setuptools.build_meta")
        self.assertIn("pytest", tool_sections)
        self.assertIn("ruff", tool_sections)
        self.assertIn(
            ("requests", "project.dependencies"),
            {
                (item.metadata["package_name"], item.metadata["dependency_group"])
                for item in requirements
                if "package_name" in item.metadata
            },
        )
        self.assertIn(
            ("pytest", "project.optional-dependencies.test"),
            {
                (item.metadata["package_name"], item.metadata["dependency_group"])
                for item in requirements
                if "package_name" in item.metadata
            },
        )
        self.assertIn(
            ("fixture-tool", "project.scripts"),
            {
                (item.metadata["entry_point_name"], item.metadata["entry_point_group"])
                for item in entry_points
            },
        )
        self.assertIn("python.redaction", kinds)
        self.assertNotIn("fake-pyproject-secret", payload)
        self.assertNotIn("user:fake", payload)

    def test_malformed_pyproject_emits_generic_and_python_parse_diagnostics(self):
        observations = extract_config_file_observations(
            "pyproject.toml",
            "[project\nname = 'broken'\n",
        )

        kinds = {item.kind for item in observations}
        python_error = next(
            item for item in observations if item.kind == "python.parse_error"
        )

        self.assertIn("config.parse_error", kinds)
        self.assertEqual(
            python_error.metadata["error_kind"],
            "malformed-pyproject-toml",
        )
        self.assertNotIn("broken", str(python_error.metadata))

    def test_package_json_emits_ecosystem_profile_observations_and_redacts_scripts(self):
        observations = extract_config_file_observations(
            "package.json",
            json.dumps(
                {
                    "name": "@example/app",
                    "version": "1.2.3",
                    "private": True,
                    "type": "module",
                    "packageManager": "pnpm@9.1.0",
                    "scripts": {
                        "test": "jest --runInBand",
                        "deploy": "TOKEN=fake-package-secret npm publish",
                    },
                    "dependencies": {
                        "express": "^4.18.0",
                        "next": "14.0.0",
                        "react": "18.2.0",
                    },
                    "devDependencies": {"jest": "^29.0.0"},
                    "peerDependencies": {"jquery": "^3.7.0"},
                    "optionalDependencies": {"fsevents": "^2.3.0"},
                    "engines": {"node": ">=20"},
                    "workspaces": ["packages/*"],
                    "bin": {"example": "bin/example.js"},
                    "main": "dist/index.js",
                    "module": "dist/index.mjs",
                    "types": "dist/index.d.ts",
                    "exports": {"." : "./dist/index.js"},
                    "imports": {"#config": "./src/config.js"},
                    "repository": {"url": "https://example.invalid/repo.git"},
                    "homepage": "https://example.invalid/app",
                    "bugs": {"url": "https://example.invalid/issues"},
                }
            ),
        )

        payload = json.dumps(
            [observation.to_dict() for observation in observations],
            sort_keys=True,
        )
        kinds = {observation.kind for observation in observations}
        package = next(item for item in observations if item.kind == "npm.package")
        scripts = [item for item in observations if item.kind == "npm.script"]
        dependencies = [item for item in observations if item.kind == "npm.dependency"]
        hints = [item for item in observations if item.kind == "ecosystem.framework_hint"]
        paths = {item.metadata["pointer"]: item for item in observations if item.kind == "config.path"}

        self.assertIn("config.document", kinds)
        self.assertIn("ecosystem.config_profile", kinds)
        self.assertEqual(package.metadata["package_name"], "@example/app")
        self.assertEqual(package.metadata["package_version"], "1.2.3")
        self.assertTrue(package.metadata["private"])
        self.assertEqual(package.metadata["package_manager"], "pnpm@9.1.0")
        self.assertIn("scripts", package.metadata["declared_sections"])
        self.assertIn("workspaces", package.metadata["declared_sections"])
        self.assertIn(
            ("express", "dependencies"),
            {
                (item.metadata["dependency_name"], item.metadata["dependency_group"])
                for item in dependencies
            },
        )
        self.assertIn(
            ("jquery", "peerDependencies"),
            {
                (item.metadata["dependency_name"], item.metadata["dependency_group"])
                for item in dependencies
            },
        )
        self.assertIn(
            ("next", "package-dependency"),
            {
                (item.metadata["framework"], item.metadata["hint_reason"])
                for item in hints
            },
        )
        self.assertIn(
            ("test", "jest"),
            {
                (item.metadata["script_name"], item.metadata["command_summary"])
                for item in scripts
            },
        )
        deploy = next(item for item in scripts if item.metadata["script_name"] == "deploy")
        self.assertTrue(deploy.metadata["redacted"])
        self.assertEqual(deploy.metadata["redaction_reason"], "secret-prone-script")
        self.assertTrue(paths["/scripts/deploy"].metadata["redacted"])
        self.assertNotIn("fake-package-secret", payload)
        self.assertNotIn("TOKEN=", payload)

    def test_typescript_angular_jest_nest_and_playwright_json_profiles(self):
        cases = [
            (
                "tsconfig.json",
                {
                    "extends": "./tsconfig.base.json",
                    "compilerOptions": {
                        "baseUrl": ".",
                        "paths": {"@app/*": ["src/app/*"]},
                        "jsx": "react-jsx",
                    },
                    "references": [{"path": "./packages/app"}],
                },
                {"typescript.config", "typescript.reference"},
            ),
            (
                "angular.json",
                {
                    "projects": {
                        "web": {
                            "root": "apps/web",
                            "sourceRoot": "apps/web/src",
                            "architect": {"build": {"builder": "@angular/build:application"}},
                        }
                    }
                },
                {"angular.project", "angular.target"},
            ),
            (
                "nest-cli.json",
                {"sourceRoot": "src", "collection": "@nestjs/schematics"},
                {"nest.config"},
            ),
            (
                "jest.config.json",
                {
                    "testEnvironment": "node",
                    "testMatch": ["**/*.test.ts"],
                    "setupFilesAfterEnv": ["./test/setup.ts"],
                },
                {"jest.config"},
            ),
            (
                "playwright.config.json",
                {
                    "testDir": "./tests/e2e",
                    "projects": [{"name": "chromium"}, {"name": "webkit"}],
                    "reporter": [["html", {"outputFolder": "playwright-report"}]],
                },
                {"playwright.config"},
            ),
        ]

        for path, document, expected_kinds in cases:
            with self.subTest(path=path):
                observations = extract_config_file_observations(path, json.dumps(document))
                kinds = {observation.kind for observation in observations}
                profiles = [
                    item
                    for item in observations
                    if item.kind == "ecosystem.config_profile"
                ]

                self.assertTrue(expected_kinds.issubset(kinds))
                self.assertEqual(len(profiles), 1)
                self.assertEqual(profiles[0].metadata["format"], "json")
                self.assertIn("profile", profiles[0].metadata)
                self.assertIn("config.document", kinds)
                self.assertIn("config.path", kinds)

import json
import unittest

from repomap_kg.extractors.config.generic import (
    extract_config_file_observations,
)


class ConfigExtractorTomlYamlUnitTests(unittest.TestCase):
    def test_toml_document_paths_references_and_redaction(self):
        observations = extract_config_file_observations(
            "config.toml",
            """
[mcp_servers.repomap]
command = "python3"
args = ["-m", "repomap_kg.server.mcp"]
cwd = "src/main/python"
docs_url = "https://example.com/docs"
api_key = "toml-secret-api-key"
dotted.path.value = "docs/guide.md"

[mcp_servers.repomap.env]
PYTHONPATH = "src/main/python"
TOKEN = "toml-secret-token"

[projects.repo-map]
root_path = "projects/repo-map"
pg_database = "repomap_repo_map"
""",
        )

        payload = json.dumps(
            [observation.to_dict() for observation in observations],
            sort_keys=True,
        )
        paths = [item for item in observations if item.kind == "config.path"]
        references = [item for item in observations if item.kind == "config.reference"]
        pointer_by_path = {item.metadata["pointer"]: item for item in paths}

        self.assertNotIn("toml-secret-api-key", payload)
        self.assertNotIn("toml-secret-token", payload)
        self.assertEqual(observations[0].kind, "config.document")
        self.assertEqual(observations[0].metadata["format"], "toml")
        self.assertEqual(observations[0].metadata["parser"], "stdlib-tomllib")
        self.assertIn("/mcp_servers/repomap", pointer_by_path)
        self.assertIn("/mcp_servers/repomap/command", pointer_by_path)
        self.assertIn("/mcp_servers/repomap/dotted/path/value", pointer_by_path)
        self.assertIn("/projects/repo-map/root_path", pointer_by_path)
        self.assertTrue(pointer_by_path["/mcp_servers/repomap/api_key"].metadata["redacted"])
        self.assertNotIn(
            "value_summary",
            pointer_by_path["/mcp_servers/repomap/api_key"].metadata,
        )
        self.assertIn(
            (
                "/mcp_servers/repomap/command",
                "tool:python3",
                "tool",
            ),
            {
                (item.metadata["pointer"], item.target, item.metadata["reference_kind"])
                for item in references
            },
        )
        self.assertIn(
            (
                "/mcp_servers/repomap/cwd",
                "file:src/main/python",
                "file",
            ),
            {
                (item.metadata["pointer"], item.target, item.metadata["reference_kind"])
                for item in references
            },
        )
        self.assertIn(
            (
                "/mcp_servers/repomap/env/PYTHONPATH",
                "env:PYTHONPATH",
                "env",
            ),
            {
                (item.metadata["pointer"], item.target, item.metadata["reference_kind"])
                for item in references
            },
        )
        self.assertIn("env:TOKEN", {item.target for item in references})
        self.assertIn(
            "external.url:https%3A%2F%2Fexample.com%2Fdocs",
            {item.target for item in references},
        )
        self.assertIn("file:docs/guide.md", {item.target for item in references})

    def test_toml_arrays_of_tables_use_stable_member_keys_without_indexes(self):
        observations = extract_config_file_observations(
            "tools.toml",
            """
plugins = ["python", "ruby"]

[[tools]]
name = "repomap"
command = "repomap-kg"
path = "bin/tool"

[[tools]]
id = "helper"
command = "python3"

[[anonymous]]
command = "do-not-index-with-number"
""",
        )

        paths = [item for item in observations if item.kind == "config.path"]
        pointers = {item.metadata["pointer"] for item in paths}
        references = [item for item in observations if item.kind == "config.reference"]
        plugins = next(item for item in paths if item.metadata["pointer"] == "/plugins")
        tools = next(item for item in paths if item.metadata["pointer"] == "/tools")
        anonymous = next(item for item in paths if item.metadata["pointer"] == "/anonymous")

        self.assertEqual(plugins.metadata["array_policy"], "summary-only")
        self.assertEqual(plugins.metadata["value_summaries"], ["python", "ruby"])
        self.assertEqual(tools.metadata["array_policy"], "stable-member-key")
        self.assertEqual(anonymous.metadata["array_policy"], "summary-only")
        self.assertIn("/tools/repomap", pointers)
        self.assertIn("/tools/repomap/command", pointers)
        self.assertIn("/tools/helper/command", pointers)
        self.assertNotIn("/tools/0/command", pointers)
        self.assertNotIn("/anonymous/0/command", pointers)
        self.assertIn("tool:repomap-kg", {item.target for item in references})
        self.assertIn("tool:python3", {item.target for item in references})
        self.assertIn("file:bin/tool", {item.target for item in references})

    def test_yaml_paths_profiles_references_and_redaction(self):
        observations = extract_config_file_observations(
            ".github/workflows/build.yml",
            """
name: Build
on:
  push:
    branches:
      - main
jobs:
  test:
    runs-on: ubuntu-latest
    env:
      API_TOKEN: fake-yaml-secret-token
    steps:
      - id: checkout
        uses: actions/checkout@v4
      - name: Run tests
        run: python3 tools/run_tests.py --suite unit
      - name: Local action
        uses: ./.github/actions/local-action
""",
        )

        payload = json.dumps(
            [observation.to_dict() for observation in observations],
            sort_keys=True,
        )
        paths = [item for item in observations if item.kind == "config.path"]
        references = [item for item in observations if item.kind == "config.reference"]
        pointer_by_path = {item.metadata["pointer"]: item for item in paths}

        self.assertNotIn("fake-yaml-secret-token", payload)
        self.assertEqual(observations[0].kind, "config.document")
        self.assertEqual(observations[0].metadata["format"], "yaml")
        self.assertEqual(observations[0].metadata["parser"], "stdlib-yaml-conservative")
        self.assertEqual(observations[0].metadata["profile"], "github_actions")
        self.assertEqual(observations[0].metadata["document_count"], 1)
        self.assertIn("/jobs/test/env/API_TOKEN", pointer_by_path)
        self.assertTrue(pointer_by_path["/jobs/test/env/API_TOKEN"].metadata["redacted"])
        self.assertNotIn(
            "value_summary",
            pointer_by_path["/jobs/test/env/API_TOKEN"].metadata,
        )
        self.assertIn("/jobs/test/steps/checkout/uses", pointer_by_path)
        self.assertIn(
            (
                "/jobs/test/steps/checkout/uses",
                "external:github.action:actions%2Fcheckout%40v4",
                "external",
            ),
            {
                (item.metadata["pointer"], item.target, item.metadata["reference_kind"])
                for item in references
            },
        )
        self.assertIn(
            (
                "/jobs/test/steps/Local action/uses",
                "file:.github/actions/local-action",
                "file",
            ),
            {
                (item.metadata["pointer"], item.target, item.metadata["reference_kind"])
                for item in references
            },
        )

    def test_yaml_multidocument_profiles_refs_and_secret_redaction(self):
        observations = extract_config_file_observations(
            "k8s/app.yaml",
            """
apiVersion: v1
kind: ConfigMap
metadata:
  name: app-config
data:
  config_path: ./config/app.yml
---
apiVersion: v1
kind: Secret
metadata:
  name: app-secret
stringData:
  password: fake-k8s-secret-password
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: app
spec:
  template:
    spec:
      serviceAccountName: app-service
      containers:
        - name: app
          image: example/app:1.0
          envFrom:
            - secretRef:
                name: app-secret
""",
        )

        payload = json.dumps(
            [observation.to_dict() for observation in observations],
            sort_keys=True,
        )
        paths = [item for item in observations if item.kind == "config.path"]
        references = [item for item in observations if item.kind == "config.reference"]
        pointer_by_path = {item.metadata["pointer"]: item for item in paths}

        self.assertNotIn("fake-k8s-secret-password", payload)
        self.assertEqual(observations[0].metadata["profile"], "kubernetes")
        self.assertEqual(observations[0].metadata["document_count"], 3)
        self.assertIn("/documents/0/kind", pointer_by_path)
        self.assertIn("/documents/1/stringData/password", pointer_by_path)
        self.assertIn(
            "/documents/2/spec/template/spec/containers/app/image",
            pointer_by_path,
        )
        self.assertEqual(
            pointer_by_path["/documents/1/stringData/password"].metadata[
                "redaction_reason"
            ],
            "secret-prone-yaml-path",
        )
        self.assertEqual(
            pointer_by_path[
                "/documents/2/spec/template/spec/containers/app/image"
            ].metadata["stable_member_keys"],
            ["name"],
        )
        self.assertIn(
            (
                "/documents/0/data/config_path",
                "file:k8s/config/app.yml",
                "file",
            ),
            {
                (item.metadata["pointer"], item.target, item.metadata["reference_kind"])
                for item in references
            },
        )
        self.assertIn(
            "external:docker.image:example%2Fapp%3A1.0",
            {item.target for item in references},
        )

    def test_yaml_profile_detection_matrix_and_openapi_refs(self):
        cases = {
            "Chart.yaml": ("helm_chart", "dependencies:\n  - name: redis\n    repository: https://charts.example.invalid\n"),
            "values.yaml": ("helm_values", "image:\n  repository: example/app\n"),
            "application.yml": ("spring_boot", "spring:\n  config:\n    import: optional:file:./extra.yml\n  datasource:\n    password: fake-spring-secret\n"),
            "openapi.yaml": ("openapi", "openapi: 3.0.0\ninfo:\n  title: API\npaths:\n  /pets:\n    get:\n      responses:\n        '200':\n          $ref: '#/components/responses/Pets'\ncomponents: {}\n"),
            "docker-compose.yml": ("docker_compose", "services:\n  app:\n    image: example/app:latest\n    build:\n      context: ./app\n    env_file: .env\n"),
            ".circleci/config.yml": ("circleci", "version: 2.1\norbs:\n  ruby: circleci/ruby@2.1\njobs:\n  build:\n    docker:\n      - image: cimg/ruby:3.3\n"),
            "grafana/provisioning/datasources.yaml": ("grafana", "apiVersion: 1\ndatasources:\n  - name: main\n    secureJsonData:\n      password: fake-grafana-secret\n"),
            "harness-pipeline.yaml": ("harness", "pipeline:\n  identifier: build\n  projectIdentifier: demo\n  stages: []\n"),
            "serena.yaml": ("serena", "project: repo-map\nserver:\n  token: fake-serena-token\n"),
            "arq-backup-dump.yaml": ("arq_backup", "arq:\n  destination: example-backup\n  arq_encryption_key: fake-arq-key\n"),
            "generic.yaml": ("generic_yaml", "name: generic\n"),
        }

        for path, (profile, content) in cases.items():
            with self.subTest(path=path):
                observations = extract_config_file_observations(path, content)
                payload = json.dumps(
                    [observation.to_dict() for observation in observations],
                    sort_keys=True,
                )
                references = [
                    item for item in observations if item.kind == "config.reference"
                ]

                self.assertEqual(observations[0].metadata["profile"], profile)
                self.assertNotIn("fake-spring-secret", payload)
                self.assertNotIn("fake-grafana-secret", payload)
                self.assertNotIn("fake-serena-token", payload)
                self.assertNotIn("fake-arq-key", payload)
                if path == "openapi.yaml":
                    self.assertIn(
                        "config.path:file%3Aopenapi.yaml:%2Fcomponents%2Fresponses%2FPets",
                        {item.target for item in references},
                    )
                if path == "docker-compose.yml":
                    self.assertIn(
                        "external:docker.image:example%2Fapp%3Alatest",
                        {item.target for item in references},
                    )
                    self.assertIn("file:app", {item.target for item in references})
                    self.assertIn("file:.env", {item.target for item in references})


if __name__ == "__main__":
    unittest.main()

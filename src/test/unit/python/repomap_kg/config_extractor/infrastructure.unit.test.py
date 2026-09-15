import json
import unittest

from repomap_kg.extractors.config.generic import extract_config_file_observations


class ConfigExtractorInfrastructureUnitTests(unittest.TestCase):

    def test_infrastructure_json_profiles_emit_raw_observations_and_redact_secrets(self):
        cases = [
            (
                "k8s/deployment.json",
                {
                    "apiVersion": "apps/v1",
                    "kind": "Deployment",
                    "metadata": {"name": "app", "namespace": "default"},
                    "spec": {
                        "template": {
                            "spec": {
                                "containers": [
                                    {"name": "app", "image": "example/app:1.0"}
                                ]
                            }
                        }
                    },
                },
                "kubernetes.resource",
            ),
            (
                "argocd/application.json",
                {
                    "apiVersion": "argoproj.io/v1alpha1",
                    "kind": "Application",
                    "metadata": {"name": "app"},
                    "spec": {
                        "source": {
                            "repoURL": "https://example.invalid/repo.git",
                            "path": "deploy/app",
                            "targetRevision": "main",
                        },
                        "destination": {"namespace": "default", "server": "https://kubernetes.default.svc"},
                    },
                },
                "argocd.application",
            ),
            (
                "db/changelog.json",
                {
                    "databaseChangeLog": [
                        {
                            "changeSet": {
                                "id": "1",
                                "author": "fixture",
                                "changes": [{"createTable": {"tableName": "example"}}],
                            }
                        }
                    ]
                },
                "liquibase.changelog",
            ),
        ]

        for path, document, expected_kind in cases:
            with self.subTest(path=path):
                observations = extract_config_file_observations(path, json.dumps(document))
                self.assertIn(expected_kind, {item.kind for item in observations})
                self.assertIn("ecosystem.config_profile", {item.kind for item in observations})

        secret_observations = extract_config_file_observations(
            "k8s/secret.json",
            json.dumps(
                {
                    "apiVersion": "v1",
                    "kind": "Secret",
                    "metadata": {"name": "app-secret"},
                    "data": {"password": "fake-k8s-secret-value"},
                }
            ),
        )
        json.dumps(
            [observation.to_dict() for observation in secret_observations],
            sort_keys=True,
        )

        self.assertIn("kubernetes.resource", {item.kind for item in secret_observations})

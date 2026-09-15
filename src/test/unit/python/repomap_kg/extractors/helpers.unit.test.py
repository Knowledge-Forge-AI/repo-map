import unittest

from repomap_kg import __version__
from repomap_kg.extractors.shell.bash import (
    redaction_for_name as bash_redaction_for_name,
    redaction_for_value as bash_redaction_for_value,
)
from repomap_kg.extractors.shared.observations import secret_like_observation
from repomap_kg.extractors.shared.redaction import (
    secret_name_redaction_reason,
    secret_value_redaction_reason,
)
from repomap_kg.extractors.shared.scanner import identifier_parts
from repomap_kg.extractors.shell.zsh import (
    redaction_for_name as zsh_redaction_for_name,
    redaction_for_value as zsh_redaction_for_value,
)


SECRET_PARTS = frozenset(
    {
        "password",
        "passwd",
        "secret",
        "token",
        "key",
        "credential",
        "apikey",
        "pat",
        "authorization",
        "auth",
    }
)


class ExtractorHelperUnitTests(unittest.TestCase):
    def test_identifier_parts_preserves_existing_camel_and_delimiter_splitting(self):
        self.assertEqual(identifier_parts("apiToken"), ("api", "token"))
        self.assertEqual(identifier_parts("NPM_TOKEN"), ("npm", "token"))
        self.assertEqual(
            identifier_parts("path.with-secret/key"),
            ("path", "with", "secret", "key"),
        )

    def test_secret_name_redaction_preserves_exact_and_part_reasons(self):
        exact_reason = secret_name_redaction_reason(
            "GITHUB_TOKEN",
            SECRET_PARTS,
            exact_names={"GITHUB_TOKEN"},
            exact_reason="sensitive-env-name",
        )
        part_reason = secret_name_redaction_reason("ApiToken", SECRET_PARTS)

        self.assertEqual(exact_reason, "sensitive-env-name")
        self.assertEqual(part_reason, "secret-like-name")
        self.assertEqual(
            secret_name_redaction_reason("PUBLIC_FLAG", SECRET_PARTS),
            "",
        )

    def test_secret_value_redaction_preserves_fake_and_part_reasons(self):
        self.assertEqual(
            secret_value_redaction_reason("FAKE_EXAMPLE_TOKEN", SECRET_PARTS),
            "secret-like-value",
        )
        self.assertEqual(
            secret_value_redaction_reason("clientSecret", SECRET_PARTS),
            "secret-like-value",
        )
        self.assertEqual(secret_value_redaction_reason("", SECRET_PARTS), "")
        self.assertEqual(
            secret_value_redaction_reason("public-value", SECRET_PARTS),
            "",
        )

    def test_secret_like_observation_builder_preserves_shell_secret_shape(self):
        observation = secret_like_observation(
            relative_path="scripts/example.sh",
            line_number=7,
            name="API_TOKEN",
            secret_source="assignment",
            reason="secret-like-name",
            source_prefix="test",
            extractor="repo-test",
            extractor_version=__version__,
            metadata_builder=lambda metadata: {"dialect": "test", **metadata},
            slugger=lambda value: value.lower().replace("_", "-"),
        )

        self.assertEqual(observation.kind, "shell.secret_like")
        self.assertEqual(
            observation.source_id,
            "scripts/example.sh#test-secret:7:assignment-api-token",
        )
        self.assertEqual(observation.path, "scripts/example.sh")
        self.assertEqual(observation.start_line, 7)
        self.assertEqual(observation.end_line, 7)
        self.assertEqual(observation.name, "API_TOKEN")
        self.assertEqual(observation.confidence, "heuristic")
        self.assertEqual(observation.metadata["secret_source"], "assignment")
        self.assertTrue(observation.metadata["redacted"])
        self.assertEqual(
            observation.metadata["redaction_reason"],
            "secret-like-name",
        )
        self.assertFalse(observation.metadata["raw_value_stored"])

    def test_bash_and_zsh_redaction_wrappers_remain_compatible(self):
        self.assertEqual(
            bash_redaction_for_name("GITHUB_TOKEN"),
            (True, "sensitive-env-name"),
        )
        self.assertEqual(
            zsh_redaction_for_name("PROMPT"),
            (True, "prompt-like-variable"),
        )
        self.assertEqual(
            bash_redaction_for_name("ApiToken"),
            (True, "secret-like-name"),
        )
        self.assertEqual(
            zsh_redaction_for_name("ApiToken"),
            (True, "secret-like-name"),
        )
        self.assertEqual(
            bash_redaction_for_value("FAKE_BASH_TOKEN"),
            (True, "secret-like-value"),
        )
        self.assertEqual(
            zsh_redaction_for_value("FAKE_ZSH_TOKEN"),
            (True, "secret-like-value"),
        )


if __name__ == "__main__":
    unittest.main()

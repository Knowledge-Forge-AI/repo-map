import unittest
from urllib.parse import unquote

from repomap_kg.extractors.languages.javascript import extract_javascript_file_observations
from repomap_kg.observations.raw import RawObservation


SOURCE_PATH = "src/app/main.js"
LONG_SPECIFIER = "./" + "a" * 130


def extract(*lines, repository_paths=None):
    return extract_javascript_file_observations(
        SOURCE_PATH, "\n".join(lines) + "\n", repository_paths=repository_paths
    )


def references_by_line(observations):
    found: dict[int | None, list[RawObservation]] = {}
    for item in observations:
        if item.kind == "js.reference":
            found.setdefault(item.start_line, []).append(item)
    return found


def single_reference(observations, line_number):
    matches = references_by_line(observations).get(line_number, [])
    assert len(matches) == 1, f"line {line_number}: {len(matches)} references"
    return matches[0]


def at(observations, kind, line_number):
    return [
        item for item in observations
        if item.kind == kind and item.start_line == line_number
    ]


def variables_by_name(observations):
    return {item.name: item.metadata for item in observations if item.kind == "js.variable"}


class JavaScriptSpecifierTargetContractTests(unittest.TestCase):
    def setUp(self):
        self.observations = extract(
            'import mailer from "mailto:ops@example.invalid";',
            'import "s3://bucket/key";',
            'import tools from "@scope/pkg/subpath";',
            'import fp from "lodash/fp";',
            'import home from "~/app.js";',
            'import all from "./pages/*.js";',
            'const abs = require("/tmp/file");',
            'const out = require("../../../outside");',
            'const cfg = require("config/app.json");',
            'import broken from "http://[broken*";',
        )

    def assert_reference(self, line_number, target, reason):
        reference = single_reference(self.observations, line_number)
        self.assertEqual(reference.target, target)
        self.assertEqual(reference.metadata["target_key"], target)
        self.assertEqual(reference.metadata["resolution_reason"], reason)
        self.assertTrue(reference.metadata["not_fetched"])
        return reference

    def test_schemes_are_classified_without_fetching(self):
        mail = single_reference(self.observations, 1)
        self.assertEqual(unquote(mail.target), "external.url:mailto:ops@example.invalid")
        self.assertEqual(mail.metadata["resolution_reason"], "external-url")
        self.assertEqual(mail.metadata["raw_value_summary"], "mailto:ops@example.invalid")
        self.assertTrue(mail.metadata["not_fetched"])
        side_effect = self.assert_reference(
            2, "unknown:js.reference:unsupported-scheme", "unsupported-scheme"
        )
        self.assertEqual(side_effect.metadata["reference_kind"], "side_effect_import")
        self.assertEqual(side_effect.metadata["raw_value_summary"], "s3://bucket/key")

    def test_package_specifiers_collapse_to_their_package_names(self):
        self.assert_reference(3, "external:js-package:%40scope%2Fpkg", "external-js-package")
        self.assert_reference(4, "external:js-package:lodash", "external-js-package")

    def test_home_wildcard_and_malformed_url_specifiers_are_dynamic(self):
        self.assert_reference(5, "dynamic:js.reference:dynamic-path", "dynamic")
        self.assert_reference(6, "dynamic:js.reference:dynamic-specifier", "dynamic")
        malformed = self.assert_reference(
            10, "dynamic:js.reference:dynamic-specifier", "dynamic"
        )
        self.assertEqual(malformed.metadata["raw_value_summary"], "http://[broken*")
        imported = at(self.observations, "js.import", 10)[0]
        self.assertEqual(imported.name, "http://[broken*")
        self.assertEqual(imported.metadata["import_specifier"], "http://[broken*")
        self.assertTrue(imported.metadata["not_loaded"])

    def test_absolute_escaping_and_bare_file_specifiers_stay_repo_bounded(self):
        absolute = self.assert_reference(7, "external:file:absolute-js-reference", "absolute-file")
        self.assertEqual(absolute.metadata["reference_kind"], "require")
        escaping = self.assert_reference(
            8, "unknown:file:repo-escaping-js-reference", "repo-escaping"
        )
        self.assertEqual(escaping.metadata["reference_kind"], "require")
        bare = self.assert_reference(9, "file:src/app/config/app.json", "repo-local")
        self.assertEqual(bare.metadata["reference_kind"], "require")
        for line_number in (7, 8, 9):
            required = at(self.observations, "node.require", line_number)
            self.assertEqual(len(required), 1)
            self.assertTrue(required[0].metadata["not_loaded"])


class JavaScriptRepositoryResolutionContractTests(unittest.TestCase):
    def test_directory_specifiers_resolve_to_index_files_or_stay_unresolved(self):
        observations = extract(
            'import widgets from "./components";',
            'import legacy from "./legacy";',
            'import ghost from "./ghost";',
            repository_paths=frozenset(
                {
                    SOURCE_PATH,
                    "src/app/components/index.tsx",
                    "src/app/legacy/index.mjs",
                }
            ),
        )

        self.assertEqual(single_reference(observations, 1).target, "file:src/app/components/index.tsx")
        self.assertEqual(single_reference(observations, 2).target, "file:src/app/legacy/index.mjs")
        ghost = single_reference(observations, 3)
        self.assertEqual(ghost.target, "file:src/app/ghost")
        for line_number in (1, 2, 3):
            self.assertEqual(
                single_reference(observations, line_number).metadata["resolution_reason"],
                "repo-local",
            )


class JavaScriptSafeSummaryContractTests(unittest.TestCase):
    def setUp(self):
        self.observations = extract(
            f'import long from "{LONG_SPECIFIER}";',
            'import session from "./auth/session";',
            'fetch("https://user:pass@example.invalid:8443/path?id=my-token&ok=1");',
            'importScripts("s3://bucket/worker.js");',
        )

    def test_overlong_specifier_summaries_are_truncated(self):
        expected = LONG_SPECIFIER[:117] + "..."
        imported = at(self.observations, "js.import", 1)[0]
        self.assertEqual(len(expected), 120)
        self.assertEqual(imported.name, expected)
        self.assertEqual(imported.metadata["import_specifier"], expected)
        reference = single_reference(self.observations, 1)
        self.assertEqual(reference.metadata["raw_value_summary"], expected)
        self.assertEqual(reference.target, "file:src/app/" + "a" * 130)

    def test_secret_prone_specifier_summaries_are_redacted_but_target_is_kept(self):
        imported = at(self.observations, "js.import", 2)[0]
        self.assertEqual(imported.name, "REDACTED")
        self.assertEqual(imported.metadata["import_specifier"], "REDACTED")
        reference = single_reference(self.observations, 2)
        self.assertEqual(reference.metadata["raw_value_summary"], "REDACTED")
        self.assertEqual(reference.target, "file:src/app/auth/session")

    def test_url_credentials_port_and_secret_query_values_are_sanitized(self):
        fetched = single_reference(self.observations, 3)
        self.assertEqual(fetched.metadata["reference_kind"], "fetch")
        self.assertEqual(fetched.metadata["resolution_reason"], "external-url")
        self.assertEqual(
            fetched.metadata["raw_value_summary"],
            "https://example.invalid:8443/path?id=REDACTED&ok=1",
        )
        self.assertEqual(
            unquote(fetched.target),
            "external.url:https://example.invalid:8443/path?id=REDACTED&ok=1",
        )
        self.assertTrue(fetched.metadata["not_fetched"])
        payload = "\n".join(item.to_json_line() for item in self.observations)
        self.assertNotIn("user:pass", payload)
        self.assertNotIn("my-token", payload)

    def test_import_scripts_with_unsupported_scheme_is_not_fetched(self):
        worker = single_reference(self.observations, 4)
        self.assertEqual(worker.metadata["reference_kind"], "importScripts")
        self.assertEqual(worker.metadata["resolution_reason"], "unsupported-scheme")
        self.assertEqual(worker.target, "unknown:js.reference:unsupported-scheme")
        self.assertTrue(worker.metadata["not_fetched"])


class JavaScriptVariableLiteralContractTests(unittest.TestCase):
    def setUp(self):
        self.pem = "-----BEGIN PRIVATE KEY-----"
        self.blob = "abcdefghijklmnopqrstuvwxyz0123456789token"
        self.digest = "abcdefghijklmnopqrstuvwxyz0123456789abcd"
        self.observations = extract(
            "let pending;",
            "const flag = true;",
            "const nothing = null;",
            "const ratio = 4.2;",
            "const offset = -5;",
            "const list = [1, 2];",
            "const shape = { a: 1 };",
            "const text = 'plain';",
            "const handler = x => x;",
            "const maker = function () {};",
            "const computed = compute();",
            f'const pem = "{self.pem}";',
            f'const blob = "{self.blob}";',
            f'const digest = "{self.digest}";',
        )
        self.variables = variables_by_name(self.observations)

    def test_literal_types_are_classified_from_source_text(self):
        expected = {
            "pending": "unknown", "flag": "boolean", "nothing": "null", "ratio": "decimal",
            "offset": "integer", "list": "array", "shape": "object", "text": "string",
            "handler": "function", "maker": "function", "computed": "expression",
        }
        self.assertEqual(
            {name: self.variables[name]["literal_type"] for name in expected}, expected
        )
        self.assertEqual(self.variables["pending"]["variable_kind"], "let")
        self.assertEqual(self.variables["flag"]["variable_kind"], "const")
        for name in expected:
            self.assertFalse(self.variables[name]["redacted"], name)
            self.assertNotIn("redaction_reason", self.variables[name])

    def test_secret_shaped_literals_are_redacted_even_with_neutral_names(self):
        for name in ("pem", "blob"):
            self.assertTrue(self.variables[name]["redacted"], name)
            self.assertEqual(self.variables[name]["redaction_reason"], "secret-prone-variable")
            self.assertEqual(self.variables[name]["literal_type"], "string")
        self.assertFalse(self.variables["digest"]["redacted"])
        payload = "\n".join(item.to_json_line() for item in self.observations)
        self.assertNotIn(self.pem, payload)
        self.assertNotIn(self.blob, payload)


class JavaScriptDecoratorArgumentContractTests(unittest.TestCase):
    def test_decorator_arguments_are_omitted_or_redacted(self):
        observations = extract(
            "@Injectable",
            "export class Service {}",
            "@UseGuards(AuthGuard)",
            "export class Guarded {}",
        )

        bare = at(observations, "nest.decorator", 1)[0]
        self.assertEqual(bare.metadata["decorator_name"], "Injectable")
        self.assertNotIn("decorator_args_summary", bare.metadata)
        guarded = at(observations, "nest.decorator", 3)[0]
        self.assertEqual(guarded.metadata["decorator_name"], "UseGuards")
        self.assertEqual(guarded.metadata["decorator_args_summary"], "REDACTED")
        payload = "\n".join(item.to_json_line() for item in observations)
        self.assertNotIn("AuthGuard", payload)


if __name__ == "__main__":
    unittest.main()

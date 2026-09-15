import unittest
from unittest.mock import patch
from xml.etree import ElementTree


from repomap_kg.extractors.config import generic as config


class ConfigExtractorHelperBranchUnitTests(unittest.TestCase):
    def test_config_yaml_helpers_cover_scalar_metadata_and_safe_errors(self):
        state = config._YamlParseState()

        tagged = config._parse_yaml_scalar("!secret &main", 1, state)
        self.assertTrue(tagged.metadata_only)
        config._record_yaml_value_metadata(
            tagged,
            state,
            pointer_segments=("credentials",),
            merge_key=True,
        )
        self.assertEqual(
            state.metadata()["/credentials"],
            {
                "yaml_tag": "!secret",
                "redacted": True,
                "redaction_reason": "secret-prone-yaml-tag",
                "anchor": "main",
                "merge_key": True,
            },
        )

        alias = config._parse_yaml_scalar("*main", 2, state)
        self.assertEqual(alias.value, "main")
        self.assertEqual(alias.alias, "main")
        with patch.object(config, "YAML_MAX_ALIASES", state.alias_count):
            with self.assertRaises(config.YamlParseError):
                config._parse_yaml_scalar("*again", 3, state)
        with patch.object(config, "YAML_MAX_SCALAR_LENGTH", 3):
            with self.assertRaises(config.YamlParseError):
                config._parse_yaml_scalar("abcd", 4, config._YamlParseState())

        scalar_cases = {
            "'quoted # still value'": "quoted # still value",
            '"line\\nfeed"': "line\nfeed",
            "true": True,
            "FALSE": False,
            "null": None,
            "~": None,
            "-7": -7,
            "+8": 8,
            "3.14": 3.14,
            "plain": "plain",
        }
        for text, value in scalar_cases.items():
            with self.subTest(text=text):
                self.assertEqual(config._parse_yaml_plain_scalar(text), value)

        self.assertEqual(
            config._strip_yaml_comment('value "# not comment" # comment'),
            'value "# not comment" ',
        )
        self.assertEqual(config._yaml_first_token(""), (None, ""))
        self.assertEqual(config._yaml_first_token("!tag rest"), ("!tag", "rest"))
        self.assertEqual(config._yaml_mapping_colon_index('"a:b": value'), 5)
        self.assertIsNone(config._yaml_mapping_colon_index("http://example.invalid"))
        self.assertEqual(config._split_yaml_mapping_pair('"a:b": value', 1), ("a:b", "value"))
        for text in ("not a pair", ": missing-key"):
            with self.subTest(text=text):
                with self.assertRaises(config.YamlParseError):
                    config._split_yaml_mapping_pair(text, 1)

        inline_state = config._YamlParseState()
        self.assertEqual(
            config._parse_yaml_inline_sequence('[one, "two, too", {nested: [true, false]}]', 1, inline_state),
            ["one", "two, too", {"nested": [True, False]}],
        )
        self.assertEqual(
            config._parse_yaml_inline_mapping("{alpha: one, beta: [x, y]}", 1, inline_state),
            {"alpha": "one", "beta": ["x", "y"]},
        )
        self.assertEqual(config._parse_yaml_inline_sequence("[]", 1, inline_state), [])
        self.assertEqual(config._parse_yaml_inline_mapping("{}", 1, inline_state), {})
        for text in ("[unterminated", "{unterminated"):
            with self.subTest(text=text):
                with self.assertRaises(config.YamlParseError):
                    config._parse_yaml_scalar(text, 1, config._YamlParseState())
        for text in ("one, ]", "one, }"):
            with self.subTest(text=text):
                with self.assertRaises(config.YamlParseError):
                    config._split_yaml_inline_items(text, 1)
        with self.assertRaises(config.YamlParseError):
            config._parse_yaml_inline_mapping("{a: one, a: two}", 1, inline_state)

        parsed, metadata, document_count = config._parse_yaml_documents(
            "multi.yaml",
            """
---
first: !secret &main hidden
...
---
- item
- nested: value
""",
        )
        self.assertEqual(document_count, 3)
        self.assertIsNone(parsed["documents"]["0"])
        self.assertEqual(parsed["documents"]["2"], ["item", {"nested": "value"}])
        self.assertEqual(
            metadata["/documents/1/first"]["redaction_reason"],
            "secret-prone-yaml-tag",
        )
        error_cases = {
            "tab.yaml": "\tbad: value\n",
            "indent.yaml": "root:\n    child: value\n  bad: value\n",
            "sequence.yaml": "- key: value\n  - nested\n",
            "duplicate.yaml": "a: one\na: two\n",
        }
        for path, content in error_cases.items():
            with self.subTest(path=path):
                observations = config.extract_config_file_observations(path, content)
                self.assertEqual(observations[0].kind, "config.parse_error")
        openapi_error = config.extract_config_file_observations(
            "openapi.yaml",
            "openapi: 3.1.0\npaths: one\npaths: two\n",
        )
        self.assertEqual(
            {item.kind for item in openapi_error},
            {"config.parse_error", "openapi.parse_error"},
        )

    def test_config_profile_helpers_cover_python_terraform_openapi_and_xml_branches(self):
        pyproject = {
            "project": {
                "name": "repo-map",
                "version": "1.2.3",
                "dependencies": [
                    "requests>=2",
                    "git+https://example.invalid/pkg.git#egg=remote_pkg",
                    7,
                    "not a valid requirement ???",
                ],
                "optional-dependencies": {"dev": ["pytest>=8"]},
                "dynamic": ["version", "api-token"],
                "scripts": {"repomap": "repomap_kg.__main__:main"},
                "gui-scripts": {"repomap-gui": "repomap_kg.gui:main"},
                "entry-points": {"repomap.plugins": {"plugin": "repomap_kg.plugin:main"}},
            },
            "build-system": {
                "requires": ["setuptools>=70"],
                "build-backend": "setuptools.build_meta",
            },
            "tool": {"pytest": {"addopts": "-q"}},
            "dependency-groups": {"docs": ["mkdocs>=1"]},
        }
        observations = config._python_pyproject_observations(
            "pyproject.toml",
            pyproject,
            format_name="toml",
            confidence="extracted",
        )
        kinds = [observation.kind for observation in observations]
        self.assertIn("python.pyproject", kinds)
        self.assertIn("python.build_system", kinds)
        self.assertIn("python.dependency_group", kinds)
        self.assertEqual(kinds.count("python.entry_point"), 3)
        self.assertGreaterEqual(kinds.count("python.requirement"), 4)
        self.assertGreaterEqual(kinds.count("python.reference"), 1)
        self.assertGreaterEqual(kinds.count("python.parse_error"), 1)
        pyproject_metadata = next(
            observation.metadata
            for observation in observations
            if observation.kind == "python.pyproject"
        )
        self.assertEqual(pyproject_metadata["project_name"], "repo-map")
        self.assertEqual(pyproject_metadata["project_version"], "1.2.3")
        self.assertEqual(pyproject_metadata["dynamic_metadata"], ["version"])
        self.assertEqual(pyproject_metadata["optional_dependency_groups"], ["dev"])

        self.assertEqual(
            config._python_requirement_package_from_source(
                "git+https://example.invalid/pkg.git#egg=remote_pkg"
            ),
            "remote_pkg",
        )
        self.assertEqual(
            config._python_requirement_package_from_source(
                "https://example.invalid/archive.tar.gz"
            ),
            "archive",
        )
        self.assertIsNone(config._python_requirement_package_from_source("###"))

        terraform = {
            "provider": [{"aws": {}}, {"google": {}}],
            "resource": {"aws_s3_bucket": {"logs": {}}},
            "data": {"aws_iam_policy_document": {"assume": {}}},
            "module": {"vpc": {"source": "terraform-aws-modules/vpc/aws"}},
            "variable": {"region": {}},
            "output": {"bucket": {}},
            "locals": {"name": "logs"},
        }
        tf_observations = config._terraform_named_block_observations(
            "main.tf.json",
            terraform,
            format_name="json",
            confidence="extracted",
        )
        self.assertEqual(config._terraform_block_names({"aws": {}, "google": {}}), ("aws", "google"))
        self.assertEqual(
            config._terraform_block_names([{"aws": {}}, "bad", {"google": {}}]),
            ("aws", "google"),
        )
        self.assertEqual(config._terraform_block_names("bad"), ())
        self.assertEqual(
            {
                "terraform.provider",
                "terraform.resource",
                "terraform.data_source",
                "terraform.module",
                "terraform.reference",
                "terraform.variable",
                "terraform.output",
                "terraform.local",
            },
            {observation.kind for observation in tf_observations},
        )

        expression_cases = {
            "": "unknown",
            '"literal"': "literal_string",
            '"${var.name}"': "template_interpolation",
            "false": "literal_bool",
            "null": "literal_null",
            "-1.5": "literal_number",
            "[1, 2]": "collection_shape",
            "${var.name}": "template_interpolation",
            "lookup(var.map, \"x\")": "function_call",
            "var.enabled ? 1 : 0": "conditional",
            "module.vpc.id": "traversal_reference",
            "dynamic \"ingress\"": "dynamic_block",
            "not valid !": "unknown",
        }
        for expression, expression_kind in expression_cases.items():
            with self.subTest(expression=expression):
                self.assertEqual(
                    config._terraform_hcl_expression_kind(expression),
                    expression_kind,
                )

        profile_cases = {
            "openapi.json": ({"openapi": "3.1.0", "paths": {}}, "openapi_json"),
            "vars.tfvars.json": ({}, "terraform_tfvars_json"),
            "main.tf.json": ({}, "terraform_json"),
            "package.json": ({}, "package_json"),
            "package-lock.json": ({}, "package_lock_json"),
            "tsconfig.app.json": ({}, "typescript_config"),
            "jsconfig.json": ({}, "javascript_config"),
            "angular.json": ({}, "angular_workspace"),
            "workspace.json": ({}, "workspace_config"),
            "nest-cli.json": ({}, "nest_config"),
            "jest.config.json": ({}, "jest_config"),
            ".babelrc": ({}, "babel_config"),
            ".eslintrc.json": ({}, "eslint_config"),
            ".prettierrc": ({}, "prettier_config"),
            "playwright.config.json": ({}, "playwright_config"),
            "kubernetes.json": (
                {"apiVersion": "v1", "kind": "Pod", "metadata": {"name": "pod"}},
                "kubernetes_json",
            ),
        }
        for path, (value, profile) in profile_cases.items():
            with self.subTest(path=path):
                self.assertEqual(
                    config._tfjson_profile(path, value, format_name="json"),
                    profile,
                )
        self.assertIsNone(config._tfjson_profile("data.txt", {}, format_name="json"))
        self.assertIsNone(config._tfjson_profile("package.json", [], format_name="json"))
        self.assertIsNone(config._tfjson_profile("package.json", {}, format_name="toml"))

        oauth_scheme = {
            "flows": {
                "authorizationCode": {
                    "scopes": {
                        "repo:read": "read repositories",
                        "api-token": "secret marker",
                        "x" * (config.OPENAPI_MAX_METADATA_STRING + 1): "too long",
                    }
                },
                "clientCredentials": "bad",
            }
        }
        self.assertEqual(config._openapi_scope_names(oauth_scheme), ["repo:read"])
        self.assertEqual(config._openapi_scope_names({"flows": []}), [])
        self.assertEqual(
            config._yaml_openapi_ref("openapi.yaml", "https://example.invalid/spec.json", redacted=False)["kind"],
            "external.url",
        )
        self.assertEqual(
            config._yaml_openapi_ref("openapi.yaml", "#/components/schemas/User", redacted=True)["reason"],
            "openapi-local-pointer-ref",
        )
        self.assertEqual(
            config._yaml_openapi_ref("openapi.yaml", "common.yaml#/User", redacted=False)["reason"],
            "openapi-local-file-ref",
        )
        self.assertEqual(
            config._yaml_openapi_ref("openapi.yaml", "relative.yaml", redacted=False)["kind"],
            "file",
        )

        plist = ElementTree.fromstring(
            """
<dict>
  <key>Name</key><string>repo-map</string>
  <key>Enabled</key><true/>
  <key>Count</key><integer>7</integer>
  <key>Ratio</key><real>1.5</real>
  <key>Items</key><array><string>a</string><false/></array>
</dict>
""",
        )
        self.assertEqual(
            config._plist_value(plist),
            {
                "Name": "repo-map",
                "Enabled": True,
                "Count": 7,
                "Ratio": 1.5,
                "Items": ["a", False],
            },
        )
        for xml_text in ("<integer>bad</integer>", "<real>bad</real>", "<unknown/>"):
            with self.subTest(xml_text=xml_text):
                with self.assertRaises(config.PlistXmlParseError):
                    config._plist_value(ElementTree.fromstring(xml_text))

        bean = ElementTree.fromstring('<bean id="repoMap" class="example.RepoMap"/>')
        prop = ElementTree.fromstring('<property name="client" ref="repoMap"/>')
        pom = ElementTree.fromstring(
            """
<dependency>
  <groupId>com.example</groupId>
  <artifactId>repo-map</artifactId>
  <version>1.0</version>
</dependency>
""",
        )
        self.assertEqual(
            config._xml_domain_metadata(bean, document_role="spring-config"),
            {"bean_id": "repoMap", "class_name": "example.RepoMap"},
        )
        self.assertEqual(
            config._xml_domain_metadata(prop, document_role="spring-config"),
            {"property_name": "client", "bean_ref": "repoMap"},
        )
        self.assertEqual(
            config._xml_domain_metadata(pom, document_role="maven-pom"),
            {
                "maven_group_id": "com.example",
                "maven_artifact_id": "repo-map",
                "maven_version": "1.0",
            },
        )
        self.assertEqual(config._xml_domain_metadata(bean, document_role="generic"), {})

        package_lock = config._package_lock_observations(
            "package-lock.json",
            {"lockfileVersion": 3, "packages": {"": {}, "node_modules/a": {}}},
            format_name="json",
            confidence="extracted",
        )
        self.assertEqual(package_lock[0].metadata["package_count"], 2)

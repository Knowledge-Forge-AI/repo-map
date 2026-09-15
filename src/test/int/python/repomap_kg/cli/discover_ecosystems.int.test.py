import json
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[6]
from repomap_test_support.cli_integration import CliIntegrationTestCase


class CliDiscoverEcosystemsIntegrationTests(CliIntegrationTestCase):
    def _run_discover(self, fixture: Path) -> tuple[str, list[dict]]:
        exit_code, stdout, stderr = self.run_module_entrypoint("discover", str(fixture), "--jsonl")
        self.assertEqual(exit_code, 0, stderr)
        return stdout, [json.loads(line) for line in stdout.splitlines() if line.strip()]

    def test_discover_command_emits_python_ecosystem_observations_from_fixture(self):
        fixture = REPO_ROOT / "src" / "test" / "fixtures" / "python_ecosystem"
        stdout, observations = self._run_discover(fixture)
        kinds = {obs["kind"] for obs in observations}
        self.assertTrue({
            "python.package_file", "python.requirement", "python.reference", "python.pyproject",
            "python.build_system", "python.dependency_group", "python.entry_point", "python.tool_config",
            "python.test_file", "python.test_function", "python.test_method", "python.test_fixture",
            "python.test_parametrize", "python.test_assertion", "python.unittest_case", "python.pytest_test",
            "python.pytest_fixture", "python.parse_error", "python.redaction", "config.document", "config.path",
        }.issubset(kinds))
        for secret in ("fake-python-index-secret", "fake-python-direct-secret", "fake-pyproject-secret",
                       "fake-pyproject-index-secret", "user:fake"):
            self.assertNotIn(secret, stdout)

        redaction_reasons = {obs["metadata"]["redaction_reason"] for obs in observations if obs["kind"] == "python.redaction"}
        self.assertIn("credentialed-url", redaction_reasons)
        references = [obs for obs in observations if obs["kind"] == "python.reference"]
        self.assertTrue(any(item["metadata"]["not_fetched"] for item in references))
        self.assertTrue(any(item["metadata"]["reference_kind"] in {"include_file", "constraint_file"}
                            and item["target"].startswith("file:") for item in references))
        parse_error_kinds = {obs["metadata"]["error_kind"] for obs in observations if obs["kind"] == "python.parse_error"}
        self.assertTrue({"malformed-python-requirement", "malformed-pyproject-toml", "malformed-python"}.issubset(parse_error_kinds))

    def test_discover_command_emits_python_web_observations_from_fixture(self):
        fixture = REPO_ROOT / "src" / "test" / "fixtures" / "python_web"
        stdout, observations = self._run_discover(fixture)
        kinds = {obs["kind"] for obs in observations}
        self.assertTrue({
            "python.flask_app", "python.flask_blueprint", "python.flask_route", "python.fastapi_app",
            "python.fastapi_router", "python.fastapi_route", "python.fastapi_dependency", "python.django_app",
            "python.django_urlpattern", "python.django_view", "python.django_model",
            "python.django_setting_reference", "python.reference", "python.parse_error", "python.redaction",
        }.issubset(kinds))

        flask_route = next(obs for obs in observations if obs["kind"] == "python.flask_route" and obs["metadata"].get("route_path") == "/health")
        fastapi_route = next(obs for obs in observations if obs["kind"] == "python.fastapi_route" and obs["metadata"].get("route_path") == "/items/{item_id}")
        django_url = next(obs for obs in observations if obs["kind"] == "python.django_urlpattern" and obs["metadata"].get("route_path") == "users/")
        dynamic_diagnostics = [obs for obs in observations if obs["kind"] == "python.parse_error" and obs["metadata"].get("error_kind") == "dynamic-python-web-route"]
        references = [obs for obs in observations if obs["kind"] == "python.reference"]

        self.assertEqual(flask_route["metadata"]["http_methods"], ["GET"])
        self.assertEqual(fastapi_route["metadata"]["http_methods"], ["GET"])
        self.assertTrue(fastapi_route["metadata"]["summary_present"])
        self.assertIn("summary_sha256", fastapi_route["metadata"])
        self.assertEqual(django_url["metadata"]["urlpattern_kind"], "path")
        self.assertTrue(dynamic_diagnostics)
        self.assertTrue({"flask_route_handler", "fastapi_route_handler", "fastapi_dependency",
                         "django_urlpattern_view", "django_include"}.issubset(
            {ref["metadata"]["reference_kind"] for ref in references}
        ))
        for secret in ("fake-flask-web-secret", "fake-flask-db-secret", "fake-fastapi-default-secret",
                       "fake-fastapi-token-secret", "fake-django-web-secret", "fake-django-redaction-secret",
                       "fake-django-uri-secret", "fixture item summary", "fixture bulk description"):
            self.assertNotIn(secret, stdout)

    def test_discover_command_emits_terraform_hcl_observations_from_fixture(self):
        fixture = REPO_ROOT / "src" / "test" / "fixtures" / "terraform_hcl" / "basic"
        stdout, observations = self._run_discover(fixture)
        kinds = {obs["kind"] for obs in observations}
        self.assertTrue({
            "terraform.file", "terraform.block", "terraform.required_provider", "terraform.resource",
            "terraform.module", "terraform.variable", "terraform.output", "terraform.reference",
            "terraform.import", "terraform.redaction", "terraform.parse_error",
        }.issubset(kinds))
        terraform_files = [obs for obs in observations if obs["kind"] == "file" and obs["metadata"]["language"] == "terraform"]
        self.assertEqual(
            [obs["path"] for obs in terraform_files],
            ["broken.tf", "dev.auto.tfvars", "main.tf", "prod.tfvars", "terraform.tfvars"],
        )
        for secret in ("fake-tfhcl-provider-secret", "fake-tfhcl-module-secret", "fake-tfhcl-prod-tfvars-secret",
                       "fake-tfhcl-tfvars-secret", "fake-tfhcl-import-secret"):
            self.assertNotIn(secret, stdout)

    def test_discover_command_emits_css_static_observations_from_fixture(self):
        fixture = REPO_ROOT / "src" / "test" / "fixtures" / "discovery" / "css_static_basic"
        stdout, observations = self._run_discover(fixture)
        for secret in ("fixture-secret-token", "PHNlY3JldD4="):
            self.assertNotIn(secret, stdout)
        kinds = {obs["kind"] for obs in observations}
        self.assertTrue({
            "css.document", "css.rule", "css.selector", "css.declaration",
            "css.custom_property", "css.reference", "css.parse_error",
        }.issubset(kinds))
        css_files = [obs for obs in observations if obs["kind"] == "file" and obs["metadata"]["language"] == "css"]
        self.assertEqual([obs["path"] for obs in css_files], ["tools/test/report/static/report.css", "tools/test/report/static/reset.css"])
        selector_classes = {class_name for obs in observations if obs["kind"] == "css.selector" for class_name in obs["metadata"]["classes"]}
        self.assertTrue({"status-badge", "report-header", "report-badges", "tree-grid", "test-grid",
                         "path-cell", "metric-cell", "status-cell", "row"}.issubset(selector_classes))
        reference_targets = {obs["target"] for obs in observations if obs["kind"] == "css.reference"}
        self.assertIn("file:tools/test/assets/panel.svg", reference_targets)
        self.assertIn("unknown:file:repo-escaping-css-reference", reference_targets)
        self.assertIn("dynamic:file:css-url-dynamic", reference_targets)

    def test_discover_command_emits_ruby_static_observations_from_fixture(self):
        fixture = REPO_ROOT / "src" / "test" / "fixtures" / "discovery" / "ruby_basic"
        stdout, observations = self._run_discover(fixture)
        kinds = {obs["kind"] for obs in observations}
        profiles = {obs["metadata"].get("profile") for obs in observations if obs["kind"] == "ruby.file"}
        targets = {obs.get("target") for obs in observations if obs["kind"] == "ruby.reference"}

        self.assertTrue({
            "ruby.file", "ruby.module", "ruby.class", "ruby.method", "ruby.singleton_method",
            "ruby.constant", "ruby.require", "ruby.route", "ruby.test_case", "ruby.test_method",
            "ruby.gem_dependency", "ruby.vagrant_config", "ruby.parse_error",
        }.issubset(kinds))
        self.assertTrue({"generic_ruby", "minitest", "vagrantfile", "sinatra", "hanami", "rake", "gemfile", "gemspec"}.issubset(profiles))
        self.assertIn("file:lib/example/service.rb", targets)
        self.assertIn("external:ruby-gem:rack", targets)
        self.assertIn("external:vagrant-box:example%2Fubuntu", targets)
        self.assertNotIn("echo setup", stdout)

    def test_discover_command_emits_js_static_observations_from_fixture(self):
        fixture = REPO_ROOT / "src" / "test" / "fixtures" / "discovery" / "js_basic"
        stdout, observations = self._run_discover(fixture)
        kinds = {obs["kind"] for obs in observations}
        profiles = {obs["metadata"].get("profile") for obs in observations if obs["kind"] == "js.file"}
        targets = {obs.get("target") for obs in observations if obs["kind"] == "js.reference"}

        self.assertTrue({
            "js.file", "js.module", "js.import", "js.export", "js.function", "js.class", "js.method",
            "js.variable", "js.component", "js.hook", "js.route", "js.test_suite", "js.test_case",
            "js.test_expectation", "js.reference", "js.parse_error",
        }.issubset(kinds))
        self.assertTrue({"generic_javascript", "generic_typescript", "jest", "react", "angular",
                         "vue", "frontend_asset", "test_report_asset"}.issubset(profiles))
        self.assertIn("file:src/util.mjs", targets)
        self.assertIn("external:js-package:react", targets)
        self.assertIn("file:public/report.js.map", targets)
        self.assertIn("external.url:https%3A%2F%2Fexample.invalid%2Fapi%3Ftoken%3DREDACTED", targets)
        self.assertNotIn("placeholder", stdout)
        self.assertNotIn("Bearer ${apiToken}", stdout)

    def test_discover_command_emits_feed_observations_from_fixture(self):
        fixture = REPO_ROOT / "src" / "test" / "fixtures" / "discovery" / "feed_static_basic"
        stdout, observations = self._run_discover(fixture)
        for s in ("fixture-feed-secret", "throw new Error"):
            self.assertNotIn(s, stdout)
        kinds = {obs["kind"] for obs in observations}
        self.assertTrue({"feed.document", "feed.channel", "feed.item", "feed.link",
                         "feed.enclosure", "feed.author", "feed.category", "feed.content", "feed.parse_error"}.issubset(kinds))
        feed_formats = {obs["metadata"].get("feed_format") for obs in observations if obs["kind"] == "feed.document"}
        self.assertEqual(feed_formats, {"rss", "atom", "json-feed"})
        feed_files = [obs for obs in observations if obs["kind"] == "file" and obs["metadata"]["language"] in ("json", "xml")]
        self.assertEqual([obs["path"] for obs in feed_files],
                         ["atom.xml", "feed.json", "malformed-rss.xml", "rss.xml", "secret-feed.xml"])
        link_targets = {obs["target"] for obs in observations if obs["kind"] in ("feed.link", "feed.enclosure")}
        self.assertIn("external.url:https%3A%2F%2Fexample.com%2Frepomap%2Frss%2F1", link_targets)
        self.assertIn("file:media/rss-audio.mp3", link_targets)
        parse_errors = [obs for obs in observations if obs["kind"] == "feed.parse_error"]
        self.assertIn("xml-parse-error", {error["metadata"]["error_kind"] for error in parse_errors})

    def test_discover_command_emits_java_spring_maven_xml_observations(self):
        fixture = REPO_ROOT / "src" / "test" / "fixtures" / "discovery" / "xml_java_spring_maven_basic"
        stdout, observations = self._run_discover(fixture)
        for s in ("xml2-fixture-maven-secret", "xml2-fixture-spring-secret", "file:///etc/passwd"):
            self.assertNotIn(s, stdout)
        kinds = {obs["kind"] for obs in observations}
        self.assertTrue({"file", "xml.document", "xml.element", "xml.attribute", "xml.reference", "xml.parse_error"}.issubset(kinds))
        roles = {obs["metadata"].get("document_role") for obs in observations if obs["kind"] == "xml.document"}
        self.assertTrue({"maven-pom", "spring-config"}.issubset(roles))
        targets = {obs.get("target") for obs in observations if obs["kind"] == "xml.reference"}
        self.assertIn("external.url:https%3A%2F%2Fmaven.apache.org%2Fxsd%2Fmaven-4.0.0.xsd", targets)
        self.assertIn("file:src/main/resources/config/service.properties", targets)
        self.assertIn("env:DB_PASSWORD", targets)
        self.assertIn("dynamic:xml.property-placeholder:spring-maven-property", targets)
        parse_errors = [obs for obs in observations if obs["kind"] == "xml.parse_error"]
        self.assertEqual(parse_errors[0]["metadata"]["error_kind"], "unsafe-xml-construct")

    def test_discover_command_emits_codex_mcp_config_dogfood_observations(self):
        fixture = REPO_ROOT / "src" / "test" / "fixtures" / "discovery" / "config_codex_mcp_dogfood"
        stdout, observations = self._run_discover(fixture)
        for secret in ("cfg3-json-secret-token", "cfg3-json-secret-api-key", "cfg3-toml-secret-refresh-token",
                       "cfg3-toml-secret-api-key", "cfg3-jsonl-secret-token", "cfg3-jsonc-secret-password"):
            self.assertNotIn(secret, stdout)

        kinds = {obs["kind"] for obs in observations}
        self.assertTrue({"config.document", "config.path", "config.reference", "config.jsonl_record", "config.parse_error"}.issubset(kinds))
        file_languages = {obs["path"]: obs["metadata"]["language"] for obs in observations if obs["kind"] == "file"}
        self.assertEqual(file_languages, {
            "codex/config.toml": "toml", "editor/settings.jsonc": "jsonc",
            "logs/events.jsonl": "jsonl", "mcp/repo-map/config.json": "json",
        })
        document_targets = {obs["target"] for obs in observations if obs["kind"] == "config.document"}
        self.assertEqual(document_targets, {
            "config.document:file%3Acodex%2Fconfig.toml", "config.document:file%3Aeditor%2Fsettings.jsonc",
            "config.document:file%3Alogs%2Fevents.jsonl", "config.document:file%3Amcp%2Frepo-map%2Fconfig.json",
        })
        reference_targets = {obs["target"] for obs in observations if obs["kind"] == "config.reference"}
        self.assertTrue({
            "tool:repomap-kg", "tool:python3", "dynamic:tool:config-command-fragment", "env:REPOMAP_MCP_CONFIG",
            "env:CODEX_HOME", "env:TOKEN", "env:API_KEY", "env:PASSWORD", "file:codex/config.toml",
            "file:mcp/repo-map/config.json", "file:src/main/python", "file:projects/repo-map",
            "file:bin/repomap", "external.url:https%3A%2F%2Fexample.com%2Frepo-map",
            "external.url:https%3A%2F%2Fexample.com%2Feditor", "external.url:https%3A%2F%2Fexample.com%2Flog",
            "external.url:mailto%3Aops%40example.com", "external:file:absolute-config-reference",
            "unknown:file:repo-escaping-config-reference",
        }.issubset(reference_targets))

        path_metadata = {(obs["path"], obs["metadata"]["pointer"]): obs["metadata"] for obs in observations if obs["kind"] == "config.path"}
        self.assertTrue(path_metadata[("mcp/repo-map/config.json", "/api_key")]["redacted"])
        self.assertTrue(path_metadata[("codex/config.toml", "/profiles/default/refresh_token")]["redacted"])
        self.assertTrue(path_metadata[("editor/settings.jsonc", "/env/PASSWORD")]["redacted"])
        self.assertEqual(path_metadata[("codex/config.toml", "/tools")]["array_policy"], "stable-member-key")

        parse_errors = [obs for obs in observations if obs["kind"] == "config.parse_error"]
        self.assertEqual([(error["path"], error["metadata"]["error_kind"]) for error in parse_errors],
                         [("logs/events.jsonl", "malformed-jsonl-line")])
        jsonl_records = [obs for obs in observations if obs["kind"] == "config.jsonl_record"]
        self.assertEqual(len(jsonl_records), 3)

    def test_discover_command_handles_markdown_ambiguity_without_execution(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            fixture = Path(tmpdir) / "fixture-repo"
            self.write_fixture(
                fixture / "docs" / "guide.md",
                (
                    "---\ntitle: \"Guide\"\npublished: true\ndraft: false\ntags:\n  - docs\n"
                    "not yaml\nsecret_token: hidden\n---\n# Guide\n"
                    "See [same](#guide), [missing](missing.md), [template]({{ site.url }}/docs), and [bad](bad%zz).\n"
                    "```sh\necho \x27[not](executed.md)\x27\n"
                ),
            )
            self.write_fixture(fixture / "docs" / "skills" / "path-only" / "SKILL.md", "# Path Only\n")
            self.write_fixture(fixture / "docs" / "adr" / "0010-filename-title.md", "No heading here.\n")
            exit_code, stdout, stderr = self.run_module_entrypoint("discover", str(fixture), "--jsonl")

        observations = [json.loads(line) for line in stdout.splitlines()]
        guide_items = [item for item in observations if item["path"] == "docs/guide.md"]
        frontmatter = next(item for item in guide_items if item["kind"] == "markdown.frontmatter")
        fence = next(item for item in guide_items if item["kind"] == "markdown.code_fence")
        link_targets = {item.get("target") for item in guide_items if item["kind"] == "markdown.link"}
        skill = next(item for item in observations if item["kind"] == "markdown.skill_metadata")
        adr = next(item for item in observations if item["kind"] == "markdown.adr_metadata")

        self.assertEqual(exit_code, 0)
        self.assertEqual(stderr, "")
        self.assertEqual(frontmatter["metadata"]["parse_status"], "partial")
        self.assertIn("secret_token", frontmatter["metadata"]["redacted_keys"])
        self.assertFalse(fence["metadata"]["closed"])
        self.assertIn("doc.section:file%3Adocs%2Fguide.md:guide", link_targets)
        self.assertIn("unknown:doc.page:missing-markdown-link-target", link_targets)
        self.assertIn("dynamic:external.url:markdown-link-template", link_targets)
        self.assertIn("unknown:external.url:malformed-markdown-link", link_targets)
        self.assertEqual(skill["target"], "doc.skill:path-only")
        self.assertEqual(adr["metadata"]["metadata_source"], "filename")

from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile

from repomap_test_support.cli_integration import CliIntegrationTestCase

from repomap_kg.observations import RawObservation, write_observations_jsonl


class General1LanguageContractsIntegrationTests(CliIntegrationTestCase):
    """Subprocess contracts for graph-shaped observation normalization."""

    def _make_obs(
        self,
        kind: str,
        path: str,
        *,
        name: str | None = None,
        target: str | None = None,
        source_id: str | None = None,
        extractor: str = "test-extractor",
        confidence: str = "extracted",
        metadata: dict[str, object] | None = None,
    ) -> RawObservation:
        return RawObservation(
            kind=kind,
            source_id=source_id or f"{path}#{kind}:{name or 'item'}",
            path=path,
            name=name,
            target=target,
            confidence=confidence,
            extractor=extractor,
            extractor_version="1.0.0",
            metadata=metadata or {},
        )

    def test_cli_observations_normalize_ruby_and_javascript_subprocess_json_output(self) -> None:
        """JSON and text CLI views agree on normalized observations and evidence."""
        with tempfile.TemporaryDirectory() as tmpdir:
            jsonl_path = Path(tmpdir) / "observations.jsonl"
            observations = [
                self._make_obs("ruby.file", "lib/service.rb", name="lib/service.rb", extractor="ruby-extractor"),
                self._make_obs("ruby.module", "lib/service.rb", name="ServiceModule", target="ruby.module:ServiceModule", extractor="ruby-extractor"),
                self._make_obs("ruby.class", "lib/service.rb", name="ServiceRunner", target="ruby.class:ServiceRunner", extractor="ruby-extractor"),
                self._make_obs(
                    "ruby.method",
                    "lib/service.rb",
                    name="perform",
                    target="ruby.method:ServiceRunner:perform",
                    extractor="ruby-extractor",
                    metadata={"owner": "ServiceRunner", "owner_kind": "ruby.class"},
                ),
                self._make_obs(
                    "ruby.constant",
                    "lib/service.rb",
                    name="MAX_RETRIES",
                    target="ruby.constant:ServiceRunner:MAX_RETRIES",
                    extractor="ruby-extractor",
                    metadata={"owner": "ServiceRunner"},
                ),
                self._make_obs(
                    "ruby.route",
                    "config/routes.rb",
                    name="GET /api/v1",
                    target="ruby.route:file%3Aconfig%2Froutes.rb:%2Froutes%2Fapi%2Fv1",
                    extractor="ruby-extractor",
                    metadata={"route_pointer": "/routes/api/v1"},
                ),
                self._make_obs(
                    "ruby.reference",
                    "lib/service.rb",
                    name="util_ref",
                    target="file:lib/util.rb",
                    extractor="ruby-extractor",
                    metadata={"source_key": "ruby.class:ServiceRunner", "reference_kind": "require"},
                ),
                self._make_obs(
                    "ruby.parse_error",
                    "lib/service.rb",
                    confidence="heuristic",
                    extractor="ruby-extractor",
                    metadata={"error_kind": "dynamic-ruby-construct"},
                ),
                self._make_obs("js.file", "src/app.js", name="src/app.js", extractor="js-extractor"),
                self._make_obs("js.module", "src/app.js", name="src/app.js", target="js.module:file%3Asrc%2Fapp.js", extractor="js-extractor"),
                self._make_obs("js.class", "src/app.js", name="AppClient", target="js.class:file%3Asrc%2Fapp.js:AppClient", extractor="js-extractor"),
                self._make_obs("js.function", "src/app.js", name="bootstrap", target="js.function:file%3Asrc%2Fapp.js:bootstrap", extractor="js-extractor"),
                self._make_obs("js.component", "src/components/View.jsx", name="View", target="js.component:file%3Asrc%2Fcomponents%2FView.jsx:View", extractor="js-extractor"),
                self._make_obs(
                    "js.route",
                    "src/server.js",
                    name="/health",
                    target="js.route:file%3Asrc%2Fserver.js:%2Fhealth",
                    extractor="js-extractor",
                    metadata={"route_pointer": "/health"},
                ),
                self._make_obs(
                    "js.reference",
                    "src/app.js",
                    name="client_ref",
                    target="file:src/util.js",
                    extractor="js-extractor",
                    metadata={"source_key": "js.class:file%3Asrc%2Fapp.js:AppClient", "reference_kind": "import"},
                ),
                self._make_obs(
                    "js.framework_profile",
                    "src/app.js",
                    extractor="js-extractor",
                    metadata={"profile": "next"},
                ),
            ]
            write_observations_jsonl(observations, jsonl_path)

            exit_code, stdout, stderr = self.run_module_entrypoint(
                "observations", "normalize", str(jsonl_path), "--json"
            )

            self.assertEqual(exit_code, 0)
            self.assertEqual(stderr, "")
            payload = json.loads(stdout)
            summary = payload["summary"]
            self.assertEqual(summary["raw_observations"], 16)
            self.assertEqual(summary["evidence"], 16)
            self.assertGreater(summary["nodes"], 0)
            self.assertGreater(summary["edges"], 0)

            node_keys = {node["stable_key"] for node in payload["nodes"]}
            self.assertIn("node:lib/service.rb:ruby.class:lib/service.rb#ruby.class:ServiceRunner", node_keys)
            self.assertIn("node:src/app.js:js.function:src/app.js#js.function:bootstrap", node_keys)

            edge_targets = {edge["dst_node_key"] for edge in payload["edges"]}
            self.assertIn("file:lib/util.rb", edge_targets)
            self.assertIn("file:src/util.js", edge_targets)

            evidence_ids = {ev["metadata"].get("raw_source_id") for ev in payload["evidence"]}
            self.assertIn("lib/service.rb#ruby.parse_error:item", evidence_ids)
            self.assertIn("src/app.js#js.framework_profile:item", evidence_ids)

            exit_txt, stdout_txt, stderr_txt = self.run_module_entrypoint(
                "observations", "normalize", str(jsonl_path)
            )
            self.assertEqual(exit_txt, 0)
            self.assertEqual(stderr_txt, "")
            self.assertIn(
                f"normalized 16 observations into {summary['nodes']} nodes, {summary['edges']} edges, and 16 evidence records",
                stdout_txt,
            )

    def test_cli_observations_normalize_preserves_declared_redaction_metadata(self) -> None:
        """Normalization preserves redaction metadata supplied by extraction."""
        with tempfile.TemporaryDirectory() as tmpdir:
            jsonl_path = Path(tmpdir) / "redacted.jsonl"
            observations = [
                self._make_obs(
                    "ruby.file",
                    "Gemfile",
                    extractor="ruby-extractor",
                    metadata={
                        "source_url": "https://user:REDACTED@example.invalid:8443/gems?token=REDACTED",
                        "raw_query": "token%3DREDACTED",
                        "redacted": True,
                        "redaction_reason": "credential_sanitized",
                    },
                ),
                self._make_obs(
                    "js.reference",
                    "src/api.js",
                    target="file:src/env.js",
                    extractor="js-extractor",
                    metadata={
                        "token_spec": "token%3DREDACTED",
                        "redacted": True,
                        "redaction_reason": "auth_header_redacted",
                    },
                ),
            ]
            write_observations_jsonl(observations, jsonl_path)

            exit_code, stdout, stderr = self.run_module_entrypoint(
                "observations", "normalize", str(jsonl_path), "--json"
            )

            self.assertEqual(exit_code, 0)
            self.assertEqual(stderr, "")
            self.assertIn("token%3DREDACTED", stdout)
            self.assertIn("user:REDACTED", stdout)
            self.assertIn("credential_sanitized", stdout)
            self.assertIn("auth_header_redacted", stdout)

            payload = json.loads(stdout)
            self.assertTrue(all(node["metadata"]["redacted"] for node in payload["nodes"]))

    def test_cli_observations_normalize_duplicate_identity_replaces_graph_records(self) -> None:
        """Raw count retains duplicates while stable graph identities keep the last record."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            jsonl_path = root / "duplicates.jsonl"
            observations = [
                self._make_obs(
                    "ruby.reference", "lib/source.rb", name="before",
                    source_id="shared-reference", target="file:lib/target.rb",
                    extractor="ruby-extractor",
                    metadata={"revision": 1},
                ),
                self._make_obs(
                    "ruby.reference", "lib/source.rb", name="after",
                    source_id="shared-reference", target="file:lib/target.rb",
                    extractor="ruby-extractor", confidence="heuristic",
                    metadata={"revision": 2},
                ),
            ]
            write_observations_jsonl(observations, jsonl_path)

            exit_code, stdout, stderr = self.run_module_entrypoint(
                "observations", "normalize", str(jsonl_path), "--json"
            )

            self.assertEqual(exit_code, 0)
            self.assertEqual(stderr, "")
            payload = json.loads(stdout)
            self.assertEqual(payload["summary"], {
                "raw_observations": 2, "nodes": 1, "edges": 1, "evidence": 1,
            })
            self.assertEqual(payload["nodes"][0]["name"], "after")
            self.assertEqual(payload["nodes"][0]["metadata"], {"revision": 2})
            self.assertEqual(payload["edges"][0]["confidence"], "heuristic")
            self.assertEqual(payload["edges"][0]["evidence_key"], payload["evidence"][0]["stable_key"])

    def test_cli_observations_normalize_failure_exit_codes(self) -> None:
        """CLI observations normalize refuses a missing kind and an absent input file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            invalid_schema_path = Path(tmpdir) / "invalid_schema.jsonl"
            invalid_schema_path.write_text(
                json.dumps({
                    "source_id": "app.rb#file",
                    "path": "app.rb",
                    "confidence": "extracted",
                    "extractor": "ruby-extractor",
                    "extractor_version": "1.0.0",
                }) + "\n",
                encoding="utf-8",
            )

            exit_schema, stdout_schema, stderr_schema = self.run_module_entrypoint(
                "observations", "normalize", str(invalid_schema_path), "--json"
            )
            self.assertEqual(exit_schema, 1)
            self.assertEqual(stdout_schema, "")
            self.assertIn("kind is required", stderr_schema)

            nonexistent_path = Path(tmpdir) / "does_not_exist.jsonl"
            exit_missing, _, stderr_missing = self.run_module_entrypoint(
                "observations", "normalize", str(nonexistent_path), "--json"
            )
            self.assertNotEqual(exit_missing, 0)
            self.assertTrue(stderr_missing)


if __name__ == "__main__":
    sys.exit("Direct execution unsupported: use tools/run_tests.py --suite int with container sandbox admission.")

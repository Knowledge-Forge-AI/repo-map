"""Migrated Slice15 isolated regressions; no integration campaign credit."""

from __future__ import annotations
import ast
from pathlib import Path
import tempfile
import unittest
from repomap_kg.canonicalization.document_family import _document_definition
from repomap_kg.canonicalization.diagnostics import CanonicalizationDiagnostic
from repomap_kg.extractors.config.openapi_helpers import (
    _openapi_scope_names,
    _openapi_url_metadata,
)
from repomap_kg.extractors.languages.go_protocol import (
    GoDiagnostic,
    GoFileEnd,
    GoProtocolError,
    GoProtocolMessage,
    validate_go_protocol_message,
)
from repomap_kg.extractors.languages.python_web_helpers import (
    _expression_kind,
    _route_path_metadata,
)
from repomap_kg.observations.raw import RawObservation
from repomap_kg.runtime.plan import resolve_runtime_source_root


class Slice15LanguageCanonicalPipelineUnitTests(unittest.TestCase):
    def test_s15_a01_python_web_expression_kind_matrix(self) -> None:
        """_expression_kind classifies constants, collections, calls, names, and operations."""
        self.assertEqual(_expression_kind(None), "unknown")

        # Literal constants
        str_node = ast.parse("'hello'", mode="eval").body
        self.assertEqual(_expression_kind(str_node), "literal_string")

        bool_node = ast.parse("True", mode="eval").body
        self.assertEqual(_expression_kind(bool_node), "literal_bool")

        int_node = ast.parse("42", mode="eval").body
        self.assertEqual(_expression_kind(int_node), "literal_number")

        float_node = ast.parse("3.14", mode="eval").body
        self.assertEqual(_expression_kind(float_node), "literal_number")

        none_node = ast.parse("None", mode="eval").body
        self.assertEqual(_expression_kind(none_node), "literal_null")

        # Collection shapes
        list_node = ast.parse("[1, 2, 3]", mode="eval").body
        self.assertEqual(_expression_kind(list_node), "collection_shape")

        dict_node = ast.parse("{'a': 1}", mode="eval").body
        self.assertEqual(_expression_kind(dict_node), "collection_shape")

        tuple_node = ast.parse("(1, 2)", mode="eval").body
        self.assertEqual(_expression_kind(tuple_node), "collection_shape")

        set_node = ast.parse("{1, 2}", mode="eval").body
        self.assertEqual(_expression_kind(set_node), "collection_shape")

        # Functions, traversals, and dynamic binary operations
        call_node = ast.parse("calculate()", mode="eval").body
        self.assertEqual(_expression_kind(call_node), "function_call")

        name_node = ast.parse("variable_ref", mode="eval").body
        self.assertEqual(_expression_kind(name_node), "traversal_reference")

        attr_node = ast.parse("obj.attribute", mode="eval").body
        self.assertEqual(_expression_kind(attr_node), "traversal_reference")

        bin_node = ast.parse("a + b", mode="eval").body
        self.assertEqual(_expression_kind(bin_node), "dynamic_expression")

        # Fallback unknown AST expression
        if_node = ast.parse("x if True else y", mode="eval").body
        self.assertEqual(_expression_kind(if_node), "unknown")


    def test_s15_a02_python_web_route_path_metadata_and_redaction(self) -> None:
        """_route_path_metadata handles literals, credentialed URLs, regexes, and dynamic nodes."""
        # Literal string path
        lit_node = ast.parse("'/api/v1/users'", mode="eval").body
        lit_meta = _route_path_metadata(lit_node)
        self.assertEqual(lit_meta["route_path"], "/api/v1/users")
        self.assertEqual(lit_meta["route_path_kind"], "literal")
        self.assertFalse(lit_meta["dynamic"])

        # Credentialed URL is redacted
        cred_node = ast.parse(
            "'https://robot_admin:pass_secret_123@api.internal.corp/webhook'"
        , mode="eval").body
        cred_meta = _route_path_metadata(cred_node)
        self.assertEqual(cred_meta["route_path_kind"], "redacted")
        self.assertTrue(cred_meta["redacted"])
        self.assertFalse(cred_meta["dynamic"])
        self.assertNotIn("route_path", cred_meta)

        # Regex literal path
        regex_node = ast.parse("r'/items/(?P<item_id>[0-9]+)'", mode="eval").body
        regex_meta = _route_path_metadata(regex_node, regex=True)
        self.assertEqual(regex_meta["route_path_kind"], "regex_literal")
        self.assertEqual(regex_meta["route_path"], r"/items/(?P<item_id>[0-9]+)")
        self.assertFalse(regex_meta["dynamic"])

        # Dynamic non-literal expression
        dynamic_node = ast.parse("BASE_URL + '/endpoint'", mode="eval").body
        dyn_meta = _route_path_metadata(dynamic_node)
        self.assertEqual(dyn_meta["route_path_kind"], "dynamic")
        self.assertTrue(dyn_meta["dynamic"])

        # None node yields dynamic fallback
        none_meta = _route_path_metadata(None)
        self.assertEqual(none_meta["route_path_kind"], "dynamic")
        self.assertTrue(none_meta["dynamic"])


    def test_s15_a03_go_protocol_message_validation_matrix(self) -> None:
        """validate_go_protocol_message validates observations, diagnostics, and terminals."""
        # Valid observation message
        obs_payload = {
            "protocol_version": 1,
            "type": "observation",
            "sequence": 1,
            "path": "pkg/server/server.go",
            "observation": {
                "kind": "go.function",
                "source_id": "pkg/server/server.go#go.function:10:0",
                "path": "pkg/server/server.go",
                "name": "ServeHTTP",
                "confidence": "extracted",
                "extractor": "repo-go-ast",
                "extractor_version": "0.1.0",
                "metadata": {"exported": True},
            },
        }
        msg_obs = validate_go_protocol_message(
            obs_payload, expected_sequence=1, expected_path="pkg/server/server.go"
        )
        self.assertIsInstance(msg_obs, GoProtocolMessage)
        self.assertEqual(msg_obs.type, "observation")
        assert msg_obs.observation is not None
        self.assertEqual(msg_obs.observation.name, "ServeHTTP")

        # Valid diagnostic message
        diag_payload = {
            "protocol_version": 1,
            "type": "diagnostic",
            "sequence": 2,
            "path": "pkg/server/server.go",
            "severity": "warning",
            "code": "go-parse-error",
            "line": 42,
            "message": "expected declaration, found 'IDENT'",
        }
        msg_diag = validate_go_protocol_message(
            diag_payload, expected_sequence=2, expected_path="pkg/server/server.go"
        )
        self.assertEqual(msg_diag.type, "diagnostic")
        assert isinstance(msg_diag.diagnostic, GoDiagnostic)
        self.assertEqual(msg_diag.diagnostic.line, 42)

        # Valid file_end message
        end_payload = {
            "protocol_version": 1,
            "type": "file_end",
            "sequence": 3,
            "path": "pkg/server/server.go",
            "observation_count": 1,
            "diagnostic_count": 1,
            "truncated": False,
        }
        msg_end = validate_go_protocol_message(
            end_payload, expected_sequence=3, expected_path="pkg/server/server.go"
        )
        self.assertEqual(msg_end.type, "file_end")
        assert isinstance(msg_end.file_end, GoFileEnd)
        self.assertEqual(msg_end.file_end.observation_count, 1)

        # Violations: version mismatch, sequence mismatch, path mismatch
        with self.assertRaises(GoProtocolError) as cm_ver:
            validate_go_protocol_message(
                dict(obs_payload, protocol_version=2),
                expected_sequence=1,
                expected_path="pkg/server/server.go",
            )
        self.assertIn("protocol version mismatch", str(cm_ver.exception))

        with self.assertRaises(GoProtocolError) as cm_seq:
            validate_go_protocol_message(
                obs_payload, expected_sequence=99, expected_path="pkg/server/server.go"
            )
        self.assertIn("protocol sequence mismatch", str(cm_seq.exception))

        with self.assertRaises(GoProtocolError) as cm_path:
            validate_go_protocol_message(
                obs_payload, expected_sequence=1, expected_path="pkg/other/other.go"
            )
        self.assertIn("protocol path mismatch", str(cm_path.exception))


    def test_s15_a04_openapi_security_flow_scope_extraction(self) -> None:
        """_openapi_scope_names extracts flow scopes and filters sensitive keys and non-dict values."""
        # Non-dict flows
        self.assertEqual(_openapi_scope_names({}), [])
        self.assertEqual(_openapi_scope_names({"flows": "not-a-dict"}), [])

        # OAuth2 security scheme with multiple flows and sensitive scopes
        scheme = {
            "type": "oauth2",
            "flows": {
                "implicit": "invalid-flow-not-dict",
                "authorizationCode": {
                    "authorizationUrl": "https://auth.example.com/oauth/authorize",
                    "tokenUrl": "https://auth.example.com/oauth/token",
                    "scopes": {
                        "read:profile": "Read user profile",
                        "write:data": "Write user data",
                        "admin:secret_key_access": "Sensitive credential scope (filtered)",
                        "auth:jwt_token_inspect": "Sensitive auth token scope (filtered)",
                    },
                },
                "clientCredentials": {
                    "tokenUrl": "https://auth.example.com/oauth/token",
                    "scopes": {
                        "read:analytics": "Read application analytics",
                    },
                },
            },
        }
        scopes = _openapi_scope_names(scheme)
        self.assertIn("read:profile", scopes)
        self.assertIn("write:data", scopes)
        self.assertIn("read:analytics", scopes)
        self.assertNotIn("admin:secret_key_access", scopes)
        self.assertNotIn("auth:jwt_token_inspect", scopes)
        self.assertEqual(scopes, sorted(scopes))


    def test_s15_a05_openapi_url_metadata_extraction_and_credential_redaction(self) -> None:
        """_openapi_url_metadata parses URL parts and redacts credentialed authority."""
        # Non-string input
        self.assertEqual(_openapi_url_metadata(12345), {"url_present": False})
        self.assertEqual(_openapi_url_metadata(None), {"url_present": False})

        # Clean HTTPS URL
        clean_url = "https://developer.github.com/v3"
        clean_meta = _openapi_url_metadata(clean_url)
        self.assertTrue(clean_meta["url_present"])
        self.assertFalse(clean_meta["redacted"])
        self.assertEqual(clean_meta["scheme"], "https")
        self.assertEqual(clean_meta["host"], "developer.github.com")
        self.assertEqual(clean_meta["url_length"], len(clean_url))

        # Credentialed URL with username and password
        cred_url = "https://api_key_usr:super_token_999@internal.gateway.net/api"
        cred_meta = _openapi_url_metadata(cred_url)
        self.assertTrue(cred_meta["url_present"])
        self.assertTrue(cred_meta["redacted"])
        self.assertEqual(cred_meta["redaction_reason"], "credentialed-url")
        self.assertEqual(cred_meta["scheme"], "https")
        self.assertNotIn("host", cred_meta)


    def test_s15_a07_runtime_plan_source_root_resolution(self) -> None:
        """resolve_runtime_source_root finds repository root through parents and markers."""
        repo_root = resolve_runtime_source_root()
        self.assertTrue((repo_root / "pyproject.toml").is_file())
        self.assertTrue((repo_root / "README.md").is_file())
        self.assertTrue(
            (repo_root / "src" / "main" / "python" / "repomap_kg" / "__main__.py").is_file()
        )

        with tempfile.TemporaryDirectory() as tmp:
            isolated = Path(tmp) / "empty_dir"
            isolated.mkdir()
            # Resolving from an isolated directory walks upward and returns module-derived root
            resolved = resolve_runtime_source_root(start=isolated)
            self.assertTrue((resolved / "pyproject.toml").is_file())


    def test_s15_a08_document_definition_canonicalization(self) -> None:
        """_document_definition canonicalizes text and section document observations."""
        diagnostics: list[CanonicalizationDiagnostic] = []
        doc_obs = RawObservation(
            kind="document.text_document",
            source_id="docs/overview.md#text-doc:1",
            path="docs/overview.md",
            name="overview.md",
            confidence="extracted",
            extractor="test-document-extractor",
            extractor_version="1.0.0",
            metadata={"format": "markdown", "title": "System Overview"},
        )
        res_doc = _document_definition(doc_obs, ordinal=0, diagnostics=diagnostics)
        self.assertIn("nodes", res_doc)
        self.assertIn("edges", res_doc)
        self.assertEqual(len(res_doc["nodes"]), 2)
        self.assertEqual(len(res_doc["edges"]), 1)

        # Document text section with explicit pointer
        sec_obs = RawObservation(
            kind="document.text_section",
            source_id="docs/overview.md#text-sec:1",
            path="docs/overview.md",
            name="Architecture",
            confidence="extracted",
            extractor="test-document-extractor",
            extractor_version="1.0.0",
            metadata={
                "format": "markdown",
                "pointer": "/architecture",
                "heading_summary": "Architecture Overview",
            },
        )
        res_sec = _document_definition(sec_obs, ordinal=1, diagnostics=diagnostics)
        self.assertEqual(len(res_sec["nodes"]), 3)
        self.assertEqual(len(res_sec["edges"]), 2)

        # Section without pointer or name raises GraphKeyError
        bad_sec = RawObservation(
            kind="document.text_section",
            source_id="docs/bad.md#bad:1",
            path="docs/bad.md",
            name=None,
            confidence="extracted",
            extractor="test-extractor",
            extractor_version="1.0.0",
            metadata={},
        )
        from repomap_kg.graph.keys import GraphKeyError
        with self.assertRaises(GraphKeyError):
            _document_definition(bad_sec, ordinal=2, diagnostics=diagnostics)

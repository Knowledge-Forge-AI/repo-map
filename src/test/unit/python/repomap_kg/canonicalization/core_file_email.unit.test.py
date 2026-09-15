import unittest

from repomap_kg.canonicalization.dispatch import (
    CanonicalizationState,
    append_unsupported_observation_diagnostic,
    canonicalization_result_from_state,
)
from repomap_kg.canonicalization import (
    _display_name_from_key,
    _evidence_key,
    _node_kind_from_key,
    _stronger_confidence,
    _upsert_node,
    canonicalize_observations,
)
from repomap_kg.extractors.documents.email import (
    extract_eml_file_observations,
    extract_mbox_file_observations,
)
from repomap_kg.canonicalization.records import CanonicalNode
from repomap_kg.observations import RawObservation



class CanonicalizationCoreFileEmailUnitTests(unittest.TestCase):
    def test_canonicalization_facade_preserves_moved_core_helper_imports(self):
        observation = RawObservation(
            kind="file",
            source_id="README.md",
            path="README.md",
            start_line=3,
            end_line=5,
            confidence="heuristic",
            extractor="repo-discovery",
            extractor_version="0.1.0",
        )
        nodes: dict[str, CanonicalNode] = {}

        _upsert_node(
            nodes,
            canonical_key="file:README.md",
            kind="file",
            display_name="README.md",
            metadata={"language": "markdown"},
            confidence="heuristic",
        )
        _upsert_node(
            nodes,
            canonical_key="file:README.md",
            kind="file",
            display_name="README.md",
            metadata={"ignored": True},
            confidence="extracted",
        )

        self.assertEqual(
            _evidence_key(observation, 7),
            "evidence:7:README.md:3-5:repo-discovery:README.md",
        )
        self.assertEqual(_node_kind_from_key("file:README.md"), "file")
        self.assertEqual(_display_name_from_key("file:README.md"), "README.md")
        self.assertEqual(_stronger_confidence("heuristic", "extracted"), "extracted")
        self.assertEqual(nodes["file:README.md"].confidence, "extracted")
        self.assertEqual(nodes["file:README.md"].metadata, {"language": "markdown"})

    def test_canonical_dispatch_state_preserves_unsupported_diagnostic_result_shape(self):
        observation = RawObservation(
            kind="future.kind",
            source_id="future#1",
            path="future.txt",
            confidence="heuristic",
            extractor="fixture",
            extractor_version="0.1.0",
        )
        state = CanonicalizationState()

        append_unsupported_observation_diagnostic(
            state.diagnostics,
            observation,
            0,
        )
        result = canonicalization_result_from_state(state, raw_observation_count=1)
        payload = result.to_dict()

        self.assertTrue(result.ok)
        self.assertEqual(payload["summary"]["raw_observations"], 1)
        self.assertEqual(payload["summary"]["nodes"], 0)
        self.assertEqual(payload["summary"]["warnings"], 1)
        self.assertEqual(
            payload["diagnostics"][0]["category"],
            "unsupported_raw_observation_kind",
        )
        self.assertEqual(payload["diagnostics"][0]["field"], "kind")
        self.assertEqual(payload["diagnostics"][0]["value"], "future.kind")

    def test_file_observation_creates_canonical_file_node_and_evidence(self):
        observation = RawObservation(
            kind="file",
            source_id="README.md",
            path="README.md",
            confidence="extracted",
            extractor="repo-discovery",
            extractor_version="0.1.0",
            metadata={
                "language": "markdown",
                "role": "documentation",
                "content_hash": "sha256:abc123",
                "executable": False,
                "generated": False,
            },
        )

        result = canonicalize_observations([observation])
        payload = result.to_dict()

        self.assertTrue(result.ok)
        self.assertEqual(payload["summary"]["raw_observations"], 1)
        self.assertEqual(payload["summary"]["nodes"], 1)
        self.assertEqual(payload["summary"]["edges"], 0)
        self.assertEqual(payload["summary"]["evidence"], 1)
        self.assertEqual(payload["summary"]["node_evidence_links"], 1)
        self.assertEqual(payload["summary"]["edge_evidence_links"], 0)
        self.assertEqual(payload["diagnostics"], [])
        self.assertEqual(
            payload["nodes"],
            [
                {
                    "canonical_key": "file:README.md",
                    "graph_key_version": 1,
                    "kind": "file",
                    "display_name": "README.md",
                    "metadata": {
                        "content_hash": "sha256:abc123",
                        "executable": False,
                        "generated": False,
                        "language": "markdown",
                        "role": "documentation",
                    },
                    "confidence": "extracted",
                    "conflict": False,
                }
            ],
        )
        self.assertEqual(
            payload["evidence"],
            [
                {
                    "evidence_key": "evidence:0:README.md:0-0:repo-discovery:README.md",
                    "raw_observation_ordinal": 0,
                    "raw_schema_version": 1,
                    "raw_kind": "file",
                    "raw_source_id": "README.md",
                    "path": "README.md",
                    "start_line": None,
                    "end_line": None,
                    "extractor": "repo-discovery",
                    "extractor_version": "0.1.0",
                    "confidence": "extracted",
                    "metadata": {
                        "content_hash": "sha256:abc123",
                        "executable": False,
                        "generated": False,
                        "language": "markdown",
                        "role": "documentation",
                    },
                }
            ],
        )
        self.assertEqual(
            payload["node_evidence_links"],
            [
                {
                    "canonical_key": "file:README.md",
                    "evidence_key": "evidence:0:README.md:0-0:repo-discovery:README.md",
                    "link_kind": "observed",
                }
            ],
        )

    def test_email_observations_create_message_parts_addresses_and_thread_edges(self):
        observations = extract_eml_file_observations(
            "mail/thread-reply.eml",
            (
                b"Message-ID: <reply-message@example.invalid>\n"
                b"Date: Tue, 30 Jun 2026 13:00:00 +0000\n"
                b"From: Example Receiver <bob@example.invalid>\n"
                b"To: Example Sender <alice@example.invalid>\n"
                b"Subject: Re: private subject\n"
                b"In-Reply-To: <single-message@example.invalid>\n"
                b"References: <root-message@example.invalid> <single-message@example.invalid>\n"
                b"Content-Type: text/plain; charset=utf-8\n"
                b"\n"
                b"private body text must not leak\n"
            ),
        )

        result = canonicalize_observations(observations)
        payload = result.to_dict()
        nodes = {node["canonical_key"]: node for node in payload["nodes"]}
        edge_pairs = {
            (edge["source_key"], edge["kind"], edge["target_key"])
            for edge in payload["edges"]
        }
        serialized = result.to_json()
        message_key = next(key for key in nodes if key.startswith("email.message:"))
        address_keys = [key for key in nodes if key.startswith("email.address:")]
        part_keys = [key for key in nodes if key.startswith("email.part:")]
        hint_keys = [key for key in nodes if key.startswith("email.thread_hint:")]

        self.assertTrue(result.ok)
        self.assertIn(("file:mail/thread-reply.eml", "defines", message_key), edge_pairs)
        self.assertTrue(address_keys)
        self.assertTrue(part_keys)
        self.assertEqual(len(hint_keys), 3)
        self.assertTrue(
            any(
                source == message_key
                and kind == "references"
                and (
                    target.startswith("email.message:")
                    or target.startswith("unknown:email-message:")
                )
                for source, kind, target in edge_pairs
            )
        )
        self.assertNotIn("alice@example.invalid", serialized)
        self.assertNotIn("bob@example.invalid", serialized)
        self.assertNotIn("private subject", serialized)
        self.assertNotIn("private body text", serialized)

    def test_email_mbox_observations_create_mailbox_container_edges(self):
        observations = extract_mbox_file_observations(
            "mail/sample.mbox",
            (
                b"From MAILER-DAEMON Tue Jun 30 12:00:00 2026\n"
                b"Message-ID: <mbox-one@example.invalid>\n"
                b"Date: Tue, 30 Jun 2026 12:00:00 +0000\n"
                b"From: Example Sender <alice@example.invalid>\n"
                b"To: Example Receiver <bob@example.invalid>\n"
                b"Subject: MBOX private subject\n"
                b"Content-Type: text/plain; charset=utf-8\n"
                b"\n"
                b"MBOX body text must not leak.\n"
                b"From MAILER-DAEMON Tue Jun 30 12:05:00 2026\n"
                b"Message-ID: <mbox-two@example.invalid>\n"
                b"Date: Tue, 30 Jun 2026 12:05:00 +0000\n"
                b"From: Example Receiver <bob@example.invalid>\n"
                b"To: Example Sender <alice@example.invalid>\n"
                b"Subject: Re: MBOX private subject\n"
                b"In-Reply-To: <mbox-one@example.invalid>\n"
                b"References: <mbox-one@example.invalid>\n"
                b"Content-Type: text/plain; charset=utf-8\n"
                b"\n"
                b"Reply body text must not leak.\n"
            ),
        )

        result = canonicalize_observations(observations)
        payload = result.to_dict()
        nodes = {node["canonical_key"]: node for node in payload["nodes"]}
        edge_pairs = {
            (edge["source_key"], edge["kind"], edge["target_key"])
            for edge in payload["edges"]
        }
        serialized = result.to_json()
        mailbox_key = next(key for key in nodes if key.startswith("email.mailbox:"))
        message_keys = [key for key in nodes if key.startswith("email.message:")]

        self.assertTrue(result.ok)
        self.assertIn(("file:mail/sample.mbox", "defines", mailbox_key), edge_pairs)
        self.assertGreaterEqual(len(message_keys), 2)
        self.assertTrue(
            all((mailbox_key, "defines", message_key) in edge_pairs for message_key in message_keys)
        )
        self.assertNotIn("alice@example.invalid", serialized)
        self.assertNotIn("bob@example.invalid", serialized)
        self.assertNotIn("MBOX private subject", serialized)
        self.assertNotIn("MBOX body text", serialized)

    def test_file_observations_with_multiple_roles_merge_without_conflict(self):
        observations = [
            RawObservation(
                kind="file",
                source_id="bin/tool:first",
                path="bin/tool",
                confidence="heuristic",
                extractor="repo-discovery",
                extractor_version="0.1.0",
                metadata={
                    "language": "shell",
                    "role": "entrypoint",
                    "content_hash": "sha256:same",
                    "executable": True,
                    "generated": False,
                },
            ),
            RawObservation(
                kind="file",
                source_id="bin/tool:second",
                path="bin/tool",
                confidence="heuristic",
                extractor="repo-discovery",
                extractor_version="0.1.0",
                metadata={
                    "language": "shell",
                    "role": "script",
                    "content_hash": "sha256:same",
                    "executable": True,
                    "generated": False,
                },
            ),
        ]

        result = canonicalize_observations(observations)
        payload = result.to_dict()

        self.assertTrue(result.ok)
        self.assertEqual(payload["diagnostics"], [])
        self.assertFalse(payload["nodes"][0]["conflict"])
        self.assertEqual(
            payload["nodes"][0]["metadata"]["role"], ["entrypoint", "script"]
        )

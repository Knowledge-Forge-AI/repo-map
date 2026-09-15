import unittest


from repomap_kg.canonicalization import canonicalize_observations
from repomap_kg.extractors.documents.email import (
    MAX_EML_BYTES,
    MAX_HEADER_BYTES,
    MAX_MIME_PARTS,
    extract_eml_file_observations,
    extract_mbox_file_observations,
)
from repomap_kg.graph.keys import (
    email_message_key,
)
from repomap_kg.observations import RawObservation

class CanonicalEmailIntegrationTests(unittest.TestCase):
    def test_static_eml_extraction_and_canonicalization_contract(self):
        observations: list[RawObservation] = []
        observations.extend(
            extract_eml_file_observations(
                "reply.eml",
                (
                    "Message-ID: <reply@example.invalid>\n"
                    "Date: Fri, 02 Jan 2026 03:04:05 +0000\n"
                    "From: Alice Person <alice@example.invalid>\n"
                    "To: Bob Person <bob@example.invalid>\n"
                    "Cc: Team Person <team@example.invalid>\n"
                    "Reply-To: Replies Person <replies@example.invalid>\n"
                    "Sender: Sender Person <sender@example.invalid>\n"
                    "Return-Path: <bounce@example.invalid>\n"
                    "Subject: Quarterly planning code fake-mail-token\n"
                    "In-Reply-To: <root@example.invalid>\n"
                    "References: <root@example.invalid> <prior@example.invalid>\n"
                    "List-Id: <updates.example.invalid>\n"
                    "List-Unsubscribe: <https://example.invalid/unsub?token=fake-mail-token&ok=1>\n"
                    "MIME-Version: 1.0\n"
                    "Content-Type: text/plain; charset=utf-8\n"
                    "\n"
                    "Fixture body fake-mail-token should not be serialized.\n"
                ).encode("utf-8"),
            )
        )
        observations.extend(
            extract_eml_file_observations(
                "multipart.eml",
                (
                    "Message-ID: <multipart@example.invalid>\n"
                    "Date: Fri, 02 Jan 2026 04:04:05 +0000\n"
                    "From: Alice Person <alice@example.invalid>\n"
                    "To: Bob Person <bob@example.invalid>\n"
                    "Subject: Attachment invoice-secret-code.txt\n"
                    "MIME-Version: 1.0\n"
                    "Content-Type: multipart/mixed; boundary=\"outer\"\n"
                    "\n"
                    "--outer\n"
                    "Content-Type: text/html; charset=utf-8\n"
                    "\n"
                    "<html><script>evil()</script><body>HTML body secret</body></html>\n"
                    "--outer\n"
                    "Content-Type: image/png\n"
                    "Content-Disposition: attachment; filename=\"invoice-secret-code.txt\"\n"
                    "Content-ID: <image-1@example.invalid>\n"
                    "\n"
                    "not-real-image-bytes\n"
                    "--outer--\n"
                ).encode("utf-8"),
            )
        )
        observations.extend(
            extract_eml_file_observations(
                "fallback.eml",
                (
                    "Message-ID: not-a-valid-message-id\n"
                    "Date: not-a-real-date\n"
                    "From: No Name <missing@example.invalid>\n"
                    "Subject: Reset code fake-mail-reset-code\n"
                    "Content-Type: text/plain\n"
                    "\n"
                    "Fallback identity body should not leak.\n"
                ).encode("utf-8"),
            )
        )
        observations.extend(
            extract_eml_file_observations(
                "header-limit.eml",
                (
                    "Message-ID: <header-limit@example.invalid>\n"
                    f"X-Long: {'x' * (MAX_HEADER_BYTES + 1)}\n"
                    "Content-Type: text/plain\n"
                    "\n"
                    "Header limit body should not leak.\n"
                ).encode("utf-8"),
            )
        )
        many_parts = [
            "Message-ID: <many-parts@example.invalid>\n",
            "MIME-Version: 1.0\n",
            "Content-Type: multipart/mixed; boundary=\"many\"\n",
            "\n",
        ]
        for index in range(MAX_MIME_PARTS + 2):
            many_parts.extend(
                (
                    "--many\n",
                    "Content-Type: text/plain\n",
                    "\n",
                    f"Part {index} body should not leak.\n",
                )
            )
        many_parts.append("--many--\n")
        observations.extend(
            extract_eml_file_observations(
                "many-parts.eml",
                "".join(many_parts).encode("utf-8"),
            )
        )
        observations.extend(
            extract_eml_file_observations(
                "filename-and-mailto.eml",
                (
                    "Message-ID: <filename-mailto@example.invalid>\n"
                    "List-Unsubscribe: <mailto:unsubscribe@example.invalid>\n"
                    "MIME-Version: 1.0\n"
                    "Content-Type: multipart/mixed; boundary=\"files\"\n"
                    "\n"
                    "--files\n"
                    "Content-Type: application/octet-stream\n"
                    "Content-Disposition: attachment; filename=\"SECRETFILE\"\n"
                    "\n"
                    "attachment bytes should not leak\n"
                    "--files--\n"
                ).encode("utf-8"),
            )
        )
        observations.extend(
            extract_eml_file_observations(
                "defect.eml",
                b"Bad header\n\nParser defect body should not leak.\n",
            )
        )
        observations.extend(
            extract_eml_file_observations(
                "large.eml",
                b"x" * (MAX_EML_BYTES + 1),
            )
        )

        result = canonicalize_observations(observations)
        kinds = {observation.kind for observation in observations}
        parse_error_kinds = {
            observation.metadata.get("error_kind")
            for observation in observations
            if observation.kind == "email.parse_error"
        }
        reference_targets = {
            observation.target
            for observation in observations
            if observation.kind == "email.reference" and observation.target is not None
        }
        node_kinds = {node.kind for node in result.graph.nodes}
        edge_kinds = {edge.kind for edge in result.graph.edges}
        payload = "\n".join(observation.to_json_line() for observation in observations)
        payload += result.to_json()

        self.assertIn("email.message", kinds)
        self.assertIn("email.header", kinds)
        self.assertIn("email.address", kinds)
        self.assertIn("email.part", kinds)
        self.assertIn("email.attachment_stub", kinds)
        self.assertIn("email.thread_hint", kinds)
        self.assertIn("email.reference", kinds)
        self.assertIn("missing-or-invalid-message-id", parse_error_kinds)
        self.assertIn("header-size-limit", parse_error_kinds)
        self.assertIn("mime-part-count-limit", parse_error_kinds)
        self.assertIn("parser-defect", parse_error_kinds)
        self.assertIn("file-size-limit", parse_error_kinds)
        self.assertTrue(
            any(target.startswith("unknown:email-message:") for target in reference_targets)
        )
        self.assertIn(
            "external.url:https%3A%2F%2Fexample.invalid%2Funsub%3Ftoken%3DREDACTED%26ok%3D1",
            reference_targets,
        )
        self.assertIn("email.message", node_kinds)
        self.assertIn("email.address", node_kinds)
        self.assertIn("email.part", node_kinds)
        self.assertIn("email.attachment_stub", node_kinds)
        self.assertIn("email.thread_hint", node_kinds)
        self.assertIn("defines", edge_kinds)
        self.assertIn("references", edge_kinds)
        self.assertNotIn("alice@example.invalid", payload)
        self.assertNotIn("bob@example.invalid", payload)
        self.assertNotIn("Alice Person", payload)
        self.assertNotIn("Bob Person", payload)
        self.assertNotIn("Quarterly planning code", payload)
        self.assertNotIn("Fixture body", payload)
        self.assertNotIn("HTML body secret", payload)
        self.assertNotIn("evil()", payload)
        self.assertNotIn("invoice-secret-code.txt", payload)
        self.assertNotIn("SECRETFILE", payload)
        self.assertNotIn("Header limit body", payload)
        self.assertNotIn("Parser defect body", payload)
        self.assertNotIn("unsubscribe@example.invalid", payload)
        self.assertNotIn("fake-mail-token", payload)
        self.assertNotIn("fake-mail-reset-code", payload)

    def test_static_mbox_extraction_and_canonicalization_contract(self):
        observations: list[RawObservation] = []
        observations.extend(
            extract_mbox_file_observations(
                "mailbox.mbox",
                (
                    b"From MAILER-DAEMON Tue Jun 30 12:00:00 2026\n"
                    b"Message-ID: <mbox-contract-one@example.invalid>\n"
                    b"Date: Tue, 30 Jun 2026 12:00:00 +0000\n"
                    b"From: Alice Person <alice@example.invalid>\n"
                    b"To: Bob Person <bob@example.invalid>\n"
                    b"Subject: MBOX contract private subject fake-mail-token\n"
                    b"List-Unsubscribe: <https://example.invalid/unsub?token=fake-mail-token>\n"
                    b"Content-Type: text/plain; charset=utf-8\n"
                    b"\n"
                    b"MBOX contract body fake-mail-token must not leak.\n"
                    b"From MAILER-DAEMON Tue Jun 30 12:05:00 2026\n"
                    b"Message-ID: <mbox-contract-two@example.invalid>\n"
                    b"Date: Tue, 30 Jun 2026 12:05:00 +0000\n"
                    b"From: Bob Person <bob@example.invalid>\n"
                    b"To: Alice Person <alice@example.invalid>\n"
                    b"Subject: Re: MBOX contract private subject\n"
                    b"In-Reply-To: <mbox-contract-one@example.invalid>\n"
                    b"References: <mbox-contract-one@example.invalid>\n"
                    b"MIME-Version: 1.0\n"
                    b"Content-Type: multipart/mixed; boundary=\"contract\"\n"
                    b"\n"
                    b"--contract\n"
                    b"Content-Type: text/plain; charset=utf-8\n"
                    b"\n"
                    b"MBOX reply body must not leak.\n"
                    b"--contract\n"
                    b"Content-Type: text/plain\n"
                    b"Content-Disposition: attachment; filename=\"contract-secret-note.txt\"\n"
                    b"\n"
                    b"MBOX attachment body must not leak.\n"
                    b"--contract--\n"
                ),
            )
        )
        observations.extend(
            extract_mbox_file_observations(
                "limited.mbox",
                (
                    b"From MAILER-DAEMON Tue Jun 30 12:00:00 2026\n"
                    b"Message-ID: <limited-one@example.invalid>\n\nbody\n"
                    b"From MAILER-DAEMON Tue Jun 30 12:01:00 2026\n"
                    b"Message-ID: <limited-two@example.invalid>\n\nbody\n"
                ),
                max_messages=1,
            )
        )
        observations.extend(
            extract_mbox_file_observations(
                "malformed.mbox",
                b"Message-ID: <not-mbox@example.invalid>\n\nbody\n",
            )
        )
        observations.extend(
            extract_mbox_file_observations(
                "message-limit.mbox",
                (
                    b"From MAILER-DAEMON Tue Jun 30 12:00:00 2026\n"
                    b"Message-ID: <message-limit@example.invalid>\n\nbody\n"
                ),
                max_message_bytes=10,
            )
        )

        result = canonicalize_observations(observations)
        payload = result.to_dict()
        serialized = result.to_json()
        node_kinds = {node["kind"] for node in payload["nodes"]}
        edge_pairs = {
            (edge["source_key"], edge["kind"], edge["target_key"])
            for edge in payload["edges"]
        }
        mailbox_key = next(
            node["canonical_key"]
            for node in payload["nodes"]
            if node["kind"] == "email.mailbox"
            and node["canonical_key"] == "email.mailbox:file%3Amailbox.mbox"
        )
        message_keys = [
            node["canonical_key"]
            for node in payload["nodes"]
            if node["kind"] == "email.message"
            and node["metadata"].get("format") == "mbox"
        ]
        parse_error_kinds = {
            item.metadata["error_kind"]
            for item in observations
            if item.kind == "email.parse_error"
        }

        self.assertTrue(result.ok)
        self.assertIn("email.mailbox", node_kinds)
        self.assertIn("email.message", node_kinds)
        self.assertIn("email.attachment_stub", node_kinds)
        self.assertIn("email.thread_hint", node_kinds)
        self.assertIn(("file:mailbox.mbox", "defines", mailbox_key), edge_pairs)
        self.assertTrue(
            any((mailbox_key, "defines", message_key) in edge_pairs for message_key in message_keys)
        )
        self.assertIn("mbox-message-count-limit", parse_error_kinds)
        self.assertIn("mbox-missing-from-separator", parse_error_kinds)
        self.assertIn("mbox-message-size-limit", parse_error_kinds)
        self.assertNotIn("alice@example.invalid", serialized)
        self.assertNotIn("bob@example.invalid", serialized)
        self.assertNotIn("MBOX contract private subject", serialized)
        self.assertNotIn("MBOX contract body", serialized)
        self.assertNotIn("contract-secret-note.txt", serialized)
        self.assertNotIn("fake-mail-token", serialized)

    def test_email_canonicalization_diagnostic_contracts(self):
        message_hash = "a" * 64
        address_hash = "b" * 64
        message_key = email_message_key("diag.eml", f"structural:{message_hash}")
        def _diag_obs(
            kind: str,
            sid: str,
            meta: dict[str, str],
            target: str | None = None,
        ) -> RawObservation:
            return RawObservation(
                kind=kind,
                source_id=sid,
                path="diag.eml",
                confidence="extracted",
                extractor="repo-email",
                extractor_version="0.1.0",
                target=target,
                metadata={"format": "eml", **meta},
            )

        result = canonicalize_observations(
            [
                _diag_obs("email.message", "diag.eml#email-message", {"message_id_hash": message_hash, "identity_strength": "structural"}),
                _diag_obs("email.part", "diag.eml#email-part:1", {"source_key": message_key, "part_path": "/parts/1", "content_type": "text/plain"}),
                _diag_obs("email.attachment_stub", "diag.eml#email-attachment:1", {"source_key": message_key, "part_path": "/parts/2", "attachment_mime_type": "text/plain"}),
                _diag_obs("email.thread_hint", "diag.eml#email-thread-hint:1", {"source_key": message_key, "part_path": "/thread/in-reply-to/1", "thread_hint_kind": "in_reply_to"}),
                _diag_obs("email.address", "diag.eml#email-address:from", {"source_key": message_key, "address_hash": address_hash, "address_role": "from"}),
                _diag_obs("email.reference", "diag.eml#email-reference:missing", {"source_key": message_key, "reference_kind": "missing-target"}),
                _diag_obs("email.reference", "diag.eml#email-reference:malformed", {"source_key": message_key, "reference_kind": "malformed-target"}, target="not-a-canonical-key"),
                _diag_obs("email.part", "diag.eml#email-part:missing-source", {"part_path": "/parts/bad"}),
                _diag_obs("email.part", "diag.eml#email-part:bad-target", {"source_key": message_key}, target="file:diag.eml"),
                _diag_obs("email.address", "diag.eml#email-address:bad-target", {"source_key": message_key, "address_hash": address_hash}, target="file:diag.eml"),
                _diag_obs("email.reference", "diag.eml#email-reference:bad-source", {"source_key": "file:diag.eml"}, target="unknown:email-message:missing"),
            ]
        )

        categories = {diagnostic.category for diagnostic in result.diagnostics}
        messages = {diagnostic.message for diagnostic in result.diagnostics}
        node_kinds = {node.kind for node in result.graph.nodes}
        placeholder_targets = {
            edge.target_key
            for edge in result.graph.edges
            if edge.target_key.startswith("unknown:email.reference:")
        }

        self.assertFalse(result.ok)
        self.assertIn("email.message", node_kinds)
        self.assertIn("email.part", node_kinds)
        self.assertIn("email.attachment_stub", node_kinds)
        self.assertIn("email.thread_hint", node_kinds)
        self.assertIn("email.address", node_kinds)
        self.assertIn("missing_required_metadata", categories)
        self.assertIn("invalid_canonical_key", categories)
        self.assertIn("email.reference observation requires target", messages)
        self.assertIn("email.part observation requires source_key", messages)
        self.assertIn("email.part target has unsupported namespace", messages)
        self.assertIn("email.address target must be email.address", messages)
        self.assertIn("email.reference source_key has unsupported namespace", messages)
        self.assertIn("unknown:email.reference:missing-target", placeholder_targets)
        self.assertIn("unknown:email.reference:malformed-target", placeholder_targets)

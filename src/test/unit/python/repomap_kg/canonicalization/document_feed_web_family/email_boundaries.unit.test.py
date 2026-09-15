import unittest

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from repomap_kg.canonicalization.main import canonicalize_observations
    from repomap_kg.observations.raw import RawObservation
else:
    from repomap_kg.canonicalization import canonicalize_observations
    from repomap_kg.observations import RawObservation
from repomap_kg.canonicalization.email_family import (
    _email_address_target_key,
    _email_definition_source_key,
    _email_definition_target_key,
    _email_reference_source_key,
)
from repomap_kg.graph.keys import GraphKeyError


class CanonicalizationEmailBoundaryUnitTests(unittest.TestCase):
    def test_email_canonicalization_valid_definitions_and_references(self):
        observations = [
            RawObservation(
                kind="email.mailbox",
                source_id="mail/inbox.mbox#mailbox",
                path="mail/inbox.mbox",
                confidence="extracted",
                extractor="repo-email",
                extractor_version="0.1.0",
                metadata={"format": "mbox", "message_count": 1},
            ),
            RawObservation(
                kind="email.message",
                source_id="mail/inbox.mbox#msg:1",
                path="mail/inbox.mbox",
                confidence="extracted",
                extractor="repo-email",
                extractor_version="0.1.0",
                metadata={
                    "format": "mbox",
                    "source_key": "email.mailbox:file%3Amail%2Finbox.mbox",
                    "message_id_hash": "hash123",
                    "identity_strength": "strong",
                },
            ),
            RawObservation(
                kind="email.part",
                source_id="mail/inbox.mbox#msg:1/part:1",
                path="mail/inbox.mbox",
                confidence="extracted",
                extractor="repo-email",
                extractor_version="0.1.0",
                metadata={
                    "format": "mbox",
                    "source_key": "email.message:file%3Amail%2Finbox.mbox:strong%3Ahash123",
                    "part_path": "/1",
                    "mime_type": "text/plain",
                },
            ),
            RawObservation(
                kind="email.attachment_stub",
                source_id="mail/inbox.mbox#msg:1/att:1",
                path="mail/inbox.mbox",
                confidence="extracted",
                extractor="repo-email",
                extractor_version="0.1.0",
                metadata={
                    "format": "mbox",
                    "source_key": "email.message:file%3Amail%2Finbox.mbox:strong%3Ahash123",
                    "part_path": "/2",
                    "filename": "file.pdf",
                },
            ),
            RawObservation(
                kind="email.thread_hint",
                source_id="mail/inbox.mbox#msg:1/hint:1",
                path="mail/inbox.mbox",
                confidence="extracted",
                extractor="repo-email",
                extractor_version="0.1.0",
                metadata={
                    "format": "mbox",
                    "source_key": "email.message:file%3Amail%2Finbox.mbox:strong%3Ahash123",
                    "part_path": "/hint:1",
                    "thread_hint_kind": "in-reply-to",
                    "referenced_message_id_hash": "parent_hash",
                },
            ),
            RawObservation(
                kind="email.address",
                source_id="mail/inbox.mbox#msg:1/addr:1",
                path="mail/inbox.mbox",
                confidence="extracted",
                extractor="repo-email",
                extractor_version="0.1.0",
                metadata={
                    "format": "mbox",
                    "source_key": "email.message:file%3Amail%2Finbox.mbox:strong%3Ahash123",
                    "address_hash": "addrhash123",
                    "address_role": "from",
                },
            ),
            RawObservation(
                kind="email.reference",
                source_id="mail/inbox.mbox#msg:1/ref:1",
                path="mail/inbox.mbox",
                target="file:docs/attachment.pdf",
                confidence="extracted",
                extractor="repo-email",
                extractor_version="0.1.0",
                metadata={
                    "format": "mbox",
                    "source_key": "email.message:file%3Amail%2Finbox.mbox:strong%3Ahash123",
                },
            ),
        ]
        result = canonicalize_observations(observations)
        payload = result.to_dict()
        self.assertTrue(payload["ok"])

    def test_email_canonicalization_key_rejections(self):
        # Invalid source key namespace for message
        with self.assertRaises(GraphKeyError):
            _email_definition_source_key(
                RawObservation(
                    kind="email.message",
                    source_id="m1",
                    path="mail.eml",
                    confidence="extracted",
                    extractor="repo-email",
                    extractor_version="0.1.0",
                    metadata={"source_key": "file:mail.eml"},
                )
            )

        # Missing source key for part
        with self.assertRaises(GraphKeyError):
            _email_definition_source_key(
                RawObservation(
                    kind="email.part",
                    source_id="p1",
                    path="mail.eml",
                    confidence="extracted",
                    extractor="repo-email",
                    extractor_version="0.1.0",
                    metadata={},
                )
            )

        # Invalid source key namespace for part
        with self.assertRaises(GraphKeyError):
            _email_definition_source_key(
                RawObservation(
                    kind="email.part",
                    source_id="p1",
                    path="mail.eml",
                    confidence="extracted",
                    extractor="repo-email",
                    extractor_version="0.1.0",
                    metadata={"source_key": "email.mailbox:file%3Amail.mbox"},
                )
            )

        # Target with unsupported namespace
        with self.assertRaises(GraphKeyError):
            _email_definition_target_key(
                RawObservation(
                    kind="email.part",
                    source_id="p1",
                    path="mail.eml",
                    target="file:wrong.txt",
                    confidence="extracted",
                    extractor="repo-email",
                    extractor_version="0.1.0",
                    metadata={},
                )
            )

        # Unsupported definition kind
        with self.assertRaises(GraphKeyError):
            _email_definition_target_key(
                RawObservation(
                    kind="email.unsupported",
                    source_id="u1",
                    path="mail.eml",
                    confidence="extracted",
                    extractor="repo-email",
                    extractor_version="0.1.0",
                    metadata={"source_key": "email.message:file%3Am:s%3Ah", "part_path": "/1"},
                )
            )

        # Address with invalid target namespace
        with self.assertRaises(GraphKeyError):
            _email_address_target_key(
                RawObservation(
                    kind="email.address",
                    source_id="a1",
                    path="mail.eml",
                    target="file:not-address",
                    confidence="extracted",
                    extractor="repo-email",
                    extractor_version="0.1.0",
                    metadata={},
                )
            )

        # Address missing address_hash when target is None
        with self.assertRaises(GraphKeyError):
            _email_address_target_key(
                RawObservation(
                    kind="email.address",
                    source_id="a1",
                    path="mail.eml",
                    confidence="extracted",
                    extractor="repo-email",
                    extractor_version="0.1.0",
                    metadata={},
                )
            )

        # Reference missing source_key
        with self.assertRaises(GraphKeyError):
            _email_reference_source_key(
                RawObservation(
                    kind="email.reference",
                    source_id="r1",
                    path="mail.eml",
                    confidence="extracted",
                    extractor="repo-email",
                    extractor_version="0.1.0",
                    metadata={},
                )
            )

        # Reference with invalid source_key namespace
        with self.assertRaises(GraphKeyError):
            _email_reference_source_key(
                RawObservation(
                    kind="email.reference",
                    source_id="r1",
                    path="mail.eml",
                    confidence="extracted",
                    extractor="repo-email",
                    extractor_version="0.1.0",
                    metadata={"source_key": "file:mail.eml"},
                )
            )


if __name__ == "__main__":
    unittest.main()

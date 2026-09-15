import unittest

from repomap_test_support.policy_observations import (
    raw_observation,
)

from repomap_kg.canonicalization import main as canon
from repomap_kg.canonicalization.diagnostics import CanonicalizationDiagnostic
from repomap_kg.graph.keys import GraphKeyError


class CanonicalizationHelperBranchUnitTests(unittest.TestCase):
    def test_canonicalization_key_helpers_cover_language_edge_branches(self):
        diagnostics: list[CanonicalizationDiagnostic] = []

        python_module = raw_observation(
            "python.module",
            path="src/pkg/mod.py",
            name=None,
            metadata={"module": "pkg.mod"},
        )
        self.assertEqual(canon._python_definition_target(python_module)[1], "pkg.mod")
        self.assertEqual(
            canon._python_definition_target(
                raw_observation(
                    "python.class",
                    path="src/pkg/mod.py",
                    name="Service",
                    metadata={"module": "pkg.mod"},
                )
            )[1],
            "Service",
        )
        self.assertEqual(
            canon._python_definition_target(
                raw_observation(
                    "python.method",
                    path="src/pkg/mod.py",
                    name="run",
                    metadata={"module": "pkg.mod", "class": "Service"},
                )
            )[1],
            "Service.run",
        )
        for observation in (
            raw_observation("python.module", name=""),
            raw_observation("python.function", name="run", metadata={}),
            raw_observation("python.method", name="run", metadata={"module": "pkg.mod"}),
        ):
            with self.subTest(kind=observation.kind, metadata=observation.metadata):
                with self.assertRaises(GraphKeyError):
                    canon._python_definition_target(observation)

        ruby_file = raw_observation("ruby.file", path="app/models/user.rb")
        self.assertEqual(canon._ruby_definition_source_key(ruby_file), "file:app/models/user.rb")
        self.assertEqual(
            canon._ruby_definition_source_key(
                raw_observation("ruby.class", metadata={"source_key": "ruby.module:Admin"})
            ),
            "ruby.module:Admin",
        )
        self.assertEqual(
            canon._ruby_definition_source_key(
                raw_observation(
                    "ruby.test_method",
                    metadata={
                        "test_case_key": canon.ruby_test_case_key(
                            "spec/user_spec.rb",
                            "/User",
                        )
                    },
                )
            ),
            canon.ruby_test_case_key("spec/user_spec.rb", "/User"),
        )
        for observation in (
            raw_observation("ruby.class", metadata={"source_key": "python.module:bad"}),
            raw_observation("ruby.test_method", metadata={}),
            raw_observation("ruby.method", name="run", metadata={}),
            raw_observation("ruby.constant", name="NAME", metadata={"owner": "User", "owner_kind": "bad"}),
        ):
            with self.subTest(kind=observation.kind, metadata=observation.metadata):
                with self.assertRaises(GraphKeyError):
                    canon._ruby_definition_source_key(observation)

        ruby_targets = (
            raw_observation("ruby.file", path="app.rb", name="ignored"),
            raw_observation("ruby.module", name="Admin"),
            raw_observation("ruby.class", name="Admin::User"),
            raw_observation("ruby.method", name="save", metadata={"owner": "User"}),
            raw_observation("ruby.singleton_method", name="build", metadata={"owner": "User"}),
            raw_observation("ruby.constant", name="NAME", metadata={"owner": "User"}),
            raw_observation("ruby.test_case", path="spec/user_spec.rb", name="User spec"),
            raw_observation(
                "ruby.test_method",
                name="works",
                metadata={
                    "test_case_key": canon.ruby_test_case_key(
                        "spec/user_spec.rb",
                        "/User",
                    )
                },
            ),
            raw_observation("ruby.route", path="config/routes.rb", name="route", metadata={"route_pointer": "/routes/0"}),
            raw_observation("ruby.class", target="ruby.class:Explicit"),
        )
        for observation in ruby_targets:
            with self.subTest(kind=observation.kind, metadata=observation.metadata):
                self.assertIsInstance(canon._ruby_definition_target_key(observation), str)
        for observation in (
            raw_observation("ruby.method", name="save", metadata={}),
            raw_observation("ruby.singleton_method", name="build", metadata={}),
            raw_observation("ruby.constant", name="NAME", metadata={}),
            raw_observation("ruby.test_method", name="works", metadata={}),
            raw_observation("ruby.route", name="route", metadata={}),
            raw_observation("ruby.unknown", name="x"),
        ):
            with self.subTest(kind=observation.kind):
                with self.assertRaises(GraphKeyError):
                    canon._ruby_definition_target_key(observation)

        self.assertTrue(
            canon._ruby_reference_target_key(
                raw_observation("ruby.reference", target="ruby.class:User"),
                1,
                diagnostics,
            ).startswith("ruby.class:")
        )
        self.assertIn(
            "unknown:ruby.reference:missing-target",
            canon._ruby_reference_target_key(raw_observation("ruby.reference"), 2, diagnostics),
        )
        self.assertIn(
            "unknown:ruby.reference:malformed-target",
            canon._ruby_reference_target_key(
                raw_observation("ruby.reference", target="not a key"),
                3,
                diagnostics,
            ),
        )

        js_targets = (
            raw_observation("js.file", path="src/app.js", name="app.js"),
            raw_observation("js.module", path="src/app.js", name="app"),
            raw_observation("js.function", path="src/app.js", name="run"),
            raw_observation("js.class", path="src/app.js", name="Service"),
            raw_observation("js.method", path="src/app.js", name="run", metadata={"class_name": "Service"}),
            raw_observation("js.variable", path="src/app.js", name="state"),
            raw_observation("js.component", path="src/App.jsx", name="App"),
            raw_observation("js.test_suite", path="src/app.test.js", name="suite"),
            raw_observation("js.test_case", path="src/app.test.js", name="case"),
            raw_observation("js.route", path="src/routes.js", name="route", metadata={"route_pointer": "/routes/0"}),
            raw_observation("js.class", target=canon.js_class_key("src/app.js", "Service")),
        )
        for observation in js_targets:
            with self.subTest(kind=observation.kind, metadata=observation.metadata):
                self.assertIsInstance(canon._js_definition_target_key(observation), str)
        self.assertEqual(
            canon._js_definition_source_key(
                raw_observation(
                    "js.method",
                    metadata={"class_key": canon.js_class_key("src/app.js", "Service")},
                )
            ),
            canon.js_class_key("src/app.js", "Service"),
        )
        self.assertEqual(
            canon._js_definition_source_key(
                raw_observation(
                    "js.test_case",
                    path="src/app.test.js",
                    metadata={
                        "test_suite_key": canon.js_test_suite_key(
                            "src/app.test.js",
                            "/tests/suite",
                        )
                    },
                )
            ),
            canon.js_test_suite_key("src/app.test.js", "/tests/suite"),
        )
        for observation in (
            raw_observation("js.method", name="run", metadata={}),
            raw_observation("js.reference", metadata={"source_key": "python.module:bad"}),
            raw_observation("js.unknown", name="x"),
        ):
            with self.subTest(kind=observation.kind):
                with self.assertRaises(GraphKeyError):
                    if observation.kind == "js.reference":
                        canon._js_reference_source_key(observation)
                    elif observation.kind == "js.unknown":
                        canon._js_definition_target_key(observation)
                    else:
                        canon._js_definition_source_key(observation)
        with self.assertRaises(GraphKeyError):
            canon._js_definition_target_key(raw_observation("js.route", name="route", metadata={}))
        self.assertIn(
            "unknown:js.reference:missing-target",
            canon._js_reference_target_key(raw_observation("js.reference"), 4, diagnostics),
        )
        self.assertIn(
            "unknown:js.reference:malformed-target",
            canon._js_reference_target_key(
                raw_observation("js.reference", target="not a key"),
                5,
                diagnostics,
            ),
        )

        email_cases = (
            raw_observation("email.mailbox", path="mail/inbox.mbox"),
            raw_observation("email.message", path="mail/inbox.mbox", metadata={"message_id_hash": "abc"}),
            raw_observation(
                "email.part",
                metadata={
                    "source_key": canon.email_message_key(
                        "mail/inbox.mbox",
                        "structural:abc",
                    ),
                    "part_path": "/body",
                },
            ),
            raw_observation(
                "email.attachment_stub",
                metadata={
                    "source_key": canon.email_message_key(
                        "mail/inbox.mbox",
                        "structural:abc",
                    ),
                    "part_path": "/attachments/0",
                },
            ),
            raw_observation(
                "email.thread_hint",
                metadata={
                    "source_key": canon.email_message_key(
                        "mail/inbox.mbox",
                        "structural:abc",
                    ),
                    "thread_hint_kind": "/thread",
                },
            ),
            raw_observation("email.mailbox", target=canon.email_mailbox_key("mail/inbox.mbox")),
        )
        for observation in email_cases:
            with self.subTest(kind=observation.kind, metadata=observation.metadata):
                self.assertIsInstance(canon._email_definition_target_key(observation), str)
        self.assertEqual(
            canon._email_address_target_key(
                raw_observation("email.address", metadata={"address_hash": "abc"})
            ),
            canon.email_address_key("addrhash:abc"),
        )
        for observation in (
            raw_observation("email.part", metadata={}),
            raw_observation("email.address", metadata={}),
            raw_observation("email.reference", metadata={}),
            raw_observation("email.message", metadata={"source_key": "python.module:bad"}),
        ):
            with self.subTest(kind=observation.kind, metadata=observation.metadata):
                with self.assertRaises(GraphKeyError):
                    if observation.kind == "email.address":
                        canon._email_address_target_key(observation)
                    elif observation.kind == "email.reference":
                        canon._email_reference_source_key(observation)
                    elif observation.kind == "email.message":
                        canon._email_definition_source_key(observation)
                    else:
                        canon._email_definition_target_key(observation)
        self.assertIn(
            "unknown:email.reference:missing-target",
            canon._email_reference_target_key(raw_observation("email.reference"), 6, diagnostics),
        )

        self.assertEqual(
            canon._python_import_target_key(
                raw_observation("python.import", metadata={"resolution": "local", "imported_module": "pkg.mod"}),
                7,
                diagnostics,
            ),
            "python.module:pkg.mod",
        )
        self.assertEqual(
            canon._python_import_target_key(
                raw_observation("python.import", metadata={"resolution": "external", "imported_module": "requests"}),
                8,
                diagnostics,
            ),
            "external:python.module:requests",
        )
        self.assertEqual(
            canon._python_import_target_key(
                raw_observation("python.import", target="dynamic:python.module:star", metadata={"resolution": "unknown"}),
                9,
                diagnostics,
            ),
            "dynamic:python.module:star",
        )
        self.assertIn(
            "unknown:python.module:missing-module",
            canon._python_import_target_key(
                raw_observation("python.import", target="not a key", metadata={"resolution": "unknown"}),
                10,
                diagnostics,
            ),
        )

        self.assertEqual(
            canon._nix_import_target_key(
                raw_observation("nix.import", metadata={"resolved_path": "flake.nix"}),
                11,
                diagnostics,
            ),
            "file:flake.nix",
        )
        self.assertIn(
            "dynamic:file:interpolation",
            canon._nix_import_target_key(
                raw_observation("nix.import", metadata={"dynamic_reason": "interpolation"}),
                12,
                diagnostics,
            ),
        )
        self.assertEqual(
            canon._nix_import_target_key(
                raw_observation(
                    "nix.import",
                    target=canon.external_key("nix.store", "/nix/store/example"),
                ),
                13,
                diagnostics,
            ),
            canon.external_key("nix.store", "/nix/store/example"),
        )
        self.assertIn(
            "unknown:file:repo-escaping-nix-import",
            canon._nix_import_target_key(
                raw_observation("nix.import", metadata={"resolved_path": "../outside.nix"}),
                14,
                diagnostics,
            ),
        )
        self.assertEqual(
            canon._nix_output_target(
                raw_observation(
                    "nix.package",
                    name="repo-map",
                    metadata={
                        "flake_ref": ".",
                        "system": "aarch64-darwin",
                        "output_kind": "package",
                        "name": "repo-map",
                    },
                ),
                15,
                diagnostics,
            )[1],
            "repo-map",
        )
        self.assertIn(
            "unknown:nix.app:missing-output-identity",
            canon._nix_output_target(raw_observation("nix.app"), 16, diagnostics)[0],
        )
        with self.assertRaises(GraphKeyError):
            canon._nix_output_target(
                raw_observation(
                    "nix.unknown",
                    name="x",
                    metadata={"flake_ref": ".", "system": "aarch64-darwin"},
                ),
                17,
                diagnostics,
            )
        self.assertGreaterEqual(len(diagnostics), 8)

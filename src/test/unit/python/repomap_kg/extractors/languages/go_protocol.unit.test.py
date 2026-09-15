from __future__ import annotations

import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from repomap_kg.extractors.languages import go_protocol
from repomap_kg.extractors.languages.go_protocol import (
    GoHelperUnavailableError,
    GoProtocolError,
    iter_go_protocol_observations,
    resolve_go_helper_command,
    validate_go_protocol_message,
)


class GoProtocolValidationUnitTests(unittest.TestCase):
    def test_validates_observation_diagnostic_and_file_end_messages(self):
        observation = {
            "schema_version": 1,
            "kind": "go.package",
            "source_id": "pkg/file.go#go.package:0:10:0",
            "path": "pkg/file.go",
            "confidence": "extracted",
            "extractor": "repo-go-ast",
            "extractor_version": "0.1.0",
            "start_line": 1,
            "end_line": 1,
            "name": "pkg",
            "metadata": {"static_only": True},
        }
        messages = (
            {
                "protocol_version": 1,
                "type": "observation",
                "sequence": 2,
                "path": "pkg/file.go",
                "observation": observation,
            },
            {
                "protocol_version": 1,
                "type": "diagnostic",
                "sequence": 2,
                "path": "pkg/file.go",
                "severity": "warning",
                "code": "go-parse-error",
                "line": 3,
                "message": "syntax error",
            },
            {
                "protocol_version": 1,
                "type": "file_end",
                "sequence": 2,
                "path": "pkg/file.go",
                "observation_count": 1,
                "diagnostic_count": 1,
                "truncated": False,
            },
        )

        validated = [
            validate_go_protocol_message(
                message,
                expected_sequence=2,
                expected_path="pkg/file.go",
            )
            for message in messages
        ]

        self.assertEqual([item.type for item in validated], ["observation", "diagnostic", "file_end"])
        self.assertIsNotNone(validated[0].observation)
        assert validated[0].observation is not None
        self.assertEqual(validated[0].observation.kind, "go.package")
        self.assertIsNotNone(validated[1].diagnostic)
        assert validated[1].diagnostic is not None
        self.assertEqual(validated[1].diagnostic.code, "go-parse-error")
        self.assertIsNotNone(validated[2].file_end)
        assert validated[2].file_end is not None
        self.assertEqual(validated[2].file_end.observation_count, 1)

    def test_rejects_protocol_shape_and_identity_mismatches(self):
        base = {
            "protocol_version": 1,
            "type": "file_end",
            "sequence": 0,
            "path": "file.go",
            "observation_count": 0,
            "diagnostic_count": 0,
            "truncated": False,
        }
        invalid: tuple[object, ...] = (
            [],
            {**base, "protocol_version": 2},
            {**base, "sequence": 1},
            {**base, "path": "other.go"},
            {**base, "type": "unknown"},
            {**base, "observation_count": -1},
            {**base, "truncated": "false"},
            {**base, "extra": True},
            {key: value for key, value in base.items() if key != "path"},
        )

        for payload in invalid:
            with self.subTest(payload=payload):
                with self.assertRaises(GoProtocolError):
                    validate_go_protocol_message(
                        payload,
                        expected_sequence=0,
                        expected_path="file.go",
                    )

    def test_rejects_invalid_observation_and_diagnostic_payloads(self):
        common = {
            "protocol_version": 1,
            "sequence": 0,
            "path": "file.go",
        }
        observation = {
            "schema_version": 1,
            "kind": "go.package",
            "source_id": "file.go#go.package:0:1:0",
            "path": "file.go",
            "confidence": "extracted",
            "extractor": "repo-go-ast",
            "extractor_version": "0.1.0",
            "metadata": {},
        }
        invalid = (
            {**common, "type": "observation", "observation": []},
            {
                **common,
                "type": "observation",
                "observation": {**observation, "kind": ""},
            },
            {
                **common,
                "type": "observation",
                "observation": {**observation, "path": "other.go"},
            },
            {
                **common,
                "type": "diagnostic",
                "severity": "warning",
                "code": "go-parse-error",
                "line": 0,
                "message": "syntax error",
            },
            {
                **common,
                "type": "diagnostic",
                "severity": "warning",
                "code": "go-parse-error",
                "message": "x" * 513,
            },
        )

        for payload in invalid:
            with self.subTest(payload_type=payload["type"]):
                with self.assertRaises(GoProtocolError):
                    validate_go_protocol_message(
                        payload,
                        expected_sequence=0,
                        expected_path="file.go",
                    )


class GoProtocolProcessUnitTests(unittest.TestCase):
    def test_client_rejects_excess_observations_and_bounds_reader_queue(self):
        script = r'''
import json, sys
request = json.loads(sys.stdin.readline())
path = request["path"]
observation = {"schema_version": 1, "kind": "go.package", "source_id": path + "#package", "path": path, "confidence": "extracted", "extractor": "repo-go-ast", "extractor_version": "0.1.0", "metadata": {}}
print(json.dumps({"protocol_version": 1, "type": "observation", "sequence": 0, "path": path, "observation": observation}), flush=True)
print(json.dumps({"protocol_version": 1, "type": "file_end", "sequence": 0, "path": path, "observation_count": 1, "diagnostic_count": 0, "truncated": False}), flush=True)
'''

        with patch.object(go_protocol, "MAX_OBSERVATIONS_PER_FILE", 0):
            with self.assertRaisesRegex(GoProtocolError, "observation count"):
                list(
                    iter_go_protocol_observations(
                        Path("/synthetic-repository"),
                        ["file.go"],
                        (sys.executable, "-c", script),
                    )
                )

        self.assertLessEqual(go_protocol.STDOUT_QUEUE_LINES, 16)

    def test_client_rejects_messages_after_final_file_end(self):
        script = r'''
import json, sys
request = json.loads(sys.stdin.readline())
message = {"protocol_version": 1, "type": "file_end", "sequence": 0, "path": request["path"], "observation_count": 0, "diagnostic_count": 0, "truncated": False}
print(json.dumps(message), flush=True)
print(json.dumps(message), flush=True)
'''

        with self.assertRaisesRegex(GoProtocolError, "after final file_end"):
            list(
                iter_go_protocol_observations(
                    Path("/synthetic-repository"),
                    ["file.go"],
                    (sys.executable, "-c", script),
                )
            )

    def test_empty_paths_are_a_noop_and_commands_must_be_explicit(self):
        self.assertEqual(
            list(
                iter_go_protocol_observations(
                    Path("/tmp/repository"),
                    [],
                    (sys.executable,),
                )
            ),
            [],
        )
        for command in ((), ("relative-helper",), (sys.executable, "")):
            with self.subTest(command=command):
                with self.assertRaises(GoHelperUnavailableError):
                    list(
                        iter_go_protocol_observations(
                            Path("/tmp/repository"),
                            ["file.go"],
                            command,
                        )
                    )

    def test_iterates_sorted_paths_and_converts_diagnostics(self):
        script = r'''
import json, sys
for line in sys.stdin:
    request = json.loads(line)
    path = request["path"]
    observation = {
        "schema_version": 1,
        "kind": "go.package",
        "source_id": path + "#go.package:0:1:0",
        "path": path,
        "confidence": "extracted",
        "extractor": "repo-go-ast",
        "extractor_version": "0.1.0",
        "start_line": 1,
        "end_line": 1,
        "name": "sample",
        "metadata": {"static_only": True},
    }
    print(json.dumps({"protocol_version": 1, "type": "observation", "sequence": request["sequence"], "path": path, "observation": observation}), flush=True)
    diagnostic_count = 0
    if path.endswith("partial.go"):
        print(json.dumps({"protocol_version": 1, "type": "diagnostic", "sequence": request["sequence"], "path": path, "severity": "warning", "code": "go-parse-error", "line": 2, "message": "syntax error"}), flush=True)
        diagnostic_count = 1
    print(json.dumps({"protocol_version": 1, "type": "file_end", "sequence": request["sequence"], "path": path, "observation_count": 1, "diagnostic_count": diagnostic_count, "truncated": False}), flush=True)
'''

        observations = list(
            iter_go_protocol_observations(
                Path("/tmp/repository"),
                ["z/partial.go", "a/file.go"],
                (sys.executable, "-c", script),
                response_timeout=2,
            )
        )

        self.assertEqual(
            [(item.kind, item.path) for item in observations],
            [
                ("go.package", "a/file.go"),
                ("go.package", "z/partial.go"),
                ("go.parse_error", "z/partial.go"),
            ],
        )
        self.assertNotIn("/tmp/repository", "".join(item.to_json_line() for item in observations))

    def test_rejects_count_mismatch_oversized_line_timeout_and_child_exit(self):
        scripts = {
            "count": r'''
import json, sys
request = json.loads(sys.stdin.readline())
print(json.dumps({"protocol_version": 1, "type": "file_end", "sequence": 0, "path": request["path"], "observation_count": 1, "diagnostic_count": 0, "truncated": False}), flush=True)
''',
            "oversized": "import sys; sys.stdin.readline(); print('x' * ((1 << 20) + 1), flush=True)",
            "timeout": "import sys, time; sys.stdin.readline(); time.sleep(2)",
            "exit": "import sys; sys.stdin.readline(); sys.stderr.write('/private/source.go\\n'); sys.exit(7)",
        }
        for name, script in scripts.items():
            with self.subTest(name=name):
                started = time.monotonic()
                with self.assertRaises(GoProtocolError) as caught:
                    list(
                        iter_go_protocol_observations(
                            Path("/tmp/repository"),
                            ["file.go"],
                            (sys.executable, "-c", script),
                            response_timeout=0.1 if name == "timeout" else 2,
                            cleanup_timeout=0.1,
                        )
                    )
                self.assertLess(time.monotonic() - started, 1.5)
                self.assertNotIn("/private/source.go", str(caught.exception))
                self.assertNotIn("/tmp/repository", str(caught.exception))

    def test_abrupt_early_eof_versus_completed_file_end_nonzero_exit(self):
        # 1. Abrupt early EOF: child consumes request from stdin and exits before emitting file_end.
        # Error path is "helper exited before file_end" where poll status may be None or nonzero.
        abrupt_script = "import sys; sys.stdin.readline(); sys.stderr.write('abrupt error\\n'); sys.exit(42)"
        with self.assertRaises(GoProtocolError) as cm_abrupt:
            list(
                iter_go_protocol_observations(
                    Path("/tmp/repository"),
                    ["file.go"],
                    (sys.executable, "-c", abrupt_script),
                    cleanup_timeout=0.5,
                )
            )
        self.assertIn("helper exited before file_end", str(cm_abrupt.exception))

        # 2. Completed file_end followed by nonzero exit:
        # Error path is "helper exited unsuccessfully; status=42" with stderr metadata.
        completed_script = (
            "import json, sys\n"
            "req = json.loads(sys.stdin.readline())\n"
            "print(json.dumps({'protocol_version': 1, 'type': 'file_end', 'sequence': req['sequence'], "
            "'path': req['path'], 'observation_count': 0, 'diagnostic_count': 0, 'truncated': False}), flush=True)\n"
            "sys.stderr.write('nonzero error\\n')\n"
            "sys.exit(42)\n"
        )
        with self.assertRaises(GoProtocolError) as cm_completed:
            list(
                iter_go_protocol_observations(
                    Path("/tmp/repository"),
                    ["file.go"],
                    (sys.executable, "-c", completed_script),
                    cleanup_timeout=0.5,
                )
            )
        self.assertIn("helper exited unsuccessfully; status=42", str(cm_completed.exception))
        self.assertIn("stderr_bytes=", str(cm_completed.exception))


class GoHelperResolutionUnitTests(unittest.TestCase):
    def test_resolves_explicit_absolute_helper(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            helper = Path(tmpdir) / "repomap-go-extract"
            helper.write_text("#!/bin/sh\nexit 0\n")
            helper.chmod(0o755)

            command = resolve_go_helper_command(
                environment={"REPOMAP_GO_HELPER": str(helper)},
                package_root=Path(tmpdir) / "unused",
                target_platform="test-platform",
            )
            expected = str(helper.resolve())

        self.assertEqual(command, (expected,))

    def test_resolves_only_packaged_platform_location(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            package_root = Path(tmpdir)
            helper = package_root / "_bin" / "test-platform" / "repomap-go-extract"
            helper.parent.mkdir(parents=True)
            helper.write_text("#!/bin/sh\nexit 0\n")
            helper.chmod(0o755)

            command = resolve_go_helper_command(
                environment={},
                package_root=package_root,
                target_platform="test-platform",
            )
            expected = str(helper.resolve())

        self.assertEqual(command, (expected,))

    def test_rejects_missing_relative_or_non_executable_helper(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            non_executable = Path(tmpdir) / "helper"
            non_executable.write_text("helper")
            environments: tuple[dict[str, str], ...] = (
                {},
                {"REPOMAP_GO_HELPER": "relative/helper"},
                {"REPOMAP_GO_HELPER": str(non_executable)},
            )
            for environment in environments:
                with self.subTest(environment=environment):
                    with self.assertRaises(GoHelperUnavailableError):
                        resolve_go_helper_command(
                            environment=environment,
                            package_root=Path(tmpdir) / "package",
                            target_platform="test-platform",
                        )


if __name__ == "__main__":
    unittest.main()

"""Integration tests for Go parser helper subprocess composition, protocol contracts, and bounds."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import sys
import tempfile
from collections.abc import Mapping
import unittest
from unittest import mock

FIXTURE_ROOT = Path(__file__).resolve().parents[6] / "src" / "test" / "fixtures"
from repomap_kg.canonicalization.main import canonicalize_observations
from repomap_kg.extractors.languages.go_helper import (
    GoHelperUnavailableError,
    resolve_go_helper_command,
)
from repomap_kg.extractors.languages.go_protocol import (
    GoProtocolError,
    iter_go_protocol_observations,
)
from repomap_kg.extractors.languages.golang import (
    extract_go_repository_observations,
)
from repomap_kg.observations.raw import RawObservation


GO_FIXTURE_ROOT = FIXTURE_ROOT / "go"


def _mock_helper_cmd(*messages: Mapping[str, object]) -> tuple[str, ...]:
    lines = "; ".join(f"print({json.dumps(json.dumps(m))}, flush=True)" for m in messages)
    return (sys.executable, "-c", f"import sys; sys.stdin.readline(); {lines}")


@dataclass(frozen=True)
class GoTestFileInfo:
    path: str
    language: str


class GoHelperCompositionIntegrationTests(unittest.TestCase):
    helper_command: tuple[str, ...]
    @classmethod
    def setUpClass(cls) -> None:
        cls.helper_command = resolve_go_helper_command()

    def test_real_helper_streaming_extraction_on_syntax_fixtures(self) -> None:
        root = GO_FIXTURE_ROOT / "syntax_basic"
        self.assertTrue(root.is_dir(), f"Fixture directory not found: {root}")

        observations = list(
            iter_go_protocol_observations(
                root,
                ["declarations.go"],
                self.helper_command,
            )
        )

        self.assertGreaterEqual(len(observations), 15)
        kinds = {obs.kind for obs in observations}
        expected_kinds = {
            "go.package", "go.import", "go.const", "go.var", "go.type", "go.type_alias",
            "go.function", "go.struct", "go.field", "go.type_parameter", "go.constraint", "go.reference",
        }
        self.assertTrue(
            expected_kinds.issubset(kinds),
            f"Missing expected kinds: {expected_kinds - kinds}",
        )

        for obs in observations:
            self.assertEqual(obs.extractor, "repo-go-ast")
            self.assertEqual(obs.path, "declarations.go")
            assert obs.start_line is not None and obs.end_line is not None
            self.assertGreater(obs.start_line, 0)
            self.assertGreaterEqual(obs.end_line, obs.start_line)

    def test_real_helper_malformed_syntax_emits_diagnostics_without_crash(self) -> None:
        root = GO_FIXTURE_ROOT / "syntax_malformed"
        self.assertTrue(root.is_dir(), f"Fixture directory not found: {root}")

        observations = list(
            iter_go_protocol_observations(
                root,
                ["partial.go"],
                self.helper_command,
            )
        )

        obs_by_kind: dict[str, list[RawObservation]] = {}
        for obs in observations:
            obs_by_kind.setdefault(obs.kind, []).append(obs)

        # Concrete assertions: pre-error AST is extracted cleanly despite trailing syntax error
        self.assertIn("go.package", obs_by_kind)
        pkg_obs = obs_by_kind["go.package"][0]
        self.assertEqual(pkg_obs.path, "partial.go")
        self.assertEqual(pkg_obs.name, "broken")

        self.assertIn("go.import", obs_by_kind)
        import_obs = obs_by_kind["go.import"][0]
        self.assertEqual(import_obs.path, "partial.go")
        self.assertEqual(import_obs.name, "example.invalid/safe")

        self.assertIn("go.const", obs_by_kind)
        const_obs = obs_by_kind["go.const"][0]
        self.assertEqual(const_obs.path, "partial.go")
        self.assertEqual(const_obs.name, "BeforeError")

        # Concrete assertions: diagnostic emitted without crashing helper
        self.assertIn("go.parse_error", obs_by_kind)
        parse_error = obs_by_kind["go.parse_error"][0]
        self.assertEqual(parse_error.path, "partial.go")
        self.assertEqual(parse_error.confidence, "unknown")
        self.assertEqual(parse_error.extractor, "repo-go-ast")
        assert parse_error.start_line is not None
        self.assertGreaterEqual(parse_error.start_line, 7)
        self.assertTrue(parse_error.source_id.startswith("partial.go#go.parse_error:"))
        self.assertEqual(parse_error.metadata.get("code"), "go-parse-error")
        self.assertEqual(parse_error.metadata.get("severity"), "warning")
        self.assertTrue(len(parse_error.metadata.get("bounded_message", "")) > 0)

    def test_go_repository_observations_composition_with_companions(self) -> None:
        root = GO_FIXTURE_ROOT / "syntax_basic"
        file_infos = [
            GoTestFileInfo(path="declarations.go", language="go"),
            GoTestFileInfo(path="context.go", language="go"),
            GoTestFileInfo(path="context.s", language="assembly"),
        ]

        observations = extract_go_repository_observations(root, file_infos)
        self.assertGreater(len(observations), 20)

        kinds = {obs.kind for obs in observations}
        self.assertIn("go.assembly_companion", kinds)
        self.assertIn("go.package", kinds)
        self.assertIn("go.function", kinds)

        companion_obs = [obs for obs in observations if obs.kind == "go.assembly_companion"]
        self.assertGreaterEqual(len(companion_obs), 1)
        self.assertEqual(companion_obs[0].path, "context.s")
        self.assertEqual(companion_obs[0].metadata.get("package_name"), "sample")

    def test_extract_go_repository_observations_empty_returns_empty(self) -> None:
        root = GO_FIXTURE_ROOT / "syntax_basic"
        file_infos = [
            GoTestFileInfo(path="declarations.go", language="text"),
            GoTestFileInfo(path="context.s", language="assembly"),
        ]
        observations = extract_go_repository_observations(root, file_infos)
        self.assertEqual(observations, ())

    def test_protocol_handles_abrupt_subprocess_termination(self) -> None:
        root = GO_FIXTURE_ROOT / "syntax_basic"
        # Deterministic early EOF: child consumes request from stdin, then abruptly exits before file_end
        failing_cmd = (sys.executable, "-c", "import sys; sys.stdin.readline(); sys.exit(42)")

        with self.assertRaises(GoProtocolError) as cm:
            list(
                iter_go_protocol_observations(
                    root,
                    ["declarations.go"],
                    failing_cmd,
                    cleanup_timeout=0.5,
                )
            )
        self.assertIn("helper exited before file_end", str(cm.exception))


    def test_protocol_detects_invalid_json_lines(self) -> None:
        root = GO_FIXTURE_ROOT / "syntax_basic"
        bad_json_cmd = (
            sys.executable,
            "-c",
            "import sys; sys.stdin.readline(); print('NOT_VALID_JSON', flush=True)",
        )

        with self.assertRaises(GoProtocolError) as cm:
            list(
                iter_go_protocol_observations(
                    root,
                    ["declarations.go"],
                    bad_json_cmd,
                    cleanup_timeout=0.5,
                )
            )
        self.assertIn("invalid protocol JSON", str(cm.exception))

    def test_missing_helper_environment_raises_unavailable_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            missing_path = Path(tmpdir) / "nonexistent-helper"
            with mock.patch.dict(
                os.environ, {"REPOMAP_GO_HELPER": str(missing_path)}
            ):
                with self.assertRaises(GoHelperUnavailableError) as cm:
                    resolve_go_helper_command()
                self.assertIn("Go parser helper is unavailable", str(cm.exception))

    def test_protocol_enforces_command_path_absoluteness(self) -> None:
        root = GO_FIXTURE_ROOT / "syntax_basic"
        with self.assertRaises(GoHelperUnavailableError) as cm:
            list(iter_go_protocol_observations(root, ["declarations.go"], ["go-helper-relative"]))
        self.assertIn("Go parser helper command must be explicit", str(cm.exception))

    def test_protocol_enforces_version_and_sequence_contract(self) -> None:
        root = GO_FIXTURE_ROOT / "syntax_basic"
        # Version mismatch
        bad_ver = {"protocol_version": 99, "type": "file_end", "sequence": 0, "path": "declarations.go", "observation_count": 0, "diagnostic_count": 0, "truncated": False}
        with self.assertRaises(GoProtocolError) as cm_ver:
            list(iter_go_protocol_observations(root, ["declarations.go"], _mock_helper_cmd(bad_ver), cleanup_timeout=0.5))
        self.assertIn("protocol version mismatch", str(cm_ver.exception))

        # Sequence mismatch
        bad_seq = {"protocol_version": 1, "type": "file_end", "sequence": 99, "path": "declarations.go", "observation_count": 0, "diagnostic_count": 0, "truncated": False}
        with self.assertRaises(GoProtocolError) as cm_seq:
            list(iter_go_protocol_observations(root, ["declarations.go"], _mock_helper_cmd(bad_seq), cleanup_timeout=0.5))
        self.assertIn("protocol sequence mismatch", str(cm_seq.exception))

        # Path mismatch
        bad_path = {"protocol_version": 1, "type": "file_end", "sequence": 0, "path": "other.go", "observation_count": 0, "diagnostic_count": 0, "truncated": False}
        with self.assertRaises(GoProtocolError) as cm_path:
            list(iter_go_protocol_observations(root, ["declarations.go"], _mock_helper_cmd(bad_path), cleanup_timeout=0.5))
        self.assertIn("protocol path mismatch", str(cm_path.exception))

    def test_protocol_enforces_diagnostic_and_accounting_bounds(self) -> None:
        root = GO_FIXTURE_ROOT / "syntax_basic"
        # Diagnostic line must be positive
        bad_line = {"protocol_version": 1, "type": "diagnostic", "sequence": 0, "path": "declarations.go", "severity": "error", "code": "go-parse-error", "line": 0, "message": "bad line"}
        with self.assertRaises(GoProtocolError) as cm_line:
            list(iter_go_protocol_observations(root, ["declarations.go"], _mock_helper_cmd(bad_line), cleanup_timeout=0.5))
        self.assertIn("diagnostic line must be positive", str(cm_line.exception))

        # Diagnostic message bound (> 512 bytes)
        long_diag = {"protocol_version": 1, "type": "diagnostic", "sequence": 0, "path": "declarations.go", "severity": "error", "code": "go-parse-error", "line": 1, "message": "x" * 513}
        with self.assertRaises(GoProtocolError) as cm_bound:
            list(iter_go_protocol_observations(root, ["declarations.go"], _mock_helper_cmd(long_diag), cleanup_timeout=0.5))
        self.assertIn("diagnostic message exceeds its bound", str(cm_bound.exception))

        # Diagnostic count bound (> 32 diagnostics)
        diags = [{"protocol_version": 1, "type": "diagnostic", "sequence": 0, "path": "declarations.go", "severity": "warning", "code": "go-parse-error", "line": 1, "message": f"err {i}"} for i in range(33)]
        with self.assertRaises(GoProtocolError) as cm_diag_count:
            list(iter_go_protocol_observations(root, ["declarations.go"], _mock_helper_cmd(*diags), cleanup_timeout=0.5))
        self.assertIn("protocol diagnostic count exceeds its bound", str(cm_diag_count.exception))

        # Observation count mismatch on file_end
        count_mismatch = {"protocol_version": 1, "type": "file_end", "sequence": 0, "path": "declarations.go", "observation_count": 42, "diagnostic_count": 0, "truncated": False}
        with self.assertRaises(GoProtocolError) as cm_count:
            list(iter_go_protocol_observations(root, ["declarations.go"], _mock_helper_cmd(count_mismatch), cleanup_timeout=0.5))
        self.assertIn("protocol observation count mismatch", str(cm_count.exception))

    def test_real_helper_streaming_extraction_on_composites_and_callables(self) -> None:
        root = GO_FIXTURE_ROOT / "syntax_basic"
        self.assertTrue(root.is_dir(), f"Fixture directory not found: {root}")

        observations = list(
            iter_go_protocol_observations(
                root,
                ["composites.go", "callables.go"],
                self.helper_command,
            )
        )
        self.assertGreaterEqual(len(observations), 10)
        paths = {obs.path for obs in observations}
        self.assertEqual(paths, {"composites.go", "callables.go"})

        obs_by_kind: dict[str, list[RawObservation]] = {}
        for obs in observations:
            self.assertEqual(obs.extractor, "repo-go-ast")
            obs_by_kind.setdefault(obs.kind, []).append(obs)

        # Assert composite and callable language features extracted by admitted Go helper
        self.assertIn("go.struct", obs_by_kind)
        self.assertIn("go.interface", obs_by_kind)
        self.assertIn("go.method", obs_by_kind)
        self.assertIn("go.type_parameter", obs_by_kind)

        # Confirm specific symbol identities from composites and callables fixtures
        struct_names = {obs.name for obs in obs_by_kind["go.struct"]}
        self.assertIn("Embedded", struct_names)
        self.assertIn("Pair", struct_names)
        self.assertIn("Box", struct_names)

        method_names = {obs.name for obs in obs_by_kind["go.method"]}
        self.assertIn("Transform", method_names)
        self.assertIn("Value", method_names)
        self.assertIn("Reset", method_names)

        interface_names = {obs.name for obs in obs_by_kind["go.interface"]}
        self.assertIn("Service", interface_names)

    def test_protocol_enforces_observation_path_integrity(self) -> None:
        root = GO_FIXTURE_ROOT / "syntax_basic"
        bad_obs = {
            "protocol_version": 1,
            "type": "observation",
            "sequence": 0,
            "path": "declarations.go",
            "observation": {
                "schema_version": 1,
                "kind": "go.package",
                "source_id": "decl#pkg",
                "path": "wrong_path.go",
                "confidence": "extracted",
                "extractor": "repo-go-ast",
                "extractor_version": "1.0",
            },
        }
        with self.assertRaises(GoProtocolError) as cm_path:
            list(iter_go_protocol_observations(root, ["declarations.go"], _mock_helper_cmd(bad_obs), cleanup_timeout=0.5))
        self.assertIn("observation path mismatch", str(cm_path.exception))

    def test_protocol_handles_hanging_helper_termination_and_trailing_messages(self) -> None:
        from repomap_test_support.staging_abrupt_launch import observe_go_hang
        root = GO_FIXTURE_ROOT / "syntax_basic"
        # Helper emits valid file_end and then hangs after input; protocol enforces cleanup_timeout
        hanging_cmd = (
            sys.executable,
            "-c",
            "import sys, json, time; sys.stdin.readline(); print(json.dumps({'protocol_version': 1, 'type': 'file_end', 'sequence': 0, 'path': 'declarations.go', 'observation_count': 0, 'diagnostic_count': 0, 'truncated': False}), flush=True); time.sleep(5)",
        )
        with observe_go_hang(hanging_cmd):
            with self.assertRaises(GoProtocolError) as cm_hang:
                list(iter_go_protocol_observations(root, ["declarations.go"], hanging_cmd, cleanup_timeout=0.2))
        self.assertIn("helper did not exit after input completed", str(cm_hang.exception))

        # Helper emits message after final file_end
        end_msg = {"protocol_version": 1, "type": "file_end", "sequence": 0, "path": "declarations.go", "observation_count": 0, "diagnostic_count": 0, "truncated": False}
        end_msg2 = {"protocol_version": 1, "type": "file_end", "sequence": 1, "path": "declarations.go", "observation_count": 0, "diagnostic_count": 0, "truncated": False}
        with self.assertRaises(GoProtocolError) as cm_trail:
            list(iter_go_protocol_observations(root, ["declarations.go"], _mock_helper_cmd(end_msg, end_msg2), cleanup_timeout=0.5))
        self.assertIn("protocol message received after final file_end", str(cm_trail.exception))

        # Helper failure reports bounded stderr accounting without disclosing raw stderr
        crash_stderr_cmd = (sys.executable, "-c", "import sys; sys.stderr.write('fatal go runtime panic\\n'); sys.exit(2)")
        with self.assertRaises(GoProtocolError) as cm_crash:
            list(iter_go_protocol_observations(root, ["declarations.go"], crash_stderr_cmd, cleanup_timeout=0.5))
        self.assertNotIn("fatal go runtime panic", str(cm_crash.exception))
        self.assertIn("helper exited", str(cm_crash.exception))

    def test_native_go_observations_canonicalization_and_accounting(self) -> None:
        root = GO_FIXTURE_ROOT / "syntax_basic"
        self.assertTrue(root.is_dir(), f"Fixture directory not found: {root}")

        extracted = list(
            iter_go_protocol_observations(
                root,
                ["declarations.go", "composites.go", "callables.go"],
                self.helper_command,
            )
        )
        self.assertGreaterEqual(len(extracted), 20)

        file_observations = [
            RawObservation(
                kind="file", source_id=f"file:{p}", path=p, confidence="extracted",
                extractor="fixture", extractor_version="1.0", metadata={"language": "go", "role": "source"},
            )
            for p in ("declarations.go", "composites.go", "callables.go")
        ]

        result = canonicalize_observations(
            (*file_observations, *extracted),
            repository_scope="go-canonical-test",
        )
        self.assertTrue(result.ok)

        # Assert instrumented native Go canonical accounting diagnostic
        accounting_diag = next(
            (d for d in result.diagnostics if d.category == "go_canonical_accounting"),
            None,
        )
        assert accounting_diag is not None
        assert isinstance(accounting_diag.value, dict)
        self.assertGreater(len(accounting_diag.value), 0)

        # Assert canonical nodes produced from native Go observations
        node_kinds = {node.kind for node in result.graph.nodes}
        self.assertIn("go.source_package", node_kinds)
        self.assertIn("go.source_function", node_kinds)
        self.assertIn("go.source_type", node_kinds)
        self.assertIn("go.source_method", node_kinds)

        # Assert canonical edges and evidence linkage
        edge_kinds = {edge.kind for edge in result.graph.edges}
        self.assertIn("declares", edge_kinds)
        self.assertGreater(len(result.graph.evidence), 0)
        self.assertGreater(len(result.graph.node_evidence_links), 0)
        self.assertGreater(len(result.graph.edge_evidence_links), 0)

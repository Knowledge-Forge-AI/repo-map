"""Admitted native helper path refusal and owned cancellation authorings."""
from __future__ import annotations

import subprocess
from types import GeneratorType
import unittest
from unittest import mock

from repomap_kg.extractors.languages import go_protocol
from repomap_kg.extractors.languages.go_helper import resolve_go_helper_command
from pathlib import Path
FIXTURE_ROOT = Path(__file__).resolve().parents[6] / "src" / "test" / "fixtures"


class GoNativeLifecycleIntegrationTests(unittest.TestCase):
    def test_native_helper_refuses_escaping_path_and_next_request_recovers(self) -> None:
        command = resolve_go_helper_command()
        root = FIXTURE_ROOT / "go" / "syntax_basic"
        with self.assertRaises(go_protocol.GoProtocolError) as caught:
            list(go_protocol.iter_go_protocol_observations(root, ["../outside.go"], command))
        message = str(caught.exception)
        self.assertIn("helper exited before file_end", message)
        self.assertNotIn(str(root), message)
        self.assertNotIn("outside.go", message)
        recovered = list(go_protocol.iter_go_protocol_observations(root, ["declarations.go"], command))
        self.assertTrue(recovered)
        self.assertEqual({item.path for item in recovered}, {"declarations.go"})
        self.assertTrue(any(item.kind == "go.package" for item in recovered))

    def test_close_after_native_observation_joins_owned_process_and_closes_pipes(self) -> None:
        command = resolve_go_helper_command()
        root = FIXTURE_ROOT / "go" / "syntax_basic"
        terminated: list[subprocess.Popen[bytes]] = []
        terminate = go_protocol._terminate_process

        def observe_termination(process: subprocess.Popen[bytes], timeout: float) -> None:
            terminated.append(process)
            terminate(process, timeout)

        with mock.patch.object(go_protocol, "_terminate_process", side_effect=observe_termination):
            observations = go_protocol.iter_go_protocol_observations(root, ["declarations.go"], command)
            assert isinstance(observations, GeneratorType)
            try:
                first = next(observations)
                self.assertEqual(first.path, "declarations.go")
                self.assertEqual(first.extractor, "repo-go-ast")
            finally:
                observations.close()
        self.assertEqual(len(terminated), 1)
        process = terminated[0]
        self.assertIsNotNone(process.poll())
        for pipe in (process.stdin, process.stdout, process.stderr):
            assert pipe is not None
            self.assertTrue(pipe.closed)

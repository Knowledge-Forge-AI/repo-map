from types import SimpleNamespace
from unittest.mock import patch

import run_tests
from runner_coverage import ChildCoverageSession

from src.test.unit.python.tools.report_test_fixtures import ReportTestCase


class ReportLifecycleUnitTests(ReportTestCase):
    def test_coverage_finalization_preserves_pytest_exit_when_stop_and_save_fail(self):
        class FailingCoverageRunner:
            _instrumentation_error: str

            def __init__(self):
                self.events = []

            def start(self):
                self.events.append("start")

            def stop(self):
                self.events.append("stop")
                raise RuntimeError("stop failed")

            def save(self):
                self.events.append("save")
                raise RuntimeError("save failed")

        class FakeSession(ChildCoverageSession):
            def __init__(self, runner):
                self.runner = runner
                self.combine_called = False

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc_value, traceback):
                return None

            def cleanup(self):
                # This collaborator allocates no session resources.
                return None

            def create_coverage(self, coverage_module=None):
                return self.runner

            def combine(self, coverage_runner=None):
                self.combine_called = True
                return coverage_runner

        runner = FailingCoverageRunner()
        session = FakeSession(runner)
        plugin = SimpleNamespace(_suite="int", test_records=[])
        with patch.object(run_tests, "run_pytest", return_value=1):
            exit_code, returned_runner = run_tests.run_pytest_with_coverage(
                object(), SimpleNamespace(), [], plugin, session=session,
            )

        self.assertEqual(exit_code, 1)
        self.assertIs(returned_runner, runner)
        self.assertEqual(runner.events, ["start", "stop", "save"])
        self.assertFalse(session.combine_called)
        self.assertIn("coverage stop failed", runner._instrumentation_error)
        self.assertIn("coverage save failed", runner._instrumentation_error)

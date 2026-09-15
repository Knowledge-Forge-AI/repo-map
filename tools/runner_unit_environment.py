"""Environment and purity setup helpers for RepoMap test execution."""

from __future__ import annotations

from contextlib import contextmanager
import os
from pathlib import Path
import subprocess
import sys

_TOOLS_ROOT = Path(__file__).resolve().parent
_REPO_ROOT = _TOOLS_ROOT.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
if str(_TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(_TOOLS_ROOT))
if str(_REPO_ROOT / "src" / "test" / "support" / "python") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "src" / "test" / "support" / "python"))

from build_go_helper import build_go_helper, validate_go_sources
from repomap_test_support.build_profile_debt import DEFERRED_BUILD_PROFILE_NODE_IDS
from repomap_test_support.test_scratch import establish_run
from repomap_test_support.unit_purity import UnitPurityState
from runner_arguments import is_relative_to
from test_report import TestRecord


def prepare_go_test_environment(
    suite: str,
    *,
    establish_run_fn=establish_run,
    validate_go_sources_fn=validate_go_sources,
    build_go_helper_fn=build_go_helper,
) -> None:
    try:
        from go_runner_coverage import prepare_go_environment

        helper = prepare_go_environment(
            suite,
            establish_run_fn().go_tmp,
            validate_go_sources_fn,
            build_go_helper_fn,
        )
    except (OSError, RuntimeError, subprocess.CalledProcessError) as error:
        raise RuntimeError(f"Go helper validation failed: {error}") from error
    os.environ["REPOMAP_GO_HELPER"] = str(helper)


@contextmanager
def pytest_environment_for(suites: tuple[str, ...], args):
    updates: dict[str, str] = {}
    if "int" in suites:
        updates = {
            "REPOMAP_TEST_PG_CONTAINER_RUNTIME": args.pg_container_runtime,
            "REPOMAP_TEST_PG_CONTAINER_PORT": str(args.pg_container_port),
        }
    previous = {key: os.environ.get(key) for key in updates}
    os.environ.update(updates)
    try:
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _test_root(suite: str) -> Path:
    return Path(__file__).resolve().parents[1] / "src" / "test" / suite / "python"


class RecordingPytestPlugin:
    def __init__(self, *, suite: str = "unit", full_population: bool = False):
        self.test_records: tuple[TestRecord, ...] = ()
        self._record_list: list[TestRecord] = []
        self._recorded_nodeids: set[str] = set()
        self.deferred_build_count = 0
        self._suite = suite
        self._full_population = full_population
        self._purity = UnitPurityState()

    def pytest_runtest_protocol(self, item, nextitem) -> None:
        item_path = Path(str(item.path)).resolve()
        self._purity.activate(
            unit_item=is_relative_to(item_path, _test_root("unit")),
        )

    def pytest_sessionfinish(self, session, exitstatus) -> None:
        self._purity.restore()

    def pytest_collection_modifyitems(self, session, config, items) -> None:
        marked = {
            item.nodeid
            for item in items
            if item.get_closest_marker("requires_build_profile") is not None
        }
        registered = set(DEFERRED_BUILD_PROFILE_NODE_IDS)
        collected_registered = {item.nodeid for item in items} & registered
        if marked.difference(registered) or collected_registered.difference(marked):
            raise RuntimeError(
                "requires_build_profile marker and deferred registry disagree"
            )
        expected = registered if self._suite in {"int", "staging"} else set()
        if self._full_population and marked != expected:
            raise RuntimeError(
                "complete canonical population differs from deferred build registry"
            )
        selected = [item for item in items if item.nodeid not in marked]
        deselected = [item for item in items if item.nodeid in marked]
        items[:] = selected
        self.deferred_build_count = len(deselected)
        if deselected:
            config.hook.pytest_deselected(items=deselected)

    @staticmethod
    def _extract_skip_reason(report) -> str:
        longrepr = getattr(report, "longrepr", None)
        if isinstance(longrepr, tuple) and len(longrepr) >= 3:
            reason = str(longrepr[2])
            if reason.startswith("Skipped: "):
                return reason[len("Skipped: ") :]
            return reason
        longreprtext = getattr(report, "longreprtext", "")
        if longreprtext:
            text = str(longreprtext).strip()
            if "Skipped: " in text:
                return text.split("Skipped: ", 1)[1].strip()
            return text
        if isinstance(longrepr, str) and longrepr:
            text = longrepr.strip()
            if "Skipped: " in text:
                return text.split("Skipped: ", 1)[1].strip()
            return text
        return ""

    def pytest_runtest_logreport(self, report) -> None:
        if report.when == "call":
            if report.passed:
                self.add_record(report, "passed")
            elif report.skipped:
                self.add_record(report, "skipped", self._extract_skip_reason(report))
            elif report.failed:
                self.add_record(report, "failed", getattr(report, "longreprtext", ""))
        elif report.when == "setup":
            if report.skipped:
                self.add_record(report, "skipped", self._extract_skip_reason(report))
            elif report.failed:
                self.add_record(report, "failed", getattr(report, "longreprtext", ""))
        elif report.when == "teardown" and report.failed:
            self.add_record(report, "failed", getattr(report, "longreprtext", ""))
        if report.when == "teardown":
            self._purity.restore()

    def add_record(self, report, status: str, message: str = "") -> None:
        nodeid = getattr(report, "nodeid", "")
        duration = max(0.0, float(getattr(report, "duration", 0.0)))
        location = getattr(report, "location", ("", None, ""))
        test_file = location[0] if location else ""
        for idx, existing in enumerate(self._record_list):
            if existing.test_id == nodeid:
                if status == "failed":
                    fail_msg = (
                        existing.message
                        if existing.status == "failed" and existing.message
                        else (message or existing.message)
                    )
                    self._record_list[idx] = TestRecord(
                        test_id=nodeid,
                        test_file=test_file or existing.test_file,
                        status="failed",
                        duration_seconds=existing.duration_seconds + duration,
                        message=fail_msg,
                    )
                    self._recorded_nodeids.add(nodeid)
                    self.test_records = tuple(self._record_list)
                return
        self._recorded_nodeids.add(nodeid)
        self._record_list.append(
            TestRecord(
                test_id=nodeid,
                test_file=test_file,
                status=status,
                duration_seconds=duration,
                message=message,
            ),
        )
        self.test_records = tuple(self._record_list)


__all__ = (
    "RecordingPytestPlugin",
    "prepare_go_test_environment",
    "pytest_environment_for",
)

import subprocess
import unittest
from typing import NoReturn
from io import StringIO
from unittest.mock import patch

from repomap_test_support.postgres_harness import (
    PostgresIpcGuard,
    SharedMemorySegment,
    cleanup_postgres_shared_memory_leaks,
    parse_ipcs_shared_memory,
    shared_memory_cleanup_candidates,
)


def unexpected_runner(*args: object, **kwargs: object) -> NoReturn:
    raise AssertionError("command-plan inspection must not execute a process")


class PostgresSharedMemoryUnitTests(unittest.TestCase):
    def setUp(self) -> None:
        # These command-plan contracts use explicit fake runners. The managed
        # Docker ownership path has separate SDK-double unit contracts.
        active_run = patch(
            "repomap_test_support.postgres_container.active_resource_run",
            return_value=None,
        )
        active_run.start()
        self.addCleanup(active_run.stop)

    def test_baseline_segment_is_never_removed(self):
        baseline = (
            SharedMemorySegment(
                shmid="100",
                owner="slair",
                creator="slair",
                nattch=0,
                size=56,
            ),
        )

        candidates = shared_memory_cleanup_candidates(
            baseline=baseline,
            current=baseline,
            current_user="slair",
        )

        self.assertEqual(candidates, ())

    def test_non_current_user_segment_is_never_removed(self):
        current = (
            SharedMemorySegment(
                shmid="101",
                owner="postgres",
                creator="postgres",
                nattch=0,
                size=56,
            ),
        )

        candidates = shared_memory_cleanup_candidates(
            baseline=(),
            current=current,
            current_user="slair",
        )

        self.assertEqual(candidates, ())

    def test_attached_segment_is_never_removed(self):
        current = (
            SharedMemorySegment(
                shmid="102",
                owner="slair",
                creator="slair",
                nattch=1,
                size=56,
            ),
        )

        candidates = shared_memory_cleanup_candidates(
            baseline=(),
            current=current,
            current_user="slair",
        )

        self.assertEqual(candidates, ())

    def test_new_current_user_unattached_postgres_segment_is_selected(self):
        current = (
            SharedMemorySegment(
                shmid="103",
                owner="slair",
                creator="slair",
                nattch=0,
                size=56,
            ),
        )

        candidates = shared_memory_cleanup_candidates(
            baseline=(),
            current=current,
            current_user="slair",
        )

        self.assertEqual(candidates, current)

    def test_live_test_processes_skip_cleanup_candidates(self):
        current = (
            SharedMemorySegment(
                shmid="104",
                owner="slair",
                creator="slair",
                nattch=0,
                size=56,
            ),
        )

        candidates = shared_memory_cleanup_candidates(
            baseline=(),
            current=current,
            current_user="slair",
            live_test_processes=True,
        )

        self.assertEqual(candidates, ())

    def test_parse_ipcs_shared_memory_reads_macos_a_output(self):
        output = """\
IPC status from <running system> as of Mon Jun 29 23:45:50 EDT 2026
T     ID     KEY        MODE       OWNER    GROUP  CREATOR   CGROUP NATTCH  SEGSZ  CPID  LPID   ATIME    DTIME    CTIME
Shared Memory:
m 196609 0x00000000 --rw------- slair staff slair staff 0 56 100 0 no-entry no-entry 23:40
"""

        segments = parse_ipcs_shared_memory(output)

        self.assertEqual(
            segments,
            (
                SharedMemorySegment(
                    shmid="196609",
                    owner="slair",
                    creator="slair",
                    nattch=0,
                    size=56,
                ),
            ),
        )

    def test_cleanup_skips_when_ipcs_is_unavailable(self):
        calls = []

        def runner(command, **kwargs):
            calls.append(command)
            raise FileNotFoundError("ipcs")

        report = cleanup_postgres_shared_memory_leaks(
            baseline=(),
            current_user="slair",
            runner=runner,
        )

        self.assertEqual(report.removed_shmids, ())
        self.assertEqual(calls, [["ipcs", "-m", "-a"]])

    def test_capture_baseline_reports_unavailable_ipcs_before_initdb(self):
        stderr = StringIO()

        def runner(command, **kwargs):
            return subprocess.CompletedProcess(
                command,
                1,
                stdout="",
                stderr="ipcs: sysctlbyname: Operation not permitted",
            )

        guard = PostgresIpcGuard(
            current_user="slair",
            runner=runner,
            stderr=stderr,
        )

        self.assertFalse(guard.capture_baseline())
        self.assertIsNone(guard.baseline)
        self.assertIn("refusing to start", stderr.getvalue())

    def test_cleanup_reports_when_baseline_is_unavailable(self):
        stderr = StringIO()

        report = cleanup_postgres_shared_memory_leaks(
            baseline=None,
            current_user="slair",
            stderr=stderr,
        )

        self.assertTrue(report.unavailable)
        self.assertEqual(report.removed_shmids, ())
        self.assertIn("baseline unavailable", stderr.getvalue())

    def test_cleanup_command_receives_only_selected_shmids(self):
        calls = []
        ipcs_output = """\
T     ID     KEY        MODE       OWNER    GROUP  CREATOR   CGROUP NATTCH  SEGSZ  CPID  LPID   ATIME    DTIME    CTIME
Shared Memory:
m 201 0x00000000 --rw------- slair staff slair staff 0 56 100 0 no-entry no-entry 23:40
m 202 0x00000000 --rw------- other staff other staff 0 56 100 0 no-entry no-entry 23:40
m 203 0x00000000 --rw------- slair staff slair staff 2 56 100 0 no-entry no-entry 23:40
"""

        def runner(command, **kwargs):
            calls.append(command)
            if command == ["ipcs", "-m", "-a"]:
                return subprocess.CompletedProcess(
                    command,
                    0,
                    stdout=ipcs_output,
                    stderr="",
                )
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

        report = cleanup_postgres_shared_memory_leaks(
            baseline=(),
            current_user="slair",
            runner=runner,
        )

        self.assertEqual(report.removed_shmids, ("201",))
        self.assertEqual(calls, [["ipcs", "-m", "-a"], ["ipcrm", "-m", "201"]])

    def test_cleanup_reports_ambiguous_new_current_user_segments(self):
        calls = []
        stderr = StringIO()
        ipcs_output = """\
T     ID     KEY        MODE       OWNER    GROUP  CREATOR   CGROUP NATTCH  SEGSZ  CPID  LPID   ATIME    DTIME    CTIME
Shared Memory:
m 301 0x00000000 --rw------- slair staff slair staff 0 4096 100 0 no-entry no-entry 23:40
"""

        def runner(command, **kwargs):
            calls.append(command)
            return subprocess.CompletedProcess(
                command,
                0,
                stdout=ipcs_output,
                stderr="",
            )

        report = cleanup_postgres_shared_memory_leaks(
            baseline=(),
            current_user="slair",
            runner=runner,
            stderr=stderr,
        )

        self.assertEqual(report.removed_shmids, ())
        self.assertEqual(report.skipped_shmids, ("301",))
        self.assertEqual(calls, [["ipcs", "-m", "-a"]])
        self.assertIn("ambiguous", stderr.getvalue())

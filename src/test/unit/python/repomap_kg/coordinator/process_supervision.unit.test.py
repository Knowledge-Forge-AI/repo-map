from typing import IO, cast
from io import BytesIO
from pathlib import Path

import pytest

import repomap_kg.coordinator.process_supervision as supervision


class FakeProcess:
    pid: int = 101
    stdin: IO[bytes] | None = BytesIO()
    stdout: IO[bytes] | None = BytesIO()
    stderr: IO[bytes] | None = BytesIO()
    returncode: int | None = None

    def poll(self) -> int | None:
        return self.returncode

    def wait(self, timeout: float | None = None) -> int:
        self.returncode = 0
        return self.returncode

    def terminate(self) -> None:
        self.returncode = 15

    def kill(self) -> None:
        self.returncode = -9


class BaseFakeBoundary:
    kind: str = "fake"

    def assign(self, process: object) -> None:
        pass

    def resume(self, process: object) -> None:
        pass

    def terminate_tree(self) -> None:
        pass

    def terminate_gracefully(self) -> None:
        pass

    def kill_tree(self) -> None:
        pass

    def tree_exists(self) -> bool:
        return False

    def close(self) -> None:
        pass


def test_posix_launch_preserves_process_group_creation(monkeypatch):
    calls = []

    def popen(*args, **kwargs):
        calls.append((args, kwargs))
        return FakeProcess()

    monkeypatch.setattr(supervision.os, "name", "posix")
    handle = supervision.launch_managed_process(
        ("python", "-c", "pass"), {}, Path("/tmp"), popen_factory=popen
    )

    assert calls[0][1]["shell"] is False
    assert calls[0][1]["start_new_session"] is True
    assert handle.supervision_kind == "posix_process_group"


def test_windows_launch_assigns_job_before_resuming(monkeypatch):
    events: list[tuple[object, ...]] = []

    class FakeJob:
        kind = "windows_job_object"

        def assign(self, process):
            events.append(("assign", process.pid))

        def resume(self, process):
            events.append(("resume", process.pid))

        def terminate_tree(self):
            events.append(("kill_tree",))

        def close(self):
            events.append(("close",))

        def tree_exists(self):
            return False

    def popen(*args, **kwargs):
        events.append(("popen", kwargs["creationflags"]))
        return FakeProcess()

    monkeypatch.setattr(supervision.os, "name", "nt")
    monkeypatch.setattr(supervision.subprocess, "CREATE_SUSPENDED", 0x4, raising=False)
    monkeypatch.setattr(supervision, "WindowsJobObject", FakeJob)

    handle = supervision.launch_managed_process(
        ("python.exe", "-c", "pass"),
        {"SystemRoot": r"C:\\Windows"},
        Path("C:\\work"),
        popen_factory=popen,
    )

    assert events[:3] == [("popen", 0x4), ("assign", 101), ("resume", 101)]
    assert handle.supervision_kind == "windows_job_object"
    handle.kill_tree()
    handle.close()
    assert events[-2:] == [("kill_tree",), ("close",)]


def test_windows_launch_failure_closes_job_before_rethrow(monkeypatch):
    events = []

    class FakeJob:
        def assign(self, _process):
            events.append("assign")
            raise supervision.ProcessBoundaryError("assign_failed")

        def close(self):
            events.append("close")

    monkeypatch.setattr(supervision.os, "name", "nt")
    monkeypatch.setattr(supervision.subprocess, "CREATE_SUSPENDED", 0x4, raising=False)
    monkeypatch.setattr(supervision, "WindowsJobObject", FakeJob)
    monkeypatch.setattr(supervision.subprocess, "Popen", lambda *a, **k: FakeProcess())

    with pytest.raises(supervision.ProcessBoundaryError, match="assign_failed"):
        supervision.launch_managed_process(
                ("python.exe",),
                {"SystemRoot": r"C:\\Windows"},
                Path("C:\\work"),
            popen_factory=supervision.subprocess.Popen,
        )

    assert events == ["assign", "close"]


def test_managed_process_properties_and_delegation():
    process = FakeProcess()

    class DummyBoundary(BaseFakeBoundary):
        kind = "dummy"

        def close(self):
            pass

    handle = supervision.ManagedProcess(process, DummyBoundary())
    assert handle.pid == 101
    assert handle.stdin is process.stdin
    assert handle.stdout is process.stdout
    assert handle.stderr is process.stderr
    returncode_before = handle.returncode
    assert returncode_before is None
    poll_before = handle.poll()
    assert poll_before is None
    assert handle.wait(timeout=1.0) == 0
    returncode_after = handle.returncode
    assert returncode_after == 0
    poll_after = handle.poll()
    assert poll_after == 0


def test_posix_process_group_tree_signals_and_tree_exists(monkeypatch):
    import signal

    signals_sent = []

    def fake_killpg(pid, sig):
        signals_sent.append((pid, sig))
        if sig == 0 and getattr(fake_killpg, "raise_lookup", False):
            raise ProcessLookupError()
        if sig == 0 and getattr(fake_killpg, "raise_perm", False):
            raise PermissionError()

    monkeypatch.setattr(supervision.os, "killpg", fake_killpg)
    group = supervision.PosixProcessGroup(456)
    group.assign(None)
    group.resume(None)
    group.close()

    group.terminate_gracefully()
    assert (456, signal.SIGTERM) in signals_sent

    group.terminate_tree()
    assert signals_sent.count((456, signal.SIGTERM)) == 2

    group.kill_tree()
    assert (456, signal.SIGKILL) in signals_sent

    assert group.tree_exists() is True
    setattr(fake_killpg, "raise_lookup", True)
    assert group.tree_exists() is False
    setattr(fake_killpg, "raise_lookup", False)
    setattr(fake_killpg, "raise_perm", True)
    assert group.tree_exists() is True

    def failing_killpg(pid, sig):
        raise ProcessLookupError()

    monkeypatch.setattr(supervision.os, "killpg", failing_killpg)
    supervision._signal_group(456, signal.SIGTERM)

    def perm_failing_killpg(pid, sig):
        raise PermissionError()

    monkeypatch.setattr(supervision.os, "killpg", perm_failing_killpg)
    supervision._signal_group(456, signal.SIGTERM)


def test_posix_launch_managed_process_os_error(monkeypatch):
    def failing_popen(*args, **kwargs):
        raise OSError("exec error")

    monkeypatch.setattr(supervision.os, "name", "posix")
    with pytest.raises(supervision.ProcessBoundaryError, match="worker launch failed"):
        supervision.launch_managed_process(
            ("python", "-c", "pass"),
            {},
            Path("/tmp"),
            popen_factory=failing_popen,
        )


def test_managed_process_cleanup_flow():
    import subprocess

    class LifecycleBoundary(BaseFakeBoundary):
        kind = "test_boundary"

        def __init__(self):
            self.closed = 0
            self.terminated_gracefully = 0
            self.killed_tree = 0
            self.exists = False

        def terminate_gracefully(self):
            self.terminated_gracefully += 1

        def kill_tree(self):
            self.killed_tree += 1

        def tree_exists(self):
            return self.exists

        def close(self):
            self.closed += 1

    proc1 = FakeProcess()
    boundary = LifecycleBoundary()
    handle = supervision.ManagedProcess(proc1, boundary)
    assert handle.cleanup(term_timeout=0.1, kill_timeout=0.1) is True
    assert boundary.terminated_gracefully == 1
    assert boundary.closed == 1
    handle.close()
    assert boundary.closed == 1

    class UnstoppableProcess(FakeProcess):
        def wait(self, timeout=None):
            raise subprocess.TimeoutExpired(cmd="fake", timeout=timeout or 0)

    proc2 = UnstoppableProcess()
    boundary2 = LifecycleBoundary()
    boundary2.exists = True
    handle2 = supervision.ManagedProcess(proc2, boundary2)
    assert handle2.cleanup(term_timeout=0.01, kill_timeout=0.01) is False
    assert boundary2.terminated_gracefully == 1
    assert boundary2.killed_tree == 2
    assert boundary2.closed == 1

    class MinimalBoundary:
        kind = "minimal"

        def __init__(self):
            self.terminated_tree = 0
            self.closed = 0

        def terminate_tree(self):
            self.terminated_tree += 1

        def tree_exists(self):
            return False

        def close(self):
            self.closed += 1

    def _invalid_process_boundary(boundary: MinimalBoundary) -> supervision.ProcessBoundary:
        """Narrow runtime-invalid boundary builder testing fallback termination branches."""
        return cast(supervision.ProcessBoundary, boundary)

    proc3 = FakeProcess()
    min_boundary = MinimalBoundary()
    handle3 = supervision.ManagedProcess(proc3, _invalid_process_boundary(min_boundary))
    handle3.terminate_gracefully()
    assert min_boundary.terminated_tree == 1
    handle3.kill_tree()
    assert min_boundary.terminated_tree == 2
    assert handle3.cleanup(term_timeout=0.1, kill_timeout=0.1) is True


def test_wait_and_wait_boundary_helpers():
    import subprocess

    class TimeoutProcess(FakeProcess):
        def wait(self, timeout=None):
            raise subprocess.TimeoutExpired("test", timeout or 0)

    class StubBoundary(BaseFakeBoundary):
        kind = "stub"

        def __init__(self):
            self.checks = 0

        def tree_exists(self):
            self.checks += 1
            return self.checks < 3

        def close(self):
            pass

    proc = TimeoutProcess()
    handle = supervision.ManagedProcess(proc, StubBoundary())
    assert supervision._wait(handle, 0.01) is False
    assert supervision._wait_boundary(handle, 0.2) is True

    class PersistentBoundary(StubBoundary):
        def tree_exists(self):
            return True

    handle2 = supervision.ManagedProcess(proc, PersistentBoundary())
    assert supervision._wait_boundary(handle2, 0.02) is False


def test_windows_launch_environment_and_os_error(monkeypatch):
    import subprocess

    monkeypatch.setattr(supervision.os, "name", "nt")
    with pytest.raises(supervision.ProcessBoundaryError, match="worker_environment_invalid"):
        supervision.launch_managed_process(
            ("python.exe",),
            {},
            Path("C:\\work"),
        )

    class FakeJob:
        def __init__(self):
            self.closed = False

        def close(self):
            self.closed = True

    job = FakeJob()
    monkeypatch.setattr(supervision, "WindowsJobObject", lambda: job)
    monkeypatch.setattr(supervision.subprocess, "CREATE_SUSPENDED", 0x4, raising=False)

    def failing_popen(*args, **kwargs):
        raise OSError("spawn failed")

    with pytest.raises(supervision.ProcessBoundaryError, match="worker launch failed"):
        supervision.launch_managed_process(
            ("python.exe",),
            {"SystemRoot": r"C:\\Windows"},
            Path("C:\\work"),
            popen_factory=failing_popen,
        )
    assert job.closed is True

    class ErrorProcess:
        def kill(self):
            raise OSError("kill failed")

        def wait(self, timeout=None):
            raise subprocess.TimeoutExpired("proc", 1)

    supervision._dispose_failed_process(ErrorProcess())


def test_windows_handle_failure_uses_public_boundary_error():
    from types import SimpleNamespace
    from repomap_kg.coordinator import _process_supervision_windows as windows

    for process in (object(), SimpleNamespace(_handle="invalid"), SimpleNamespace(_handle=None)):
        with pytest.raises(supervision.ProcessBoundaryError, match="handle is unavailable"):
            windows._popen_handle(process, "_handle")

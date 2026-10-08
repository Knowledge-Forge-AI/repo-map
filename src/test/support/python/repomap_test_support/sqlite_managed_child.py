"""Dedicated managed handle for abruptly terminated SQLite guard and holder children.

Enforces structural ownership of child settlement and abrupt termination.
Hides raw unmanaged kill and SIGKILL dispatch from callers, requiring settlement-aware
central abrupt helpers or managed termination.

Enforced for maintained repository source by static policy and API ownership.
"""

from __future__ import annotations

import os
import signal
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any


class AbruptOwnershipError(RuntimeError):
    """Direct unmanaged termination or bypass of abrupt child ownership contract."""


def settle_cleanup_receipt(pid: int | None) -> None:
    """Require child-originated settlement; cleanup cannot synthesize success."""
    manifest_dir = os.environ.get("COVERAGE_CHILD_MANIFEST_DIR")
    if not manifest_dir or not pid:
        return
    exit_marker = Path(manifest_dir) / f"{pid}.exit"
    start_marker = Path(manifest_dir) / f"{pid}.start"
    try:
        fields = dict(line.split("=", 1) for line in exit_marker.read_text(encoding="utf-8").splitlines() if "=" in line)
        start = dict(line.split("=", 1) for line in start_marker.read_text(encoding="utf-8").splitlines() if "=" in line)
    except (OSError, ValueError) as error:
        raise AssertionError("terminal_receipt_incomplete before abrupt termination") from error
    identity_keys = ("invocation", "suite", "revision", "token", "role", "owner", "ppid", "launch_shape", "pid")
    if fields.get("complete") != "1" or fields.get("pid") != str(pid) or any(
        key not in start or fields.get(key) != start[key] for key in identity_keys
    ):
        raise AssertionError("terminal_receipt_incomplete before abrupt termination")


class ProcessIdentity:
    """Diagnostic identity that cannot be passed to OS signal functions."""

    __slots__ = ("__text",)

    def __init__(self, pid: int) -> None:
        self.__text = str(pid)

    def __str__(self) -> str:
        return self.__text


class ManagedChild:
    """Dedicated managed handle owning settlement and abrupt termination of a child process.

    Enforced for maintained repository source by static policy and API ownership.
    """

    __slots__ = (
        "_ManagedChild__process",
        "_abrupt",
        "barrier",
        "_abruptly_killed",
        "_group_owned",
    )

    def __init__(
        self,
        process: subprocess.Popen[str],
        *,
        abrupt: bool = False,
        barrier: Path | None = None,
        group_owned: bool | None = None,
    ) -> None:
        self.__process = process
        self._abrupt = bool(abrupt)
        self.barrier = barrier
        self._abruptly_killed = False
        self._group_owned = not abrupt if group_owned is None else bool(group_owned)

    @property
    def abrupt(self) -> bool:
        return self._abrupt

    def __setattr__(self, name: str, value: Any) -> None:
        if name in ("_abrupt", "abrupt", "_ManagedChild__process", "__process"):
            import sys
            frame = sys._getframe(1)
            caller_code = frame.f_code
            caller_qualname = getattr(caller_code, "co_qualname", caller_code.co_name)
            if (
                frame.f_globals.get("__name__") != __name__
                or caller_qualname.split(".")[0] != "ManagedChild"
            ):
                raise AbruptOwnershipError(f"Direct mutation of '{name}' on ManagedChild is forbidden")
        super().__setattr__(name, value)

    def __getattribute__(self, name: str) -> Any:
        if name in ("_ManagedChild__process", "__process"):
            import sys
            frame = sys._getframe(1)
            caller_code = frame.f_code
            caller_qualname = getattr(caller_code, "co_qualname", caller_code.co_name)
            if (
                frame.f_globals.get("__name__") != __name__
                or caller_qualname.split(".")[0] != "ManagedChild"
            ):
                raise AbruptOwnershipError("Direct access to private process handle is forbidden")
        return super().__getattribute__(name)

    @property
    def pid(self) -> ProcessIdentity:
        return ProcessIdentity(self.__process.pid)

    @property
    def returncode(self) -> int | None:
        return self.__process.returncode

    @property
    def stdin(self) -> Any:
        return self.__process.stdin

    @property
    def stdout(self) -> Any:
        return self.__process.stdout

    @property
    def stderr(self) -> Any:
        return self.__process.stderr

    @property
    def args(self) -> Any:
        return self.__process.args

    def poll(self) -> int | None:
        return self.__process.poll()

    def wait(self, timeout: float | None = None) -> int:
        return self.__process.wait(timeout=timeout)

    def communicate(
        self,
        input: str | None = None,
        timeout: float | None = None,
    ) -> tuple[str, str]:
        return self.__process.communicate(input=input, timeout=timeout)

    def interrupt(self) -> None:
        """Send one orderly SIGINT to the owned group or individual child."""
        if isinstance(self.barrier, Path) and (self.barrier / "settlement_error").exists():
            err = (self.barrier / "settlement_error").read_text(encoding="utf-8")
            raise AssertionError(f"paused writer settlement error: {err}")
        if self.poll() is None:
            try:
                if self._group_owned:
                    os.killpg(self.__process.pid, signal.SIGINT)
                else:
                    self.__process.send_signal(signal.SIGINT)
            except (ProcessLookupError, OSError):
                pass

    def terminate(self) -> None:
        self.__process.terminate()

    def send_signal(self, signal_num: int) -> None:
        """Send a signal to the child; direct SIGKILL is forbidden outside abrupt ownership."""
        if signal_num == signal.SIGKILL:
            raise AbruptOwnershipError(
                "Direct send_signal(SIGKILL) on ManagedChild is forbidden; use kill_paused_child or kill_holder"
            )
        self.__process.send_signal(signal_num)

    def kill(self) -> None:
        """Direct unmanaged kill() is forbidden; abrupt kill requires settlement ownership."""
        raise AbruptOwnershipError(
            "Direct kill() on ManagedChild is forbidden; use kill_paused_child or kill_holder"
        )

    def settle(self) -> None:
        """Settle child terminal receipt under explicit abrupt contract."""
        if isinstance(self.barrier, Path) and (self.barrier / "settlement_error").exists():
            err = (self.barrier / "settlement_error").read_text(encoding="utf-8")
            raise AssertionError(f"paused writer settlement error: {err}")
        settle_cleanup_receipt(self.__process.pid)

    def kill_abruptly(self, signal_num: int = signal.SIGKILL) -> None:
        """Kill under an explicit abrupt-kill contract with terminal receipt settlement."""
        if not self.abrupt:
            raise AbruptOwnershipError(
                "kill_abruptly requires abrupt=True launch contract on ManagedChild"
            )
        if signal_num != signal.SIGKILL:
            raise AbruptOwnershipError(
                "kill_abruptly is restricted to abrupt SIGKILL; use interrupt() or terminate() for orderly stop"
            )
        try:
            self.settle()
        finally:
            self._abruptly_killed = True
            if self.poll() is None:
                try:
                    self.__process.send_signal(signal_num)
                except (ProcessLookupError, OSError):
                    pass

    def verify_dead_and_group(self) -> None:
        """Require reap and exact owned process/group absence; unknown is failure."""
        if self.poll() is None:
            raise AssertionError("managed child was not reaped")
        probes: list[tuple[Callable[[int, int], None], int]] = [(os.kill, self.__process.pid)]
        if self._group_owned:
            probes.append((os.killpg, self.__process.pid))
        for probe, identity in probes:
            try:
                probe(identity, 0)
            except ProcessLookupError:
                continue
            raise AssertionError("managed child or owned group remains alive")

    def emergency_escalate(self, *, grace_seconds: float = 2.0) -> None:
        """One managed emergency path; incomplete coverage is a cleanup failure."""
        import time

        primary: Exception | None = None
        try:
            if self._group_owned:
                try:
                    os.killpg(self.__process.pid, signal.SIGKILL)
                except (ProcessLookupError, OSError):
                    pass
            if self.poll() is None:
                try:
                    self.__process.kill()
                except (ProcessLookupError, OSError):
                    pass
            try:
                self.__process.wait(timeout=grace_seconds)
            except subprocess.TimeoutExpired as timeout_err:
                primary = timeout_err

            if primary is None:
                deadline = time.monotonic() + grace_seconds
                while True:
                    try:
                        self.verify_dead_and_group()
                        break
                    except AssertionError as alive_err:
                        if time.monotonic() >= deadline:
                            primary = alive_err
                            break
                        time.sleep(0.01)
        except Exception as err:
            if primary is None:
                primary = err

        try:
            # Never write or synthesize a receipt after killing. Coverage-armed
            # children that did not settle authentically fail the owning run.
            settle_cleanup_receipt(self.__process.pid)
        except Exception as settlement_err:
            if primary is None:
                raise
            primary.add_note("Secondary cleanup settlement failure: " + type(settlement_err).__name__)
            if primary.__cause__ is None:
                primary.__cause__ = settlement_err

        if primary is not None:
            raise primary

    def terminate_and_reap(self, *, grace_seconds: float = 2.0) -> None:
        """Request orderly termination, bounded reap, then managed escalation."""
        if self.poll() is None:
            try:
                self.__process.terminate()
            except (ProcessLookupError, OSError):
                pass
            if self._group_owned:
                try:
                    os.killpg(self.__process.pid, signal.SIGTERM)
                except (ProcessLookupError, OSError):
                    pass
        orderly_primary: Exception | None = None
        try:
            self.__process.wait(timeout=grace_seconds)
            self.verify_dead_and_group()
        except (subprocess.TimeoutExpired, AssertionError) as err:
            orderly_primary = err
            try:
                self.emergency_escalate(grace_seconds=grace_seconds)
            except Exception as escalate_err:
                orderly_primary.add_note("Secondary managed reap failure: " + type(escalate_err).__name__)
                if orderly_primary.__cause__ is None:
                    orderly_primary.__cause__ = escalate_err
                raise orderly_primary
            return
        settle_cleanup_receipt(self.__process.pid)

    def cleanup(self, *, grace_seconds: float = 2.0) -> None:
        """Preserve explicit abrupt settlement; ordinary cleanup is orderly."""
        if not self.abrupt:
            self.terminate_and_reap(grace_seconds=grace_seconds)
            return
        primary = None
        try:
            self.kill_abruptly()
        except Exception as error:
            primary = error
        try:
            self.__process.wait(timeout=grace_seconds)
            self.verify_dead_and_group()
        except (subprocess.TimeoutExpired, AssertionError):
            try:
                self.emergency_escalate(grace_seconds=grace_seconds)
            except Exception as error:
                if primary is None:
                    raise
                primary.add_note("Secondary managed reap failure: " + type(error).__name__)
                if primary.__cause__ is None:
                    primary.__cause__ = error
        if primary is not None:
            raise primary

    def __enter__(self) -> ManagedChild:
        self.__process.__enter__()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> Any:
        return self.__process.__exit__(exc_type, exc_val, exc_tb)

    def __repr__(self) -> str:
        return f"<ManagedChild pid={self.pid} abrupt={self.abrupt}>"


def cleanup_child(
    process: subprocess.Popen[str] | ManagedChild,
    *,
    grace_seconds: float = 2.0,
) -> None:
    """Use one maintained owner for bounded settlement, termination and reap."""
    child = process if isinstance(process, ManagedChild) else ManagedChild(
        process,
        abrupt=bool(getattr(process, "abrupt", False)),
        barrier=getattr(process, "barrier", None),
        group_owned=getattr(process, "group_owned", None),
    )
    child.cleanup(grace_seconds=grace_seconds)


def cleanup_after_failure(process: subprocess.Popen[str] | ManagedChild, primary: BaseException) -> None:
    """Attach bounded secondary diagnostics while preserving the original error."""
    try:
        cleanup_child(process)
    except Exception as secondary:
        primary.add_note("Secondary cleanup settlement failure: " + type(secondary).__name__)
        if primary.__cause__ is None:
            primary.__cause__ = secondary


def child_failure_detail(process: subprocess.Popen[str] | ManagedChild, primary: BaseException) -> str:
    """Read bounded terminal stderr only after cleanup; failures stay observable."""
    from repomap_kg.coordinator._transport_validation import public_diagnostic_summary

    try:
        _, stderr = process.communicate(timeout=2.0)
        return public_diagnostic_summary(stderr) or ""
    except Exception as secondary:
        primary.add_note("Secondary terminal read failure: " + type(secondary).__name__)
        if primary.__cause__ is None:
            primary.__cause__ = secondary
        return ""


ManagedChildProcess = ManagedChild

__all__ = (
    "AbruptOwnershipError",
    "ManagedChild",
    "ManagedChildProcess",
    "cleanup_child",
    "cleanup_after_failure",
    "child_failure_detail",
    "settle_cleanup_receipt",
)

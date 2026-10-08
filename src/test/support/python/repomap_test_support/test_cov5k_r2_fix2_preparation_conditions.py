"""Bounded environmental and operational conditions for preparation scenarios."""

from __future__ import annotations

import hashlib
from pathlib import Path
import socket
import subprocess
import sys
from contextlib import contextmanager
from threading import Event, Thread

from repomap_test_support.test_cov5k_r2_fix2_preparation_execution import (
    _policy,
)
from runner_coverage_execution import prepare_child_coverage_environment


@contextmanager
def _condition_activity(condition: str, temp_root: Path, identity: str):
    """Keep the selected bounded condition active while the worker runs."""

    if condition == "quiet_success":
        yield ("quiet", True)
        return
    if condition == "cpu_contention":
        process = subprocess.Popen(
            [sys.executable, "-c", "sum(i*i for i in range(20_000_000))"],
            shell=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=prepare_child_coverage_environment(family="unmeasured"),
        )
        try:
            yield ("contention_pid", process.pid)
        finally:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=3)
        return
    stop = Event()
    if condition == "filesystem_contention":
        path = temp_root / f"{identity}.contention"

        def churn_file() -> None:
            counter = 0
            while not stop.is_set():
                path.write_bytes(hashlib.sha256(str(counter).encode("ascii")).digest())
                counter += 1

        thread = Thread(target=churn_file, name="fix2-filesystem-contention")
        thread.start()
        try:
            yield ("contention_path_digest", hashlib.sha256(identity.encode("ascii")).hexdigest())
        finally:
            stop.set()
            thread.join(timeout=3)
            path.unlink(missing_ok=True)
        return
    if condition == "connection_churn":
        left, right = socket.socketpair()

        def churn_connection() -> None:
            while not stop.is_set():
                try:
                    left.sendall(b"x")
                    right.recv(1)
                except OSError:
                    return

        thread = Thread(target=churn_connection, name="fix2-connection-churn")
        thread.start()
        try:
            yield ("connection_family", left.family.name)
        finally:
            stop.set()
            left.close()
            right.close()
            thread.join(timeout=3)
        return
    if condition == "complete_gate_prelude":
        yield ("derived_end_to_end_ms", _policy().derived_end_to_end_ms)
        return
    if condition == "immediate_second_attempt":
        yield ("reacquisition", "immediate")
        return
    raise ValueError("unknown preparation condition")

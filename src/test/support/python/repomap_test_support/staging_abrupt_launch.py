"""Test-owned observers around real supervisors for the sealed abrupt leg."""

from contextlib import contextmanager
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace
from unittest.mock import patch

from runner_abrupt_evidence import active_abrupt_context


@contextmanager
def observe_go_hang(command):
    import repomap_kg.extractors.languages.go_protocol as owner
    context = active_abrupt_context()
    launch = context.begin("go-helper-hang")
    popen = owner.subprocess.Popen
    validate = owner.validate_go_protocol_message
    thread_factory = owner.threading.Thread
    event_factory = owner.threading.Event
    threads = []

    def start(argv, **kwargs):
        if tuple(argv[:len(command)]) != tuple(command) or "env" in kwargs:
            raise RuntimeError("unexpected Go abrupt launch command")
        return launch.launched(popen(argv, env=context.child_environment(), **kwargs))

    def message(*args, **kwargs):
        result = validate(*args, **kwargs)
        if result.file_end is not None:
            launch.observed_checkpoint("file_end")
        return result

    def thread(*args, **kwargs):
        result = thread_factory(*args, **kwargs)
        threads.append(result)
        return result

    with patch.object(owner, "subprocess", SimpleNamespace(
            Popen=start, PIPE=subprocess.PIPE, TimeoutExpired=subprocess.TimeoutExpired)), \
         patch.object(owner, "validate_go_protocol_message", message), \
         patch.object(owner, "threading", SimpleNamespace(Thread=thread, Event=event_factory)):
        yield launch
    process = launch.process
    launch.settle(process.returncode, cleanup=(
        process.poll() is not None and all(not t.is_alive() for t in threads)
        and all(stream.closed for stream in (process.stdin, process.stdout, process.stderr))))


@contextmanager
def observe_scale28_crash(root: Path):
    import scale28_preparation_worker as owner
    if (root / "descendant.launch.json").exists():
        raise RuntimeError("abrupt checkpoint artifact predates this launch")
    context = active_abrupt_context()
    launch = context.begin("scale28-leader-abrupt")
    start = owner._start_without_ambient_parent_main
    settle = owner.settle_failed_process
    observed = {}

    def spawned(process):
        with context.spawn_environment():
            result = start(process)
        launch.launched(process)
        return result

    def settled(process, *args, **kwargs):
        if process is not launch.process:
            raise RuntimeError("different preparation process settled")
        result = settle(process, *args, **kwargs)
        observed["returncode"] = process.exitcode
        observed["cleanup"] = not process.is_alive() and not owner._process_group_exists(process.pid)
        return result

    with patch.object(owner, "_start_without_ambient_parent_main", spawned), \
         patch.object(owner, "settle_failed_process", settled):
        yield launch
    checkpoint = json.loads((root / "descendant.launch.json").read_text())
    if (checkpoint["leader_pid"] != launch.pid
            or checkpoint["ready"] != str(checkpoint["descendant_pid"])
            or checkpoint["process_group"] != launch.pid):
        raise RuntimeError("descendant startup identity is unproved")
    launch.observed_checkpoint("descendant-created")
    launch.settle(observed.get("returncode"), cleanup=observed.get("cleanup") is True)

"""A closed test-support worker for real owned-worker usage attribution proofs.

``run_usage_worker`` launches this module through the private portable launch
chain with ``collect_usage=True``. Before handing over to the real portable
worker (whose authority guard is installed in ``portable_worker.main``) the
module performs one fixed, public-safe case: burn CPU, hold a resident
allocation, run and wait for a CPU-burning grandchild, leave a grandchild in
the process group, kill itself, or block so the parent can be interrupted.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import resource
import signal
import subprocess
import sys
import time
from types import SimpleNamespace
from typing import Any

CASES = frozenset({"nominal", "burn", "rss", "grandchild-waited", "grandchild-remaining", "sigkill", "block"})
BURN_SECONDS = 0.4
RSS_BYTES = 64 * 1024 * 1024
_BURN = "import time\nend = time.process_time() + {seconds}\nwhile time.process_time() < end:\n    pass\n"


def run_usage_worker(root: Path, case: str, *, probe_path: Path | None = None, cancel_event: Any = None):
    """Seal a one-file graph and run this module as a usage-collecting worker."""
    from common_lore_index.artifacts.parity_harness import seal_graph
    from common_lore_index.artifacts.store import FileSystemArtifactStore
    from common_lore_index.coordinator._portable_capability import (
        PortableExecutionCapability, create_portable_capability,
    )
    from common_lore_index.coordinator._portable_worker_launch import _run_portable_worker_command
    from common_lore_index.graph.multi_source_pipeline import capture_multi_source_candidate
    from repomap_test_support.sealing_governance_fixtures import binding_for, graph_for, write_tree

    assert case in CASES
    graph = graph_for(binding_for("entry", write_tree(root / "source", {"main.py": b"VALUE = 1\n"})))
    store = FileSystemArtifactStore(root / "store")
    manifest = seal_graph(graph, capture_multi_source_candidate(graph), store)
    manifest_reference = store.put(
        manifest.canonical_bytes(), media_type="application/x-repomap-snapshot-manifest-v1+json",
        record_format="canonical-json-v1", privacy=manifest.effective_privacy,
    )
    workspace, private = root / "workspace", root / "private"
    for directory in (workspace, private):
        directory.mkdir(mode=0o700)
    capability = PortableExecutionCapability(
        1, "job-usage", 1, graph.id, store.root, workspace.resolve(), manifest_reference,
        manifest.source_generation, manifest.config_generation, manifest.extractor_generation,
        manifest.canonicalizer_generation, 16 * 1024 * 1024, 16 * 1024 * 1024,
    )
    repo_root = Path(__file__).resolve().parents[5]
    arguments = ["--case", case] + (["--probe-path", str(probe_path)] if probe_path is not None else [])
    return _run_portable_worker_command(
        create_portable_capability(private, capability),
        {"job_id": capability.job_id, "attempt": capability.attempt},
        SimpleNamespace(
            process_deadline_seconds=60.0, heartbeat_seconds=30.0, hello_deadline_seconds=30.0,
            cancellation_after_seconds=60.0, cancel_deadline_seconds=1.0,
            process_termination_grace_seconds=2.0, max_diagnostic_bytes=4096,
            max_protocol_line_bytes=65536, max_array_items=64,
        ),
        module="repomap_test_support.usage_worker", module_arguments=tuple(arguments),
        python_paths=(repo_root / "src/test/support/python", repo_root / "src/main/python"),
        cancel_event=cancel_event, collect_usage=True,
    )


def _burn(seconds: float) -> None:
    end = time.process_time() + seconds
    while time.process_time() < end:
        pass


def _cpu_ns(usage: Any) -> int:
    """The reaper's microsecond-to-nanosecond conversion, user plus system."""
    return round(usage.ru_utime * 10**6) * 1000 + round(usage.ru_stime * 10**6) * 1000


def _write_cpu_witness(descriptor: int) -> None:
    """Record own and waited-children CPU at the end of this worker's life.

    The descriptor is opened before the authority guard is installed; writing
    to an already open descriptor needs no further filesystem authority.
    """
    own = _cpu_ns(resource.getrusage(resource.RUSAGE_SELF))
    waited = _cpu_ns(resource.getrusage(resource.RUSAGE_CHILDREN))
    try:
        os.write(descriptor, f"{own} {waited}\n".encode("ascii"))
    finally:
        os.close(descriptor)


def _grandchild(seconds: float) -> subprocess.Popen[bytes]:
    code = _BURN.format(seconds=seconds) if seconds else "import time; time.sleep(600)"
    return subprocess.Popen(
        (sys.executable, "-I", "-S", "-B", "-c", code),
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        env={"LANG": "C", "LC_ALL": "C", "PATH": ""}, close_fds=True,
    )


def _prepare(case: str, probe_path: Path | None, probe_fd: int | None = None) -> Any:
    held = None
    if case == "burn":
        _burn(BURN_SECONDS)
    elif case == "rss":
        held = bytearray(RSS_BYTES)
        for offset in range(0, RSS_BYTES, 4096):
            held[offset] = 1
    elif case == "grandchild-waited":
        _grandchild(BURN_SECONDS).wait()
    elif case == "grandchild-remaining":
        remaining = _grandchild(0)
        if probe_fd is not None:
            os.write(probe_fd, f"{remaining.pid}\n".encode("ascii"))
    elif case == "sigkill":
        _burn(0.1)
        os.write(2, f"REPOMAP_ABRUPT_CHECKPOINT pre_hello {os.getpid()}\n".encode("ascii"))
        os.kill(os.getpid(), signal.SIGKILL)
    elif case == "block" and probe_path is not None:
        _grandchild(0)
        if probe_fd is not None:
            os.write(probe_fd, f"{os.getpid()}\n".encode("ascii"))
    return held


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--case", required=True, choices=sorted(CASES))
    parser.add_argument("--probe-path")
    known, worker_argv = parser.parse_known_args(argv)
    witness = None
    if known.probe_path:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        flags |= getattr(os, "O_NOFOLLOW", 0)
        witness = os.open(known.probe_path, flags, 0o600)
    held = _prepare(known.case, Path(known.probe_path) if known.probe_path else None, witness)
    from common_lore_index.coordinator import portable_worker
    from common_lore_index.coordinator._portable_semantic_adapter import PortableExecutionError

    original_execute = portable_worker.execute_portable_extraction

    def execute(*args: Any, **kwargs: Any) -> Any:
        if known.case == "block":
            kwargs["cancel_event"].wait(600)
            raise PortableExecutionError("cancelled")
        return original_execute(*args, **kwargs)

    portable_worker.execute_portable_extraction = execute
    try:
        return portable_worker.main(worker_argv)
    finally:
        del held
        if witness is not None and known.case == "grandchild-waited":
            _write_cpu_witness(witness)
        elif witness is not None:
            os.close(witness)


if __name__ == "__main__":
    raise SystemExit(main())

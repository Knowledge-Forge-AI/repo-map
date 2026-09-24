"""Closed subprocess probes for the portable worker's negotiated terminal seam."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
from types import SimpleNamespace
import socket
import subprocess
import sys
import threading

from repomap_kg.artifacts.store import ArtifactIntegrityError
from repomap_kg.coordinator import portable_worker
from repomap_kg.coordinator import _portable_semantic_adapter as semantic_adapter
from repomap_kg.coordinator._portable_semantic_adapter import PortableExecutionError


def run_portable_worker_conformance(
    root: Path,
    case: str,
    *,
    probe_path: Path | None = None,
    cancel_event: threading.Event | None = None,
):
    """Launch the real worker through the closed test-support entrypoint."""

    from repomap_kg.artifacts.parity_harness import seal_graph
    from repomap_kg.artifacts.store import FileSystemArtifactStore
    from repomap_kg.coordinator._portable_capability import (
        PortableExecutionCapability,
        create_portable_capability,
    )
    from repomap_kg.coordinator._portable_worker_launch import (
        _run_portable_worker_command,
    )
    from repomap_kg.graph.multi_source import (
        SourceKind,
        graph_source_binding_id,
        source_selection_policy_id,
    )
    from repomap_kg.graph.multi_source_pipeline import capture_multi_source_candidate
    from repomap_kg.ops.config_binding_records import OpsGraphSourceBindingConfig
    from repomap_kg.ops.config_records import OpsGraphConfig

    source = root / "source"
    source.mkdir(exist_ok=True)
    (source / "main.py").write_text("VALUE = 1\n", encoding="utf-8")
    binding = OpsGraphSourceBindingConfig(
        schema_version=1,
        binding_id=graph_source_binding_id("fixture-graph", "entry"),
        source_definition_id="src1:entry",
        alias="entry",
        revision=1,
        source_kind=SourceKind.FOLDER,
        root_path=str(source),
        root_path_expanded=str(source),
        repository_name="fixture-entry",
        logical_root=".",
        privacy="public-dev",
        evidence_retention="metadata-only",
        extractor_profile="default",
        include_paths=(),
        exclude_paths=(),
        selection_policy_id=source_selection_policy_id((), ()),
        resolution_policy="allow-declared",
        enabled=True,
        role="entry",
    )
    graph = OpsGraphConfig(
        id="fixture-graph",
        name="Fixture",
        root_path="",
        root_path_expanded="",
        repository_name="multi-source",
        privacy="public-dev",
        enabled=True,
        mcp_visible=False,
        extractor_profile="",
        refresh_policy="manual",
        source_bindings=(binding,),
        explicit_source_bindings=True,
    )
    incumbent = capture_multi_source_candidate(graph)
    store = FileSystemArtifactStore(root / "store")
    manifest = seal_graph(graph, incumbent, store)
    manifest_reference = store.put(
        manifest.canonical_bytes(),
        media_type="application/x-repomap-snapshot-manifest-v1+json",
        record_format="canonical-json-v1",
        privacy=manifest.effective_privacy,
    )
    workspace = root / "workspace"
    private = root / "private"
    for directory in (workspace, private):
        directory.mkdir(mode=0o700)
    capability = PortableExecutionCapability(
        1, "job-conformance", 1, graph.id, store.root, workspace.resolve(),
        manifest_reference, manifest.source_generation, manifest.config_generation,
        manifest.extractor_generation, manifest.canonicalizer_generation,
        16 * 1024 * 1024, 16 * 1024 * 1024,
    )
    capability_path = create_portable_capability(private, capability)
    repo_root = Path(__file__).resolve().parents[5]
    module_arguments = ["--case", case]
    if probe_path is not None:
        module_arguments.extend(("--probe-path", str(probe_path)))
    result = _run_portable_worker_command(
        capability_path,
        {"job_id": capability.job_id, "attempt": capability.attempt},
        SimpleNamespace(
            process_deadline_seconds=10.0,
            heartbeat_seconds=2.0,
            hello_deadline_seconds=2.0,
            cancellation_after_seconds=1.0,
            cancel_deadline_seconds=1.0,
            process_termination_grace_seconds=1.0,
            max_diagnostic_bytes=4096,
            max_protocol_line_bytes=65536,
            max_array_items=64,
        ),
        module="repomap_test_support.portable_worker_conformance",
        module_arguments=tuple(module_arguments),
        python_paths=(
            repo_root / "src/test/support/python",
            repo_root / "src/main/python",
        ),
        job_graph_id=(
            "other-graph" if case == "identity-start:mismatch" else None
        ),
        cancel_event=cancel_event,
    )
    return result, store


def _exercise_authority(probe: str, probe_path: Path | None) -> None:
    try:
        if probe in {"read", "caller-source-read"}:
            assert probe_path is not None
            probe_path.read_bytes()
        elif probe == "write":
            assert probe_path is not None
            probe_path.write_bytes(b"denied")
        elif probe == "listdir":
            assert probe_path is not None
            os.listdir(probe_path)
        elif probe == "scandir":
            assert probe_path is not None
            with os.scandir(probe_path) as entries:
                tuple(entries)
        elif probe == "mkdir":
            assert probe_path is not None
            os.mkdir(probe_path / "created")
        elif probe == "remove":
            assert probe_path is not None
            os.remove(probe_path / "file")
        elif probe == "rmdir":
            assert probe_path is not None
            os.rmdir(probe_path / "empty")
        elif probe == "rename":
            assert probe_path is not None
            os.rename(probe_path / "file", probe_path / "renamed")
        elif probe == "replace":
            assert probe_path is not None
            os.replace(probe_path / "file", probe_path / "destination")
        elif probe == "chmod":
            assert probe_path is not None
            os.chmod(probe_path / "file", 0o600)
        elif probe == "link":
            assert probe_path is not None
            os.link(probe_path / "file", probe_path / "linked")
        elif probe == "symlink":
            assert probe_path is not None
            os.symlink(probe_path / "file", probe_path / "linked")
        elif probe == "lazy-import":
            import email.message
            del email  # The probe needs import side effects only.
            raise PortableExecutionError("contract_validation")
        elif probe == "socket":
            socket.socket()
        elif probe == "connect":
            socket.create_connection(("127.0.0.1", 9), timeout=0.01)
        elif probe == "bind-listen":
            listener = socket.socket()
            try:
                listener.bind(("127.0.0.1", 0))
                listener.listen(1)
            finally:
                listener.close()
        elif probe == "dns":
            socket.getaddrinfo("localhost", 0)
        elif probe == "subprocess":
            subprocess.Popen((sys.executable, "-c", "pass"))
        elif probe == "exec":
            os.execv(sys.executable, (sys.executable, "-c", "raise SystemExit(0)"))
        elif probe == "spawn":
            os.posix_spawn(sys.executable, (sys.executable, "-c", "pass"), os.environ)
        elif probe == "system":
            os.system(":")
        elif probe == "fork":
            child = os.fork()
            if child == 0:
                os._exit(0)
            os.waitpid(child, 0)
        elif probe == "forkpty":
            child, descriptor = os.forkpty()
            if child == 0:
                os._exit(0)
            os.close(descriptor)
            os.waitpid(child, 0)
        elif probe == "database-import":
            sys.modules.pop("psycopg", None)
            import psycopg
            del psycopg  # The probe needs import side effects only.
        elif probe == "publisher-import":
            sys.modules.pop("repomap_kg.storage.staged_ingestion", None)
            import repomap_kg.storage.staged_ingestion
            del repomap_kg  # The probe needs import side effects only.
        elif probe == "control-import":
            sys.modules.pop("repomap_kg.coordinator._control_schema", None)
            import repomap_kg.coordinator._control_schema
            del repomap_kg  # The probe needs import side effects only.
        else:
            raise KeyError(probe)
    except PermissionError as error:
        raise PortableExecutionError("unsupported_capability") from error
    raise PortableExecutionError("semantic_workload")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--case", required=True)
    parser.add_argument("--probe-path")
    known, worker_argv = parser.parse_known_args(argv)

    case_kind, _, value = known.case.partition(":")
    if case_kind == "cancel" and value == "drain-at-completion":
        case_kind = "cancel-drain"
    if case_kind == "cancel" and value == "wire-during-semantic":
        case_kind = "cancel-work"
    if case_kind == "terminal-validation" and value.startswith("completion-"):
        case_kind, value = "completion", value.removeprefix("completion-")
    if case_kind == "heartbeat-failure" and value == "late-completion":
        case_kind = "heartbeat-late"
    original_execute = portable_worker.execute_portable_extraction
    original_failure_terminal = portable_worker._failure_terminal
    if case_kind == "cancel-drain":
        original_reader = portable_worker._read_cancellation

        def read_at_completion(session, identity, lock, stop, cancel_event, lifecycle_failed):
            assert stop.wait(5.0), "workload did not reach completion"
            original_reader(session, identity, lock, stop, cancel_event, lifecycle_failed)

        portable_worker._read_cancellation = read_at_completion
    if case_kind == "completion":
        original_write = portable_worker._write

        def write_after_settlement(message):
            if message.get("message_type") == "result":
                assert not any(t is not threading.current_thread() and t.is_alive()
                               for t in threading.enumerate())
            original_write(message)
            if message.get("status") == "succeeded" and value == "duplicate":
                original_write(message)

        portable_worker._write = write_after_settlement
    if case_kind == "heartbeat-late":
        def late_heartbeat(session, identity, lock, stop, lifecycle_failed) -> None:
            threading.Event().wait(1.2)

        portable_worker._heartbeat_loop = late_heartbeat

    if case_kind == "heartbeat-failure":
        portable_worker._heartbeat_loop = lambda *args, **kwargs: None
    if case_kind == "terminal-validation":
        def invalid_terminal(*args, **kwargs):
            terminal = original_failure_terminal(*args, **kwargs)
            terminal["unexpected"] = True
            return terminal

        portable_worker._failure_terminal = invalid_terminal

    def execute(*args, **kwargs):
        if case_kind == "cancel-drain":
            raise PortableExecutionError("semantic_workload")
        if case_kind == "cancel-work":
            def cooperative_checkpoint(name: str) -> None:
                if name == "during_semantic":
                    (Path.cwd() / "ready").write_text("ready\n", encoding="utf-8")
                    assert kwargs["cancel_event"].wait(5.0), "cancel was not delivered"

            return original_execute(*args, **kwargs, checkpoint=cooperative_checkpoint)
        if case_kind in {"completion", "heartbeat-late"}:
            return original_execute(*args, **kwargs)
        if case_kind == "crash":
            if value != "after-materialization":
                os._exit(17)

            def abrupt_checkpoint(name: str) -> None:
                if name == "during_semantic":
                    os.write(2, f"REPOMAP_ABRUPT_CHECKPOINT {name} {os.getpid()}\n".encode("ascii"))
                    os._exit(17)

            return original_execute(*args, **kwargs, checkpoint=abrupt_checkpoint)
        if case_kind == "heartbeat-failure":
            kwargs["cancel_event"].wait(5.0)
            raise PortableExecutionError("semantic_workload")
        if case_kind == "progress-failure":
            kwargs["emit_progress"]("extraction", -1, 1)
            raise PortableExecutionError("semantic_workload")
        if case_kind == "terminal-validation":
            raise PortableExecutionError("semantic_workload")
        if case_kind == "failure":
            raise PortableExecutionError(value)
        if case_kind == "cancel":
            cancel_event = kwargs["cancel_event"]

            def checkpoint(name: str) -> None:
                if name == value:
                    cancel_event.set()

            return original_execute(*args, **kwargs, checkpoint=checkpoint)
        if case_kind == "parent-wait":
            (Path.cwd() / "ready").write_text("ready\n", encoding="utf-8")
            if kwargs["cancel_event"].wait(5.0):
                raise PortableExecutionError("cancelled")
            raise PortableExecutionError("semantic_workload")
        if case_kind == "receipt-cancel":
            raise PortableExecutionError("cancelled")
        if case_kind == "authority":
            _exercise_authority(
                value,
                Path(known.probe_path) if known.probe_path is not None else None,
            )
        raise PortableExecutionError("semantic_workload")

    portable_worker.execute_portable_extraction = execute
    if case_kind in {"receipt", "receipt-cancel"}:
        code = {
            "store_unavailable": "store_unavailable",
            "permission_denied": "permission_denied",
            "receipt_bounds": "artifact_bounds",
            "write_failed": "write_failed",
        }[value]

        class ConfiguredFailureStore:
            def put(self, *args: object, **kwargs: object) -> None:
                raise ArtifactIntegrityError(
                    "boundary write failure",
                    code=code,
                )

        setattr(
            semantic_adapter,
            "FileSystemArtifactStore",
            lambda root: ConfiguredFailureStore(),
        )
    result = portable_worker.main(worker_argv)
    if case_kind == "completion":
        if value == "exit-error":
            return 17
    return result


if __name__ == "__main__":
    raise SystemExit(main())

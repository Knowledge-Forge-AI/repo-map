"""Real guarded SQLite Local publication, replay, failure, and cancellation reports."""

from __future__ import annotations

import json
import os
import select
from pathlib import Path
import subprocess
import sys
import time
from typing import Any

from common_lore_index.ops.config_local import LocalSqliteConfig, load_graph_registry_config_home
from common_lore_index.ops.local_refresh import refresh_local_graph
from common_lore_index.ops.resource_view import ResourceObserver
from repomap_test_support.retrieval_evaluation_canaries import assert_canary_free
from repomap_test_support.retrieval_evaluation_fixture import (
    MIXED_V1_GRAPH_ID,
    materialize_mixed_v1_working_copy,
    write_mixed_v1_sqlite_home,
)
from repomap_test_support.sqlite_local_harness import (
    LocalHarness,
    await_ready,
    kill_paused_child,
    interrupt_paused_child,
    initialize,
    release,
    structured,
    tool,
)
from repomap_test_support.sqlite_managed_child import (
    ManagedChild,
    cleanup_after_failure,
)
from repomap_test_support.sqlite_local_lock_children import attempt
from runner_coverage_observer import popen_observed_process

_TEST_CONTROL_ACK = b"resource-view-test-control-ack-v1\n"
_TEST_CONTROL_ACK_REQUEST = b"resource-view-test-control-ack-request-v1\n"

def _json(completed: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert isinstance(payload, dict)
    return payload


def _home(root: Path, name: str, *, generation: int = 1) -> tuple[Path, Path]:
    working = materialize_mixed_v1_working_copy(root / f"{name}-working", generation=generation)
    home = write_mixed_v1_sqlite_home(root / f"{name}-home", working)
    return home, working

def _init_and_refresh(harness: LocalHarness, home: Path) -> dict[str, Any]:
    init = harness.run(
        "ops", "sqlite-init", "--repo-map-home", str(home), "--graph", MIXED_V1_GRAPH_ID, "--json"
    )
    assert _json(init)["result"] == "initialized"
    return _json(harness.run(
        "ops", "refresh-graph", "--repo-map-home", str(home), "--graph", MIXED_V1_GRAPH_ID, "--json"
    ))

def _assert_private_report(payload: dict[str, Any], *roots: Path) -> None:
    assert payload["schema"] == "cloe-resource-view-v1"
    assert_canary_free(payload)
    encoded = json.dumps(payload, sort_keys=True)
    assert MIXED_V1_GRAPH_ID not in encoded
    for root in roots:
        assert str(root) not in encoded
    assert "TRUNCATABLE_PROSE_PREFIX_MARKER_V1" not in encoded

_OBSERVED_LOCAL_SCRIPT = """
import json, runpy, sys
guard = runpy.run_path(sys.argv[2])
sys.addaudithook(guard["_audit"])
sys.meta_path.insert(0, guard["_PsycopgGuard"]())
guard["_install_psycopg_blocker"]()
guard["_install_pause"]()
from common_lore_index.ops.config_local import load_graph_registry_config_home
from common_lore_index.ops.local_refresh import refresh_local_graph
from common_lore_index.ops.resource_view import ResourceObserver
observer = ResourceObserver()
try:
    result = refresh_local_graph(
        load_graph_registry_config_home(sys.argv[1]), sys.argv[3], resource_observer=observer
    )
except BaseException as error:
    print(json.dumps({
        "raised": type(error).__name__,
        "report": observer.report().to_payload(),
    }), flush=True)
else:
    print(json.dumps({
        "generation": result.generation,
        "run_id": result.run_id,
        "reconciled": result.reconciled,
        "family_counts": dict(result.family_counts),
        "report": observer.report().to_payload(),
    }), flush=True)
"""

def _launch_observed_local(
    harness: LocalHarness, home: Path, *, script: str = _OBSERVED_LOCAL_SCRIPT,
    extra_env: dict[str, str] | None = None, binary: bool = False,
    parent_pid: int | None = None,
) -> ManagedChild:
    raw = popen_observed_process(
        [
            sys.executable, "-c", script, str(home),
            str(Path(__file__).parents[4] / "support/python/repomap_test_support/sqlite_local_guard.py"),
            MIXED_V1_GRAPH_ID,
            *((str(parent_pid),) if parent_pid is not None else ()),
        ],
        family="cli_module", cwd=harness.cwd, env=harness.environment(extra_env),
        stdin=subprocess.PIPE if binary else subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=not binary,
        pid_namespace_relation="shared", start_new_session=True,
    )
    return ManagedChild(raw, group_owned=True)

def _run_guarded_observed_local(
    harness: LocalHarness, home: Path,
) -> dict[str, Any]:
    child = _launch_observed_local(harness, home)
    try:
        stdout, stderr = child.communicate(timeout=300)
        child.verify_dead_and_group()
    except BaseException as error:
        cleanup_after_failure(child, error)
        raise
    assert child.returncode == 0, stderr
    payload = json.loads(stdout)
    assert isinstance(payload, dict)
    return payload

def _wait_child_token(
    child: ManagedChild, expected: bytes, *, deadline_seconds: float = 300.0
) -> None:
    stream = child.stderr
    assert stream is not None
    deadline = time.monotonic() + deadline_seconds
    while time.monotonic() < deadline:
        readable, _, _ = select.select([stream], [], [], 0.25)
        if not readable:
            if child.poll() is not None:
                _, stderr = child.communicate(timeout=2)
                raise AssertionError(f"owned child exited before readiness: {stderr}")
            continue
        token = stream.readline() if expected.endswith(b"\n") else stream.read(len(expected))
        if token == expected:
            return
        if not token:
            break
    raise AssertionError("owned child did not complete the test-control handshake")


def _send_test_control_ack(child: ManagedChild) -> None:
    """Complete the test-control ACK; this is not backend telemetry proof."""
    _wait_child_token(child, _TEST_CONTROL_ACK_REQUEST)
    stdin = child.stdin
    assert stdin is not None
    stdin.write(_TEST_CONTROL_ACK)
    stdin.flush()

_INTERRUPTIBLE_LOCAL_SCRIPT = """
import json, os, runpy, signal, sys, time
TEST_CONTROL_ACK = b"resource-view-test-control-ack-v1\\n"
signal.signal(signal.SIGINT, signal.default_int_handler)
guard = runpy.run_path(sys.argv[2])
sys.addaudithook(guard["_audit"])
sys.meta_path.insert(0, guard["_PsycopgGuard"]())
guard["_install_psycopg_blocker"]()
from common_lore_index.storage.sqlite_local import publisher
from common_lore_index.ops.config_local import load_graph_registry_config_home
from common_lore_index.ops.local_refresh import refresh_local_graph
from common_lore_index.ops.resource_view import ResourceObserver
expected_parent = int(sys.argv[4])
sys.stderr.buffer.write(b"resource-view-test-control-ack-request-v1\\n")
sys.stderr.buffer.flush()
if sys.stdin.buffer.read(len(TEST_CONTROL_ACK)) != TEST_CONTROL_ACK:
    raise RuntimeError("test-control ACK is invalid")
if os.getppid() != expected_parent:
    raise RuntimeError("owned child parent relation is invalid")
def pause(name):
    if name != "after_commit":
        return
    if os.getppid() != expected_parent:
        raise RuntimeError("owned child parent relation is invalid")
    sys.stderr.buffer.write(b"\x01")
    sys.stderr.buffer.flush()
    while True:
        time.sleep(60)
publisher._fault_point = pause
observer = ResourceObserver()
try:
    refresh_local_graph(
        load_graph_registry_config_home(sys.argv[1]), sys.argv[3], resource_observer=observer
    )
except BaseException as error:
    print(json.dumps({
        "raised": type(error).__name__,
        "report": observer.report().to_payload(),
    }), flush=True)
else:
    raise AssertionError("owned child was not interrupted")
"""


def test_observed_local_refresh_matches_unobserved_family_counts(tmp_path: Path) -> None:
    unobserved_home, _ = _home(tmp_path, "unobserved")
    observed_home, observed_working = _home(tmp_path, "observed")
    harness = LocalHarness(tmp_path / "guarded", block_psycopg=True)
    unobserved = _init_and_refresh(harness, unobserved_home)
    init = harness.run(
        "ops", "sqlite-init", "--repo-map-home", str(observed_home),
        "--graph", MIXED_V1_GRAPH_ID, "--json",
    )
    assert _json(init)["result"] == "initialized"
    observed = _run_guarded_observed_local(harness, observed_home)
    assert observed["generation"] == 1
    assert observed["family_counts"] == unobserved["family_counts"]
    payload = observed["report"]
    assert payload["operation"] == "local_refresh"
    assert payload["backend"] == "sqlite"
    assert payload["outcome"] == "published"
    assert payload["instrumentation"] == "complete"
    worker_rows = {
        item["name"]: item for item in payload["metrics"]
        if item["name"] in {"worker_cpu", "worker_peak_rss"}
    }
    assert {row["reason"] for row in worker_rows.values()} == {"not_observed"}
    assert _json(harness.run(
        "ops", "refresh-graph", "--repo-map-home", str(observed_home),
        "--graph", MIXED_V1_GRAPH_ID, "--json",
    ))["accepted_generation"] == 2
    _assert_private_report(payload, observed_home, observed_working)


def test_concurrent_guarded_observed_local_refreshes_serialize_on_graph_lock(
    tmp_path: Path,
) -> None:
    home, _ = _home(tmp_path, "observed-pair")
    harness = LocalHarness(tmp_path / "guarded", block_psycopg=True)
    assert _json(
        harness.run(
            "ops", "sqlite-init", "--repo-map-home", str(home),
            "--graph", MIXED_V1_GRAPH_ID, "--json",
        )
    )["result"] == "initialized"
    database = home / "state" / "sqlite-local" / "graphs" / f"{MIXED_V1_GRAPH_ID}.sqlite3"
    assert attempt(database, harness.environment(), "probe") == "probed"
    barrier = tmp_path / "observed-pair-lock"
    children: list[ManagedChild] = []
    payloads: list[dict[str, Any]] = []
    try:
        children.append(_launch_observed_local(
            harness, home, extra_env=harness.paused_env("after_run_insert", barrier)
        ))
        await_ready(barrier, children[0])
        children.append(_launch_observed_local(harness, home))
        stdout, stderr = children[1].communicate(timeout=300)
        children[1].verify_dead_and_group()
        assert children[1].returncode == 0, stderr
        refused_payload = json.loads(stdout)
        assert isinstance(refused_payload, dict)
        payloads.append(refused_payload)
        release(barrier)
        stdout, stderr = children[0].communicate(timeout=300)
        children[0].verify_dead_and_group()
        assert children[0].returncode == 0, stderr
        published_payload = json.loads(stdout)
        assert isinstance(published_payload, dict)
        payloads.append(published_payload)
    except BaseException as error:
        if barrier.exists():
            release(barrier)
        for child in children:
            if child.poll() is None:
                cleanup_after_failure(child, error)
        raise
    published = [item for item in payloads if "generation" in item]
    refused = [item for item in payloads if "raised" in item]
    assert len(published) == 1 and published[0]["generation"] == 1
    assert len(refused) == 1 and refused[0]["report"]["outcome"] == "not_recorded"
    assert refused[0]["report"]["instrumentation"] == "incomplete"
    state = harness.mcp(
        home,
        [initialize(), tool(2, "repomap_graph_status", {"graph_id": MIXED_V1_GRAPH_ID})],
    )
    assert structured(state, 2)["storage"]["latest_run_id"] == published[0]["run_id"]
    assert attempt(database, harness.environment(), "probe") == "probed"
    for item in payloads:
        _assert_private_report(item["report"], home)


def test_local_replay_report_and_refused_report_preserve_readback(tmp_path: Path) -> None:
    home, working = _home(tmp_path, "reconcile")
    harness = LocalHarness(tmp_path / "guarded", block_psycopg=True)
    first = _init_and_refresh(harness, home)
    assert first["accepted_generation"] == 1
    materialize_mixed_v1_working_copy(working, generation=2)
    barrier = tmp_path / "after-commit"
    child = harness.start(
        "ops", "refresh-graph", "--repo-map-home", str(home), "--graph", MIXED_V1_GRAPH_ID,
        "--json", extra_env=harness.paused_env("after_commit", barrier, abrupt=True),
    )
    try:
        await_ready(barrier, child)
        kill_paused_child(child)
    finally:
        child.communicate()

    config = load_graph_registry_config_home(home)
    assert isinstance(config, LocalSqliteConfig)
    observer = ResourceObserver()
    replay = refresh_local_graph(config, MIXED_V1_GRAPH_ID, resource_observer=observer)
    assert replay.generation == 2 and replay.reconciled is True
    replay_report: dict[str, Any] = observer.report().to_payload()
    assert replay_report["outcome"] == "reconciled_replay"
    assert all(
        item["reason"] == "not_started"
        for item in replay_report["metrics"]
        if item["name"] in {"worker_cpu", "worker_peak_rss"}
    )
    _assert_private_report(replay_report, home, working)

    (working / "companion").rename(tmp_path / "companion-missing")
    refused_observer = ResourceObserver()
    try:
        refresh_local_graph(config, MIXED_V1_GRAPH_ID, resource_observer=refused_observer)
    except ValueError:
        refused_report = refused_observer.report().to_payload()
    else:
        raise AssertionError("missing source unexpectedly refreshed")
    assert refused_report["outcome"] == "not_recorded"
    assert refused_report["instrumentation"] == "incomplete"
    _assert_private_report(refused_report, home, working)
    (tmp_path / "companion-missing").rename(working / "companion")
    status = harness.mcp(
        home,
        [initialize(), tool(2, "repomap_graph_status", {"graph_id": MIXED_V1_GRAPH_ID})],
    )
    assert structured(status, 2)["storage"]["latest_run_id"] == replay.run_id
    recovered = _json(harness.run(
        "ops", "refresh-graph", "--repo-map-home", str(home),
        "--graph", MIXED_V1_GRAPH_ID, "--json",
    ))
    assert recovered["accepted_generation"] == 3


def test_local_sigint_owned_child_reports_unrecorded_after_commit(tmp_path: Path) -> None:
    home, working = _home(tmp_path, "cancel")
    harness = LocalHarness(tmp_path / "guarded", block_psycopg=True)
    first = _init_and_refresh(harness, home)
    assert first["accepted_generation"] == 1
    materialize_mixed_v1_working_copy(working, generation=2)
    child = _launch_observed_local(
        harness, home, script=_INTERRUPTIBLE_LOCAL_SCRIPT, binary=True, parent_pid=os.getpid()
    )
    try:
        _send_test_control_ack(child)
        _wait_child_token(child, b"\x01")
        interrupt_paused_child(child)
        stdout, stderr = child.communicate(timeout=300)
        child.verify_dead_and_group()
    except BaseException as error:
        cleanup_after_failure(child, error)
        raise
    assert child.returncode == 0, stderr
    result = json.loads(stdout)
    assert result["raised"] == "KeyboardInterrupt"
    report = result["report"]
    assert report["outcome"] == "not_recorded"
    assert report["instrumentation"] == "incomplete"
    _assert_private_report(report, home, working)
    accepted = harness.mcp(
        home,
        [initialize(), tool(2, "repomap_graph_status", {"graph_id": MIXED_V1_GRAPH_ID})],
    )
    accepted_storage = structured(accepted, 2)["storage"]
    assert accepted_storage["latest_run_status"] == "complete"
    assert accepted_storage["latest_run_id"] != first["run_id"]
    reconciled = _json(harness.run(
        "ops", "refresh-graph", "--repo-map-home", str(home),
        "--graph", MIXED_V1_GRAPH_ID, "--json",
    ))
    assert reconciled["accepted_generation"] == 2
    assert reconciled["run_id"] == accepted_storage["latest_run_id"]

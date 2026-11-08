"""Guarded SQLite Local CLI children with ``--resource-report`` and offline inspection.

Every child runs through the existing guarded Local harness with the Psycopg
family made unavailable, so these are dependency-light boundary proofs, not
just successful commands in an image that happens to contain the driver.
"""

from __future__ import annotations

import fcntl
import json
import os
from pathlib import Path
from typing import Any

import pytest

import common_lore_index.cli._ops_sqlite_dispatch as sqlite_dispatch
from common_lore_index.cli.main import main
from common_lore_index.ops.local_refresh import refresh_local_graph
from repomap_test_support.resource_report_cli_files import (
    limit, metric, private_directory, report_leftovers, report_payload,
)
from repomap_test_support.sqlite_local_fixtures import graph_toml, write_shell_source, write_sqlite_home
from repomap_test_support.sqlite_local_harness import (
    CHILD_DEADLINE_SECONDS, LocalHarness, await_ready, cleanup_after_failure, cleanup_child,
    interrupt_paused_child,
)

GRAPH, OTHER = "report-local", "report-other"
POSTGRES_IMPLEMENTATION = {
    "common_lore_index.coordinator.local_mode", "common_lore_index.storage.staged_ingestion",
    "common_lore_index.runtime.maintenance", "common_lore_index.ops.refresh", "psycopg",
}


def _setup(tmp_path: Path) -> tuple[Path, Path, Path, LocalHarness, Path]:
    source = write_shell_source(tmp_path / "sources" / "one")
    other = write_shell_source(tmp_path / "sources" / "two")
    home = write_sqlite_home(tmp_path / "home", graph_toml(GRAPH, source) + graph_toml(OTHER, other))
    harness = LocalHarness(tmp_path / "harness", block_psycopg=True)
    for graph in (GRAPH, OTHER):
        _driver_free(harness, harness.run("ops", "sqlite-init", "--repo-map-home", str(home), "--graph", graph))
    return home, source, other, harness, private_directory(tmp_path / "reports")


def _driver_free(harness: LocalHarness, completed: Any) -> Any:
    assert completed.returncode == 0, completed.stderr
    assert harness.forbidden_events() == [], harness.forbidden_events()
    assert not harness.imported_modules() & POSTGRES_IMPLEMENTATION, harness.imported_modules()
    return completed


def _refresh(home: Path, *extra: str) -> tuple[str, ...]:
    return ("ops", "refresh-graph", "--repo-map-home", str(home), "--graph", GRAPH, "--json", *extra)


def test_local_refresh_report_and_offline_inspection_stay_driver_free(tmp_path: Path) -> None:
    home, source, _other, harness, reports = _setup(tmp_path)
    first = json.loads(_driver_free(harness, harness.run(*_refresh(home))).stdout)
    target = reports / "generation-2.json"
    completed = _driver_free(harness, harness.run(*_refresh(home, "--resource-report", str(target))))
    second = json.loads(completed.stdout)
    assert completed.stderr == "" and set(second) == set(first)
    assert (first["accepted_generation"], second["accepted_generation"]) == (1, 2)
    payload = report_payload(
        target, operation="local_refresh", backend="sqlite", outcome="published",
        instrumentation="complete", forbidden=(home, source, tmp_path, GRAPH),
    )
    assert metric(payload, "sealed_manifest_files")["value"] >= 2
    assert metric(payload, "validated_bundle_records")["availability"] == "measured"
    assert limit(payload, "manifest_max_artifacts")["applies_this_call"] is True
    assert report_leftovers(reports) == []

    check = _driver_free(harness, harness.run("ops", "resource-report", "check", "--input", str(target)))
    assert check.stdout.startswith("valid cloe-resource-view-v1: operation local_refresh, outcome published")
    shown = _driver_free(harness, harness.run("ops", "resource-report", "show", "--input", str(target), "--json"))
    assert shown.stdout.encode("utf-8") == target.read_bytes()
    text = _driver_free(harness, harness.run("ops", "resource-report", "show", "--input", str(target)))
    assert "format and domain only" in text.stdout
    assert harness.shim_invocations() == ""


def test_destinations_in_any_source_or_managed_home_refuse_before_capture(tmp_path: Path) -> None:
    home, source, other, harness, _reports = _setup(tmp_path)
    before = sorted(path.name for path in source.iterdir())
    for parent in (
        private_directory(source / "reports"), private_directory(other / "reports"),
        private_directory(home / "reports"),
    ):
        refused = harness.run(*_refresh(home, "--resource-report", str(parent / "r.json")))
        assert refused.returncode == 1
        assert refused.stderr.endswith("ERROR: resource-report-refused: protected_root_overlap\n")
        assert str(tmp_path) not in refused.stderr and not (parent / "r.json").exists()
    alias = tmp_path / "alias-to-source"
    alias.symlink_to(source)
    aliased = harness.run(*_refresh(home, "--resource-report", str(alias / "reports" / "r.json")))
    assert aliased.returncode == 1 and "protected_root_overlap" in aliased.stderr
    assert sorted(path.name for path in source.iterdir()) == sorted([*before, "reports"])
    # No refused attempt captured or published anything: the next refresh is generation 1.
    accepted = json.loads(_driver_free(harness, harness.run(*_refresh(home))).stdout)
    assert accepted["accepted_generation"] == 1


def test_context_pack_report_projects_the_returned_packet(tmp_path: Path) -> None:
    home, source, _other, harness, reports = _setup(tmp_path)
    _driver_free(harness, harness.run(*_refresh(home)))
    target = reports / "context.json"
    completed = harness.run(
        "ops", "context-pack", "--repo-map-home", str(home), "--graph", GRAPH,
        "--mode", "ranked_discovery", "--query", "greet", "--resource-report", str(target),
    )
    assert completed.returncode in {0, 1, 3}, completed.stderr
    assert harness.forbidden_events() == []
    assert not harness.imported_modules() & POSTGRES_IMPLEMENTATION, harness.imported_modules()
    packet = json.loads(completed.stdout)
    payload = report_payload(
        target, operation="compact_context", backend="sqlite", outcome=packet["status"],
        forbidden=(home, source, GRAPH, "greet"),
    )
    statements = metric(payload, "sql_statements_executed")
    assert statements["value"] == packet["work_ledger"]["sql_statements_executed"]
    assert limit(payload, "wall_clock_deadline")["applies_this_call"] is None

    early = reports / "early.json"
    refused = harness.run(
        "ops", "context-pack", "--repo-map-home", str(home), "--graph", GRAPH,
        "--mode", "literal_captured_text", "--query", "greet", "--resource-report", str(early),
    )
    assert refused.returncode == 1 and json.loads(refused.stdout)["status"] == "unavailable"
    assert not early.exists(), "a placeholder-ledger packet never becomes a measured report"


def test_sigint_after_commit_leaves_no_sidecar_and_replay_is_not_relabelled(tmp_path: Path) -> None:
    home, _source, _other, _guarded, reports = _setup(tmp_path)
    harness = LocalHarness(tmp_path / "pause-harness")
    _driver_free(harness, harness.run(*_refresh(home)))
    interrupted = reports / "interrupted.json"
    barrier = tmp_path / "after-commit-barrier"
    writer = harness.start(
        *_refresh(home, "--resource-report", str(interrupted)),
        extra_env=harness.paused_env("after_commit", barrier),
    )
    try:
        await_ready(barrier, writer)
        interrupt_paused_child(writer)
        stdout, _stderr = writer.communicate(timeout=CHILD_DEADLINE_SECONDS)
        writer.settle()
        writer.verify_dead_and_group()
    except BaseException as primary:
        cleanup_after_failure(writer, primary)
        raise
    else:
        if writer.poll() is None:
            cleanup_child(writer)
            writer.communicate()
    assert writer.returncode != 0 and '"accepted_generation"' not in stdout
    assert os.listdir(reports) == [], "an interrupted subject produces no sidecar or temp"
    replay = reports / "replay.json"
    completed = harness.run(*_refresh(home, "--resource-report", str(replay)))
    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout)["accepted_generation"] == 2
    assert "sqlite-local-attempt-reconciled" in completed.stderr
    report_payload(replay, operation="local_refresh", backend="sqlite", outcome="reconciled_replay")


def test_held_destination_descriptor_is_close_on_exec_during_the_real_subject(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    home, _source, _other, _harness, reports = _setup(tmp_path)
    identity = (os.stat(reports).st_dev, os.stat(reports).st_ino)
    held: list[int] = []

    def referencing() -> list[int]:
        found = []
        for name in os.listdir("/dev/fd"):
            try:
                details = os.fstat(int(name))
            except OSError:
                continue
            if (details.st_dev, details.st_ino) == identity:
                found.append(int(name))
        return found

    def observed_refresh(config: Any, graph_id: str, **kwargs: Any) -> Any:
        for descriptor in referencing():
            held.append(descriptor)
            assert fcntl.fcntl(descriptor, fcntl.F_GETFD) & fcntl.FD_CLOEXEC
            assert os.get_inheritable(descriptor) is False
        # The real Local owner launches its worker while the descriptor is held.
        return refresh_local_graph(config, graph_id, **kwargs)

    monkeypatch.setattr(sqlite_dispatch, "refresh_local_graph", observed_refresh)
    target = reports / "in-process.json"
    assert main(list(_refresh(home, "--resource-report", str(target)))) == 0
    assert json.loads(capsys.readouterr().out)["accepted_generation"] == 1
    assert len(held) == 1, "exactly one admitted destination descriptor per invocation"
    report_payload(target, operation="local_refresh", backend="sqlite", outcome="published")
    assert referencing() == [], "the invocation closed its destination descriptor"


def test_offline_check_refuses_unsafe_inputs_in_a_guarded_child(tmp_path: Path) -> None:
    harness = LocalHarness(tmp_path / "harness", block_psycopg=True)
    reports = private_directory(tmp_path / "reports")
    fifo = reports / "fifo.json"
    os.mkfifo(fifo, 0o600)
    (reports / "link.json").symlink_to(fifo)
    shared = reports / "shared.json"
    shared.write_text("{}\n", encoding="utf-8")
    shared.chmod(0o644)
    for name, category in (("fifo.json", "unsafe_input"), ("link.json", "unsafe_input"),
                           ("shared.json", "unsafe_input"), ("absent.json", "unreadable")):
        completed = harness.run("ops", "resource-report", "check", "--input", str(reports / name))
        assert completed.returncode == 1 and completed.stdout == ""
        assert completed.stderr == f"ERROR: resource-report-invalid: {category}\n"
    assert harness.forbidden_events() == []  # the FIFO was refused without being opened


def test_destination_admission_refuses_real_unsafe_paths_before_any_refresh(tmp_path: Path) -> None:
    home, _source, _other, harness, reports = _setup(tmp_path)
    shared = tmp_path / "shared-reports"
    shared.mkdir(mode=0o755)
    shared.chmod(0o755)
    regular = tmp_path / "regular-parent"
    regular.write_bytes(b"parent sentinel")
    alias = tmp_path / "report-alias"
    alias.symlink_to(reports, target_is_directory=True)
    existing = reports / "existing.json"
    existing.write_bytes(b"destination sentinel")
    directory = reports / "directory.json"
    directory.mkdir(mode=0o700)
    dangling = reports / "dangling.json"
    dangling.symlink_to(reports / "absent.json")
    fifo = reports / "fifo.json"
    os.mkfifo(fifo, 0o600)
    cases = (
        ("", "invalid_destination"),
        (str(reports) + os.sep, "invalid_destination"),
        (str(reports / ".." / "outside.json"), "invalid_destination"),
        (str(tmp_path / "absent" / "r.json"), "parent_missing"),
        (str(regular / "r.json"), "parent_not_directory"),
        (str(alias / "r.json"), "parent_symlink"),
        (str(shared / "r.json"), "parent_not_private"),
        *((str(path), "destination_exists") for path in (existing, directory, dangling, fifo)),
    )
    before = {p.relative_to(home): p.read_bytes() for p in home.rglob("*") if p.is_file()}
    for target, category in cases:
        completed = harness.run(*_refresh(home, "--resource-report", target))
        assert completed.returncode == 1 and completed.stdout == ""
        assert completed.stderr == f"ERROR: resource-report-refused: {category}\n"
        assert str(tmp_path) not in completed.stderr
        assert report_leftovers(reports) == []
    assert {p.relative_to(home): p.read_bytes() for p in home.rglob("*") if p.is_file()} == before
    assert existing.read_bytes() == b"destination sentinel"
    assert regular.read_bytes() == b"parent sentinel"
    assert dangling.is_symlink() and not dangling.exists()
    assert directory.is_dir() and not any(directory.iterdir())
    assert harness.forbidden_events() == []
    accepted = json.loads(_driver_free(harness, harness.run(*_refresh(home))).stdout)
    assert accepted["accepted_generation"] == 1

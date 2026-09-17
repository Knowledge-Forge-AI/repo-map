"""Actual combine warning policies and owned SQLite allocation/closure evidence."""

from __future__ import annotations

import gc
import json
from pathlib import Path
import sqlite3
import sys
import traceback
import tracemalloc
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch
import warnings

import coverage
from coverage.exceptions import CoverageWarning, NoDataError
import pytest

from runner_coverage import ChildCoverageSession
from runner_coverage_combine import close_runner_data, combine_and_reload
from runner_coverage_execution import execute_shard_combine, validate_shard_file


def run_combine(accumulator, paths=()):
    snapshots: list[dict[str, Any]] = []
    execute_shard_combine(accumulator, list(paths), coverage,
                          lambda **fields: fields, snapshots.append)
    return snapshots


@pytest.mark.parametrize("category", [ResourceWarning, DeprecationWarning, UserWarning])
@pytest.mark.parametrize("policy", ["always", "ignore", "error"])
def test_unrelated_warning_obeys_policy_at_emission(category, policy):
    progressed = []
    source = object()

    def combine(**kwargs):
        warnings.warn_explicit("fixture warning", category, "owned_fixture.py", 17, source=source)
        progressed.append(True)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter(policy, category)
        if policy == "error":
            with pytest.raises(category, match="fixture warning"):
                run_combine(SimpleNamespace(combine=combine))
            assert not progressed
        else:
            snapshots = run_combine(SimpleNamespace(combine=combine))
            assert progressed == [True]
            assert len(caught) == (1 if policy == "always" else 0)
            if caught:
                warning = caught[0]
                assert (warning.category, warning.filename, warning.lineno, warning.source) == (
                    category, "owned_fixture.py", 17, source)
                evidence = json.loads(snapshots[0]["reader_status"])
                assert evidence["category"] == category.__name__
                assert evidence["allocation_origin"] == "unknown"
                assert "tracemalloc_enabled" in evidence
                assert snapshots[0]["file_type"] == "noncoverage_warning"


def test_warning_named_coverage_warning_is_not_authentic():
    class CoverageWarning(UserWarning):
        pass

    def combine(**kwargs):
        warnings.warn("unrelated same name", CoverageWarning)

    with pytest.warns(CoverageWarning, match="unrelated same name"):
        assert run_combine(SimpleNamespace(combine=combine))[0]["file_type"] == "noncoverage_warning"


def test_coverage_warning_is_fatal_even_under_ignore_policy():
    def combine(**kwargs):
        warnings.warn("corrupt coverage", CoverageWarning)

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        with pytest.raises(RuntimeError, match="combine rejected: corrupt coverage"):
            run_combine(SimpleNamespace(combine=combine))


def test_combine_exception_preserves_prior_warning_and_primary_cause():
    snapshots: list[dict[str, Any]] = []
    failure = NoDataError("invalid shard")

    def combine(**kwargs):
        warnings.warn("earlier lifecycle warning", ResourceWarning)
        raise failure

    with pytest.warns(ResourceWarning, match="earlier lifecycle"):
        with pytest.raises(RuntimeError, match="combine failed: invalid shard") as raised:
            execute_shard_combine(SimpleNamespace(combine=combine), [], coverage,
                                  lambda **fields: fields, snapshots.append)
    assert raised.value.__cause__ is failure
    assert [s["file_type"] for s in snapshots] == ["noncoverage_warning", "combine_error"]


def test_combine_exception_preserves_authentic_warning_evidence():
    snapshots: list[dict[str, Any]] = []
    failure = NoDataError("invalid shard")

    def combine(**kwargs):
        warnings.warn_explicit("coverage warning before failure", CoverageWarning, "fixture.py", 19)
        raise failure

    with pytest.raises(RuntimeError, match="combine failed: invalid shard") as raised:
        execute_shard_combine(SimpleNamespace(combine=combine), [], coverage,
                              lambda **fields: fields, snapshots.append)
    assert raised.value.__cause__ is failure
    assert [s["file_type"] for s in snapshots] == ["combine_warning", "combine_error"]
    assert json.loads(snapshots[0]["reader_status"])["lineno"] == 19


def test_cleanup_error_preserves_original_combine_failure():
    original = RuntimeError("combine failure")
    cleanup = RuntimeError("cleanup failure")

    def combine():
        raise original

    def close(**kwargs):
        raise cleanup

    runner = SimpleNamespace(get_data=lambda: SimpleNamespace(close=close))
    with pytest.raises(RuntimeError, match="combine failure") as raised:
        combine_and_reload(runner, combine)
    assert raised.value is original
    assert raised.value.__cause__ is cleanup
    assert "cleanup failed" in raised.value.__notes__[0]


def test_unconsumed_and_actual_corrupt_shards_fail(tmp_path):
    shard = tmp_path / ".coverage.invalid"
    shard.write_bytes(b"not a database")
    with pytest.raises(RuntimeError, match="unconsumed during combine"):
        run_combine(SimpleNamespace(combine=lambda **kwargs: None), [str(shard)])
    accumulator = coverage.Coverage(data_file=str(tmp_path / "combined"), config_file=False)
    try:
        with pytest.raises(RuntimeError, match="combine rejected"):
            run_combine(accumulator, [str(shard)])
    finally:
        close_runner_data(accumulator)


def track_connections(monkeypatch):
    connections = []
    connect = sqlite3.connect

    def tracked(*args, **kwargs):
        connection = connect(*args, **kwargs)
        connections.append((connection, traceback.extract_stack()))
        return connection

    monkeypatch.setattr(sqlite3, "connect", tracked)
    return connections


def assert_closed(connections):
    assert connections
    for connection, _stack in connections:
        with pytest.raises(sqlite3.ProgrammingError, match="closed database"):
            connection.execute("SELECT 1")


def test_session_cleanup_settles_remaining_data_and_scratch_after_close_error(tmp_path):
    session = ChildCoverageSession(coverage_module=coverage, source_root=tmp_path)
    root = session.session_dir
    failure = RuntimeError("owned close failure")
    connection = sqlite3.connect(":memory:")

    def fail_close(**kwargs):
        raise failure

    session._created_collector = SimpleNamespace(
        get_data=lambda: SimpleNamespace(close=fail_close))
    session._combined_runner = SimpleNamespace(
        get_data=lambda: SimpleNamespace(close=lambda **kwargs: connection.close()))
    try:
        with pytest.raises(RuntimeError, match="owned close failure") as raised:
            session.cleanup()
        assert raised.value is failure
        assert not root.exists()
        assert_closed([(connection, [])])
        assert not getattr(session, "_data_settled", False)
    finally:
        session._created_collector = None
        session.cleanup()
        connection.close()


@pytest.mark.parametrize("failure", [False, True])
def test_actual_sqlite_and_coverage_readers_close_on_content_result(tmp_path, monkeypatch, failure):
    shard = tmp_path / ".coverage.child.706.fixture"
    data = coverage.CoverageData(basename=str(shard))
    data.add_lines({"owned.py": {1}})
    data.write()
    data.close(force=True)
    connections = track_connections(monkeypatch)
    expected = "no_selected_hits" if failure else "selected_hits"
    kwargs: dict[str, Any] = dict(sp=str(shard), registered_children={706: {"strict": True, "measurement": expected, "exited": True}},
                  snapshot_fn=lambda **fields: fields, record_fn=lambda record: None, cov_mod=coverage)
    if failure:
        with pytest.raises(RuntimeError, match="measurement content mismatch"):
            validate_shard_file(**kwargs)
    else:
        validate_shard_file(**kwargs)
    assert any(any(frame.name == "validate_shard_file" for frame in stack) for _, stack in connections)
    assert any(any(Path(frame.filename).name == "sqlitedb.py" for frame in stack) for _, stack in connections)
    assert_closed(connections)


@pytest.mark.parametrize("failure", [False, True])
def test_owned_memory_accumulator_settles_on_error_or_after_reporting(tmp_path, monkeypatch, failure):
    connections = track_connections(monkeypatch)
    accumulator = coverage.Coverage(data_file=None, config_file=False)
    data = accumulator.get_data()
    data.add_lines({str(tmp_path / "owned.py"): {1}})

    def combine():
        if failure:
            raise RuntimeError("owned combine failure")

    if failure:
        with pytest.raises(RuntimeError, match="owned combine failure"):
            combine_and_reload(accumulator, combine)
    else:
        # A successful accumulator remains usable until its last report read.
        combine_and_reload(accumulator, combine)
        assert data.lines(str(tmp_path / "owned.py")) == [1]
        close_runner_data(accumulator)
    assert_closed(connections)


def test_warning_allocation_evidence_preserves_available_trace():
    already_tracing = tracemalloc.is_tracing()
    if not already_tracing:
        tracemalloc.start()
    try:
        source = bytearray(32)

        def combine(**kwargs):
            warnings.warn_explicit("traced fixture", ResourceWarning, "fixture.py", 23, source=source)

        with pytest.warns(ResourceWarning, match="traced fixture"):
            snapshots = run_combine(SimpleNamespace(combine=combine))
        evidence = json.loads(snapshots[0]["reader_status"])
        assert evidence["allocation_origin"] == "trace_available"
        assert evidence["allocation_trace"]
        assert evidence["tracemalloc_enabled"] is True
    finally:
        if not already_tracing:
            tracemalloc.stop()


@pytest.mark.skipif(sys.version_info < (3, 13), reason="SQLite deletion warning starts in Python 3.13")
def test_actual_unclosed_sqlite_warning_retains_source_without_corruption_claim():
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", ResourceWarning)

        def combine(**kwargs):
            connection = sqlite3.connect(":memory:")
            connection.execute("SELECT 1").close()
            del connection
            gc.collect()  # Unit-only controlled destructor stimulus, never a runner remedy.

        snapshots = run_combine(SimpleNamespace(combine=combine))
    emitted = [warning for warning in caught if warning.category is ResourceWarning]
    assert emitted
    assert isinstance(emitted[0].source, sqlite3.Connection)
    assert snapshots[0]["file_type"] == "noncoverage_warning"
    # The deliberately leaked fixture is ours; settle its surviving warning source.
    emitted[0].source.close()


@pytest.mark.parametrize("enclosing", [False, True])
def test_real_nested_session_tracks_and_closes_owned_connections(tmp_path, monkeypatch, enclosing):
    source = tmp_path / "source"
    source.mkdir()
    product = source / "nested_fixture_product.py"
    product.write_text("def choose(flag):\n    if flag:\n        return 7\n    return 0\n")
    test = tmp_path / "test_nested.py"
    test.write_text("import nested_fixture_product\ndef test_value():\n    assert nested_fixture_product.choose(True) == 7\n")
    config = tmp_path / "pytest.ini"
    config.write_text("[pytest]\naddopts = --import-mode=importlib\n")
    before = coverage.Coverage.current()
    outer = coverage.Coverage(data_file=str(tmp_path / "outer"), config_file=False) if enclosing else None
    if outer is not None:
        outer.start()
    active = coverage.Coverage.current()
    connections = track_connections(monkeypatch)
    try:
        with patch.object(sys, "path", [str(source), *sys.path]):
            with ChildCoverageSession(coverage_module=coverage, scratch_dir=tmp_path / "session", source_root=source) as session:
                runner = session.create_coverage(coverage)
                runner.start()
                try:
                    assert pytest.main([str(test), "-c", str(config), "-q"]) == 0
                finally:
                    runner.stop()
                    runner.save()
                    combined = session.combine(runner)
                data = combined.get_data()
                assert set(data.lines(str(product)) or []) == {1, 2, 3}
                assert (2, 3) in (data.arcs(str(product)) or [])
                assert (2, 4) not in (data.arcs(str(product)) or [])
            session.cleanup()
            assert coverage.Coverage.current() is active
    finally:
        sys.modules.pop("nested_fixture_product", None)
        sys.modules.pop("test_nested", None)
        if outer is not None:
            outer.stop()
            outer.get_data().close(force=True)
    assert coverage.Coverage.current() is before
    assert_closed(connections)


def test_live_caller_shard_containment_rejection(tmp_path: Path):
    """Exercise live caller shape (ChildCoverageSession.combine) for shard containment."""
    external_dir = tmp_path / "external"
    external_dir.mkdir()
    external_shard = external_dir / ".coverage.external_shard"
    external_shard.write_bytes(b"SQLite format 3\x00" + b"\x00" * 100)

    session_dir = tmp_path / "session"
    session = ChildCoverageSession(scratch_dir=session_dir, coverage_module=coverage)
    session.data_dir.mkdir(parents=True, exist_ok=True)

    # Shard symlink pointing to external directory is rejected by live combine()
    link_shard = session.data_dir / ".coverage.symlink_shard"
    link_shard.symlink_to(external_shard)

    with pytest.raises(RuntimeError, match="coverage shard symlink rejected"):
        session.combine()

    link_shard.unlink()
    parent_symlink = external_dir / "parent_link"
    parent_symlink.symlink_to(external_shard)
    fake_runner = SimpleNamespace(
        get_data=lambda: SimpleNamespace(data_filename=lambda: str(parent_symlink))
    )
    with pytest.raises(RuntimeError, match="parent coverage shard is a symlink"):
        session.combine(fake_runner)

    unreg_shard = session.data_dir / ".coverage.unreg_child_123"
    unreg_shard.write_bytes(b"SQLite format 3\x00" + b"\x00" * 100)
    with pytest.raises(RuntimeError, match="unregistered coverage shard rejected"):
        session.combine()

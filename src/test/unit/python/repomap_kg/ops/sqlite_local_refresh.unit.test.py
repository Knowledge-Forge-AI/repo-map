"""Explicit SQLite Local write authority: ``ops sqlite-init`` and Local refresh.

The Local write path never reaches the PostgreSQL staged publisher, maintenance
admission, the coordinator client or a psql executable; SQLite-home refusals
precede any capture; PostgreSQL homes keep the unchanged dispatcher. Real
capture-to-publication success is owned by the containerized loop owner.
LOCAL3: an attempt is armed before the publisher is entered and settled failed
only on positive proof that COMMIT was never attempted; the source-root check
follows the lock and reconciliation, so an uninitialized graph refuses first.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from repomap_kg.cli import _ops_sqlite_dispatch
from repomap_kg.cli._ops_sqlite_dispatch import dispatch_ops_sqlite_command
from repomap_kg.ops import local_refresh
from repomap_kg.ops.config_local import LocalSqliteConfig, load_graph_registry_config_home
from repomap_kg.ops.local_refresh import LocalRefreshResult, refresh_local_graph
from repomap_kg.storage.sqlite_local.connection import publisher_lock
from repomap_kg.storage.sqlite_local.publisher import FAMILY_ORDER
from repomap_kg.storage.sqlite_local.schema import LocalStoreError
from repomap_test_support.cli_in_process import run_repo_map_in_process
from repomap_test_support.host_read_store_config import fail_if_reached, setup_owned_config
from repomap_test_support.sqlite_local_fixtures import graph_toml, sqlite_home_toml, write_sqlite_home

PG_WRITE_TRIPWIRES = (
    "repomap_kg.ops.portable_refresh.run_staged_portable_refresh",
    "repomap_kg.ops.portable_refresh.effective_postgres_route",
    "repomap_kg.cli.refresh_graph",
    "repomap_kg.cli.maintenance_activity_for_home",
    "repomap_kg.cli.run_coordinator_refresh",
    "repomap_kg.ops.refresh.refresh_graph",
)


def _home(tmp_path: Path) -> Path:
    source = tmp_path / "src"
    source.mkdir()
    return write_sqlite_home(
        tmp_path / "home",
        graph_toml("one", source) + graph_toml("off", source, enabled=False)
        + graph_toml("gone", tmp_path / "missing"),
    )


def _local(home: Path) -> LocalSqliteConfig:
    config = load_graph_registry_config_home(home)
    assert isinstance(config, LocalSqliteConfig)
    return config


def _cli(*args: str) -> tuple[int, str, str]:
    stack = [patch(target, fail_if_reached) for target in PG_WRITE_TRIPWIRES]
    for item in stack:
        item.start()
    try:
        return run_repo_map_in_process(*args)
    finally:
        for item in stack:
            item.stop()


def test_sqlite_init_creates_once_then_reports_current(tmp_path: Path) -> None:
    home = _home(tmp_path)
    code, stdout, stderr = _cli("ops", "sqlite-init", "--repo-map-home", str(home), "--graph", "one", "--json")
    assert code == 0, stderr
    assert json.loads(stdout)["result"] == "initialized"
    code, stdout, _ = _cli("ops", "sqlite-init", "--repo-map-home", str(home), "--graph", "one", "--json")
    assert code == 0 and json.loads(stdout)["result"] == "already-current"
    database = home / "state" / "sqlite-local" / "graphs" / "one.sqlite3"
    assert database.is_file() and (database.stat().st_mode & 0o777) == 0o600
    assert (database.parent.stat().st_mode & 0o777) == 0o700


def test_sqlite_init_refuses_a_postgres_home(tmp_path: Path) -> None:
    home = tmp_path / "pg"
    home.mkdir()
    (home / "repomap.rpl.toml").write_text(setup_owned_config(), encoding="utf-8")
    code, _, stderr = _cli("ops", "sqlite-init", "--repo-map-home", str(home), "--graph", "host-one")
    assert code == 1 and "sqlite-local-home-required" in stderr, stderr


def test_local_refresh_routes_without_postgres_or_admission(tmp_path: Path) -> None:
    home = _home(tmp_path)
    fake = LocalRefreshResult("one", 1, 1, None, {"execution_route": "portable-worker-v1"}, {"files": 1})
    with patch("repomap_kg.cli._ops_sqlite_dispatch.refresh_local_graph", return_value=fake) as called:
        code, stdout, stderr = _cli("ops", "refresh-graph", "--repo-map-home", str(home), "--graph", "one", "--json")
    assert code == 0, stderr
    assert json.loads(stdout)["accepted_generation"] == 1 and called.call_count == 1


@pytest.mark.parametrize(
    ("extra", "code_text"),
    (
        (("--mode", "coordinator"), "sqlite-local-refresh-rejects-coordinator-mode"),
        (("--psql-command", "psql"), "sqlite-local-refresh-rejects-psql-command"),
        (("--staging-event-fd", "9"), "sqlite-local-refresh-rejects-postgres-telemetry"),
    ),
)
def test_local_refresh_refuses_postgres_only_options(
    tmp_path: Path, extra: tuple[str, ...], code_text: str
) -> None:
    home = _home(tmp_path)
    with patch("repomap_kg.cli._ops_sqlite_dispatch.refresh_local_graph", fail_if_reached):
        code, _, stderr = _cli("ops", "refresh-graph", "--repo-map-home", str(home), "--graph", "one", *extra)
    assert code == 1 and code_text in stderr, stderr


def test_sqlite_home_config_errors_are_reported_directly(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    (home / "repomap.rp.toml").write_text(
        sqlite_home_toml('[postgres]\nhost = "h"\n' + graph_toml("one", tmp_path)), encoding="utf-8"
    )
    code, _, stderr = _cli("ops", "refresh-graph", "--repo-map-home", str(home), "--graph", "one")
    assert code == 1 and "PostgreSQL-only and are not allowed" in stderr, stderr
    assert "requires-local-command" not in stderr and "supports PostgreSQL homes only" not in stderr


def test_postgres_home_falls_through_to_the_unchanged_dispatcher(tmp_path: Path) -> None:
    home = tmp_path / "pg"
    home.mkdir()
    (home / "repomap.rpl.toml").write_text(setup_owned_config(), encoding="utf-8")
    args = argparse.Namespace(
        command="ops", ops_command="refresh-graph", repo_map_home=str(home), config=None,
        graph="host-one", mode="direct", psql_command=None, json=True,
    )
    with patch("repomap_kg.cli._ops_sqlite_dispatch.refresh_local_graph", fail_if_reached):
        assert dispatch_ops_sqlite_command(args, fail_if_reached) is None
        missing = argparse.Namespace(**{**vars(args), "repo_map_home": str(tmp_path / "absent")})
        assert dispatch_ops_sqlite_command(missing, fail_if_reached) is None
    coordinator = argparse.Namespace(command="ops", ops_command="refresh-graph", mode="coordinator")
    with patch("repomap_kg.cli._ops_sqlite_dispatch.declared_storage_backend", fail_if_reached):
        assert dispatch_ops_sqlite_command(coordinator, fail_if_reached) is None


def test_refresh_refuses_before_capture_when_uninitialized_disabled_or_rootless(tmp_path: Path) -> None:
    config = _local(_home(tmp_path))
    store = config.graph_store_root
    with patch("repomap_kg.ops.local_refresh.capture_portable_candidate", fail_if_reached):
        for graph_id in ("one", "gone"):  # not-initialized now outranks a missing source root
            with pytest.raises(LocalStoreError) as caught:
                refresh_local_graph(config, graph_id)
            assert caught.value.code == "graph-database-not-initialized"
        assert not store.exists()
        with pytest.raises(ValueError) as refused:
            refresh_local_graph(config, "off")
        assert "disabled" in str(refused.value)
        assert local_refresh.initialize_local_graph(config, "gone")["result"] == "initialized"
        with pytest.raises(ValueError) as refused:
            refresh_local_graph(config, "gone")
        assert "source root is unavailable" in str(refused.value)


def test_refresh_refuses_while_another_publisher_holds_the_graph(tmp_path: Path) -> None:
    home = _home(tmp_path)
    assert _cli("ops", "sqlite-init", "--repo-map-home", str(home), "--graph", "one")[0] == 0
    config = _local(home)
    database = config.graph_store_root / "one.sqlite3"
    with publisher_lock(database), patch(
        "repomap_kg.ops.local_refresh.capture_portable_candidate", fail_if_reached
    ):
        with pytest.raises(LocalStoreError) as caught:
            refresh_local_graph(config, "one")
    assert caught.value.code == "graph-publication-in-progress"


class _Capture:
    def __init__(self) -> None:
        self.marks: list[bool] = []

    def mark_terminal(self, *, accepted: bool) -> None:
        self.marks.append(accepted)


def test_validation_failure_publishes_nothing(tmp_path: Path) -> None:
    home = _home(tmp_path)
    assert _cli("ops", "sqlite-init", "--repo-map-home", str(home), "--graph", "one")[0] == 0
    config = _local(home)
    database = config.graph_store_root / "one.sqlite3"
    before = database.read_bytes()
    capture = _Capture()

    def reject(_capture: Any, *, stage_id: str) -> Any:
        assert stage_id == "sqlite-local"
        raise ValueError("publication bundle framing is invalid")

    with patch("repomap_kg.ops.local_refresh.capture_portable_candidate", return_value=capture), patch(
        "repomap_kg.ops.local_refresh.validate_portable_capture", reject
    ), patch("repomap_kg.ops.local_refresh.publish_generation", fail_if_reached):
        with pytest.raises(ValueError):
            refresh_local_graph(config, "one")
    assert database.read_bytes() == before


def test_postgres_home_with_sqlite_overlay_refuses_both_commands(tmp_path: Path) -> None:
    home = tmp_path / "pg"
    home.mkdir()
    (home / "repomap.rpl.toml").write_text(setup_owned_config(), encoding="utf-8")
    (home / "zz-local.rpl.toml").write_text(
        'schema_version = 1\n[storage]\nbackend = "sqlite"\n', encoding="utf-8"
    )
    with patch.object(_ops_sqlite_dispatch, "refresh_local_graph", fail_if_reached), patch.object(
        _ops_sqlite_dispatch, "initialize_local_graph", fail_if_reached
    ):
        for command in ("refresh-graph", "sqlite-init"):
            code, _, stderr = _cli("ops", command, "--repo-map-home", str(home), "--graph", "host-one")
            assert code == 1, (command, code, stderr)
            assert "conflicts with the postgresql backend of repomap.rpl.toml" in stderr, (command, stderr)
            assert "storage-backend-conflict: " in stderr, (command, stderr)
    assert not (home / "state").exists()


def _terminal_marks(
    tmp_path: Path,
    error: BaseException | None,
    *,
    mark_error: BaseException | None = None,
    arm_error: BaseException | None = None,
    expect: type[BaseException] | None = None,
) -> tuple[list[bool], list[str]]:
    home = _home(tmp_path)
    assert _cli("ops", "sqlite-init", "--repo-map-home", str(home), "--graph", "one")[0] == 0
    events: list[str] = []
    capture = MagicMock()

    def arm(key: str, _value: object, *, sync_directory: bool) -> None:
        assert sync_directory is True
        events.append(f"arm:{key}")
        _raise(arm_error)

    def mark(*, accepted: bool, sync_directory: bool) -> None:
        assert sync_directory is True
        _raise(mark_error)

    capture.annotate.side_effect = arm
    capture.mark_terminal.side_effect = mark
    validated = MagicMock()
    validated.family_spools = {family: [] for family in FAMILY_ORDER}

    def publish(*_args: object, **_kwargs: object) -> Any:
        events.append("publish")
        if error is not None:
            raise error
        return MagicMock(generation=1, run_id=1, previous_run_id=None, family_counts={})

    with patch.object(local_refresh, "capture_portable_candidate", return_value=capture), patch.object(
        local_refresh, "validate_portable_capture", return_value=(MagicMock(), validated)
    ), patch.object(local_refresh, "portable_publication_binding"), patch.object(
        local_refresh, "RunPublicationReceipt"
    ), patch.object(local_refresh, "LocalPublication"), patch.object(
        local_refresh, "publish_generation", publish
    ):
        if expect is None:
            refresh_local_graph(_local(home), "one")
        else:
            with pytest.raises(expect):
                refresh_local_graph(_local(home), "one")
    assert validated.close.call_count == 1
    return [call.kwargs["accepted"] for call in capture.mark_terminal.call_args_list], events


class BaseExceptionOnly(BaseException):
    """A process-control exception type raised by a settlement double."""


def _raise(error: BaseException | None) -> None:
    if error is not None:
        raise error


def _tag(error: BaseException, attribute: str) -> BaseException:
    setattr(error, attribute, True)
    return error


@pytest.mark.parametrize(
    ("error", "marks"),
    (
        (_tag(RuntimeError("before commit"), "is_not_committed"), [False]),
        (_tag(KeyboardInterrupt(), "is_not_committed"), [False]),
        (RuntimeError("untagged"), []),
        (KeyboardInterrupt(), []),
        (_tag(KeyboardInterrupt(), "is_commit_unknown"), []),
        (_tag(SystemExit(3), "is_commit_unknown"), []),
        (_tag(LocalStoreError("graph-database-busy"), "is_commit_unknown"), []),
    ),
    ids=(
        "not-committed", "interrupt-not-committed", "untagged-exception", "untagged-interrupt",
        "interrupt-after-commit", "exit-after-commit", "store-error-after-commit",
    ),
)
def test_attempt_settles_failed_only_on_positive_proof_that_commit_was_never_attempted(
    tmp_path: Path, error: BaseException, marks: list[bool]
) -> None:
    observed, events = _terminal_marks(tmp_path, error, expect=type(error))
    assert observed == marks, observed
    assert events == ["arm:sqlite_local_publication", "publish"], events


def test_success_settles_accepted_and_a_failed_mark_keeps_the_success(tmp_path: Path) -> None:
    for name in ("ok", "unwritable"):
        (tmp_path / name).mkdir()
    assert _terminal_marks(tmp_path / "ok", None)[0] == [True]
    assert _terminal_marks(tmp_path / "unwritable", None, mark_error=OSError("read-only"))[0] == [True]


def test_interrupt_after_publish_returned_never_settles_failed(tmp_path: Path) -> None:
    observed, _ = _terminal_marks(tmp_path, None, mark_error=BaseExceptionOnly(), expect=BaseExceptionOnly)
    assert observed == [True], observed


def test_arming_failure_settles_failed_before_the_publisher(tmp_path: Path) -> None:
    observed, events = _terminal_marks(tmp_path, None, arm_error=OSError("disk full"), expect=OSError)
    assert observed == [False] and events == ["arm:sqlite_local_publication"], (observed, events)


def test_initializer_refuses_while_another_publisher_holds_the_graph(tmp_path: Path) -> None:
    config = _local(_home(tmp_path))
    database = config.graph_store_root / "one.sqlite3"
    with publisher_lock(database):
        with pytest.raises(LocalStoreError) as caught:
            local_refresh.initialize_local_graph(config, "one")
    assert caught.value.code == "graph-publication-in-progress"
    assert not database.exists()
    assert local_refresh.initialize_local_graph(config, "one")["result"] == "initialized"

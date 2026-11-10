"""Ordered steps, outcome classification, interruption and owned cleanup of the installed driver."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from installed_experience_records import decode_intent, decode_observation
from installed_experience_source_identity import Preparation, owner_intent
from repomap_test_support import installed_experience_driver as driver
from repomap_test_support.installed_experience_driver import (
    CleanupRegistry, Observed, OwnerRun, json_object, observed_code, remove_owned_root,
)
from repomap_test_support.installed_environment import ChildExecutionFailure

SOURCE = {"S02": {"graph_catalog_sha256": "a" * 64, "control_catalog_sha256": "b" * 64},
          "S04": {"tools_sha256": "c" * 64}}
INTENT = owner_intent("server", Preparation("1" * 64, 3, "2" * 64, 10, 5, "3" * 64), SOURCE,
                      fixture_digest="4" * 64, candidate_census="5" * 64, python="3.13.12", platform="aarch64")
EXPECTED = {row["id"]: row["expected"] for row in decode_intent(INTENT)["scenarios"]}


class _Coded(RuntimeError):
    code = "projection-hash-mismatch"


def _witness(scenario: str, **override: Any) -> Callable[[], Observed]:
    facts = {key: (value, "child-stdout") for key, value in {**EXPECTED[scenario], **override}.items()}
    origins = {"env-purelib": 1, "system-site": 1} if scenario == "S01" else None
    return lambda: Observed(facts, exit=0, stderr_class="empty", origin_classes=origins)


@pytest.fixture
def bundles(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    base = tmp_path / "first-use-workload"
    base.mkdir(mode=0o700)
    monkeypatch.setattr(driver, "default_bundle_base", lambda _temporary: base)
    return base


def _outcomes(run: OwnerRun) -> list[tuple[str, str, Any]]:
    decoded = [decode_observation(data) for _name, data in run.observations]
    return [(item["scenario"], item["outcome"], item["failure_code"]) for item in decoded]


def test_all_rows_witnessed_are_accepted_and_owned_roots_removed(tmp_path: Path, bundles: Path) -> None:
    owned = tmp_path / "owned root"
    (owned / "venv").mkdir(parents=True)
    run = OwnerRun("server", INTENT)
    run.registry.own(owned)
    for scenario in ("S01", "S02", "S03", "S04"):
        assert run.step(scenario, _witness(scenario)) == "passed"
    root, verdict = run.finish(tmp_path)
    assert verdict.outcome == "accepted" and not owned.exists()
    assert root.parent == bundles / "installed-experience" / "server"
    assert _outcomes(run)[-1] == ("X01", "passed", None)


def test_mismatch_fails_once_and_later_rows_are_not_reached(tmp_path: Path, bundles: Path) -> None:
    run = OwnerRun("server", INTENT)
    assert run.step("S01", _witness("S01", psycopg_version="3.2.12")) == "failed"
    assert run.mismatches == {"S01": ["psycopg_version"]}
    assert run.step("S02", _witness("S02")) == "not-reached"
    _root, verdict = run.finish(tmp_path)
    assert verdict.outcome == "rejected" and "unexpected-outcome" in verdict.categories
    assert _outcomes(run) == [("S01", "failed", "fact-unobserved"), ("S02", "not-reached", None),
                              ("S03", "not-reached", None), ("S04", "not-reached", None),
                              ("X01", "passed", None)]


def test_extra_fact_and_coded_exception_are_failures(tmp_path: Path) -> None:
    run = OwnerRun("server", INTENT)
    assert run.step("S01", lambda: Observed({**_witness("S01")().facts, "path": ("/x", "child-stdout")})) == "failed"
    second = OwnerRun("server", INTENT)

    def raises() -> Observed:
        raise _Coded("refused")

    assert second.step("S01", raises) == "failed"
    assert _outcomes(second) == [("S01", "failed", "projection-hash-mismatch")]


def test_unknown_outcome_makes_the_bundle_incomplete(tmp_path: Path, bundles: Path) -> None:
    run = OwnerRun("server", INTENT)
    run.step("S01", _witness("S01"))
    run.step("S02", _witness("S02"))
    assert run.step("S03", lambda: Observed(unknown=True)) == "unknown"
    _root, verdict = run.finish(tmp_path)
    assert verdict.outcome == "incomplete" and verdict.categories == ("incomplete-step",)
    assert _outcomes(run)[2] == ("S03", "unknown", "child-deadline")


def test_interrupt_records_runs_cleanup_and_propagates(tmp_path: Path) -> None:
    owned = tmp_path / "owned root"
    owned.mkdir()
    run = OwnerRun("server", INTENT)
    run.registry.own(owned)

    def interrupt() -> Observed:
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        run.step("S01", interrupt)
    assert _outcomes(run) == [("S01", "unknown", "interrupted")] and not owned.exists()


def test_rows_must_follow_the_frozen_order() -> None:
    run = OwnerRun("server", INTENT)
    with pytest.raises(Exception):
        run.step("S02", _witness("S02"))
    with pytest.raises(Exception):
        OwnerRun("local", INTENT)


def test_owned_removal_never_follows_symlinks(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep.txt").write_text("keep\n", encoding="utf-8")
    owned = tmp_path / "owned root"
    (owned / "venv" / "bin").mkdir(parents=True)
    (owned / "venv" / "bin" / "python").symlink_to(outside / "keep.txt")
    (owned / "linked dir").symlink_to(outside)
    assert remove_owned_root(owned) and not owned.exists()
    assert (outside / "keep.txt").read_text(encoding="utf-8") == "keep\n"
    link = tmp_path / "root link"
    link.symlink_to(outside)
    assert remove_owned_root(link) and outside.is_dir() and not link.is_symlink()
    assert remove_owned_root(tmp_path / "absent")


def test_retained_worker_workspace_is_reported_never_removed(tmp_path: Path) -> None:
    workspace = tmp_path / "worker workspace"
    workspace.mkdir()
    registry = CleanupRegistry()
    registry.retain(workspace)
    assert registry.run() == "retained-reported" and workspace.is_dir()


def test_retaining_descendant_preserves_owned_ancestor(tmp_path: Path) -> None:
    owned = tmp_path / "owned root"
    workspace = owned / "state" / "worker"
    workspace.mkdir(parents=True)
    marker = workspace / "in-use"
    marker.write_bytes(b"owned worker state")
    registry = CleanupRegistry()
    registry.own(owned)
    registry.retain(workspace)
    assert registry.run() == "retained-reported"
    assert marker.read_bytes() == b"owned worker state"


def test_pass_cannot_hide_nonzero_child_exit() -> None:
    run = OwnerRun("server", INTENT)
    witnessed = _witness("S01")()
    witnessed.exit = 7
    assert run.step("S01", lambda: witnessed) == "failed"
    assert _outcomes(run) == [("S01", "failed", "child-exit-nonzero")]
    assert decode_observation(run.observations[0][1])["exit"] == 7


def test_unsettled_child_is_unknown_and_preserves_owned_workspace(tmp_path: Path, bundles: Path) -> None:
    owned = tmp_path / "owned root"
    owned.mkdir()
    run = OwnerRun("server", INTENT)
    run.registry.own(owned)

    def expired() -> Observed:
        raise ChildExecutionFailure("child-deadline", "partial", "diagnostic")

    assert run.step("S01", expired) == "unknown"
    _root, verdict = run.finish(tmp_path)
    assert verdict.outcome != "accepted" and owned.is_dir()
    assert _outcomes(run)[0] == ("S01", "unknown", "child-deadline")
    assert decode_observation(run.observations[-1][1])["cleanup"] == "retained-reported"


def test_child_output_helpers_are_closed() -> None:
    assert json_object('{"a": 1}') == {"a": 1}
    assert json_object("[1]") is None and json_object("not json") is None
    assert observed_code("", "ERROR: sqlite-restore-target-exists: x\n", ("sqlite-restore-target-exists",)) == (
        "sqlite-restore-target-exists")
    assert observed_code("", "ERROR: graph-database-busy: detail\n", ()) == "graph-database-busy"
    assert observed_code("", "", ()) == "other"


def test_failed_child_strings_never_enter_exported_evidence(tmp_path: Path, bundles: Path) -> None:
    marker = "PRIVATE_PAYLOAD_SENTINEL"
    run = OwnerRun("server", INTENT)
    observed = _witness("S01", psycopg_version=marker, unexpected_field=marker)()
    assert run.step("S01", lambda: observed) == "failed"
    root, verdict = run.finish(tmp_path)
    assert verdict.outcome != "accepted"
    assert all(marker.encode() not in path.read_bytes() for path in root.iterdir() if path.is_file())
    row = decode_observation(run.observations[0][1])
    assert "psycopg_version" not in row["facts"]
    assert "unexpected_field" not in row["facts"]

"""ADR 0089 D10: the D12 owner's cleanup never replaces the initiating failure (no build)."""

from __future__ import annotations

from pathlib import Path
import subprocess
from types import SimpleNamespace
from typing import Any

import pytest

from repomap_test_support import d12_core_image as d12, d12_image_probes as probes
from repomap_test_support.d12_core_image_cleanup import run_candidate_cleanup
from tools.system.config import SystemDeadline
from tools.system.d12_exec import wrap_create_with_bounded_exec
from tools.system.d12_system_evidence import _finish_probe_owner
from tools.system.d12_system_reports import (
    write_bounded_json_atomic,
    write_bounded_json_to_targets,
)


class Reports:
    def __init__(self, failure: Exception | None = None) -> None:
        self.failure = failure
        self.written: list[tuple[str, dict[str, object]]] = []

    def __call__(self, name: str, record: dict[str, object]) -> None:
        if self.failure is not None:
            raise self.failure
        self.written.append((name, dict(record)))


def _steps(error: BaseException | None = None):
    def steps(record: dict[str, object]) -> None:
        record["image"] = "removed"
        if error is not None:
            raise error
    return steps


def test_clean_cleanup_writes_one_record_and_returns_it():
    reports = Reports()
    record = run_candidate_cleanup(None, _steps(), reports)
    assert reports.written == [("cleanup", {"image": "removed", "primary": None})], reports.written
    assert record == {"image": "removed", "primary": None}, record


def test_cleanup_failure_without_primary_is_raised_after_the_report():
    reports, failure = Reports(), RuntimeError("baseline differs")
    with pytest.raises(RuntimeError) as raised:
        run_candidate_cleanup(None, _steps(failure), reports)
    assert raised.value is failure, raised.value
    assert reports.written[0][1]["error"] == "RuntimeError: baseline differs", reports.written


def test_cleanup_failure_with_primary_annotates_and_never_replaces_it():
    reports, primary = Reports(), AssertionError("round trip differs")
    record = run_candidate_cleanup(primary, _steps(OSError("busy")), reports)
    assert record["error"] == "OSError: busy" and record["primary"] == "AssertionError: round trip differs", record
    assert primary.__notes__ == ["D12 candidate cleanup also failed; see cleanup report"], primary.__notes__


@pytest.mark.parametrize("write_failure", [OSError("disk full"), ValueError("report ceiling")])
def test_report_write_failure_annotates_the_primary(write_failure):
    primary = AssertionError("build failed")
    run_candidate_cleanup(primary, _steps(), Reports(write_failure))
    assert primary.__notes__ == [
        f"D12 cleanup report could not be written ({type(write_failure).__name__})"
    ], primary.__notes__


def test_report_write_failure_annotates_a_cleanup_failure_that_is_still_raised():
    failure = RuntimeError("tag left for operator")
    with pytest.raises(RuntimeError) as raised:
        run_candidate_cleanup(None, _steps(failure), Reports(OSError("disk full")))
    assert raised.value is failure, raised.value
    assert failure.__notes__ == ["D12 cleanup report could not be written (OSError)"], failure.__notes__


def test_report_write_failure_alone_is_raised():
    failure = OSError("disk full")
    with pytest.raises(OSError) as raised:
        run_candidate_cleanup(None, _steps(), Reports(failure))
    assert raised.value is failure, raised.value


def test_interrupt_during_cleanup_is_preserved_after_the_report():
    reports = Reports()
    with pytest.raises(KeyboardInterrupt):
        run_candidate_cleanup(None, _steps(KeyboardInterrupt()), reports)
    assert reports.written[0][1]["error"] == "KeyboardInterrupt: ", reports.written


class _FakeProcessOwner:
    def __init__(self, *, cleanup_error: BaseException | None = None, start_error: BaseException | None = None) -> None:
        self.cleanup_error = cleanup_error
        self.start_error = start_error
        self.created: list[str] = []
        self.cleaned: list[str] = []
        self.baseline_checks = 0
        self.containers: dict[str, Any] = {}

    def create(self, image: str, _command: Any, *, role: str = "c", **_opts: Any) -> str:
        cid = f"cid-{role}-{len(self.created)}"
        self.created.append(cid)
        start_err = self.start_error

        def _start() -> None:
            if start_err is not None:
                raise start_err

        self.containers[cid] = SimpleNamespace(
            id=cid,
            status="exited",
            attrs={"Image": image, "Mounts": []},
            start=_start,
            reload=lambda: None,
            wait=lambda **_k: {"StatusCode": 0},
            logs=lambda stdout=True, stderr=False: (
                b"U\t/usr/lib/x86_64-linux-gnu/libunowned.so\nUC\t1\nVC\t0\nO\tDebian\tx86_64\tamd64\n"
                if stdout and not stderr
                else b""
            ),
        )
        return cid

    def cleanup(self, identity: str) -> None:
        self.cleaned.append(identity)
        if self.cleanup_error is not None:
            raise self.cleanup_error

    def verify_baseline(self) -> None:
        self.baseline_checks += 1


def _fake_client(owner: _FakeProcessOwner) -> Any:
    return SimpleNamespace(
        images=SimpleNamespace(get=lambda _img: SimpleNamespace(attrs={"Config": {"Volumes": {}}})),
        containers=SimpleNamespace(get=lambda cid: owner.containers[cid]),
    )


def test_start_server_cleans_exact_container_on_start_or_readiness_failure_and_annotates() -> None:
    env = {"POSTGRES_USER": "d12", "POSTGRES_DB": "d12", "POSTGRES_PASSWORD": "pw"}
    exec_calls: list[list[str]] = []

    def fake_run_cmd(cmd: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        exec_calls.append(list(cmd))
        return subprocess.CompletedProcess(cmd, 1, b"not ready\n", b"waiting\n")

    owner_readiness = _FakeProcessOwner()
    client_readiness = _fake_client(owner_readiness)
    bounded_create = wrap_create_with_bounded_exec(
        probes._create,
        deadline=SystemDeadline(120.0, 20.0),
        default_timeout_seconds=10.0,
        run_cmd=fake_run_cmd,
    )
    with pytest.raises(AssertionError, match="16.15 server never became ready"):
        probes._start_server(
            owner_readiness, client_readiness, env, "linux/amd64", create_fn=bounded_create
        )
    assert owner_readiness.created == ["cid-d12-server-0"]
    assert owner_readiness.cleaned == ["cid-d12-server-0"]
    assert len(exec_calls) == 1 and "pg_isready" in exec_calls[0]

    owner_both_fail = _FakeProcessOwner(
        cleanup_error=OSError("docker rm socket error"),
        start_error=RuntimeError("daemon failed to start server"),
    )
    client_both_fail = _fake_client(owner_both_fail)
    with pytest.raises(RuntimeError, match="daemon failed to start server") as exc_info:
        probes._start_server(
            owner_both_fail, client_both_fail, env, "linux/amd64", create_fn=bounded_create
        )
    assert owner_both_fail.cleaned == ["cid-d12-server-0"]
    assert any(
        "D12 server container cid-d12-server-0 cleanup also failed (OSError: docker rm socket error)" in n
        for n in getattr(exc_info.value, "__notes__", ())
    )

    primary_probe_err = RuntimeError("probe failed after server start")
    owner_post = _FakeProcessOwner(cleanup_error=OSError("rm failed"))
    _finish_probe_owner(owner_post, "cid-d12-server-9", primary_probe_err)
    assert owner_post.cleaned == ["cid-d12-server-9"]
    assert owner_post.baseline_checks == 1
    assert any("rm failed" in n for n in getattr(primary_probe_err, "__notes__", ()))


def test_inventory_unowned_usr_lib_returns_flat_paths_and_bounded_reports_enforce_5mb_cap(
    tmp_path: Path,
) -> None:
    owner = _FakeProcessOwner()
    client = _fake_client(owner)
    inv = probes._inventory(owner, client, "postgres:16", "linux/amd64", "d12-inventory-test")
    assert inv["unowned_usr_lib"] == ["/usr/lib/x86_64-linux-gnu/libunowned.so"]
    assert inv["unowned_count"] == 1
    assert owner.cleaned == ["cid-d12-inventory-test-0"]

    report_dir = tmp_path / "report"
    evidence_dir = tmp_path / "evidence"
    write_bounded_json_atomic(
        report_dir / "session-part-1.json",
        {"blob": "x" * 1_400_000},
        part_limit=d12.REPORT_PART_LIMIT,
        total_limit=d12.REPORT_TOTAL_LIMIT,
        cleanup_reserve=d12.REPORT_CLEANUP_RESERVE,
    )
    write_bounded_json_atomic(
        report_dir / "session-part-2.json",
        {"blob": "y" * 1_400_000},
        part_limit=d12.REPORT_PART_LIMIT,
        total_limit=d12.REPORT_TOTAL_LIMIT,
        cleanup_reserve=d12.REPORT_CLEANUP_RESERVE,
    )
    write_bounded_json_atomic(
        report_dir / "session-part-3.json",
        {"blob": "z" * 1_400_000},
        part_limit=d12.REPORT_PART_LIMIT,
        total_limit=d12.REPORT_TOTAL_LIMIT,
        cleanup_reserve=d12.REPORT_CLEANUP_RESERVE,
    )
    with pytest.raises(ValueError, match="exceeds part limit"):
        write_bounded_json_atomic(
            report_dir / "oversized-part.json",
            {"blob": "p" * d12.REPORT_PART_LIMIT},
            part_limit=d12.REPORT_PART_LIMIT,
            total_limit=d12.REPORT_TOTAL_LIMIT,
            cleanup_reserve=d12.REPORT_CLEANUP_RESERVE,
        )
    with pytest.raises(ValueError, match="exceeds total report budget"):
        write_bounded_json_to_targets(
            (report_dir, evidence_dir),
            "d12-system-candidate-evidence.json",
            {"blob": "s" * 400_000},
            part_limit=d12.REPORT_PART_LIMIT,
            total_limit=d12.REPORT_TOTAL_LIMIT,
            cleanup_reserve=d12.REPORT_CLEANUP_RESERVE,
        )
    assert not (report_dir / "d12-system-candidate-evidence.json").exists()
    assert not (evidence_dir / "d12-system-candidate-evidence.json").exists()
    with pytest.raises(ValueError, match="exceeds total report budget"):
        write_bounded_json_atomic(
            evidence_dir / "session-part-1.json",
            {"blob": "s" * 750_000},
            part_limit=d12.REPORT_PART_LIMIT,
            total_limit=d12.REPORT_TOTAL_LIMIT,
            cleanup_reserve=d12.REPORT_CLEANUP_RESERVE,
            account_dirs=(report_dir,),
        )
    assert not (evidence_dir / "session-part-1.json").exists()
    alias_report_dir = tmp_path / "report-alias"
    alias_report_dir.symlink_to(report_dir)
    dedup_written = write_bounded_json_to_targets(
        (report_dir, report_dir, alias_report_dir),
        "d12-system-candidate-evidence.json",
        {"blob": "s" * 400_000},
        part_limit=d12.REPORT_PART_LIMIT,
        total_limit=d12.REPORT_TOTAL_LIMIT,
        cleanup_reserve=d12.REPORT_CLEANUP_RESERVE,
    )
    assert dedup_written == report_dir / "d12-system-candidate-evidence.json"
    assert (report_dir / "d12-system-candidate-evidence.json").is_file()
    one_dir_replaced = write_bounded_json_to_targets(
        (report_dir,),
        "d12-system-candidate-evidence.json",
        {"blob": "r" * 400_000},
        part_limit=d12.REPORT_PART_LIMIT,
        total_limit=d12.REPORT_TOTAL_LIMIT,
        cleanup_reserve=d12.REPORT_CLEANUP_RESERVE,
    )
    assert one_dir_replaced == report_dir / "d12-system-candidate-evidence.json"
    written = write_bounded_json_to_targets(
        (report_dir, evidence_dir),
        "d12-system-candidate-evidence.json",
        {"ok": True},
        part_limit=d12.REPORT_PART_LIMIT,
        total_limit=d12.REPORT_TOTAL_LIMIT,
        cleanup_reserve=d12.REPORT_CLEANUP_RESERVE,
    )
    assert written == report_dir / "d12-system-candidate-evidence.json"
    assert (evidence_dir / "d12-system-candidate-evidence.json").is_file()

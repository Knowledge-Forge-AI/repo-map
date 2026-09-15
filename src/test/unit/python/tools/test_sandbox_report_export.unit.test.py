from __future__ import annotations

from collections.abc import Callable

from types import FrameType

import test_sandbox as sandbox_owner


from pathlib import Path



import tarfile

import pytest

REPO_ROOT = Path(__file__).resolve().parents[5]

from src.test.unit.python.tools.sandbox_hosted_test_fixtures import _capacity_boundary as _capacity_boundary, completed, finished_follower, report_archive, special_archive, FakeArchiveProcess


@pytest.mark.parametrize(
    "member",
    [
        tarfile.TarInfo("../escape"),
        tarfile.TarInfo("/absolute"),
        tarfile.TarInfo("nested/../../escape"),
    ],
)
def test_report_export_rejects_path_escape_without_destination_write(tmp_path, member):
    module = sandbox_owner
    destination = tmp_path / "report"

    with pytest.raises(RuntimeError, match="unsafe path"):
        module._export_sandbox_report(special_archive(member), destination)

    assert not destination.exists()



def test_report_export_rejects_symlinks_and_existing_destination(tmp_path):
    module = sandbox_owner
    symlink = tarfile.TarInfo("escape-link")
    symlink.type = tarfile.SYMTYPE
    symlink.linkname = "../outside"
    destination = tmp_path / "report"

    with pytest.raises(RuntimeError, match="unsafe file type"):
        module._export_sandbox_report(special_archive(symlink), destination)
    destination.mkdir()
    with pytest.raises(RuntimeError, match="already exists"):
        module._export_sandbox_report(report_archive({"index.html": "ok"}), destination)



def test_report_archive_reader_uses_fixed_source_and_enforces_stream_bound(
    monkeypatch,
):
    module = sandbox_owner
    calls = []
    process = FakeArchiveProcess(b"archive")

    def fake_popen(command, **kwargs):
        calls.append((command, kwargs))
        return process

    monkeypatch.setattr(module.subprocess, "Popen", fake_popen)
    container_id = "4" * 64
    assert module._read_container_report_archive(container_id, True) == b"archive"
    assert calls[0][0] == [
        "docker",
        "cp",
        f"{container_id}:{module.INNER_REPORT_ROOT}/.",
        "-",
    ]

    oversized = FakeArchiveProcess(b"too-large")
    monkeypatch.setattr(module.subprocess, "Popen", lambda *_args, **_kwargs: oversized)
    monkeypatch.setattr(module, "MAX_REPORT_ARCHIVE_BYTES", 1)
    with pytest.raises(RuntimeError, match="exceeds size limit"):
        module._read_container_report_archive(container_id, True)
    assert oversized.killed



def test_report_export_enforces_member_and_content_bounds(tmp_path, monkeypatch):
    module = sandbox_owner
    monkeypatch.setattr(module, "MAX_REPORT_MEMBERS", 1)
    with pytest.raises(RuntimeError, match="bounded limits"):
        module._export_sandbox_report(
            report_archive({"first": "1", "second": "2"}),
            tmp_path / "members",
        )
    monkeypatch.setattr(module, "MAX_REPORT_MEMBERS", 4096)
    monkeypatch.setattr(module, "MAX_REPORT_CONTENT_BYTES", 1)
    with pytest.raises(RuntimeError, match="bounded limits"):
        module._export_sandbox_report(
            report_archive({"large": "12"}),
            tmp_path / "content",
        )



@pytest.mark.parametrize(("test_status", "expected"), [(0, 2), (7, 7)])
def test_report_export_failure_preserves_primary_status_and_exact_cleanup(
    tmp_path, capsys, test_status, expected
):
    module = sandbox_owner
    calls = []
    outer_id = "6" * 64
    empty = module.HostSnapshot(frozenset(), frozenset(), frozenset(), frozenset())

    def fake_runner(command, **kwargs):
        calls.append(command)
        if command[:3] == ["docker", "run", "-d"]:
            return completed(command, stdout=outer_id + "\n")
        if command[:2] == ["docker", "wait"]:
            return completed(command, stdout=f"{test_status}\n")
        if command[:3] == ["docker", "container", "inspect"]:
            return completed(command, status=1)
        return completed(command)

    def fail_export(_container_id, _required):
        raise RuntimeError("bounded export failure")

    result = module.run_in_sandbox(
        ["--suite", "int", "--report", "--report-dir", str(tmp_path / "report")],
        repo_root=tmp_path / "repo",
        image_id="sha256:" + "7" * 64,
        runner=fake_runner,
        follower_factory=finished_follower,
        snapshotter=lambda _runner: empty,
        boundary_prover=lambda *_args, **_kwargs: None,
        archive_reader=fail_export,
    )

    assert result == expected
    assert ["docker", "rm", "-f", "-v", outer_id] in calls
    assert "bounded export failure" in capsys.readouterr().err



def test_missing_report_on_successful_run_fails_launcher(tmp_path):
    module = sandbox_owner
    calls = []
    outer_id = "5" * 64
    repo_root = tmp_path / "repo"
    empty = module.HostSnapshot(frozenset(), frozenset(), frozenset(), frozenset())

    def fake_runner(command, **kwargs):
        calls.append(command)
        if command[:3] == ["docker", "run", "-d"]:
            return completed(command, stdout=outer_id + "\n")
        if command[:2] == ["docker", "wait"]:
            # exit status 0, but no report directory was generated
            return completed(command, stdout="0\n")
        if command[:2] == ["docker", "logs"]:
            return completed(command)
        if command[:3] == ["docker", "container", "inspect"]:
            return completed(command, status=1)
        return completed(command)

    result = module.run_in_sandbox(
        ["--suite", "staging", "--sandbox", "--report"],
        repo_root=repo_root,
        image_id="sha256:" + "4" * 64,
        runner=fake_runner,
        follower_factory=finished_follower,
        snapshotter=lambda _runner: empty,
        boundary_prover=lambda *_args, **_kwargs: None,
        archive_reader=lambda _container_id, _required: None,
    )

    assert result == 2
    assert ["docker", "rm", "-f", "-v", outer_id] in calls



def test_missing_report_does_not_mask_sandbox_setup_failure(tmp_path):
    module = sandbox_owner
    empty = module.HostSnapshot(frozenset(), frozenset(), frozenset(), frozenset())

    result = module.run_in_sandbox(
        ["--suite", "int", "--sandbox", "--report"],
        repo_root=tmp_path / "repo",
        image_id="sha256:" + "c" * 64,
        runner=lambda command, **_kwargs: completed(command, status=1),
        follower_factory=finished_follower,
        snapshotter=lambda _runner: empty,
        boundary_prover=lambda *_args, **_kwargs: None,
        archive_reader=lambda _container_id, _required: None,
    )

    assert result == 2
    assert not (tmp_path / "repo" / ".test-reports").exists()



def test_launcher_cleans_outer_after_setup_exception(tmp_path):
    module = sandbox_owner
    calls = []
    outer_id = "9" * 64
    empty = module.HostSnapshot(frozenset(), frozenset(), frozenset(), frozenset())

    def fake_runner(command, **kwargs):
        calls.append(command)
        if command[:3] == ["docker", "run", "-d"]:
            return completed(command, stdout=outer_id + "\n")
        if command[:3] == ["docker", "container", "inspect"]:
            return completed(command, status=1)
        return completed(command)

    def fail_boundary(*_args, **_kwargs):
        raise RuntimeError("bounded setup failure")

    result = module.run_in_sandbox(
        ["--suite", "int"],
        repo_root=tmp_path / "repo",
        image_id="sha256:" + "8" * 64,
        runner=fake_runner,
        follower_factory=finished_follower,
        snapshotter=lambda _runner: empty,
        boundary_prover=fail_boundary,
    )

    assert result == 2
    assert ["docker", "rm", "-f", "-v", outer_id] in calls



def test_snapshot_residue_does_not_mask_cleanup_error(tmp_path, monkeypatch):
    module = sandbox_owner
    calls = []
    outer_id = "3" * 64
    residue = module.HostSnapshot(frozenset({"residual-container"}), frozenset(), frozenset(), frozenset())

    def fake_runner(command, **kwargs):
        calls.append(command)
        if command[:3] == ["docker", "run", "-d"]:
            return completed(command, stdout=outer_id + "\n")
        if command[:2] == ["docker", "wait"]:
            return completed(command, stdout="0\n")
        if command[:2] == ["docker", "logs"]:
            return completed(command)
        if command[:3] == ["docker", "container", "inspect"]:
            return completed(command, status=1)
        return completed(command)

    # Both report export fails (because source is missing on exit 0) and snapshot fails
    result = module.run_in_sandbox(
        ["--suite", "staging", "--sandbox", "--report"],
        repo_root=tmp_path / "repo",
        image_id="sha256:" + "2" * 64,
        runner=fake_runner,
        follower_factory=finished_follower,
        snapshotter=lambda _runner: residue,
        boundary_prover=lambda *_args, **_kwargs: None,
        archive_reader=lambda _container_id, _required: None,
    )

    assert result == 2
    assert ["docker", "rm", "-f", "-v", outer_id] in calls



def test_launcher_maps_sigterm_to_interrupt_and_cleans_outer(tmp_path, monkeypatch):
    module = sandbox_owner
    calls = []
    handlers: dict[int, int | Callable[[int, FrameType | None], None] | None] = {}
    outer_id = "7" * 64
    empty = module.HostSnapshot(frozenset(), frozenset(), frozenset(), frozenset())

    def fake_signal(signum, handler):
        previous = handlers.get(signum, module.signal.SIG_DFL)
        handlers[signum] = handler
        return previous

    monkeypatch.setattr(module.signal, "signal", fake_signal)

    def fake_runner(command, **kwargs):
        calls.append(command)
        if command[:3] == ["docker", "run", "-d"]:
            return completed(command, stdout=outer_id + "\n")
        if command[:2] == ["docker", "wait"]:
            handler = handlers[module.signal.SIGTERM]
            assert callable(handler)
            handler(module.signal.SIGTERM, None)
        if command[:3] == ["docker", "container", "inspect"]:
            return completed(command, status=1)
        return completed(command)

    result = module.run_in_sandbox(
        ["--suite", "int"],
        repo_root=tmp_path / "repo",
        image_id="sha256:" + "6" * 64,
        runner=fake_runner,
        follower_factory=finished_follower,
        snapshotter=lambda _runner: empty,
        boundary_prover=lambda *_args, **_kwargs: None,
    )

    assert result == 130
    assert ["docker", "rm", "-f", "-v", outer_id] in calls
    assert handlers[module.signal.SIGTERM] == module.signal.SIG_DFL


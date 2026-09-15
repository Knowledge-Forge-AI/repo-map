from __future__ import annotations

import os
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from repomap_test_support.resource_ledger import ResourceLedger, RunIdentity
from repomap_test_support.resource_test_images import (
    TestImageError as ImageLifecycleError,
    TestImageManager as ImageManager,
)


BASE_REFERENCE = "python:3.12-slim-bookworm@sha256:" + "c" * 64


class FakeClient:
    """The lifecycle lock never reaches Docker, so no engine surface is needed."""


def _project(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    root.joinpath("pyproject.toml").write_text(
        """[project]
name = "fixture"
version = "0.1"
dependencies = ["psycopg[binary]==3.2.12", "typing-extensions==4.16.0"]
""",
        encoding="utf-8",
    )
    return root


def _resource_run(tmp_path: Path):
    ledger = ResourceLedger.create(
        tmp_path / "ledger.json",
        RunIdentity("repo-map", "TEST-IMAGE-LIFECYCLE1", "run-1"),
    )
    return SimpleNamespace(
        ledger=ledger,
        materialization_manifest_path=tmp_path / "materialization.json",
    )


def _manager(tmp_path: Path):
    client = FakeClient()
    manager = ImageManager(
        repo_root=_project(tmp_path),
        resource_run=_resource_run(tmp_path),
        client=client,
        base_reference=BASE_REFERENCE,
        python_base_family="python:3.12-slim-bookworm",
        python_version="3.12.13",
        psycopg_release_version="3.2.12",
        runtime_extras=(),
        probe=lambda _identity: None,
    )
    return manager, client


def test_lifecycle_lock_lives_under_project_root_scratch(tmp_path):
    manager, _client = _manager(tmp_path)

    path = manager._lifecycle_lock_path()

    assert path.parent == manager.repo_root / ".scratch" / "locks"
    assert path.name == f"repomap-test-images-{os.getuid()}.lock"
    assert path.parent.is_dir()


def test_lifecycle_lock_path_never_uses_system_temporary_directories(tmp_path):
    manager, _client = _manager(tmp_path)

    path = manager._lifecycle_lock_path()

    assert path.parent == manager.repo_root / ".scratch" / "locks"

    source = (
        Path(__file__).parents[3]
        / "support/python/repomap_test_support/resource_test_images.py"
    ).read_text(encoding="utf-8")
    assert '"/tmp"' not in source
    assert "/private/tmp" not in source
    assert "gettempdir" not in source
    assert "TMPDIR" not in source


def test_repository_scratch_lock_path_is_git_ignored():
    repository = Path(__file__).resolve().parents[5]
    relative = Path(".scratch") / "locks" / f"repomap-test-images-{os.getuid()}.lock"

    result = subprocess.run(
        ["git", "check-ignore", "-v", str(relative)],
        cwd=repository,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert ".scratch/" in result.stdout


def test_lifecycle_lock_path_ignores_tmpdir_and_per_run_scratch(tmp_path, monkeypatch):
    manager, _client = _manager(tmp_path)
    original_tempdir = tempfile.tempdir
    try:
        monkeypatch.setenv("TMPDIR", str(tmp_path / "env-a"))
        monkeypatch.setattr(tempfile, "tempdir", str(tmp_path / "run-a"))
        manager.resource_run.layout = SimpleNamespace(run_root=tmp_path / "run-a")
        first = manager._lifecycle_lock_path()

        monkeypatch.setenv("TMPDIR", str(tmp_path / "env-b"))
        monkeypatch.setattr(tempfile, "tempdir", str(tmp_path / "run-b"))
        manager.resource_run.layout = SimpleNamespace(run_root=tmp_path / "run-b")
        second = manager._lifecycle_lock_path()
    finally:
        tempfile.tempdir = original_tempdir

    assert first == second


def test_lifecycle_lock_path_is_shared_by_managers_in_the_same_project_root(tmp_path):
    first_manager, _first = _manager(tmp_path)
    second_run_root = tmp_path / "second-run"
    second_run_root.mkdir()
    second = ImageManager(
        repo_root=first_manager.repo_root,
        resource_run=_resource_run(second_run_root),
        client=FakeClient(),
        base_reference=BASE_REFERENCE,
        python_base_family="python:3.12-slim-bookworm",
        python_version="3.12.13",
        psycopg_release_version="3.2.12",
        runtime_extras=(),
        probe=lambda _identity: None,
    )

    assert first_manager._lifecycle_lock_path() == second._lifecycle_lock_path()


def test_lifecycle_lock_paths_differ_across_project_roots(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    first_manager, _first = _manager(tmp_path / "a")
    second_manager, _second = _manager(tmp_path / "b")

    assert first_manager._lifecycle_lock_path() != second_manager._lifecycle_lock_path()


def test_lifecycle_lock_refuses_symlinked_scratch(tmp_path):
    manager, _client = _manager(tmp_path)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (manager.repo_root / ".scratch").symlink_to(elsewhere, target_is_directory=True)

    with pytest.raises(ImageLifecycleError, match="scratch is a symlink"):
        manager._lifecycle_lock_path()


def test_lifecycle_lock_refuses_symlinked_lock_directory(tmp_path):
    manager, _client = _manager(tmp_path)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    scratch = manager.repo_root / ".scratch"
    scratch.mkdir(mode=0o700)
    (scratch / "locks").symlink_to(elsewhere, target_is_directory=True)

    with pytest.raises(ImageLifecycleError, match="scratch is a symlink"):
        manager._lifecycle_lock_path()


def test_lifecycle_lock_refuses_non_directory_scratch(tmp_path):
    manager, _client = _manager(tmp_path)
    (manager.repo_root / ".scratch").write_text("", encoding="utf-8")

    with pytest.raises(ImageLifecycleError, match="scratch is not a directory"):
        manager._lifecycle_lock_path()


def test_lifecycle_lock_refuses_group_or_world_writable_scratch(tmp_path):
    manager, _client = _manager(tmp_path)
    scratch = manager.repo_root / ".scratch"
    scratch.mkdir(mode=0o700)
    scratch.chmod(0o777)

    with pytest.raises(ImageLifecycleError, match="scratch mode is unsafe"):
        manager._lifecycle_lock_path()


def test_lifecycle_lock_refuses_symlinked_lock_file(tmp_path):
    manager, _client = _manager(tmp_path)
    target = tmp_path / "decoy.lock"
    target.write_text("", encoding="utf-8")
    manager._lifecycle_lock_path().symlink_to(target)

    with pytest.raises(OSError):
        with manager._lifecycle_lock():
            pass


def test_lifecycle_lock_reuses_an_existing_private_lock_file(tmp_path):
    manager, _client = _manager(tmp_path)
    path = manager._lifecycle_lock_path()
    path.touch(mode=0o600)
    before = path.stat().st_ino

    with manager._lifecycle_lock():
        pass

    assert path.exists()
    assert path.stat().st_ino == before
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_lifecycle_lock_contends_across_processes(tmp_path):
    manager, _client = _manager(tmp_path)
    lock_path = manager._lifecycle_lock_path()

    contended = tmp_path / "child-contended"
    acquired = tmp_path / "child-acquired"
    # The child derives the lock path independently from the same project root,
    # which is the property the previous host-stable /tmp path existed to give.
    # It proves contention with a non-blocking probe before blocking, so the
    # parent observes exclusion positively instead of inferring it from timing.
    script = """
import errno, fcntl, os, pathlib, sys
root = pathlib.Path(sys.argv[1])
lock = root / ".scratch" / "locks" / f"repomap-test-images-{os.getuid()}.lock"
descriptor = os.open(lock, os.O_CREAT | os.O_RDWR, 0o600)
try:
    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
except OSError as error:
    if error.errno not in (errno.EACCES, errno.EAGAIN):
        raise
    pathlib.Path(sys.argv[2]).touch()
else:
    raise SystemExit("lifecycle lock was not held by the parent process")
fcntl.flock(descriptor, fcntl.LOCK_EX)
pathlib.Path(sys.argv[3]).touch()
fcntl.flock(descriptor, fcntl.LOCK_UN)
os.close(descriptor)
"""
    with manager._lifecycle_lock():
        child = subprocess.Popen(
            [
                sys.executable,
                "-c",
                script,
                str(manager.repo_root),
                str(contended),
                str(acquired),
            ]
        )
        deadline = time.monotonic() + 5
        while not contended.exists() and child.poll() is None:
            if time.monotonic() > deadline:
                break
            time.sleep(0.01)
        # The child reached flock and was refused, so it is blocked and cannot
        # reach ``acquired`` while this process still holds the lock.
        assert contended.exists()
        assert not acquired.exists()
    child.wait(timeout=5)
    assert child.returncode == 0
    assert acquired.exists()
    assert lock_path.exists()

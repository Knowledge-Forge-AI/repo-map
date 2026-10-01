"""Setup establishes authority instead of requiring operator permission repair."""

import os
from types import SimpleNamespace

import pytest

from repomap_kg.runtime import _home_authority as authority
from repomap_kg.runtime.local import setup_local_runtime
from repomap_kg.runtime.plan import LocalRuntimeError


def test_fresh_setup_private_under_permissive_umask(tmp_path):
    home = tmp_path / "fresh"
    previous = os.umask(0)
    try:
        setup_local_runtime(home)
    finally:
        os.umask(previous)
    assert home.stat().st_mode & 0o777 == 0o700
    assert (home / "runtime/.env").stat().st_mode & 0o777 == 0o600
    assert (home / "runtime").stat().st_mode & 0o777 == 0o700
    setup_local_runtime(home)


def test_dry_run_does_not_create_or_chmod(tmp_path):
    home = tmp_path / "absent"
    setup_local_runtime(home, dry_run=True)
    assert not home.exists()
    home.mkdir(mode=0o755)
    setup_local_runtime(home, dry_run=True)
    assert home.stat().st_mode & 0o777 == 0o755
    assert list(home.iterdir()) == []


@pytest.mark.parametrize("kind", ["broad", "file", "symlink", "wrong-owner"])
def test_unsafe_existing_home_refused_without_mutation(tmp_path, monkeypatch, kind):
    home = tmp_path / "home"
    if kind == "file":
        home.write_text("unchanged")
    elif kind == "symlink":
        home.symlink_to(tmp_path, target_is_directory=True)
    else:
        home.mkdir(mode=0o755 if kind == "broad" else 0o700)
    before = home.lstat()
    if kind == "wrong-owner":
        monkeypatch.setattr(os, "getuid", lambda: before.st_uid + 1)
    with pytest.raises(LocalRuntimeError) as error:
        setup_local_runtime(home)
    assert error.value.diagnostics[0].code == "repo-map-home-unsafe"
    assert home.lstat().st_mode == before.st_mode
    assert not (home / "runtime").exists()


def test_existing_safe_home_accepted(tmp_path):
    home = tmp_path / "safe"
    home.mkdir(mode=0o700)
    assert setup_local_runtime(home).result == "success"


def test_windows_new_directory_acl_only_on_creation(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(authority, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(authority, "reject_reparse_path", lambda p: calls.append("reparse"))
    monkeypatch.setattr(authority, "apply_owner_private_acl", lambda p: calls.append("apply"))
    monkeypatch.setattr(authority, "validate_private_directory", lambda p: calls.append("validate"))
    home = tmp_path / "windows-double"
    assert authority.ensure_private_directory(home)
    assert calls == ["reparse", "apply", "validate"]
    calls.clear()
    assert not authority.ensure_private_directory(home)
    assert calls == ["reparse", "validate"]


def test_runtime_env_symlink_refused_before_config_creation(tmp_path):
    home = tmp_path / "home"
    (home / "runtime").mkdir(parents=True, mode=0o700)
    home.chmod(0o700)
    target = tmp_path / "target"
    target.write_text("unchanged")
    (home / "runtime/.env").symlink_to(target)
    with pytest.raises(LocalRuntimeError):
        setup_local_runtime(home)
    assert target.read_text() == "unchanged"
    assert not (home / "repomap.rpl.toml").exists()


def test_windows_acl_error_is_bounded(tmp_path, monkeypatch):
    monkeypatch.setattr(authority, "os", SimpleNamespace(name="nt"))
    def refuse(path):
        raise authority.WindowsSecurityError("fixture-secret")
    monkeypatch.setattr(authority, "reject_reparse_path", refuse)
    with pytest.raises(ValueError) as error:
        authority.validate_private_file(tmp_path / "private")
    assert str(error.value) == "generated-local-admin-credential-unsafe"


def test_private_creation_failure_has_local_runtime_diagnostic(tmp_path, monkeypatch):
    def refuse(*args):
        raise ValueError("fixture-secret")
    monkeypatch.setattr("repomap_kg.runtime.local.create_private_file", refuse)
    with pytest.raises(LocalRuntimeError) as error:
        setup_local_runtime(tmp_path / "home")
    assert error.value.diagnostics[0].code == "generated-local-admin-credential-unsafe"
    assert "fixture-secret" not in str(error.value)

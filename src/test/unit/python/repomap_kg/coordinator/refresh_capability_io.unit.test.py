"""Direct fail-closed coverage for refresh capability executable authority."""

import os
from pathlib import Path

import pytest

from repomap_test_support.executable_authority import (
    PSQL_NAME,
    approved_psql,
    private_bin_directory,
    search_path_for,
)
from repomap_kg.coordinator._refresh_capability_io import (
    validate_config_file,
    validate_psql,
    validate_search_path,
)


posix_only = pytest.mark.skipif(
    os.name == "nt", reason="POSIX mode bits are not the Windows authority rule"
)


def test_approved_psql_fixture_is_accepted(tmp_path):
    validate_psql(approved_psql(tmp_path))


@posix_only
def test_approved_lexical_psql_may_resolve_to_a_secure_wrapper(tmp_path):
    wrapper = tmp_path / "libexec" / "pg_wrapper"
    wrapper.parent.mkdir()
    wrapper.write_text("", encoding="utf-8")
    wrapper.chmod(0o755)
    invoked = private_bin_directory(tmp_path) / PSQL_NAME
    invoked.symlink_to(wrapper)

    validate_psql(invoked)


def test_wrong_lexical_executable_name_is_rejected(tmp_path):
    wrong = approved_psql(tmp_path, name="pg-console")
    with pytest.raises(ValueError, match="invalid refresh capability"):
        validate_psql(wrong)


@posix_only
def test_non_executable_target_is_rejected(tmp_path):
    path = approved_psql(tmp_path)
    path.chmod(0o644)
    with pytest.raises(ValueError, match="invalid refresh capability"):
        validate_psql(path)


@posix_only
@pytest.mark.parametrize("mode", [0o775, 0o757, 0o777])
def test_group_or_other_writable_target_is_rejected(tmp_path, mode):
    path = approved_psql(tmp_path)
    path.chmod(mode)
    with pytest.raises(ValueError, match="invalid refresh capability"):
        validate_psql(path)


@posix_only
def test_broken_indirection_is_rejected(tmp_path):
    invoked = private_bin_directory(tmp_path) / PSQL_NAME
    invoked.symlink_to(tmp_path / "absent" / PSQL_NAME)
    with pytest.raises(ValueError, match="invalid refresh capability"):
        validate_psql(invoked)


def test_absent_executable_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="invalid refresh capability"):
        validate_psql(private_bin_directory(tmp_path) / PSQL_NAME)


def test_search_path_accepts_the_controlled_private_directory(tmp_path):
    validate_search_path(search_path_for(approved_psql(tmp_path)))


@posix_only
@pytest.mark.parametrize("mode", [0o775, 0o757, 0o777])
def test_group_or_other_writable_search_path_is_rejected(tmp_path, mode):
    directory = private_bin_directory(tmp_path)
    directory.chmod(mode)
    with pytest.raises(ValueError, match="invalid refresh capability"):
        validate_search_path((directory,))


def test_non_directory_search_path_entry_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="invalid refresh capability"):
        validate_search_path((approved_psql(tmp_path),))


def test_absent_search_path_entry_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="invalid refresh capability"):
        validate_search_path((Path(tmp_path) / "absent-bin",))


@posix_only
@pytest.mark.parametrize("mode", [0o664, 0o646, 0o666])
def test_group_or_other_writable_config_file_is_rejected(tmp_path, mode):
    config_path = tmp_path / "ops.toml"
    config_path.write_text("version = 1\n", encoding="utf-8")
    config_path.chmod(mode)
    with pytest.raises(ValueError, match="invalid refresh capability"):
        validate_config_file(config_path)


@posix_only
def test_fixture_authority_does_not_inherit_a_permissive_umask(tmp_path):
    previous = os.umask(0o000)
    try:
        config_path = tmp_path / "ops.toml"
        config_path.write_text("version = 1\n", encoding="utf-8")
        config_path.chmod(0o600)
        validate_config_file(config_path)
        psql_path = approved_psql(tmp_path)
        validate_psql(psql_path)
        validate_search_path(search_path_for(psql_path))
    finally:
        os.umask(previous)

import inspect
import os
import shutil
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from repomap_test_support.executable_authority import (
    PSQL_NAME,
    approved_psql,
    private_bin_directory,
)
from repomap_kg.service_package import contract
from repomap_kg.service_package.contract import (
    SERVICE_ENVIRONMENT_ALLOWLIST,
    apply_service_environment,
    build_service_inspection_spec,
    build_service_package_spec,
    is_approved_psql_executable,
    is_approved_python_executable,
    service_semantics,
)


def test_service_spec_normalizes_one_portable_foreground_contract(
    tmp_path, service_authority
):
    repo_map_home = tmp_path / "RepoMap Home"

    spec = build_service_package_spec(repo_map_home)

    assert spec.psql_path is not None
    assert spec.python_sha256 is not None
    assert spec.psql_sha256 is not None
    assert spec.service_identity == "org.repomap.coordinator"
    assert spec.foreground_argv == (
        str(service_authority.python_path),
        "-m",
        "repomap_kg",
        "ops",
        "coordinator-serve",
        "--repo-map-home",
        str(repo_map_home.resolve()),
        "--service-package-environment",
        "--service-package-psql",
        spec.psql_path.as_posix(),
        "--json",
    )
    assert spec.environment_source == "allowlisted_native_manager_environment"
    assert spec.environment_allowlist == SERVICE_ENVIRONMENT_ALLOWLIST
    assert spec.repo_map_home == repo_map_home.resolve()
    assert spec.config_source == "repo_map_home"
    assert spec.psql_path.is_absolute()
    assert spec.psql_path.name == "psql"
    assert len(spec.python_sha256) == 64
    assert len(spec.psql_sha256) == 64
    assert spec.runtime_directory == repo_map_home.resolve() / "coordinator"
    assert spec.working_directory == repo_map_home.resolve()
    assert spec.stdout_path == spec.runtime_directory / "service.stdout.log"
    assert spec.stderr_path == spec.runtime_directory / "service.stderr.log"
    assert spec.startup_policy == "explicit_user_session"
    assert spec.restart_policy == "on_failure_rate_limited"
    assert spec.restart_delay_seconds == 10
    assert spec.shutdown_policy == "sigterm_then_kill"
    assert spec.shutdown_timeout_seconds == 30
    assert spec.readiness_contract == "authenticated_health_v1"
    assert spec.log_ownership == "owner_private_files"
    assert spec.resource_policy == "native_user_default"
    assert spec.install_target == "current_user"
    assert spec.generated_artifact_ownership == "repomap_owned_private_regular_file_v1"
    assert spec.status_inspection == "manager_state_plus_authenticated_health"
    assert spec.uninstall_behavior == "recognized_owner_file_only"
    assert spec.upgrade_behavior == "preserve_native_state_or_rollback"
    assert spec.rollback_behavior == "restore_prior_known_good"
    assert spec.privacy_classification == "owner_private"
    assert spec.architectural_targets == ("darwin", "linux", "win32")
    assert spec.native_adapter_targets == ("darwin", "linux")


def test_service_spec_has_no_executable_or_environment_value_authority(
    tmp_path, service_authority
):
    parameters = inspect.signature(build_service_package_spec).parameters
    assert tuple(parameters) == ("repo_map_home",)

    spec = build_service_package_spec(tmp_path)
    assert "shell" not in vars(spec)
    assert "environment" not in vars(spec)
    assert all("secret" not in value.lower() for value in spec.foreground_argv)


def test_service_spec_fails_when_the_fixed_psql_dependency_is_unavailable(
    tmp_path, service_authority
):
    with patch(
        "repomap_kg.service_package.contract.shutil.which",
        return_value=None,
    ):
        with pytest.raises(RuntimeError, match="service_psql_unavailable"):
            build_service_package_spec(tmp_path)


def test_executable_authority_rejects_renamed_arbitrary_binaries(
    tmp_path, service_authority
):
    fake_python = tmp_path / "python3"
    fake_psql = tmp_path / "psql"
    shutil.copyfile("/bin/echo", fake_python)
    shutil.copyfile("/bin/echo", fake_psql)
    fake_python.chmod(0o700)
    fake_psql.chmod(0o700)

    assert not is_approved_python_executable(fake_python)
    assert not is_approved_psql_executable(fake_psql)


@pytest.mark.skipif(os.name == "nt", reason="POSIX mode authority")
@pytest.mark.parametrize("mode", [0o777, 0o757, 0o775, 0o644])
def test_executable_authority_rejects_unsafe_target_modes(
    tmp_path, service_authority, mode
):
    """0o777 is the shape a group/other-writable toolcache interpreter has."""

    service_authority.python_path.chmod(mode)

    assert not is_approved_python_executable(service_authority.python_path)
    with pytest.raises(RuntimeError, match="service_foreground_executable_invalid"):
        build_service_package_spec(tmp_path / "home")


def test_executable_authority_rejects_broken_indirection(tmp_path, service_authority):
    dangling = tmp_path / "dangling-python3"
    dangling.symlink_to(tmp_path / "absent" / "python3")

    assert not is_approved_python_executable(dangling)


def test_executable_authority_accepts_safe_indirection(tmp_path, service_authority):
    link = tmp_path / "python3"
    link.symlink_to(service_authority.python_path)

    assert is_approved_python_executable(link)


@contextmanager
def _wrapped_psql(tmp_path):
    """Build the Debian shape: a lexical ``psql`` link to a wrapper target."""

    target = approved_psql(tmp_path / "share", name="pg_wrapper")
    invoked = private_bin_directory(tmp_path / "usr") / PSQL_NAME
    invoked.symlink_to(target)
    with patch.object(
        contract, "shutil", SimpleNamespace(which=lambda name: str(invoked))
    ):
        yield SimpleNamespace(invoked=invoked, target=target)


def test_psql_authority_accepts_secure_lexical_indirection(tmp_path, service_authority):
    with _wrapped_psql(tmp_path) as psql:
        assert is_approved_psql_executable(psql.invoked)

        spec = build_service_package_spec(tmp_path / "home")

    assert spec.psql_path == psql.invoked
    assert spec.psql_path is not None
    assert spec.psql_path.name == PSQL_NAME


def test_psql_authority_rejects_the_wrapper_target_name(tmp_path, service_authority):
    with _wrapped_psql(tmp_path) as psql:
        assert not is_approved_psql_executable(psql.target)
        assert not is_approved_psql_executable(psql.invoked.parent / "pg-console")


@pytest.mark.skipif(os.name == "nt", reason="POSIX mode authority")
def test_psql_authority_rejects_an_unsafe_indirection_target(
    tmp_path, service_authority
):
    with _wrapped_psql(tmp_path) as psql:
        psql.target.chmod(0o777)

        assert not is_approved_psql_executable(psql.invoked)
        with pytest.raises(RuntimeError, match="service_psql_unavailable"):
            build_service_package_spec(tmp_path / "home")


def test_psql_authority_rejects_broken_indirection(tmp_path, service_authority):
    dangling = private_bin_directory(tmp_path / "usr") / PSQL_NAME
    dangling.symlink_to(tmp_path / "absent" / PSQL_NAME)
    with patch.object(
        contract, "shutil", SimpleNamespace(which=lambda name: str(dangling))
    ):
        assert not is_approved_psql_executable(dangling)
        with pytest.raises(RuntimeError, match="service_psql_unavailable"):
            build_service_package_spec(tmp_path / "home")


def test_psql_authority_rejects_a_relative_invocation(tmp_path, service_authority):
    with patch.object(
        contract, "shutil", SimpleNamespace(which=lambda name: PSQL_NAME)
    ):
        assert not is_approved_psql_executable(Path(PSQL_NAME))
        with pytest.raises(RuntimeError, match="service_psql_unavailable"):
            build_service_package_spec(tmp_path / "home")


def test_dependency_free_inspection_spec_cannot_render_or_start(tmp_path):
    spec = build_service_inspection_spec(tmp_path)

    assert spec.foreground_argv == ()
    assert spec.psql_path is None
    assert spec.python_sha256 is None
    assert spec.psql_sha256 is None
    assert spec.repo_map_home == tmp_path.resolve()


def test_packaged_foreground_keeps_only_the_fixed_environment_allowlist():
    environment = {
        "HOME": "/placeholder/home",
        "PATH": "/placeholder/bin",
        "LANG": "C.UTF-8",
        "LC_ALL": "C",
        "LC_CTYPE": "UTF-8",
        "TZ": "UTC",
        "DATABASE_PASSWORD": "synthetic-secret",
        "UNRELATED": "value",
    }

    apply_service_environment(environment)

    assert environment == {
        "LANG": "C.UTF-8",
        "LC_ALL": "C",
        "LC_CTYPE": "UTF-8",
        "TZ": "UTC",
    }


def test_service_semantics_are_complete_and_adapter_neutral(
    tmp_path, service_authority
):
    spec = build_service_package_spec(tmp_path)

    semantics = service_semantics(spec)

    assert semantics == {
        "service_identity": "org.repomap.coordinator",
        "foreground_argv": spec.foreground_argv,
        "environment_source": "allowlisted_native_manager_environment",
        "environment_allowlist": SERVICE_ENVIRONMENT_ALLOWLIST,
        "repo_map_home": spec.repo_map_home,
        "config_source": "repo_map_home",
        "psql_path": spec.psql_path,
        "runtime_directory": spec.runtime_directory,
        "working_directory": spec.working_directory,
        "startup_policy": "explicit_user_session",
        "restart_policy": "on_failure_rate_limited",
        "restart_delay_seconds": 10,
        "shutdown_policy": "sigterm_then_kill",
        "shutdown_timeout_seconds": 30,
        "readiness_contract": "authenticated_health_v1",
        "log_ownership": "owner_private_files",
        "resource_policy": "native_user_default",
        "install_target": "current_user",
        "generated_artifact_ownership": "repomap_owned_private_regular_file_v1",
        "status_inspection": "manager_state_plus_authenticated_health",
        "uninstall_behavior": "recognized_owner_file_only",
        "upgrade_behavior": "preserve_native_state_or_rollback",
        "rollback_behavior": "restore_prior_known_good",
        "privacy_classification": "owner_private",
    }


@pytest.mark.parametrize("value", ["\x00", "relative/home"])
def test_service_spec_rejects_unsafe_home_selection(value):
    with pytest.raises(ValueError, match="service_repo_map_home_invalid"):
        build_service_package_spec(value)

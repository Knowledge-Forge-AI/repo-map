from pathlib import Path

import pytest

from repomap_kg.service_package.contract import (
    build_service_package_spec,
    service_semantics,
)
from repomap_kg.service_package.launchd import LaunchdUserAdapter
from repomap_kg.service_package.platforms import (
    NativeServiceUnavailable,
    select_service_adapter,
)
from repomap_kg.service_package.systemd import SystemdUserAdapter


def test_platform_selection_is_explicit_and_never_falls_back(tmp_path):
    assert isinstance(
        select_service_adapter("darwin", user_home=tmp_path, uid=501),
        LaunchdUserAdapter,
    )
    assert isinstance(
        select_service_adapter("linux", user_home=tmp_path, uid=1000),
        SystemdUserAdapter,
    )
    with pytest.raises(
        NativeServiceUnavailable, match="native_service_adapter_pending_windows"
    ):
        select_service_adapter("win32", user_home=tmp_path, uid=1000)
    with pytest.raises(
        NativeServiceUnavailable, match="native_service_manager_unsupported"
    ):
        select_service_adapter("freebsd14", user_home=tmp_path, uid=1000)


def test_native_adapters_preserve_identical_portable_semantics(
    tmp_path, service_authority
):
    spec = build_service_package_spec(tmp_path / "RepoMap Home")
    launchd = LaunchdUserAdapter(user_home=tmp_path / "mac", uid=501)
    systemd = SystemdUserAdapter(user_home=tmp_path / "linux", uid=1000)

    assert launchd.semantic_values(spec) == service_semantics(spec)
    assert systemd.semantic_values(spec) == service_semantics(spec)
    assert launchd.semantic_values(spec) == systemd.semantic_values(spec)
    assert spec.architectural_targets == ("darwin", "linux", "win32")
    assert spec.native_adapter_targets == ("darwin", "linux")


@pytest.mark.parametrize("home", [Path("relative"), Path("/tmp/home") / "\x00bad"])
def test_adapter_selection_rejects_unsafe_user_home(home):
    with pytest.raises(ValueError, match="service_user_home_invalid"):
        select_service_adapter("linux", user_home=home, uid=1000)

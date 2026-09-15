from dataclasses import replace
import plistlib
import shutil

import pytest

from repomap_kg.service_package.contract import build_service_package_spec
from repomap_kg.service_package.launchd import LaunchdUserAdapter


def test_launchd_renders_one_private_user_launch_agent(tmp_path, service_authority):
    user_home = tmp_path / "user"
    repo_map_home = tmp_path / "RepoMap Home"
    adapter = LaunchdUserAdapter(user_home=user_home, uid=501)
    spec = build_service_package_spec(repo_map_home)

    content = adapter.render(spec)
    payload = plistlib.loads(content)

    assert adapter.target_path == (
        user_home / "Library" / "LaunchAgents" / "org.repomap.coordinator.plist"
    )
    assert payload == {
        "Disabled": True,
        "ExitTimeOut": 30,
        "KeepAlive": {"SuccessfulExit": False},
        "Label": "org.repomap.coordinator",
        "ProcessType": "Background",
        "ProgramArguments": list(spec.foreground_argv),
        "RunAtLoad": True,
        "StandardErrorPath": str(spec.stderr_path),
        "StandardOutPath": str(spec.stdout_path),
        "ThrottleInterval": 10,
        "Umask": 0o077,
        "WorkingDirectory": str(spec.working_directory),
        "X-RepoMap-Psql-SHA256": spec.psql_sha256,
        "X-RepoMap-Python-SHA256": spec.python_sha256,
    }
    assert b"EnvironmentVariables" not in content
    assert b"/bin/sh" not in content
    assert b"synthetic-secret" not in content
    adapter.validate(content, spec)
    assert adapter.recognizes(content)


def test_launchd_uses_current_user_domain_commands(tmp_path):
    adapter = LaunchdUserAdapter(user_home=tmp_path, uid=502)
    path = adapter.target_path

    assert adapter.manager_probe_argv() == (
        "/bin/launchctl",
        "print",
        "gui/502",
    )
    assert adapter.inactive_return_codes() == frozenset({113})
    assert adapter.active_probe_argv() == (
        "/bin/launchctl",
        "print",
        "gui/502/org.repomap.coordinator",
    )
    assert getattr(adapter, "enabled_probe_argv")() is None
    assert adapter.reload_commands() == ()
    assert adapter.enable_commands() == (
        ("/bin/launchctl", "enable", "gui/502/org.repomap.coordinator"),
    )
    assert adapter.disable_commands() == (
        ("/bin/launchctl", "disable", "gui/502/org.repomap.coordinator"),
    )
    assert adapter.start_commands() == (
        ("/bin/launchctl", "bootstrap", "gui/502", str(path)),
    )
    assert adapter.stop_commands() == (
        ("/bin/launchctl", "bootout", "gui/502/org.repomap.coordinator"),
    )
    assert adapter.restart_commands() == (
        (
            "/bin/launchctl",
            "kickstart",
            "-k",
            "gui/502/org.repomap.coordinator",
        ),
    )


@pytest.mark.parametrize(
    "content",
    [
        b"not a plist",
        plistlib.dumps({"Label": "org.example.unrecognized"}),
        plistlib.dumps(
            {
                "Label": "org.repomap.coordinator",
                "ProgramArguments": ["/bin/sh", "-c", "repomap-kg"],
            }
        ),
    ],
)
def test_launchd_rejects_unrecognized_or_shell_definitions(
    tmp_path, service_authority, content
):
    adapter = LaunchdUserAdapter(user_home=tmp_path, uid=501)
    spec = build_service_package_spec(tmp_path / "home")

    assert not adapter.recognizes(content)
    with pytest.raises(ValueError, match="service_definition_invalid"):
        adapter.validate(content, spec)


def test_launchd_rejects_modified_output_ownership(tmp_path, service_authority):
    adapter = LaunchdUserAdapter(user_home=tmp_path, uid=501)
    spec = build_service_package_spec(tmp_path / "home")
    payload = plistlib.loads(adapter.render(spec))
    payload["StandardOutPath"] = "/placeholder/unrecognized.log"
    content = plistlib.dumps(payload, sort_keys=True)

    assert not adapter.recognizes(content)


def test_launchd_rejects_an_arbitrary_non_python_executable(
    tmp_path, service_authority
):
    adapter = LaunchdUserAdapter(user_home=tmp_path, uid=501)
    spec = build_service_package_spec(tmp_path / "home")
    payload = plistlib.loads(adapter.render(spec))
    payload["ProgramArguments"][0] = "/bin/echo"
    content = plistlib.dumps(payload, sort_keys=True)

    assert not adapter.recognizes(content)


def test_launchd_recognizes_an_owned_definition_after_psql_relocation(
    tmp_path, service_authority
):
    adapter = LaunchdUserAdapter(user_home=tmp_path, uid=501)
    spec = build_service_package_spec(tmp_path / "home")
    stale_psql = tmp_path / "stale" / "psql"
    stale_psql.parent.mkdir()
    assert spec.psql_path is not None
    shutil.copyfile(spec.psql_path, stale_psql)
    stale_psql.chmod(0o700)
    argv = (*spec.foreground_argv[:9], str(stale_psql), *spec.foreground_argv[10:])
    content = adapter.render(replace(spec, foreground_argv=argv, psql_path=stale_psql))

    assert adapter.recognizes(content)
    stale_psql.unlink()
    assert adapter.recognizes(content)

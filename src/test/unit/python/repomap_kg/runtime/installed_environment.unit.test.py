"""The closed child environment of section 2 and environment configuration witnesses."""

from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

from repomap_test_support.installed_environment import (
    DELETED_KEYS, FIXED_VALUES, ChildExecutionFailure, ChildResult, InstalledEnvironment,
    child_environment, create_environment, include_system_site_packages, run_child,
)
from repomap_test_support import installed_environment as owner

INHERITED = {
    "PATH": "/opt/runner/bin:/usr/bin", "HOME": "/home/runner", "PYTHONPATH": "/checkout/src/main/python",
    "PYTHONHOME": "/x", "PYTHONSTARTUP": "/x", "PYTHONUSERBASE": "/x", "PYTHONEXECUTABLE": "/x",
    "PYTHONSAFEPATH": "1", "VIRTUAL_ENV": "/checkout/.venv", "COVERAGE_FILE": "/c", "PGHOST": "db", "PGPASSWORD": "pw", "REPOMAP_HOME": "/h", "CLOE_HOME": "/h",
    "REPOMAP_OPS_CONFIG": "/h", "REPOMAP_PG_URL": "x", "SERVICE_TOKEN": "t", "LANG": "en_US.UTF-8",
    "KEEP_ME": "kept",
}


def _env(root: Path, env_class: str = "pure-local") -> InstalledEnvironment:
    prefix = root / "venv"
    return InstalledEnvironment(root, env_class, prefix, prefix / "bin" / "python", prefix / "bin",
                                prefix / "lib" / "python3.13" / "site-packages", prefix,
                                root / "user home", root / "unrelated cwd")


def test_inherited_checkout_coverage_home_and_credential_keys_are_removed(tmp_path: Path) -> None:
    env = _env(tmp_path / "owned root")
    mapping = child_environment(env, base=INHERITED)
    for key in DELETED_KEYS:
        assert key not in mapping
    assert not any(key.startswith("COVERAGE_") for key in mapping)
    assert "REPOMAP_PG_URL" not in mapping and "SERVICE_TOKEN" not in mapping
    assert mapping["KEEP_ME"] == "kept"
    for key, value in FIXED_VALUES.items():
        assert mapping[key] == value
    assert mapping["HOME"] == str(env.user_home)
    assert mapping["PATH"] == f"{env.bin}:/usr/bin:/bin"


def test_explicit_extra_is_the_only_way_to_add_a_selector(tmp_path: Path) -> None:
    env = _env(tmp_path / "owned root")
    mapping = child_environment(env, {"CLOE_HOME": "/owned home", "PYTHONPATH": "/checkout"}, base=INHERITED)
    assert mapping["CLOE_HOME"] == "/owned home" and mapping["PYTHONPATH"] == "/checkout"


def test_provisioned_path_adds_only_postgres_binaries(tmp_path: Path) -> None:
    env = _env(tmp_path / "owned root", "provisioned-server")
    assert child_environment(env, base=INHERITED)["PATH"] == (
        f"{env.bin}:/usr/lib/postgresql/17/bin:/usr/bin:/bin")


def test_pip_family_is_scrubbed_the_same_way(tmp_path: Path) -> None:
    env = _env(tmp_path / "owned root")
    mapping = child_environment(env, base=INHERITED, family="arch7f_pip")
    assert "PYTHONPATH" not in mapping and mapping["PIP_NO_INDEX"] == "1"


def test_pyvenv_flag_is_read_from_the_file(tmp_path: Path) -> None:
    env = _env(tmp_path / "owned root")
    env.prefix.mkdir(parents=True)
    (env.prefix / "pyvenv.cfg").write_text("home = /usr/bin\ninclude-system-site-packages = false\n",
                                           encoding="utf-8")
    assert include_system_site_packages(env) is False
    (env.prefix / "pyvenv.cfg").write_text("include-system-site-packages = true\n", encoding="utf-8")
    assert include_system_site_packages(env) is True
    (env.prefix / "pyvenv.cfg").write_text("home = /usr/bin\n", encoding="utf-8")
    with pytest.raises(ValueError):
        include_system_site_packages(env)


def test_environment_roots_need_a_space_and_a_known_class(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="needs-space"):
        create_environment(tmp_path / "nospace", "pure-local")
    with pytest.raises(ValueError, match="class-unknown"):
        create_environment(tmp_path / "with space", "release")
    assert not (tmp_path / "nospace").exists() and not (tmp_path / "with space").exists()


def test_child_exit_never_reports_a_signal_or_deadline() -> None:
    assert ChildResult(0, "", "").exit == 0
    assert ChildResult(-9, "", "").exit is None
    assert ChildResult(None, "", "", timed_out=True).exit is None
    assert _env(Path("/r")).resource_root == Path("/r/venv/share/common-lore-index")


class _Process:
    pid = 12345
    stdin = stdout = stderr = None

    def __init__(self, error: BaseException | None = None, returncode: int = 0) -> None:
        self.error, self.final = error, returncode
        self.returncode: int | None = None
        self.killed = self.waited = 0

    def communicate(self, **_kwargs: object) -> tuple[str, str]:
        if self.error is not None:
            raise self.error
        self.returncode = self.final
        return "completed", ""

    def poll(self) -> int | None:
        return self.returncode

    def kill(self) -> None:
        self.killed += 1
        self.returncode = -9

    def wait(self, *, timeout: float) -> int:
        assert timeout > 0
        self.waited += 1
        assert self.returncode is not None
        return self.returncode


def test_direct_launch_uses_closed_environment_and_owns_a_session(tmp_path: Path, monkeypatch) -> None:
    process = _Process()
    launches: list[dict] = []

    def launch(_args: object, **kwargs: object) -> _Process:
        launches.append(kwargs)
        return process

    monkeypatch.setattr(owner, "popen_observed_process", launch)
    env = _env(tmp_path / "owned root")
    result = run_child(env, (str(env.python), "-c", "pass"))
    assert result.returncode == 0 and result.stdout == "completed"
    assert launches[0]["start_new_session"] is True
    assert launches[0]["cwd"] == env.cwd and launches[0]["family"] == "arch7f_probe"
    assert "PYTHONPATH" not in launches[0]["env"]


def test_deadline_reaps_owned_group_and_retains_bounded_partial_streams(tmp_path: Path, monkeypatch) -> None:
    failure = subprocess.TimeoutExpired("owned-child", 1, output=b"partial", stderr=b"diagnostic")
    process = _Process(failure)
    groups: list[tuple[int, int]] = []

    def kill_group(pid: int, sig: int) -> None:
        groups.append((pid, sig))
        process.returncode = -9

    monkeypatch.setattr(owner.os, "killpg", kill_group)
    monkeypatch.setattr(owner, "popen_observed_process", lambda *_a, **_k: process)
    with pytest.raises(ChildExecutionFailure) as caught:
        run_child(_env(tmp_path / "owned root"), ("owned-child",), timeout=1)
    assert caught.value.code == "child-deadline" and caught.value.unknown
    assert caught.value.stdout == "partial" and caught.value.stderr == "diagnostic"
    assert process.killed == 0 and process.waited == 1
    assert groups == [(process.pid, owner.signal.SIGKILL)]


def test_interrupt_identity_survives_owned_group_cleanup(tmp_path: Path, monkeypatch) -> None:
    failure = KeyboardInterrupt("owned interrupt")
    process = _Process(failure)
    groups: list[tuple[int, int]] = []

    def kill_group(pid: int, sig: int) -> None:
        groups.append((pid, sig))
        process.returncode = -9

    monkeypatch.setattr(owner.os, "killpg", kill_group)
    monkeypatch.setattr(owner, "popen_observed_process", lambda *_a, **_k: process)
    with pytest.raises(KeyboardInterrupt) as caught:
        run_child(_env(tmp_path / "owned root"), ("owned-child",))
    assert caught.value is failure and process.killed == 0 and process.waited == 1
    assert groups == [(process.pid, owner.signal.SIGKILL)]
    assert "installed-child-workspace-unproved" in failure.__notes__


def test_signal_is_an_unsettled_failure_even_with_normal_output(tmp_path: Path, monkeypatch) -> None:
    process = _Process(returncode=-9)
    monkeypatch.setattr(owner, "popen_observed_process", lambda *_a, **_k: process)
    with pytest.raises(ChildExecutionFailure) as caught:
        run_child(_env(tmp_path / "owned root"), ("owned-child",))
    assert caught.value.code == "child-signalled" and caught.value.unknown


def test_failure_diagnostic_omits_private_paths_and_payload(capsys) -> None:
    owner._exit_diagnostic(1, '  File "<string>", line 17, in <module>\n'
                          '  File "/private/home/custom.py", line 8, in fail\n'
                          'ValueError: UNAUTHORIZED-FIXTURE-TEXT\n')
    output = capsys.readouterr().out
    assert '"exception_type": "ValueError"' in output and '"script_line": 17' in output
    assert "/private" not in output and "UNAUTHORIZED-FIXTURE-TEXT" not in output
    owner._exit_diagnostic(1, "UNAUTHORIZED_IDENTIFIER\n")
    output = capsys.readouterr().out
    assert "UNAUTHORIZED_IDENTIFIER" not in output and '"exception_type": "process-exit"' in output

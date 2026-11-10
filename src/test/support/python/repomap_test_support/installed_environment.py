"""Explicit offline installed environments and their closed child environment (section 2).

A ``pure-local`` environment is a fresh ``system_site_packages=False`` venv
under an owned root whose path contains a space; ``provisioned-server`` (and the
A05 ``shared-site`` negative) inherit the SDK site. Every installed child gets a
closed mapping passed as ``env=``: the unmeasured family's prepared environment
with checkout, coverage, home, credential and PostgreSQL selectors deleted,
then fixed interpreter/locale/home/PATH values. Children run in an owned
unrelated working directory through the existing ``arch7f_*`` families.
"""

from __future__ import annotations

import os
import json
import re
import signal
import subprocess
import sys
import sysconfig
import venv
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from runner_coverage_bootstrap import resolve_bootstrap_capability
from runner_coverage_execution import popen_observed_process, prepare_child_coverage_environment

from installed_experience_pins import CHILD_DEADLINE_SECONDS, POSTGRES_BIN

ENV_CLASSES = ("pure-local", "incumbent-local", "provisioned-server", "shared-site")
DELETED_KEYS = frozenset({
    "PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP", "PYTHONUSERBASE", "PYTHONEXECUTABLE",
    "PYTHONSAFEPATH", "VIRTUAL_ENV", "PGHOST", "PGPORT", "PGUSER", "PGDATABASE", "PGSERVICE",
    "PGPASSWORD", "PGPASSFILE", "DATABASE_URL", "DOCKER_HOST", "REPOMAP_OPS_CONFIG",
    "REPOMAP_PSQL_COMMAND", "REPOMAP_HOME", "CLOE_HOME", "REPOMAP_MCP_CONFIG",
})
DELETED_MARKERS = ("PASSWORD", "PGPASS", "SECRET", "TOKEN", "REPOMAP_PG", "REPOMAP_STORAGE")
FIXED_VALUES = {
    "PYTHONNOUSERSITE": "1", "PYTHONDONTWRITEBYTECODE": "1", "PIP_NO_INDEX": "1",
    "PIP_DISABLE_PIP_VERSION_CHECK": "1", "LANG": "C.UTF-8",
}


@dataclass(frozen=True)
class InstalledEnvironment:
    root: Path
    env_class: str
    prefix: Path
    python: Path
    bin: Path
    purelib: Path
    data: Path
    user_home: Path
    cwd: Path

    def wrapper(self, name: str) -> Path:
        return self.bin / name

    @property
    def resource_root(self) -> Path:
        return self.data / "share" / "common-lore-index"


@dataclass(frozen=True)
class ChildResult:
    returncode: int | None
    stdout: str
    stderr: str
    timed_out: bool = False

    @property
    def exit(self) -> int | None:
        """Observation exit: a signal or deadline has no non-negative exit."""
        return self.returncode if self.returncode is not None and self.returncode >= 0 else None


class ChildExecutionFailure(RuntimeError):
    """Unsettled owned child; bounded partial streams remain private diagnostics."""

    def __init__(self, code: str, stdout: str = "", stderr: str = "") -> None:
        super().__init__(code)
        self.code, self.stdout, self.stderr = code, stdout, stderr
        self.unknown = True


def _partial(value: str | bytes | None, limit: int) -> str:
    text = value.decode("utf-8", errors="replace") if isinstance(value, bytes) else value or ""
    return text[:limit]


def _exit_diagnostic(returncode: int, stderr: str) -> None:
    """Closed failure context only; never print streams, arguments or private paths."""
    lines = stderr.splitlines()
    kind = lines[-1].partition(":")[0].rsplit(".", 1)[-1] if lines else "process-exit"
    allowed = {"AssertionError", "AttributeError", "FileNotFoundError", "ImportError",
               "ModuleNotFoundError", "OSError", "RepoMapMcpError", "RuntimeError",
               "StorageSchemaError", "SyntaxError", "TypeError", "ValueError"}
    if kind not in allowed:
        kind = "process-exit"
    frames = re.findall(r'File "<string>", line ([0-9]{1,6})', stderr)
    print(json.dumps({"event": "installed-child-exit", "exit": returncode,
                      "exception_type": kind, "script_line": int(frames[-1]) if frames else None},
                     sort_keys=True))


def _reap_owned_group(process: subprocess.Popen[str]) -> bool:
    """Reap the owned session group; separately-sessioned workers remain unproved."""
    try:
        group_reaped = True
        if process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            except OSError:
                group_reaped = False
                process.kill()
        process.wait(timeout=5)
        return group_reaped
    except (OSError, subprocess.TimeoutExpired):
        return False
    finally:
        for stream in (process.stdin, process.stdout, process.stderr):
            if stream is not None:
                try:
                    stream.close()
                except OSError:
                    pass


def _venv_paths(prefix: Path) -> tuple[Path, Path, Path]:
    variables = {"base": str(prefix), "platbase": str(prefix), "installed_base": str(prefix),
                 "installed_platbase": str(prefix)}
    purelib = Path(sysconfig.get_path("purelib", scheme="venv", vars=variables))
    data = Path(sysconfig.get_path("data", scheme="venv", vars=variables))
    scripts = Path(sysconfig.get_path("scripts", scheme="venv", vars=variables))
    return purelib, data, scripts


def create_environment(root: Path, env_class: str) -> InstalledEnvironment:
    """Create one owned venv; only the provisioned and shared-site classes see the SDK site."""
    if env_class not in ENV_CLASSES:
        raise ValueError("installed-environment-class-unknown")
    if " " not in str(root):
        raise ValueError("installed-environment-root-needs-space")
    root.mkdir(mode=0o700, parents=True, exist_ok=False)
    prefix = root / "venv"
    shared = env_class in ("provisioned-server", "shared-site")
    venv.EnvBuilder(with_pip=False, system_site_packages=shared, symlinks=True).create(prefix)
    purelib, data, scripts = _venv_paths(prefix)
    user_home, cwd = root / "user home", root / "unrelated cwd"
    for directory in (user_home, cwd):
        directory.mkdir(mode=0o700)
    return InstalledEnvironment(root, env_class, prefix, scripts / "python", scripts, purelib,
                                data, user_home, cwd)


def include_system_site_packages(env: InstalledEnvironment) -> bool:
    """Read ``pyvenv.cfg`` as a file; the classifier never trusts the label."""
    for line in (env.prefix / "pyvenv.cfg").read_text(encoding="utf-8").splitlines():
        key, _sep, value = line.partition("=")
        if key.strip() == "include-system-site-packages":
            return value.strip().lower() == "true"
    raise ValueError("installed-environment-config-incomplete")


def child_environment(
    env: InstalledEnvironment,
    extra: Mapping[str, str] | None = None,
    *,
    family: str = "arch7f_probe",
    base: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """The closed child mapping of section 2; ``extra`` is applied last and explicitly."""
    source = dict(os.environ if base is None else base)
    capability = resolve_bootstrap_capability(env=source)
    prepared = prepare_child_coverage_environment(source, family=family, capability=capability)
    closed = {key: value for key, value in prepared.items()
              if key not in DELETED_KEYS and not key.startswith("COVERAGE_")
              and not any(marker in key.upper() for marker in DELETED_MARKERS)}
    closed.update(FIXED_VALUES)
    closed["HOME"] = str(env.user_home)
    path = [str(env.bin), "/usr/bin", "/bin"]
    if env.env_class == "provisioned-server":
        path.insert(1, POSTGRES_BIN)
    closed["PATH"] = ":".join(path)
    closed.update(extra or {})
    return closed


def run_child(
    env: InstalledEnvironment,
    argv: Sequence[str],
    *,
    cwd: Path | None = None,
    input_text: str | None = None,
    extra: Mapping[str, str] | None = None,
    family: str = "arch7f_probe",
    timeout: float = CHILD_DEADLINE_SECONDS,
) -> ChildResult:
    """Run once; timeout/signal cannot become an ordinary successful observation."""
    mapping = child_environment(env, extra, family=family)
    capability = resolve_bootstrap_capability(env=mapping)
    process = popen_observed_process(
        list(argv), family=family, cwd=cwd or env.cwd, env=mapping,
        capability=capability, stdin=subprocess.PIPE if input_text is not None else None,
        start_new_session=True,
    )
    try:
        stdout, stderr = process.communicate(input=input_text, timeout=timeout)
    except subprocess.TimeoutExpired as error:
        reaped = _reap_owned_group(process)
        raise ChildExecutionFailure(
            "child-deadline" if reaped else "cleanup-failed",
            _partial(error.output, 2 * 1024 * 1024), _partial(error.stderr, 64 * 1024),
        ) from None
    except BaseException as error:
        reaped = _reap_owned_group(process)
        error.add_note("installed-child-workspace-unproved")
        if not reaped:
            error.add_note("installed-owned-group-cleanup-incomplete")
        raise
    if process.returncode is not None and process.returncode < 0:
        raise ChildExecutionFailure("child-signalled", _partial(stdout, 2 * 1024 * 1024),
                                    _partial(stderr, 64 * 1024))
    if process.returncode:
        _exit_diagnostic(process.returncode, stderr or "")
    return ChildResult(process.returncode, stdout or "", stderr or "")


# An installed workflow child is an ordinary ``arch7f_probe`` child.
run_installed = run_child


def install_wheel(env: InstalledEnvironment, wheel: Path) -> ChildResult:
    """``pip --python <env> install --no-index --no-deps`` under ``arch7f_pip``."""
    return run_child(env, (sys.executable, "-m", "pip", "--python", str(env.python), "install",
                           "--no-index", "--no-deps", str(wheel)), family="arch7f_pip")


def pip_check(env: InstalledEnvironment) -> ChildResult:
    """Independent requirement closure check under ``arch7f_pip``."""
    return run_child(env, (sys.executable, "-m", "pip", "--python", str(env.python), "check"),
                     family="arch7f_pip")


__all__ = [
    "ChildExecutionFailure", "ChildResult", "DELETED_KEYS", "ENV_CLASSES", "FIXED_VALUES", "InstalledEnvironment",
    "child_environment", "create_environment", "include_system_site_packages", "install_wheel",
    "pip_check", "run_child", "run_installed",
]

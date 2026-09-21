"""Explicit structured capability for runner-owned child coverage measurement."""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import os
from pathlib import Path
import secrets
import subprocess
from typing import Any, Sequence


class CoverageCapabilityError(RuntimeError):
    """Base error for capability failures."""


class CapabilityContainmentError(CoverageCapabilityError):
    """Raised when containment, symlink, or path boundaries are violated."""


class CapabilityRefusalError(CoverageCapabilityError):
    """Raised when suite or unauthorized operations are rejected."""


class CapabilityValidationError(CoverageCapabilityError):
    """Raised when validation of tokens, manifests, or shards fails."""


ALLOWED_SUITES = frozenset({"int", "staging"})
DISALLOWED_SUITES = frozenset({"unit", "smoke", "system", "inert"})
PathIdentity = tuple[int, int, int, int]


def _path_id(path: Path) -> PathIdentity:
    st = path.stat()
    return (st.st_dev, st.st_ino, st.st_mode, st.st_uid)


def _check_contained(path: Path, root: Path, label: str) -> None:
    try:
        if any(p.is_symlink() for p in (path, *path.parents)) or not path.resolve().is_relative_to(root.resolve()):
            raise CapabilityContainmentError(f"{label} {path} escapes or symlinks outside {root}")
    except (ValueError, OSError) as exc:
        raise CapabilityContainmentError(f"{label} invalid: {exc}") from exc


def compute_source_commitment(source_root: Path) -> str:
    """Compute deterministic commitment from git revision and current source bytes."""
    s_root = Path(source_root).resolve()
    try:
        p = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=str(Path(__file__).resolve().parents[1]),
            capture_output=True, text=True, check=True,
        )
        git_rev = p.stdout.strip()
        if len(git_rev) != 40 or any(c not in "0123456789abcdef" for c in git_rev):
            raise ValueError("invalid source revision")
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        raise CapabilityValidationError("source revision is unavailable") from exc

    py_files = sorted(
        f for f in s_root.rglob("*.py")
        if "__pycache__" not in f.parts and not f.name.startswith(".")
    )
    h = hashlib.sha256(git_rev.encode("utf-8"))
    for f in py_files:
        try:
            _check_contained(f, s_root, "source")
            h.update(str(f.relative_to(s_root)).encode("utf-8"))
            h.update(hashlib.sha256(f.read_bytes()).digest())
        except OSError as exc:
            raise CapabilityValidationError("source commitment is unreadable") from exc
    return h.hexdigest()


def _parse_marker(path: Path) -> dict[str, str]:
    if not path.is_file():
        raise CapabilityValidationError(f"marker file {path} missing or not a file")
    if path.is_symlink():
        raise CapabilityContainmentError(f"marker file {path} is a symlink")
    seen: set[str] = set()
    data: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or "=" not in line:
            continue
        k, v = (part.strip() for part in line.split("=", 1))
        if k in seen:
            raise CapabilityValidationError(f"duplicate marker key '{k}' in {path.name}")
        seen.add(k)
        data[k] = v
    return data


@dataclass
class ChildCoverageCapability:
    """Explicit capability governing child coverage instrumentation."""

    session: Any
    invocation_id: str
    suite: str
    source_commitment: str
    session_dir: Path
    config_file: Path
    bootstrap_dir: Path
    child_manifest_dir: Path
    data_dir: Path
    config_sha256: str
    bootstrap_sha256: str
    expected_config_bytes: bytes
    expected_bootstrap_bytes: bytes
    path_identities: dict[str, PathIdentity]
    permitted_python_paths: tuple[Path, ...]
    portable_command: tuple[str, ...] = field(
        default_factory=lambda: ("-m", "repomap_kg.coordinator.portable_worker")
    )
    registered_tokens: set[str] = field(default_factory=set)
    launched_pids: dict[str, int] = field(default_factory=dict)
    active: bool = True
    conformance_root: Path | None = None
    conformance_commitment: str | None = None
    launched_commands: dict[str, tuple[str, ...]] = field(default_factory=dict)

    @property
    def revision(self) -> str:
        return self.source_commitment

    def _verify_roots(self) -> None:
        if self.session is None or getattr(self.session, "_portable_capability", None) is not self:
            raise CapabilityValidationError("capability is not bound to active session")
        if self.session.session_dir.resolve() != self.session_dir.resolve():
            raise CapabilityValidationError("session_dir mutated or mismatched")
        if self.invocation_id != self.session.session_dir.name or self.suite != self.session.suite:
            raise CapabilityValidationError("invocation or suite mismatched with session")

        cur_rev = compute_source_commitment(self.session.source_root)
        if cur_rev != self.source_commitment:
            raise CapabilityValidationError(f"stale source revision: {cur_rev} != {self.source_commitment}")

        root = self.session_dir.resolve()
        for label, path in (
            ("session_dir", self.session_dir),
            ("config_file", self.config_file), ("bootstrap_dir", self.bootstrap_dir),
            ("child_manifest_dir", self.child_manifest_dir), ("data_dir", self.data_dir),
        ):
            _check_contained(path, root, label)
            if label not in self.path_identities or _path_id(path) != self.path_identities[label]:
                raise CapabilityContainmentError(f"{label} identity mismatch")
            if path.stat().st_uid != os.getuid() or path.stat().st_mode & 0o022:
                raise CapabilityContainmentError(f"{label} has foreign ownership or writable permissions")

    def validate_for_launch(self) -> None:
        """Validate capability authority, revision, and containment before launch."""
        if not self.active:
            raise CapabilityRefusalError("capability is inactive or expired")
        if self.suite in DISALLOWED_SUITES or self.suite not in ALLOWED_SUITES:
            err = f"suite '{self.suite}' is excluded from portable measurement" if self.suite in DISALLOWED_SUITES else f"unrecognized suite '{self.suite}'"
            raise CapabilityRefusalError(err)

        self._verify_roots()
        if not self.config_file.is_file() or self.config_file.is_symlink():
            raise CapabilityValidationError(f"config_file invalid: {self.config_file}")
        cfg_bytes = self.config_file.read_bytes()
        if cfg_bytes != self.expected_config_bytes or hashlib.sha256(cfg_bytes).hexdigest() != self.config_sha256:
            raise CapabilityValidationError("config_file content or sha256 mismatch")

        sc = self.bootstrap_dir / "sitecustomize.py"
        if not sc.is_file() or sc.is_symlink():
            raise CapabilityValidationError(f"bootstrap sitecustomize invalid: {sc}")
        sc_bytes = sc.read_bytes()
        if sc_bytes != self.expected_bootstrap_bytes or hashlib.sha256(sc_bytes).hexdigest() != self.bootstrap_sha256:
            raise CapabilityValidationError("bootstrap sitecustomize content or sha256 mismatch")

        for p in self.permitted_python_paths:
            if not p.resolve().is_dir() or p.is_symlink():
                raise CapabilityContainmentError(f"permitted python path invalid: {p}")

    def register_prelaunch_child(self, token: str | None = None) -> str:
        """Pre-register an expected child process token prior to launch."""
        self.validate_for_launch()
        tok = token or secrets.token_hex(16)
        if len(tok) != 32 or any(c not in "0123456789abcdef" for c in tok):
            raise CapabilityValidationError("invalid child registration token")
        if tok in self.registered_tokens:
            raise CapabilityValidationError(f"duplicate child token: {tok}")
        self.registered_tokens.add(tok)
        m = self.child_manifest_dir / f"{tok}.expected"
        m.write_text(f"token={tok}\ninvocation={self.invocation_id}\nsuite={self.suite}\nstatus=prelaunch\n", encoding="utf-8")
        return tok

    def paths_for_command(self, command: tuple[str, ...]) -> tuple[Path, ...]:
        """Select one exact launch identity without widening production paths."""
        if command == self.portable_command:
            return self.permitted_python_paths
        from runner_coverage_conformance import CONFORMANCE_COMMAND

        if command != CONFORMANCE_COMMAND or self.conformance_root is None:
            raise CapabilityValidationError("invalid worker command identity")
        expected_root = Path(__file__).resolve().parents[1] / "src/test/support/python"
        if self.conformance_root != expected_root:
            raise CapabilityContainmentError("conformance source root mismatch")
        if compute_source_commitment(self.conformance_root) != self.conformance_commitment:
            raise CapabilityValidationError("conformance source commitment mismatch")
        return (self.conformance_root, *self.permitted_python_paths)

    def validate_for_accept(self, token: str, pid: int | None = None) -> Path:
        """Validate child produced expected terminal markers and a readable coverage shard."""
        if not self.active:
            raise CapabilityRefusalError("capability is inactive or expired")
        if token not in self.registered_tokens:
            raise CapabilityRefusalError(f"unregistered child token cannot be accepted: {token}")

        self.validate_for_launch()
        md = self.child_manifest_dir
        if token in self.launched_commands:
            self.paths_for_command(self.launched_commands[token])
        for f in md.iterdir():
            if f.is_symlink():
                raise CapabilityContainmentError(f"symlink in manifest dir: {f}")

        exp_d = _parse_marker(md / f"{token}.expected")
        if (exp_d.get("token") != token or exp_d.get("invocation") != self.invocation_id
                or exp_d.get("suite") != self.suite or exp_d.get("status") != "prelaunch"):
            raise CapabilityValidationError(f"expected marker mismatch for {token}")

        start_p = md / f"{token}.start"
        if not start_p.is_file():
            raise CapabilityValidationError(f"start marker missing for {token}")
        start_d = _parse_marker(start_p)

        exit_p = md / f"{token}.exit"
        if not exit_p.is_file():
            raise CapabilityValidationError(f"terminal exit marker missing for {token}")
        exit_d = _parse_marker(exit_p)
        if start_d.get("cov_start") != "1":
            err = start_d.get("bootstrap_error")
            raise CapabilityValidationError(f"child collector bootstrap incomplete: {err}" if err else "child collector bootstrap incomplete")
        if exit_d.get("complete") != "1":
            if exit_d.get("error"):
                raise CapabilityValidationError(f"child reported coverage save failure: {exit_d.get('error')}")
            if exit_p.stat().st_size == 0:
                raise CapabilityValidationError("child terminal receipt empty (0 bytes)")
            raise CapabilityValidationError("child terminal receipt incomplete")
        for d, name in ((start_d, "start"), (exit_d, "exit")):
            if d.get("token") != token or d.get("invocation") != self.invocation_id:
                raise CapabilityValidationError(f"{name} marker token/invocation mismatch")
            if d.get("suite") != self.suite or d.get("revision") != self.source_commitment:
                raise CapabilityValidationError(f"{name} marker suite/revision mismatch")

        start_pid = start_d.get("pid")
        if not start_pid or not start_pid.isdigit() or int(start_pid) <= 0 or exit_d.get("pid") != start_pid:
            raise CapabilityValidationError("start/exit PID missing or mismatch")
        pid = pid if pid is not None else self.launched_pids.get(token)
        if pid is not None and str(pid) != start_pid:
            raise CapabilityValidationError(f"PID mismatch: expected {pid}, got {start_pid}")

        shard_str = exit_d.get("shard", "") or ((md / f"{token}.shard").read_text(encoding="utf-8").strip() if (md / f"{token}.shard").is_file() else "")
        if not shard_str:
            raise CapabilityValidationError(f"no coverage shard recorded for {token}")

        shard = Path(shard_str)
        _check_contained(shard, self.data_dir.resolve(), "shard")
        if shard.parent != self.data_dir or token not in shard.name.split("."):
            raise CapabilityValidationError("coverage shard does not belong to registered child")
        if exit_d.get("error"):
            raise CapabilityValidationError("child reported coverage save failure")
        if not shard.is_file() or shard.is_symlink() or shard.stat().st_size == 0:
            raise CapabilityValidationError(f"coverage shard {shard} is missing or 0 bytes")

        with open(shard, "rb") as s:
            if s.read(16) != b"SQLite format 3\x00":
                raise CapabilityValidationError(f"coverage shard {shard} has invalid SQLite header")

        cd = None
        try:
            import coverage
            cd = coverage.CoverageData(basename=str(shard))
            cd.read()
            measured = "selected_hits" if any(cd.lines(f) for f in cd.measured_files()) else "no_selected_hits"
            if exit_d.get("measurement") != measured:
                raise CapabilityValidationError("child measurement content mismatch")
        except CapabilityValidationError:
            raise
        except Exception as exc:
            raise CapabilityValidationError(f"coverage shard schema read error: {exc}") from exc
        finally:
            if cd is not None and hasattr(cd, "close"):
                cd.close()
        return shard

    def deactivate(self) -> None:
        self.active = False


def issue_coverage_capability(
    *,
    session: Any,
    suite: str | None = None,
    revision: str | None = None,
    permitted_python_paths: Sequence[Path | str] = (),
    portable_command: tuple[str, ...] = ("-m", "repomap_kg.coordinator.portable_worker"),
    allow_test_conformance: bool = False,
) -> ChildCoverageCapability:
    """Factory creating and validating a structured ChildCoverageCapability."""
    if session is None or not hasattr(session, "session_dir"):
        raise CapabilityValidationError("capability requires an active ChildCoverageSession")

    eff_suite = suite or getattr(session, "suite", "inert")
    if eff_suite in DISALLOWED_SUITES:
        raise CapabilityRefusalError(f"suite '{eff_suite}' is excluded from portable measurement")
    if eff_suite not in ALLOWED_SUITES:
        raise CapabilityRefusalError(f"unrecognized suite '{eff_suite}'")

    from runner_coverage_bootstrap import generate_bootstrap_source

    s_dir, cfg_file = Path(session.session_dir).resolve(), Path(session.config_file).resolve()
    boot_dir, man_dir = Path(session.bootstrap_dir).resolve(), Path(session.child_manifest_dir).resolve()
    dat_dir = Path(session.data_dir).resolve()

    exp_boot = generate_bootstrap_source().encode("utf-8")
    boot_sha = hashlib.sha256(exp_boot).hexdigest()

    exp_cfg = (
        session._derive_expected_config_bytes()
        if hasattr(session, "_derive_expected_config_bytes")
        else (cfg_file.read_bytes() if cfg_file.is_file() else b"")
    )
    cfg_sha = hashlib.sha256(exp_cfg).hexdigest()
    source_rev = compute_source_commitment(Path(session.source_root).resolve())
    if revision is not None and revision not in ("current", source_rev):
        raise CapabilityValidationError(f"caller revision '{revision}' rejected; must match {source_rev}")

    p_ids: dict[str, PathIdentity] = {
        "session_dir": _path_id(s_dir), "config_file": _path_id(cfg_file),
        "bootstrap_dir": _path_id(boot_dir), "child_manifest_dir": _path_id(man_dir),
        "data_dir": _path_id(dat_dir),
    }
    sc = boot_dir / "sitecustomize.py"
    if sc.is_file():
        p_ids["sitecustomize"] = _path_id(sc)

    cap = ChildCoverageCapability(
        session=session, invocation_id=s_dir.name, suite=eff_suite, source_commitment=source_rev,
        session_dir=s_dir, config_file=cfg_file, bootstrap_dir=boot_dir, child_manifest_dir=man_dir,
        data_dir=dat_dir, config_sha256=cfg_sha, bootstrap_sha256=boot_sha,
        expected_config_bytes=exp_cfg, expected_bootstrap_bytes=exp_boot, path_identities=p_ids,
        permitted_python_paths=tuple(Path(p).resolve() for p in permitted_python_paths),
        portable_command=portable_command,
    )
    session._portable_capability = cap
    repo_root = Path(__file__).resolve().parents[1]
    if (allow_test_conformance
            and portable_command == ("-m", "repomap_kg.coordinator.portable_worker")
            and Path(session.source_root).resolve() == repo_root / "src/main/python"):
        cap.conformance_root = repo_root / "src/test/support/python"
        cap.conformance_commitment = compute_source_commitment(cap.conformance_root)
    cap.validate_for_launch()
    return cap


def prepare_session_capability(
    session: Any, *, suite: str | None = None, revision: str | None = None,
    permitted_python_paths: Sequence[Path | str] = (), allow_test_conformance: bool = False,
    portable_command: tuple[str, ...],
) -> ChildCoverageCapability:
    """Prepare invocation assets and source paths before issuing the capability."""
    from runner_coverage_bootstrap import install_bootstrap_directory

    eff_suite = suite or session.suite
    if eff_suite not in ALLOWED_SUITES:
        raise CapabilityRefusalError(f"suite '{eff_suite}' cannot issue portable capability")
    install_bootstrap_directory(session.bootstrap_dir)
    session._write_config()
    paths = list(session.source_paths)
    if session.source_root.is_dir() and session.source_root not in paths:
        paths.append(session.source_root)
    for path in permitted_python_paths:
        resolved = Path(path).resolve()
        if resolved not in paths:
            paths.append(resolved)
    return issue_coverage_capability(
        session=session, suite=eff_suite, revision=revision,
        permitted_python_paths=paths, portable_command=portable_command,
        allow_test_conformance=allow_test_conformance,
    )


__all__ = (
    "ALLOWED_SUITES",
    "CapabilityContainmentError",
    "CapabilityRefusalError",
    "CapabilityValidationError",
    "ChildCoverageCapability",
    "CoverageCapabilityError",
    "DISALLOWED_SUITES",
    "compute_source_commitment",
    "issue_coverage_capability",
)

"""Coverage measurement, policy thresholds, and reporting helpers for test runner."""

from __future__ import annotations

import hashlib
import os
from collections.abc import Sequence
from pathlib import Path
import tempfile
from typing import Any
from runner_coverage_bootstrap import (
    BOOTSTRAP_TEMPLATE,
    BootstrapCapabilityRecord,
    derive_container_mount_aliases,
)
from runner_coverage_combine import close_owned_runners, combine_and_reload
import runner_coverage_execution as _execution
from runner_coverage_observer import ProcessObserver
import runner_coverage_reports as _reports

# Re-export reporting constants and policy
REPO_ROOT = _reports.REPO_ROOT
SOURCE_ROOT = _reports.SOURCE_ROOT

DEFAULT_INT_LINE_HARD_THRESHOLD = _reports.DEFAULT_INT_LINE_HARD_THRESHOLD
DEFAULT_INT_BRANCH_HARD_THRESHOLD = _reports.DEFAULT_INT_BRANCH_HARD_THRESHOLD
DEFAULT_UNIT_STATEMENT_HARD_THRESHOLD = _reports.DEFAULT_UNIT_STATEMENT_HARD_THRESHOLD
DEFAULT_UNIT_BRANCH_HARD_THRESHOLD = _reports.DEFAULT_UNIT_BRANCH_HARD_THRESHOLD
DEFAULT_ADVISORY_THRESHOLD = _reports.DEFAULT_ADVISORY_THRESHOLD

CoveragePolicy = _reports.CoveragePolicy
coverage_policy_for_suite = _reports.coverage_policy_for_suite
coverage_file_status = _reports.coverage_file_status
coverage_json_path = _reports.coverage_json_path
coverage_record_from_summary = _reports.coverage_record_from_summary
coverage_record_from_analysis = _reports.coverage_record_from_analysis
percentage = _reports.percentage
is_relative_to = _reports.is_relative_to
report_coverage = _reports.report_coverage

# Re-export execution snapshots
ShardDiagnosticSnapshot = _execution.ShardDiagnosticSnapshot


coverage_records_from_json = _reports.coverage_records_from_json


def collect_coverage_summary(*args: Any, **kwargs: Any) -> Any:
    kwargs.setdefault("source_root", SOURCE_ROOT)
    return _reports.collect_coverage_summary(*args, **kwargs)


class ChildCoverageSession:
    """Manages child process coverage collection and deterministic combination."""

    def __init__(
        self,
        *,
        coverage_module: Any = None,
        scratch_dir: Path | None = None,
        source_root: Path = SOURCE_ROOT,
        source_paths: Sequence[Path | str] = (),
        suite: str = "inert",
    ) -> None:
        self.coverage_module = coverage_module
        self._temp_dir: tempfile.TemporaryDirectory | None = None
        if scratch_dir is not None:
            if Path(scratch_dir).is_symlink():
                raise ValueError("coverage scratch root must not be a symlink")
            self.session_dir = Path(scratch_dir).resolve()
            self.session_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
            if suite in ("int", "staging"):
                self._temp_dir = tempfile.TemporaryDirectory(prefix="invocation-", dir=self.session_dir)
                self.session_dir = Path(self._temp_dir.name)
        else:
            self._temp_dir = tempfile.TemporaryDirectory(prefix="repomap-coverage-session-")
            self.session_dir = Path(self._temp_dir.name).resolve()
        self.source_root = Path(source_root).resolve()
        self.source_paths = tuple(Path(p).resolve() for p in source_paths)
        self.suite = suite
        self.data_dir = self.session_dir / "shards"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.data_file = self.data_dir / ".coverage"
        self.config_file = self.session_dir / "coverage.rc"
        self._prev_env: dict[str, str | None] = {}
        self._coverage_runner: Any = None
        self._created_collector: Any = None
        self._expected_parent_data_file: str | None = None
        self._combined_runner: Any = None
        self.measurement_errors: list[Exception] = []
        self.source_rejections: list[str] = []
        self.diagnostic_snapshots: list[ShardDiagnosticSnapshot] = []
        self.child_manifest_dir = self.session_dir / "child_procs"
        self.child_manifest_dir.mkdir(parents=True, exist_ok=True)
        self.observation_dir = self.session_dir / "observations"
        self.observation_dir.mkdir(parents=True, exist_ok=True)
        self.bootstrap_dir = self.session_dir / "bootstrap"
        self.invocation_id = self.session_dir.name
        b_ident = hashlib.sha256(BOOTSTRAP_TEMPLATE.encode("utf-8")).hexdigest()
        self.bootstrap_capability = BootstrapCapabilityRecord(
            identity=b_ident, host_visible_path=self.bootstrap_dir,
            same_namespace_path=self.bootstrap_dir,
            container_mount_aliases=derive_container_mount_aliases(self.bootstrap_dir),
        )
        self.process_observer = ProcessObserver(
            observation_dir=self.observation_dir, invocation_id=self.invocation_id,
            capability=self.bootstrap_capability,
        )
        self._portable_capability: Any = None
        self._adapter_cm: Any = None

    def record_measurement_error(self, error: Exception) -> None:
        self.measurement_errors.append(error)

    def _create_snapshot(
        self,
        *,
        shard_name: str,
        file_type: str,
        size_bytes: int,
        sha256: str | None,
        reader_status: str,
        stage: str,
        cov_mod: Any = None,
        child_probe_id: str | None = None,
        termination_outcome: str | None = None,
        launch_role: str | None = None,
        test_owner: str | None = None,
    ) -> ShardDiagnosticSnapshot:
        return _execution.create_shard_snapshot(
            session_name=self.session_dir.name, shard_name=shard_name, file_type=file_type,
            size_bytes=size_bytes, sha256=sha256, reader_status=reader_status, stage=stage,
            coverage_module=cov_mod or self.coverage_module, source_root=self.source_root,
            source_paths=self.source_paths, child_probe_id=child_probe_id,
            termination_outcome=termination_outcome,
            launch_role=launch_role, test_owner=test_owner,
        )

    def _record_diagnostic(self, snapshot: ShardDiagnosticSnapshot) -> None:
        _execution.record_diagnostic(
            self.diagnostic_snapshots, snapshot, self.session_dir,
        )

    def _verify_source_identity(self, copy_dir: Path) -> bool:
        py_files = list(copy_dir.rglob("*.py"))
        if not py_files:
            self.source_rejections.append(f"{copy_dir}: no python files found")
            return False
        canon_py_files = list(self.source_root.rglob("*.py"))
        copy_rels = {f.relative_to(copy_dir) for f in py_files}
        canon_rels = {f.relative_to(self.source_root) for f in canon_py_files}
        if copy_rels != canon_rels:
            self.source_rejections.append(f"{copy_dir}: file inventory mismatch")
            return False
        for rel in copy_rels:
            copy_file, canonical = copy_dir / rel, self.source_root / rel
            if not canonical.is_file() or copy_file.stat().st_size != canonical.stat().st_size:
                self.source_rejections.append(f"{copy_file}: file mismatch with {canonical}")
                return False
            if hashlib.sha256(copy_file.read_bytes()).digest() != hashlib.sha256(canonical.read_bytes()).digest():
                self.source_rejections.append(f"{copy_file}: sha256 mismatch with {canonical}")
                return False
        return True

    def _derive_expected_config(self) -> str:
        all_sources = [str(self.source_root)]
        approved_paths = [str(self.source_root)]
        for p in self.source_paths:
            p_path = Path(p).resolve()
            if p_path.is_dir() and self._verify_source_identity(p_path):
                sp = str(p_path)
                if sp not in all_sources:
                    all_sources.append(sp)
                approved_paths.append(sp)
        sources_block = "\n    ".join(all_sources)
        paths_block = "\n    ".join(approved_paths)
        return (
            "[run]\nbranch = True\nparallel = True\n"
            f"data_file = {self.data_file}\nsource =\n    {sources_block}\n\n"
            f"[paths]\nsource =\n    {paths_block}\n"
        )

    def _derive_expected_config_bytes(self) -> bytes:
        return self._derive_expected_config().encode("utf-8")

    def _write_config(self) -> None:
        self.config_file.write_text(self._derive_expected_config(), encoding="utf-8")

    def _write_sitecustomize(self) -> None:
        from runner_coverage_bootstrap import generate_bootstrap_source
        (self.session_dir / "sitecustomize.py").write_text(generate_bootstrap_source(), encoding="utf-8")

    def issue_portable_capability(
        self,
        *,
        suite: str | None = None,
        revision: str | None = None,
        permitted_python_paths: Sequence[Path | str] = (),
        portable_command: tuple[str, ...] = ("-m", "repomap_kg.coordinator.portable_worker"),
        allow_test_conformance: bool = False,
    ) -> Any:
        from runner_coverage_capability import prepare_session_capability
        return prepare_session_capability(
            self, suite=suite, revision=revision,
            permitted_python_paths=permitted_python_paths, portable_command=portable_command,
            allow_test_conformance=allow_test_conformance,
        )

    def purge_shards(self) -> None:
        for d in (self.data_dir, self.child_manifest_dir):
            if d.exists():
                for child in d.iterdir():
                    if d is self.child_manifest_dir or child.name.startswith(".coverage"):
                        try:
                            child.unlink()
                        except OSError:
                            pass

    def _restore_env(self) -> None:
        for key, val in self._prev_env.items():
            if val is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = val

    def __enter__(self) -> ChildCoverageSession:
        self.purge_shards()
        self._write_config()
        self._write_sitecustomize()
        (self.observation_dir / "invocation_id.txt").write_text(
            self.invocation_id, encoding="utf-8"
        )
        env_vars = (
            "COVERAGE_PROCESS_START", "PYTHONPATH", "COVERAGE_CHILD_MANIFEST_DIR",
            "COVERAGE_SESSION_INVOCATION_ID", "COVERAGE_SESSION_SUITE",
            "COVERAGE_SESSION_REVISION",
        )
        for var in env_vars:
            self._prev_env[var] = os.environ.get(var)
        os.environ["COVERAGE_PROCESS_START"] = str(self.config_file)
        os.environ["COVERAGE_CHILD_MANIFEST_DIR"] = str(self.child_manifest_dir)
        os.environ["COVERAGE_SESSION_INVOCATION_ID"] = self.invocation_id
        os.environ["COVERAGE_SESSION_SUITE"] = self.suite
        orig_pp = os.environ.get("PYTHONPATH", "")
        os.environ["PYTHONPATH"] = f"{self.session_dir}:{orig_pp}" if orig_pp else str(self.session_dir)
        if self.suite in ("int", "staging"):
            try:
                from runner_portable_coverage import scoped_portable_coverage_adapter
                # Integration/staging own the closed test conformance matrix.
                cap = self.issue_portable_capability(allow_test_conformance=True)
                os.environ["COVERAGE_SESSION_REVISION"] = cap.source_commitment
                self._adapter_cm = scoped_portable_coverage_adapter(self, cap)
                self._adapter_cm.__enter__()
            except Exception as exc:
                self._restore_env()
                snap = self._create_snapshot(
                    shard_name="session_enter", file_type="adapter_setup_error",
                    size_bytes=-1, sha256=None, reader_status=f"adapter_setup_failed: {exc}",
                    stage="session_enter", termination_outcome="adapter_setup_failed",
                )
                self._record_diagnostic(snap)
                self.record_measurement_error(exc)
                raise
        return self

    def __exit__(self, exc_type: object, exc_val: object, exc_tb: object) -> None:
        # Reporting may outlive this environment scope. Call cleanup after the
        # last data read, with every session-owned collector already stopped.
        if self._adapter_cm is not None:
            try:
                self._adapter_cm.__exit__(exc_type, exc_val, exc_tb)
            finally:
                self._adapter_cm = None
        self._restore_env()

    def cleanup(self) -> None:
        if self._portable_capability is not None:
            self._portable_capability.deactivate()
        try:
            if not getattr(self, "_data_settled", False):
                close_owned_runners((self._created_collector, self._coverage_runner, self._combined_runner))
                self._data_settled = True
        finally:
            if self._temp_dir is not None:
                self._temp_dir.cleanup()
                self._temp_dir = None

    def __del__(self) -> None:
        self.cleanup()

    def create_coverage(self, coverage_module: Any = None) -> Any:
        cov_mod = coverage_module or self.coverage_module
        if cov_mod is None:
            raise RuntimeError("coverage module must be provided")
        runner = cov_mod.Coverage(
            config_file=str(self.config_file), data_file=str(self.data_file), branch=True,
        )
        self._coverage_runner = runner
        self._created_collector = runner
        self._expected_parent_data_file = str(self.data_file.resolve())
        return runner

    def combine(self, coverage_runner: Any = None) -> Any:
        if self._combined_runner is not None:
            return self._combined_runner
        if self.measurement_errors:
            raise RuntimeError(f"coverage measurement failed: {self.measurement_errors[0]}")

        runner = coverage_runner or self._created_collector or self._coverage_runner
        if (coverage_runner is not None and self._created_collector is not None
                and coverage_runner is not self._created_collector):
            raise RuntimeError("parent runner substitution detected")

        cov_mod = self.coverage_module
        if cov_mod is None and runner is not None:
            cov_mod = getattr(runner, "_coverage", None) or getattr(runner, "coverage", None)
        if cov_mod is None:
            import coverage as cov_mod

        if not self.data_dir.exists():
            return runner

        registered_children = _execution.read_registered_children(
            self.child_manifest_dir,
            expected_invocation=self.session_dir.name if self.suite in ("int", "staging") else None,
            expected_suite=self.suite if self.suite in ("int", "staging") else None,
            expected_revision=(self._portable_capability.source_commitment
                               if self._portable_capability is not None else None),
        )
        if self._portable_capability is not None:
            for token in sorted(self._portable_capability.registered_tokens):
                self._portable_capability.validate_for_accept(token)
            if any(info.get("token") and info["token"] not in self._portable_capability.registered_tokens
                   for info in registered_children.values()):
                raise RuntimeError("unregistered portable child marker")
        if any(p.is_symlink() for p in self.data_dir.iterdir() if p.name.startswith(".coverage")):
            raise RuntimeError("coverage shard symlink rejected")
        shard_paths = [
            str(p.resolve())
            for p in sorted(self.data_dir.iterdir(), key=lambda item: item.name)
            if p.name.startswith(".coverage.")
        ]
        consumed_by_child, consumed_shards = _execution.reconcile_child_manifests(
            registered_children=registered_children, shard_paths_set=set(shard_paths),
            child_manifest_dir=self.child_manifest_dir,
            parent_data_path=str(self.data_file.resolve()), parent_pid=os.getpid(),
            snapshot_fn=self._create_snapshot, record_fn=self._record_diagnostic, cov_mod=cov_mod,
        )

        parent_shard = _execution.identify_parent_shard(
            runner, self.data_dir, self._expected_parent_data_file,
        )
        allowed_shards = set(consumed_shards)
        if parent_shard:
            allowed_shards.add(parent_shard)

        from runner_portable_coverage import validate_shard_directory_integrity
        validate_shard_directory_integrity(
            data_dir=self.data_dir, allowed_shards=allowed_shards, parent_shard=parent_shard,
            snapshot_fn=self._create_snapshot, record_fn=self._record_diagnostic, cov_mod=cov_mod,
            source_root=self.source_root, checkout_root=REPO_ROOT,
            invocation_id=self.invocation_id, observer=self.process_observer,
        )

        shards_to_combine = sorted(consumed_shards)
        if parent_shard:
            shards_to_combine.insert(0, parent_shard)

        if not shards_to_combine:
            if runner is not None:
                runner.load()
            self._combined_runner = runner
            return runner

        for sp in shards_to_combine:
            _execution.validate_shard_file(
                sp=sp, registered_children=registered_children,
                snapshot_fn=self._create_snapshot, record_fn=self._record_diagnostic, cov_mod=cov_mod,
            )

        accumulator = cov_mod.Coverage(
            config_file=str(self.config_file), data_file=str(self.data_file), branch=True,
        )
        combine_and_reload(accumulator, lambda: _execution.execute_shard_combine(
            accumulator=accumulator, shard_paths=shards_to_combine, cov_mod=cov_mod,
            snapshot_fn=self._create_snapshot, record_fn=self._record_diagnostic,
        ))
        self._coverage_runner = accumulator
        self._combined_runner = accumulator
        return accumulator

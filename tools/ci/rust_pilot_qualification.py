"""One bounded AMD qualification command; positive D12 and exact image are prerequisites."""

from __future__ import annotations

import argparse
from contextlib import ExitStack
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any, Sequence

_ROOT = Path(__file__).resolve().parents[2]
for _relative in ("tools", "src/main/python", "src/test/support/python"):
    _entry = str((_ROOT / _relative).resolve())
    if _entry not in sys.path:
        sys.path.insert(0, _entry)

from common_lore_index.extractors.contracts.vocabulary import ContractError

from ci.qualification_rust_acquisition import AcquisitionError
from ci.qualification_rust_accounting import AccountingGap, require_component_accounting
from ci.qualification_rust_shape import command_work_deadline, require_work_deadline
from ci.qualification_rust_import_guard import HostImportRefused, host_import_guard
from ci.qualification_rust_shape import source_digests
from ci.qualification_rust_manifest import ManifestError, fixture_paths, validate_manifest
from ci.qualification_rust_runtime import RuntimeGap, run_native_component

REPORT_SCHEMA = "cloe-rust-pilot-qualification-report-v1"
INTENT_SCHEMA = "cloe-rust-pilot-qualification-intent-v1"


class PrerequisiteRefused(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _counter(value: int | None, basis: str, checked: bool) -> dict[str, Any]:
    return {"value": value, "basis": basis, "cross_checked": checked}


def _initial() -> dict[str, Any]:
    names = ("containers", "parses", "builds", "pulls", "images", "volumes")
    return {"schema": REPORT_SCHEMA, "result": "not-executed", "qualified": False,
            "reason": "not_started", "candidate_sha": None, "files": [], "costs": {},
            "counters": {"downloads": _counter(0, "pre-work", True),
                         **{name: _counter(0, "pre-work", True) for name in names}}}


def _write_report(directory: Path, report: dict[str, Any]) -> None:
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    data = json.dumps(report, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")
    if len(data) > 1_048_576:
        raise RuntimeError("report_bound_exceeded")
    with (directory / "rust-pilot-qualification.json").open("xb") as handle:
        handle.write(data + b"\n")


def _intent(directory: Path) -> None:
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        handle = (directory / "rust-pilot-attempt-intent.json").open("xb")
        try:
            handle.write(json.dumps({"schema": INTENT_SCHEMA, "architecture": "amd64",
                                     "candidate_binding": "sealed_d12"},
                                    sort_keys=True, separators=(",", ":")).encode("ascii") + b"\n")
        finally:
            handle.close()
    except FileExistsError:
        raise PrerequisiteRefused("attempt_intent_already_exists") from None
    except OSError:
        raise PrerequisiteRefused("attempt_intent_unwritable") from None


def _sealed(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        raise PrerequisiteRefused("d12_sealed_json_invalid") from None
    if not isinstance(value, dict):
        raise PrerequisiteRefused("d12_sealed_json_mapping")
    return value


def _positive_d12(sealed_path: Path, state_dir: Path) -> tuple[str, str, str, str]:
    if sealed_path.resolve().parent != state_dir.resolve():
        raise PrerequisiteRefused("d12_state_path_mismatch")
    from ci.d12_hosted_evidence import validate_sealed_d12_evidence

    evidence = _sealed(sealed_path)
    if validate_sealed_d12_evidence(evidence, require_positive_qualification=True):
        raise PrerequisiteRefused("d12_positive_evidence_invalid")
    env, sdk = evidence["native_environment"], evidence["sdk_materialization"]
    if env.get("runner_arch") != "X64" or sdk.get("sdk_architecture") != "amd64":
        raise PrerequisiteRefused("d12_architecture_mismatch")
    return (evidence["pr_binding"]["candidate_sha"], evidence["pr_binding"]["candidate_tree"],
            sdk["sdk_image_id"], sdk["sdk_recipe_sha256"])


def _git(root: Path, *args: str) -> str:
    try:
        result = subprocess.run(["git", *args], cwd=root, check=True, text=True,
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=10)
    except (OSError, subprocess.SubprocessError):
        raise PrerequisiteRefused("git_evidence_unavailable") from None
    value = result.stdout.strip()
    if len(value) != 40 or any(char not in "0123456789abcdef" for char in value):
        raise PrerequisiteRefused("git_identity_invalid")
    return value


def _bind_candidate(root: Path, manifest: dict[str, Any], sealed_sha: str,
                    sealed_tree: str, manifest_path: Path) -> None:
    head, tree = _git(root, "rev-parse", "--verify", "HEAD"), _git(root, "rev-parse", "--verify", "HEAD^{tree}")
    checkpoint = manifest["source_checkpoint"]
    if (head != sealed_sha or tree != sealed_tree
            or _git(root, "rev-parse", "--verify", checkpoint["sha"]) != checkpoint["sha"]
            or _git(root, "rev-parse", "--verify", f'{checkpoint["sha"]}^{{tree}}') != checkpoint["tree"]):
        raise PrerequisiteRefused("candidate_binding_mismatch")
    try:
        subprocess.run(["git", "merge-base", "--is-ancestor", checkpoint["sha"], head],
                       cwd=root, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
        relative = manifest_path.resolve().relative_to(root.resolve()).as_posix()
        present = subprocess.run(["git", "cat-file", "-e", f'{checkpoint["sha"]}:{relative}'],
                                 cwd=root, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10).returncode == 0
    except (OSError, subprocess.SubprocessError, ValueError):
        raise PrerequisiteRefused("source_checkpoint_invalid") from None
    if present:
        raise PrerequisiteRefused("checkpoint_contains_manifest")
    _bind_committed_files(root, manifest, relative)


def _bind_committed_files(root: Path, manifest: dict[str, Any], relative_manifest: str) -> None:
    """Bind exact working bytes to regular candidate blobs, including the manifest."""
    paths = set(manifest["closure"]["python_paths"]) | {relative_manifest,
        manifest["incumbent"]["report_path"], *manifest["sdk"]["recipe_files"]}
    fixture = manifest["fixture"]
    paths.update(str(Path(fixture["root"]) / path) for path in fixture["files"])
    try:
        done = subprocess.run(["git", "ls-tree", "-rz", "HEAD", "--", *sorted(paths)],
                              cwd=root, check=True, stdout=subprocess.PIPE,
                              stderr=subprocess.DEVNULL, timeout=10)
        committed = {}
        for record in done.stdout.split(b"\0"):
            if not record:
                continue
            metadata, name = record.split(b"\t", 1)
            mode, kind, oid = metadata.split()
            if mode not in (b"100644", b"100755") or kind != b"blob":
                raise PrerequisiteRefused("committed_input_not_regular")
            committed[name.decode("utf-8")] = oid.decode("ascii")
        if set(committed) != paths:
            raise PrerequisiteRefused("committed_input_path_set_mismatch")
        for path in sorted(paths):
            raw = (root / path).read_bytes()
            # The repository's enforced 40-hex commit format is Git SHA-1.
            computed_oid = hashlib.sha1(b"blob " + str(len(raw)).encode("ascii") + b"\0" + raw,
                               usedforsecurity=False).hexdigest()
            if computed_oid != committed[path]:
                raise PrerequisiteRefused("committed_input_bytes_mismatch")
    except PrerequisiteRefused:
        raise
    except (OSError, UnicodeError, ValueError, subprocess.SubprocessError):
        raise PrerequisiteRefused("committed_input_unavailable") from None


def _verify_sdk(root: Path, manifest: dict[str, Any], image_id: str, recipe: str, *,
                work_deadline: float | None = None) -> None:
    sdk = manifest["sdk"]
    if recipe != sdk["recipe_sha256"]:
        raise PrerequisiteRefused("sdk_recipe_mismatch")
    for relative, expected in sdk["recipe_files"].items():
        try:
            actual = hashlib.sha256((root / relative).read_bytes()).hexdigest()
        except OSError:
            raise PrerequisiteRefused("sdk_recipe_missing") from None
        if actual != expected:
            raise PrerequisiteRefused("sdk_recipe_mismatch")
    docker_cli = shutil.which("docker")
    if not docker_cli:
        raise PrerequisiteRefused("docker_unavailable")
    from common_lore_index.extractors.rust_pilot.docker_boundary import DockerBoundary
    boundary = DockerBoundary(docker_cli)
    boundary.limit_work_deadline(work_deadline)
    server = boundary.server()
    if server.os != "linux" or server.arch not in {"x86_64", "amd64"}:
        raise PrerequisiteRefused("docker_server_mismatch")
    boundary.check_image(image_id, "amd64")
    boundary.require_work_deadline()
    inspected = boundary.run(["image", "inspect", image_id])
    try:
        documents = json.loads(inspected.stdout)
        image = documents[0]
        labels = image["Config"]["Labels"]
        valid = (inspected.clean and len(documents) == 1 and image["Id"] == image_id
                 and labels["org.repomap.test.sandbox.image"] == "true"
                 and labels["org.repomap.test.sandbox.recipe"] == recipe)
    except (ValueError, KeyError, IndexError, TypeError):
        valid = False
    if not valid:
        raise PrerequisiteRefused("sdk_image_label_mismatch")


def _null_after(report: dict[str, Any], reason: str) -> None:
    for name in ("containers", "parses", "builds", "pulls", "images", "volumes"):
        report["counters"][name] = _counter(None, reason, False)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("architecture", choices=("amd64",))
    for name in ("repo-root", "d12-state-dir", "d12-sealed-json", "manifest", "work-dir", "report-dir"):
        parser.add_argument("--" + name, dest=name.replace("-", "_"), type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    work_deadline = command_work_deadline()
    report, phase, work_created = _initial(), "before-work", False
    intent_created = False
    guard = ExitStack()
    try:
        _intent(args.report_dir)
        intent_created = True
        require_work_deadline(work_deadline)
        guard.enter_context(host_import_guard())
        from ci.qualification_rust_shape import check_work_report_paths
        check_work_report_paths(args.work_dir, args.report_dir)
        require_work_deadline(work_deadline)
        sealed_sha, sealed_tree, image_id, recipe = _positive_d12(args.d12_sealed_json, args.d12_state_dir)
        report["candidate_sha"] = sealed_sha
        phase = "manifest"
        require_work_deadline(work_deadline)
        manifest = validate_manifest(args.manifest, args.repo_root)
        guard.enter_context(host_import_guard(args.repo_root, source_digests(manifest["closure"])))
        _bind_candidate(args.repo_root, manifest, sealed_sha, sealed_tree, args.manifest)
        require_work_deadline(work_deadline)
        _verify_sdk(args.repo_root, manifest, image_id, recipe, work_deadline=work_deadline)
        require_work_deadline(work_deadline)
        report["candidate_sha"], phase = sealed_sha, "acquisition"
        args.work_dir.mkdir(mode=0o700, parents=False, exist_ok=False)
        work_created = True
        from ci.qualification_rust_acquisition import acquire_exact_amd_wheels
        wheels = acquire_exact_amd_wheels(manifest, args.work_dir / "amd-wheels", work_deadline=work_deadline)
        report["acquisitions"] = list(wheels)
        report["counters"]["downloads"] = _counter(len(wheels), "exact-transfer", True)
        require_work_deadline(work_deadline)
        phase = "profile"
        from common_lore_index.extractors.rust_pilot.prepared_profile import prepare_profile
        profile_dir = args.work_dir / "profile"
        if prepare_profile(args.work_dir / "amd-wheels", profile_dir, "x86_64") != manifest["sdk"]["profile_sha256"]:
            raise PrerequisiteRefused("profile_digest_mismatch")
        require_work_deadline(work_deadline)
        phase = "native"
        audit_dir = args.report_dir / "audit"
        audit_dir.mkdir(mode=0o700, parents=False, exist_ok=False)
        fixture_root, _ = fixture_paths(manifest, args.repo_root)
        native = run_native_component(args.repo_root, fixture_root, profile_dir, image_id, audit_dir, manifest,
                                      work_deadline=work_deadline)
        require_work_deadline(work_deadline)
        accounting = require_component_accounting(native)
        require_work_deadline(work_deadline)
        report.update({"result": "passed", "qualified": True, "reason": "native_gold_and_containment_passed",
                       "files": native["audit"]["files"], "costs": native["costs"],
                       "counters": {"downloads": _counter(2, "exact-transfer", True), **accounting["totals"]},
                       "evidence": {"mode": "native", "source": native["evidence_source"],
                                    "run_id": native["run_id"], "receipts": native["audit"]["receipts"],
                                    "preflights": native["preflights"],
                                    "gold": native["gold"], "incumbent": native["incumbent"],
                                    "incumbent_measurement": native["incumbent_measurement"],
                                    "navigation": native["navigation"], "graph_quality": native["graph_quality"],
                                    "containment": native["containment"], "accounting": accounting}})
        return 0
    except AcquisitionError as error:
        report.update({"result": "failed", "reason": error.code})
        report["acquisitions"] = list(error.completed)
        report["acquisition_attempted"] = error.attempted
        report["counters"]["downloads"] = _counter(
            len(error.completed), "confirmed-exact-transfers", True)
        _null_after(report, "acquisition_failed")
        return 1
    except (ManifestError, PrerequisiteRefused, RuntimeGap, HostImportRefused, ContractError, AccountingGap) as error:
        code = getattr(error, "code", "qualification_failed")
        report.update({"result": "prerequisite-refused" if phase in {"before-work", "manifest"} else "failed",
                       "reason": code})
        evidence = getattr(error, "evidence", {})
        report["failure_evidence"] = evidence
        if isinstance(evidence, dict) and evidence.get("counters"):
            report["counters"].update(evidence["counters"])
            report["counter_scope"] = "source_controller_only"
            audit = evidence.get("audit", {})
            report["files"] = audit.get("files", []) if isinstance(audit, dict) else []
        elif phase in {"acquisition", "profile", "native"}:
            _null_after(report, code)
        return 1
    except Exception as error:
        report.update({"result": "failed", "qualified": False, "reason": "bounded_operation_failed",
                       "exception_type": type(error).__name__})
        if phase != "before-work":
            _null_after(report, "bounded_operation_failed")
        return 1
    finally:
        guard.close()
        try:
            if intent_created:
                _write_report(args.report_dir, report)
        finally:
            if work_created:
                shutil.rmtree(args.work_dir)


if __name__ == "__main__":
    raise SystemExit(main())

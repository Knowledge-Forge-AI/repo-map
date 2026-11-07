"""Import-closure owner: qualification imports cannot reach database/publication owners."""

from pathlib import Path
import os
import subprocess
import sys


def test_qualification_import_closure_isolated() -> None:
    root = Path(__file__).resolve().parents[7]
    code = (
        "import importlib.abc, sys\n"
        "sys.path[:0]=[ROOT+'/tools',ROOT+'/src/main/python',ROOT+'/src/test/support/python']\n"
        "blocked={'psycopg','psycopg2','storage','staged_ingestion','publication'}\n"
        "class Guard(importlib.abc.MetaPathFinder):\n"
        " def find_spec(self, fullname, path=None, target=None):\n"
        "  if fullname.split('.')[0] in blocked: raise AssertionError(fullname)\n"
        "sys.meta_path.insert(0,Guard())\n"
        "import ci.rust_pilot_qualification\n"
        "assert not any(name.split('.')[0] in blocked for name in sys.modules)\n"
    ).replace("ROOT", repr(str(root)))
    result = subprocess.run([sys.executable, "-I", "-B", "-c", code],
                            env={"PATH": os.environ.get("PATH", "")},
                            text=True, capture_output=True, check=False, timeout=30)
    assert result.returncode == 0, result.stderr


def test_d12_validator_path_and_runtime_guard_are_real_and_isolated() -> None:
    root = Path(__file__).resolve().parents[7]
    code = (
        "import importlib, sys, tempfile\n"
        "from pathlib import Path\n"
        "root = Path(sys.argv[1])\n"
        "sys.path[:0] = [str(root / 'tools'), str(root / 'src/main/python'), "
        "str(root / 'src/test/support/python')]\n"
        "from ci.qualification_rust_import_guard import HostImportRefused, host_import_guard\n"
        "from ci.rust_pilot_qualification import PrerequisiteRefused, _positive_d12\n"
        "with tempfile.TemporaryDirectory() as raw:\n"
        " state = Path(raw)\n"
        " sealed = state / 'sealed.json'\n"
        " sealed.write_text('{}', encoding='utf-8')\n"
        " try:\n"
        "  _positive_d12(sealed, state)\n"
        " except PrerequisiteRefused as error:\n"
        "  assert error.code == 'd12_positive_evidence_invalid'\n"
        " else:\n"
        "  raise AssertionError('invalid D12 evidence was accepted')\n"
        "assert 'ci.d12_hosted_evidence' in sys.modules\n"
        "assert not any(name.startswith(('psycopg', 'sqlite3', 'tree_sitter', 'common_lore_index.storage')) for name in sys.modules)\n"
        "for name in ('psycopg', 'sqlite3', 'tree_sitter', 'common_lore_index.storage', 'common_lore_index.ops.rust_pilot_publication'):\n"
        " try:\n"
        "  with host_import_guard():\n"
        "   importlib.import_module(name)\n"
        " except HostImportRefused as error:\n"
        "  assert error.code == 'host_import_refused'\n"
        " else:\n"
        "  raise AssertionError('forbidden deferred import was not refused')\n"
    )
    result = subprocess.run(
        [sys.executable, "-I", "-B", "-c", code, str(root)],
        env={"PATH": os.environ.get("PATH", "")},
        text=True, capture_output=True, check=False, timeout=30,
    )
    assert result.returncode == 0, result.stderr


def test_full_qualification_call_path_is_guarded_over_frozen_fixture() -> None:
    """Run the real workflow with only the T1 VerifiedProfile/fake bridge seams.

    The profile and Docker bridge are synthetic test support. Gold, incumbent,
    discovery, canonicalization, navigation, graph-quality, audit and
    containment verdicts remain the production implementations; this is not
    native execution or T2 equivalence.
    """

    root = Path(__file__).resolve().parents[7]
    code = r"""
import hashlib
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

root = Path(sys.argv[1])
sys.path[:0] = [str(root / "tools"), str(root / "src/main/python"),
                str(root / "src/test/support/python")]

from ci.qualification_rust_import_guard import host_import_guard
from ci.qualification_rust_shape import source_digests
from repomap_test_support.rust_pilot_fake_docker import FakeDockerBridge, IMAGE
from repomap_test_support.rust_pilot_fake_tree_sitter.wheels import stand_in_wheels

manifest = json.loads(
    (root / "tools/ci/rust_pilot_qualification_manifest.json").read_text(encoding="utf-8")
)
synthetic = stand_in_wheels()
deferred = {
    "common_lore_index.graph.discovery",
    "common_lore_index.canonicalization.main",
    "common_lore_index.canonicalization.rust_pilot_family",
}

# Fake-Docker support imports closed production leaves for command vectors.
# Retain the class/value objects, then remove only those support modules so
# entering the real guard cannot accept an eager test import.
for name in tuple(sys.modules):
    if name.startswith("repomap_test_support.rust_pilot_fake_"):
        sys.modules.pop(name, None)

assert not deferred.intersection(sys.modules)


with tempfile.TemporaryDirectory(prefix="rust-pilot-qualification-t1-") as raw:
    scratch = Path(raw)
    audit_dir = scratch / "reports" / "audit"
    audit_dir.mkdir(mode=0o700, parents=True)
    bridge = FakeDockerBridge(scratch / "fake-docker")

    def make_boundary(docker_cli, **_kwargs):
        return T1ContainmentBoundary(docker_cli)

    with host_import_guard(root, source_digests(manifest["closure"])):
        from ci.qualification_rust_manifest import fixture_paths, validate_manifest
        from common_lore_index.extractors.rust_pilot.archive_verifier import verify_wheel
        from common_lore_index.extractors.rust_pilot.docker_boundary import DockerBoundary as RealDockerBoundary
        from common_lore_index.extractors.rust_pilot.prepared_profile import (
            ProfileUnavailable, VerifiedProfile, profile_bytes,
        )
        manifest = validate_manifest(root / "tools/ci/rust_pilot_qualification_manifest.json", root)
        fixture_root, _ = fixture_paths(manifest, root)
        source_paths = tuple(path for path in manifest["fixture"]["files"] if not path.startswith("golds/"))
        assert len(source_paths) == 13
        assert manifest["fixture"]["expected_item_claims"] == 420
        verified_pair = tuple(verify_wheel(item.data, item.lock) for item in synthetic)
        arm_profile = VerifiedProfile(
            "aarch64", hashlib.sha256(profile_bytes("aarch64")).hexdigest(),
            profile_bytes("aarch64"), verified_pair,
        )
        amd_profile = VerifiedProfile(
            "x86_64", hashlib.sha256(profile_bytes("x86_64")).hexdigest(),
            profile_bytes("x86_64"), verified_pair,
        )

        from common_lore_index.extractors.rust_pilot.bounded_exec import ExecResult
        from common_lore_index.extractors.rust_pilot.containment import ALL_PROBES
        fixture_digests = {manifest["fixture"]["files"][name]["sha256"] for name in source_paths}
        qualification_events = []
        class T1ContainmentBoundary:
            '''Delegate all normal commands; synthesize only named negative probes.'''

            def __init__(self, docker_cli):
                self._delegate = RealDockerBoundary(docker_cli, runner=bridge.as_runner())
                self._probe_names = {}

            def __getattr__(self, name):
                return getattr(self._delegate, name)

            def run_guest(self, container_id, *, user, tail, stdin, stdout_limit,
                          deadline, workdir=None, hard_end=None):
                if tail[-1].endswith("/helper/parse_helper.py") and stdin:
                    header = json.loads(stdin.split(b"\n", 1)[0])
                    if header["sha256"] in fixture_digests:
                        qualification_events.append(("fixture", header["sha256"]))
                if (len(tail) >= 6 and tail[3] == "-c"
                        and tail[-1] in ALL_PROBES
                        and "containment" in tail[4]):
                    name = tail[-1]
                    qualification_events.append(("containment", name))
                    self._probe_names[container_id] = name
                    if name in {"tcp", "udp", "write_root", "write_prefix",
                                "write_prefix_file", "chmod_sealed", "exec_scratch",
                                "setuid", "docker_socket", "processes"}:
                        stdout = f"REFUSED {name} t1-fake\n".encode("ascii")
                        return ExecResult(
                            returncode=0, stdout=stdout, stdout_overflow=False,
                            stderr_bytes=0, stderr_sha256="0" * 64,
                            stderr_overflow=False, timed_out=False, settled=True,
                            elapsed=0.0, io_failed=False, input_complete=True,
                            callback_failed=False,
                        )
                    if name == "memory":
                        return ExecResult(
                            returncode=137, stdout=b"", stdout_overflow=False,
                            stderr_bytes=0, stderr_sha256="0" * 64,
                            stderr_overflow=False, timed_out=False, settled=True,
                            elapsed=0.0, io_failed=False, input_complete=True,
                            callback_failed=False,
                        )
                    if name == "sleep":
                        return ExecResult(
                            returncode=None, stdout=b"", stdout_overflow=False,
                            stderr_bytes=0, stderr_sha256="0" * 64,
                            stderr_overflow=False, timed_out=True, settled=True,
                            elapsed=0.0, io_failed=False, input_complete=True,
                            callback_failed=False,
                        )
                    if name == "stdout_flood":
                        return ExecResult(
                            returncode=0, stdout=b"", stdout_overflow=True,
                            stderr_bytes=0, stderr_sha256="0" * 64,
                            stderr_overflow=False, timed_out=False, settled=True,
                            elapsed=0.0, io_failed=False, input_complete=True,
                            callback_failed=False,
                        )
                    if name == "stderr_flood":
                        return ExecResult(
                            returncode=0, stdout=b"", stdout_overflow=False,
                            stderr_bytes=0, stderr_sha256="0" * 64,
                            stderr_overflow=True, timed_out=False, settled=True,
                            elapsed=0.0, io_failed=False, input_complete=True,
                            callback_failed=False,
                        )
                    return ExecResult(
                        returncode=1, stdout=b"", stdout_overflow=False,
                        stderr_bytes=0, stderr_sha256="0" * 64,
                        stderr_overflow=False, timed_out=False, settled=True,
                        elapsed=0.0, io_failed=False, input_complete=True,
                        callback_failed=False,
                    )
                return self._delegate.run_guest(
                    container_id, user=user, tail=tail, stdin=stdin,
                    stdout_limit=stdout_limit, deadline=deadline, workdir=workdir,
                    hard_end=hard_end,
                )

            def inspect(self, container_id, *, hard_end=None):
                value = self._delegate.inspect(container_id, hard_end=hard_end)
                if self._probe_names.get(container_id) != "memory":
                    return value
                state = dict(value["State"])
                state["OOMKilled"] = True
                return {**value, "State": state}

        def fake_load(path, *, server_cpu=None):
            name = Path(path).name
            if name == "nonexistent-profile" or name.startswith("corrupt-profile-"):
                raise ProfileUnavailable("profile_missing")
            profile = amd_profile if name == "cross-profile" else arm_profile
            if server_cpu is not None and profile.cpu != server_cpu:
                raise ProfileUnavailable("wrong_platform")
            return profile

        from ci import qualification_rust_runtime as runtime_module
        from ci import qualification_rust_scenarios as scenarios
        from common_lore_index.extractors.rust_pilot import (
            controller as controller_module,
            docker_boundary as docker_boundary_module,
            prepared_profile,
        )

        real_compare = runtime_module.compare_gold_claims
        def compare_with_public_failure_detail(controller, summary, fixture_root, source_paths, manifest):
            try:
                result = real_compare(controller, summary, fixture_root, source_paths, manifest)
            except runtime_module.RuntimeGap as error:
                print(json.dumps({"reason": error.code,
                                  "mismatches": error.evidence.get("mismatches", [])},
                                 sort_keys=True), file=sys.stderr)
                raise
            assert result["comparison_complete"] is True
            assert len(result["comparisons"]) == 13
            missing = next(row for row in result["comparisons"]
                           if row["fixture"] == "q04_missing_brace.rs")
            assert missing["actual"]["items"][2]["end_byte"] == 252
            assert missing["actual_document_sha256"] == (
                "d738feee3215c67b3b928572ef259768059865186f6e973ea851169b2b56f92e")
            real_document = runtime_module._document
            targets = {"q01_all_items.rs", "unsupported_forms.rs"}
            def altered_document(relative, *args):
                document = real_document(relative, *args)
                if relative in targets:
                    document["line_count"] += 1
                return document
            with patch.object(runtime_module, "_document", new=altered_document):
                try:
                    real_compare(controller, summary, fixture_root, source_paths, manifest)
                except runtime_module.RuntimeGap as error:
                    assert error.code == "gold_mismatch"
                    assert error.evidence["comparison_complete"] is True
                    assert len(error.evidence["comparisons"]) == 13
                    assert {row["fixture"] for row in error.evidence["mismatches"]} == targets
                else:
                    raise AssertionError("two comparison mismatches were admitted")
            return result

        with (
            patch.object(runtime_module, "compare_gold_claims", new=compare_with_public_failure_detail),
            patch.object(controller_module, "_new_boundary", new=make_boundary),
            patch.object(controller_module, "load_profile", new=fake_load),
            patch.object(prepared_profile, "load_profile", new=fake_load),
            patch.object(scenarios, "DockerBoundary", new=make_boundary),
            patch.object(scenarios, "load_profile", new=fake_load),
            patch.object(docker_boundary_module, "DockerBoundary", new=make_boundary),
            patch.object(
                runtime_module.shutil, "which",
                new=lambda value: "/usr/bin/docker" if value == "docker" else None,
            ),
        ):
            result = runtime_module.run_native_component(
                root, fixture_root, scratch / "profile", IMAGE, audit_dir, manifest,
                platform="linux/arm64", cross_cpu_profile=scratch / "cross-profile",
            )
    from repomap_test_support.rust_pilot_qualification_report import assert_t1_amd_report_fits
    print("T1_AMD_REPORT_BYTES=" + str(assert_t1_amd_report_fits(root, scratch, result)))

assert {name for kind, name in qualification_events if kind == "containment"} == set(ALL_PROBES)
assert max(i for i, (kind, _) in enumerate(qualification_events) if kind == "containment") < min(
    i for i, (kind, _) in enumerate(qualification_events) if kind == "fixture")
assert len(result["gold"]["files"]) == len(source_paths)
assert result["gold"]["item_claims"] == 420
assert result["gold"]["source"] == "native_controller_admissions"
assert result["incumbent"]["source"] == "actual_incumbent_report"
assert result["navigation"]["task_count"] == 5
assert all(isinstance(task["candidate"], bool) and isinstance(task["incumbent"], bool)
           for task in result["navigation"]["tasks"])
assert result["graph_quality"]["legacy_invariance"]["byte_identical"] is True
assert all(item.get("passed") is True for item in result["preflights"].values())
assert result["containment"]["role"] == "containment"
assert result["containment"]["outcomes"]
assert all(item["absence_proven"] is True for item in result["containment"]["outcomes"])

audit = result["audit"]
rows = audit["files"]
assert len(rows) == len(source_paths) + 1
assert sum(row.get("invocation_role") == "probe" for row in rows) == 1
assert sum(row.get("invocation_role") == "source" for row in rows) == len(source_paths) - 1
refusals = [row for row in rows if "invocation_role" not in row]
assert len(refusals) == 1 and refusals[0]["outcome"] == "input_not_utf8"
assert audit["residue"]["owned_containers_remaining"] == 0
for name in ("builds", "pulls", "images", "volumes"):
    assert audit["counters"][name]["value"] == 0
    assert audit["counters"][name]["basis"] == "journal-derived"
    assert audit["counters"][name]["cross_checked"] is True

assert deferred.issubset(sys.modules)
assert not any(name.startswith(("psycopg", "psycopg2", "sqlite3", "sqlalchemy"))
               for name in sys.modules)
"""
    result = subprocess.run(
        [sys.executable, "-I", "-B", "-c", code, str(root)],
        env={"PATH": os.environ.get("PATH", "")},
        text=True, capture_output=True, check=False, timeout=120,
    )
    assert result.returncode == 0, result.stderr
    size_line = next(line for line in result.stdout.splitlines() if line.startswith("T1_AMD_REPORT_BYTES="))
    assert 748_847 < int(size_line.split("=", 1)[1]) <= 1_048_576
    print(size_line)


def test_missing_live_call_source_pin_is_refused_by_real_guard() -> None:
    root = Path(__file__).resolve().parents[7]
    code = r"""
import importlib
import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
sys.path[:0] = [str(root / "tools"), str(root / "src/main/python"),
                str(root / "src/test/support/python")]
from ci.qualification_rust_import_guard import HostImportRefused, host_import_guard
from ci.qualification_rust_shape import source_digests

manifest = json.loads(
    (root / "tools/ci/rust_pilot_qualification_manifest.json").read_text(encoding="utf-8")
)
target_path = "src/main/python/common_lore_index/graph/discovery.py"
target_module = "common_lore_index.graph.discovery"
closure = manifest["closure"]
rows = closure["python_digests"]
assert any(row["path"] == target_path for row in rows)
closure["python_digests"] = [row for row in rows if row["path"] != target_path]
try:
    with host_import_guard(root, source_digests(closure)):
        importlib.import_module(target_module)
except HostImportRefused as error:
    assert error.code == "host_import_refused"
else:
    raise AssertionError("missing live call-source pin was accepted")
"""
    result = subprocess.run(
        [sys.executable, "-I", "-B", "-c", code, str(root)],
        env={"PATH": os.environ.get("PATH", "")},
        text=True, capture_output=True, check=False, timeout=30,
    )
    assert result.returncode == 0, result.stderr

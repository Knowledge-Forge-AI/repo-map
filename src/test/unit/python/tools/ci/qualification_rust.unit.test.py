"""Executable owners for the frozen Rust qualification boundary."""

from __future__ import annotations

import hashlib
from dataclasses import replace
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest

import ci.rust_pilot_qualification as qualification
from ci.qualification_rust_manifest import (
    EXPECTED_FILES,
    EXPECTED_SOURCES,
    GOLD_KEYS,
    ManifestError,
    _check_closure,
    validate_manifest,
)
from ci.qualification_rust_runtime import RuntimeGap, _audit, _graph_quality, _legacy_measure, _navigation
from common_lore_index.canonicalization.rust_pilot_family import canonicalize_rust_pilot
from repomap_test_support.rust_pilot_semantic_fixtures import live_pilot

ROOT = Path(__file__).resolve().parents[6]
MANIFEST = ROOT / "tools/ci/rust_pilot_qualification_manifest.json"
INVALID_GOLD = ROOT / "src/test/fixtures/rust_pilot/golds/q06_invalid_utf8.gold.json"
INVALID_SOURCE = ROOT / "src/test/fixtures/rust_pilot/q06_invalid_utf8.rs"


def _manifest() -> dict[str, Any]:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def _write_manifest(tmp_path: Path, document: dict[str, Any]) -> Path:
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(document, sort_keys=True), encoding="utf-8")
    return path


def _main_args(tmp_path: Path) -> list[str]:
    state = tmp_path / "d12"
    state.mkdir()
    sealed = state / "sealed.json"
    sealed.write_text("{}", encoding="utf-8")
    return [
        "amd64", "--repo-root", str(ROOT), "--d12-state-dir", str(state),
        "--d12-sealed-json", str(sealed), "--manifest", str(MANIFEST),
        "--work-dir", str(tmp_path / "work"), "--report-dir", str(tmp_path / "report"),
    ]


def test_invalid_utf8_gold_retains_actual_document_shape_and_seven_lines() -> None:
    data = INVALID_SOURCE.read_bytes()
    gold = json.loads(INVALID_GOLD.read_text(encoding="utf-8"))
    assert set(gold) == GOLD_KEYS
    assert gold["outcome"] == "input_not_utf8"
    assert gold["items"] == [] and gold["completeness"] == "none"
    assert gold["line_count"] == 7
    assert gold["input_bytes"] == len(data)
    assert gold["input_sha256"] == hashlib.sha256(data).hexdigest()


def test_actual_frozen_manifest_validates_against_current_checkout() -> None:
    document = validate_manifest(MANIFEST, ROOT)
    assert set(document["fixture"]["files"]) == set(EXPECTED_FILES)


def test_manifest_rejects_top_level_extra_field(tmp_path: Path) -> None:
    document = _manifest()
    document["unexpected"] = "must remain closed"
    with pytest.raises(ManifestError):
        validate_manifest(_write_manifest(tmp_path, document), ROOT)


def test_manifest_rejects_nested_extra_field(tmp_path: Path) -> None:
    document = _manifest()
    document["sdk"]["unexpected"] = "must remain closed"
    with pytest.raises(ManifestError):
        validate_manifest(_write_manifest(tmp_path, document), ROOT)


def test_manifest_rejects_corrupt_helper_closure(tmp_path: Path) -> None:
    document = _manifest()
    document["closure"]["helper_closure_sha256"] = "0" * 64
    with pytest.raises(ManifestError):
        validate_manifest(_write_manifest(tmp_path, document), ROOT)


def test_manifest_rejects_profile_digest_change(tmp_path: Path) -> None:
    document = _manifest()
    document["closure"]["profile_digests"]["amd64"] = "0" * 64
    with pytest.raises(ManifestError):
        validate_manifest(_write_manifest(tmp_path, document), ROOT)


def test_manifest_rejects_sdk_profile_binding_change(tmp_path: Path) -> None:
    document = _manifest()
    document["sdk"]["profile_sha256"] = "f" * 64
    with pytest.raises(ManifestError):
        validate_manifest(_write_manifest(tmp_path, document), ROOT)


def test_manifest_rejects_closure_path_denial(tmp_path: Path) -> None:
    document = _manifest()
    document["closure"]["python_paths"].append("tools/ci/not-in-closure.py")
    document["closure"]["python_digests"].append({"path": "tools/ci/not-in-closure.py", "sha256": "0" * 64})
    with pytest.raises(ManifestError):
        validate_manifest(_write_manifest(tmp_path, document), ROOT)


@pytest.mark.parametrize("mutation", ["duplicate", "extra", "mapping", "nontext"])
def test_manifest_rejects_invalid_source_digest_records(tmp_path: Path, mutation: str) -> None:
    document = _manifest()
    rows = document["closure"]["python_digests"]
    if mutation == "duplicate":
        rows.append(dict(rows[0]))
    elif mutation == "extra":
        rows[0]["unexpected"] = "closed"
    elif mutation == "mapping":
        document["closure"]["python_digests"] = {row["path"]: row["sha256"] for row in rows}
    else:
        rows[0]["sha256"] = 123
    with pytest.raises(ManifestError):
        validate_manifest(_write_manifest(tmp_path, document), ROOT)


def test_manifest_rejects_boolean_budget_counter(tmp_path: Path) -> None:
    document = _manifest()
    document["budget"]["retries"] = True
    with pytest.raises(ManifestError):
        validate_manifest(_write_manifest(tmp_path, document), ROOT)


def test_manifest_rejects_boolean_wheel_size(tmp_path: Path) -> None:
    document = _manifest()
    document["wheels"][0]["bytes"] = True
    with pytest.raises(ManifestError):
        validate_manifest(_write_manifest(tmp_path, document), ROOT)


def test_manifest_rejects_frozen_fixture_digest_change(tmp_path: Path) -> None:
    document = _manifest()
    document["fixture"]["files"][EXPECTED_SOURCES[0]]["sha256"] = "0" * 64
    with pytest.raises(ManifestError):
        validate_manifest(_write_manifest(tmp_path, document), ROOT)


def test_manifest_navigation_freezes_five_distinct_rust_categories() -> None:
    tasks = _manifest()["navigation"]["tasks"]
    assert len(tasks) == 5
    assert {task["namespace"] for task in tasks} == {
        "rust.function", "rust.trait", "rust.impl", "rust.macro", "rust.module",
    }
    assert len({task["incumbent_key"] for task in tasks}) == 5


def test_actual_component_closure_is_initialization_resolved_and_digest_bound() -> None:
    document = _manifest()
    closure = document["closure"]
    _check_closure(ROOT, closure)
    guest_init = "src/main/python/common_lore_index/extractors/rust_pilot/guest/__init__.py"
    from ci.qualification_rust_closure import required_sources
    from ci.qualification_rust_manifest import GUEST_FILES

    assert set(closure["python_paths"]) == (
        required_sources(ROOT) | set(GUEST_FILES) | {guest_init}
    )


def test_positive_t1_audit_uses_live_controller_cost_and_probe_receipts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    with live_pilot(tmp_path, monkeypatch) as live:
        source = (live.root / "src/lib.rs").read_bytes()
        snapshot, audited = _audit(
            live.controller, ("src/lib.rs",),
            {"files": {"src/lib.rs": {"sha256": hashlib.sha256(source).hexdigest()}}},
        )
        cost = audited["costs"]["src/lib.rs"]
        assert snapshot["residue"]["owned_containers_remaining"] == 0
        assert cost["construction_includes_readback"] is True
        assert cost["memory_peak_basis"] == "guest_reported"
        assert any(row.get("invocation_role") == "probe" for row in snapshot["files"])
        assert audited["counters"]["containers"]["basis"] == "journal-derived"
        assert audited["counters"]["parses"]["value"] == 2
        assert audited["counters"]["parses"]["scope"] == "fixed_parse_exec_commands_attempted"


def test_actual_t1_graph_delta_preserves_legacy_rows_and_rejects_mutation(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    with live_pilot(tmp_path, monkeypatch) as live:
        tasks = [{"fixture": "src/lib.rs", "name": name, "namespace": "rust." + kind,
                  "incumbent_key": kind} for kind, name in (
                     ("function", "f"), ("module", "nested"), ("trait", "absent"),
                     ("impl", "absent"), ("macro", "absent"))]
        measured = _legacy_measure(live.root, ("src/lib.rs",), tasks)
        witnessed = canonicalize_rust_pilot(live.controller, measured["_observations"],
                                             repository_scope="rust-pilot-qualified")
        graph = witnessed.result.graph
        quality = _graph_quality(graph, measured)
        assert quality["legacy_invariance"]["byte_identical"] is True
        assert quality["witnessed_candidate"]["rust_nodes"] == 3
        navigation = _navigation(graph, ("src/lib.rs",), tasks, measured)
        assert [row["candidate"] for row in navigation["tasks"]] == [True, True, False, False, False]
        assert all(row["incumbent"] is False for row in navigation["tasks"])
        first, *remaining = graph.nodes
        changed = replace(graph, nodes=(replace(first, display_name="changed legacy row"), *remaining))
        with pytest.raises(RuntimeGap, match="legacy_rows_changed"):
            _graph_quality(changed, measured)


def test_d12_refusal_stops_before_download_or_native_work(
    tmp_path: Path,
) -> None:
    args = _main_args(tmp_path)
    code = (
        "from pathlib import Path\n"
        "import sys\n"
        "root = Path(sys.argv[1])\n"
        "sys.path[:0] = [str(root / 'tools'), str(root / 'src/main/python'), "
        "str(root / 'src/test/support/python')]\n"
        "import ci.qualification_rust_acquisition as acquisition\n"
        "import ci.rust_pilot_qualification as qualification\n"
        "def denied(*_args, **_kwargs): raise AssertionError('native/download reached')\n"
        "acquisition.acquire_exact_amd_wheels = denied\n"
        "qualification.run_native_component = denied\n"
        "raise SystemExit(qualification.main(sys.argv[2:]))\n"
    )
    result = subprocess.run(
        [sys.executable, "-I", "-B", "-c", code, str(ROOT), *args],
        env={"PATH": os.environ.get("PATH", "")},
        text=True, capture_output=True, check=False, timeout=30,
    )
    assert result.returncode == 1, result.stderr
    report = json.loads((tmp_path / "report/rust-pilot-qualification.json").read_text())
    assert report["result"] == "prerequisite-refused"
    assert report["reason"] == "d12_positive_evidence_invalid"
    assert report["counters"]["downloads"]["value"] == 0
    assert (tmp_path / "report/rust-pilot-attempt-intent.json").read_bytes()
    assert "native/download reached" not in result.stderr


def test_duplicate_intent_refusal_preserves_existing_report(
    tmp_path: Path,
) -> None:
    report_dir = tmp_path / "report"
    qualification._intent(report_dir)
    original = {"schema": qualification.REPORT_SCHEMA, "result": "failed", "reason": "prior"}
    qualification._write_report(report_dir, original)
    before = (report_dir / "rust-pilot-qualification.json").read_bytes()
    intent_before = (report_dir / "rust-pilot-attempt-intent.json").read_bytes()
    args = _main_args(tmp_path)
    args[args.index("--report-dir") + 1] = str(report_dir)
    assert qualification.main(args) == 1
    assert (report_dir / "rust-pilot-qualification.json").read_bytes() == before
    assert (report_dir / "rust-pilot-attempt-intent.json").read_bytes() == intent_before


def test_partial_acquisition_failure_reports_completed_transfer_count(
    tmp_path: Path,
) -> None:
    completed = ({"name": "first.whl", "bytes": 3, "sha256": "a" * 64, "attempts": 1},)
    args = _main_args(tmp_path)
    code = (
        "from pathlib import Path\n"
        "import json, sys\n"
        "root = Path(sys.argv[1])\n"
        "sys.path[:0] = [str(root / 'tools'), str(root / 'src/main/python'), "
        "str(root / 'src/test/support/python')]\n"
        "import ci.qualification_rust_acquisition as acquisition\n"
        "import ci.rust_pilot_qualification as qualification\n"
        "qualification._positive_d12 = lambda *_args: ('a' * 40, 'b' * 40, 'image', 'recipe')\n"
        "qualification.validate_manifest = lambda path, root: json.loads(path.read_bytes())\n"
        "qualification._bind_candidate = lambda *_args: None\n"
        "qualification._verify_sdk = lambda *_args, **_kwargs: None\n"
        "def native_denied(*_args, **_kwargs): raise AssertionError('native reached')\n"
        "qualification.run_native_component = native_denied\n"
        "completed = " + repr(completed) + "\n"
        "def fail(*_args, **_kwargs): raise acquisition.AcquisitionError('wheel_fetch_failed', completed=completed, attempted=True)\n"
        "acquisition.acquire_exact_amd_wheels = fail\n"
        "raise SystemExit(qualification.main(sys.argv[2:]))\n"
    )
    result = subprocess.run(
        [sys.executable, "-I", "-B", "-c", code, str(ROOT), *args],
        env={"PATH": os.environ.get("PATH", "")},
        text=True, capture_output=True, check=False, timeout=30,
    )
    assert result.returncode == 1, result.stderr
    report = json.loads((tmp_path / "report/rust-pilot-qualification.json").read_text())
    assert report["reason"] == "wheel_fetch_failed"
    assert report["acquisitions"] == list(completed)
    assert report["acquisition_attempted"] is True
    assert report["counters"]["downloads"] == {
        "value": 1, "basis": "confirmed-exact-transfers", "cross_checked": True,
    }
    assert report["counters"]["containers"]["value"] is None
    assert "native reached" not in result.stderr


def test_missing_client_contract_is_a_prerequisite_refusal_before_acquisition(tmp_path: Path) -> None:
    args = _main_args(tmp_path)
    code = (
        "from pathlib import Path\nimport sys\n"
        "root=Path(sys.argv[1]);sys.path[:0]=[str(root/'tools'),str(root/'src/main/python'),str(root/'src/test/support/python')]\n"
        "import ci.rust_pilot_qualification as q\n"
        "from common_lore_index.extractors.contracts.vocabulary import ContractError\n"
        "q._positive_d12=lambda *_:('1'*40,'2'*40,'sha256:'+'a'*64,'b'*64)\n"
        "q._bind_candidate=lambda *_:None\n"
        "def unavailable(*_, **_kwargs): raise ContractError('client_unavailable')\n"
        "q._verify_sdk=unavailable\n"
        "raise SystemExit(q.main(sys.argv[2:]))\n"
    )
    result = subprocess.run([sys.executable, "-I", "-B", "-c", code, str(ROOT), *args],
                            capture_output=True, check=False, timeout=30,
                            env=os.environ | {"GIT_OPTIONAL_LOCKS": "0"})
    assert result.returncode == 1, result.stderr.decode("utf-8", "replace")[-1000:]
    report = json.loads((tmp_path / "report/rust-pilot-qualification.json").read_bytes())
    assert (report["result"], report["reason"], report["qualified"]) == (
        "prerequisite-refused", "client_unavailable", False)
    assert report["counters"]["downloads"]["value"] == 0
    assert not (tmp_path / "work").exists()



def test_failed_containment_prevents_any_target_fixture_delivery(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from types import SimpleNamespace
    from ci import qualification_rust_runtime as runtime_module
    from ci import qualification_rust_scenarios as scenarios
    from common_lore_index.extractors.rust_pilot import controller, prepared_profile

    deliveries: list[str] = []
    class DeliverySentinel:
        def __init__(self, **_kwargs: object) -> None:
            pass
        def process(self, *_args: object) -> None:
            deliveries.append("target")
            raise AssertionError("target delivered before containment")
        def close(self) -> None:
            pass

    failed = {"containment": {"outcomes": [{"name": "memory", "absence_proven": False}]}}
    def refuse_containment(*_args: object, **_kwargs: object) -> None:
        raise RuntimeGap("containment_not_proven", failed)

    monkeypatch.setattr(prepared_profile, "load_profile", lambda *_args, **_kwargs:
                        SimpleNamespace(profile_sha256="c" * 64))
    monkeypatch.setattr(runtime_module.shutil, "which", lambda _value: "/usr/bin/docker")
    monkeypatch.setattr(scenarios, "preflight_scenarios", lambda *_args, **_kwargs:
                        {"prerequisite": {"passed": True}})
    monkeypatch.setattr(runtime_module, "_containment", refuse_containment)
    monkeypatch.setattr(controller, "RustPilotController", DeliverySentinel)
    manifest = {"closure": {"profile_digests": {"arm64": "c" * 64}},
                "fixture": {"files": {"toy.rs": {"sha256": "a" * 64}}}}
    with pytest.raises(RuntimeGap, match="containment_not_proven") as raised:
        runtime_module._run_native_component(
            ROOT, tmp_path, tmp_path / "profile", "image", tmp_path, manifest,
            platform="linux/arm64", cross_cpu_profile=None, work_deadline=time.monotonic() + 1200.0)
    assert raised.value.evidence == failed
    assert deliveries == []

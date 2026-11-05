"""Pure fake-boundary owners for cleanup evidence and Q10 timing."""

from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from ci import qualification_rust_scenarios as scenarios
from ci.qualification_rust_cleanup import close_native_controller
from ci.qualification_rust_runtime import RuntimeGap
from common_lore_index.extractors.contracts.vocabulary import ContractError


class _Sources:
    def text(self, name: str) -> str:
        return name


class _FakeBoundary:
    def limit_work_deadline(self, _deadline: float | None) -> None:
        pass

    def __init__(self, *, server_arch: str = "amd64") -> None:
        self.server_arch = server_arch
        self.events: list[str] = []
        stderr = b"setup_refused payload_digest_mismatch\n"
        self.setup_result = SimpleNamespace(
            returncode=2,
            stdout=b"",
            stderr_bytes=len(stderr),
            stderr_sha256=hashlib.sha256(stderr).hexdigest(),
            settled=True,
            io_failed=False,
            input_complete=True,
            callback_failed=False,
        )

    def server(self) -> SimpleNamespace:
        self.events.append("server")
        return SimpleNamespace(os="linux", arch=self.server_arch)

    def check_image(self, *_args: object, **_kwargs: object) -> None:
        self.events.append("check_image")

    def snapshot(self, _run_id: str) -> dict[str, object]:
        self.events.append("snapshot")
        return {"run_id": "run-id"}

    def create(self, *, owned: list[str] | None = None, **_kwargs: object) -> str:
        self.events.append("create")
        if owned is not None:
            owned.append("container-id")
        return "container-id"

    def start(self, _container_id: str, **_kwargs: object) -> None:
        self.events.append("start")

    def inspect(self, _container_id: str, **_kwargs: object) -> dict[str, object]:
        self.events.append("inspect")
        return {}

    def run_guest(self, *_args: object, **_kwargs: object) -> SimpleNamespace:
        self.events.append("setup")
        return self.setup_result

    def begin_settlement(self, _container_id: str) -> None:
        self.events.append("begin_settlement")

    def settle(self, _container_id: str) -> bool:
        self.events.append("settle")
        return True


def _patch_q10(
    monkeypatch: pytest.MonkeyPatch,
    boundary: _FakeBoundary,
    clock_values: list[float],
    captured: dict[str, Any],
) -> list[float]:
    profile = SimpleNamespace(profile_sha256="p" * 64)
    material = SimpleNamespace(setup_stream=b"payload", sources=_Sources())
    seen: list[float] = []

    def now() -> float:
        value = clock_values[len(seen)]
        seen.append(value)
        return value

    def audit(
        _run_id: str, rows: tuple[dict[str, Any], ...], _receipts: object,
        _residue: object, _boundary: object,
    ) -> dict[str, Any]:
        captured["row"] = rows[0]
        return {"receipts": [{"state": "refused"}], "counters": {
            "containers": {"value": 1}, "parses": {"value": 0},
            "commands": {"value": 3},
        }}

    monkeypatch.setattr(scenarios, "DockerBoundary", lambda _cli: boundary)
    monkeypatch.setattr(scenarios, "run_identity", lambda _nonce: "run-id")
    monkeypatch.setattr(scenarios.secrets, "token_bytes", lambda size: b"x" * size)
    monkeypatch.setattr(scenarios.time, "monotonic", now)
    monkeypatch.setattr(scenarios, "load_profile", lambda *_args, **_kwargs: profile)
    monkeypatch.setattr(scenarios, "load_guest_sources", lambda: material.sources)
    monkeypatch.setattr(scenarios.construction, "build_material", lambda *_args: material)
    monkeypatch.setattr(scenarios.construction, "load_notices", lambda: ())
    monkeypatch.setattr(scenarios, "check_container_config", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(scenarios.controller_audit, "observe_residue",
                        lambda *_args: ({"observed": True}, True))
    monkeypatch.setattr(scenarios.controller_audit, "audit_snapshot", audit)
    monkeypatch.setattr(scenarios.receipts, "refusal_receipt",
                        lambda **kwargs: {"state": "refused", **kwargs})
    return seen


class _FailingClose:
    def __init__(self, error: Exception | None = None) -> None:
        self.closed = False
        self.error = error or RuntimeError("private cleanup detail")

    def close(self) -> None:
        self.closed = True
        raise self.error

    def audit_snapshot(self) -> dict[str, object]:
        return {"run_id": "run-id", "counters": {"commands": 4}}


def test_cleanup_failure_preserves_runtime_gap_evidence() -> None:
    controller = _FailingClose(ContractError("cleanup_incomplete"))
    original = RuntimeGap("gold_mismatch", {
        "audit": {"run_id": "run-id"},
        "preflights": {"Q10": {"passed": True}},
        "costs": {"src/lib.rs": {"construction_ms": 4}},
        "counters": {"containers": {"value": 1}},
    })
    with pytest.raises(RuntimeGap) as raised:
        close_native_controller(controller, original)
    evidence = raised.value.evidence
    assert controller.closed
    assert raised.value.code == "gold_mismatch"
    assert evidence["audit"] == {"run_id": "run-id"}
    assert evidence["preflights"]["Q10"]["passed"] is True
    assert evidence["costs"]["src/lib.rs"]["construction_ms"] == 4
    assert evidence["counters"]["containers"]["value"] == 1
    assert evidence["cleanup_audit"]["counters"]["commands"] == 4
    assert evidence["cleanup_incomplete"] is True
    assert evidence["qualified"] is False
    assert evidence["cleanup_error"] == "cleanup_incomplete"


def test_cleanup_failure_without_original_gap_is_unqualified() -> None:
    with pytest.raises(RuntimeGap) as raised:
        close_native_controller(_FailingClose(), None)
    assert raised.value.code == "cleanup_incomplete"
    assert raised.value.evidence["qualified"] is False
    assert raised.value.evidence["cleanup_incomplete"] is True
    assert raised.value.evidence["cleanup_error"] == "cleanup_exception"


def test_q10_timing_stops_before_settlement_and_retains_refusal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    boundary = _FakeBoundary()
    captured: dict[str, Any] = {}
    seen = _patch_q10(monkeypatch, boundary, [10.0, 11.0, 13.25, 20.0, 21.5], captured)
    result = scenarios._tampered_setup(
        docker_cli="docker", image_id="image", profile_dir=tmp_path / "profile",
        audit_dir=tmp_path, platform="linux/amd64",
    )
    cost = captured["row"]["cost"]
    assert result["passed"] is True
    assert cost["construction_ms"] == 3250
    assert cost["settlement_ms"] == 1500
    assert seen == [10.0, 11.0, 13.25, 20.0, 21.5]
    assert boundary.events.index("setup") < boundary.events.index("begin_settlement")


def test_q10_precreate_failure_reports_unknown_construction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    boundary = _FakeBoundary(server_arch="arm64")
    captured: dict[str, Any] = {}
    seen = _patch_q10(monkeypatch, boundary, [40.0, 41.0], captured)
    result = scenarios._tampered_setup(
        docker_cli="docker", image_id="image", profile_dir=tmp_path / "profile",
        audit_dir=tmp_path, platform="linux/amd64",
    )
    assert result["passed"] is False
    assert result["cost"]["construction_ms"] is None
    assert result["cost"]["settlement_ms"] == 1000
    assert seen == [40.0, 41.0]
    assert boundary.events == ["server"]


@pytest.mark.parametrize("primary_kind", ["contract", "unexpected"])
def test_non_runtime_primary_survives_cleanup_failure(primary_kind: str) -> None:
    from ci.qualification_rust_cleanup import native_failure
    primary = ContractError("runtime_mismatch") if primary_kind == "contract" else ValueError("synthetic private detail")
    class Broken:
        def close(self) -> None:
            raise ContractError("cleanup_incomplete")
        def audit_snapshot(self) -> object:
            return {"files": [], "counters": {}}
    controller = Broken()
    gap = native_failure(controller, primary, None, {}, {})
    with pytest.raises(RuntimeGap) as refused:
        close_native_controller(controller, gap)
    assert refused.value.code == ("runtime_mismatch" if primary_kind == "contract" else "bounded_operation_failed")
    assert refused.value.evidence["cleanup_incomplete"] is True
    assert "synthetic private detail" not in str(refused.value.evidence)


def test_expired_command_writes_refusal_without_work_or_prerequisite_actions(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import json
    from ci import rust_pilot_qualification as qualification
    monkeypatch.setattr(qualification, "command_work_deadline", lambda: 0.0)
    def forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("prerequisite work must not start")
    monkeypatch.setattr(qualification, "_positive_d12", forbidden)
    args = ["amd64"]
    for key, value in (("repo-root", tmp_path / "repo"), ("d12-state-dir", tmp_path / "d12"),
                       ("d12-sealed-json", tmp_path / "sealed.json"), ("manifest", tmp_path / "manifest.json"),
                       ("work-dir", tmp_path / "work"), ("report-dir", tmp_path / "report")):
        args += ["--" + key, str(value)]
    assert qualification.main(args) == 1
    report = json.loads((tmp_path / "report/rust-pilot-qualification.json").read_bytes())
    assert report["reason"] == "internal_deadline_exceeded" and report["qualified"] is False, report
    assert not (tmp_path / "work").exists()


@pytest.mark.parametrize("expire_at", ["version", "image"])
def test_sdk_work_uses_the_shared_cutoff_between_client_calls(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, expire_at: str) -> None:
    import json
    from ci import rust_pilot_qualification as qualification
    from common_lore_index.extractors.rust_pilot import docker_boundary
    from common_lore_index.extractors.rust_pilot.bounded_exec import ExecResult
    clock = [0.0]
    calls: list[str] = []
    image_id = "sha256:" + "a" * 64
    def runner(*args: Any, **_kwargs: Any) -> ExecResult:
        verb = args[0][1]
        calls.append(verb)
        value = ({"Os": "linux", "Arch": "amd64"} if verb == "version" else
                 [{"Id": image_id, "Os": "linux", "Architecture": "amd64", "Config": {}}])
        if verb == expire_at:
            clock[0] = 10.0
        return ExecResult(0, json.dumps(value).encode(), False, 0, "0" * 64, False, False, True, 0.0)
    boundary = docker_boundary.DockerBoundary("/usr/bin/docker", runner=runner, clock=lambda: clock[0])
    monkeypatch.setattr(docker_boundary, "DockerBoundary", lambda _cli: boundary)
    monkeypatch.setattr(qualification.shutil, "which", lambda _name: "/usr/bin/docker")
    manifest = {"sdk": {"recipe_sha256": "recipe", "recipe_files": {}}}
    with pytest.raises(ContractError, match="internal_deadline_exceeded"):
        qualification._verify_sdk(tmp_path, manifest, image_id, "recipe", work_deadline=10.0)
    assert calls == (["version"] if expire_at == "version" else ["version", "image"])


def test_accounting_crossing_work_cutoff_cannot_write_qualified_success(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Synthetic main control flow; real guard/accounting/native proofs are separate."""
    import json
    from contextlib import nullcontext
    from ci import qualification_rust_acquisition as acquisition, qualification_rust_shape as shape
    from ci import rust_pilot_qualification as qualification
    from common_lore_index.extractors.rust_pilot import prepared_profile
    clock = [0.0]
    monkeypatch.setattr(shape.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(qualification, "command_work_deadline", lambda: 10.0)
    monkeypatch.setattr(qualification, "host_import_guard", lambda *_a, **_k: nullcontext())
    monkeypatch.setattr(qualification, "_positive_d12", lambda *_a: ("a" * 40, "b" * 40, "image", "recipe"))
    monkeypatch.setattr(qualification, "validate_manifest", lambda *_a: {"closure": {}, "sdk": {"profile_sha256": "profile"}})
    monkeypatch.setattr(qualification, "source_digests", lambda _closure: {})
    monkeypatch.setattr(qualification, "_bind_candidate", lambda *_a, **_k: None)
    monkeypatch.setattr(qualification, "_verify_sdk", lambda *_a, **_k: None)
    monkeypatch.setattr(acquisition, "acquire_exact_amd_wheels", lambda *_a, **_k: ({"name": "one"}, {"name": "two"}))
    monkeypatch.setattr(prepared_profile, "prepare_profile", lambda *_a: "profile")
    monkeypatch.setattr(qualification, "fixture_paths", lambda *_a: (tmp_path, {}))
    native: dict[str, Any] = {"audit": {"files": [], "receipts": []}, "costs": {}, "evidence_source": "synthetic",
                              "run_id": "synthetic", "preflights": {}, "gold": {}, "incumbent": {},
                              "incumbent_measurement": {}, "navigation": {}, "graph_quality": {}, "containment": {}}
    monkeypatch.setattr(qualification, "run_native_component", lambda *_a, **_k: native)
    def aggregate(_native: object) -> dict[str, Any]:
        clock[0] = 10.0
        return {"totals": {}}
    monkeypatch.setattr(qualification, "require_component_accounting", aggregate)
    args = ["amd64"]
    for key, value in (("repo-root", tmp_path / "repo"), ("d12-state-dir", tmp_path / "d12"),
                       ("d12-sealed-json", tmp_path / "sealed.json"), ("manifest", tmp_path / "manifest.json"),
                       ("work-dir", tmp_path / "work"), ("report-dir", tmp_path / "report")):
        args += ["--" + key, str(value)]
    assert qualification.main(args) == 1
    report = json.loads((tmp_path / "report/rust-pilot-qualification.json").read_bytes())
    assert report["reason"] == "internal_deadline_exceeded" and report["qualified"] is False, report
    assert not (tmp_path / "work").exists()

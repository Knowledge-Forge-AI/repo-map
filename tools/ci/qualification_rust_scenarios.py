"""Real pre-import refusals within one native qualification command."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import hashlib
from pathlib import Path
import secrets
import tempfile
import time
from typing import Any

from ci.qualification_rust_accounting import AccountingGap, refusal_accounting
from ci.qualification_rust_accounting import AuditGap as AuditGap, audit_snapshot as audit_snapshot
from ci.qualification_rust_shape import require_work_deadline
from common_lore_index.extractors.contracts.vocabulary import ContractError
from common_lore_index.extractors.rust_pilot import construction, controller_audit, receipts
from common_lore_index.extractors.rust_pilot.component_lock import CPU_BY_DOCKER_ARCH
from common_lore_index.extractors.rust_pilot.controller import RustPilotController, run_identity
from common_lore_index.extractors.rust_pilot.docker_boundary import (
    SETUP_USER, DockerBoundary, check_container_config,
)
from common_lore_index.extractors.rust_pilot.guest_sources import load_guest_sources
from common_lore_index.extractors.rust_pilot.prepared_profile import load_profile
from common_lore_index.extractors.rust_pilot.selection import MAX_INPUT_BYTES
from common_lore_index.graph.discovery_records import FileInfo


def _refusal(root: Path, infos: Sequence[FileInfo], *, docker_cli: str, image_id: str,
             profile: Path, platform: str, expected_commands: int, scenario_code: str,
             work_deadline: float | None = None) -> dict[str, Any]:
    audit: dict[str, Any] | None = None
    try:
        with RustPilotController(docker_cli=docker_cli, sdk_image_id=image_id,
                                  profile_dir=profile, platform=platform) as controller:
            controller._boundary.limit_work_deadline(work_deadline)
            observer = DockerBoundary(docker_cli)
            observer.limit_work_deadline(work_deadline)
            observer.require_work_deadline()
            before = observer.snapshot(controller.run_id)
            summary = controller.process(root, infos)
            audit = controller.audit_snapshot()
            counters = audit.get("counters") if isinstance(audit, Mapping) else None
            receipts_seen = audit.get("receipts", ()) if isinstance(audit, Mapping) else ()
            commands = (counters.get("commands", {}).get("value")
                        if isinstance(counters, Mapping) and isinstance(counters.get("commands"), Mapping)
                        else None)
            selected = list(controller.selected_paths())
            passed = (
                summary.run_outcome == "dependency_unavailable"
                and summary.refusal == "dependency_unavailable"
                and commands == expected_commands and not selected
                and isinstance(receipts_seen, Sequence) and len(receipts_seen) == 1
                and isinstance(receipts_seen[0], Mapping)
                and receipts_seen[0].get("state") == "unavailable"
                and isinstance(counters, Mapping)
                and counters.get("containers", {}).get("value") == 0
                and counters.get("parses", {}).get("value") == 0
            )
            after = observer.snapshot(controller.run_id)
            checked_counters = refusal_accounting(counters or {}, controller._boundary.journal,
                                                  observer.journal, before, after, controller.run_id)
            return {"scenario": scenario_code, "scenario_code": scenario_code, "passed": passed,
                    "outcome": summary.run_outcome, "refusal": summary.refusal,
                    "expected": {"outcome": "dependency_unavailable", "commands": expected_commands},
                    "observed": {"commands": commands, "selected_paths": selected},
                    "audit": audit, "counters": checked_counters,
                    "receipt": receipts_seen[0] if len(receipts_seen) == 1 else None}
    except (ContractError, OSError, AccountingGap):
        return {"scenario": scenario_code, "scenario_code": scenario_code, "passed": False,
                "outcome": None, "refusal": None, "expected": {"outcome": "dependency_unavailable",
                                                                  "commands": expected_commands},
                "observed": {}, "audit": audit, "counters": None,
                "error": "scenario_execution_failed"}


def _oversized_input(root: Path, *, docker_cli: str, image_id: str, profile_dir: Path,
                     audit_dir: Path, platform: str, work_deadline: float | None = None) -> dict[str, Any]:
    scenario_code = "Q06_oversized_input"
    data = b"fn oversized_input() {}\n"
    data += b" " * (MAX_INPUT_BYTES + 1 - len(data))
    digest = hashlib.sha256(data).hexdigest()
    audit: dict[str, Any] | None = None
    try:
        with tempfile.TemporaryDirectory(prefix="oversized-input-", dir=audit_dir) as temporary:
            temporary_root = Path(temporary)
            (temporary_root / "oversized.rs").write_bytes(data)
            info = FileInfo("oversized.rs", "unknown", "source", digest, False, False)
            with RustPilotController(docker_cli=docker_cli, sdk_image_id=image_id,
                                      profile_dir=profile_dir, platform=platform) as controller:
                controller._boundary.limit_work_deadline(work_deadline)
                summary = controller.process(temporary_root, (info,))
                audit = controller.audit_snapshot()
                counters = audit.get("counters") if isinstance(audit, Mapping) else None
                rows = audit.get("files", ()) if isinstance(audit, Mapping) else ()
                row = next((item for item in rows if isinstance(item, Mapping)
                            and item.get("input_sha256") == digest), None)
                refusal = next((item for item in audit.get("receipts", ()) if isinstance(item, Mapping)
                                and item.get("source_sha256") == digest), None)
                residue = audit.get("residue") if isinstance(audit, Mapping) else None
                passed = (
                    summary.run_outcome == "processed"
                    and summary.refusal is None
                    and summary.file_outcomes == (("oversized.rs", "resource_bound_exceeded"),)
                    and not controller.selected_paths()
                    and isinstance(row, Mapping) and "invocation_role" not in row and "cost" not in row
                    and isinstance(refusal, Mapping) and refusal.get("state") == "refused"
                    and isinstance(refusal.get("observed"), Mapping)
                    and refusal["observed"].get("verification") == "refused"
                    and isinstance(counters, Mapping)
                    and counters.get("containers", {}).get("value") == 1
                    and counters.get("parses", {}).get("value") == 1
                    and isinstance(residue, Mapping) and residue.get("observed") is True
                    and residue.get("owned_containers_remaining") == 0
                    and residue.get("journal_violations") == []
                    and residue.get("global_image_delta") == 0
                    and residue.get("global_volume_delta") == 0
                )
                return {"scenario": scenario_code, "scenario_code": scenario_code, "passed": passed,
                        "outcome": "resource_bound_exceeded" if row else None,
                        "input_sha256": digest, "input_bytes": len(data), "audit": audit,
                        "counters": counters, "receipt": refusal}
    except (ContractError, OSError):
        return {"scenario": scenario_code, "scenario_code": scenario_code, "passed": False,
                "outcome": None, "input_sha256": digest, "input_bytes": len(data),
                "audit": audit, "counters": None, "error": "scenario_execution_failed"}


def _tampered_setup(*, docker_cli: str, image_id: str, profile_dir: Path,
                    audit_dir: Path, platform: str, work_deadline: float | None = None) -> dict[str, Any]:
    """Run one real guest setup frame with a payload digest tamper."""

    scenario_code = "Q10_tampered_setup"
    docker_arch = platform.rsplit("/", 1)[-1]
    profile_cpu = CPU_BY_DOCKER_ARCH.get(docker_arch)
    run_id = run_identity(secrets.token_bytes(32))
    boundary = DockerBoundary(docker_cli)
    boundary.limit_work_deadline(work_deadline)
    owned: list[str] = []
    start = None
    source_sha: str | None = None
    profile_sha: str | None = None
    setup_result: Any = None
    construction_started: float | None = None
    construction_finished: float | None = None
    try:
        if profile_cpu is None:
            raise ContractError("unsupported_platform")
        server = boundary.server()
        if server.os != "linux" or server.arch != docker_arch:
            raise ContractError("server_mismatch")
        boundary.check_image(image_id, docker_arch)
        profile = load_profile(profile_dir, server_cpu=profile_cpu)
        profile_sha = profile.profile_sha256
        material = construction.build_material(profile, load_guest_sources(), construction.load_notices())
        tampered = bytearray(material.setup_stream)
        if not tampered:
            raise ContractError("setup_stream_empty")
        tampered[-1] ^= 1
        frame = bytes(tampered)
        source_sha = hashlib.sha256(frame).hexdigest()
        start = boundary.snapshot(run_id)
        construction_started = time.monotonic()
        deadline = construction_started + construction.CONSTRUCTION_BUDGET
        container_id = boundary.create(run_id=run_id, seq=1, docker_arch=docker_arch,
                                       image_id=image_id, hard_end=deadline, owned=owned)
        boundary.start(container_id, hard_end=deadline)
        check_container_config(boundary.inspect(container_id, hard_end=deadline),
                               container_id=container_id, image_id=image_id, run_id=run_id, seq=1)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ContractError("construction_deadline")
        setup_result = boundary.run_guest(
            container_id, user=SETUP_USER, workdir="/",
            tail=[*construction.PYTHON_FLAGS, "-c", material.sources.text("setup_writer")],
            stdin=frame, stdout_limit=4_096, deadline=remaining, hard_end=deadline)
    except (ContractError, OSError):
        pass
    if construction_started is not None:
        construction_finished = time.monotonic()
    settlement_started = time.monotonic()
    settlement_ok = False
    if owned:
        try:
            for owned_id in tuple(owned):
                boundary.begin_settlement(owned_id)
            settlement_ok = all(boundary.settle(owned_id) for owned_id in tuple(owned))
        except ContractError:
            settlement_ok = False
    settlement_ms = round((time.monotonic() - settlement_started) * 1000)
    construction_ms = None if construction_started is None or construction_finished is None else round(
        (construction_finished - construction_started) * 1000)
    if start is None or source_sha is None or profile_sha is None:
        return {"scenario": scenario_code, "scenario_code": scenario_code, "passed": False,
                "outcome": None, "audit": None, "counters": None,
                "cost": {"construction_ms": construction_ms, "settlement_ms": settlement_ms},
                "error": "scenario_execution_failed"}
    residue, residue_ok = controller_audit.observe_residue(
        boundary, run_id, start, () if settlement_ok else tuple(owned))
    expected_stderr = b"setup_refused payload_digest_mismatch\n"
    refused = (
        setup_result is not None and setup_result.returncode == 2 and setup_result.stdout == b""
        and setup_result.stderr_bytes == len(expected_stderr)
        and setup_result.stderr_sha256 == hashlib.sha256(expected_stderr).hexdigest()
        and setup_result.settled and not setup_result.io_failed
        and setup_result.input_complete and not setup_result.callback_failed
    )
    outcome = ("setup_refused" if refused else
               "setup_succeeded" if setup_result is not None and setup_result.returncode == 0
               else "setup_unclassified" if setup_result is not None else "not_observed")
    cost = {
        "construction_ms": construction_ms, "readback_ms": None, "parse_ms": None,
        "settlement_ms": settlement_ms, "readback_bytes": None, "installed_tree_bytes": None,
        "stdout_bytes": None if setup_result is None else len(setup_result.stdout),
        "diagnostic_bytes": None if setup_result is None else setup_result.stderr_bytes,
        "memory_peak_bytes": None, "memory_peak_basis": "guest_reported",
        "memory_peak_reason": "not_observed", "construction_includes_readback": False,
    }
    row = {"seq": 1, "scenario_code": scenario_code, "input_sha256": source_sha,
           "outcome": outcome, "completeness": "none",
           "cleanup": "proven" if settlement_ok and residue_ok else "incomplete", "cost": cost}
    observed_receipts: tuple[Any, ...] = ()
    if refused:
        observed_receipts = (receipts.refusal_receipt(
            run_id=run_id, seq=1, source_sha256=source_sha, profile_sha256=profile_sha,
            code="inadmissible_effects", cleanup="proven" if settlement_ok and residue_ok else "incomplete"),)
    audit = controller_audit.audit_snapshot(run_id, (row,), observed_receipts, residue, boundary)
    counters = audit.get("counters") if isinstance(audit, Mapping) else None
    passed = (
        refused and settlement_ok and residue_ok
        and isinstance(counters, Mapping)
        and counters.get("containers", {}).get("value") == 1
        and counters.get("parses", {}).get("value") == 0
        and isinstance(counters.get("commands", {}).get("value"), int)
        and counters.get("commands", {}).get("value") > 0
        and isinstance(audit.get("receipts"), Sequence) and len(audit["receipts"]) == 1
    )
    return {"scenario": scenario_code, "scenario_code": scenario_code, "passed": passed,
            "outcome": outcome, "refusal": "payload_digest_mismatch" if refused else None,
            "audit": audit, "counters": counters,
            "receipt": audit["receipts"][0] if len(audit["receipts"]) == 1 else None}


def preflight_scenarios(root: Path, infos: Sequence[FileInfo], *, docker_cli: str, image_id: str,
                        profile_dir: Path, audit_dir: Path, platform: str,
                        cross_cpu_profile: Path | None, work_dir: Path | None = None,
                        work_deadline: float | None = None) -> dict[str, Any]:
    scratch_root = profile_dir.parent if work_dir is None else work_dir
    if scratch_root.resolve().is_relative_to(audit_dir.parent.resolve()):
        raise ContractError("preflight_scratch_in_report")
    require_work_deadline(work_deadline)
    result = {"Q07_missing_profile": _refusal(
        root, infos, docker_cli=docker_cli, image_id=image_id,
        profile=audit_dir / "nonexistent-profile", platform=platform, expected_commands=0,
        scenario_code="Q07_missing_profile", work_deadline=work_deadline)}
    require_work_deadline(work_deadline)
    verified = load_profile(profile_dir)
    with tempfile.TemporaryDirectory(prefix="corrupt-profile-", dir=scratch_root) as temporary:
        corrupt = Path(temporary)
        (corrupt / "profile.json").write_bytes(verified.profile_bytes)
        (corrupt / "profile.json").chmod(0o600)
        for index, wheel in enumerate(verified.wheels):
            require_work_deadline(work_deadline)
            data = wheel.data if index else bytes([wheel.data[0] ^ 1]) + wheel.data[1:]
            path = corrupt / wheel.lock.filename
            path.write_bytes(data)
            path.chmod(0o600)
        result["Q10_corrupt_artifact"] = _refusal(
            root, infos, docker_cli=docker_cli, image_id=image_id, profile=corrupt,
            platform=platform, expected_commands=0, scenario_code="Q10_corrupt_artifact", work_deadline=work_deadline)
    require_work_deadline(work_deadline)
    result["Q06_oversized_input"] = _oversized_input(
        root, docker_cli=docker_cli, image_id=image_id, profile_dir=profile_dir,
        audit_dir=audit_dir, platform=platform, work_deadline=work_deadline)
    require_work_deadline(work_deadline)
    result["Q10_tampered_setup"] = _tampered_setup(
        docker_cli=docker_cli, image_id=image_id, profile_dir=profile_dir,
        audit_dir=audit_dir, platform=platform, work_deadline=work_deadline)
    require_work_deadline(work_deadline)
    if platform == "linux/arm64":
        if cross_cpu_profile is None or load_profile(cross_cpu_profile).cpu != "x86_64":
            raise ValueError("native_cross_cpu_profile_unavailable")
        result["Q11_wrong_cpu"] = _refusal(
            root, infos, docker_cli=docker_cli, image_id=image_id, profile=cross_cpu_profile,
            platform="linux/amd64", expected_commands=1, scenario_code="Q11_wrong_cpu", work_deadline=work_deadline)
    return result


def native_containment(docker_cli: str, image_id: str, profile_dir: Path, *, platform: str,
                       work_deadline: float | None = None) -> dict[str, Any]:
    from ci.qualification_rust_runtime import PLATFORM_FACTS, RuntimeGap
    from common_lore_index.extractors.rust_pilot import construction, controller_audit
    from common_lore_index.extractors.rust_pilot.containment import run_containment_probes
    from common_lore_index.extractors.rust_pilot.controller import run_identity
    from common_lore_index.extractors.rust_pilot.docker_boundary import DockerBoundary
    from common_lore_index.extractors.rust_pilot.guest_sources import load_guest_sources
    from common_lore_index.extractors.rust_pilot.prepared_profile import load_profile
    facts = PLATFORM_FACTS.get(platform)
    if facts is None:
        raise RuntimeGap("unsupported_platform")
    profile_cpu, docker_arch = facts

    boundary = DockerBoundary(docker_cli)
    boundary.limit_work_deadline(work_deadline)
    server = boundary.server()
    if server.os != "linux" or server.arch not in {profile_cpu, docker_arch}:
        raise RuntimeGap("containment_server_mismatch")
    boundary.check_image(image_id, docker_arch)
    profile = load_profile(profile_dir, server_cpu=profile_cpu)
    material = construction.build_material(profile, load_guest_sources(), construction.load_notices())
    run_id = run_identity(secrets.token_bytes(32))
    start = boundary.snapshot(run_id)
    outcomes = run_containment_probes(boundary, run_id=run_id, first_seq=1,
                                      docker_arch=docker_arch, image_id=image_id, material=material)
    residue, settled = controller_audit.observe_residue(boundary, run_id, start, ())
    counters = controller_audit.audit_snapshot(run_id, (), (), residue, boundary)["counters"]
    result = {"run_id": run_id, "role": "containment", "counters": counters,
            "outcomes": [{"name": item.name, "expected": item.expected, "observed": item.observed,
                          "absence_proven": item.absence_proven}
                         for item in outcomes], "residue": residue}
    if not settled or not outcomes or any(not outcome.passed for outcome in outcomes):
        raise RuntimeGap("containment_not_proven", {"containment": result})
    return result

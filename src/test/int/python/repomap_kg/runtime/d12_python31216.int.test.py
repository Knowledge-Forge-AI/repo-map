"""Containerized raw native linux/arm64 Python 3.12.16 component proof owner (ADR 0100).

This owner never pulls, builds or materializes. It reads the exact
base the canonical inner harness preloaded, validates native ARM64 and the exact config and rootfs before any image
execution, and runs the payload contract once in a network-less container. Dependency-cache and dynamic-Psycopg
qualification are separate. On a native AMD daemon it proves the ARM admission refusal before image access and
reports that refusal explicitly; it never reports an AMD payload qualification.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from repomap_kg.runtime import python_payload as payload
from repomap_kg.runtime import release
from repomap_kg.runtime.commands import PYTHON_PAYLOAD_SOURCE
from repomap_test_support import d12_core_image as d12
from repomap_test_support import d12_python31216 as proof
from repomap_test_support.resource_docker_current import CurrentRunDockerContainers
from repomap_test_support.resource_ledger import ResourceKind
from repomap_test_support.resource_run import active_resource_run
from repomap_test_support.resource_test_images import TestImageManager

REPO_ROOT = Path(__file__).resolve().parents[6]


def test_python_31216_native_arm64_component_proof(capsys: pytest.CaptureFixture[str]) -> None:
    boundary = d12.locate_run_boundary()
    run = active_resource_run()
    assert run is not None, "the Python 3.12.16 component proof requires the canonical resource run"
    client = boundary.client
    # A foreign daemon refuses here, before any image read or execution; nothing is inferred across architectures.
    raw_arch = str(client.info().get("Architecture") or "")
    operations_before = boundary.projection()
    if raw_arch.strip().lower() in ("amd64", "x86_64"):
        with pytest.raises(proof.Python31216ProofError, match="native linux/arm64 proof refuses"):
            proof.normalize_daemon_arch(raw_arch)
        amd64 = payload.build_31216_exclusion("amd64", payload.AMD64_31216_NATIVE_BASELINE_IMPORTS)
        assert payload.PYTHON_PAYLOAD_EXCLUSIONS["amd64"] == amd64  # ADR 0103 source fact; this ARM owner never vouches
        proof.validate_zero_docker_operations(boundary.projection(), baseline=operations_before)
        with capsys.disabled():
            print("PY31216_ARM_ADMISSION_REFUSAL_JSON:" + json.dumps({
                "daemon_arch": raw_arch, "result": "arm64_proof_refused", "amd64_qualified": False,
                "amd64_default_enrolled": True}), flush=True)
        return
    daemon_arch = proof.normalize_daemon_arch(raw_arch)

    manager = TestImageManager(
        repo_root=REPO_ROOT,
        resource_run=run,
        client=client,
        boundary=boundary,
        base_reference=release.PYTHON_RELEASE_IMAGE,
        python_base_family="python:3.12-slim-trixie",
        python_version=release.PYTHON_RELEASE_VERSION,
        psycopg_release_version=release.PSYCOPG_RELEASE_VERSION,
    )
    # Passive: reads the preloaded exact base (absent refuses); never pulls, builds or materializes.
    manager.runtime_identity()
    base_prov = manager.base_provenance
    base_attrs = client.images.get(base_prov.image_id).attrs
    provenance = proof.validate_native_arm64_base_provenance(
        daemon_arch=daemon_arch,
        reference=base_prov.reference,
        index_digest=base_prov.digest,
        manifest_digest=payload.PYTHON_31216_ARM64_MANIFEST,
        config_digest=payload.PYTHON_31216_ARM64_CONFIG,
        image_id=str(base_attrs.get("Id") or ""),
        repo_digests=tuple(str(item) for item in (base_attrs.get("RepoDigests") or ())),
        image_os=str(base_attrs.get("Os") or ""),
        image_arch=str(base_attrs.get("Architecture") or ""),
        pulled=base_prov.pulled,
        retained_manifest_bytes=proof.RETAINED_ARM64_MANIFEST_BYTES,
        rootfs_layers=tuple(str(x) for x in ((base_attrs.get("RootFS") or {}).get("Layers") or ())),
    )
    assert base_prov.image_id == provenance["image_id"], (base_prov.image_id, provenance["image_id"])

    payload_source_path = REPO_ROOT / PYTHON_PAYLOAD_SOURCE
    assert payload_source_path.resolve() == Path(payload.__file__).resolve()
    inner_script = proof.build_inner_probe_script(payload_source_path.read_bytes())

    owner = CurrentRunDockerContainers(run, client)
    cid = owner.create(
        base_prov.image_id,
        ["-I", "-B", "-c", inner_script],
        role="d12-python31216-native-proof",
        entrypoint=["python3"],
        network_mode="none",
    )
    try:
        container = client.containers.get(cid)
        container.start()
        status = container.wait(timeout=300).get("StatusCode", 1)
        stdout = container.logs(stdout=True, stderr=False).decode("utf-8", "replace")
        stderr = container.logs(stdout=False, stderr=True).decode("utf-8", "replace")
        # The raw observation and inner probe line reach the terminal before cleanup or any assertion can fail;
        # capture is suspended so a passing run keeps them (pytest discards captured stdout on PASS).
        with capsys.disabled():
            for line in proof.raw_observation_lines(stdout):
                print(line, flush=True)
            for line in stdout.splitlines():
                if line.startswith(proof.INNER_STDOUT_PREFIX):
                    print(line, flush=True)
    finally:
        owner.cleanup(cid)
    owner.verify_baseline()
    ledger_rec = run.ledger.get(ResourceKind.DOCKER_CONTAINER, cid)
    cleanup_details = proof.validate_container_cleanup(
        container_id=cid,
        cleanup_result=ledger_rec.cleanup_result.value,
        final_presence=ledger_rec.final_presence.value,
        engine_absent=(owner.api.inspect(ResourceKind.DOCKER_CONTAINER, cid) is None),
        baseline_verified=True,  # verify_baseline() returned; it raises on any baseline change
    )
    operations_after = proof.validate_zero_docker_operations(boundary.projection(), baseline=operations_before)

    assert status == 0, f"Python 3.12.16 inner probe failed with {status}: {stderr[-4000:]}"
    probe_lines = [
        line.removeprefix(proof.INNER_STDOUT_PREFIX)
        for line in stdout.splitlines()
        if line.startswith(proof.INNER_STDOUT_PREFIX)
    ]
    assert len(probe_lines) == 1, stdout[-2000:]
    inner_data = json.loads(probe_lines[0])
    assert inner_data["python_version"] == proof.EXPECTED_PYTHON_VERSION
    assert inner_data["python_banner"] == proof.EXPECTED_PYTHON_BANNER

    trimmed_summary = proof.validate_trimmed_arm64_proof_report(
        raw_report=inner_data["raw_report"],
        trimmed_report=inner_data["trimmed_report"],
        entry_delta=int(inner_data["entry_delta"]),
        modified_survivors=tuple(inner_data["modified_survivors"]),
    )
    proof_record = proof.build_native_proof_record(
        provenance=provenance,
        operations_before=operations_before,
        operations_after=operations_after,
        trimmed_summary=trimmed_summary,
        default_enrolled=bool(inner_data["default_enrolled"]),
        cleanup_details=cleanup_details,
    )
    with capsys.disabled():
        print(proof.format_native_proof_stdout(proof_record), flush=True)
    assert proof_record["amd64_qualified"] is False and proof_record["amd64_default_enrolled"] is True

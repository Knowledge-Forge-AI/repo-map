"""Containerized native linux/arm64 Trixie glibc disposition component proof (ADR 0101).

Like the ADR 0100 owner, this never pulls, builds or materializes. It reads the exact raw Python 3.12.16 base the
canonical inner harness preloaded, validates native ARM64 config, manifest and rootfs provenance before any image
execution, and runs the production D12 inventory probe once in a network-less run-owned container. The real libc6
observation feeds the production assessor; one bounded changed assessor input then demonstrates a genuine refusal
without mutating container bytes or running another probe. This is component proof only: no AMD, application-image,
P3 or image qualification is inferred. A native AMD daemon proves the ARM admission refusal before image access;
that explicitly reported refusal is separate from a positive native ARM component observation.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from repomap_kg.runtime import python_payload as payload
from repomap_kg.runtime import release
from repomap_test_support import d12_core_image as d12
from repomap_test_support import d12_python31216 as proof
from repomap_test_support.d12_image_probes import _inventory
from repomap_test_support.resource_docker_current import CurrentRunDockerContainers
from repomap_test_support.resource_ledger import ResourceKind
from repomap_test_support.resource_run import active_resource_run
from repomap_test_support.resource_test_images import TestImageManager
from tools.system import d12_glibc_risk as risk

REPO_ROOT = Path(__file__).resolve().parents[6]
OBSERVATION_PREFIX = "D12_GLIBC_DISPOSITION_JSON:"
OBSERVATION_SCHEMA = "repomap-d12-glibc-native-component-v1"
MAX_OBSERVATION_BYTES = 16_384
PROBE_ROLE = "d12-glibc-disposition-native"
FUTURE_LIBC_VERSION = "2.41-12+deb13u5"


class _RecordingOwner:
    """Delegates to the current-run owner and records each exact container ID the moment it is created."""

    def __init__(self, inner: CurrentRunDockerContainers) -> None:
        self.inner = inner
        self.created: list[str] = []

    def create(self, image_reference: str, command: Any, *, role: str, **options: Any) -> str:
        identity = self.inner.create(image_reference, command, role=role, **options)
        self.created.append(identity)
        return identity

    def cleanup(self, identity: str) -> None:
        self.inner.cleanup(identity)


def _libc_evidence(inventory: dict[str, Any]) -> dict[str, Any]:
    """The bounded raw libc slice of the real probe output, retained beside the assessor result."""
    return {
        "files": [row for row in inventory["files"] if str(row.get("resolved", "")).endswith("/libc.so.6")
                  or str(row.get("invoked", "")).endswith("/libc.so.6")],
        "links": [row for row in inventory["links"] if row[1:2] == ["libc.so.6"]],
        "packages": [row for row in inventory["packages"] if row[:1] and row[0] in risk.GLIBC_PACKAGES],
        "notice": inventory["notices"].get(risk.LIBC_NOTICE), "os": inventory["os"],
    }


def test_native_trixie_glibc_disposition(capsys: pytest.CaptureFixture[str]) -> None:
    boundary = d12.locate_run_boundary()
    run = active_resource_run()
    assert run is not None, "the glibc disposition component proof requires the canonical resource run"
    client = boundary.client
    # A foreign daemon refuses here, before any image read or execution; nothing is inferred across architectures.
    raw_daemon_arch = str(client.info().get("Architecture") or "")
    operations_before = boundary.projection()
    if raw_daemon_arch.strip().lower() in ("amd64", "x86_64"):
        with pytest.raises(proof.Python31216ProofError, match="native linux/arm64 proof refuses"):
            proof.normalize_daemon_arch(raw_daemon_arch)
        proof.validate_zero_docker_operations(boundary.projection(), baseline=operations_before)
        with capsys.disabled():
            print("D12_GLIBC_ARM_ADMISSION_REFUSAL_JSON:" + json.dumps({
                "daemon_arch": raw_daemon_arch, "result": "arm64_proof_refused", "image_qualified": False}), flush=True)
        return
    daemon_arch = proof.normalize_daemon_arch(raw_daemon_arch)
    availability = d12.platform_availability("linux/arm64", raw_daemon_arch, ())  # emulation refuses

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

    # Exactly one network-less probe: the production D12 inventory script on the exact config ID. _run_once removes
    # its container in its own finally; any container left by a failed create readback is removed here.
    current = CurrentRunDockerContainers(run, client)
    owner = _RecordingOwner(current)
    try:
        inventory = _inventory(owner, client, provenance["image_id"], None, PROBE_ROLE)
    finally:
        for identity in owner.created:
            if current.api.inspect(ResourceKind.DOCKER_CONTAINER, identity) is not None:
                current.cleanup(identity)
    current.verify_baseline()
    assert len(owner.created) == 1, owner.created
    cid = owner.created[0]
    ledger_rec = run.ledger.get(ResourceKind.DOCKER_CONTAINER, cid)
    cleanup_details = proof.validate_container_cleanup(
        container_id=cid,
        cleanup_result=ledger_rec.cleanup_result.value,
        final_presence=ledger_rec.final_presence.value,
        engine_absent=(current.api.inspect(ResourceKind.DOCKER_CONTAINER, cid) is None),
        baseline_verified=True,  # verify_baseline() returned; it raises on any baseline change
    )
    operations_after = proof.validate_zero_docker_operations(boundary.projection(), baseline=operations_before)

    image = {"label": "python-31216-arm64-base", "base_reference": release.PYTHON_RELEASE_IMAGE,
             "image_id": provenance["image_id"], "platform": availability["platform"],
             "execution": availability["execution"], "inventory": inventory}
    accepted = risk.evaluate_glibc_disposition([image])
    # One bounded changed INPUT to the assessor: the same real observation claiming a future libc6 version.
    changed = copy.deepcopy(inventory)
    libc6_rows = [row for row in changed["packages"] if row[:1] == ["libc6"]]
    for row in libc6_rows:
        row[1] = FUTURE_LIBC_VERSION
    refused = risk.evaluate_glibc_disposition([{**image, "inventory": changed}])
    finding_ids = [item["id"] for item in accepted.get("findings", [])]

    observation = {
        "schema": OBSERVATION_SCHEMA, "scope": "native linux/arm64 component proof only; AMD, application image, "
        "P3 and image qualification are not inferred",
        "provenance": {key: provenance[key] for key in (
            "platform", "reference", "index_digest", "manifest_digest", "config_digest", "image_id",
            "rootfs_diff_ids_verified", "pulled_by_test_image_manager")},
        "availability": availability, "probe_role": PROBE_ROLE, "raw_libc": _libc_evidence(inventory),
        "accepted": {key: accepted.get(key) for key in ("status", "refusal", "record_sha256", "images",
                                                        "image_qualified", "accepts_image_or_other_findings")},
        "accepted_finding_ids": finding_ids,
        "changed_input": {"libc6_version": FUTURE_LIBC_VERSION, "rows_changed": len(libc6_rows),
                          "status": refused["status"], "refusal": refused.get("refusal")},
        "operations_before": operations_before, "operations_after": operations_after, "cleanup": cleanup_details,
    }
    encoded = json.dumps(observation, sort_keys=True, separators=(",", ":"))
    # Capture is suspended so a passing run keeps the single bounded observation line.
    with capsys.disabled():
        print(OBSERVATION_PREFIX + encoded[:MAX_OBSERVATION_BYTES], flush=True)
    assert len(encoded.encode("utf-8")) <= MAX_OBSERVATION_BYTES, len(encoded)

    assert accepted["status"] == risk.ACCEPTED, accepted.get("refusal")
    assert accepted["record_sha256"] == risk.APPROVED_RECORD_SHA256
    assert accepted["image_qualified"] is False and accepted["accepts_image_or_other_findings"] is False
    assert tuple(finding_ids) == risk.FINDING_IDS
    (observed,) = accepted["images"]
    assert (observed["image_id"], observed["platform"]) == (payload.PYTHON_31216_ARM64_CONFIG, "linux/arm64")
    assert observed["package"] == ["libc6", "2.41-12+deb13u4", "arm64"]
    assert observed["glibc_packages"] == [[name, "2.41-12+deb13u4", "arm64"] for name in risk.GLIBC_PACKAGES]
    assert observed["os"] == ["Debian GNU/Linux 13 (trixie)", "aarch64", "arm64"]
    assert observed["libc"]["path"] == "/usr/lib/aarch64-linux-gnu/libc.so.6"
    assert (observed["libc"]["owner"], observed["libc"]["md5"]) == ("libc6", "match")
    assert observed["libc"]["file_observations"] >= 1 and observed["libc"]["ldd_observations"] >= 1
    assert observed["notice"]["path"] == risk.LIBC_NOTICE
    assert len(libc6_rows) == 1 and refused["status"] == risk.REFUSED, refused
    assert "libc6 package rows" in str(refused["refusal"]) and FUTURE_LIBC_VERSION in str(refused["refusal"])
    assert refused["images"] == [{"label": image["label"], "base_reference": release.PYTHON_RELEASE_IMAGE,
                                  "image_id": provenance["image_id"], "platform": "linux/arm64"}]

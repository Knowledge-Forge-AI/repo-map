"""Native ARM component proof for ADR0105's Debian responsibility boundary.

Use the current exact harness-preloaded slim image and complete production collector. Prove real supplier bytes,
retain the historical glibc-record refusal as information, and reject an introduced package mismatch. This is
component evidence, not native AMD or application-image qualification. The AMD host proves ARM admission refusal.
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
from repomap_test_support.d12_complete_inventory import complete_inventory
from repomap_test_support.d12_image_probes import _hashes
from tools.system.d12_debian_policy import DebianDeltaError, assess_debian_delta
from repomap_test_support.resource_docker_current import CurrentRunDockerContainers
from repomap_test_support.resource_ledger import ResourceKind
from repomap_test_support.resource_run import active_resource_run
from repomap_test_support.resource_test_images import TestImageManager
from tools.system import d12_glibc_risk as risk

REPO_ROOT = Path(__file__).resolve().parents[6]
OBSERVATION_PREFIX = "D12_GLIBC_DISPOSITION_JSON:"
OBSERVATION_SCHEMA = "repomap-d12-debian-native-component-v2"
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

    # Complete inventory and independent hash probes of the two already-preloaded supplier bases.
    # Each execution is network-less; exact cleanup also covers failed create/readback paths.
    current = CurrentRunDockerContainers(run, client)
    owner = _RecordingOwner(current)
    try:
        inventory = complete_inventory(owner, client, provenance["image_id"], None, PROBE_ROLE)
        paths = sorted({row["resolved"] for row in inventory["files"] if row["kind"] != "missing"})
        supplier_hashes = _hashes(owner, client, provenance["image_id"], paths, None, PROBE_ROLE + "-hashes")
        pg_base = d12.verify_bases(client, "linux/arm64", (release.POSTGRES_RELEASE_IMAGE,))[release.POSTGRES_RELEASE_IMAGE]
        assert pg_base["config_digest_verified"] is True
        pg_inventory = complete_inventory(owner, client, str(pg_base["id"]), None, PROBE_ROLE + "-postgres")
        pg_paths = sorted({row["resolved"] for row in pg_inventory["files"] if row["kind"] != "missing"})
        pg_hashes = _hashes(owner, client, str(pg_base["id"]), pg_paths, None, PROBE_ROLE + "-postgres-hashes")
    finally:
        for identity in owner.created:
            if current.api.inspect(ResourceKind.DOCKER_CONTAINER, identity) is not None:
                current.cleanup(identity)
    current.verify_baseline()
    assert inventory["package_verification"]["count"] == len(inventory["package_verification"]["rows"])
    assert len(inventory["package_verification"]["checks"]) == len(inventory["packages"])
    assert inventory["unowned_count"] == len(inventory["unowned_usr_lib"])
    assert len(inventory["source_packages"]) == len(inventory["packages"])
    assert len(owner.created) == 4, owner.created
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
    legacy = risk.evaluate_glibc_disposition([image])
    accepted = assess_debian_delta(copy.deepcopy(inventory), inventory, {"python": supplier_hashes})
    pg_accepted = assess_debian_delta(copy.deepcopy(pg_inventory), pg_inventory, {"postgres": pg_hashes})
    inventory_bytes = {name: len((json.dumps(value, indent=2, sort_keys=True) + "\n").encode())
                       for name, value in (("python", inventory), ("postgres", pg_inventory))}
    assert all(size <= d12.REPORT_PART_LIMIT for size in inventory_bytes.values()), inventory_bytes
    changed = copy.deepcopy(inventory)
    libc6_rows = [row for row in changed["packages"] if row[:1] == ["libc6"]]
    for row in libc6_rows:
        row[1] = FUTURE_LIBC_VERSION
    with pytest.raises(DebianDeltaError, match="packages changed"):
        assess_debian_delta(changed, inventory, {"python": supplier_hashes})

    observation = {
        "schema": OBSERVATION_SCHEMA, "scope": "native linux/arm64 component proof only; AMD, application image, "
        "P3 and image qualification are not inferred",
        "provenance": {key: provenance[key] for key in (
            "platform", "reference", "index_digest", "manifest_digest", "config_digest", "image_id",
            "rootfs_diff_ids_verified", "pulled_by_test_image_manager")},
        "availability": availability, "probe_role": PROBE_ROLE, "raw_libc": _libc_evidence(inventory),
        "complete_inventory": {
            "schema": inventory["schema"], "packages": len(inventory["packages"]),
            "verification_rows": inventory["package_verification"]["count"],
            "package_checks": len(inventory["package_verification"]["checks"]),
            "packages_without_md5sums": sum(r["md5sums_sha256"] == "absent" for r in inventory["package_verification"]["checks"]),
            "dpkg_configs": inventory["dpkg_configs"], "path_filters": inventory["path_filters"],
        },
        "accepted": accepted,
        "postgres_supplier": {"config_id": pg_base["id"], "complete_packages": len(pg_inventory["packages"]),
            "enumerations": pg_inventory["enumerations"], "assessment": pg_accepted},
        "complete_inventory_json_bytes": inventory_bytes,
        "historical_glibc_record": {key: legacy.get(key) for key in ("status", "refusal", "record_sha256")},
        "changed_input": {"libc6_version": FUTURE_LIBC_VERSION, "rows_changed": len(libc6_rows),
                          "status": "refused_introduced_package_mismatch"},
        "operations_before": operations_before, "operations_after": operations_after, "cleanup": cleanup_details,
    }
    encoded = json.dumps(observation, sort_keys=True, separators=(",", ":"))
    assert len(encoded.encode("utf-8")) <= MAX_OBSERVATION_BYTES, len(encoded)
    # Capture is suspended so a passing run keeps the complete bounded observation line.
    with capsys.disabled():
        print(OBSERVATION_PREFIX + encoded, flush=True)

    assert accepted["assembly_delta_verified"] is True
    assert accepted["upstream_debian_findings_blocking"] is False
    assert accepted["inherited_verification_rows"] == inventory["package_verification"]["count"]
    assert len(libc6_rows) == 1
    assert legacy["status"] == risk.REFUSED  # The old finite record does not apply to this refreshed base.
    assert provenance["image_id"] == payload.PYTHON_31216_ARM64_CONFIG

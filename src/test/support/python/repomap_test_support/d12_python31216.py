"""ADR 0100 native linux/arm64 Python 3.12.16 component proof helpers and fail-closed validators."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping, Sequence

from repomap_kg.runtime import python_payload as payload
from repomap_kg.runtime import release
from repomap_kg.runtime import release_manifest as historical
from repomap_test_support.resource_docker_operation_records import DERIVED_OPERATION_FIELDS

PROOF_SCHEMA = "repomap-d12-python31216-native-proof-v1"
PROOF_STDOUT_PREFIX = "PY31216_NATIVE_PROOF_JSON:"
RAW_OBSERVATION_STDOUT_PREFIX = "PY31216_RAW_OBSERVATION_JSON:"
INNER_STDOUT_PREFIX = "REPOMAP_PY31216_INNER_PROBE="
INNER_RAW_STDOUT_PREFIX = "REPOMAP_PY31216_RAW_OBSERVATION="
EXPECTED_PYTHON_VERSION, EXPECTED_PYTHON_BANNER = "3.12.16", "Python 3.12.16"
HISTORICAL_31215_INDEX = "sha256:a0f57064cbdcd6285fa45f51237ab0b35ea8ebaed06a1f5973e89e19dfb86704"
HISTORICAL_31215_ARM64_CONFIG = "sha256:7efd45553a98be3d940b73600550669831c0be34f30c521159e7030a91fcdee6"
ARM64_31216_PREDICTED_IMPORTS_AWAITING_NATIVE_PROOF = historical.ARM64_BASELINE_IMPORTS
DEPENDENCY_CACHE_UNEXECUTED_REASON = "This raw component probe does not qualify a dependency runtime cache."
ARM64_TKINTER_PATH = f"{payload.DYNLOAD}/_tkinter.cpython-312-aarch64-linux-gnu.so"
ARM64_TKINTER_SHA256 = "9fe4f2c93a746b000a15ebb6fbb71ea33b3b7888efb70e3c1296fac8b30c2c96"
ARM64_TKINTER_SIZE, ARM64_TKINTER_ELF_MACHINE = 70584, 183
ARM64_TKINTER_MISSING = ("libtcl8.6.so", "libtk8.6.so")
EXPECTED_ARM64_LAYER_DIGESTS = ('sha256:2b70e040f7d132c8d366ee0223462552686510fb372ea5a83822973c30f19e36',
 'sha256:0922d1fc1a5f7baa280015c744bb0be989e6e146a9181c04d2971e1273416844',
 'sha256:b41621e272b0b306c196fabab6f5e0132d1c13f3c929bfb63455191fa509e311',
 'sha256:64074ecd150a3526f7ef1af3128b9186744abfb9dc3d1c3e87c11c1ea880cbd0')
EXPECTED_ARM64_DIFF_IDS = ('sha256:685889762157cefb6370119253b3c709f70bb2622402052065c92243e3d9105f',
 'sha256:5c0bc5ee0491a1a68853ceaecd26669d4e40028743b5ae987ee7ca5f9537680f',
 'sha256:e3af5abbdc37fa9b5b795480004e631040ad0b537c2174d07352e25c43d1d0ed',
 'sha256:013d8fa6cec40683d59b02f867200c97732ee03b6ce0a5816df5702a353ffedc')
RETAINED_ARM64_MANIFEST_BYTES = (
    b'{\n' b'  "schemaVersion": 2,\n'
    b'  "mediaType": "application/vnd.oci.image.manifest.v1+json",\n' b'  "config": {\n'
    b'    "mediaType": "application/vnd.oci.image.config.v1+json",\n'
    b'    "digest": "sha256:ff710677e697054c516f12c53c92166f1aef075f21b2a593f4c615e522112b4e",\n'
    b'    "size": 5679\n' b'  },\n'
    b'  "layers": [\n' b'    {\n'
    b'      "mediaType": "application/vnd.oci.image.layer.v1.tar+gzip",\n'
    b'      "digest": "sha256:2b70e040f7d132c8d366ee0223462552686510fb372ea5a83822973c30f19e36",\n'
    b'      "size": 30213496\n' b'    },\n'
    b'    {\n' b'      "mediaType": "application/vnd.oci.image.layer.v1.tar+gzip",\n'
    b'      "digest": "sha256:0922d1fc1a5f7baa280015c744bb0be989e6e146a9181c04d2971e1273416844",\n'
    b'      "size": 1270171\n' b'    },\n'
    b'    {\n' b'      "mediaType": "application/vnd.oci.image.layer.v1.tar+gzip",\n'
    b'      "digest": "sha256:b41621e272b0b306c196fabab6f5e0132d1c13f3c929bfb63455191fa509e311",\n'
    b'      "size": 12060033\n' b'    },\n'
    b'    {\n' b'      "mediaType": "application/vnd.oci.image.layer.v1.tar+gzip",\n'
    b'      "digest": "sha256:64074ecd150a3526f7ef1af3128b9186744abfb9dc3d1c3e87c11c1ea880cbd0",\n'
    b'      "size": 251\n' b'    }\n'
    b'  ],\n' b'  "annotations": {\n'
    b'    "com.docker.official-images.bashbrew.arch": "arm64v8",\n'
    b'    "org.opencontainers.image.base.digest": "sha256:1470991b497d26788dc4d6f438bf5690c6ba0d499235d237e55f4b43caea7a75",\n'
    b'    "org.opencontainers.image.base.name": "debian:trixie-slim",\n'
    b'    "org.opencontainers.image.created": "2026-10-28T01:58:03Z",\n'
    b'    "org.opencontainers.image.revision": "3d7e95597e56a415d9e4abc0f15877e005d2cb2e",\n'
    b'    "org.opencontainers.image.source": "https://github.com/docker-library/python.git#3d7e95597e56a415d9e4abc0f15877e005d2cb2e:3.12/slim-trixie",\n'
    b'    "org.opencontainers.image.url": "https://hub.docker.com/_/python",\n'
    b'    "org.opencontainers.image.version": "3.12.16-slim-trixie"\n' b'  }\n'
    b'}'
)

class Python31216ProofError(ValueError):
    """Raised when the Python 3.12.16 native ARM64 component proof violates ADR 0100."""


def normalize_daemon_arch(raw_arch: str) -> str:
    """Normalize the Docker daemon architecture and refuse non-ARM64 or cross-arch inference."""
    cleaned = str(raw_arch).strip().lower()
    if cleaned in ("aarch64", "arm64"):
        return "arm64"
    if cleaned in ("x86_64", "amd64"):
        raise Python31216ProofError(
            f"native linux/arm64 proof refuses {cleaned!r} daemon; never infer amd64 from arm64 or vice versa"
        )
    raise Python31216ProofError(f"unsupported daemon architecture for native arm64 proof: {raw_arch!r}")


def validate_native_arm64_base_provenance(
    *, daemon_arch: str, reference: str, index_digest: str, manifest_digest: str, config_digest: str,
    image_id: str, repo_digests: Sequence[str], image_os: str, image_arch: str, pulled: bool,
    retained_manifest_bytes: bytes = RETAINED_ARM64_MANIFEST_BYTES, rootfs_layers: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Validate that the local Python 3.12.16 base image matches the pinned ARM64 OCI hierarchy."""
    normalized_daemon = normalize_daemon_arch(daemon_arch)
    if pulled:
        raise Python31216ProofError("the proof reads the harness-preloaded base passively; an in-run pull is refused")
    if release.PYTHON_RELEASE_VERSION != EXPECTED_PYTHON_VERSION:
        raise Python31216ProofError(
            f"release.PYTHON_RELEASE_VERSION is {release.PYTHON_RELEASE_VERSION!r}, "
            f"expected {EXPECTED_PYTHON_VERSION!r}"
        )
    if reference != release.PYTHON_RELEASE_IMAGE:
        raise Python31216ProofError(
            f"base reference {reference!r} does not match release.PYTHON_RELEASE_IMAGE {release.PYTHON_RELEASE_IMAGE!r}"
        )
    if index_digest in (HISTORICAL_31215_INDEX, "") or index_digest != payload.PYTHON_31216_INDEX:
        raise Python31216ProofError(
            f"index digest {index_digest!r} does not match PYTHON_31216_INDEX {payload.PYTHON_31216_INDEX!r}"
        )
    computed_manifest_digest = "sha256:" + hashlib.sha256(retained_manifest_bytes).hexdigest()
    if computed_manifest_digest != payload.PYTHON_31216_ARM64_MANIFEST or manifest_digest != computed_manifest_digest:
        raise Python31216ProofError(
            f"arm64 manifest digest {manifest_digest!r} / retained {computed_manifest_digest!r} "
            f"does not match {payload.PYTHON_31216_ARM64_MANIFEST!r}"
        )
    if config_digest in (HISTORICAL_31215_ARM64_CONFIG, "") or config_digest != payload.PYTHON_31216_ARM64_CONFIG:
        raise Python31216ProofError(
            f"arm64 config digest {config_digest!r} does not match {payload.PYTHON_31216_ARM64_CONFIG!r}"
        )
    if len({index_digest, manifest_digest, config_digest}) != 3:
        raise Python31216ProofError("index, platform manifest, and config digests must be distinct")
    if image_id == manifest_digest or image_id == index_digest:
        raise Python31216ProofError(
            f"image_id {image_id!r} must be the OCI config digest, never the manifest or index digest"
        )
    if image_id != config_digest:
        raise Python31216ProofError(f"local base image_id {image_id!r} does not match config_digest {config_digest!r}")
    manifest_doc = json.loads(retained_manifest_bytes.decode("utf-8"))
    if manifest_doc.get("config", {}).get("digest") != image_id:
        raise Python31216ProofError("retained arm64 manifest config descriptor does not match observed image_id")
    layer_digests = tuple(str(layer.get("digest") or "") for layer in (manifest_doc.get("layers") or ()))
    if layer_digests != EXPECTED_ARM64_LAYER_DIGESTS:
        raise Python31216ProofError(f"retained arm64 manifest layer digests drifted: {layer_digests!r}")
    if rootfs_layers is not None and tuple(str(x) for x in rootfs_layers) != EXPECTED_ARM64_DIFF_IDS:
        raise Python31216ProofError(
            f"observed RootFS.Layers {list(rootfs_layers)!r} != {list(EXPECTED_ARM64_DIFF_IDS)!r}")
    if not any(str(item).endswith(f"@{index_digest}") for item in repo_digests):
        raise Python31216ProofError(f"RepoDigests {list(repo_digests)!r} lacks pinned index digest {index_digest!r}")
    normalized_image_arch = normalize_daemon_arch(image_arch)
    if str(image_os).strip().lower() != "linux" or normalized_image_arch != "arm64":
        raise Python31216ProofError(f"local base platform is {image_os}/{image_arch}, expected linux/arm64")
    return {
        "daemon_arch": normalized_daemon, "platform": "linux/arm64", "reference": reference,
        "index_digest": index_digest, "manifest_digest": computed_manifest_digest,
        "manifest_digest_source": "retained_manifest_bytes_and_config_descriptor",
        "retained_manifest_verified": True, "config_digest": config_digest, "image_id": image_id,
        "config_digest_verified": True, "rootfs_diff_ids_verified": rootfs_layers is not None,
        "manifest_registry_observed": False, "pulled_by_test_image_manager": False,
        "phase_pull_accounting": "The parent separately accounts for canonical harness pulls before pytest.",
    }


def validate_zero_docker_operations(
    projection: Mapping[str, Any], *, baseline: Mapping[str, Any] | None = None,
) -> dict[str, int]:
    """Require zero operations, or no count changes from an explicitly observed run-wide baseline."""
    for observed in (projection,) if baseline is None else (baseline, projection):
        if missing := sorted(set(DERIVED_OPERATION_FIELDS) - set(observed)):
            raise Python31216ProofError(f"Docker boundary projection lacks operation fields: {missing}")
        for field, value in observed.items():
            if type(value) is not int or value < 0:
                raise Python31216ProofError(f"Docker boundary count {field}={value!r} is not a non-negative integer")
    if baseline is not None and projection.keys() != baseline.keys():
        raise Python31216ProofError("Docker boundary fields changed during the component proof")
    counts = {str(field): int(value) for field, value in sorted(projection.items())}
    if nonzero := {field: value - (baseline[field] if baseline is not None else 0)
                   for field, value in counts.items() if value != (baseline[field] if baseline is not None else 0)}:
        raise Python31216ProofError(f"raw component proof requires zero Docker build/pull operations: {nonzero}")
    return counts


def raw_observation_lines(stdout: str) -> list[str]:
    """Inner raw observations, re-prefixed for host stdout before any assertion or cleanup check can fail."""
    return [RAW_OBSERVATION_STDOUT_PREFIX + line.removeprefix(INNER_RAW_STDOUT_PREFIX)
            for line in stdout.splitlines() if line.startswith(INNER_RAW_STDOUT_PREFIX)]


def validate_runtime_cache_cap(
    *, selected_image_id: str, runtime_cache_ids: Sequence[str], ephemeral_ids: Sequence[str] = (),
    operation_counts: Mapping[str, int] | None = None, manager_outcome: str | None = None,
    materialization_recorded: bool = False,
) -> dict[str, Any]:
    """Dependency-only runtime cache cap; for the pending offline cache qualification, not the raw proof."""
    cache_list = [str(item) for item in runtime_cache_ids]
    if len(cache_list) != 1 or cache_list[0] != selected_image_id:
        raise Python31216ProofError(
            f"expected exactly 1 dependency-only runtime cache image matching {selected_image_id!r}, got {cache_list!r}"
        )
    if list(ephemeral_ids):
        raise Python31216ProofError(f"unexpected ephemeral test images present: {list(ephemeral_ids)!r}")
    build_count = 0
    if operation_counts is not None:
        build_count = int(operation_counts.get("managed_test_runtime_image_build_count", 0))
        if build_count > 1:
            raise Python31216ProofError(f"managed_test_runtime_image_build_count {build_count} exceeds cap 1")
        for zero_field in (
            "managed_system_candidate_image_build_count", "product_or_build_profile_build_count",
            "unmanaged_build_count", "unmanaged_pull_count",
        ):
            if int(operation_counts.get(zero_field, 0)) != 0:
                raise Python31216ProofError(
                    f"forbidden Docker operation count {zero_field}={operation_counts[zero_field]}")
    return {
        "selected_image_id": selected_image_id, "runtime_cache_count": len(cache_list), "runtime_cache_cap": 1,
        "ephemeral_count": 0, "managed_runtime_cache_build_count": build_count,
        "manager_outcome": manager_outcome, "materialization_recorded": bool(materialization_recorded),
    }


def validate_container_cleanup(
    *, container_id: str, cleanup_result: str, final_presence: str, engine_absent: bool, baseline_verified: bool,
) -> dict[str, Any]:
    """Validate observed ledger and Engine cleanup state for the probe container."""
    if (not container_id or cleanup_result != "removed" or final_presence != "absent"
            or not engine_absent or not baseline_verified):
        raise Python31216ProofError(
            f"container cleanup incomplete: id={container_id!r} result={cleanup_result!r} "
            f"presence={final_presence!r} engine_absent={engine_absent} baseline_verified={baseline_verified}"
        )
    return {
        "container_id": container_id, "cleanup_result": cleanup_result, "final_presence": final_presence,
        "owned_containers_removed": True, "baseline_verified": True,
    }


def build_native_arm64_exclusion_from_observation(raw_report: Mapping[str, Any]) -> payload.PayloadExclusion:
    """Validate a raw ``--no-exclusion`` observation report and build the 3.12.16 ARM64 exclusion."""
    if raw_report.get("schema") != payload.SCHEMA:
        raise Python31216ProofError(f"unexpected payload schema: {raw_report.get('schema')!r}")
    if raw_report.get("architecture") != "arm64":
        raise Python31216ProofError(
            f"raw observation architecture must be 'arm64', got {raw_report.get('architecture')!r}")
    if raw_report.get("result") != "refused" or raw_report.get("exclusion") is not None:
        raise Python31216ProofError("raw --no-exclusion observation must refuse with exclusion=None")
    reasons = raw_report.get("reasons")
    if not isinstance(reasons, list) or not reasons or "no frozen exclusion applies" not in str(reasons[0]):
        raise Python31216ProofError(f"raw --no-exclusion refusal reason missing expected diagnostic: {reasons!r}")
    baseline = raw_report.get("baseline")
    if not isinstance(baseline, Mapping):
        raise Python31216ProofError("raw observation report is missing baseline mapping")
    if baseline.get("machine") != "aarch64":
        raise Python31216ProofError(f"raw observation machine must be 'aarch64', got {baseline.get('machine')!r}")
    if baseline.get("dynload_real") != payload.DYNLOAD:
        raise Python31216ProofError(f"unexpected dynload_real: {baseline.get('dynload_real')!r}")
    elves = baseline.get("elves")
    if not isinstance(elves, Mapping) or ARM64_TKINTER_PATH not in elves:
        raise Python31216ProofError("raw observation elves missing _tkinter shared object")
    tk_elf = elves[ARM64_TKINTER_PATH]
    if not isinstance(tk_elf, Mapping):
        raise Python31216ProofError("malformed _tkinter ELF entry")
    if (
        tk_elf.get("sha256") != ARM64_TKINTER_SHA256
        or tk_elf.get("size") != ARM64_TKINTER_SIZE
        or tk_elf.get("elf") != [2, 1, ARM64_TKINTER_ELF_MACHINE]
    ):
        raise Python31216ProofError(f"_tkinter ELF metadata drifted: {tk_elf!r}")
    lost = payload.unresolved(elves)
    expected_lost = [f"{ARM64_TKINTER_PATH}: {lib} => not found" for lib in ARM64_TKINTER_MISSING]
    if sorted(lost) != expected_lost:
        raise Python31216ProofError(f"unexpected unresolved ELF dependencies: {lost!r}")
    failed = baseline.get("failed")
    if not isinstance(failed, Mapping) or list(failed.keys()) != ["_tkinter"]:
        raise Python31216ProofError(f"raw observation failed modules must be only ['_tkinter'], got {failed!r}")
    imports = baseline.get("imports")
    if not isinstance(imports, list) or len(imports) < 70 or imports != sorted(set(imports)):
        raise Python31216ProofError(f"raw observation imports list invalid or too short: {imports!r}")
    dynload_mods = payload.lib_dynload_modules(baseline)
    if set(imports) != set(dynload_mods) - {"_tkinter"}:
        raise Python31216ProofError(f"raw observation imports disagree with lib-dynload modules: {dynload_mods!r}")
    return payload.build_31216_exclusion("arm64", tuple(str(name) for name in imports))


def validate_trimmed_arm64_proof_report(
    *, raw_report: Mapping[str, Any], trimmed_report: Mapping[str, Any],
    entry_delta: int, modified_survivors: Sequence[str],
) -> dict[str, Any]:
    """Validate the trimmed Python 3.12.16 ARM64 report against the raw observation."""
    expected_entry = build_native_arm64_exclusion_from_observation(raw_report)
    if trimmed_report.get("schema") != payload.SCHEMA or trimmed_report.get("architecture") != "arm64":
        raise Python31216ProofError("trimmed report schema or architecture mismatch")
    if trimmed_report.get("result") != "trimmed" or trimmed_report.get("reasons") != []:
        raise Python31216ProofError(f"trimmed report did not succeed cleanly: {trimmed_report.get('reasons')!r}")
    if entry_delta != -1:
        raise Python31216ProofError(f"expected /usr/local entry count delta -1, got {entry_delta}")
    if list(modified_survivors):
        raise Python31216ProofError(f"surviving /usr/local entries drifted: {list(modified_survivors)[:10]!r}")
    exclusion = trimmed_report.get("exclusion")
    expected_excl = {
        **expected_entry._asdict(), "missing": list(expected_entry.missing),
        "baseline_imports": len(expected_entry.baseline_imports),
        "reason": "unusable Tk bridge: Tcl/Tk libraries are absent from the base",
    }
    if exclusion != expected_excl:
        raise Python31216ProofError(f"trimmed exclusion mismatch: {exclusion!r} != {expected_excl!r}")
    retained = trimmed_report.get("retained")
    if not isinstance(retained, Mapping):
        raise Python31216ProofError("trimmed report missing retained mapping")
    raw_baseline = raw_report["baseline"]
    if retained.get("entries") != int(raw_baseline["entries"]) - 1:
        raise Python31216ProofError(
            f"retained entry count {retained.get('entries')} != raw {raw_baseline['entries']} - 1"
        )
    if retained.get("digest") != retained.get("expected_digest"):
        raise Python31216ProofError("retained digest disagrees with expected_digest")
    if retained.get("digest") == raw_baseline.get("digest"):
        raise Python31216ProofError("retained digest did not change after removing _tkinter")
    if (retained.get("excluded_absent") is not True or retained.get("preserved") is not True
            or retained.get("unresolved") != []):
        raise Python31216ProofError(f"retained payload flags invalid: {retained!r}")
    if (
        retained.get("imports") != list(expected_entry.baseline_imports)
        or retained.get("lib_dynload") != list(expected_entry.baseline_imports)
    ):
        raise Python31216ProofError("retained imports or lib_dynload modules differ from observed baseline")
    owners = retained.get("owners")
    if not isinstance(owners, Mapping) or not owners or any(not str(val).strip() for val in owners.values()):
        raise Python31216ProofError(f"retained shared-library ownership incomplete: {owners!r}")
    matches_predicted = tuple(expected_entry.baseline_imports) == ARM64_31216_PREDICTED_IMPORTS_AWAITING_NATIVE_PROOF
    return {
        "before_entries": int(raw_baseline["entries"]), "after_entries": int(retained["entries"]),
        "entry_delta": entry_delta, "before_digest": str(raw_baseline["digest"]),
        "after_digest": str(retained["digest"]), "expected_digest": str(retained["expected_digest"]),
        "elf_count": int(retained["elf_count"]), "excluded_path": expected_entry.path,
        "excluded_sha256": expected_entry.sha256, "excluded_size": expected_entry.size,
        "excluded_elf_machine": expected_entry.elf_machine, "excluded_missing": list(expected_entry.missing),
        "baseline_imports": list(expected_entry.baseline_imports),
        "baseline_import_count": len(expected_entry.baseline_imports),
        "matches_predicted_arm64_imports": matches_predicted,
        "excluded_absent": True, "preserved": True, "unresolved": [], "owners": dict(owners),
    }


def build_inner_probe_script(payload_source_bytes: bytes) -> str:
    """Build the stdlib-only inner container script that prints raw observation before assertions."""
    return (
        "import contextlib, io, json, pathlib, subprocess, sys, types\n"
        f"_PAYLOAD_BYTES = {payload_source_bytes!r}\n"
        "assert sys.dont_write_bytecode and sys.flags.isolated == 1\n"
        f"assert sys.version.split()[0] == {EXPECTED_PYTHON_VERSION!r}, sys.version\n"
        "ver_out = subprocess.run([sys.executable, '-I', '-B', '--version'], "
        "capture_output=True, text=True, check=True).stdout.strip()\n"
        f"assert ver_out == {EXPECTED_PYTHON_BANNER!r}, ver_out\n"
        "mod = types.ModuleType('_repomap_py31216_payload')\n"
        "mod.__file__ = '<python_payload>'\n"
        "sys.modules[mod.__name__] = mod\n"
        "exec(compile(_PAYLOAD_BYTES, mod.__file__, 'exec'), mod.__dict__)\n"
        "mach = mod.platform.machine()\n"
        "assert mach == 'aarch64' and mod.NATIVE.get(mach) == 'arm64', mach\n"
        "before_map, _ = mod._walk(pathlib.Path('/'))\n"
        "buf_no = io.StringIO()\n"
        "with contextlib.redirect_stdout(buf_no):\n"
        "    rc_no = mod.main(['arm64', '--no-exclusion'])\n"
        "rep_no = json.loads(buf_no.getvalue().splitlines()[-1])\n"
        f"print({INNER_RAW_STDOUT_PREFIX!r} + json.dumps(rep_no, sort_keys=True), flush=True)\n"
        "obs_imports = tuple((rep_no.get('baseline') or {}).get('imports') or ())\n"
        "entry = mod.build_31216_exclusion('arm64', obs_imports)\n"
        "default_enrolled = ('arm64' in mod.PYTHON_PAYLOAD_EXCLUSIONS)\n"
        "excl_map = mod.PYTHON_PAYLOAD_EXCLUSIONS if default_enrolled else {'arm64': entry}\n"
        "buf_tr = io.StringIO()\n"
        "with contextlib.redirect_stdout(buf_tr):\n"
        "    rc_tr = mod.main(['arm64'], exclusions=excl_map)\n"
        "rep_tr = json.loads(buf_tr.getvalue().splitlines()[-1])\n"
        "after_map, _ = mod._walk(pathlib.Path('/'))\n"
        "entry_delta = len(after_map) - len(before_map)\n"
        "modified = sorted(p for p in after_map if before_map.get(p) != after_map.get(p))\n"
        f"print({INNER_STDOUT_PREFIX!r} + json.dumps({{\n"
        "    'python_version': sys.version.split()[0], 'python_banner': ver_out,\n"
        "    'default_enrolled': default_enrolled, 'entry_delta': entry_delta,\n"
        "    'modified_survivors': modified, 'raw_report': rep_no, 'trimmed_report': rep_tr,\n"
        "}, sort_keys=True), flush=True)\n"
        "assert rc_no == 1 and rep_no['result'] == 'refused', rep_no.get('reasons')\n"
        "if default_enrolled:\n"
        "    assert mod.PYTHON_PAYLOAD_EXCLUSIONS['arm64'] == entry\n"
        "assert rc_tr == 0 and rep_tr['result'] == 'trimmed', rep_tr.get('reasons')\n"
    )


def build_native_proof_record(
    *, provenance: Mapping[str, Any], operations_before: Mapping[str, Any], operations_after: Mapping[str, Any],
    trimmed_summary: Mapping[str, Any], default_enrolled: bool, cleanup_details: Mapping[str, Any],
) -> dict[str, Any]:
    """Assemble the compact ADR 0100 raw native ARM64 component proof record from observed values."""
    if (cleanup_details.get("owned_containers_removed") is not True
            or cleanup_details.get("baseline_verified") is not True):
        raise Python31216ProofError(f"container cleanup not verified: {cleanup_details!r}")
    before = validate_zero_docker_operations(operations_before, baseline=operations_before)
    after = validate_zero_docker_operations(operations_after, baseline=operations_before)
    amd64_enrolled = isinstance(payload.PYTHON_PAYLOAD_EXCLUSIONS.get("amd64"), payload.PayloadExclusion)  # ADR 0103
    return {
        "schema": PROOF_SCHEMA, "scope": "raw_native_arm64_component_proof", "python_version": EXPECTED_PYTHON_VERSION,
        "daemon_arch": provenance["daemon_arch"], "platform": provenance["platform"],
        "amd64_qualified": False, "amd64_default_enrolled": amd64_enrolled,
        "default_arm64_enrolled": bool(default_enrolled),
        "matches_predicted_arm64_imports": bool(trimmed_summary.get("matches_predicted_arm64_imports")),
        "oci_provenance": dict(provenance), "docker_operations": {"before_probe": before, "after_probe": after},
        "dependency_runtime_cache": {"qualification": "unexecuted", "reason": DEPENDENCY_CACHE_UNEXECUTED_REASON},
        "runtime_acceptance_claimed": False, "payload_proof": dict(trimmed_summary), "cleanup": dict(cleanup_details),
    }

def format_native_proof_stdout(record: Mapping[str, Any]) -> str:
    """Format the proof record as a single compact JSON stdout line."""
    return PROOF_STDOUT_PREFIX + json.dumps(record, sort_keys=True, separators=(",", ":"))

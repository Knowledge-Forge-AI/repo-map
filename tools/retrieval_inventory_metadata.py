"""Stdlib-only bounded metadata transport and manifest classifier for immutable A/B inventory."""

from __future__ import annotations

import argparse
import datetime
import errno
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
from typing import Any, Sequence

_TOOLS_DIR = str(Path(__file__).resolve().parent)
if _TOOLS_DIR not in sys.path:
    sys.path.insert(0, _TOOLS_DIR)

from _retrieval_inventory_transport import (
    IDENTITY_BYTE_CAP, LIVE_API_ORIGIN, LIVE_TIMEOUT_SECONDS, PRIVATE_TEXT_RE, REQUEST_HEADERS,
    ROSTER, SAFE_REASON_RE, SHA1_HEX_RE, TREE_BYTE_CAP, TREE_ENTRY_CAP, CandidateSpec,
    InventoryError, TransportExchange, _TestTransportSeam, fetch_endpoint_json,
    parse_strict_json_object, read_bounded_response, require,
)

SCHEMA_VERSION = "repomap-retrieval-inventory-metadata-v1"
VALID_MODE_TYPES: dict[str, str] = {
    "100644": "blob", "100755": "blob", "040000": "tree", "120000": "blob", "160000": "commit",
}
FORBIDDEN_IDENTITY_KEYS: frozenset[str] = frozenset(
    {"author", "committer", "tagger", "verification", "signature", "payload", "message", "raw", "body"}
)
__all__ = [
    "IDENTITY_BYTE_CAP", "LIVE_API_ORIGIN", "LIVE_TIMEOUT_SECONDS", "ROSTER", "SCHEMA_VERSION",
    "TREE_BYTE_CAP", "TREE_ENTRY_CAP", "CandidateSpec", "InventoryError", "TransportExchange",
    "_TestTransportSeam", "build_dry_plan", "execute_candidate_inventory", "main",
    "parse_strict_json_object", "read_bounded_response", "sanitize_identity_payload",
    "validate_and_classify_tree",
]


def _admission_flags() -> dict[str, bool]:
    return {
        "corpus_admitted": False, "labels_collected": False, "learned_utility_measured": False,
        "production_pgvector_admitted": False, "rights_cleared": False,
        "independent_cryptographic_authentication": False,
    }


def _candidate_binding_dict(spec: CandidateSpec) -> dict[str, Any]:
    return {
        "candidate": spec.candidate, "repository": spec.repository, "tag": spec.tag, "ref": spec.ref,
        "annotated_tag_sha": spec.annotated_tag_sha, "commit_sha": spec.commit_sha,
        "tree_sha": spec.tree_sha, "package_root": spec.package_root,
        "origin_review_paths": list(spec.origin_review_paths),
        "origin_review_concern": spec.origin_review_concern,
        "endpoints": spec.endpoints(LIVE_API_ORIGIN),
    }


def _transport_contract_dict() -> dict[str, Any]:
    return {
        "live_api_origin": LIVE_API_ORIGIN, "method": "GET", "authenticated": False,
        "redirects_allowed": False, "retries_allowed": False, "accept_encoding": "identity",
        "timeout_seconds": LIVE_TIMEOUT_SECONDS, "identity_byte_cap": IDENTITY_BYTE_CAP,
        "tree_byte_cap": TREE_BYTE_CAP, "tree_entry_cap": TREE_ENTRY_CAP,
        "max_recursive_tree_requests_per_candidate": 1, "per_entry_requests_allowed": False,
        "read_accounting_layer": "http_response_application_read",
        "request_headers": dict(REQUEST_HEADERS),
    }


def build_dry_plan(candidate: str | None = None) -> dict[str, Any]:
    """Build zero-network dry plan for the immutable A/B roster or one selected candidate."""
    if candidate is not None:
        require(candidate in ROSTER, "invalid_candidate")
        selected = [ROSTER[candidate]]
    else:
        selected = [ROSTER["A"], ROSTER["B"]]
    return {
        "schema_version": SCHEMA_VERSION, "mode": "dry_plan", "status": "planned",
        "network_operations_performed": 0,
        "selected_candidates": [_candidate_binding_dict(spec) for spec in selected],
        "transport_contract": _transport_contract_dict(), **_admission_flags(),
    }


def _validate_safe_relpath(path: Any) -> str:
    require(isinstance(path, str) and 1 <= len(path) <= 1024, "unsafe_tree_path")
    require(
        not path.startswith("/") and not path.endswith("/") and "\\" not in path
        and "\x00" not in path and not any(ord(c) < 32 for c in path),
        "unsafe_tree_path",
    )
    require(all(part and part not in (".", "..") for part in path.split("/")), "unsafe_tree_path")
    return path


def sanitize_identity_payload(
    spec: CandidateSpec, step: str, payload: dict[str, Any], *,
    raw_bytes: int, raw_sha256: str, request_utc: str,
) -> dict[str, Any]:
    """Verify exact identity bindings and strip names, contacts, signatures, messages, and raw bodies."""
    base = {
        "step": step, "endpoint": spec.endpoints(LIVE_API_ORIGIN)[step],
        "request_utc": request_utc, "raw_byte_count": raw_bytes, "raw_sha256": raw_sha256,
        "verified": True, "independent_cryptographic_authentication": False,
    }
    if step == "ref":
        obj = payload.get("object")
        require(
            payload.get("ref") == spec.ref and isinstance(obj, dict)
            and obj.get("type") == "tag" and obj.get("sha") == spec.annotated_tag_sha,
            "identity_drift_ref",
        )
        return {**base, "ref": spec.ref, "target_type": "tag", "annotated_tag_sha": spec.annotated_tag_sha}
    if step == "tag":
        obj = payload.get("object")
        require(
            payload.get("sha") == spec.annotated_tag_sha and payload.get("tag") == spec.tag
            and isinstance(obj, dict) and obj.get("type") == "commit" and obj.get("sha") == spec.commit_sha,
            "identity_drift_tag",
        )
        return {
            **base, "tag": spec.tag, "annotated_tag_sha": spec.annotated_tag_sha,
            "target_type": "commit", "commit_sha": spec.commit_sha,
        }
    if step == "commit":
        tree_obj, parents = payload.get("tree"), payload.get("parents")
        if not (
            payload.get("sha") == spec.commit_sha and isinstance(tree_obj, dict)
            and tree_obj.get("sha") == spec.tree_sha and isinstance(parents, list)
        ):
            raise InventoryError("identity_drift_commit")
        parent_shas: list[str] = []
        for parent in parents:
            require(
                isinstance(parent, dict) and isinstance(parent.get("sha"), str)
                and SHA1_HEX_RE.fullmatch(parent["sha"]) is not None,
                "identity_drift_commit",
            )
            parent_shas.append(parent["sha"])
        return {**base, "commit_sha": spec.commit_sha, "tree_sha": spec.tree_sha, "parent_shas": parent_shas}
    raise InventoryError("invalid_identity_step")


def validate_and_classify_tree(
    spec: CandidateSpec, payload: dict[str, Any], *, raw_bytes: int, raw_sha256: str,
    request_utc: str, byte_cap: int = TREE_BYTE_CAP, entry_cap: int = TREE_ENTRY_CAP,
) -> dict[str, Any]:
    """Validate complete recursive tree payload and classify manifest and layout/review buckets."""
    require(payload.get("sha") == spec.tree_sha, "tree_sha_mismatch")
    require("truncated" in payload and type(payload["truncated"]) is bool, "invalid_truncated_flag")
    require(payload["truncated"] is False, "tree_truncated")
    raw_tree = payload.get("tree")
    if not isinstance(raw_tree, list):
        raise InventoryError("invalid_tree_field")
    require(len(raw_tree) <= entry_cap, "tree_entry_cap_exceeded")

    seen_paths: set[str] = set()
    manifest: list[dict[str, Any]] = []
    layout_buckets: dict[str, list[str]] = {
        "package_source_tree": [], "tests_tree": [], "docs_tree": [],
        "github_workflows_or_config": [], "repository_root_files": [], "other_paths": [],
    }
    review_buckets: dict[str, Any] = {
        "path_candidates_only": [], "origin_review_required": [],
        "ineligible_symlinks": [], "ineligible_gitlinks": [], "excluded_trees": [],
        "excluded_non_python_package_blobs": [], "excluded_outside_package_blobs": [],
    }
    pkg_prefix = f"{spec.package_root}/"

    for entry in raw_tree:
        require(isinstance(entry, dict), "invalid_tree_entry")
        path = _validate_safe_relpath(entry.get("path"))
        require(path not in seen_paths, "duplicate_tree_path")
        seen_paths.add(path)

        mode, obj_type = entry.get("mode"), entry.get("type")
        require(isinstance(mode, str) and isinstance(obj_type, str) and VALID_MODE_TYPES.get(mode) == obj_type, "invalid_tree_mode_or_type")
        sha = entry.get("sha")
        require(isinstance(sha, str) and SHA1_HEX_RE.fullmatch(sha) is not None, "invalid_entry_sha")
        size = entry.get("size")
        require((type(size) is int and 0 <= size <= 104_857_600) if obj_type == "blob" else size is None, "invalid_entry_size")

        if path == spec.package_root or path.startswith(pkg_prefix):
            layout_buckets["package_source_tree"].append(path)
        elif path == "tests" or path.startswith("tests/"):
            layout_buckets["tests_tree"].append(path)
        elif path == "docs" or path.startswith("docs/"):
            layout_buckets["docs_tree"].append(path)
        elif path == ".github" or path.startswith(".github/"):
            layout_buckets["github_workflows_or_config"].append(path)
        elif "/" not in path and obj_type != "tree":
            layout_buckets["repository_root_files"].append(path)
        else:
            layout_buckets["other_paths"].append(path)

        in_pkg = path.startswith(pkg_prefix)
        origin_flag = path in spec.origin_review_paths and mode in ("100644", "100755")
        if mode == "120000":
            classification, eligible, bucket_key = "ineligible_symlink", False, "ineligible_symlinks"
        elif mode == "160000":
            classification, eligible, bucket_key = "ineligible_gitlink", False, "ineligible_gitlinks"
        elif mode == "040000":
            classification, eligible, bucket_key = "directory_tree", False, "excluded_trees"
        elif origin_flag:
            classification, eligible, bucket_key = "origin_review_hold", False, "origin_review_required"
        elif in_pkg and path.endswith(".py"):
            classification, eligible, bucket_key = "path_candidate_only", True, "path_candidates_only"
        elif in_pkg:
            classification, eligible, bucket_key = "excluded_non_python_package_blob", False, "excluded_non_python_package_blobs"
        else:
            classification, eligible, bucket_key = "excluded_outside_package_blob", False, "excluded_outside_package_blobs"
        if origin_flag:
            review_buckets["origin_review_required"].append({
                "path": path, "concern": spec.origin_review_concern,
                "held_from_eligibility": True, "content_interpreted": False,
            })
        else:
            review_buckets[bucket_key].append(path)
        manifest.append({
            "path": path, "mode": mode, "type": obj_type, "sha": sha, "object_id": sha,
            "size": size, "classification": classification, "eligible_path_candidate": eligible,
            "rights_cleared": False, "followed": False, "origin_review_required": origin_flag,
            "origin_review_concern": spec.origin_review_concern if origin_flag else None,
        })

    manifest_bytes = json.dumps(manifest, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return {
        "endpoint": spec.endpoints(LIVE_API_ORIGIN)["tree"], "request_utc": request_utc,
        "tree_sha": spec.tree_sha, "truncated": False, "complete": True,
        "raw_byte_count": raw_bytes, "raw_sha256": raw_sha256, "entry_count": len(manifest),
        "byte_cap": byte_cap, "entry_cap": entry_cap, "per_entry_urls_requested": 0,
        "manifest_sha256": "sha256:" + hashlib.sha256(manifest_bytes).hexdigest(),
        "manifest": manifest, "directory_layout_buckets": layout_buckets,
        "exclusion_and_review_buckets": review_buckets,
        "bucket_counts": {"total_entries": len(manifest), **{k: len(v) for k, v in review_buckets.items()}},
    }


def _check_exclusive_target(raw_path: str, *, exists_reason: str) -> Path:
    require(isinstance(raw_path, str) and bool(raw_path.strip()) and "\x00" not in raw_path and not raw_path.endswith(("/", "\\")), "invalid_output_path")
    abs_target = Path(os.path.abspath(Path(raw_path)))
    try:
        st: os.stat_result | None = os.lstat(abs_target)
    except FileNotFoundError:
        st = None
    except OSError:
        raise InventoryError("invalid_output_path") from None
    if st is not None:
        require(not stat.S_ISLNK(st.st_mode), "unsafe_output_symlink")
        require(stat.S_ISREG(st.st_mode), "unsafe_output_nonregular")
        raise InventoryError(exists_reason)
    parent = abs_target.parent
    try:
        parent_st = os.lstat(parent)
    except FileNotFoundError:
        raise InventoryError("output_parent_missing") from None
    except OSError:
        raise InventoryError("invalid_output_path") from None
    require(not stat.S_ISLNK(parent_st.st_mode), "unsafe_output_symlink")
    require(stat.S_ISDIR(parent_st.st_mode), "unsafe_output_nonregular")
    for anc in (parent, *parent.parents):
        try:
            anc_st = os.lstat(anc)
        except OSError:
            raise InventoryError("invalid_output_path") from None
        require(not stat.S_ISLNK(anc_st.st_mode), "unsafe_output_symlink")
    return abs_target


def _write_exclusive_json(target: Path, payload: dict[str, Any], *, exists_reason: str) -> None:
    serialized = json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n"
    require(PRIVATE_TEXT_RE.search(serialized) is None, "private_data_refused")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(str(target), flags, 0o600)
    except FileExistsError:
        raise InventoryError(exists_reason) from None
    except OSError as err:
        raise InventoryError("unsafe_output_symlink" if err.errno == errno.ELOOP else "output_write_refused") from None
    try:
        require(stat.S_ISREG(os.fstat(fd).st_mode), "unsafe_output_nonregular")
        data = serialized.encode("utf-8")
        total = 0
        while total < len(data):
            written = os.write(fd, data[total:])
            require(written > 0, "output_write_refused")
            total += written
    finally:
        os.close(fd)


def execute_candidate_inventory(
    candidate: str, *, output_path: str | Path, intent_path: str | Path | None = None,
    _seam: _TestTransportSeam | None = None, _telemetry_out: list[TransportExchange] | None = None,
) -> dict[str, Any]:
    """Execute one bounded metadata transport attempt for candidate A or B."""
    require(candidate in ROSTER, "invalid_candidate")
    spec, seam = ROSTER[candidate], (_seam or _TestTransportSeam()).validate()
    out_str = str(output_path)
    intent_str = str(intent_path) if intent_path is not None else f"{out_str}.intent.json"
    out_target = _check_exclusive_target(out_str, exists_reason="output_already_exists")
    intent_target = _check_exclusive_target(intent_str, exists_reason="intent_already_exists")
    require(out_target != intent_target, "invalid_output_path")
    intent_utc = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    _write_exclusive_json(intent_target, {
        "schema_version": SCHEMA_VERSION, "record_type": "execution_intent", "status": "intent_recorded",
        "intent_utc": intent_utc, "candidate_binding": _candidate_binding_dict(spec),
        "transport_contract": _transport_contract_dict(), **_admission_flags(),
    }, exists_reason="intent_already_exists")

    telemetry: list[TransportExchange] = _telemetry_out if _telemetry_out is not None else []
    identity_chain: dict[str, Any] = {}
    for step in ("ref", "tag", "commit"):
        payload, raw_len, raw_sha, req_utc = fetch_endpoint_json(spec, step, byte_cap=seam.identity_byte_cap, entry_cap=None, seam=seam, telemetry=telemetry)
        sanitized = sanitize_identity_payload(spec, step, payload, raw_bytes=raw_len, raw_sha256=raw_sha, request_utc=req_utc)
        require(not (FORBIDDEN_IDENTITY_KEYS & set(sanitized)), "identity_sanitization_violation")
        identity_chain[step] = sanitized

    tree_payload, tree_len, tree_sha256, tree_utc = fetch_endpoint_json(spec, "tree", byte_cap=seam.tree_byte_cap, entry_cap=seam.tree_entry_cap, seam=seam, telemetry=telemetry)
    tree_record = validate_and_classify_tree(
        spec, tree_payload, raw_bytes=tree_len, raw_sha256=tree_sha256, request_utc=tree_utc,
        byte_cap=seam.tree_byte_cap, entry_cap=seam.tree_entry_cap,
    )
    result: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION, "mode": "execute", "status": "verified", "candidate": spec.candidate,
        "candidate_binding": _candidate_binding_dict(spec), "transport_contract": _transport_contract_dict(),
        "identity_verification": {
            "verified": True, "independent_cryptographic_authentication": False,
            "sanitized_on_receipt": True, "retained_forbidden_identity_fields": [], "steps": identity_chain,
        },
        "tree_inventory": tree_record, "transport_telemetry": [ex.to_public_dict() for ex in telemetry],
        **_admission_flags(),
    }
    _write_exclusive_json(out_target, result, exists_reason="output_already_exists")
    return result


def _parse_cli_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="retrieval_inventory_metadata.py")
    parser.add_argument("--candidate", help="Select immutable candidate A or B.")
    parser.add_argument("--execute", action="store_true", help="Execute one live metadata retrieval attempt.")
    parser.add_argument("--output", help="Exclusive output JSON file path (required with --execute).")
    parser.add_argument("--intent", help="Optional exclusive intent JSON file path (only with --execute).")
    try:
        ns, extras = parser.parse_known_args(list(argv))
    except SystemExit as exc:
        if exc.code == 0:
            raise
        raise InventoryError("invalid_cli_arguments") from None
    require(not extras, "invalid_cli_arguments")
    return ns


def main(argv: Sequence[str] | None = None, *, _seam: _TestTransportSeam | None = None) -> int:
    """CLI entrypoint; dry plan is default with zero network operations."""
    args = list(sys.argv[1:] if argv is None else argv)
    telemetry: list[TransportExchange] = []
    try:
        ns = _parse_cli_args(args)
        if not ns.execute:
            require(ns.output is None and ns.intent is None, "output_requires_execute")
            sys.stdout.write(json.dumps(build_dry_plan(ns.candidate), ensure_ascii=True, indent=2, sort_keys=True) + "\n")
            return 0
        require(ns.candidate in ROSTER, "invalid_candidate")
        require(isinstance(ns.output, str) and bool(ns.output.strip()), "missing_output_path")
        res = execute_candidate_inventory(
            ns.candidate, output_path=ns.output, intent_path=ns.intent, _seam=_seam, _telemetry_out=telemetry
        )
        ti = res["tree_inventory"]
        summary = {
            "schema_version": SCHEMA_VERSION, "mode": "execute", "status": res["status"], "candidate": res["candidate"],
            "repository": res["candidate_binding"]["repository"], "tag": res["candidate_binding"]["tag"],
            "tree_sha": ti["tree_sha"], "entry_count": ti["entry_count"], "raw_tree_bytes": ti["raw_byte_count"],
            "raw_tree_sha256": ti["raw_sha256"], "manifest_sha256": ti["manifest_sha256"], **_admission_flags(),
        }
        sys.stdout.write(json.dumps(summary, ensure_ascii=True, indent=2, sort_keys=True) + "\n")
        return 0
    except InventoryError as err:
        reason = err.reason if SAFE_REASON_RE.fullmatch(err.reason) else "internal_refusal"
    except Exception:
        reason = "internal_refusal"
    refusal = {
        "schema_version": SCHEMA_VERSION, "status": "refused", "reason": reason,
        "transport_telemetry": [ex.to_public_dict() for ex in telemetry], **_admission_flags(),
    }
    sys.stderr.write(json.dumps(refusal, ensure_ascii=True, sort_keys=True) + "\n")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

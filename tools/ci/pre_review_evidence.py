"""Closed evidence-envelope support for the pre-review aggregate."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
import hashlib
import json
from pathlib import Path
import sys
from typing import Any, Iterable, Protocol

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ci.python_retention_evidence_schema import (
    INCOMPLETE_SCHEMA,
    VALID_SCHEMAS,
    validate_retention_evidence_schema,
)


LOG_CAP_BYTES = 200_000
AGGREGATE_CAP_BYTES = 5 * 1024 * 1024


class NamedCheck(Protocol):
    @property
    def name(self) -> str: ...


def bounded_log(text: str) -> str:
    encoded = text.encode("utf-8")
    if len(encoded) <= LOG_CAP_BYTES:
        return text
    suffix = b"\n[log truncated at bounded evidence cap]\n"
    return (encoded[: LOG_CAP_BYTES - len(suffix)] + suffix).decode(
        "utf-8", errors="ignore"
    )


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _expected_payloads(selected: Iterable[NamedCheck]) -> tuple[str, ...]:
    names = [check.name for check in selected]
    payloads = [f"{name}.log" for name in names]
    if "python-retention-inventory" in names:
        payloads.append("python-retention-inventory.result.json")
    payloads.append("results.json")
    return tuple(payloads)


def verify_evidence(evidence_dir: Path, selected: Iterable[NamedCheck]) -> None:
    expected_payloads = _expected_payloads(selected)
    expected_paths = set(expected_payloads) | {"manifest.json"}
    observed = {
        path.relative_to(evidence_dir).as_posix()
        for path in evidence_dir.rglob("*")
    }
    extra = sorted(observed - expected_paths)
    missing = sorted(expected_paths - observed)
    if extra:
        raise RuntimeError(f"unexpected evidence path: {extra[0]}")
    if missing:
        raise RuntimeError(f"missing evidence path: {missing[0]}")
    if any(not (evidence_dir / path).is_file() for path in expected_paths):
        raise RuntimeError("evidence artifact contains a non-file path")
    try:
        document = json.loads((evidence_dir / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError) as error:
        raise RuntimeError("evidence manifest is malformed") from error
    if not isinstance(document, dict) or document.get("schema") != "repomap-pre-review-manifest-v1":
        raise RuntimeError("evidence manifest schema is invalid")
    artifacts = document.get("artifacts")
    if not isinstance(artifacts, list):
        raise RuntimeError("evidence manifest artifact list is invalid")
    by_path = {
        item.get("path"): item
        for item in artifacts
        if isinstance(item, dict) and isinstance(item.get("path"), str)
    }
    if set(by_path) != set(expected_payloads) or len(by_path) != len(artifacts):
        raise RuntimeError("evidence manifest paths do not match the declared payloads")
    payload_size = 0
    results_doc: dict[str, Any] | None = None
    retention_doc: dict[str, Any] | None = None
    for relative in expected_payloads:
        path = evidence_dir / relative
        size = path.stat().st_size
        item = by_path[relative]
        if item.get("size_bytes") != size:
            raise RuntimeError(f"size mismatch for evidence path: {relative}")
        if item.get("sha256") != _digest(path):
            raise RuntimeError(f"digest mismatch for evidence path: {relative}")
        if relative.endswith(".log") and size > LOG_CAP_BYTES:
            raise RuntimeError(f"oversized evidence log: {relative}")
        if size > AGGREGATE_CAP_BYTES:
            raise RuntimeError(f"oversized evidence payload: {relative}")
        if relative.endswith(".json"):
            try:
                json_doc = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError, json.JSONDecodeError) as error:
                raise RuntimeError(f"malformed evidence payload: {relative}") from error
            if relative == "results.json":
                if not isinstance(json_doc, dict) or json_doc.get("schema") != "repomap-pre-review-result-v2":
                    raise RuntimeError(f"malformed evidence payload: {relative}")
                results_doc = json_doc
            elif relative == "python-retention-inventory.result.json":
                if not isinstance(json_doc, dict):
                    raise RuntimeError(f"malformed evidence payload: {relative}")
                ret_schema = json_doc.get("schema")
                if ret_schema not in VALID_SCHEMAS:
                    raise RuntimeError(
                        f"malformed evidence payload: {relative}: invalid retention schema {ret_schema!r}"
                    )
                try:
                    validate_retention_evidence_schema(json_doc)
                except Exception as error:
                    raise RuntimeError(f"malformed evidence payload: {relative}: {error}") from error
                retention_doc = json_doc
        payload_size += size
    if retention_doc is not None and results_doc is not None:
        ret_results = [
            r for r in results_doc.get("results", [])
            if isinstance(r, dict) and r.get("name") == "python-retention-inventory"
        ]
        if len(ret_results) != 1:
            raise RuntimeError("retention aggregate record must occur exactly once")
        if ret_results:
            env_status = ret_results[0].get("status")
            ret_status = retention_doc.get("status")
            if (env_status != ret_status or ret_results[0].get("classification") != retention_doc.get("classification")):
                raise RuntimeError(
                    f"retention status mismatch: results.json has {env_status!r} "
                    f"but python-retention-inventory.result.json has {ret_status!r}"
                )
            if retention_doc.get("schema") == INCOMPLETE_SCHEMA and env_status != "failed":
                raise RuntimeError(
                    "incomplete retention evidence cannot have passing status in results.json"
                )
    if document.get("payload_uncompressed_bytes") != payload_size:
        raise RuntimeError("evidence manifest aggregate size is invalid")
    aggregate_size = sum(
        (evidence_dir / relative).stat().st_size for relative in expected_paths
    )
    if aggregate_size > AGGREGATE_CAP_BYTES:
        raise RuntimeError("evidence artifact exceeds the aggregate size cap")


def finalize_evidence(
    evidence_dir: Path,
    selected: Iterable[NamedCheck],
    results: Iterable[object],
) -> int:
    """Seal and verify the envelope, returning its remaining byte capacity."""
    selected = tuple(selected)
    result_document = {
        "schema": "repomap-pre-review-result-v2",
        "results": [
            asdict(result) if is_dataclass(result) and not isinstance(result, type) else result
            for result in results
        ],
    }
    (evidence_dir / "results.json").write_text(
        json.dumps(result_document, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    artifacts = []
    payload_size = 0
    for relative in _expected_payloads(selected):
        path = evidence_dir / relative
        if not path.is_file():
            raise RuntimeError(f"missing evidence path: {relative}")
        size = path.stat().st_size
        payload_size += size
        artifacts.append(
            {
                "path": relative,
                "sha256": _digest(path),
                "size_bytes": size,
            }
        )
    manifest = {
        "schema": "repomap-pre-review-manifest-v1",
        "artifacts": artifacts,
        "payload_uncompressed_bytes": payload_size,
    }
    (evidence_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    verify_evidence(evidence_dir, selected)
    return AGGREGATE_CAP_BYTES - payload_size - (evidence_dir / "manifest.json").stat().st_size

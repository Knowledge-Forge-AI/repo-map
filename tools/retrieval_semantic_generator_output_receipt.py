"""Shared receipt types and bounded payload parsing for semantic generation."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
import hashlib
import io
import json
import math
import re
import stat
from typing import Literal, TypedDict, cast
import zipfile

from retrieval_semantic_generator_kernel import (
    MODEL_DIMENSIONS,
    QUERY_PREFIX,
    SemanticCost,
    SemanticEmbedding,
    SemanticGeneration,
    SemanticMode,
    SemanticText,
)
from retrieval_semantic_provenance import RepresentationValidationError

_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
_MAX_RECEIPT_BYTES = 32 * 1024 * 1024
_EMPTY_JOURNAL_SHA256 = "sha256:" + hashlib.sha256(b"").hexdigest()
_COST_FIELDS = frozenset(
    {
        "input_records",
        "input_bytes",
        "model_input_bytes",
        "token_count_before_limit",
        "token_count_used",
        "overflow_chunks",
        "truncated_records",
        "load_seconds",
        "inference_seconds",
        "total_seconds",
    }
)


class _CostPayload(TypedDict):
    input_records: int
    input_bytes: int
    model_input_bytes: int
    token_count_before_limit: int
    token_count_used: int
    overflow_chunks: int
    truncated_records: int
    load_seconds: float
    inference_seconds: float
    total_seconds: float


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise RepresentationValidationError(code, "generation output refused")


def _digest(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_json_key")
        result[key] = value
    return result


def _constant(_value: str) -> object:
    raise ValueError("nonfinite_json")


def _journal_object(raw: bytes, label: str) -> dict[str, object]:
    _require(
        type(raw) is bytes and 0 < len(raw) <= _MAX_RECEIPT_BYTES,
        "invalid_worker_" + label,
    )
    try:
        value = json.loads(raw, object_pairs_hook=_object, parse_constant=_constant)
        canonical = (
            json.dumps(
                value,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
                allow_nan=False,
            ).encode("ascii")
            + b"\n"
        )
    except (TypeError, UnicodeError, ValueError, json.JSONDecodeError, RecursionError) as exc:
        raise RepresentationValidationError(
            "invalid_worker_" + label, "worker receipt JSON refused"
        ) from exc
    _require(
        raw == canonical
        and isinstance(value, dict),
        "invalid_worker_" + label,
    )
    return value


def _digest_field(value: object, code: str) -> str:
    _require(type(value) is str and _DIGEST.fullmatch(value) is not None, code)
    assert isinstance(value, str)
    return value


@dataclass(frozen=True)
class QueryEmbedding:
    task_id: str
    task_sha256: str
    state: str
    reason: str | None
    vector: tuple[float, ...] | None


@dataclass(frozen=True)
class VerifiedWorkerResponse:
    """A response whose request, source archive, report and terminal agree."""

    attempt_id: str
    request_records: tuple[SemanticText, ...]
    request_sha256: str
    report_sha256: str
    terminal_sha256: str
    declaration_sha256: str
    source_manifest_sha256: str
    sources_archive_sha256: str
    source_closure_digests: tuple[tuple[str, str], ...]
    controller_admission_sha256: str
    input_identity: str
    representation_report_identity: str
    publication_identity: str
    artifact_profile_identity: str
    record_count: int
    embedding_count: int
    document_count: int
    query_count: int
    generation: SemanticGeneration | None
    status: str
    _sealed_identity: str = field(default="", repr=False, compare=False)


def _response_identity(response: VerifiedWorkerResponse) -> str:
    payload = (
        response.attempt_id,
        response.request_records,
        response.request_sha256,
        response.report_sha256,
        response.terminal_sha256,
        response.declaration_sha256,
        response.source_manifest_sha256,
        response.sources_archive_sha256,
        response.source_closure_digests,
        response.controller_admission_sha256,
        response.input_identity,
        response.representation_report_identity,
        response.publication_identity,
        response.artifact_profile_identity,
        response.record_count,
        response.embedding_count,
        response.document_count,
        response.query_count,
        response.generation,
        response.status,
    )
    return _digest(repr(payload).encode("utf-8"))


def _archive_files(raw: bytes) -> tuple[dict[str, bytes], dict[str, bytes]]:
    sources: dict[str, bytes] = {}
    inputs: dict[str, bytes] = {}
    _require(
        type(raw) is bytes and 0 < len(raw) <= _MAX_RECEIPT_BYTES,
        "invalid_worker_archive",
    )
    try:
        with zipfile.ZipFile(io.BytesIO(raw), "r") as archive:
            _require(not archive.comment, "invalid_worker_archive")
            infos = archive.infolist()
            _require(len(infos) <= 1024, "invalid_worker_archive")
            total_size = 0
            names: set[str] = set()
            for info in infos:
                name = info.filename
                _require(
                    not info.is_dir()
                    and "\\" not in name
                    and not any(part in {"", ".", ".."} for part in name.split("/")),
                    "invalid_worker_archive",
                )
                mode = (info.external_attr >> 16) & 0xFFFF
                file_type = mode & 0o170000
                _require(
                    name not in names
                    and (not file_type or stat.S_ISREG(file_type))
                    and (info.flag_bits & 0x1) == 0
                    and info.compress_type == zipfile.ZIP_STORED,
                    "invalid_worker_archive",
                )
                _require(
                    0 <= info.file_size <= _MAX_RECEIPT_BYTES - total_size,
                    "invalid_worker_archive",
                )
                names.add(name)
                total_size += info.file_size
            for info in infos:
                name = info.filename
                target, relative = name.split("/", 1) if "/" in name else ("", "")
                _require(
                    target in {"sources", "inputs"} and bool(relative),
                    "invalid_worker_archive",
                )
                with archive.open(info, "r") as stream:
                    data = stream.read(info.file_size + 1)
                _require(len(data) == info.file_size, "invalid_worker_archive")
                target_map = sources if target == "sources" else inputs
                _require(relative not in target_map, "invalid_worker_archive")
                target_map[relative] = data
    except (
        OSError,
        EOFError,
        RuntimeError,
        ValueError,
        KeyError,
        zipfile.BadZipFile,
        zipfile.LargeZipFile,
    ) as exc:
        if isinstance(exc, RepresentationValidationError):
            raise
        raise RepresentationValidationError(
            "invalid_worker_archive", "worker source archive refused"
        ) from exc
    return sources, inputs


def _parse_generation(
    report: Mapping[str, object],
    request_records: tuple[SemanticText, ...],
) -> SemanticGeneration:
    embeddings_raw = report["embeddings"]
    _require(
        isinstance(embeddings_raw, list)
        and len(embeddings_raw) == len(request_records)
        and len(embeddings_raw) <= 500,
        "invalid_worker_embeddings",
    )
    assert isinstance(embeddings_raw, list)
    embeddings: list[SemanticEmbedding] = []
    expected_keys = {
        "record_id",
        "mode",
        "vector",
        "token_count_before_limit",
        "token_count_used",
        "overflow_chunks",
        "truncated",
    }
    for raw in embeddings_raw:
        _require(
            isinstance(raw, dict) and set(raw) == expected_keys,
            "invalid_worker_embeddings",
        )
        mode = raw["mode"]
        _require(
            type(mode) is str and mode in {"document", "query"},
            "invalid_worker_embedding_mode",
        )
        vector = raw["vector"]
        _require(
            isinstance(vector, list) and len(vector) == MODEL_DIMENSIONS,
            "invalid_worker_embedding_vector",
        )
        values: list[float] = []
        for value in vector:
            _require(
                type(value) in (int, float)
                and not isinstance(value, bool)
                and math.isfinite(float(value)),
                "invalid_worker_embedding_vector",
            )
            values.append(float(value))
        for key in ("token_count_before_limit", "token_count_used", "overflow_chunks"):
            _require(type(raw[key]) is int, "invalid_worker_embedding_counts")
        _require(type(raw["truncated"]) is bool, "invalid_worker_embedding_counts")
        _require(
            raw["token_count_before_limit"] > 0
            and 1 <= raw["token_count_used"] <= 512
            and raw["token_count_used"]
            == min(raw["token_count_before_limit"], 512)
            and raw["overflow_chunks"] >= 0
            and raw["truncated"]
            == (raw["overflow_chunks"] > 0)
            == (raw["token_count_before_limit"] > 512),
            "invalid_worker_embedding_counts",
        )
        _require(type(raw["record_id"]) is str, "invalid_worker_embedding_identity")
        embeddings.append(
            SemanticEmbedding(
                raw["record_id"],
                SemanticMode(mode),
                tuple(values),
                raw["token_count_before_limit"],
                raw["token_count_used"],
                raw["overflow_chunks"],
                raw["truncated"],
            )
        )
    cost_raw = report["cost"]
    _require(isinstance(cost_raw, dict), "invalid_worker_cost")
    assert isinstance(cost_raw, dict)
    _require(
        set(cost_raw) == _COST_FIELDS,
        "invalid_worker_cost",
    )
    try:
        cost = SemanticCost(**cast(_CostPayload, cost_raw))
    except (TypeError, ValueError) as exc:
        raise RepresentationValidationError(
            "invalid_worker_cost", "worker cost refused"
        ) from exc
    _require(
        type(cost.input_records) is int
        and cost.input_records == len(request_records),
        "worker_cost_count_mismatch",
    )
    input_bytes = sum(
        len(item.record_id.encode("utf-8")) + len(item.text.encode("utf-8"))
        for item in request_records
    )
    model_bytes = sum(
        len(((QUERY_PREFIX if item.mode is SemanticMode.QUERY else "") + item.text).encode("utf-8"))
        for item in request_records
    )
    _require(
        type(cost.input_bytes) is int
        and type(cost.model_input_bytes) is int
        and cost.input_bytes == input_bytes
        and cost.model_input_bytes == model_bytes,
        "worker_cost_bytes_mismatch",
    )
    for name in (
        "input_bytes",
        "model_input_bytes",
        "token_count_before_limit",
        "token_count_used",
        "overflow_chunks",
        "truncated_records",
    ):
        _require(
            type(getattr(cost, name)) is int and getattr(cost, name) >= 0,
            "invalid_worker_cost",
        )
    for name in ("load_seconds", "inference_seconds", "total_seconds"):
        value = getattr(cost, name)
        _require(
            type(value) in (int, float)
            and math.isfinite(value)
            and value >= 0,
            "invalid_worker_cost",
        )
    _require(
        cost.total_seconds + 1e-6 >= cost.load_seconds + cost.inference_seconds,
        "invalid_worker_cost",
    )
    status = report["status"]
    partial = report["partial"]
    _require(
        type(status) is str
        and status in {"complete", "partial"}
        and type(partial) is bool,
        "invalid_worker_partial_state",
    )
    assert isinstance(status, str)
    assert isinstance(partial, bool)
    status_value = cast(Literal["complete", "partial"], status)
    _require(
        status == ("partial" if partial else "complete"),
        "invalid_worker_partial_state",
    )
    return SemanticGeneration(tuple(embeddings), cost, status_value, partial)


def read_worker_archive_inputs(raw: bytes) -> dict[str, bytes]:
    """Return inert inputs using the unchanged worker archive grammar and caps."""
    return _archive_files(raw)[1]


__all__ = ["QueryEmbedding", "VerifiedWorkerResponse", "read_worker_archive_inputs"]

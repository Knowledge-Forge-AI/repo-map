"""Verify request, report, journal and source-archive receipt identities."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
import math

from retrieval_semantic_generator_kernel import SemanticMode
from retrieval_semantic_generator_output_receipt import (
    _EMPTY_JOURNAL_SHA256,
    _archive_files,
    _digest,
    _digest_field,
    _journal_object,
    _parse_generation,
    _require,
    _response_identity,
    VerifiedWorkerResponse,
)
from retrieval_semantic_generator_worker import (
    REQUEST_SCHEMA,
    RESPONSE_SCHEMA,
    WorkerRequestError,
    parse_worker_request,
)
from retrieval_semantic_provenance import RepresentationValidationError


def parse_verified_worker_response(
    *,
    request_raw: bytes,
    report_raw: bytes,
    terminal_raw: bytes,
    declaration_raw: bytes,
    source_manifest_raw: bytes,
    sources_archive_raw: bytes,
    expected_controller_admission_sha256: str,
    expected_source_closure: Mapping[str, str],
) -> VerifiedWorkerResponse:
    """Verify the complete immutable receipt before any vector is sealed."""
    try:
        request, request_records = parse_worker_request(request_raw)
    except WorkerRequestError as exc:
        raise RepresentationValidationError(
            "invalid_worker_request", "worker request refused"
        ) from exc
    declaration = _journal_object(declaration_raw, "declaration")
    manifest = _journal_object(source_manifest_raw, "source_manifest")
    terminal = _journal_object(terminal_raw, "terminal")
    report = _journal_object(report_raw, "report")
    _require(
        set(declaration)
        == {
            "attempt_id",
            "schema",
            "request_sha256",
            "controller_admission_sha256",
            "candidate_closure_digests",
            "public_input_trust",
            "input_identity",
            "representation_report_identity",
            "publication_identity",
            "artifact_profile_identity",
        },
        "invalid_worker_declaration",
    )
    _require(
        declaration["schema"] == REQUEST_SCHEMA
        and declaration["public_input_trust"]
        == "external evaluator current-store admission required",
        "invalid_worker_declaration",
    )
    _require(
        set(manifest)
        == {"archive_sha256", "input_files", "schema_version", "source_files"},
        "invalid_worker_manifest",
    )
    _require(
        manifest["schema_version"] == "cloe-retrieval-attempt-source-manifest-v1",
        "invalid_worker_manifest",
    )
    _require(
        set(terminal)
        == {
            "declaration_sha256",
            "journal_sha256",
            "observation_count",
            "report_sha256",
            "source_manifest_sha256",
            "sources_archive_sha256",
            "status",
        },
        "invalid_worker_terminal",
    )
    _require(
        terminal["status"] == "completed"
        and terminal["observation_count"] == 0
        and terminal["journal_sha256"] == _EMPTY_JOURNAL_SHA256,
        "worker_receipt_not_complete",
    )
    _require(
        set(report)
        == {
            "schema",
            "request_sha256",
            "controller_admission_sha256",
            "input_identity",
            "representation_report_identity",
            "publication_identity",
            "artifact_profile_identity",
            "status",
            "partial",
            "record_count",
            "embedding_count",
            "document_count",
            "query_count",
            "embeddings",
            "cost",
            "elapsed_seconds",
            "claim",
        },
        "invalid_worker_report",
    )
    _require(
        report["schema"] == RESPONSE_SCHEMA
        and report["claim"]
        == "fixed CPU component only; no learned quality, native ANN or production acceptance",
        "invalid_worker_report",
    )
    request_sha256 = _digest(request_raw)
    report_sha256 = _digest(report_raw)
    terminal_sha256 = _digest(terminal_raw)
    declaration_sha256 = _digest(declaration_raw)
    manifest_sha256 = _digest(source_manifest_raw)
    archive_sha256 = _digest(sources_archive_raw)
    _require(
        declaration["request_sha256"] == request_sha256
        and report["request_sha256"] == request_sha256,
        "worker_request_identity_mismatch",
    )
    _require(
        terminal["declaration_sha256"] == declaration_sha256
        and terminal["report_sha256"] == report_sha256,
        "worker_receipt_hash_mismatch",
    )
    _require(
        terminal["source_manifest_sha256"] == manifest_sha256
        and terminal["sources_archive_sha256"] == archive_sha256,
        "worker_receipt_hash_mismatch",
    )
    _require(
        manifest["archive_sha256"] == archive_sha256,
        "worker_receipt_hash_mismatch",
    )
    admission_sha256 = _digest_field(
        expected_controller_admission_sha256,
        "invalid_worker_admission_identity",
    )
    for value in (
        declaration["controller_admission_sha256"],
        report["controller_admission_sha256"],
    ):
        _require(value == admission_sha256, "worker_admission_identity_mismatch")
    for key in (
        "input_identity",
        "representation_report_identity",
        "publication_identity",
        "artifact_profile_identity",
    ):
        expected = _digest_field(request[key], "invalid_worker_request_identity")
        _require(
            declaration[key] == expected and report[key] == expected,
            "worker_request_identity_mismatch",
        )
    _require(
        declaration["attempt_id"] == request["attempt_id"],
        "worker_attempt_identity_mismatch",
    )
    source_decl = declaration["candidate_closure_digests"]
    source_manifest = manifest["source_files"]
    _require(
        isinstance(source_decl, dict)
        and isinstance(source_manifest, dict)
        and isinstance(expected_source_closure, Mapping),
        "invalid_worker_source_closure",
    )
    assert isinstance(source_decl, dict)
    assert isinstance(source_manifest, dict)
    assert isinstance(expected_source_closure, Mapping)
    for source_map in (source_decl, source_manifest, expected_source_closure):
        _require(
            all(
                type(name) is str
                and name
                and "\\" not in name
                and not any(part in {"", ".", ".."} for part in name.split("/"))
                for name in source_map
            ),
            "invalid_worker_source_closure",
        )
    closure = {
        name: _digest_field(value, "invalid_worker_source_closure")
        for name, value in sorted(source_decl.items())
    }
    manifest_closure = {
        name: _digest_field(value, "invalid_worker_source_closure")
        for name, value in sorted(source_manifest.items())
    }
    expected_closure = {
        name: _digest_field(value, "invalid_worker_source_closure")
        for name, value in sorted(expected_source_closure.items())
    }
    _require(
        closure == manifest_closure == expected_closure,
        "worker_source_closure_mismatch",
    )
    input_files = manifest["input_files"]
    _require(
        isinstance(input_files, dict)
        and set(input_files) == {"request.json", "admission.json"},
        "invalid_worker_manifest",
    )
    assert isinstance(input_files, dict)
    _require(
        input_files["request.json"] == request_sha256
        and input_files["admission.json"] == admission_sha256,
        "worker_input_archive_mismatch",
    )
    archive_sources, archive_inputs = _archive_files(sources_archive_raw)
    _require(
        {name: _digest(data) for name, data in sorted(archive_sources.items())}
        == closure,
        "worker_source_archive_mismatch",
    )
    _require(
        set(archive_inputs) == {"request.json", "admission.json"},
        "worker_input_archive_mismatch",
    )
    _require(
        _digest(archive_inputs["request.json"]) == request_sha256
        and _digest(archive_inputs["admission.json"]) == admission_sha256
        and archive_inputs["request.json"] == request_raw,
        "worker_input_archive_mismatch",
    )
    generation = _parse_generation(report, request_records)
    record_count = report["record_count"]
    embedding_count = report["embedding_count"]
    document_count = report["document_count"]
    query_count = report["query_count"]
    _require(
        all(
            type(value) is int and value >= 0
            for value in (record_count, embedding_count, document_count, query_count)
        ),
        "invalid_worker_counts",
    )
    assert type(record_count) is int
    assert type(embedding_count) is int
    assert type(document_count) is int
    assert type(query_count) is int
    _require(
        (record_count, embedding_count)
        == (len(request_records), len(generation.embeddings)),
        "worker_count_mismatch",
    )
    _require(
        tuple((item.record_id, item.mode) for item in generation.embeddings)
        == tuple((item.record_id, item.mode) for item in request_records),
        "worker_generation_identity_mismatch",
    )
    _require(
        (document_count, query_count)
        == (
            sum(item.mode is SemanticMode.DOCUMENT for item in generation.embeddings),
            sum(item.mode is SemanticMode.QUERY for item in generation.embeddings),
        ),
        "worker_count_mismatch",
    )
    elapsed_seconds = report["elapsed_seconds"]
    _require(type(elapsed_seconds) in (int, float), "invalid_worker_elapsed")
    assert isinstance(elapsed_seconds, (int, float))
    _require(
        math.isfinite(elapsed_seconds) and elapsed_seconds >= 0,
        "invalid_worker_elapsed",
    )
    response = VerifiedWorkerResponse(
        str(request["attempt_id"]),
        request_records,
        request_sha256,
        report_sha256,
        terminal_sha256,
        declaration_sha256,
        manifest_sha256,
        archive_sha256,
        tuple(sorted(closure.items())),
        admission_sha256,
        str(request["input_identity"]),
        str(request["representation_report_identity"]),
        str(request["publication_identity"]),
        str(request["artifact_profile_identity"]),
        record_count,
        embedding_count,
        document_count,
        query_count,
        generation,
        "completed",
    )
    return replace(response, _sealed_identity=_response_identity(response))


__all__ = ["parse_verified_worker_response"]

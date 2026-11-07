"""Run the bounded offline semantic component after protocol admission."""

from __future__ import annotations

import argparse
from dataclasses import asdict
from pathlib import Path
import time

from retrieval_semantic_generator_artifacts import (
    ArtifactVerificationError,
    verify_artifact_directory,
)
from retrieval_semantic_generator_kernel import (
    SemanticGeneratorKernel,
    SemanticKernelError,
    SemanticKernelProfile,
    SemanticMode,
)
from retrieval_semantic_generator_runtime import RuntimeFactory
from retrieval_semantic_generator_worker_protocol import (
    CONTROLLER_ADMISSION_SCHEMA,
    MAX_ADMISSION_BYTES,
    MAX_REQUEST_BYTES,
    PhaseControllerAdmission,
    REQUEST_SCHEMA,
    RESPONSE_SCHEMA,
    WORKER_SOURCE_FILES,
    WorkerRequestError,
    _admit,
    _declaration,
    _digest,
    _finish_failure,
    _fixed_path,
    _read_regular,
    _require_digest,
    _source_digests,
    _source_files,
    parse_controller_admission,
    parse_worker_request,
)


def run_worker(
    request_path: Path,
    artifact_root: Path,
    output_root: Path,
    *,
    admission_path: Path,
    expected_admission_sha256: str,
    runtime_factory: RuntimeFactory | None = None,
) -> None:
    """Publish one complete journaled response or one bounded failed receipt."""
    output_root = _fixed_path(
        output_root, directory=True, code="output_root_unavailable"
    )
    raw = _read_regular(request_path, MAX_REQUEST_BYTES)
    request, records = parse_worker_request(raw)
    request_sha256 = _digest(raw)
    expected_admission = _require_digest(
        expected_admission_sha256, "invalid_admission_identity"
    )

    source_files: dict[str, bytes] = {}
    source_error: WorkerRequestError | None = None
    try:
        source_files = _source_files()
    except WorkerRequestError as exc:
        source_error = exc
    source_digests = _source_digests(source_files)

    admission_raw = b""
    admission_error: WorkerRequestError | None = None
    admission: PhaseControllerAdmission | None = None
    try:
        admission_raw = _read_regular(admission_path, MAX_ADMISSION_BYTES)
        if source_error is None:
            admission = parse_controller_admission(
                admission_raw,
                expected_admission_sha256=expected_admission,
                request=request,
                request_sha256=request_sha256,
                source_closure=source_digests,
            )
    except WorkerRequestError as exc:
        admission_error = exc

    declaration = _declaration(
        request,
        request_sha256,
        expected_admission,
        source_digests,
    )
    journal = _admit(output_root, declaration, source_files, raw, admission_raw)
    if source_error is not None:
        _finish_failure(journal, request, declaration, source_error.code)
        raise source_error
    if admission_error is not None or admission is None:
        code = (
            admission_error.code
            if admission_error is not None
            else "controller_admission_required"
        )
        _finish_failure(journal, request, declaration, code)
        raise WorkerRequestError(code)

    started = time.monotonic()
    try:
        profile = verify_artifact_directory(artifact_root)
        if profile.source_identity_sha256 != request["artifact_profile_identity"]:
            raise WorkerRequestError("artifact_profile_identity_mismatch")
        kernel_profile = SemanticKernelProfile(artifact_root / "model")
        if runtime_factory is None:
            kernel = SemanticGeneratorKernel(kernel_profile)
        else:
            kernel = SemanticGeneratorKernel(
                kernel_profile, runtime_factory=runtime_factory
            )
        generation = kernel.generate(records)
        document_count = sum(
            item.mode is SemanticMode.DOCUMENT for item in generation.embeddings
        )
        query_count = sum(
            item.mode is SemanticMode.QUERY for item in generation.embeddings
        )
        report: dict[str, object] = {
            "schema": RESPONSE_SCHEMA,
            "request_sha256": request_sha256,
            "controller_admission_sha256": admission.admission_sha256,
            "input_identity": request["input_identity"],
            "representation_report_identity": request["representation_report_identity"],
            "publication_identity": request["publication_identity"],
            "artifact_profile_identity": request["artifact_profile_identity"],
            "status": generation.status,
            "partial": generation.partial,
            "record_count": len(records),
            "embedding_count": len(generation.embeddings),
            "document_count": document_count,
            "query_count": query_count,
            "embeddings": [
                dict(asdict(item), mode=item.mode.value)
                for item in generation.embeddings
            ],
            "cost": asdict(generation.cost),
            "elapsed_seconds": time.monotonic() - started,
            "claim": "fixed CPU component only; no learned quality, native ANN or production acceptance",
        }
        try:
            journal.finish("completed", report)
        except (OSError, ValueError, RuntimeError) as exc:
            raise WorkerRequestError("attempt_terminal_write_failed") from exc
    except ArtifactVerificationError as exc:
        _finish_failure(journal, request, declaration, exc.code)
        raise WorkerRequestError(exc.code) from None
    except Exception as exc:
        code = (
            exc.code
            if isinstance(exc, (WorkerRequestError, SemanticKernelError))
            else "component_execution_failed"
        )
        _finish_failure(journal, request, declaration, code)
        raise WorkerRequestError(code) from None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", required=True, type=Path)
    parser.add_argument("--artifacts", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--admission", required=True, type=Path)
    parser.add_argument("--admission-sha256", required=True)
    args = parser.parse_args()
    try:
        run_worker(
            args.request,
            args.artifacts,
            args.output,
            admission_path=args.admission,
            expected_admission_sha256=args.admission_sha256,
        )
    except (WorkerRequestError, OSError):
        print("semantic component refused; inspect the owned bounded failure receipt")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "CONTROLLER_ADMISSION_SCHEMA",
    "MAX_ADMISSION_BYTES",
    "MAX_REQUEST_BYTES",
    "PhaseControllerAdmission",
    "REQUEST_SCHEMA",
    "RESPONSE_SCHEMA",
    "RuntimeFactory",
    "WORKER_SOURCE_FILES",
    "WorkerRequestError",
    "parse_controller_admission",
    "parse_worker_request",
    "run_worker",
]
